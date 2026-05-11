"""SB 254-effective tract layer — Delaware-state interpretation of §Q6.

Per methodology v0.2.0 §Q6, a tract is "SB 254 effective" when *both*:

  1. ≥50% of the tract's population lives more than:
       - 0.5 mi from any food resource (urban tracts)
       - 10 mi from any food resource (nonurban tracts)
     The 50% threshold is the dashboard's documented choice (see Q6); it
     is exposed as `sb254_population_threshold` in parameters.yaml.

  2. The tract meets the low-income criterion (USDA LILA-compatible):
       - poverty rate >=20% OR
       - median family income <=80% of the Delaware state-median MFI

The food-resource universe is the merged set produced by
etl.transforms.merge_food_resources (SNAP retailers + farmers markets +
DCFFP/DGI grantees deduped within 30m).

Population-share-by-distance is computed at the block-group level: every
block group inside a tract carries a population count + centroid; the
tract's "share of pop > distance" is

    sum(bg.pop for bg in tract.block_groups if min_distance(bg, resources) > threshold)
    -----------------------------------------------------------------------------------
                          sum(bg.pop for bg in tract.block_groups)

This is the simpler proxy for "≥50% of population lives more than X mi"
that the methodology spec describes; per the methodology, it could be
refined to a population-density-weighted area calculation later, but
that requires data the v1 ETL doesn't pull. The diagnostic fields on
the output carry the population numerator + denominator so downstream
consumers can apply different rules without rerunning the geocode.

This module is pure Python (haversine math) — no geo stack. Tests run
unconditionally.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Constants — methodology v0.2.0 §Q6 defaults
# ---------------------------------------------------------------------------


DEFAULT_POPULATION_THRESHOLD = 0.5       # >50% pop must fail the access test
DEFAULT_URBAN_DISTANCE_MI = 0.5
DEFAULT_NONURBAN_DISTANCE_MI = 10.0
DEFAULT_POVERTY_THRESHOLD = 0.20         # tract poverty rate >=20%
DEFAULT_MFI_RATIO_THRESHOLD = 0.80       # tract MFI <=80% of state median

MILES_TO_METERS = 1609.344

URBANICITY_URBAN = "urban"
URBANICITY_NONURBAN = "nonurban"


# ---------------------------------------------------------------------------
# I/O types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BlockGroup:
    """A single Census block group inside a tract.

    `centroid_lat`/`centroid_lon` are the BG's population-weighted
    centroid (Census publishes these in TIGER). `population` is the
    BG-level total population from ACS B01003_001E.
    """

    bg_geoid: str
    centroid_lat: float
    centroid_lon: float
    population: int


@dataclasses.dataclass(frozen=True)
class TractInput:
    """Per-tract inputs to the SB 254-effective classification.

    `urbanicity` is "urban" or "nonurban" (Census urban-area
    classification). `poverty_rate` is a 0..1 fraction (i.e., 0.20 ==
    20%). `mfi` is the tract's median family income in dollars from
    ACS B19113_001E. `block_groups` is the list of BGs whose geometry
    falls inside this tract.
    """

    tract_geoid: str
    urbanicity: str
    poverty_rate: Optional[float]
    mfi: Optional[float]
    block_groups: tuple[BlockGroup, ...]


@dataclasses.dataclass(frozen=True)
class FoodResourcePoint:
    """The minimal interface this transform needs from a food resource."""

    lat: float
    lon: float


@dataclasses.dataclass
class SB254Tract:
    """Output: SB 254-effective classification + diagnostics for one tract."""

    tract_geoid: str
    sb254_effective: bool
    urbanicity: str
    distance_threshold_mi: float
    population_total: int
    population_underserved: int
    underserved_share: float        # 0..1
    low_income: bool
    low_income_reason: Optional[str]  # "poverty>=0.20" or "mfi_ratio<=0.80" or None
    poverty_rate: Optional[float]
    mfi: Optional[float]
    mfi_ratio_to_state: Optional[float]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_tracts(
    tracts: Iterable[TractInput],
    food_resources: Iterable[FoodResourcePoint],
    *,
    state_mfi_median: float,
    population_threshold: float = DEFAULT_POPULATION_THRESHOLD,
    urban_distance_mi: float = DEFAULT_URBAN_DISTANCE_MI,
    nonurban_distance_mi: float = DEFAULT_NONURBAN_DISTANCE_MI,
    poverty_threshold: float = DEFAULT_POVERTY_THRESHOLD,
    mfi_ratio_threshold: float = DEFAULT_MFI_RATIO_THRESHOLD,
) -> list[SB254Tract]:
    """Classify each tract as SB 254-effective or not, with diagnostics.

    `state_mfi_median` must be supplied by the caller (computed upstream
    from the full ACS pull); the transform doesn't compute it because it
    operates only on the tracts it's been handed (which may be a subset
    for testing).
    """
    resource_list = list(food_resources)
    out: list[SB254Tract] = []

    for t in tracts:
        threshold_mi = (
            urban_distance_mi if t.urbanicity == URBANICITY_URBAN
            else nonurban_distance_mi
        )
        threshold_m = threshold_mi * MILES_TO_METERS

        pop_total = sum(bg.population for bg in t.block_groups)
        pop_underserved = 0
        for bg in t.block_groups:
            min_d = _min_distance_m(bg.centroid_lat, bg.centroid_lon, resource_list)
            if min_d is None or min_d > threshold_m:
                pop_underserved += bg.population

        if pop_total > 0:
            underserved_share = pop_underserved / pop_total
        else:
            underserved_share = 0.0

        access_fails = underserved_share > population_threshold

        low_income, low_income_reason = _classify_low_income(
            t.poverty_rate, t.mfi, state_mfi_median,
            poverty_threshold, mfi_ratio_threshold,
        )
        mfi_ratio = (t.mfi / state_mfi_median) if (t.mfi is not None and state_mfi_median > 0) else None

        out.append(
            SB254Tract(
                tract_geoid=t.tract_geoid,
                sb254_effective=access_fails and low_income,
                urbanicity=t.urbanicity,
                distance_threshold_mi=threshold_mi,
                population_total=pop_total,
                population_underserved=pop_underserved,
                underserved_share=underserved_share,
                low_income=low_income,
                low_income_reason=low_income_reason,
                poverty_rate=t.poverty_rate,
                mfi=t.mfi,
                mfi_ratio_to_state=mfi_ratio,
            )
        )

    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _classify_low_income(
    poverty_rate: Optional[float],
    mfi: Optional[float],
    state_mfi_median: float,
    poverty_threshold: float,
    mfi_ratio_threshold: float,
) -> tuple[bool, Optional[str]]:
    """Apply the USDA LILA-compatible low-income test (poverty OR MFI rule)."""
    if poverty_rate is not None and poverty_rate >= poverty_threshold:
        return True, f"poverty>={poverty_threshold:.2f}"
    if mfi is not None and state_mfi_median > 0:
        ratio = mfi / state_mfi_median
        if ratio <= mfi_ratio_threshold:
            return True, f"mfi_ratio<={mfi_ratio_threshold:.2f}"
    return False, None


def _min_distance_m(
    lat: float, lon: float, resources: list[FoodResourcePoint]
) -> Optional[float]:
    """Distance in meters to the nearest resource, or None if no resources."""
    if not resources:
        return None
    best = float("inf")
    for r in resources:
        d = _haversine_m(lat, lon, r.lat, r.lon)
        if d < best:
            best = d
    return best


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
