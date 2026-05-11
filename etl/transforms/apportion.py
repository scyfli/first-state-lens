"""Population-weighted areal interpolation — county → tract apportionment.

Implements methodology v0.2.0 §"Hero KPI" and §Q3: Map the Meal Gap
publishes food-insecurity counts at the county level, but the dashboard
needs tract-level numbers (so we can show "dollars per food-insecure
resident, by tract"). Census ACS block-group population is the weighting
layer: a tract gets a share of its county's count proportional to the
fraction of that county's population that lives inside the tract.

Mathematically, for each target tract t inside source county s:

    apportioned_count[t] = county_count[s] * fraction_of_s_population_in_t

where

    fraction_of_s_population_in_t = pop_in(s ∩ t) / pop_in(s)
    pop_in(geom) = sum over block groups bg:
                       bg.population * area(bg ∩ geom) / area(bg)

The block-group "smear" (proportional-area allocation) is the
methodology's documented choice: it's the cleanest tractable
implementation when block-group geometry doesn't perfectly nest inside
tract geometry (which is rare but not impossible). For block groups
fully inside one tract, the formula collapses to bg.population. For
block groups split across tract boundaries (legitimate cases include
revised tracts after 2020), area share is the documented proxy.

The methodology cites `tidycensus::interpolate_pw(..., extensive=TRUE)`
from R as the equivalent. PySAL `tobler.area_weighted.area_interpolate`
implements *area-weighted* (not population-weighted) interpolation; the
population-weighted variant is implemented in-module here using
geopandas overlays. The brief's methodology-equivalence table documents
this distinction.

This module requires the geo stack (geopandas, shapely). Imports are
lazy so the surrounding ETL doesn't require geopandas just to load this
module (e.g., for `python -m etl.run_etl --help`). Tests use
`pytest.importorskip("geopandas")` so the smoke suite still runs on a
Windows dev box without GDAL installed.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import geopandas as gpd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ApportionmentResult:
    """Result of one apportionment pass.

    `target` is a GeoDataFrame with the original target columns + one
    new column per extensive variable, named `<var>_apportioned`.

    `coverage` is the share of source-county population accounted for
    by the weight layer (block-group population sum / source count of
    weight intersections). Values < 1.0 indicate parts of the county
    where the weight layer missed coverage (e.g., uninhabited tracts).
    A coverage of 1.0 is the expected steady state for Delaware.

    `unmatched_sources` lists source ids whose population coverage was
    zero — usually a sign that geometry projection is mismatched or
    that the weight layer is missing for that county.
    """

    target: "gpd.GeoDataFrame"
    coverage: dict[str, float]
    unmatched_sources: list[str]


def population_weighted_interpolate(
    source: "gpd.GeoDataFrame",
    target: "gpd.GeoDataFrame",
    weights: "gpd.GeoDataFrame",
    *,
    source_id_col: str,
    target_id_col: str,
    weight_pop_col: str,
    extensive_variables: Sequence[str],
    working_crs: str = "EPSG:5070",
) -> ApportionmentResult:
    """Apportion `extensive_variables` from `source` polygons to `target`
    polygons using `weights` (block-group population) as the weighting layer.

    Parameters
    ----------
    source : GeoDataFrame
        Polygons whose extensive variables we apportion (counties).
        Must contain `source_id_col` and each name in `extensive_variables`.
    target : GeoDataFrame
        Polygons that should receive the apportioned values (tracts).
        Must contain `target_id_col`.
    weights : GeoDataFrame
        Population-bearing weighting polygons (block groups). Must contain
        `weight_pop_col` and a unique-per-row index. Each block group should
        nest inside one source polygon (the standard Census hierarchy); if
        it straddles, area-share allocates the population.
    source_id_col : str
        Column name on `source` carrying the join key (e.g., "GEOID").
    target_id_col : str
        Column name on `target` carrying the join key (e.g., "GEOID").
    weight_pop_col : str
        Column name on `weights` carrying population (e.g., "POP_2020").
    extensive_variables : sequence of str
        Source columns to apportion. "Extensive" means the variable's
        meaning is preserved by summation (count of food-insecure persons
        is extensive; food-insecurity rate is intensive — don't pass an
        intensive variable here).
    working_crs : str
        The equal-area CRS used for area calculations. Default EPSG:5070
        (NAD83 / Conus Albers) is the standard equal-area projection for
        the contiguous US. Inputs are projected before overlay.

    Returns
    -------
    ApportionmentResult
        `target` GeoDataFrame with new columns; `coverage` dict;
        `unmatched_sources` list.
    """
    import geopandas as gpd  # noqa: F401  (validate dependency available)
    import pandas as pd

    # Reproject everything to an equal-area CRS for consistent area math.
    src = source.to_crs(working_crs)
    tgt = target.to_crs(working_crs)
    wgt = weights.to_crs(working_crs)

    # Step 1: original block-group area (for area-share allocation when
    # a BG is intersected). Calculated once before any overlay.
    wgt = wgt.copy()
    wgt["__bg_area__"] = wgt.geometry.area
    if (wgt["__bg_area__"] <= 0).any():
        raise ValueError("weight layer has block-group geometry with non-positive area")

    # Step 2: overlay source × target → s_x_t. Each row is a single
    # (source, target) intersection polygon.
    s_x_t = gpd.overlay(
        src[[source_id_col, *extensive_variables, src.geometry.name]],
        tgt[[target_id_col, tgt.geometry.name]],
        how="intersection",
        keep_geom_type=True,
    )

    # Step 3: overlay s_x_t × weights → s_x_t_x_w. Each row is a single
    # (source, target, bg) intersection polygon. Population in that
    # polygon is bg.pop * area(s_x_t_x_w) / bg.area_original.
    s_x_t_x_w = gpd.overlay(
        s_x_t,
        wgt[[weight_pop_col, "__bg_area__", wgt.geometry.name]],
        how="intersection",
        keep_geom_type=True,
    )
    s_x_t_x_w["__sliver_area__"] = s_x_t_x_w.geometry.area
    s_x_t_x_w["__sliver_pop__"] = (
        s_x_t_x_w[weight_pop_col]
        * s_x_t_x_w["__sliver_area__"]
        / s_x_t_x_w["__bg_area__"]
    )

    # Step 4: per source, total population accounted for by the weight
    # layer. This is the denominator in fraction_of_source_pop_in_target.
    src_pop_total: pd.Series = (
        s_x_t_x_w.groupby(source_id_col)["__sliver_pop__"].sum()
    )

    # Step 5: per (source, target), population in this slice.
    s_x_t_pop = (
        s_x_t_x_w.groupby([source_id_col, target_id_col])["__sliver_pop__"]
        .sum()
        .reset_index()
        .rename(columns={"__sliver_pop__": "__slice_pop__"})
    )

    # Step 6: join in source totals + extensive variables.
    s_x_t_pop["__source_total_pop__"] = s_x_t_pop[source_id_col].map(src_pop_total)
    # Source variables — one merge to bring them in.
    src_vars = src[[source_id_col, *extensive_variables]].copy()
    s_x_t_pop = s_x_t_pop.merge(src_vars, on=source_id_col, how="left")

    # Step 7: compute per-target apportioned contribution per source.
    # Guard zero-population denominators (counties with no BG coverage).
    safe_total = s_x_t_pop["__source_total_pop__"].replace(0, float("nan"))
    s_x_t_pop["__fraction__"] = s_x_t_pop["__slice_pop__"] / safe_total
    s_x_t_pop["__fraction__"] = s_x_t_pop["__fraction__"].fillna(0.0)
    for var in extensive_variables:
        s_x_t_pop[f"{var}_apportioned"] = s_x_t_pop[var] * s_x_t_pop["__fraction__"]

    # Step 8: aggregate to target.
    apportioned_cols = [f"{v}_apportioned" for v in extensive_variables]
    by_target = (
        s_x_t_pop.groupby(target_id_col)[apportioned_cols].sum().reset_index()
    )

    # Step 9: attach to target.
    target_out = target.merge(by_target, on=target_id_col, how="left")
    for col in apportioned_cols:
        target_out[col] = target_out[col].fillna(0.0)

    # Step 10: diagnostics — coverage per source, unmatched sources.
    coverage: dict[str, float] = {}
    unmatched_sources: list[str] = []
    for src_id, _ in src.iterrows():
        sid_value = src.loc[src_id, source_id_col]
        accounted = float(src_pop_total.get(sid_value, 0.0))
        # Approximate "total bg pop in source" via the weight layer
        # overlaid against the source alone. This gives the upper bound
        # of population the weight layer can account for.
        intersect_only = gpd.overlay(
            wgt[[weight_pop_col, "__bg_area__", wgt.geometry.name]],
            src.loc[[src_id], [source_id_col, src.geometry.name]],
            how="intersection",
            keep_geom_type=True,
        )
        intersect_only["__a__"] = intersect_only.geometry.area
        bg_pop_in_src = float(
            (
                intersect_only[weight_pop_col]
                * intersect_only["__a__"]
                / intersect_only["__bg_area__"]
            ).sum()
        )
        if bg_pop_in_src > 0:
            coverage[sid_value] = accounted / bg_pop_in_src
        else:
            coverage[sid_value] = 0.0
            unmatched_sources.append(sid_value)

    return ApportionmentResult(
        target=target_out,
        coverage=coverage,
        unmatched_sources=unmatched_sources,
    )
