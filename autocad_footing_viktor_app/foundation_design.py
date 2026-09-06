from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, floor, pi, sqrt
from typing import Any, Mapping, Sequence


SERVICE = "Service"
ULTIMATE = "Ultimate"
STANDARD_BAR_DIAMETERS_MM = (12, 16, 20, 25, 32)
STANDARD_BAR_SPACINGS_MM = (300, 275, 250, 225, 200, 175, 150, 125, 100)


class DesignInputError(ValueError):
    """Raised when the user input cannot produce a valid footing design."""


@dataclass(frozen=True)
class SupportNode:
    node_id: str
    x_m: float
    y_m: float
    z_m: float
    column_x_m: float
    column_y_m: float


@dataclass(frozen=True)
class Reaction:
    node_id: str
    combination: str
    limit_state: str
    p_kn: float
    mx_knm: float
    my_knm: float


@dataclass(frozen=True)
class DesignSettings:
    allowable_bearing_pressure_kpa: float
    minimum_reinforcement_ratio: float
    concrete_strength_mpa: float
    steel_yield_strength_mpa: float
    cover_mm: float
    preferred_bar_diameter_mm: int
    self_weight_allowance_pct: float = 10.0
    dimension_increment_m: float = 0.10
    minimum_projection_m: float = 0.30
    maximum_aspect_ratio: float = 2.0
    minimum_thickness_mm: int = 300
    maximum_thickness_mm: int = 1500
    thickness_increment_mm: int = 25
    maximum_footing_dimension_m: float = 12.0
    foundation_level_tolerance_m: float = 0.01
    phi_flexure: float = 0.90
    phi_shear: float = 0.75


@dataclass(frozen=True)
class FootingDesign:
    node: SupportNode
    footing_type: str
    length_x_m: float
    length_y_m: float
    thickness_mm: int
    bar_x_mm: int
    spacing_x_mm: int
    bar_y_mm: int
    spacing_y_mm: int
    steel_x_mm2_per_m: float
    steel_y_mm2_per_m: float
    required_steel_x_mm2_per_m: float
    required_steel_y_mm2_per_m: float
    service_governing_combination: str
    ultimate_governing_combination: str
    q_service_max_kpa: float
    q_service_min_kpa: float
    q_ultimate_max_kpa: float
    bearing_utilization: float
    punching_utilization: float
    one_way_shear_x_utilization: float
    one_way_shear_y_utilization: float
    flexure_x_utilization: float
    flexure_y_utilization: float
    warning: str = ""


@dataclass(frozen=True)
class FootingTypeSummary:
    mark: str
    quantity: int
    node_ids: tuple[str, ...]
    representative: FootingDesign
    maximum_bearing_utilization: float
    maximum_punching_utilization: float
    maximum_one_way_shear_utilization: float
    maximum_flexure_utilization: float


@dataclass(frozen=True)
class DesignProject:
    nodes: tuple[SupportNode, ...]
    reactions: tuple[Reaction, ...]
    settings: DesignSettings
    footings: tuple[FootingDesign, ...]
    footing_types: tuple[FootingTypeSummary, ...]


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _required_text(row: Any, key: str, label: str, row_number: int) -> str:
    value = _row_value(row, key, "")
    text = str(value).strip() if value is not None else ""
    if not text:
        raise DesignInputError(f"{label} is required in row {row_number}.")
    return text


def _required_float(row: Any, key: str, label: str, row_number: int) -> float:
    value = _row_value(row, key, None)
    if value is None or value == "":
        raise DesignInputError(f"{label} is required in row {row_number}.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DesignInputError(f"{label} must be numeric in row {row_number}.") from exc
    return number


def parse_nodes(rows: Sequence[Any]) -> tuple[SupportNode, ...]:
    if not rows:
        raise DesignInputError("Add at least one support node.")

    nodes: list[SupportNode] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        node_id = _required_text(row, "node_id", "Node ID", index)
        if node_id in seen_ids:
            raise DesignInputError(f"Node ID '{node_id}' is repeated in the support-node table.")
        seen_ids.add(node_id)

        x_m = _required_float(row, "x_m", "X coordinate", index)
        y_m = _required_float(row, "y_m", "Y coordinate", index)
        z_value = _row_value(row, "z_m", 0.0)
        z_m = float(z_value or 0.0)
        column_x_mm = _required_float(row, "column_x_mm", "Column size X", index)
        column_y_mm = _required_float(row, "column_y_mm", "Column size Y", index)
        if column_x_mm <= 0 or column_y_mm <= 0:
            raise DesignInputError(f"Column dimensions must be greater than zero for node '{node_id}'.")

        nodes.append(
            SupportNode(
                node_id=node_id,
                x_m=x_m,
                y_m=y_m,
                z_m=z_m,
                column_x_m=column_x_mm / 1000.0,
                column_y_m=column_y_mm / 1000.0,
            )
        )
    return tuple(nodes)


def parse_reactions(rows: Sequence[Any], node_ids: set[str]) -> tuple[Reaction, ...]:
    if not rows:
        raise DesignInputError("Add service and ultimate reactions for every support node.")

    reactions: list[Reaction] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows, start=1):
        node_id = _required_text(row, "node_id", "Node ID", index)
        if node_id not in node_ids:
            raise DesignInputError(
                f"Reaction row {index} references node '{node_id}', which is not in the support-node table."
            )
        combination = _required_text(row, "combination", "Load combination", index)
        raw_state = _required_text(row, "limit_state", "Limit state", index).lower()
        if raw_state == "service":
            limit_state = SERVICE
        elif raw_state == "ultimate":
            limit_state = ULTIMATE
        else:
            raise DesignInputError(
                f"Limit state must be Service or Ultimate in reaction row {index}."
            )

        p_kn = _required_float(row, "p_kn", "Axial reaction P", index)
        mx_knm = _required_float(row, "mx_knm", "Moment Mx", index)
        my_knm = _required_float(row, "my_knm", "Moment My", index)
        if p_kn <= 0:
            raise DesignInputError(
                f"Axial reaction P must be positive compression for node '{node_id}', combination '{combination}'."
            )

        key = (node_id, combination, limit_state)
        if key in seen_keys:
            raise DesignInputError(
                f"Reaction '{combination}' ({limit_state}) is repeated for node '{node_id}'."
            )
        seen_keys.add(key)
        reactions.append(
            Reaction(
                node_id=node_id,
                combination=combination,
                limit_state=limit_state,
                p_kn=p_kn,
                mx_knm=mx_knm,
                my_knm=my_knm,
            )
        )

    for node_id in sorted(node_ids):
        states = {reaction.limit_state for reaction in reactions if reaction.node_id == node_id}
        if SERVICE not in states or ULTIMATE not in states:
            raise DesignInputError(
                f"Node '{node_id}' needs at least one Service row and one Ultimate row in the reactions table."
            )
    return tuple(reactions)


def validate_settings(settings: DesignSettings) -> None:
    if settings.allowable_bearing_pressure_kpa <= 0:
        raise DesignInputError("Allowable bearing pressure must be greater than zero.")
    if not 0 < settings.minimum_reinforcement_ratio < 0.02:
        raise DesignInputError("Minimum reinforcement ratio must be greater than 0 and less than 0.02.")
    if settings.concrete_strength_mpa <= 0:
        raise DesignInputError("Concrete strength must be greater than zero.")
    if settings.steel_yield_strength_mpa <= 0:
        raise DesignInputError("Steel yield strength must be greater than zero.")
    if settings.cover_mm <= 0:
        raise DesignInputError("Concrete cover must be greater than zero.")
    if settings.preferred_bar_diameter_mm not in STANDARD_BAR_DIAMETERS_MM:
        raise DesignInputError(
            f"Preferred bar diameter must be one of {', '.join(map(str, STANDARD_BAR_DIAMETERS_MM))} mm."
        )
    if settings.self_weight_allowance_pct < 0 or settings.self_weight_allowance_pct > 50:
        raise DesignInputError("Footing/self-weight allowance must be between 0% and 50%.")
    if settings.dimension_increment_m <= 0:
        raise DesignInputError("Footing dimension increment must be greater than zero.")
    if settings.minimum_thickness_mm <= settings.cover_mm + settings.preferred_bar_diameter_mm:
        raise DesignInputError("Minimum footing thickness is too small for the selected cover and bar size.")
    if settings.foundation_level_tolerance_m < 0:
        raise DesignInputError("Foundation-level tolerance cannot be negative.")


def _validate_single_foundation_level(
    nodes: Sequence[SupportNode], settings: DesignSettings
) -> None:
    elevations = [node.z_m for node in nodes]
    if max(elevations) - min(elevations) > settings.foundation_level_tolerance_m + 1e-9:
        raise DesignInputError(
            "This version creates one foundation plan at one elevation. Support-node Z coordinates differ "
            f"by more than {settings.foundation_level_tolerance_m:.3f} m. Split the nodes by foundation level."
        )


def _validate_no_overlapping_footings(designs: Sequence[FootingDesign]) -> None:
    for index, first in enumerate(designs):
        for second in designs[index + 1 :]:
            overlap_x = (first.length_x_m + second.length_x_m) / 2.0 - abs(
                first.node.x_m - second.node.x_m
            )
            overlap_y = (first.length_y_m + second.length_y_m) / 2.0 - abs(
                first.node.y_m - second.node.y_m
            )
            if overlap_x > 1e-7 and overlap_y > 1e-7:
                raise DesignInputError(
                    f"Designed footings at nodes '{first.node.node_id}' and '{second.node.node_id}' overlap "
                    f"in plan by approximately {overlap_x:.2f} m × {overlap_y:.2f} m. Use a combined/strip "
                    "foundation model or revise the layout."
                )


def _round_up(value: float, increment: float) -> float:
    return round(ceil((value - 1e-12) / increment) * increment, 10)


def _bar_area_mm2(diameter_mm: int) -> float:
    return pi * diameter_mm**2 / 4.0


def corner_pressures_kpa(
    reaction: Reaction,
    length_x_m: float,
    length_y_m: float,
    axial_multiplier: float = 1.0,
) -> tuple[float, float]:
    """Return minimum and maximum linear soil pressure at the four footing corners."""
    p_kn = reaction.p_kn * axial_multiplier
    base = p_kn / (length_x_m * length_y_m)
    variation_x = 6.0 * reaction.my_knm / (length_y_m * length_x_m**2)
    variation_y = 6.0 * reaction.mx_knm / (length_x_m * length_y_m**2)
    pressures = (
        base + variation_x + variation_y,
        base + variation_x - variation_y,
        base - variation_x + variation_y,
        base - variation_x - variation_y,
    )
    return min(pressures), max(pressures)


def _size_footing(
    node: SupportNode,
    service_reactions: Sequence[Reaction],
    settings: DesignSettings,
) -> tuple[float, float, str, float, float]:
    increment = settings.dimension_increment_m
    minimum_x = _round_up(
        max(0.80, node.column_x_m + 2.0 * settings.minimum_projection_m), increment
    )
    minimum_y = _round_up(
        max(0.80, node.column_y_m + 2.0 * settings.minimum_projection_m), increment
    )
    maximum = _round_up(settings.maximum_footing_dimension_m, increment)
    axial_multiplier = 1.0 + settings.self_weight_allowance_pct / 100.0

    nx = int(round((maximum - minimum_x) / increment)) + 1
    ny = int(round((maximum - minimum_y) / increment)) + 1
    values_x = [round(minimum_x + i * increment, 10) for i in range(max(nx, 0))]
    values_y = [round(minimum_y + i * increment, 10) for i in range(max(ny, 0))]

    best: tuple[tuple[float, float, float], float, float, str, float, float] | None = None
    for length_x_m in values_x:
        for length_y_m in values_y:
            aspect_ratio = max(length_x_m / length_y_m, length_y_m / length_x_m)
            if aspect_ratio > settings.maximum_aspect_ratio + 1e-9:
                continue

            all_valid = True
            governing_combo = ""
            governing_qmax = -float("inf")
            minimum_qmin = float("inf")
            for reaction in service_reactions:
                qmin, qmax = corner_pressures_kpa(
                    reaction, length_x_m, length_y_m, axial_multiplier=axial_multiplier
                )
                if qmin < -1e-7 or qmax > settings.allowable_bearing_pressure_kpa + 1e-7:
                    all_valid = False
                    break
                if qmax > governing_qmax:
                    governing_qmax = qmax
                    governing_combo = reaction.combination
                minimum_qmin = min(minimum_qmin, qmin)

            if not all_valid:
                continue

            area = length_x_m * length_y_m
            score = (round(area, 8), round(abs(length_x_m - length_y_m), 8), length_x_m + length_y_m)
            candidate = (score, length_x_m, length_y_m, governing_combo, governing_qmax, minimum_qmin)
            if best is None or candidate[0] < best[0]:
                best = candidate

    if best is None:
        raise DesignInputError(
            f"No centered footing up to {settings.maximum_footing_dimension_m:.1f} m satisfies bearing "
            f"and full-contact checks for node '{node.node_id}'. Review the reactions, allowable pressure, "
            "or use a non-centered/combined foundation model."
        )

    _, length_x_m, length_y_m, combo, qmax, qmin = best
    return length_x_m, length_y_m, combo, qmax, qmin


def _required_steel_mm2_per_m(
    moment_knm_per_m: float,
    effective_depth_mm: float,
    settings: DesignSettings,
) -> float:
    if moment_knm_per_m <= 0:
        return 0.0

    b_mm = 1000.0
    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    phi = settings.phi_flexure
    mu_nmm = moment_knm_per_m * 1_000_000.0

    quadratic_a = phi * fy**2 / (2.0 * 0.85 * fc * b_mm)
    quadratic_b = phi * fy * effective_depth_mm
    discriminant = quadratic_b**2 - 4.0 * quadratic_a * mu_nmm
    if discriminant <= 0:
        return float("inf")
    return (quadratic_b - sqrt(discriminant)) / (2.0 * quadratic_a)


def _select_rebar(
    required_steel_mm2_per_m: float,
    preferred_bar_diameter_mm: int,
) -> tuple[int, int, float] | None:
    bar_order = [preferred_bar_diameter_mm] + [
        diameter
        for diameter in sorted(
            STANDARD_BAR_DIAMETERS_MM,
            key=lambda item: (abs(item - preferred_bar_diameter_mm), item),
        )
        if diameter != preferred_bar_diameter_mm
    ]

    for diameter_mm in bar_order:
        area_mm2 = _bar_area_mm2(diameter_mm)
        for spacing_mm in STANDARD_BAR_SPACINGS_MM:
            provided = area_mm2 * 1000.0 / spacing_mm
            if provided + 1e-7 >= required_steel_mm2_per_m:
                return diameter_mm, spacing_mm, provided
    return None


def _flexural_capacity_knm_per_m(
    steel_mm2_per_m: float,
    effective_depth_mm: float,
    settings: DesignSettings,
) -> float:
    fy = settings.steel_yield_strength_mpa
    fc = settings.concrete_strength_mpa
    b_mm = 1000.0
    a_mm = steel_mm2_per_m * fy / (0.85 * fc * b_mm)
    lever_arm_mm = effective_depth_mm - a_mm / 2.0
    if lever_arm_mm <= 0:
        return 0.0
    return settings.phi_flexure * steel_mm2_per_m * fy * lever_arm_mm / 1_000_000.0


def _design_depth_and_rebar(
    node: SupportNode,
    length_x_m: float,
    length_y_m: float,
    ultimate_reactions: Sequence[Reaction],
    settings: DesignSettings,
) -> dict[str, Any]:
    projection_x_m = (length_x_m - node.column_x_m) / 2.0
    projection_y_m = (length_y_m - node.column_y_m) / 2.0
    if projection_x_m <= 0 or projection_y_m <= 0:
        raise DesignInputError(f"Footing projections are invalid for node '{node.node_id}'.")

    for thickness_mm in range(
        int(settings.minimum_thickness_mm),
        int(settings.maximum_thickness_mm) + 1,
        int(settings.thickness_increment_mm),
    ):
        effective_depth_mm = (
            thickness_mm - settings.cover_mm - 1.5 * settings.preferred_bar_diameter_mm
        )
        if effective_depth_mm <= 0:
            continue

        selected_x: tuple[int, int, float] | None = None
        selected_y: tuple[int, int, float] | None = None
        required_x = required_y = 0.0
        governing_ultimate_combo = ""
        q_ultimate_max = 0.0
        moment_x_max = 0.0
        moment_y_max = 0.0

        # Re-evaluate effective depth after actual bar sizes are selected.
        for _ in range(4):
            moment_x_max = 0.0
            moment_y_max = 0.0
            governing_ultimate_combo = ""
            q_ultimate_max = -float("inf")
            for reaction in ultimate_reactions:
                _, qmax = corner_pressures_kpa(reaction, length_x_m, length_y_m)
                moment_x = qmax * projection_x_m**2 / 2.0
                moment_y = qmax * projection_y_m**2 / 2.0
                moment_x_max = max(moment_x_max, moment_x)
                moment_y_max = max(moment_y_max, moment_y)
                if qmax > q_ultimate_max:
                    q_ultimate_max = qmax
                    governing_ultimate_combo = reaction.combination

            minimum_steel = settings.minimum_reinforcement_ratio * 1000.0 * thickness_mm
            flexural_x = _required_steel_mm2_per_m(moment_x_max, effective_depth_mm, settings)
            flexural_y = _required_steel_mm2_per_m(moment_y_max, effective_depth_mm, settings)
            required_x = max(minimum_steel, flexural_x)
            required_y = max(minimum_steel, flexural_y)
            if required_x == float("inf") or required_y == float("inf"):
                selected_x = selected_y = None
                break

            selected_x = _select_rebar(required_x, settings.preferred_bar_diameter_mm)
            selected_y = _select_rebar(required_y, settings.preferred_bar_diameter_mm)
            if selected_x is None or selected_y is None:
                break

            bar_x_mm = selected_x[0]
            bar_y_mm = selected_y[0]
            updated_depth = thickness_mm - settings.cover_mm - (
                max(bar_x_mm, bar_y_mm) + min(bar_x_mm, bar_y_mm) / 2.0
            )
            if updated_depth <= 0:
                selected_x = selected_y = None
                break
            if abs(updated_depth - effective_depth_mm) < 0.1:
                effective_depth_mm = updated_depth
                break
            effective_depth_mm = updated_depth

        if selected_x is None or selected_y is None:
            continue

        bar_x_mm, spacing_x_mm, provided_x = selected_x
        bar_y_mm, spacing_y_mm, provided_y = selected_y
        d_m = effective_depth_mm / 1000.0

        max_punching_util = 0.0
        max_one_way_x_util = 0.0
        max_one_way_y_util = 0.0
        ultimate_qmin_negative = False

        for reaction in ultimate_reactions:
            qmin, qmax = corner_pressures_kpa(reaction, length_x_m, length_y_m)
            ultimate_qmin_negative = ultimate_qmin_negative or qmin < -1e-7

            # One-way shear sections are at d from the column face. qmax is used over the
            # full tributary area as a conservative preliminary envelope.
            shear_length_x_m = max(0.0, projection_x_m - d_m)
            shear_length_y_m = max(0.0, projection_y_m - d_m)
            demand_x_kn = qmax * length_y_m * shear_length_x_m
            demand_y_kn = qmax * length_x_m * shear_length_y_m

            capacity_x_kn = (
                settings.phi_shear
                * 0.17
                * sqrt(settings.concrete_strength_mpa)
                * (length_y_m * 1000.0)
                * effective_depth_mm
                / 1000.0
            )
            capacity_y_kn = (
                settings.phi_shear
                * 0.17
                * sqrt(settings.concrete_strength_mpa)
                * (length_x_m * 1000.0)
                * effective_depth_mm
                / 1000.0
            )
            max_one_way_x_util = max(
                max_one_way_x_util, demand_x_kn / capacity_x_kn if capacity_x_kn > 0 else float("inf")
            )
            max_one_way_y_util = max(
                max_one_way_y_util, demand_y_kn / capacity_y_kn if capacity_y_kn > 0 else float("inf")
            )

            critical_x_m = node.column_x_m + d_m
            critical_y_m = node.column_y_m + d_m
            if critical_x_m >= length_x_m or critical_y_m >= length_y_m:
                punching_util = 0.0
            else:
                average_pressure_kpa = reaction.p_kn / (length_x_m * length_y_m)
                area_inside_m2 = critical_x_m * critical_y_m
                punching_demand_kn = max(
                    0.0, reaction.p_kn - average_pressure_kpa * area_inside_m2
                )
                bo_mm = 2.0 * (critical_x_m + critical_y_m) * 1000.0
                beta = max(node.column_x_m, node.column_y_m) / min(
                    node.column_x_m, node.column_y_m
                )
                vc_coefficients = (
                    0.17 * (1.0 + 2.0 / beta),
                    0.083 * (2.0 + 40.0 * effective_depth_mm / bo_mm),
                    0.33,
                )
                nominal_capacity_kn = (
                    min(vc_coefficients)
                    * sqrt(settings.concrete_strength_mpa)
                    * bo_mm
                    * effective_depth_mm
                    / 1000.0
                )
                design_capacity_kn = settings.phi_shear * nominal_capacity_kn
                punching_util = (
                    punching_demand_kn / design_capacity_kn
                    if design_capacity_kn > 0
                    else float("inf")
                )
            max_punching_util = max(max_punching_util, punching_util)

        capacity_mx = _flexural_capacity_knm_per_m(provided_x, effective_depth_mm, settings)
        capacity_my = _flexural_capacity_knm_per_m(provided_y, effective_depth_mm, settings)
        flexure_x_util = moment_x_max / capacity_mx if capacity_mx > 0 else float("inf")
        flexure_y_util = moment_y_max / capacity_my if capacity_my > 0 else float("inf")

        if max(
            max_punching_util,
            max_one_way_x_util,
            max_one_way_y_util,
            flexure_x_util,
            flexure_y_util,
        ) <= 1.0 + 1e-7:
            warning = (
                "Ultimate load produces corner tension in the linear soil-pressure model; "
                "review partial-contact behavior."
                if ultimate_qmin_negative
                else ""
            )
            return {
                "thickness_mm": thickness_mm,
                "bar_x_mm": bar_x_mm,
                "spacing_x_mm": spacing_x_mm,
                "bar_y_mm": bar_y_mm,
                "spacing_y_mm": spacing_y_mm,
                "provided_x": provided_x,
                "provided_y": provided_y,
                "required_x": required_x,
                "required_y": required_y,
                "governing_ultimate_combo": governing_ultimate_combo,
                "q_ultimate_max": q_ultimate_max,
                "punching_utilization": max_punching_util,
                "one_way_x_utilization": max_one_way_x_util,
                "one_way_y_utilization": max_one_way_y_util,
                "flexure_x_utilization": flexure_x_util,
                "flexure_y_utilization": flexure_y_util,
                "warning": warning,
            }

    raise DesignInputError(
        f"Node '{node.node_id}' needs a footing thicker than {settings.maximum_thickness_mm} mm or "
        "reinforcement outside the available bar/spacing set. Review the loads and design assumptions."
    )


def _type_key(design: FootingDesign) -> tuple[Any, ...]:
    return (
        round(design.length_x_m, 3),
        round(design.length_y_m, 3),
        design.thickness_mm,
        design.bar_x_mm,
        design.spacing_x_mm,
        design.bar_y_mm,
        design.spacing_y_mm,
        round(design.node.column_x_m, 3),
        round(design.node.column_y_m, 3),
    )


def _assign_types(
    designs: Sequence[FootingDesign],
) -> tuple[tuple[FootingDesign, ...], tuple[FootingTypeSummary, ...]]:
    unique_keys = sorted(
        {_type_key(design) for design in designs},
        key=lambda key: (key[0] * key[1], key[2], key[0], key[1], key[7], key[8]),
    )
    marks = {key: f"F{index}" for index, key in enumerate(unique_keys, start=1)}
    typed_designs = tuple(replace(design, footing_type=marks[_type_key(design)]) for design in designs)

    summaries: list[FootingTypeSummary] = []
    for key in unique_keys:
        members = [design for design in typed_designs if _type_key(design) == key]
        representative = members[0]
        summaries.append(
            FootingTypeSummary(
                mark=marks[key],
                quantity=len(members),
                node_ids=tuple(member.node.node_id for member in members),
                representative=representative,
                maximum_bearing_utilization=max(member.bearing_utilization for member in members),
                maximum_punching_utilization=max(member.punching_utilization for member in members),
                maximum_one_way_shear_utilization=max(
                    max(member.one_way_shear_x_utilization, member.one_way_shear_y_utilization)
                    for member in members
                ),
                maximum_flexure_utilization=max(
                    max(member.flexure_x_utilization, member.flexure_y_utilization)
                    for member in members
                ),
            )
        )
    return typed_designs, tuple(summaries)


def design_project(
    node_rows: Sequence[Any],
    reaction_rows: Sequence[Any],
    settings: DesignSettings,
) -> DesignProject:
    """Validate inputs and produce centered isolated-footing designs for all support nodes."""
    validate_settings(settings)
    nodes = parse_nodes(node_rows)
    _validate_single_foundation_level(nodes, settings)
    reactions = parse_reactions(reaction_rows, {node.node_id for node in nodes})

    designs: list[FootingDesign] = []
    for node in nodes:
        service = [
            reaction
            for reaction in reactions
            if reaction.node_id == node.node_id and reaction.limit_state == SERVICE
        ]
        ultimate = [
            reaction
            for reaction in reactions
            if reaction.node_id == node.node_id and reaction.limit_state == ULTIMATE
        ]
        length_x_m, length_y_m, service_combo, q_service_max, q_service_min = _size_footing(
            node, service, settings
        )
        strength = _design_depth_and_rebar(
            node, length_x_m, length_y_m, ultimate, settings
        )

        designs.append(
            FootingDesign(
                node=node,
                footing_type="",
                length_x_m=length_x_m,
                length_y_m=length_y_m,
                thickness_mm=strength["thickness_mm"],
                bar_x_mm=strength["bar_x_mm"],
                spacing_x_mm=strength["spacing_x_mm"],
                bar_y_mm=strength["bar_y_mm"],
                spacing_y_mm=strength["spacing_y_mm"],
                steel_x_mm2_per_m=strength["provided_x"],
                steel_y_mm2_per_m=strength["provided_y"],
                required_steel_x_mm2_per_m=strength["required_x"],
                required_steel_y_mm2_per_m=strength["required_y"],
                service_governing_combination=service_combo,
                ultimate_governing_combination=strength["governing_ultimate_combo"],
                q_service_max_kpa=q_service_max,
                q_service_min_kpa=q_service_min,
                q_ultimate_max_kpa=strength["q_ultimate_max"],
                bearing_utilization=q_service_max / settings.allowable_bearing_pressure_kpa,
                punching_utilization=strength["punching_utilization"],
                one_way_shear_x_utilization=strength["one_way_x_utilization"],
                one_way_shear_y_utilization=strength["one_way_y_utilization"],
                flexure_x_utilization=strength["flexure_x_utilization"],
                flexure_y_utilization=strength["flexure_y_utilization"],
                warning=strength["warning"],
            )
        )

    _validate_no_overlapping_footings(designs)
    typed_designs, footing_types = _assign_types(designs)
    return DesignProject(
        nodes=nodes,
        reactions=reactions,
        settings=settings,
        footings=typed_designs,
        footing_types=footing_types,
    )
