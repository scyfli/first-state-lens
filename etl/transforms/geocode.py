"""DGI grantee geocoding transform — Census primary, Nominatim cross-check.

Implements methodology v0.2.0 §Q5: every DGI grantee storefront address is
geocoded via the Census Geocoder. Nominatim is queried as a cross-check.
The two results are compared and a `geocoding_confidence` flag is assigned:

  high   : both providers returned a result AND lat/lon agree within
           geocoder_tie_break_distance_m (parameters.yaml; default 200m)
  medium : both providers returned a result but the lat/lon disagree
           (>tie-break distance). Flag for manual review.
  manual : at least one provider failed to return a result. Manual
           assignment required via etl/manual-reviews.yaml.
  pending-disbursement : grant exists but storefront not yet announced
           (Cycle 5 placeholder). Not geocoded; skipped here.

For Wilmington corner-store / specialty-grocer grantees in zip codes
19801-19810 (per methodology Q5), medium/manual confidence triggers an
entry in data-quality-flags.csv as `pending-manual-review`.

The transform is pure: takes a list of grantee records + a parameters
bundle, returns the geocoded list + the data-quality-flags rows. No
disk I/O happens here (the caller writes the outputs); the geocoders
themselves use etl/cache/geocode/ via etl.lib.geocode.

S+3 will compose this with apportionment + SB 254-effective tract logic.
S+4 wires it into the dashboard via the datapackage writer.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Iterable, Optional

from etl.lib.geocode import (
    GeocodeResult,
    geocode_census,
    geocode_nominatim,
)


# ---------------------------------------------------------------------------
# Confidence levels — match the methodology v0.2.0 enum
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_MANUAL = "manual"
CONFIDENCE_PENDING = "pending-disbursement"

WILMINGTON_ZIP_LOW = 19801
WILMINGTON_ZIP_HIGH = 19810

CORNER_STORE_CATEGORIES = {"corner-store", "specialty-grocer"}


# ---------------------------------------------------------------------------
# Input / output types
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GranteeInput:
    """A single DGI grantee record before geocoding.

    `storefront_address` is the canonical address string from the DSB
    roster. `category` is one of the methodology v0.2.0 enum values.
    `zip_code` is optional; if absent we'll parse it from the address.
    """

    cycle: int
    grantee: str
    amount_usd: float
    category: str
    storefront_address: Optional[str]
    zip_code: Optional[str] = None
    awarded_date: Optional[str] = None

    def is_wilmington_corner_store(self) -> bool:
        if self.category not in CORNER_STORE_CATEGORIES:
            return False
        zip_str = self.zip_code or _extract_zip(self.storefront_address)
        if not zip_str:
            return False
        try:
            return WILMINGTON_ZIP_LOW <= int(zip_str) <= WILMINGTON_ZIP_HIGH
        except ValueError:
            return False


@dataclasses.dataclass
class GeocodedGrantee:
    """A DGI grantee after Census + Nominatim cross-check."""

    cycle: int
    grantee: str
    amount_usd: float
    category: str
    storefront_address: Optional[str]
    zip_code: Optional[str]
    awarded_date: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    tract_geoid: Optional[str]
    county_fips: Optional[str]
    state_fips: Optional[str]
    geocoding_confidence: str
    wilmington_manual_reviewed: bool  # always False at this stage; set by apply_manual_reviews
    census_matched_address: Optional[str]
    nominatim_matched_address: Optional[str]
    distance_disagreement_m: Optional[float]


@dataclasses.dataclass
class DataQualityFlag:
    """A single data-quality flag row."""

    cycle: int
    grantee: str
    flag: str  # e.g. "pending-manual-review", "requires-manual-tract-assignment"
    note: str


# ---------------------------------------------------------------------------
# Geocode protocol — injectable for tests
# ---------------------------------------------------------------------------


class GeocoderPair:
    """Encapsulates the (Census, Nominatim) pair so tests can inject mocks."""

    def __init__(
        self,
        census_fn=geocode_census,
        nominatim_fn=geocode_nominatim,
        *,
        census_api_key: Optional[str] = None,
    ) -> None:
        self._census_fn = census_fn
        self._nominatim_fn = nominatim_fn
        self._census_api_key = census_api_key

    def census(self, address: str) -> GeocodeResult:
        if self._census_api_key:
            return self._census_fn(address, api_key=self._census_api_key)
        return self._census_fn(address)

    def nominatim(self, address: str) -> GeocodeResult:
        return self._nominatim_fn(address)


# ---------------------------------------------------------------------------
# Main transform entry point
# ---------------------------------------------------------------------------


def geocode_grantees(
    grantees: Iterable[GranteeInput],
    *,
    geocoders: Optional[GeocoderPair] = None,
    tie_break_distance_m: float = 200.0,
    skip_nominatim_for_pending: bool = True,
) -> tuple[list[GeocodedGrantee], list[DataQualityFlag]]:
    """Geocode every grantee; return (records, flags).

    `geocoders` defaults to live Census + Nominatim. Inject a GeocoderPair
    with mocked functions for tests.
    """
    geocoders = geocoders or GeocoderPair()
    out_records: list[GeocodedGrantee] = []
    out_flags: list[DataQualityFlag] = []

    for g in grantees:
        # Cycle 5 placeholder: no address yet, no geocoding.
        if g.storefront_address is None or g.storefront_address.strip() == "":
            out_records.append(
                _make_pending_record(g)
            )
            continue

        census = geocoders.census(g.storefront_address)
        nominatim = geocoders.nominatim(g.storefront_address)

        confidence, distance_m = _classify_confidence(
            census, nominatim, tie_break_distance_m
        )

        # Choose authoritative lat/lon: prefer Census (US-specific +
        # returns tract directly). Fall back to Nominatim if Census failed.
        if census.found:
            lat, lon = census.lat, census.lon
            tract_geoid = census.tract_geoid
            county_fips = census.county_fips
            state_fips = census.state_fips
        elif nominatim.found:
            lat, lon = nominatim.lat, nominatim.lon
            tract_geoid = None
            county_fips = None
            state_fips = None
        else:
            lat, lon = None, None
            tract_geoid = None
            county_fips = None
            state_fips = None

        record = GeocodedGrantee(
            cycle=g.cycle,
            grantee=g.grantee,
            amount_usd=g.amount_usd,
            category=g.category,
            storefront_address=g.storefront_address,
            zip_code=g.zip_code or _extract_zip(g.storefront_address),
            awarded_date=g.awarded_date,
            lat=lat,
            lon=lon,
            tract_geoid=tract_geoid,
            county_fips=county_fips,
            state_fips=state_fips,
            geocoding_confidence=confidence,
            wilmington_manual_reviewed=False,  # set by apply_manual_reviews
            census_matched_address=census.matched_address if census.found else None,
            nominatim_matched_address=nominatim.matched_address if nominatim.found else None,
            distance_disagreement_m=distance_m,
        )
        out_records.append(record)

        # Data-quality flags: Wilmington corner-store branching.
        if confidence in (CONFIDENCE_MEDIUM, CONFIDENCE_MANUAL) and g.is_wilmington_corner_store():
            if confidence == CONFIDENCE_MEDIUM:
                out_flags.append(
                    DataQualityFlag(
                        cycle=g.cycle,
                        grantee=g.grantee,
                        flag="pending-manual-review",
                        note=(
                            f"Census + Nominatim disagree by "
                            f"{distance_m:.0f}m (tie-break {tie_break_distance_m:.0f}m). "
                            f"Wilmington corner-store / specialty-grocer; "
                            f"requires manual tract confirmation per methodology Q5."
                        ),
                    )
                )
            else:  # manual
                out_flags.append(
                    DataQualityFlag(
                        cycle=g.cycle,
                        grantee=g.grantee,
                        flag="requires-manual-tract-assignment",
                        note=(
                            "At least one geocoder failed; manual tract "
                            "assignment required for Wilmington corner-store "
                            "/ specialty-grocer per methodology Q5."
                        ),
                    )
                )

    return out_records, out_flags


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _make_pending_record(g: GranteeInput) -> GeocodedGrantee:
    return GeocodedGrantee(
        cycle=g.cycle,
        grantee=g.grantee,
        amount_usd=g.amount_usd,
        category=g.category,
        storefront_address=g.storefront_address,
        zip_code=g.zip_code,
        awarded_date=g.awarded_date,
        lat=None,
        lon=None,
        tract_geoid=None,
        county_fips=None,
        state_fips=None,
        geocoding_confidence=CONFIDENCE_PENDING,
        wilmington_manual_reviewed=False,
        census_matched_address=None,
        nominatim_matched_address=None,
        distance_disagreement_m=None,
    )


def _classify_confidence(
    census: GeocodeResult,
    nominatim: GeocodeResult,
    tie_break_distance_m: float,
) -> tuple[str, Optional[float]]:
    """Return (confidence, lat/lon-disagreement-distance-meters)."""
    if not census.found or not nominatim.found:
        return CONFIDENCE_MANUAL, None

    if (
        census.lat is None
        or census.lon is None
        or nominatim.lat is None
        or nominatim.lon is None
    ):
        return CONFIDENCE_MANUAL, None

    distance_m = _haversine_m(census.lat, census.lon, nominatim.lat, nominatim.lon)
    if distance_m <= tie_break_distance_m:
        return CONFIDENCE_HIGH, distance_m
    return CONFIDENCE_MEDIUM, distance_m


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


def _extract_zip(address: Optional[str]) -> Optional[str]:
    """Best-effort 5-digit zip extraction from a free-form address."""
    if not address:
        return None
    import re

    m = re.search(r"\b(\d{5})(?:-\d{4})?\b", address)
    return m.group(1) if m else None
