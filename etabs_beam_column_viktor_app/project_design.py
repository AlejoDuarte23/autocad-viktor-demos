from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from beam_design import design_beam
from column_design import design_column
from models import (
    BeamForce,
    BeamMember,
    ColumnForce,
    ColumnMember,
    DesignInputError,
    DesignSettings,
    ProjectDesign,
)


def _value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _required_text(row: Any, key: str, label: str, row_number: int) -> str:
    value = _value(row, key)
    text = "" if value is None else str(value).strip()
    if not text:
        raise DesignInputError(f"{label} is required in row {row_number}.")
    return text


def _text(row: Any, key: str, default: str = "") -> str:
    value = _value(row, key, default)
    return default if value is None else str(value).strip()


def _number(row: Any, key: str, label: str, row_number: int, default: float | None = None) -> float:
    value = _value(row, key, default)
    if value is None or value == "":
        raise DesignInputError(f"{label} is required in row {row_number}.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DesignInputError(f"{label} must be numeric in row {row_number}.") from exc
    if not isfinite(number):
        raise DesignInputError(f"{label} must be finite in row {row_number}.")
    return number


def validate_settings(settings: DesignSettings) -> None:
    if settings.concrete_strength_mpa <= 0.0:
        raise DesignInputError("Concrete strength must be greater than zero.")
    if settings.steel_yield_strength_mpa <= 0.0:
        raise DesignInputError("Steel yield strength must be greater than zero.")
    if settings.steel_modulus_mpa <= settings.steel_yield_strength_mpa:
        raise DesignInputError("Steel modulus must be greater than steel yield strength.")
    if settings.concrete_cover_mm < 20.0:
        raise DesignInputError("Concrete cover must be at least 20 mm for this detailing routine.")
    if not 0.005 <= settings.minimum_column_ratio < settings.maximum_column_ratio <= 0.10:
        raise DesignInputError("Column reinforcement ratios must satisfy 0.005 ≤ minimum < maximum ≤ 0.10.")
    if not 0.5 <= settings.column_biaxial_exponent <= 2.0:
        raise DesignInputError("The column biaxial exponent must be between 0.5 and 2.0.")
    if settings.column_effective_length_factor <= 0.0:
        raise DesignInputError("Column effective-length factor must be greater than zero.")
    if settings.development_length_factor <= 0.0:
        raise DesignInputError("Development-length factor must be greater than zero.")
    if settings.minimum_beam_bars < 2:
        raise DesignInputError("At least two longitudinal beam bars are required per face.")
    if not 0.50 <= settings.shear_phi <= 1.00:
        raise DesignInputError("Shear strength-reduction factor must be between 0.50 and 1.00.")


def parse_beam_members(rows: Sequence[Any] | None) -> tuple[BeamMember, ...]:
    members: list[BeamMember] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows or [], start=1):
        member_id = _required_text(row, "member_id", "Beam member ID", row_number)
        if member_id in seen:
            raise DesignInputError(f"Beam member ID '{member_id}' is repeated.")
        seen.add(member_id)
        width = _number(row, "width_mm", "Beam width", row_number)
        depth = _number(row, "depth_mm", "Beam depth", row_number)
        if width <= 0.0 or depth <= 0.0:
            raise DesignInputError(f"Beam '{member_id}' must have positive section dimensions.")
        members.append(
            BeamMember(
                member_id=member_id,
                label=_text(row, "label", member_id) or member_id,
                story=_text(row, "story", "Unassigned") or "Unassigned",
                section_name=_text(row, "section_name", "RECT") or "RECT",
                material_name=_text(row, "material_name", "Concrete") or "Concrete",
                point_i=_text(row, "point_i", "I") or "I",
                point_j=_text(row, "point_j", "J") or "J",
                i_x_m=_number(row, "i_x_m", "Beam I-end X", row_number, 0.0),
                i_y_m=_number(row, "i_y_m", "Beam I-end Y", row_number, 0.0),
                i_z_m=_number(row, "i_z_m", "Beam I-end Z", row_number, 0.0),
                j_x_m=_number(row, "j_x_m", "Beam J-end X", row_number, 0.0),
                j_y_m=_number(row, "j_y_m", "Beam J-end Y", row_number, 0.0),
                j_z_m=_number(row, "j_z_m", "Beam J-end Z", row_number, 0.0),
                width_mm=width,
                depth_mm=depth,
                angle_deg=_number(row, "angle_deg", "Beam local-axis angle", row_number, 0.0),
            )
        )
    return tuple(members)


def parse_beam_forces(rows: Sequence[Any] | None, member_ids: set[str]) -> tuple[BeamForce, ...]:
    forces: list[BeamForce] = []
    for row_number, row in enumerate(rows or [], start=1):
        member_id = _required_text(row, "member_id", "Beam force member ID", row_number)
        if member_id not in member_ids:
            raise DesignInputError(
                f"Beam force row {row_number} references '{member_id}', which is not in the beam-member table."
            )
        combination = _required_text(row, "combination", "Beam load combination", row_number)
        forces.append(
            BeamForce(
                member_id=member_id,
                combination=combination,
                station_m=_number(row, "station_m", "Beam station", row_number, 0.0),
                step_type=_text(row, "step_type", "") or "",
                step_num=_number(row, "step_num", "Beam result step", row_number, 0.0),
                p_kn=_number(row, "p_kn", "Beam axial force", row_number, 0.0),
                v2_kn=_number(row, "v2_kn", "Beam V2", row_number, 0.0),
                v3_kn=_number(row, "v3_kn", "Beam V3", row_number, 0.0),
                t_knm=_number(row, "t_knm", "Beam torsion", row_number, 0.0),
                m2_knm=_number(row, "m2_knm", "Beam M2", row_number, 0.0),
                m3_knm=_number(row, "m3_knm", "Beam M3", row_number, 0.0),
            )
        )
    return tuple(forces)


def parse_column_members(rows: Sequence[Any] | None) -> tuple[ColumnMember, ...]:
    members: list[ColumnMember] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows or [], start=1):
        member_id = _required_text(row, "member_id", "Column member ID", row_number)
        if member_id in seen:
            raise DesignInputError(f"Column member ID '{member_id}' is repeated.")
        seen.add(member_id)
        shape_raw = _text(row, "shape", "Rectangular").lower()
        if shape_raw.startswith("circ"):
            shape = "Circular"
        elif shape_raw.startswith("rect"):
            shape = "Rectangular"
        else:
            raise DesignInputError(
                f"Column shape must be Rectangular or Circular in row {row_number}."
            )
        width = _number(row, "width_mm", "Column width", row_number, 0.0)
        depth = _number(row, "depth_mm", "Column depth", row_number, 0.0)
        diameter = _number(row, "diameter_mm", "Column diameter", row_number, 0.0)
        if shape == "Circular":
            if diameter <= 0.0:
                raise DesignInputError(f"Circular column '{member_id}' needs a positive diameter.")
            width = diameter
            depth = diameter
        elif width <= 0.0 or depth <= 0.0:
            raise DesignInputError(f"Rectangular column '{member_id}' needs positive width and depth.")
        members.append(
            ColumnMember(
                member_id=member_id,
                label=_text(row, "label", member_id) or member_id,
                story=_text(row, "story", "Unassigned") or "Unassigned",
                section_name=_text(row, "section_name", "RECT") or "RECT",
                material_name=_text(row, "material_name", "Concrete") or "Concrete",
                point_i=_text(row, "point_i", "I") or "I",
                point_j=_text(row, "point_j", "J") or "J",
                i_x_m=_number(row, "i_x_m", "Column I-end X", row_number, 0.0),
                i_y_m=_number(row, "i_y_m", "Column I-end Y", row_number, 0.0),
                i_z_m=_number(row, "i_z_m", "Column I-end Z", row_number, 0.0),
                j_x_m=_number(row, "j_x_m", "Column J-end X", row_number, 0.0),
                j_y_m=_number(row, "j_y_m", "Column J-end Y", row_number, 0.0),
                j_z_m=_number(row, "j_z_m", "Column J-end Z", row_number, 0.0),
                shape=shape,
                width_mm=width,
                depth_mm=depth,
                diameter_mm=diameter if shape == "Circular" else 0.0,
                angle_deg=_number(row, "angle_deg", "Column local-axis angle", row_number, 0.0),
            )
        )
    return tuple(members)


def parse_column_forces(rows: Sequence[Any] | None, member_ids: set[str]) -> tuple[ColumnForce, ...]:
    forces: list[ColumnForce] = []
    for row_number, row in enumerate(rows or [], start=1):
        member_id = _required_text(row, "member_id", "Column force member ID", row_number)
        if member_id not in member_ids:
            raise DesignInputError(
                f"Column force row {row_number} references '{member_id}', which is not in the column-member table."
            )
        end_raw = _text(row, "end", "Intermediate").upper()
        if end_raw in {"I", "BOTTOM"}:
            end = "I"
        elif end_raw in {"J", "TOP"}:
            end = "J"
        else:
            end = "Intermediate"
        forces.append(
            ColumnForce(
                member_id=member_id,
                combination=_required_text(row, "combination", "Column load combination", row_number),
                end=end,
                station_m=_number(row, "station_m", "Column station", row_number, 0.0),
                step_type=_text(row, "step_type", "") or "",
                step_num=_number(row, "step_num", "Column result step", row_number, 0.0),
                p_kn=_number(row, "p_kn", "Column axial force", row_number, 0.0),
                v2_kn=_number(row, "v2_kn", "Column V2", row_number, 0.0),
                v3_kn=_number(row, "v3_kn", "Column V3", row_number, 0.0),
                t_knm=_number(row, "t_knm", "Column torsion", row_number, 0.0),
                m2_knm=_number(row, "m2_knm", "Column M2", row_number, 0.0),
                m3_knm=_number(row, "m3_knm", "Column M3", row_number, 0.0),
            )
        )
    return tuple(forces)




def _validate_force_stations(
    beam_members: Sequence[BeamMember],
    beam_forces: Sequence[BeamForce],
    column_members: Sequence[ColumnMember],
    column_forces: Sequence[ColumnForce],
) -> None:
    beam_lengths = {member.member_id: member.length_m for member in beam_members}
    column_lengths = {member.member_id: member.length_m for member in column_members}
    for force in beam_forces:
        length = beam_lengths[force.member_id]
        tolerance = max(0.02, 0.005 * max(length, 1.0))
        if force.station_m < -tolerance or force.station_m > length + tolerance:
            raise DesignInputError(
                f"Beam force station {force.station_m:.3f} m for '{force.member_id}' lies outside "
                f"the member length of {length:.3f} m."
            )
    for force in column_forces:
        length = column_lengths[force.member_id]
        tolerance = max(0.02, 0.005 * max(length, 1.0))
        if force.station_m < -tolerance or force.station_m > length + tolerance:
            raise DesignInputError(
                f"Column force station {force.station_m:.3f} m for '{force.member_id}' lies outside "
                f"the member length of {length:.3f} m."
            )


def design_project(
    beam_member_rows: Sequence[Any] | None,
    beam_force_rows: Sequence[Any] | None,
    column_member_rows: Sequence[Any] | None,
    column_force_rows: Sequence[Any] | None,
    settings: DesignSettings,
) -> ProjectDesign:
    validate_settings(settings)
    beam_members = parse_beam_members(beam_member_rows)
    column_members = parse_column_members(column_member_rows)
    if not beam_members and not column_members:
        raise DesignInputError("Import or enter at least one beam or column.")

    beam_forces = parse_beam_forces(beam_force_rows, {item.member_id for item in beam_members})
    column_forces = parse_column_forces(column_force_rows, {item.member_id for item in column_members})
    _validate_force_stations(beam_members, beam_forces, column_members, column_forces)
    grouped_beam_forces: dict[str, list[BeamForce]] = defaultdict(list)
    grouped_column_forces: dict[str, list[ColumnForce]] = defaultdict(list)
    for force in beam_forces:
        grouped_beam_forces[force.member_id].append(force)
    for force in column_forces:
        grouped_column_forces[force.member_id].append(force)

    missing_beams = [member.member_id for member in beam_members if not grouped_beam_forces[member.member_id]]
    missing_columns = [member.member_id for member in column_members if not grouped_column_forces[member.member_id]]
    if missing_beams:
        raise DesignInputError("No force rows were found for beams: " + ", ".join(missing_beams[:20]))
    if missing_columns:
        raise DesignInputError("No force rows were found for columns: " + ", ".join(missing_columns[:20]))

    beam_designs = tuple(
        design_beam(member, grouped_beam_forces[member.member_id], settings, f"B{index}")
        for index, member in enumerate(beam_members, start=1)
    )
    column_designs = tuple(
        design_column(member, grouped_column_forces[member.member_id], settings, f"C{index}")
        for index, member in enumerate(column_members, start=1)
    )
    return ProjectDesign(beams=beam_designs, columns=column_designs, settings=settings)
