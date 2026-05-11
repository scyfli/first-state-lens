"""Tests for etl.transforms.sb254_effective."""

from __future__ import annotations

from etl.transforms.sb254_effective import (
    BlockGroup,
    FoodResourcePoint,
    TractInput,
    URBANICITY_NONURBAN,
    URBANICITY_URBAN,
    classify_tracts,
)


# Approximate centroid for a Wilmington-ish reference point.
WILMINGTON_LAT = 39.7400
WILMINGTON_LON = -75.5500
# A "far" point ~30km north — well outside any urban access window.
NORTH_FAR_LAT = 40.0100
NORTH_FAR_LON = -75.5500


def _bg(geoid: str, lat: float, lon: float, pop: int) -> BlockGroup:
    return BlockGroup(bg_geoid=geoid, centroid_lat=lat, centroid_lon=lon, population=pop)


def _urban_tract(geoid: str, bgs: tuple[BlockGroup, ...], *, poverty=0.30, mfi=50000) -> TractInput:
    return TractInput(
        tract_geoid=geoid,
        urbanicity=URBANICITY_URBAN,
        poverty_rate=poverty,
        mfi=mfi,
        block_groups=bgs,
    )


def _nonurban_tract(geoid: str, bgs: tuple[BlockGroup, ...], *, poverty=0.30, mfi=50000) -> TractInput:
    return TractInput(
        tract_geoid=geoid,
        urbanicity=URBANICITY_NONURBAN,
        poverty_rate=poverty,
        mfi=mfi,
        block_groups=bgs,
    )


# ---------------------------------------------------------------------------
# Core SB 254 classification
# ---------------------------------------------------------------------------


def test_urban_tract_with_nearby_food_resource_is_not_sb254_effective():
    bg = _bg("10003000100", WILMINGTON_LAT, WILMINGTON_LON, pop=1000)
    tract = _urban_tract("10003000100", (bg,), poverty=0.30, mfi=50000)
    # Food resource within 0.5 mi (~800m) of the BG centroid.
    food = [FoodResourcePoint(lat=WILMINGTON_LAT + 0.003, lon=WILMINGTON_LON)]  # ~330m north
    out = classify_tracts([tract], food, state_mfi_median=80000)
    assert len(out) == 1
    # >50% of pop is WITHIN 0.5mi of food, so access does not fail.
    assert out[0].underserved_share == 0.0
    assert out[0].sb254_effective is False


def test_urban_tract_with_no_food_resource_is_sb254_effective():
    bg = _bg("10003000100", WILMINGTON_LAT, WILMINGTON_LON, pop=1000)
    tract = _urban_tract("10003000100", (bg,), poverty=0.30)
    # Food resource ~5km away — well past 0.5mi urban threshold.
    food = [FoodResourcePoint(lat=NORTH_FAR_LAT, lon=NORTH_FAR_LON)]
    out = classify_tracts([tract], food, state_mfi_median=80000)
    assert out[0].underserved_share == 1.0
    assert out[0].sb254_effective is True
    assert out[0].low_income is True
    assert out[0].low_income_reason.startswith("poverty>=")


def test_low_income_via_mfi_ratio():
    bg = _bg("10003000100", WILMINGTON_LAT, WILMINGTON_LON, pop=1000)
    # Poverty below threshold but MFI is 60k vs state median 100k -> ratio 0.60 <= 0.80
    tract = _urban_tract("10003000100", (bg,), poverty=0.05, mfi=60000)
    food = [FoodResourcePoint(lat=NORTH_FAR_LAT, lon=NORTH_FAR_LON)]
    out = classify_tracts([tract], food, state_mfi_median=100000)
    assert out[0].low_income is True
    assert out[0].low_income_reason.startswith("mfi_ratio<=")
    assert out[0].sb254_effective is True


def test_underserved_but_not_low_income_is_not_sb254_effective():
    bg = _bg("10003000100", WILMINGTON_LAT, WILMINGTON_LON, pop=1000)
    # Affluent tract: high MFI ratio + low poverty
    tract = _urban_tract("10003000100", (bg,), poverty=0.05, mfi=120000)
    food = [FoodResourcePoint(lat=NORTH_FAR_LAT, lon=NORTH_FAR_LON)]
    out = classify_tracts([tract], food, state_mfi_median=80000)
    assert out[0].underserved_share == 1.0  # no food nearby
    assert out[0].low_income is False
    assert out[0].sb254_effective is False  # access fails but income test fails -> not SB254


# ---------------------------------------------------------------------------
# Population threshold edge cases
# ---------------------------------------------------------------------------


def test_population_threshold_50_percent_exactly_does_not_trigger():
    # Underserved share = 0.5 exactly. Methodology: >50% pop must fail.
    # We use the strict inequality (`> threshold`), so 0.5 does not trigger.
    bg_near = _bg("10003000101", WILMINGTON_LAT, WILMINGTON_LON, pop=500)
    bg_far = _bg("10003000102", NORTH_FAR_LAT, NORTH_FAR_LON, pop=500)
    tract = _urban_tract("10003000100", (bg_near, bg_far), poverty=0.30)
    food = [FoodResourcePoint(lat=WILMINGTON_LAT, lon=WILMINGTON_LON)]
    out = classify_tracts([tract], food, state_mfi_median=80000)
    assert abs(out[0].underserved_share - 0.5) < 1e-9
    # 0.5 is NOT > 0.5 -> access test does not fail
    assert out[0].sb254_effective is False


def test_population_threshold_just_over_triggers():
    # 60% of pop is underserved -> SB 254-effective when low income too.
    bg_near = _bg("10003000101", WILMINGTON_LAT, WILMINGTON_LON, pop=400)
    bg_far = _bg("10003000102", NORTH_FAR_LAT, NORTH_FAR_LON, pop=600)
    tract = _urban_tract("10003000100", (bg_near, bg_far), poverty=0.30)
    food = [FoodResourcePoint(lat=WILMINGTON_LAT, lon=WILMINGTON_LON)]
    out = classify_tracts([tract], food, state_mfi_median=80000)
    assert out[0].underserved_share == 0.6
    assert out[0].sb254_effective is True


# ---------------------------------------------------------------------------
# Urbanicity branching
# ---------------------------------------------------------------------------


def test_nonurban_tract_uses_10mi_threshold():
    # BG ~5 mi from food. Urban tract would fail (>0.5mi); nonurban passes.
    # 5 mi ~ 0.072 degrees lat
    bg = _bg("10005000100", 39.0500, -75.3000, pop=1000)
    food = [FoodResourcePoint(lat=39.0500 + 0.072, lon=-75.3000)]
    nonurban = _nonurban_tract("10005000100", (bg,), poverty=0.30)
    out = classify_tracts([nonurban], food, state_mfi_median=80000)
    # Under 10mi -> not underserved
    assert out[0].underserved_share == 0.0
    assert out[0].sb254_effective is False

    urban = _urban_tract("10005000100", (bg,), poverty=0.30)
    out = classify_tracts([urban], food, state_mfi_median=80000)
    # ~5mi >> 0.5mi -> underserved
    assert out[0].underserved_share == 1.0
    assert out[0].sb254_effective is True


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_tract_with_no_block_groups_is_safe():
    tract = _urban_tract("10003000100", (), poverty=0.30)
    out = classify_tracts([tract], [], state_mfi_median=80000)
    assert out[0].population_total == 0
    assert out[0].underserved_share == 0.0
    assert out[0].sb254_effective is False


def test_no_food_resources_makes_everyone_underserved():
    bg = _bg("10003000100", WILMINGTON_LAT, WILMINGTON_LON, pop=1000)
    tract = _urban_tract("10003000100", (bg,), poverty=0.30)
    out = classify_tracts([tract], [], state_mfi_median=80000)
    assert out[0].underserved_share == 1.0
    assert out[0].sb254_effective is True


def test_missing_income_data_does_not_satisfy_low_income():
    bg = _bg("10003000100", WILMINGTON_LAT, WILMINGTON_LON, pop=1000)
    # No poverty rate, no MFI — methodology says we can't certify low-income.
    tract = TractInput(
        tract_geoid="10003000100",
        urbanicity=URBANICITY_URBAN,
        poverty_rate=None,
        mfi=None,
        block_groups=(bg,),
    )
    out = classify_tracts([tract], [], state_mfi_median=80000)
    assert out[0].low_income is False
    assert out[0].sb254_effective is False


def test_diagnostic_fields_carried_for_audit():
    bg = _bg("10003000100", WILMINGTON_LAT, WILMINGTON_LON, pop=1000)
    tract = _urban_tract("10003000100", (bg,), poverty=0.25, mfi=72000)
    out = classify_tracts([tract], [], state_mfi_median=80000)
    assert out[0].poverty_rate == 0.25
    assert out[0].mfi == 72000
    assert abs(out[0].mfi_ratio_to_state - 0.9) < 1e-9
    assert out[0].distance_threshold_mi == 0.5
    assert out[0].population_total == 1000
    assert out[0].population_underserved == 1000
