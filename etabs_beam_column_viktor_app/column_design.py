from __future__ import annotations

from dataclasses import dataclass
from math import acos, cos, log10, pi, sin, sqrt
from typing import Iterable, Sequence

from models import (
    ColumnBarLayout,
    ColumnDemandCheck,
    ColumnDesign,
    ColumnForce,
    ColumnMember,
    DesignInputError,
    DesignSettings,
    InteractionPoint,
)


COLUMN_BAR_DIAMETERS = (16, 20, 25, 32)
TIE_DIAMETERS = (8, 10, 12, 16)
TIE_SPACINGS_MM = (300, 250, 225, 200, 175, 150, 125, 100, 75)


def _bar_area(diameter_mm: float) -> float:
    return pi * diameter_mm**2 / 4.0


def _beta1(fc_mpa: float) -> float:
    if fc_mpa <= 28.0:
        return 0.85
    return max(0.65, 0.85 - 0.05 * ((fc_mpa - 28.0) / 7.0))


def _column_phi(tension_strain: float, settings: DesignSettings) -> float:
    yield_strain = settings.steel_yield_strength_mpa / settings.steel_modulus_mpa
    if tension_strain <= yield_strain:
        return settings.column_tied_phi_min
    if tension_strain >= 0.005:
        return settings.column_phi_max
    return settings.column_tied_phi_min + (
        settings.column_phi_max - settings.column_tied_phi_min
    ) * ((tension_strain - yield_strain) / (0.005 - yield_strain))


def _linear_coordinates(negative: float, positive: float, count: int) -> list[float]:
    if count <= 1:
        return [(negative + positive) / 2.0]
    spacing = (positive - negative) / (count - 1)
    return [negative + i * spacing for i in range(count)]


def _clear_spacing_ok(span_between_centers: float, count: int, diameter_mm: int) -> bool:
    if count <= 1:
        return True
    center_spacing = span_between_centers / (count - 1)
    return center_spacing - diameter_mm >= max(40.0, float(diameter_mm)) - 1e-9


def _rectangular_layouts(member: ColumnMember, settings: DesignSettings) -> list[ColumnBarLayout]:
    layouts: list[ColumnBarLayout] = []
    gross_area = member.gross_area_mm2
    for diameter in COLUMN_BAR_DIAMETERS:
        edge_x = member.width_mm / 2.0 - (
            settings.concrete_cover_mm + settings.preferred_stirrup_mm + diameter / 2.0
        )
        edge_y = member.depth_mm / 2.0 - (
            settings.concrete_cover_mm + settings.preferred_stirrup_mm + diameter / 2.0
        )
        if edge_x <= 0.0 or edge_y <= 0.0:
            continue
        for nx in range(2, 9):
            if not _clear_spacing_ok(2.0 * edge_x, nx, diameter):
                continue
            for ny in range(2, 9):
                if not _clear_spacing_ok(2.0 * edge_y, ny, diameter):
                    continue
                x_values = _linear_coordinates(-edge_x, edge_x, nx)
                y_values = _linear_coordinates(-edge_y, edge_y, ny)
                coordinates: list[tuple[float, float]] = []
                for x in x_values:
                    coordinates.append((x, edge_y))
                    coordinates.append((x, -edge_y))
                for y in y_values[1:-1]:
                    coordinates.append((-edge_x, y))
                    coordinates.append((edge_x, y))
                area = len(coordinates) * _bar_area(diameter)
                ratio = area / gross_area
                if settings.minimum_column_ratio - 1e-12 <= ratio <= settings.maximum_column_ratio + 1e-12:
                    layouts.append(
                        ColumnBarLayout(
                            shape="Rectangular",
                            diameter_mm=diameter,
                            coordinates_mm=tuple(coordinates),
                            area_mm2=area,
                            ratio=ratio,
                            bars_along_width=nx,
                            bars_along_depth=ny,
                        )
                    )
    return layouts


def _circular_layouts(member: ColumnMember, settings: DesignSettings) -> list[ColumnBarLayout]:
    layouts: list[ColumnBarLayout] = []
    gross_area = member.gross_area_mm2
    diameter_section = member.diameter_mm
    for diameter in COLUMN_BAR_DIAMETERS:
        radius = diameter_section / 2.0 - (
            settings.concrete_cover_mm + settings.preferred_stirrup_mm + diameter / 2.0
        )
        if radius <= 0.0:
            continue
        for count in range(6, 33, 2):
            clear_arc = 2.0 * pi * radius / count - diameter
            if clear_arc < max(40.0, float(diameter)) - 1e-9:
                continue
            coordinates = tuple(
                (radius * cos(2.0 * pi * index / count), radius * sin(2.0 * pi * index / count))
                for index in range(count)
            )
            area = count * _bar_area(diameter)
            ratio = area / gross_area
            if settings.minimum_column_ratio - 1e-12 <= ratio <= settings.maximum_column_ratio + 1e-12:
                layouts.append(
                    ColumnBarLayout(
                        shape="Circular",
                        diameter_mm=diameter,
                        coordinates_mm=coordinates,
                        area_mm2=area,
                        ratio=ratio,
                    )
                )
    return layouts


def generate_column_layouts(member: ColumnMember, settings: DesignSettings) -> list[ColumnBarLayout]:
    if member.shape == "Circular":
        layouts = _circular_layouts(member, settings)
    else:
        layouts = _rectangular_layouts(member, settings)
    if not layouts:
        raise DesignInputError(
            f"Column '{member.member_id}' cannot fit a reinforcement layout within the selected ratio and cover limits."
        )
    return sorted(
        layouts,
        key=lambda item: (
            item.area_mm2,
            abs(item.diameter_mm - settings.preferred_column_bar_mm),
            item.count,
        ),
    )


def _circle_segment_area_and_centroid(radius_mm: float, depth_mm: float) -> tuple[float, float]:
    """Area and centroid from the circle centre of the segment at the positive axis face."""

    depth = min(max(depth_mm, 0.0), 2.0 * radius_mm)
    if depth <= 0.0:
        return 0.0, radius_mm
    if depth >= 2.0 * radius_mm:
        return pi * radius_mm**2, 0.0
    chord_coordinate = radius_mm - depth
    root = sqrt(max(0.0, radius_mm**2 - chord_coordinate**2))
    area = radius_mm**2 * acos(chord_coordinate / radius_mm) - chord_coordinate * root
    first_moment = 2.0 / 3.0 * max(0.0, radius_mm**2 - chord_coordinate**2) ** 1.5
    centroid = first_moment / area if area > 1e-12 else radius_mm
    return area, centroid


def _section_compression_block(
    member: ColumnMember,
    axis: str,
    a_mm: float,
) -> tuple[float, float, float]:
    """Return area, centroid coordinate and full depth along the bending gradient."""

    if member.shape == "Circular":
        radius = member.diameter_mm / 2.0
        area, centroid = _circle_segment_area_and_centroid(radius, a_mm)
        return area, centroid, member.diameter_mm

    # ETABS rectangular section convention: T3 is the section depth along local 2,
    # and T2 is the section width along local 3. Therefore M3 bends through T3,
    # while M2 bends through T2.
    if axis == "M3":
        depth = member.depth_mm
        perpendicular_width = member.width_mm
    else:
        depth = member.width_mm
        perpendicular_width = member.depth_mm
    actual_a = min(max(a_mm, 0.0), depth)
    area = perpendicular_width * actual_a
    centroid = depth / 2.0 - actual_a / 2.0
    return area, centroid, depth


def _bar_axis_coordinate(coordinate: tuple[float, float], axis: str) -> float:
    # Coordinates are stored as (local-3 / T2 width, local-2 / T3 depth).
    # M2 uses the local-3 coordinate; M3 uses the local-2 coordinate.
    return coordinate[0] if axis == "M2" else coordinate[1]


def _neutral_axis_values(depth_mm: float) -> list[float]:
    values = {max(0.5, depth_mm * 0.005), depth_mm}
    for index in range(70):
        exponent = log10(0.01) + (log10(20.0) - log10(0.01)) * index / 69.0
        values.add(depth_mm * (10.0**exponent))
    for index in range(1, 30):
        values.add(depth_mm * index / 10.0)
    return sorted(values)


def interaction_curve(
    member: ColumnMember,
    layout: ColumnBarLayout,
    axis: str,
    settings: DesignSettings,
) -> tuple[InteractionPoint, ...]:
    if axis not in {"M2", "M3"}:
        raise ValueError("axis must be M2 or M3")

    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    es = settings.steel_modulus_mpa
    beta1 = _beta1(fc)
    bar_area = _bar_area(layout.diameter_mm)
    gross_area = member.gross_area_mm2
    po_n = 0.85 * fc * (gross_area - layout.area_mm2) + fy * layout.area_mm2
    axial_design_cap_n = settings.column_axial_cap_factor * settings.column_tied_phi_min * po_n

    depth = member.diameter_mm if member.shape == "Circular" else (
        member.width_mm if axis == "M2" else member.depth_mm
    )
    positive_face = depth / 2.0
    points: list[InteractionPoint] = []

    pure_tension_n = -layout.area_mm2 * fy
    points.append(
        InteractionPoint(
            axial_kn=settings.column_phi_max * pure_tension_n / 1000.0,
            moment_knm=0.0,
            nominal_axial_kn=pure_tension_n / 1000.0,
            nominal_moment_knm=0.0,
            phi=settings.column_phi_max,
            neutral_axis_mm=0.0,
            tension_strain=0.1,
        )
    )

    for c_mm in _neutral_axis_values(depth):
        a_mm = min(beta1 * c_mm, depth)
        concrete_area, concrete_centroid, _ = _section_compression_block(member, axis, a_mm)
        concrete_force_n = 0.85 * fc * concrete_area
        nominal_axial_n = concrete_force_n
        nominal_moment_nmm = concrete_force_n * concrete_centroid
        minimum_bar_strain = 0.0

        compression_limit = positive_face - a_mm
        for coordinate in layout.coordinates_mm:
            u = _bar_axis_coordinate(coordinate, axis)
            strain = 0.003 * (1.0 - (positive_face - u) / c_mm)
            minimum_bar_strain = min(minimum_bar_strain, strain)
            steel_stress = max(-fy, min(fy, es * strain))
            displaced_concrete_stress = 0.85 * fc if u >= compression_limit - 1e-9 else 0.0
            net_force_n = bar_area * (steel_stress - displaced_concrete_stress)
            nominal_axial_n += net_force_n
            nominal_moment_nmm += net_force_n * u

        tension_strain = abs(min(0.0, minimum_bar_strain))
        phi = _column_phi(tension_strain, settings)
        design_axial_n = phi * nominal_axial_n
        if design_axial_n > 0.0:
            design_axial_n = min(design_axial_n, axial_design_cap_n)
        design_moment_nmm = phi * abs(nominal_moment_nmm)
        points.append(
            InteractionPoint(
                axial_kn=design_axial_n / 1000.0,
                moment_knm=design_moment_nmm / 1_000_000.0,
                nominal_axial_kn=nominal_axial_n / 1000.0,
                nominal_moment_knm=abs(nominal_moment_nmm) / 1_000_000.0,
                phi=phi,
                neutral_axis_mm=c_mm,
                tension_strain=tension_strain,
            )
        )

    # Build a clean envelope: for nearly equal axial levels retain the greatest moment.
    grouped: dict[float, InteractionPoint] = {}
    for point in points:
        key = round(point.axial_kn, 3)
        existing = grouped.get(key)
        if existing is None or point.moment_knm > existing.moment_knm:
            grouped[key] = point
    return tuple(sorted(grouped.values(), key=lambda point: point.axial_kn))


def _capacity_at_axial(curve: Sequence[InteractionPoint], axial_kn: float) -> float:
    if not curve:
        return 0.0
    if axial_kn < curve[0].axial_kn - 1e-9 or axial_kn > curve[-1].axial_kn + 1e-9:
        return 0.0
    if abs(axial_kn - curve[0].axial_kn) <= 1e-9:
        return curve[0].moment_knm
    for left, right in zip(curve, curve[1:]):
        if left.axial_kn - 1e-9 <= axial_kn <= right.axial_kn + 1e-9:
            delta = right.axial_kn - left.axial_kn
            if abs(delta) < 1e-12:
                return max(left.moment_knm, right.moment_knm)
            ratio = (axial_kn - left.axial_kn) / delta
            return left.moment_knm + ratio * (right.moment_knm - left.moment_knm)
    return curve[-1].moment_knm


def _evaluate_layout(
    member: ColumnMember,
    forces: Sequence[ColumnForce],
    layout: ColumnBarLayout,
    settings: DesignSettings,
) -> tuple[
    tuple[InteractionPoint, ...],
    tuple[InteractionPoint, ...],
    tuple[ColumnDemandCheck, ...],
]:
    curve_m2 = interaction_curve(member, layout, "M2", settings)
    curve_m3 = interaction_curve(member, layout, "M3", settings)
    max_axial_capacity = min(curve_m2[-1].axial_kn, curve_m3[-1].axial_kn)
    minimum_tension_capacity = max(abs(curve_m2[0].axial_kn), abs(curve_m3[0].axial_kn))
    alpha = max(0.5, settings.column_biaxial_exponent)

    checks: list[ColumnDemandCheck] = []
    for force in forces:
        axial = force.p_kn
        cap_m2 = _capacity_at_axial(curve_m2, axial)
        cap_m3 = _capacity_at_axial(curve_m3, axial)
        if axial >= 0.0:
            axial_ratio = axial / max_axial_capacity if max_axial_capacity > 1e-9 else float("inf")
        else:
            axial_ratio = abs(axial) / minimum_tension_capacity if minimum_tension_capacity > 1e-9 else float("inf")
        m2_ratio = abs(force.m2_knm) / cap_m2 if cap_m2 > 1e-9 else (0.0 if abs(force.m2_knm) < 1e-9 else float("inf"))
        m3_ratio = abs(force.m3_knm) / cap_m3 if cap_m3 > 1e-9 else (0.0 if abs(force.m3_knm) < 1e-9 else float("inf"))
        moment_interaction = (m2_ratio**alpha + m3_ratio**alpha) ** (1.0 / alpha)
        biaxial = max(axial_ratio, moment_interaction)
        checks.append(
            ColumnDemandCheck(
                combination=force.combination,
                end=force.end,
                axial_kn=axial,
                m2_knm=force.m2_knm,
                m3_knm=force.m3_knm,
                m2_capacity_knm=cap_m2,
                m3_capacity_knm=cap_m3,
                axial_utilization=axial_ratio,
                m2_utilization=m2_ratio,
                m3_utilization=m3_ratio,
                biaxial_utilization=biaxial,
            )
        )
    return curve_m2, curve_m3, tuple(checks)


@dataclass(frozen=True)
class _ColumnTieDesign:
    diameter_mm: int
    legs_per_direction: int
    spacing_end_mm: int
    spacing_mid_mm: int
    governing_shear_kn: float
    governing_capacity_kn: float
    maximum_utilization: float


def _select_tie_diameter(preferred: int) -> int:
    return min(TIE_DIAMETERS, key=lambda value: (abs(value - preferred), value))


def _round_down_standard_spacing(maximum_mm: float) -> int:
    feasible = [spacing for spacing in TIE_SPACINGS_MM if spacing <= maximum_mm + 1e-9]
    return max(feasible) if feasible else min(TIE_SPACINGS_MM)


def _column_shear_capacity_kn(
    member: ColumnMember,
    axis: str,
    tie_diameter_mm: int,
    spacing_mm: int,
    settings: DesignSettings,
) -> float:
    """Preliminary ACI-style column shear strength for V2 or V3.

    For a rectangular ETABS section, T3 is the depth associated with M3/V2 and
    T2 is the width associated with M2/V3. A closed tie provides two effective
    legs in either principal direction. Circular columns use a conservative
    equivalent web width equal to the diameter and d = 0.8D.
    """

    if axis not in {"V2", "V3"}:
        raise ValueError("axis must be V2 or V3")
    if member.shape == "Circular":
        bw_mm = member.diameter_mm
        d_mm = 0.80 * member.diameter_mm
    elif axis == "V2":
        bw_mm = member.width_mm
        d_mm = 0.80 * member.depth_mm
    else:
        bw_mm = member.depth_mm
        d_mm = 0.80 * member.width_mm

    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    vc_n = 0.17 * settings.lightweight_factor * sqrt(fc) * bw_mm * d_mm
    av_over_s = 2.0 * _bar_area(tie_diameter_mm) / max(float(spacing_mm), 1e-9)
    vs_n = av_over_s * fy * d_mm
    return settings.shear_phi * (vc_n + vs_n) / 1000.0


def _design_column_ties(
    member: ColumnMember,
    forces: Sequence[ColumnForce],
    layout: ColumnBarLayout,
    settings: DesignSettings,
) -> _ColumnTieDesign:
    tie_diameter = _select_tie_diameter(settings.preferred_stirrup_mm)
    smallest_dimension = (
        member.diameter_mm
        if member.shape == "Circular"
        else min(member.width_mm, member.depth_mm)
    )
    geometric_maximum = min(
        16.0 * layout.diameter_mm,
        48.0 * tie_diameter,
        smallest_dimension,
        300.0,
    )
    maximum_v2 = max(abs(force.v2_kn) for force in forces)
    maximum_v3 = max(abs(force.v3_kn) for force in forces)

    candidates: list[_ColumnTieDesign] = []
    for spacing in TIE_SPACINGS_MM:
        if spacing > geometric_maximum + 1e-9:
            continue
        capacity_v2 = _column_shear_capacity_kn(
            member, "V2", tie_diameter, spacing, settings
        )
        capacity_v3 = _column_shear_capacity_kn(
            member, "V3", tie_diameter, spacing, settings
        )
        utilization_v2 = (
            maximum_v2 / capacity_v2 if capacity_v2 > 1e-12 else float("inf")
        )
        utilization_v3 = (
            maximum_v3 / capacity_v3 if capacity_v3 > 1e-12 else float("inf")
        )
        if utilization_v2 >= utilization_v3:
            governing_shear = maximum_v2
            governing_capacity = capacity_v2
            utilization = utilization_v2
        else:
            governing_shear = maximum_v3
            governing_capacity = capacity_v3
            utilization = utilization_v3
        candidate = _ColumnTieDesign(
            diameter_mm=tie_diameter,
            legs_per_direction=2,
            spacing_end_mm=_round_down_standard_spacing(min(100.0, spacing)),
            spacing_mid_mm=int(spacing),
            governing_shear_kn=governing_shear,
            governing_capacity_kn=governing_capacity,
            maximum_utilization=utilization,
        )
        candidates.append(candidate)
        if utilization <= 1.0 + 1e-9:
            # TIE_SPACINGS_MM is ordered from the greatest spacing downward, so
            # this is the least congested arrangement that passes.
            return candidate

    if not candidates:
        spacing = min(TIE_SPACINGS_MM)
        capacity_v2 = _column_shear_capacity_kn(
            member, "V2", tie_diameter, spacing, settings
        )
        capacity_v3 = _column_shear_capacity_kn(
            member, "V3", tie_diameter, spacing, settings
        )
        utilization_v2 = maximum_v2 / max(capacity_v2, 1e-12)
        utilization_v3 = maximum_v3 / max(capacity_v3, 1e-12)
        return _ColumnTieDesign(
            diameter_mm=tie_diameter,
            legs_per_direction=2,
            spacing_end_mm=spacing,
            spacing_mid_mm=spacing,
            governing_shear_kn=maximum_v2 if utilization_v2 >= utilization_v3 else maximum_v3,
            governing_capacity_kn=capacity_v2 if utilization_v2 >= utilization_v3 else capacity_v3,
            maximum_utilization=max(utilization_v2, utilization_v3),
        )

    return min(candidates, key=lambda item: item.maximum_utilization)


def _slenderness(member: ColumnMember, settings: DesignSettings) -> tuple[float, float]:
    length_mm = member.length_m * 1000.0 * settings.column_effective_length_factor
    if member.shape == "Circular":
        radius_gyration = member.diameter_mm / 4.0
        value = length_mm / max(radius_gyration, 1e-9)
        return value, value
    r2 = member.width_mm / sqrt(12.0)
    r3 = member.depth_mm / sqrt(12.0)
    return length_mm / max(r2, 1e-9), length_mm / max(r3, 1e-9)


def design_column(
    member: ColumnMember,
    forces: Iterable[ColumnForce],
    settings: DesignSettings,
    mark: str,
) -> ColumnDesign:
    force_rows = tuple(forces)
    if not force_rows:
        raise DesignInputError(f"Column '{member.member_id}' has no force-result rows.")
    if member.length_m <= 0.0 or member.gross_area_mm2 <= 0.0:
        raise DesignInputError(f"Column '{member.member_id}' has invalid geometry.")

    candidates = generate_column_layouts(member, settings)
    selected: tuple[
        ColumnBarLayout,
        tuple[InteractionPoint, ...],
        tuple[InteractionPoint, ...],
        tuple[ColumnDemandCheck, ...],
    ] | None = None
    last_candidate = None
    for layout in candidates:
        curve_m2, curve_m3, checks = _evaluate_layout(member, force_rows, layout, settings)
        last_candidate = (layout, curve_m2, curve_m3, checks)
        if checks and max(check.biaxial_utilization for check in checks) <= 1.0 + 1e-9:
            selected = last_candidate
            break
    if selected is None:
        if last_candidate is None:
            raise DesignInputError(f"No reinforcement layout could be evaluated for column '{member.member_id}'.")
        selected = last_candidate

    layout, curve_m2, curve_m3, checks = selected
    governing = max(checks, key=lambda item: item.biaxial_utilization)
    tie_design = _design_column_ties(member, force_rows, layout, settings)
    largest_dimension = member.diameter_mm if member.shape == "Circular" else max(member.width_mm, member.depth_mm)
    confinement_length = max(largest_dimension, member.length_m * 1000.0 / 6.0, 450.0)
    confinement_length = min(confinement_length, member.length_m * 500.0)

    slenderness_m2, slenderness_m3 = _slenderness(member, settings)
    warnings: list[str] = []
    if max(check.biaxial_utilization for check in checks) > 1.0 + 1e-9:
        warnings.append("No available reinforcement layout satisfies the preliminary biaxial interaction check.")
    if tie_design.maximum_utilization > 1.0 + 1e-9:
        warnings.append(
            "The selected tie diameter at the minimum available spacing does not satisfy the preliminary column shear check."
        )
    if layout.ratio > 0.04:
        warnings.append("Longitudinal steel ratio exceeds 4%; review congestion and splice locations.")
    if max(slenderness_m2, slenderness_m3) > settings.slenderness_warning_limit:
        if settings.assume_etabs_pdelta:
            warnings.append("Column exceeds the slenderness warning limit; verify ETABS P-Delta and effective-length assumptions.")
        else:
            warnings.append("Column exceeds the slenderness warning limit and moment magnification is not included.")
    if not settings.assume_etabs_pdelta:
        warnings.append("Imported moments are used without an additional second-order magnification calculation.")
    if layout.count > 8:
        warnings.append(
            "The longitudinal layout needs project-specific crossties or overlapping hoops; the drawing shows the perimeter tie only."
        )
    if max(abs(force.t_knm) for force in force_rows) > 1e-6:
        warnings.append("Column torsion is reported by ETABS but is not included in the column transverse-reinforcement calculation.")

    return ColumnDesign(
        member=member,
        mark=mark,
        layout=layout,
        tie_diameter_mm=tie_design.diameter_mm,
        tie_legs_per_direction=tie_design.legs_per_direction,
        tie_spacing_end_mm=tie_design.spacing_end_mm,
        tie_spacing_mid_mm=tie_design.spacing_mid_mm,
        confinement_length_mm=confinement_length,
        governing_shear_kn=tie_design.governing_shear_kn,
        shear_capacity_kn=tie_design.governing_capacity_kn,
        maximum_shear_utilization=tie_design.maximum_utilization,
        interaction_m2=curve_m2,
        interaction_m3=curve_m3,
        demand_checks=checks,
        slenderness_m2=slenderness_m2,
        slenderness_m3=slenderness_m3,
        maximum_axial_utilization=max(check.axial_utilization for check in checks),
        maximum_m2_utilization=max(check.m2_utilization for check in checks),
        maximum_m3_utilization=max(check.m3_utilization for check in checks),
        maximum_biaxial_utilization=max(check.biaxial_utilization for check in checks),
        governing_combination=governing.combination,
        governing_end=governing.end,
        warnings=tuple(dict.fromkeys(warnings)),
    )
