from __future__ import annotations

from collections import defaultdict
from math import hypot
from typing import Any, Mapping, Sequence


SERVICE = "Service"
ULTIMATE = "Ultimate"


class CriticalCombinationError(ValueError):
    """Raised when ETABS rows cannot be converted into footing inputs."""


def _as_float(row: Mapping[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0.0))
    except (TypeError, ValueError) as exc:
        raise CriticalCombinationError(
            f"ETABS returned a non-numeric {key} value for point '{row.get('UniqueName', '')}'."
        ) from exc


def infer_limit_state(scale_factors: Sequence[float]) -> str:
    """Infer the footing limit state from a response combination's factors."""
    if not scale_factors:
        raise CriticalCombinationError("A response combination has no load factors.")
    return ULTIMATE if any(abs(float(factor)) > 1.000001 for factor in scale_factors) else SERVICE


def compression_is_negative(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Detect the reaction sign from a gravity case, falling back to the overall FZ sum."""
    gravity_rows = [
        row
        for row in rows
        if str(row.get("OutputCase", "")).strip().casefold() in {"dead", "dead load", "dl", "g"}
        or "dead" in str(row.get("OutputCase", "")).casefold()
        or "gravity" in str(row.get("OutputCase", "")).casefold()
    ]
    candidates = gravity_rows or list(rows)
    signed_total = sum(_as_float(row, "FZ") for row in candidates)
    if abs(signed_total) <= 1e-9:
        largest = max(candidates, key=lambda row: abs(_as_float(row, "FZ")), default=None)
        if largest is None:
            raise CriticalCombinationError("ETABS returned no vertical reactions for sign detection.")
        signed_total = _as_float(largest, "FZ")
    return signed_total < 0


def _summarize_missing(missing: list[str]) -> str:
    shown = missing[:8]
    remainder = len(missing) - len(shown)
    suffix = f"; and {remainder} more" if remainder else ""
    return "; ".join(shown) + suffix


def select_critical_reactions(
    rows: list[dict[str, Any]],
    combination_factors: Mapping[str, Sequence[float]],
) -> list[dict[str, Any]]:
    """Select the maximum-compression row for each support and limit state.

    Only ETABS response combinations are considered. Limit states are inferred
    from their factors, and ties in compression are resolved by the largest
    resultant of MX and MY.
    """
    if not rows:
        raise CriticalCombinationError("ETABS returned no joint-reaction rows.")

    if not combination_factors:
        raise CriticalCombinationError("The ETABS model has no response combinations.")
    combination_states = {
        name: infer_limit_state(factors) for name, factors in combination_factors.items()
    }
    available_states = set(combination_states.values())
    if SERVICE not in available_states or ULTIMATE not in available_states:
        classifications = ", ".join(
            f"{name}={state}" for name, state in sorted(combination_states.items())
        )
        raise CriticalCombinationError(
            "ETABS response combinations must include at least one automatically inferred Service "
            f"and Ultimate combination. Current classifications: {classifications}."
        )

    negative_compression = compression_is_negative(rows)
    selected: dict[tuple[str, str], tuple[tuple[float, float], dict[str, Any]]] = {}
    support_names: set[str] = set()
    matched_states: dict[str, set[str]] = defaultdict(set)

    for source in rows:
        node_id = str(source.get("UniqueName", "")).strip()
        if not node_id:
            raise CriticalCombinationError("A joint-reaction row is missing its ETABS UniqueName.")
        case_name = str(source.get("OutputCase", "")).strip()
        limit_state = combination_states.get(case_name)
        if limit_state is None:
            continue
        support_names.add(node_id)

        matched_states[node_id].add(limit_state)
        fz = _as_float(source, "FZ")
        compression_kn = -fz if negative_compression else fz
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
        raise CriticalCombinationError(
            "A compressive critical reaction could not be selected for every support: "
            + _summarize_missing(missing)
            + "."
        )

    return [
        selected[(node_id, limit_state)][1]
        for node_id in sorted(support_names)
        for limit_state in (SERVICE, ULTIMATE)
    ]
