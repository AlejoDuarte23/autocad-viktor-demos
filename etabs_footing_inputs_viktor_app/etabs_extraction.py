from __future__ import annotations

import logging
from typing import Any

import viktor as vkt


logger = logging.getLogger("viktor")
KN_M_C_UNITS = 6


def check(value: list | tuple | int, name: str) -> None:
    """Raise a user-facing error when an ETABS call returns a non-zero code."""
    code = int(value[-1] if isinstance(value, (list, tuple)) else value)
    if code != 0:
        raise vkt.UserError(f"ETABS call failed [{name}], return code = {code}.")


def _to_float(value: Any, field: str, point_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise vkt.UserError(
            f"ETABS returned a non-numeric {field} value for point '{point_name}'."
        ) from exc


def _get_table(sap: Any, table_name: str) -> list[dict[str, Any]]:
    result = sap.DatabaseTables.GetTableForDisplayArray(table_name, [""], "", 0, [], 0, [])
    if not isinstance(result, (list, tuple)) or len(result) != 6:
        raise vkt.UserError(
            f"ETABS table '{table_name}' returned an unexpected response with "
            f"{len(result) if isinstance(result, (list, tuple)) else 1} values."
        )
    _field_list, _version, columns, record_count, flat_data, return_code = result
    check(return_code, f"DatabaseTables.GetTableForDisplayArray({table_name!r})")

    columns = list(columns)
    record_count = int(record_count)
    column_count = len(columns)
    if column_count == 0:
        return []
    expected_values = record_count * column_count
    if len(flat_data) < expected_values:
        raise vkt.UserError(
            f"ETABS table '{table_name}' returned incomplete row data."
        )
    return [
        dict(zip(columns, flat_data[index : index + column_count]))
        for index in range(0, expected_values, column_count)
    ]


def _extract_reactions(sap: Any) -> dict[str, Any]:
    available_result = sap.DatabaseTables.GetAvailableTables(0, [], [], [])
    if not isinstance(available_result, (list, tuple)) or len(available_result) != 5:
        raise vkt.UserError("ETABS returned an unexpected available-tables response.")
    table_count, table_keys, _table_names, _import_types, return_code = available_result
    check(return_code, "DatabaseTables.GetAvailableTables")
    available = list(table_keys[: int(table_count)])

    reaction_table = "Joint Reactions"
    coordinate_table = "Point Object Connectivity"
    for table_name in (reaction_table, coordinate_table):
        if table_name not in available:
            raise vkt.UserError(
                f"Table '{table_name}' is unavailable. Run the ETABS analysis and ensure results exist."
            )

    reaction_rows = _get_table(sap, reaction_table)
    if not reaction_rows:
        raise vkt.UserError(
            "The ETABS Joint Reactions table is empty. Run the analysis and select output cases."
        )
    coordinate_rows = _get_table(sap, coordinate_table)

    coordinates: dict[str, tuple[float, float, float]] = {}
    for row in coordinate_rows:
        unique_name = str(row.get("UniqueName", "")).strip()
        if not unique_name:
            continue
        coordinates[unique_name] = (
            _to_float(row.get("X"), "X", unique_name),
            _to_float(row.get("Y"), "Y", unique_name),
            _to_float(row.get("Z"), "Z", unique_name),
        )

    enriched: list[dict[str, Any]] = []
    missing_coordinates: set[str] = set()
    for row in reaction_rows:
        unique_name = str(row.get("UniqueName", "")).strip()
        coordinate = coordinates.get(unique_name)
        if coordinate is None:
            missing_coordinates.add(unique_name or "<unnamed>")
            continue
        enriched.append(
            {
                "Story": str(row.get("Story", "")),
                "Label": str(row.get("Label", "")),
                "UniqueName": unique_name,
                "OutputCase": str(row.get("OutputCase", "")),
                "CaseType": str(row.get("CaseType", "")),
                "StepType": str(row.get("StepType", "")),
                "FX": _to_float(row.get("FX"), "FX", unique_name),
                "FY": _to_float(row.get("FY"), "FY", unique_name),
                "FZ": _to_float(row.get("FZ"), "FZ", unique_name),
                "MX": _to_float(row.get("MX"), "MX", unique_name),
                "MY": _to_float(row.get("MY"), "MY", unique_name),
                "MZ": _to_float(row.get("MZ"), "MZ", unique_name),
                "X": coordinate[0],
                "Y": coordinate[1],
                "Z": coordinate[2],
            }
        )

    if missing_coordinates:
        names = ", ".join(sorted(missing_coordinates))
        raise vkt.UserError(
            f"Coordinates were unavailable for these reacting ETABS points: {names}."
        )

    combo_list_result = sap.RespCombo.GetNameList(0, [])
    if not isinstance(combo_list_result, (list, tuple)) or len(combo_list_result) != 3:
        raise vkt.UserError("ETABS returned an unexpected response-combination list.")
    combo_count, combo_names, return_code = combo_list_result
    check(return_code, "RespCombo.GetNameList")

    combination_factors: dict[str, tuple[float, ...]] = {}
    for combo_name in list(combo_names[: int(combo_count)]):
        combo_result = sap.RespCombo.GetCaseList(str(combo_name), 0, [], [], [])
        if not isinstance(combo_result, (list, tuple)) or len(combo_result) != 5:
            raise vkt.UserError(
                f"ETABS returned an unexpected definition for response combination '{combo_name}'."
            )
        item_count, _item_types, _item_names, scale_factors, return_code = combo_result
        check(return_code, f"RespCombo.GetCaseList({combo_name!r})")
        combination_factors[str(combo_name)] = tuple(
            float(value) for value in list(scale_factors[: int(item_count)])
        )

    if not combination_factors:
        raise vkt.UserError("The ETABS model does not contain any response combinations.")

    return {
        "rows": enriched,
        "load_cases": sorted({row["OutputCase"] for row in enriched}),
        "combination_factors": combination_factors,
    }


def extract_reactions_kn_m(sap: Any) -> dict[str, Any]:
    """Extract joint reactions after temporarily setting ETABS to kN, m, C."""
    original_units = int(sap.GetPresentUnits())
    check(sap.SetPresentUnits(KN_M_C_UNITS), "SapModel.SetPresentUnits(kN_m_C)")
    try:
        return _extract_reactions(sap)
    finally:
        try:
            check(sap.SetPresentUnits(original_units), "SapModel.SetPresentUnits(restore)")
        except Exception as exc:  # The extraction result is still valid if restoring only the UI unit fails.
            logger.warning("Could not restore the original ETABS display units: %s", exc)
