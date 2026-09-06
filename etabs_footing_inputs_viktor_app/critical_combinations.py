from __future__ import annotations

from collections import defaultdict
from math import hypot
from typing import Any, Iterable, Mapping


SERVICE = "Service"
ULTIMATE = "Ultimate"


class CriticalCombinationError(ValueError):
    """Raised when ETABS rows cannot be converted into footing inputs."""


def parse_case_filters(value: str) -> tuple[str, ...]:
    filters = tuple(part.strip().casefold() for part in value.split(",") if part.strip())
    if not filters:
        raise CriticalCombinationError("Enter at least one load-combination filter.")
    return filters


def _matches(case_name: str, filters: Iterable[str]) -> bool:
    normalized_name = case_name.casefold()
    return any(case_filter in normalized_name for case_filter in filters)


def _as_float(row: Mapping[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0.0))
    except (TypeError, ValueError) as exc:
        raise CriticalCombinationError(
            f"ETABS returned a non-numeric {key} value for point '{row.get('UniqueName', '')}'."
        ) from exc


def select_critical_reactions(
    rows: list[dict[str, Any]],
    service_case_filters: str,
    ultimate_case_filters: str,
    *,
    compression_is_negative: bool = True,
) -> list[dict[str, Any]]:
    """Select the maximum-compression row for each support and limit state.

    Case filters are case-insensitive fragments. Ties in compression are resolved
    by the largest resultant of MX and MY.
    """
    if not rows:
        raise CriticalCombinationError("ETABS returned no joint-reaction rows.")

    service_filters = parse_case_filters(service_case_filters)
    ultimate_filters = parse_case_filters(ultimate_case_filters)
    selected: dict[tuple[str, str], tuple[tuple[float, float], dict[str, Any]]] = {}
    support_names: set[str] = set()
    available_cases: set[str] = set()
    matched_states: dict[str, set[str]] = defaultdict(set)

    for source in rows:
        node_id = str(source.get("UniqueName", "")).strip()
        if not node_id:
            raise CriticalCombinationError("A joint-reaction row is missing its ETABS UniqueName.")
        support_names.add(node_id)

        case_name = str(source.get("OutputCase", "")).strip()
        available_cases.add(case_name)
        is_service = _matches(case_name, service_filters)
        is_ultimate = _matches(case_name, ultimate_filters)
        if is_service and is_ultimate:
            raise CriticalCombinationError(
                f"Output case '{case_name}' matches both the service and ultimate filters. "
                "Make the filters unambiguous."
            )
        if not is_service and not is_ultimate:
            continue

        limit_state = SERVICE if is_service else ULTIMATE
        matched_states[node_id].add(limit_state)
        fz = _as_float(source, "FZ")
        compression_kn = -fz if compression_is_negative else fz
        if compression_kn <= 0:
            continue

        mx_knm = _as_float(source, "MX")
        my_knm = _as_float(source, "MY")
        score = (compression_kn, hypot(mx_knm, my_knm))
        result = {
            "node_id": node_id,
            "story": str(source.get("Story", "")),
            "label": str(source.get("Label", "")),
            "x_m": _as_float(source, "X"),
            "y_m": _as_float(source, "Y"),
            "z_m": _as_float(source, "Z"),
            "combination": case_name,
            "limit_state": limit_state,
            "p_kn": compression_kn,
            "mx_knm": mx_knm,
            "my_knm": my_knm,
            "case_type": str(source.get("CaseType", "")),
            "step_type": str(source.get("StepType", "")),
        }
        key = (node_id, limit_state)
        current = selected.get(key)
        if current is None or score > current[0]:
            selected[key] = (score, result)

    missing: list[str] = []
    for node_id in sorted(support_names):
        for limit_state in (SERVICE, ULTIMATE):
            if (node_id, limit_state) not in selected:
                matched = limit_state in matched_states[node_id]
                reason = "matched rows were uplift/non-compressive" if matched else "no case matched"
                missing.append(f"{node_id}: {limit_state} ({reason})")
    if missing:
        cases = ", ".join(sorted(case for case in available_cases if case))
        raise CriticalCombinationError(
            "A compressive critical reaction could not be selected for every support: "
            + "; ".join(missing)
            + f". Available ETABS cases: {cases or 'none'}."
        )

    return [
        selected[(node_id, limit_state)][1]
        for node_id in sorted(support_names)
        for limit_state in (SERVICE, ULTIMATE)
    ]
