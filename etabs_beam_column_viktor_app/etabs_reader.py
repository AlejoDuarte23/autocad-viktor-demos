from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase
from math import sqrt
from typing import Any, Iterable, Sequence

import viktor as vkt


class ETABSReadError(RuntimeError):
    """Raised when the attached ETABS model does not provide the required data."""


@dataclass(frozen=True)
class ETABSImportSettings:
    combination_filter: str = "*"
    story_filter: str = "*"
    beam_filter: str = "*"
    column_filter: str = "*"
    result_group_name: str = "ALL"
    compression_is_negative: bool = True
    column_vertical_ratio: float = 0.75
    maximum_members: int = 500
    maximum_beam_rows_per_combination: int = 21


@dataclass(frozen=True)
class ETABSImportResult:
    beam_members: tuple[dict[str, Any], ...]
    beam_forces: tuple[dict[str, Any], ...]
    column_members: tuple[dict[str, Any], ...]
    column_forces: tuple[dict[str, Any], ...]
    selected_combinations: tuple[str, ...]
    notes: tuple[str, ...]


def _return_code(result: Any) -> int:
    if isinstance(result, (list, tuple)):
        if not result:
            return 0
        return int(result[-1])
    return int(result)


def _outputs(result: Any, call_name: str) -> list[Any]:
    if not isinstance(result, (list, tuple)):
        raise ETABSReadError(f"ETABS call {call_name} did not return output parameters.")
    if not result:
        raise ETABSReadError(f"ETABS call {call_name} returned no data.")
    code = int(result[-1])
    if code != 0:
        raise ETABSReadError(f"ETABS call {call_name} failed with status {code}.")
    return list(result[:-1])


def _check(result: Any, call_name: str) -> None:
    code = _return_code(result)
    if code != 0:
        raise ETABSReadError(f"ETABS call {call_name} failed with status {code}.")


def _patterns(text: str) -> tuple[str, ...]:
    values = [part.strip().lower() for part in text.replace(";", ",").split(",") if part.strip()]
    return tuple(values or ["*"])


def _matches(value: str, pattern_text: str) -> bool:
    target = value.lower()
    return any(fnmatchcase(target, pattern) for pattern in _patterns(pattern_text))


def _get_combinations(sap: Any) -> tuple[str, ...]:
    outputs = _outputs(sap.RespCombo.GetNameList(0, []), "RespCombo.GetNameList")
    if len(outputs) < 2:
        raise ETABSReadError("ETABS did not return the response-combination list in the expected format.")
    number = int(outputs[0])
    names = tuple(str(name) for name in outputs[1])
    return names[:number]


def _get_frame_labels(sap: Any) -> dict[str, tuple[str, str]]:
    outputs = _outputs(
        sap.FrameObj.GetLabelNameList(0, [], [], []),
        "FrameObj.GetLabelNameList",
    )
    if len(outputs) < 4:
        return {}
    number = int(outputs[0])
    names, labels, stories = outputs[1], outputs[2], outputs[3]
    return {
        str(names[index]): (str(labels[index]), str(stories[index]))
        for index in range(min(number, len(names), len(labels), len(stories)))
    }


def _get_all_frames(sap: Any) -> list[dict[str, Any]]:
    result = sap.FrameObj.GetAllFrames(
        0,
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        "Global",
    )
    outputs = _outputs(result, "FrameObj.GetAllFrames")
    if len(outputs) < 20:
        raise ETABSReadError("ETABS returned an unexpected GetAllFrames result shape.")
    number = int(outputs[0])
    arrays = outputs[1:]
    length = min([number, *[len(array) for array in arrays if isinstance(array, Sequence)]])
    frames: list[dict[str, Any]] = []
    for index in range(length):
        frames.append(
            {
                "member_id": str(outputs[1][index]),
                "section_name": str(outputs[2][index]),
                "story": str(outputs[3][index]),
                "point_i": str(outputs[4][index]),
                "point_j": str(outputs[5][index]),
                "i_x_m": float(outputs[6][index]),
                "i_y_m": float(outputs[7][index]),
                "i_z_m": float(outputs[8][index]),
                "j_x_m": float(outputs[9][index]),
                "j_y_m": float(outputs[10][index]),
                "j_z_m": float(outputs[11][index]),
                "angle_deg": float(outputs[12][index]),
            }
        )
    return frames


def _material_is_concrete(sap: Any, material_name: str) -> bool:
    # CSI eMatType.Concrete has value 2. GetTypeOAPI returns MatType, SymType, ret.
    try:
        outputs = _outputs(
            sap.PropMaterial.GetTypeOAPI(material_name, 0, 0),
            f"PropMaterial.GetTypeOAPI({material_name})",
        )
    except (ETABSReadError, vkt.errors.ExecutionError):
        return False
    return bool(outputs) and int(outputs[0]) == 2


def _read_section(sap: Any, section_name: str) -> dict[str, Any] | None:
    rectangle = sap.PropFrame.GetRectangle(section_name, "", "", 0.0, 0.0, 0, "", "")
    if _return_code(rectangle) == 0:
        outputs = list(rectangle[:-1])
        material_name = str(outputs[1])
        if not _material_is_concrete(sap, material_name):
            return None
        return {
            "shape": "Rectangular",
            "material_name": material_name,
            "depth_mm": float(outputs[2]) * 1000.0,
            "width_mm": float(outputs[3]) * 1000.0,
            "diameter_mm": 0.0,
        }

    circle = sap.PropFrame.GetCircle(section_name, "", "", 0.0, 0, "", "")
    if _return_code(circle) == 0:
        outputs = list(circle[:-1])
        material_name = str(outputs[1])
        if not _material_is_concrete(sap, material_name):
            return None
        diameter_mm = float(outputs[2]) * 1000.0
        return {
            "shape": "Circular",
            "material_name": material_name,
            "depth_mm": diameter_mm,
            "width_mm": diameter_mm,
            "diameter_mm": diameter_mm,
        }
    return None


def _frame_force_call(sap: Any, name: str, item_type: Any) -> list[Any]:
    return sap.Results.FrameForce(
        name,
        item_type,
        0,
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )


def _parse_force_result(result: Sequence[Any]) -> list[dict[str, Any]]:
    outputs = _outputs(result, "Results.FrameForce")
    if len(outputs) < 14:
        raise ETABSReadError("ETABS returned an unexpected FrameForce result shape.")
    number = int(outputs[0])
    arrays = outputs[1:]
    length = min([number, *[len(array) for array in arrays if isinstance(array, Sequence)]])
    rows: list[dict[str, Any]] = []
    for index in range(length):
        rows.append(
            {
                "member_id": str(outputs[1][index]),
                "station_m": float(outputs[2][index]),
                "element_id": str(outputs[3][index]),
                "element_station_m": float(outputs[4][index]),
                "combination": str(outputs[5][index]),
                "step_type": str(outputs[6][index]),
                "step_num": float(outputs[7][index]),
                "p_kn_raw": float(outputs[8][index]),
                "v2_kn": float(outputs[9][index]),
                "v3_kn": float(outputs[10][index]),
                "t_knm": float(outputs[11][index]),
                "m2_knm": float(outputs[12][index]),
                "m3_knm": float(outputs[13][index]),
            }
        )
    return rows


def _read_frame_forces(sap: Any, frame_names: Sequence[str], group_name: str) -> list[dict[str, Any]]:
    selected = set(frame_names)
    try:
        result = _frame_force_call(sap, group_name, vkt.etabs.eItemTypeElm.GroupElm)
        if _return_code(result) == 0:
            group_rows = [
                row for row in _parse_force_result(result) if row["member_id"] in selected
            ]
            if group_rows:
                return group_rows
    except (ETABSReadError, vkt.errors.ExecutionError):
        # A missing group, an incompatible result shape, or a group that contains
        # none of the selected objects is handled by the object-level fallback.
        pass

    rows: list[dict[str, Any]] = []
    for frame_name in frame_names:
        result = _frame_force_call(sap, frame_name, vkt.etabs.eItemTypeElm.ObjectElm)
        if _return_code(result) != 0:
            continue
        rows.extend(_parse_force_result(result))
    return rows


def _row_score(row: dict[str, Any], length_m: float) -> float:
    return max(
        abs(row["m3_knm"]),
        abs(row["m2_knm"]),
        abs(row["v2_kn"]) * max(length_m, 1.0) / 4.0,
        abs(row["t_knm"]),
    )


def _downsample_beam_rows(
    rows: Sequence[dict[str, Any]],
    length_m: float,
    maximum_rows: int,
) -> list[dict[str, Any]]:
    if len(rows) <= maximum_rows:
        return list(rows)
    ordered = sorted(rows, key=lambda row: (row["station_m"], row["step_type"], row["step_num"]))
    keep_indices = {0, len(ordered) - 1}
    extrema_keys = (
        lambda row: row["m3_knm"],
        lambda row: -row["m3_knm"],
        lambda row: abs(row["v2_kn"]),
        lambda row: abs(row["t_knm"]),
        lambda row: abs(row["m2_knm"]),
    )
    for key in extrema_keys:
        keep_indices.add(max(range(len(ordered)), key=lambda index: key(ordered[index])))
    remaining_slots = max(0, maximum_rows - len(keep_indices))
    for slot in range(remaining_slots):
        target_station = length_m * (slot + 1) / (remaining_slots + 1)
        keep_indices.add(
            min(range(len(ordered)), key=lambda index: abs(ordered[index]["station_m"] - target_station))
        )
    selected = [ordered[index] for index in sorted(keep_indices)]
    if len(selected) > maximum_rows:
        selected = sorted(selected, key=lambda row: _row_score(row, length_m), reverse=True)[:maximum_rows]
        selected.sort(key=lambda row: row["station_m"])
    return selected


def _compress_column_rows(rows: Sequence[dict[str, Any]], length_m: float) -> list[dict[str, Any]]:
    if not rows:
        return []
    minimum_station = min(row["station_m"] for row in rows)
    maximum_station = max(row["station_m"] for row in rows)
    tolerance = max(1e-6, 0.001 * max(length_m, 1.0))
    selected = [
        row
        for row in rows
        if abs(row["station_m"] - minimum_station) <= tolerance
        or abs(row["station_m"] - maximum_station) <= tolerance
    ]
    governing = max(rows, key=lambda row: _row_score(row, length_m))
    if governing not in selected:
        selected.append(governing)
    return selected


def read_attached_etabs_model(sap: Any, settings: ETABSImportSettings) -> ETABSImportResult:
    if settings.maximum_members < 1:
        raise ETABSReadError("Maximum members must be at least one.")
    if settings.maximum_beam_rows_per_combination < 2:
        raise ETABSReadError("Maximum beam stations per combination must be at least two.")
    if not 0.5 <= settings.column_vertical_ratio <= 1.0:
        raise ETABSReadError("Column vertical ratio must be between 0.5 and 1.0.")

    previous_units: Any | None = None
    output_selection_changed = False
    try:
        try:
            previous_units = sap.GetPresentUnits()
        except (vkt.errors.ExecutionError, TimeoutError):
            previous_units = None

        _check(sap.SetPresentUnits(vkt.etabs.eUnits.kN_m_C), "SetPresentUnits")
        all_combinations = _get_combinations(sap)
        selected_combinations = tuple(
            name for name in all_combinations if _matches(name, settings.combination_filter)
        )
        if not selected_combinations:
            available = ", ".join(all_combinations[:30]) or "none"
            raise ETABSReadError(
                "No response combinations match the filter. Available combinations include: " + available
            )

        _check(
            sap.Results.Setup.DeselectAllCasesAndCombosForOutput(),
            "Results.Setup.DeselectAllCasesAndCombosForOutput",
        )
        output_selection_changed = True
        for combination in selected_combinations:
            _check(
                sap.Results.Setup.SetComboSelectedForOutput(combination, True),
                f"Results.Setup.SetComboSelectedForOutput({combination})",
            )

        labels = _get_frame_labels(sap)
        frames = _get_all_frames(sap)
        section_cache: dict[str, dict[str, Any] | None] = {}
        notes: list[str] = [
            "ETABS output case/combo selection was cleared after import; reselect output combinations in ETABS when needed."
        ]
        beam_members: list[dict[str, Any]] = []
        column_members: list[dict[str, Any]] = []

        for frame in frames:
            member_id = frame["member_id"]
            label, label_story = labels.get(member_id, (member_id, frame["story"]))
            story = label_story or frame["story"]
            if not _matches(story, settings.story_filter):
                continue
            dx = frame["j_x_m"] - frame["i_x_m"]
            dy = frame["j_y_m"] - frame["i_y_m"]
            dz = frame["j_z_m"] - frame["i_z_m"]
            length = sqrt(dx * dx + dy * dy + dz * dz)
            if length <= 1e-9:
                notes.append(f"Skipped zero-length frame {member_id}.")
                continue
            is_column = abs(dz) / length >= settings.column_vertical_ratio
            name_filter = settings.column_filter if is_column else settings.beam_filter
            if not (_matches(member_id, name_filter) or _matches(label, name_filter)):
                continue

            section_name = frame["section_name"]
            if section_name not in section_cache:
                section_cache[section_name] = _read_section(sap, section_name)
            section = section_cache[section_name]
            if section is None:
                notes.append(
                    f"Skipped {member_id}: section '{section_name}' is not a supported rectangular or circular concrete section."
                )
                continue
            common_row = {
                "member_id": member_id,
                "label": label,
                "story": story,
                "section_name": section_name,
                "material_name": section["material_name"],
                "point_i": frame["point_i"],
                "point_j": frame["point_j"],
                "i_x_m": frame["i_x_m"],
                "i_y_m": frame["i_y_m"],
                "i_z_m": frame["i_z_m"],
                "j_x_m": frame["j_x_m"],
                "j_y_m": frame["j_y_m"],
                "j_z_m": frame["j_z_m"],
            }
            if is_column:
                column_members.append(
                    {
                        **common_row,
                        "shape": section["shape"],
                        "width_mm": round(section["width_mm"], 3),
                        "depth_mm": round(section["depth_mm"], 3),
                        "diameter_mm": round(section["diameter_mm"], 3),
                        "angle_deg": frame["angle_deg"],
                    }
                )
            elif section["shape"] == "Rectangular":
                beam_members.append(
                    {
                        **common_row,
                        "width_mm": round(section["width_mm"], 3),
                        "depth_mm": round(section["depth_mm"], 3),
                        "angle_deg": frame["angle_deg"],
                    }
                )
            else:
                notes.append(f"Skipped beam {member_id}: circular beam sections are not supported by the beam design routine.")

            if len(beam_members) + len(column_members) >= settings.maximum_members:
                notes.append(f"Import stopped at the configured limit of {settings.maximum_members} members.")
                break

        selected_names = [row["member_id"] for row in beam_members] + [
            row["member_id"] for row in column_members
        ]
        if not selected_names:
            raise ETABSReadError("No supported beam or column frame objects match the member and story filters.")

        raw_force_rows = _read_frame_forces(sap, selected_names, settings.result_group_name)
        if not raw_force_rows:
            raise ETABSReadError(
                "No frame-force results were returned. Analyze the ETABS model and confirm the selected combinations have results."
            )
    finally:
        # The importer temporarily changes the ETABS output selection. Always clear
        # the selected cases/combinations, including when a section or result call fails.
        if output_selection_changed:
            try:
                sap.Results.Setup.DeselectAllCasesAndCombosForOutput()
            except (vkt.errors.ExecutionError, TimeoutError):
                pass
        if previous_units not in (None, 0, vkt.etabs.eUnits.kN_m_C):
            try:
                sap.SetPresentUnits(previous_units)
            except (vkt.errors.ExecutionError, TimeoutError):
                pass

    member_lengths = {
        row["member_id"]: sqrt(
            (row["j_x_m"] - row["i_x_m"]) ** 2
            + (row["j_y_m"] - row["i_y_m"]) ** 2
            + (row["j_z_m"] - row["i_z_m"]) ** 2
        )
        for row in [*beam_members, *column_members]
    }
    beam_ids = {row["member_id"] for row in beam_members}
    column_ids = {row["member_id"] for row in column_members}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_force_rows:
        if row["member_id"] not in beam_ids | column_ids:
            continue
        if row["combination"] not in selected_combinations:
            continue
        if row["member_id"] in column_ids and settings.compression_is_negative:
            p_value = -row["p_kn_raw"]
        else:
            p_value = row["p_kn_raw"]
        row = {**row, "p_kn": p_value}
        grouped[(row["member_id"], row["combination"])].append(row)

    beam_force_rows: list[dict[str, Any]] = []
    column_force_rows: list[dict[str, Any]] = []
    for (member_id, combination), rows in grouped.items():
        length = member_lengths[member_id]
        if member_id in beam_ids:
            chosen = _downsample_beam_rows(
                rows,
                length,
                settings.maximum_beam_rows_per_combination,
            )
            for row in chosen:
                beam_force_rows.append(
                    {
                        "member_id": member_id,
                        "combination": combination,
                        "station_m": round(row["station_m"], 6),
                        "step_type": row["step_type"],
                        "step_num": row["step_num"],
                        "p_kn": round(row["p_kn"], 6),
                        "v2_kn": round(row["v2_kn"], 6),
                        "v3_kn": round(row["v3_kn"], 6),
                        "t_knm": round(row["t_knm"], 6),
                        "m2_knm": round(row["m2_knm"], 6),
                        "m3_knm": round(row["m3_knm"], 6),
                    }
                )
        else:
            chosen = _compress_column_rows(rows, length)
            min_station = min(item["station_m"] for item in rows)
            max_station = max(item["station_m"] for item in rows)
            tolerance = max(1e-6, 0.001 * max(length, 1.0))
            for row in chosen:
                if abs(row["station_m"] - min_station) <= tolerance:
                    end = "I"
                elif abs(row["station_m"] - max_station) <= tolerance:
                    end = "J"
                else:
                    end = "Intermediate"
                column_force_rows.append(
                    {
                        "member_id": member_id,
                        "combination": combination,
                        "end": end,
                        "station_m": round(row["station_m"], 6),
                        "step_type": row["step_type"],
                        "step_num": row["step_num"],
                        "p_kn": round(row["p_kn"], 6),
                        "v2_kn": round(row["v2_kn"], 6),
                        "v3_kn": round(row["v3_kn"], 6),
                        "t_knm": round(row["t_knm"], 6),
                        "m2_knm": round(row["m2_knm"], 6),
                        "m3_knm": round(row["m3_knm"], 6),
                    }
                )

    missing_results = [
        name
        for name in selected_names
        if not any(row["member_id"] == name for row in [*beam_force_rows, *column_force_rows])
    ]
    if missing_results:
        notes.append("No selected-combination results were found for: " + ", ".join(missing_results[:30]))

    return ETABSImportResult(
        beam_members=tuple(beam_members),
        beam_forces=tuple(beam_force_rows),
        column_members=tuple(column_members),
        column_forces=tuple(column_force_rows),
        selected_combinations=selected_combinations,
        notes=tuple(dict.fromkeys(notes)),
    )
