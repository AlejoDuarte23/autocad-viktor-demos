from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, pi, sqrt
from typing import Iterable

from models import (
    BeamDesign,
    BeamForce,
    BeamMember,
    DesignInputError,
    DesignSettings,
    RebarSelection,
    StirrupSelection,
)


LONGITUDINAL_BAR_DIAMETERS = (12, 16, 20, 25, 32)
STIRRUP_DIAMETERS = (8, 10, 12, 16)
STANDARD_SPACINGS_MM = (300, 250, 225, 200, 175, 150, 125, 100, 75)


@dataclass(frozen=True)
class _BeamDemands:
    top_left_knm: float
    top_mid_knm: float
    top_right_knm: float
    bottom_left_knm: float
    bottom_mid_knm: float
    bottom_right_knm: float
    shear_left_kn: float
    shear_mid_kn: float
    shear_right_kn: float
    torsion_left_knm: float
    torsion_mid_knm: float
    torsion_right_knm: float
    governing_combination: str
    governing_moment_knm: float
    governing_shear_kn: float
    governing_torsion_knm: float


def _bar_area(diameter_mm: float) -> float:
    return pi * diameter_mm**2 / 4.0


def _beta1(fc_mpa: float) -> float:
    if fc_mpa <= 28.0:
        return 0.85
    return max(0.65, 0.85 - 0.05 * ((fc_mpa - 28.0) / 7.0))


def _strain_phi(tension_strain: float, settings: DesignSettings) -> float:
    yield_strain = settings.steel_yield_strength_mpa / settings.steel_modulus_mpa
    if tension_strain <= yield_strain:
        return 0.65
    if tension_strain >= 0.005:
        return settings.beam_phi_flexure_max
    return 0.65 + (settings.beam_phi_flexure_max - 0.65) * (
        (tension_strain - yield_strain) / (0.005 - yield_strain)
    )


def _minimum_beam_steel_mm2(b_mm: float, d_mm: float, settings: DesignSettings) -> float:
    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    return max(0.25 * sqrt(fc) / fy * b_mm * d_mm, 1.4 / fy * b_mm * d_mm)


def _required_flexural_steel_mm2(
    mu_knm: float,
    b_mm: float,
    d_mm: float,
    settings: DesignSettings,
) -> float:
    if mu_knm <= 1e-9:
        return _minimum_beam_steel_mm2(b_mm, d_mm, settings)
    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    phi = settings.beam_phi_flexure_max
    mu_nmm = mu_knm * 1_000_000.0
    coefficient_a = fy * fy / (2.0 * 0.85 * fc * b_mm)
    coefficient_b = -fy * d_mm
    coefficient_c = mu_nmm / phi
    discriminant = coefficient_b * coefficient_b - 4.0 * coefficient_a * coefficient_c
    if discriminant <= 0.0:
        return float("inf")
    root = (-coefficient_b - sqrt(discriminant)) / (2.0 * coefficient_a)
    return max(root, _minimum_beam_steel_mm2(b_mm, d_mm, settings))


def _bar_layout_depth_and_fit(
    count: int,
    diameter_mm: int,
    b_mm: float,
    h_mm: float,
    stirrup_diameter_mm: int,
    cover_mm: float,
) -> tuple[int, float, bool]:
    minimum_clear = max(25.0, float(diameter_mm))
    centerline_width = b_mm - 2.0 * (cover_mm + stirrup_diameter_mm + diameter_mm / 2.0)
    if centerline_width <= 0.0:
        return 99, 0.0, False

    max_per_layer = floor(centerline_width / (diameter_mm + minimum_clear)) + 1
    max_per_layer = max(max_per_layer, 1)
    layers = ceil(count / max_per_layer)
    if layers > 2:
        return layers, 0.0, False

    first_layer_count = min(count, max_per_layer)
    second_layer_count = count - first_layer_count
    if first_layer_count > 1:
        clear_spacing_first = centerline_width / (first_layer_count - 1) - diameter_mm
        if clear_spacing_first + 1e-9 < minimum_clear:
            return layers, 0.0, False
    if second_layer_count > 1:
        clear_spacing_second = centerline_width / (second_layer_count - 1) - diameter_mm
        if clear_spacing_second + 1e-9 < minimum_clear:
            return layers, 0.0, False

    first_center = cover_mm + stirrup_diameter_mm + diameter_mm / 2.0
    if second_layer_count:
        layer_gap = max(25.0, float(diameter_mm))
        second_center = first_center + diameter_mm + layer_gap
        centroid_from_tension_face = (
            first_layer_count * first_center + second_layer_count * second_center
        ) / count
    else:
        centroid_from_tension_face = first_center

    d_mm = h_mm - centroid_from_tension_face
    return layers, d_mm, d_mm > 0.45 * h_mm


def _flexural_capacity(
    as_mm2: float,
    b_mm: float,
    d_mm: float,
    settings: DesignSettings,
) -> tuple[float, float, float]:
    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    a_mm = as_mm2 * fy / (0.85 * fc * b_mm)
    if a_mm <= 0.0 or a_mm >= 2.0 * d_mm:
        return 0.0, 0.0, 0.0
    c_mm = a_mm / _beta1(fc)
    tension_strain = max(0.0, 0.003 * (d_mm - c_mm) / max(c_mm, 1e-9))
    phi = _strain_phi(tension_strain, settings)
    mn_knm = as_mm2 * fy * (d_mm - a_mm / 2.0) / 1_000_000.0
    return phi * mn_knm, tension_strain, phi


def _select_for_diameter(
    mu_knm: float,
    additional_required_as_mm2: float,
    diameter_mm: int,
    member: BeamMember,
    settings: DesignSettings,
) -> RebarSelection:
    bar_area = _bar_area(diameter_mm)
    best_failure: RebarSelection | None = None
    for count in range(max(2, settings.minimum_beam_bars), 25):
        layers, d_mm, fit = _bar_layout_depth_and_fit(
            count,
            diameter_mm,
            member.width_mm,
            member.depth_mm,
            settings.preferred_stirrup_mm,
            settings.concrete_cover_mm,
        )
        if not fit:
            continue
        area = count * bar_area
        required = _required_flexural_steel_mm2(mu_knm, member.width_mm, d_mm, settings)
        required += additional_required_as_mm2
        phi_mn, tension_strain, _ = _flexural_capacity(area, member.width_mm, d_mm, settings)
        utilization = mu_knm / phi_mn if phi_mn > 1e-12 else float("inf")
        selection = RebarSelection(
            count=count,
            diameter_mm=diameter_mm,
            layers=layers,
            area_mm2=area,
            required_area_mm2=required,
            effective_depth_mm=d_mm,
            phi_mn_knm=phi_mn,
            utilization=utilization,
            tension_strain=tension_strain,
            fits=area + 1e-9 >= required and utilization <= 1.0 + 1e-9,
        )
        best_failure = selection
        if selection.fits:
            return selection

    if best_failure is not None:
        return RebarSelection(**{**best_failure.__dict__, "fits": False})

    nominal_d = max(member.depth_mm - settings.concrete_cover_mm - diameter_mm, 1.0)
    required = _required_flexural_steel_mm2(mu_knm, member.width_mm, nominal_d, settings)
    return RebarSelection(
        count=0,
        diameter_mm=diameter_mm,
        layers=0,
        area_mm2=0.0,
        required_area_mm2=required + additional_required_as_mm2,
        effective_depth_mm=nominal_d,
        phi_mn_knm=0.0,
        utilization=float("inf"),
        tension_strain=0.0,
        fits=False,
    )


def _diameter_order(preferred: int, options: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted(options, key=lambda value: (abs(value - preferred), value)))


def _select_longitudinal_regions(
    member: BeamMember,
    demands: _BeamDemands,
    torsion_longitudinal_area_mm2: float,
    settings: DesignSettings,
) -> tuple[RebarSelection, ...]:
    moment_demands = (
        demands.top_left_knm,
        demands.top_mid_knm,
        demands.top_right_knm,
        demands.bottom_left_knm,
        demands.bottom_mid_knm,
        demands.bottom_right_knm,
    )
    extra_per_face = torsion_longitudinal_area_mm2 / 2.0

    passing_sets: list[tuple[float, tuple[RebarSelection, ...]]] = []
    all_sets: list[tuple[float, tuple[RebarSelection, ...]]] = []
    for diameter in _diameter_order(settings.preferred_beam_bar_mm, LONGITUDINAL_BAR_DIAMETERS):
        selections = tuple(
            _select_for_diameter(mu, extra_per_face, diameter, member, settings)
            for mu in moment_demands
        )
        score = sum(item.area_mm2 for item in selections)
        score += abs(diameter - settings.preferred_beam_bar_mm) * 10.0
        score += sum(max(0, item.layers - 1) * 1500.0 for item in selections)
        all_sets.append((score, selections))
        if all(item.fits for item in selections):
            passing_sets.append((score, selections))

    if passing_sets:
        return min(passing_sets, key=lambda item: item[0])[1]

    # Return the set with the largest total capacity so the failure remains visible in the table/drawing.
    return max(
        all_sets,
        key=lambda item: sum(
            0.0 if selection.phi_mn_knm <= 0.0 else selection.phi_mn_knm
            for selection in item[1]
        ),
    )[1]


def _torsion_requirements(
    member: BeamMember,
    maximum_torsion_knm: float,
    settings: DesignSettings,
) -> tuple[float, float, float, float, float]:
    """Return At/s, total longitudinal torsion steel, threshold, Ao and ph.

    This is a deliberately transparent 45-degree space-truss approximation for preliminary sizing.
    """

    b = member.width_mm
    h = member.depth_mm
    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    cover_to_center = settings.concrete_cover_mm + settings.preferred_stirrup_mm / 2.0
    bo = max(b - 2.0 * cover_to_center, 0.25 * b)
    ho = max(h - 2.0 * cover_to_center, 0.25 * h)
    ao = 0.85 * bo * ho
    ph = 2.0 * (bo + ho)
    acp = b * h
    pcp = 2.0 * (b + h)
    threshold_knm = 0.083 * sqrt(fc) * acp * acp / pcp / 1_000_000.0

    if not settings.design_torsion or maximum_torsion_knm <= settings.shear_phi * threshold_knm:
        return 0.0, 0.0, threshold_knm, ao, ph

    at_over_s = (
        maximum_torsion_knm * 1_000_000.0
        / (settings.shear_phi * 2.0 * ao * fy)
    )
    longitudinal_area = at_over_s * ph
    return at_over_s, longitudinal_area, threshold_knm, ao, ph


def _select_stirrups(
    member: BeamMember,
    shear_kn: float,
    torsion_knm: float,
    representative_d_mm: float,
    torsion_at_over_s: float,
    torsion_threshold_knm: float,
    ao_mm2: float,
    ph_mm: float,
    settings: DesignSettings,
) -> StirrupSelection:
    fc = settings.concrete_strength_mpa
    fy = settings.steel_yield_strength_mpa
    b = member.width_mm
    d = representative_d_mm
    vc_n = 0.17 * settings.lightweight_factor * sqrt(fc) * b * d
    vs_required_n = max(0.0, shear_kn * 1000.0 / settings.shear_phi - vc_n)
    shear_av_over_s = vs_required_n / (fy * d) if d > 0.0 else float("inf")
    minimum_av_over_s = max(0.062 * sqrt(fc) * b / fy, 0.35 * b / fy)
    required_av_over_s = max(minimum_av_over_s, shear_av_over_s) + 2.0 * torsion_at_over_s

    max_spacing = min(d / 2.0, 600.0)
    torsion_is_active = torsion_at_over_s > 0.0 and torsion_knm > settings.shear_phi * torsion_threshold_knm
    if torsion_is_active:
        max_spacing = min(max_spacing, ph_mm / 8.0, 300.0)
    max_spacing = max(75.0, max_spacing)

    options = _diameter_order(settings.preferred_stirrup_mm, STIRRUP_DIAMETERS)
    candidates: list[StirrupSelection] = []
    for diameter in options:
        area_one_leg = _bar_area(diameter)
        for spacing in STANDARD_SPACINGS_MM:
            if spacing > max_spacing + 1e-9:
                continue
            provided = 2.0 * area_one_leg / spacing
            vs_n = provided * fy * d
            shear_capacity_kn = settings.shear_phi * (vc_n + vs_n) / 1000.0
            shear_util = shear_kn / shear_capacity_kn if shear_capacity_kn > 1e-12 else float("inf")

            if torsion_is_active:
                provided_at_over_s = area_one_leg / spacing
                torsion_capacity = (
                    settings.shear_phi * 2.0 * ao_mm2 * provided_at_over_s * fy / 1_000_000.0
                )
            else:
                torsion_capacity = settings.shear_phi * torsion_threshold_knm
            torsion_util = torsion_knm / torsion_capacity if torsion_capacity > 1e-12 else 0.0

            candidate = StirrupSelection(
                diameter_mm=diameter,
                legs=2,
                spacing_mm=int(spacing),
                required_av_over_s=required_av_over_s,
                provided_av_over_s=provided,
                shear_capacity_kn=shear_capacity_kn,
                shear_utilization=shear_util,
                torsion_capacity_knm=torsion_capacity,
                torsion_utilization=torsion_util,
            )
            candidates.append(candidate)
            if provided + 1e-12 >= required_av_over_s and shear_util <= 1.0 + 1e-9 and torsion_util <= 1.0 + 1e-9:
                return candidate

    if not candidates:
        raise DesignInputError(
            f"Beam '{member.member_id}' is too shallow to place the available stirrup arrangements."
        )
    return max(candidates, key=lambda item: item.provided_av_over_s)


def _extract_demands(member: BeamMember, forces: Iterable[BeamForce]) -> _BeamDemands:
    rows = list(forces)
    if not rows:
        raise DesignInputError(f"Beam '{member.member_id}' has no force-result rows.")
    length = max(member.length_m, 1e-9)

    zone_rows: dict[str, list[BeamForce]] = {"left": [], "mid": [], "right": []}
    for row in rows:
        ratio = min(1.0, max(0.0, row.station_m / length))
        if ratio <= 0.25:
            zone_rows["left"].append(row)
        elif ratio >= 0.75:
            zone_rows["right"].append(row)
        else:
            zone_rows["mid"].append(row)

    # A model with only end stations still receives a conservative middle envelope.
    if not zone_rows["mid"]:
        zone_rows["mid"] = rows
    if not zone_rows["left"]:
        zone_rows["left"] = [min(rows, key=lambda row: row.station_m)]
    if not zone_rows["right"]:
        zone_rows["right"] = [max(rows, key=lambda row: row.station_m)]

    def top(zone: str) -> float:
        return max((max(0.0, -row.m3_knm) for row in zone_rows[zone]), default=0.0)

    def bottom(zone: str) -> float:
        return max((max(0.0, row.m3_knm) for row in zone_rows[zone]), default=0.0)

    def shear(zone: str) -> float:
        return max((abs(row.v2_kn) for row in zone_rows[zone]), default=0.0)

    def torsion(zone: str) -> float:
        return max((abs(row.t_knm) for row in zone_rows[zone]), default=0.0)

    governing_row = max(
        rows,
        key=lambda row: max(
            abs(row.m3_knm),
            abs(row.v2_kn) * length / 4.0,
            abs(row.t_knm),
        ),
    )
    return _BeamDemands(
        top_left_knm=top("left"),
        top_mid_knm=top("mid"),
        top_right_knm=top("right"),
        bottom_left_knm=bottom("left"),
        bottom_mid_knm=bottom("mid"),
        bottom_right_knm=bottom("right"),
        shear_left_kn=shear("left"),
        shear_mid_kn=shear("mid"),
        shear_right_kn=shear("right"),
        torsion_left_knm=torsion("left"),
        torsion_mid_knm=torsion("mid"),
        torsion_right_knm=torsion("right"),
        governing_combination=governing_row.combination,
        governing_moment_knm=abs(governing_row.m3_knm),
        governing_shear_kn=abs(governing_row.v2_kn),
        governing_torsion_knm=abs(governing_row.t_knm),
    )


def design_beam(
    member: BeamMember,
    forces: Iterable[BeamForce],
    settings: DesignSettings,
    mark: str,
) -> BeamDesign:
    if member.width_mm <= 0.0 or member.depth_mm <= 0.0 or member.length_m <= 0.0:
        raise DesignInputError(f"Beam '{member.member_id}' has invalid geometry.")
    if member.depth_mm <= 2.0 * settings.concrete_cover_mm + 100.0:
        raise DesignInputError(
            f"Beam '{member.member_id}' is too shallow for the selected cover and reinforcement."
        )

    demands = _extract_demands(member, forces)
    maximum_torsion = max(
        demands.torsion_left_knm,
        demands.torsion_mid_knm,
        demands.torsion_right_knm,
    )
    at_over_s, torsion_longitudinal, torsion_threshold, ao, ph = _torsion_requirements(
        member, maximum_torsion, settings
    )
    longitudinal = _select_longitudinal_regions(member, demands, torsion_longitudinal, settings)
    representative_d = min(item.effective_depth_mm for item in longitudinal if item.effective_depth_mm > 0.0)

    stirrup_left = _select_stirrups(
        member,
        demands.shear_left_kn,
        demands.torsion_left_knm,
        representative_d,
        at_over_s if demands.torsion_left_knm > settings.shear_phi * torsion_threshold else 0.0,
        torsion_threshold,
        ao,
        ph,
        settings,
    )
    stirrup_mid = _select_stirrups(
        member,
        demands.shear_mid_kn,
        demands.torsion_mid_knm,
        representative_d,
        at_over_s if demands.torsion_mid_knm > settings.shear_phi * torsion_threshold else 0.0,
        torsion_threshold,
        ao,
        ph,
        settings,
    )
    stirrup_right = _select_stirrups(
        member,
        demands.shear_right_kn,
        demands.torsion_right_knm,
        representative_d,
        at_over_s if demands.torsion_right_knm > settings.shear_phi * torsion_threshold else 0.0,
        torsion_threshold,
        ao,
        ph,
        settings,
    )

    warnings: list[str] = []
    if not all(item.fits for item in longitudinal):
        warnings.append("Available bars do not satisfy flexure and placement in one or two layers.")
    if any(item.layers > 1 for item in longitudinal):
        warnings.append("Two longitudinal reinforcement layers are required in at least one region.")
    if any(item.tension_strain < 0.005 and item.utilization > 0.05 for item in longitudinal):
        warnings.append("At least one flexural region is not tension-controlled at εt = 0.005.")
    if settings.design_torsion and maximum_torsion > settings.shear_phi * torsion_threshold:
        warnings.append("Torsion reinforcement uses a preliminary 45-degree space-truss approximation.")
    if not settings.design_torsion and maximum_torsion > settings.shear_phi * torsion_threshold:
        warnings.append("Torsion exceeds the preliminary threshold but torsion design is disabled.")

    support_zone_length_m = min(2.0 * representative_d / 1000.0, 0.25 * member.length_m)
    if 2.0 * support_zone_length_m >= 0.9 * member.length_m:
        warnings.append("Support stirrup zones occupy nearly the full beam span.")

    maximum_flexure = max(item.utilization for item in longitudinal)
    maximum_shear = max(
        stirrup_left.shear_utilization,
        stirrup_mid.shear_utilization,
        stirrup_right.shear_utilization,
    )
    maximum_torsion_util = max(
        stirrup_left.torsion_utilization,
        stirrup_mid.torsion_utilization,
        stirrup_right.torsion_utilization,
    )

    return BeamDesign(
        member=member,
        mark=mark,
        top_left=longitudinal[0],
        top_mid=longitudinal[1],
        top_right=longitudinal[2],
        bottom_left=longitudinal[3],
        bottom_mid=longitudinal[4],
        bottom_right=longitudinal[5],
        stirrup_left=stirrup_left,
        stirrup_mid=stirrup_mid,
        stirrup_right=stirrup_right,
        support_zone_length_m=support_zone_length_m,
        maximum_flexural_utilization=maximum_flexure,
        maximum_shear_utilization=maximum_shear,
        maximum_torsion_utilization=maximum_torsion_util,
        governing_combination=demands.governing_combination,
        governing_moment_knm=demands.governing_moment_knm,
        governing_shear_kn=demands.governing_shear_kn,
        governing_torsion_knm=demands.governing_torsion_knm,
        warnings=tuple(dict.fromkeys(warnings)),
    )
