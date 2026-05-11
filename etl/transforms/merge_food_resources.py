"""Food-resource universe merge — dedupe SNAP + farmers markets + DGI/DCFFP grantees.

Per design brief §"Data flow" step [3] and methodology v0.2.0 §Q6: the SB
254 statutory "food resource" universe is broader than USDA's
supermarket-only set. The pipeline merges the following sources into one
deduplicated point set:

  - USDA SNAP Retailer Locator       (supermarkets, corner stores, etc.)
  - DE Department of Agriculture     (farmers-market registry)
  - DE Council on Farm & Food Policy (grantees)
  - DGI grantees (geocoded)          (the program-of-record points)

Dedupe rule (per design brief): two records merge when *both*
  (a) geographic proximity: haversine distance < tie-break-distance-m
      (default 30m, the design-brief value)
  (b) name similarity: token-set Jaccard >= name_similarity_threshold
      (default 0.5)

When records merge, the kept record carries:
  - lat/lon from the first contributor (deterministic — input order)
  - a `sources` set listing every contributor (e.g., {"usda-snap", "dgi"})
  - the longest non-empty `name` and `address` seen across contributors
  - the merged set of categories (e.g., {"supermarket"} from SNAP +
    {"corner-store"} from DGI = both)

The output is the "food resource" set used by SB 254-effective tract
computation (etl.transforms.sb254_effective). It is also the dashboard's
SNAP-retailer layer in its merged form.

This module is pure Python (haversine math + string normalization) — no
geo stack needed. Tests run unconditionally.
"""

from __future__ import annotations

import dataclasses
import math
import re
from typing import Iterable, Optional


DEFAULT_DEDUPE_DISTANCE_M = 30.0
DEFAULT_NAME_SIMILARITY_THRESHOLD = 0.5

# Business suffixes that don't help distinguish two food resources. We
# strip them before comparing names so "Acme Market" and "Acme Market Inc"
# merge as the same place.
NAME_NOISE_TOKENS = frozenset(
    {
        "inc", "llc", "ltd", "corp", "co", "company",
        "the", "and", "&",
        "store", "market", "mart", "shop", "grocery",
        "food", "foods", "grocer", "supermarket",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# I/O types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FoodResource:
    """A single food-resource record from one upstream source.

    `source` is the puller name ("usda-snap", "de-ag-farmers-markets",
    "dcffp-grantees", "dgi-grantees"). `category` is one of the
    methodology v0.2.0 enum values.
    """

    source: str
    name: str
    lat: float
    lon: float
    category: str
    address: Optional[str] = None
    external_id: Optional[str] = None


@dataclasses.dataclass
class MergedFoodResource:
    """A merged food-resource record after cross-source dedupe."""

    name: str
    lat: float
    lon: float
    categories: list[str]
    sources: list[str]
    address: Optional[str]
    external_ids: list[str]
    contributor_count: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def merge_food_resources(
    resources: Iterable[FoodResource],
    *,
    dedupe_distance_m: float = DEFAULT_DEDUPE_DISTANCE_M,
    name_similarity_threshold: float = DEFAULT_NAME_SIMILARITY_THRESHOLD,
) -> list[MergedFoodResource]:
    """Dedupe a heterogeneous list of food-resource records.

    Input order is significant: the first record in a duplicate cluster
    keeps its lat/lon; subsequent records contribute only their source +
    metadata. This matches the design brief's deterministic-merge rule.

    Returns a list of MergedFoodResource sorted by (lat, lon, name) so
    output is stable across runs.
    """
    merged: list[MergedFoodResource] = []
    # Per-merged-record token cache, parallel to `merged` by index.
    tokens_cache: list[frozenset[str]] = []

    for r in resources:
        r_tokens = _name_tokens(r.name)

        # Look for an existing merged record this resource collides with.
        match_idx = _find_match(
            r, r_tokens, merged, tokens_cache,
            dedupe_distance_m, name_similarity_threshold,
        )

        if match_idx is None:
            merged.append(
                MergedFoodResource(
                    name=r.name,
                    lat=r.lat,
                    lon=r.lon,
                    categories=[r.category],
                    sources=[r.source],
                    address=r.address,
                    external_ids=[r.external_id] if r.external_id else [],
                    contributor_count=1,
                )
            )
            tokens_cache.append(r_tokens)
            continue

        # Merge into the existing record.
        existing = merged[match_idx]
        if r.source not in existing.sources:
            existing.sources.append(r.source)
        if r.category not in existing.categories:
            existing.categories.append(r.category)
        if r.external_id and r.external_id not in existing.external_ids:
            existing.external_ids.append(r.external_id)
        # Prefer the longer / non-empty address when one is more specific.
        if r.address and (not existing.address or len(r.address) > len(existing.address)):
            existing.address = r.address
        # Prefer the longer name (more specific) but stable: only replace
        # if strictly longer to avoid flapping on ties.
        if len(r.name) > len(existing.name):
            existing.name = r.name
            tokens_cache[match_idx] = _name_tokens(r.name)
        existing.contributor_count += 1

    merged.sort(key=lambda m: (round(m.lat, 6), round(m.lon, 6), m.name))
    return merged


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _find_match(
    r: FoodResource,
    r_tokens: frozenset[str],
    merged: list[MergedFoodResource],
    tokens_cache: list[frozenset[str]],
    dedupe_distance_m: float,
    name_similarity_threshold: float,
) -> Optional[int]:
    """Find the first merged-list index this resource collides with, or None."""
    for idx, existing in enumerate(merged):
        d = _haversine_m(r.lat, r.lon, existing.lat, existing.lon)
        if d > dedupe_distance_m:
            continue
        sim = _jaccard(r_tokens, tokens_cache[idx])
        if sim >= name_similarity_threshold:
            return idx
    return None


def _name_tokens(name: str) -> frozenset[str]:
    """Tokenize + denoise a business name for similarity comparison."""
    norm = _NON_ALNUM.sub(" ", name.lower()).strip()
    tokens = {t for t in norm.split() if t and t not in NAME_NOISE_TOKENS}
    return frozenset(tokens)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-set Jaccard similarity. Two empty sets count as similar (1.0)."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    earth_radius_m = 6_371_008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_m * c
