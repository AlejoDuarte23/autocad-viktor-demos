from __future__ import annotations

from math import ceil
from typing import Any, Sequence

from viktor.external.autocad import AcRegenType

from autocad_common import (
    DrawingSettings,
    add_centered_rectangle,
    add_circle,
    add_horizontal_dimension,
    add_line,
    add_polyline,
    add_rectangle,
    add_text,
    add_text_lines,
    add_vertical_dimension,
    draw_table,
    ensure_standard_layers,
    layer_name,
    limited_positions,
)
from models import BeamDesign, ColumnBarLayout, ColumnDesign, DesignSettings, ProjectDesign, RebarSelection


def _unique_sorted(values: Sequence[float], tolerance: float = 1e-6) -> list[float]:
    result: list[float] = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
    return result


def _beam_section_bar_coordinates(
    selection: RebarSelection,
    x_min_m: float,
    x_max_m: float,
    face_y_m: float,
    *,
    top: bool,
) -> list[tuple[float, float, float]]:
    if selection.count <= 0:
        return []
    layers = max(1, selection.layers)
    counts: list[int] = []
    remaining = selection.count
    for layer_index in range(layers):
        layers_left = layers - layer_index
        count = int(ceil(remaining / layers_left))
        counts.append(count)
        remaining -= count

    diameter_m = selection.diameter_mm / 1000.0
    layer_gap_m = max(0.025, diameter_m)
    coordinates: list[tuple[float, float, float]] = []
    for layer_index, count in enumerate(counts):
        if count <= 0:
            continue
        if count == 1:
            x_values = [(x_min_m + x_max_m) / 2.0]
        else:
            spacing = (x_max_m - x_min_m) / (count - 1)
            x_values = [x_min_m + index * spacing for index in range(count)]
        offset = layer_index * (diameter_m + layer_gap_m)
        y_value = face_y_m - offset if top else face_y_m + offset
        coordinates.extend((x_value, y_value, diameter_m / 2.0) for x_value in x_values)
    return coordinates


def _draw_beam_cross_section(
    model_space: Any,
    beam: BeamDesign,
    center_x_m: float,
    center_y_m: float,
    top_selection: RebarSelection,
    bottom_selection: RebarSelection,
    stirrup_diameter_mm: int,
    section_label: str,
    settings: DrawingSettings,
    design_settings: DesignSettings,
) -> None:
    outline_layer = layer_name(settings, "OUTLINE")
    stirrup_layer = layer_name(settings, "STIRRUP")
    rebar_layer = layer_name(settings, "REBAR")
    text_layer = layer_name(settings, "TEXT")
    b_m = beam.member.width_mm / 1000.0
    h_m = beam.member.depth_mm / 1000.0
    x_min = center_x_m - b_m / 2.0
    x_max = center_x_m + b_m / 2.0
    y_min = center_y_m - h_m / 2.0
    y_max = center_y_m + h_m / 2.0
    add_rectangle(model_space, x_min, y_min, x_max, y_max, outline_layer, settings)

    cover_m = design_settings.concrete_cover_mm / 1000.0
    inset = min(cover_m, 0.22 * min(b_m, h_m))
    add_rectangle(
        model_space,
        x_min + inset,
        y_min + inset,
        x_max - inset,
        y_max - inset,
        stirrup_layer,
        settings,
    )

    stirrup_diameter_m = stirrup_diameter_mm / 1000.0
    top_diameter_m = top_selection.diameter_mm / 1000.0
    bottom_diameter_m = bottom_selection.diameter_mm / 1000.0
    top_face_y = y_max - inset - stirrup_diameter_m - top_diameter_m / 2.0
    bottom_face_y = y_min + inset + stirrup_diameter_m + bottom_diameter_m / 2.0
    bar_x_min_top = x_min + inset + stirrup_diameter_m + top_diameter_m / 2.0
    bar_x_max_top = x_max - inset - stirrup_diameter_m - top_diameter_m / 2.0
    bar_x_min_bottom = x_min + inset + stirrup_diameter_m + bottom_diameter_m / 2.0
    bar_x_max_bottom = x_max - inset - stirrup_diameter_m - bottom_diameter_m / 2.0

    for x_m, y_m, radius_m in _beam_section_bar_coordinates(
        top_selection,
        bar_x_min_top,
        bar_x_max_top,
        top_face_y,
        top=True,
    ):
        add_circle(model_space, x_m, y_m, radius_m, rebar_layer, settings)
    for x_m, y_m, radius_m in _beam_section_bar_coordinates(
        bottom_selection,
        bar_x_min_bottom,
        bar_x_max_bottom,
        bottom_face_y,
        top=False,
    ):
        add_circle(model_space, x_m, y_m, radius_m, rebar_layer, settings)

    add_text(
        model_space,
        section_label,
        center_x_m,
        y_min - 0.25,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.72,
        center=True,
    )
    add_text(
        model_space,
        f"T {top_selection.description} / B {bottom_selection.description}",
        center_x_m,
        y_min - 0.48,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.64,
        center=True,
    )


def _draw_beam_detail(
    model_space: Any,
    beam: BeamDesign,
    cell_x_m: float,
    cell_top_y_m: float,
    cell_width_m: float,
    cell_height_m: float,
    settings: DrawingSettings,
    design_settings: DesignSettings,
) -> None:
    outline_layer = layer_name(settings, "OUTLINE")
    support_layer = layer_name(settings, "SUPPORT")
    rebar_layer = layer_name(settings, "REBAR")
    stirrup_layer = layer_name(settings, "STIRRUP")
    text_layer = layer_name(settings, "TEXT")
    dim_layer = layer_name(settings, "DIM")
    aux_layer = layer_name(settings, "AUX")

    member = beam.member
    span = member.length_m
    depth_m = member.depth_mm / 1000.0
    x0 = cell_x_m + 1.05
    x1 = x0 + span
    beam_center_y = cell_top_y_m - 1.25
    y_bottom = beam_center_y - depth_m / 2.0
    y_top = beam_center_y + depth_m / 2.0
    support_width = max(0.35, min(0.75, 0.8 * depth_m))
    support_height = depth_m + 0.85

    add_text(
        model_space,
        f"BEAM {beam.mark} / {member.label} · {member.story} · {member.section_name}",
        cell_x_m + cell_width_m / 2.0,
        cell_top_y_m - 0.20,
        text_layer,
        settings,
        height_m=settings.text_height_m * 1.08,
        center=True,
    )
    add_rectangle(model_space, x0, y_bottom, x1, y_top, outline_layer, settings)
    add_centered_rectangle(model_space, x0, beam_center_y, support_width, support_height, support_layer, settings)
    add_centered_rectangle(model_space, x1, beam_center_y, support_width, support_height, support_layer, settings)
    add_line(model_space, (x0, beam_center_y - support_height / 2.0), (x0, beam_center_y + support_height / 2.0), aux_layer, settings)
    add_line(model_space, (x1, beam_center_y - support_height / 2.0), (x1, beam_center_y + support_height / 2.0), aux_layer, settings)

    top_y = y_top - max(0.05, 0.08 * depth_m)
    top_second_y = top_y - max(0.045, beam.top_left.diameter_mm / 1000.0 + 0.025)
    bottom_y = y_bottom + max(0.05, 0.08 * depth_m)
    bottom_second_y = bottom_y + max(0.045, beam.bottom_mid.diameter_mm / 1000.0 + 0.025)
    anchorage_left = support_width / 2.0
    anchorage_right = support_width / 2.0
    development_factor = design_settings.development_length_factor
    left_extension = min(
        0.48 * span,
        max(0.30 * span, development_factor * beam.top_left.diameter_mm / 1000.0),
    )
    right_extension = min(
        0.48 * span,
        max(0.30 * span, development_factor * beam.top_right.diameter_mm / 1000.0),
    )

    # Continuous bars and additional support/span bars in longitudinal elevation.
    add_polyline(
        model_space,
        ((x0 - anchorage_left, top_y - 0.08), (x0 - anchorage_left, top_y), (x1 + anchorage_right, top_y), (x1 + anchorage_right, top_y - 0.08)),
        rebar_layer,
        settings,
    )
    add_polyline(
        model_space,
        ((x0 - anchorage_left, bottom_y + 0.08), (x0 - anchorage_left, bottom_y), (x1 + anchorage_right, bottom_y), (x1 + anchorage_right, bottom_y + 0.08)),
        rebar_layer,
        settings,
    )
    if beam.top_left.area_mm2 > beam.top_mid.area_mm2 + 1e-6:
        add_line(model_space, (x0 - anchorage_left, top_second_y), (x0 + left_extension, top_second_y), rebar_layer, settings)
    if beam.top_right.area_mm2 > beam.top_mid.area_mm2 + 1e-6:
        add_line(model_space, (x1 - right_extension, top_second_y), (x1 + anchorage_right, top_second_y), rebar_layer, settings)
    if beam.bottom_mid.area_mm2 > min(beam.bottom_left.area_mm2, beam.bottom_right.area_mm2) + 1e-6:
        add_line(model_space, (x0 + 0.18 * span, bottom_second_y), (x1 - 0.18 * span, bottom_second_y), rebar_layer, settings)

    zone = min(beam.support_zone_length_m, span / 2.0)
    zone_limits = (x0, x0 + zone, x1 - zone, x1)
    requested = (
        (x0, x0 + zone, beam.stirrup_left.spacing_mm),
        (x0 + zone, x1 - zone, beam.stirrup_mid.spacing_mm),
        (x1 - zone, x1, beam.stirrup_right.spacing_mm),
    )
    all_stirrups: list[float] = []
    simplified = False
    per_zone_limit = max(4, settings.maximum_stirrup_symbols_per_member // 3)
    for start, end, spacing in requested:
        positions, was_limited = limited_positions(start, end, spacing, per_zone_limit)
        all_stirrups.extend(positions)
        simplified = simplified or was_limited
    for x_value in _unique_sorted(all_stirrups, tolerance=1e-4):
        add_line(
            model_space,
            (x_value, y_bottom + 0.035),
            (x_value, y_top - 0.035),
            stirrup_layer,
            settings,
        )
    for x_value in zone_limits[1:3]:
        add_line(model_space, (x_value, y_bottom - 0.10), (x_value, y_top + 0.10), aux_layer, settings)

    add_horizontal_dimension(
        model_space,
        x0,
        x1,
        y_top + 0.05,
        y_top + 0.55,
        dim_layer,
        settings,
        text=f"L = {span:.2f} m",
    )
    if zone > 0.05:
        add_horizontal_dimension(model_space, x0, x0 + zone, y_bottom - 0.03, y_bottom - 0.42, dim_layer, settings, text=f"{zone:.2f}")
        add_horizontal_dimension(model_space, x1 - zone, x1, y_bottom - 0.03, y_bottom - 0.42, dim_layer, settings, text=f"{zone:.2f}")

    labels_y = y_top + 0.86
    add_text(model_space, f"TOP L: {beam.top_left.description}", x0 + 0.04 * span, labels_y, text_layer, settings, height_m=settings.text_height_m * 0.72)
    add_text(model_space, f"TOP M: {beam.top_mid.description}", x0 + 0.40 * span, labels_y, text_layer, settings, height_m=settings.text_height_m * 0.72)
    add_text(model_space, f"TOP R: {beam.top_right.description}", x0 + 0.74 * span, labels_y, text_layer, settings, height_m=settings.text_height_m * 0.72)
    add_text(model_space, f"BOT L: {beam.bottom_left.description}", x0 + 0.04 * span, y_bottom - 0.72, text_layer, settings, height_m=settings.text_height_m * 0.72)
    add_text(model_space, f"BOT M: {beam.bottom_mid.description}", x0 + 0.40 * span, y_bottom - 0.72, text_layer, settings, height_m=settings.text_height_m * 0.72)
    add_text(model_space, f"BOT R: {beam.bottom_right.description}", x0 + 0.74 * span, y_bottom - 0.72, text_layer, settings, height_m=settings.text_height_m * 0.72)

    stirrup_note_y = y_bottom - 0.98
    add_text(model_space, f"L: {beam.stirrup_left.description}", x0, stirrup_note_y, text_layer, settings, height_m=settings.text_height_m * 0.66)
    add_text(model_space, f"MID: {beam.stirrup_mid.description}", x0 + 0.38 * span, stirrup_note_y, text_layer, settings, height_m=settings.text_height_m * 0.66)
    add_text(model_space, f"R: {beam.stirrup_right.description}", x0 + 0.74 * span, stirrup_note_y, text_layer, settings, height_m=settings.text_height_m * 0.66)

    section_y = cell_top_y_m - cell_height_m + 1.05
    section_centers = (x0 + 0.18 * span, x0 + 0.50 * span, x0 + 0.82 * span)
    _draw_beam_cross_section(
        model_space, beam, section_centers[0], section_y, beam.top_left, beam.bottom_left,
        beam.stirrup_left.diameter_mm, "SECTION L", settings, design_settings
    )
    _draw_beam_cross_section(
        model_space, beam, section_centers[1], section_y, beam.top_mid, beam.bottom_mid,
        beam.stirrup_mid.diameter_mm, "SECTION MID", settings, design_settings
    )
    _draw_beam_cross_section(
        model_space, beam, section_centers[2], section_y, beam.top_right, beam.bottom_right,
        beam.stirrup_right.diameter_mm, "SECTION R", settings, design_settings
    )

    notes = [
        f"Mu={beam.governing_moment_knm:.1f} kN·m · Vu={beam.governing_shear_kn:.1f} kN · Tu={beam.governing_torsion_knm:.1f} kN·m",
        f"Governing combo: {beam.governing_combination} · Flex={beam.maximum_flexural_utilization:.3f} · Shear={beam.maximum_shear_utilization:.3f} · Torsion={beam.maximum_torsion_utilization:.3f}",
        f"STATUS: {beam.status}",
    ]
    if simplified:
        notes.append("Stirrup symbols were reduced for drawing performance; labels give the designed spacing.")
    if beam.warnings:
        notes.append("Warnings: " + "; ".join(beam.warnings))
    add_text_lines(
        model_space,
        notes,
        x0,
        cell_top_y_m - cell_height_m + 0.38,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.62,
        line_spacing=1.35,
    )


def _projected_column_bar_x(layout: ColumnBarLayout) -> list[float]:
    return _unique_sorted([coordinate[0] / 1000.0 for coordinate in layout.coordinates_mm], tolerance=0.002)


def _draw_column_section(
    model_space: Any,
    column: ColumnDesign,
    center_x_m: float,
    center_y_m: float,
    settings: DrawingSettings,
    design_settings: DesignSettings,
) -> None:
    outline_layer = layer_name(settings, "OUTLINE")
    stirrup_layer = layer_name(settings, "STIRRUP")
    rebar_layer = layer_name(settings, "REBAR")
    text_layer = layer_name(settings, "TEXT")
    member = column.member
    radius_bar = max(0.007, column.layout.diameter_mm / 2000.0)

    if member.shape == "Circular":
        diameter_m = member.diameter_mm / 1000.0
        add_circle(model_space, center_x_m, center_y_m, diameter_m / 2.0, outline_layer, settings)
        tie_radius = max(0.02, diameter_m / 2.0 - design_settings.concrete_cover_mm / 1000.0)
        add_circle(model_space, center_x_m, center_y_m, tie_radius, stirrup_layer, settings)
    else:
        width_m = member.width_mm / 1000.0
        depth_m = member.depth_mm / 1000.0
        add_centered_rectangle(model_space, center_x_m, center_y_m, width_m, depth_m, outline_layer, settings)
        inset = min(design_settings.concrete_cover_mm / 1000.0, 0.20 * min(width_m, depth_m))
        add_centered_rectangle(
            model_space,
            center_x_m,
            center_y_m,
            width_m - 2.0 * inset,
            depth_m - 2.0 * inset,
            stirrup_layer,
            settings,
        )

    for x_mm, y_mm in column.layout.coordinates_mm:
        add_circle(
            model_space,
            center_x_m + x_mm / 1000.0,
            center_y_m + y_mm / 1000.0,
            radius_bar,
            rebar_layer,
            settings,
        )
    add_text(
        model_space,
        f"SECTION {column.mark} · {column.layout.description}",
        center_x_m,
        center_y_m - (member.depth_mm if member.shape == "Rectangular" else member.diameter_mm) / 2000.0 - 0.30,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.74,
        center=True,
    )


def _draw_column_detail(
    model_space: Any,
    column: ColumnDesign,
    cell_x_m: float,
    cell_top_y_m: float,
    cell_width_m: float,
    cell_height_m: float,
    settings: DrawingSettings,
    design_settings: DesignSettings,
) -> None:
    outline_layer = layer_name(settings, "OUTLINE")
    support_layer = layer_name(settings, "SUPPORT")
    rebar_layer = layer_name(settings, "REBAR")
    stirrup_layer = layer_name(settings, "STIRRUP")
    text_layer = layer_name(settings, "TEXT")
    dim_layer = layer_name(settings, "DIM")
    aux_layer = layer_name(settings, "AUX")

    member = column.member
    height_m = member.length_m
    section_width_m = (member.diameter_mm if member.shape == "Circular" else member.width_mm) / 1000.0
    elevation_width = max(0.45, min(0.85, section_width_m))
    center_x = cell_x_m + 1.35
    y_top = cell_top_y_m - 0.85
    y_bottom = y_top - height_m
    x_min = center_x - elevation_width / 2.0
    x_max = center_x + elevation_width / 2.0

    add_text(
        model_space,
        f"COLUMN {column.mark} / {member.label} · {member.story} · {member.section_name}",
        cell_x_m + cell_width_m / 2.0,
        cell_top_y_m - 0.18,
        text_layer,
        settings,
        height_m=settings.text_height_m * 1.08,
        center=True,
    )
    add_rectangle(model_space, x_min, y_bottom, x_max, y_top, outline_layer, settings)
    add_line(model_space, (cell_x_m + 0.35, y_bottom), (cell_x_m + 2.35, y_bottom), support_layer, settings)
    add_line(model_space, (cell_x_m + 0.35, y_top), (cell_x_m + 2.35, y_top), support_layer, settings)
    add_text(model_space, "LOWER FLOOR", cell_x_m + 0.35, y_bottom - 0.22, text_layer, settings, height_m=settings.text_height_m * 0.62)
    add_text(model_space, "UPPER FLOOR", cell_x_m + 0.35, y_top + 0.10, text_layer, settings, height_m=settings.text_height_m * 0.62)

    projected = _projected_column_bar_x(column.layout)
    if len(projected) > 10:
        indices = {round(index * (len(projected) - 1) / 9) for index in range(10)}
        projected = [projected[index] for index in sorted(indices)]
    if not projected:
        projected = [-0.35 * elevation_width, 0.35 * elevation_width]
    scale = elevation_width / max(section_width_m, 1e-9)
    for x_local in projected:
        x_value = center_x + x_local * scale
        add_line(model_space, (x_value, y_bottom - 0.08), (x_value, y_top + 0.08), rebar_layer, settings)

    confinement_m = min(column.confinement_length_mm / 1000.0, 0.48 * height_m)
    tie_zones = (
        (y_bottom, y_bottom + confinement_m, column.tie_spacing_end_mm),
        (y_bottom + confinement_m, y_top - confinement_m, column.tie_spacing_mid_mm),
        (y_top - confinement_m, y_top, column.tie_spacing_end_mm),
    )
    tie_positions: list[float] = []
    simplified = False
    per_zone_limit = max(4, settings.maximum_stirrup_symbols_per_member // 3)
    for start, end, spacing in tie_zones:
        positions, was_limited = limited_positions(start, end, spacing, per_zone_limit)
        tie_positions.extend(positions)
        simplified = simplified or was_limited
    for y_value in _unique_sorted(tie_positions, tolerance=1e-4):
        add_line(model_space, (x_min + 0.025, y_value), (x_max - 0.025, y_value), stirrup_layer, settings)
    add_line(model_space, (x_min - 0.12, y_bottom + confinement_m), (x_max + 0.12, y_bottom + confinement_m), aux_layer, settings)
    add_line(model_space, (x_min - 0.12, y_top - confinement_m), (x_max + 0.12, y_top - confinement_m), aux_layer, settings)

    add_vertical_dimension(
        model_space,
        y_bottom,
        y_top,
        x_min - 0.02,
        x_min - 0.52,
        dim_layer,
        settings,
        text=f"H = {height_m:.2f} m",
    )
    add_vertical_dimension(
        model_space,
        y_bottom,
        y_bottom + confinement_m,
        x_max + 0.02,
        x_max + 0.40,
        dim_layer,
        settings,
        text=f"Lo = {confinement_m:.2f} m",
    )

    section_center_x = cell_x_m + 3.40
    section_center_y = cell_top_y_m - 1.75
    _draw_column_section(
        model_space, column, section_center_x, section_center_y, settings, design_settings
    )

    if member.shape == "Circular":
        section_text = f"%%c{member.diameter_mm:.0f} mm"
    else:
        section_text = f"{member.width_mm:.0f} x {member.depth_mm:.0f} mm"
    notes = [
        f"Section: {section_text} · Longitudinal: {column.layout.description} · rho={column.layout.ratio:.4f}",
        f"Ties: %%c{column.tie_diameter_mm} @ {column.tie_spacing_end_mm} mm in end zones; @ {column.tie_spacing_mid_mm} mm at mid-height",
        f"P-M2={column.maximum_m2_utilization:.3f} · P-M3={column.maximum_m3_utilization:.3f} · Biaxial={column.maximum_biaxial_utilization:.3f}",
        f"Column shear: Vu={column.governing_shear_kn:.1f} kN · phiVn={column.shear_capacity_kn:.1f} kN · util={column.maximum_shear_utilization:.3f}",
        f"Slenderness L/r: axis 2={column.slenderness_m2:.1f}; axis 3={column.slenderness_m3:.1f}",
        f"Governing: {column.governing_combination} / {column.governing_end}-end · STATUS: {column.status}",
    ]
    if simplified:
        notes.append("Tie symbols were reduced for drawing performance; labels give the designed spacing.")
    if column.warnings:
        notes.append("Warnings: " + "; ".join(column.warnings))
    add_text_lines(
        model_space,
        notes,
        cell_x_m + 2.45,
        cell_top_y_m - 3.05,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.64,
        line_spacing=1.38,
    )


def _beam_schedule_rows(beams: Sequence[BeamDesign]) -> list[list[object]]:
    return [
        [
            beam.mark,
            beam.member.story,
            f"{beam.member.width_mm:.0f}x{beam.member.depth_mm:.0f}",
            f"{beam.top_left.description}/{beam.top_mid.description}/{beam.top_right.description}",
            f"{beam.bottom_left.description}/{beam.bottom_mid.description}/{beam.bottom_right.description}",
            f"{beam.stirrup_left.description}; {beam.stirrup_mid.description}; {beam.stirrup_right.description}",
            beam.status,
        ]
        for beam in beams
    ]


def _column_schedule_rows(columns: Sequence[ColumnDesign]) -> list[list[object]]:
    rows: list[list[object]] = []
    for column in columns:
        member = column.member
        section = f"%%c{member.diameter_mm:.0f}" if member.shape == "Circular" else f"{member.width_mm:.0f}x{member.depth_mm:.0f}"
        rows.append(
            [
                column.mark,
                member.story,
                section,
                column.layout.description,
                f"%%c{column.tie_diameter_mm}@{column.tie_spacing_end_mm}/{column.tie_spacing_mid_mm}",
                f"{column.maximum_biaxial_utilization:.3f}",
                f"{column.maximum_shear_utilization:.3f}",
                column.status,
            ]
        )
    return rows


def draw_beam_and_column_details(acad: Any, project: ProjectDesign, settings: DrawingSettings) -> None:
    """Draw RC beam and column details into the AutoCAD drawing already open on the worker."""

    settings.validate()
    document = acad.ActiveDocument
    model_space = document.ModelSpace
    layers = document.Layers
    ensure_standard_layers(layers, settings)

    beams = list(project.beams[: settings.maximum_beams_to_draw])
    columns = list(project.columns[: settings.maximum_columns_to_draw])
    details_per_row = settings.details_per_row
    origin_x = settings.origin_x_m
    origin_y = settings.origin_y_m
    text_layer = layer_name(settings, "TEXT")
    border_layer = layer_name(settings, "BORDER")

    max_beam_span = max((beam.member.length_m for beam in beams), default=6.0)
    max_beam_depth = max((beam.member.depth_mm / 1000.0 for beam in beams), default=0.6)
    beam_cell_width = max(9.0, max_beam_span + 3.2)
    beam_cell_height = max(5.6, max_beam_depth + 5.0)
    max_column_height = max((column.member.length_m for column in columns), default=3.0)
    column_cell_width = 7.2
    column_cell_height = max(6.2, max_column_height + 3.0)
    drawing_width = max(
        details_per_row * beam_cell_width if beams else 0.0,
        details_per_row * column_cell_width if columns else 0.0,
        13.0,
    )

    add_text(
        model_space,
        "ETABS RC BEAM AND COLUMN REINFORCEMENT DETAILS",
        origin_x + drawing_width / 2.0,
        origin_y,
        text_layer,
        settings,
        height_m=settings.text_height_m * 1.55,
        center=True,
    )
    add_text(
        model_space,
        "Preliminary ACI-style design from imported ETABS frame forces · verify before construction",
        origin_x + drawing_width / 2.0,
        origin_y - 0.35,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.78,
        center=True,
    )

    current_top = origin_y - 0.90
    if beams:
        add_text(model_space, "BEAM DETAILS", origin_x, current_top, text_layer, settings, height_m=settings.text_height_m * 1.22)
        beam_details_top = current_top - 0.35
        for index, beam in enumerate(beams):
            row = index // details_per_row
            column = index % details_per_row
            cell_x = origin_x + column * beam_cell_width
            cell_top = beam_details_top - row * beam_cell_height
            _draw_beam_detail(
                model_space, beam, cell_x, cell_top, beam_cell_width, beam_cell_height,
                settings, project.settings
            )
        beam_rows = ceil(len(beams) / details_per_row)
        current_top = beam_details_top - beam_rows * beam_cell_height - 0.55
        if len(project.beams) > len(beams):
            add_text(
                model_space,
                f"Beam drawing limited to {len(beams)} of {len(project.beams)} designs by the AutoCAD settings.",
                origin_x,
                current_top + 0.25,
                text_layer,
                settings,
                height_m=settings.text_height_m * 0.75,
            )

    if columns:
        add_text(model_space, "COLUMN DETAILS", origin_x, current_top, text_layer, settings, height_m=settings.text_height_m * 1.22)
        column_details_top = current_top - 0.35
        for index, column in enumerate(columns):
            row = index // details_per_row
            grid_column = index % details_per_row
            cell_x = origin_x + grid_column * column_cell_width
            cell_top = column_details_top - row * column_cell_height
            _draw_column_detail(
                model_space, column, cell_x, cell_top, column_cell_width, column_cell_height,
                settings, project.settings
            )
        column_rows = ceil(len(columns) / details_per_row)
        current_top = column_details_top - column_rows * column_cell_height - 0.65
        if len(project.columns) > len(columns):
            add_text(
                model_space,
                f"Column drawing limited to {len(columns)} of {len(project.columns)} designs by the AutoCAD settings.",
                origin_x,
                current_top + 0.25,
                text_layer,
                settings,
                height_m=settings.text_height_m * 0.75,
            )

    if settings.draw_schedules:
        if beams:
            _, beam_schedule_bottom, _, _ = draw_table(
                model_space,
                origin_x,
                current_top,
                ("Mark", "Story", "Section", "Top L/M/R", "Bottom L/M/R", "Stirrups L/M/R", "Status"),
                _beam_schedule_rows(beams),
                (0.75, 1.05, 1.15, 2.45, 2.45, 3.25, 0.85),
                settings,
                title="BEAM REINFORCEMENT SCHEDULE",
                row_height_m=0.36,
            )
            current_top = beam_schedule_bottom - 0.65
        if columns:
            _, column_schedule_bottom, _, _ = draw_table(
                model_space,
                origin_x,
                current_top,
                ("Mark", "Story", "Section", "Bars", "Ties end/mid", "Biaxial", "Shear", "Status"),
                _column_schedule_rows(columns),
                (0.75, 1.05, 1.15, 1.15, 2.15, 1.05, 1.00, 0.85),
                settings,
                title="COLUMN REINFORCEMENT SCHEDULE",
                row_height_m=0.36,
            )
            current_top = column_schedule_bottom - 0.65

    notes = [
        "GENERAL NOTES",
        "1. Dimensions are generated in model space using the configured AutoCAD units per metre.",
        "2. ETABS local frame-force signs are retained except column P, which can be converted to compression positive during import.",
        f"3. Design inputs: f'c={project.settings.concrete_strength_mpa:.1f} MPa; fy={project.settings.steel_yield_strength_mpa:.1f} MPa; cover={project.settings.concrete_cover_mm:.0f} mm.",
        "4. Bar curtailment, development, lap locations, seismic detailing, joints, and constructability require project review.",
        "5. App geometry is placed on prefixed layers. Repeated runs append another drawing set.",
    ]
    note_bottom = add_text_lines(
        model_space,
        notes,
        origin_x,
        current_top,
        text_layer,
        settings,
        height_m=settings.text_height_m * 0.72,
        line_spacing=1.45,
    )
    drawing_bottom = note_bottom - 0.30

    if settings.draw_border:
        margin = 0.45
        add_rectangle(
            model_space,
            origin_x - margin,
            drawing_bottom - margin,
            origin_x + drawing_width + margin,
            origin_y + 0.45,
            border_layer,
            settings,
        )
        title_block_width = 4.4
        title_block_height = 0.72
        add_rectangle(
            model_space,
            origin_x + drawing_width - title_block_width,
            drawing_bottom - 0.10,
            origin_x + drawing_width,
            drawing_bottom + title_block_height,
            border_layer,
            settings,
        )
        add_text(
            model_space,
            "VIKTOR / ETABS / AutoCAD",
            origin_x + drawing_width - title_block_width / 2.0,
            drawing_bottom + 0.47,
            text_layer,
            settings,
            height_m=settings.text_height_m * 0.72,
            center=True,
        )
        add_text(
            model_space,
            "RC BEAM & COLUMN DETAILS",
            origin_x + drawing_width - title_block_width / 2.0,
            drawing_bottom + 0.18,
            text_layer,
            settings,
            height_m=settings.text_height_m * 0.66,
            center=True,
        )

    document.Regen(AcRegenType.acAllViewports)
