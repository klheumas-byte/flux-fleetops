from __future__ import annotations

from typing import Any


FUEL_LEVEL_MAX_EIGHTHS = 8
FUEL_LEVEL_LABELS = {
    0: "Empty",
    1: "Very Low",
    2: "Low",
    3: "Below Half",
    4: "Half Tank",
    5: "Above Half",
    6: "Three Quarters",
    7: "Nearly Full",
    8: "Full Tank",
}

_TEXT_MAPPINGS = {
    "e": 0,
    "empty": 0,
    "none": 0,
    "zero": 0,
    "low": 1,
    "very low": 1,
    "quarter": 2,
    "one quarter": 2,
    "1 quarter": 2,
    "1/4": 2,
    "25": 2,
    "25 percent": 2,
    "25%": 2,
    "below half": 3,
    "three eighths": 3,
    "3/8": 3,
    "half": 4,
    "half tank": 4,
    "1/2": 4,
    "4/8": 4,
    "50": 4,
    "50 percent": 4,
    "50%": 4,
    "above half": 5,
    "five eighths": 5,
    "5/8": 5,
    "three quarters": 6,
    "three quarter": 6,
    "3/4": 6,
    "6/8": 6,
    "75": 6,
    "75 percent": 6,
    "75%": 6,
    "nearly full": 7,
    "almost full": 7,
    "7/8": 7,
    "full": 8,
    "full tank": 8,
    "f": 8,
    "8/8": 8,
    "100": 8,
    "100 percent": 8,
    "100%": 8,
}


def _round_to_eighths(value: float) -> int:
    return max(0, min(FUEL_LEVEL_MAX_EIGHTHS, int(round(value))))


def normalize_fuel_level_eighths(value: Any) -> tuple[int | None, str | None]:
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, "Boolean values are not valid fuel levels."
    if isinstance(value, (int, float)):
        numeric_value = float(value)
        if 0 <= numeric_value <= 1:
            return _round_to_eighths(numeric_value * FUEL_LEVEL_MAX_EIGHTHS), None
        if 0 <= numeric_value <= FUEL_LEVEL_MAX_EIGHTHS:
            return _round_to_eighths(numeric_value), None
        if 0 <= numeric_value <= 100:
            return _round_to_eighths((numeric_value / 100) * FUEL_LEVEL_MAX_EIGHTHS), None
        return None, "Fuel level must map to a value between 0 and 8."
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None, None
        if normalized in _TEXT_MAPPINGS:
            return _TEXT_MAPPINGS[normalized], None
        if normalized.endswith("%"):
            try:
                percentage_value = float(normalized[:-1].strip())
            except ValueError:
                return None, f"Unsupported fuel level value: {value}."
            return normalize_fuel_level_eighths(percentage_value)
        if "/" in normalized:
            left, _, right = normalized.partition("/")
            try:
                numerator = float(left.strip())
                denominator = float(right.strip())
            except ValueError:
                return None, f"Unsupported fuel level value: {value}."
            if denominator <= 0:
                return None, "Fuel level denominator must be greater than zero."
            return normalize_fuel_level_eighths((numerator / denominator) * FUEL_LEVEL_MAX_EIGHTHS)
        try:
            return normalize_fuel_level_eighths(float(normalized))
        except ValueError:
            return None, f"Unsupported fuel level value: {value}."
    return None, f"Unsupported fuel level value: {value}."


def build_fuel_level_details(value: Any, *, tank_capacity_litres: Any = None) -> dict | None:
    normalized, _ = normalize_fuel_level_eighths(value)
    if normalized is None:
        return None
    estimated_litres = None
    if isinstance(tank_capacity_litres, (int, float)) and tank_capacity_litres > 0:
        estimated_litres = round((normalized / FUEL_LEVEL_MAX_EIGHTHS) * float(tank_capacity_litres), 2)
    return {
        "eighths": normalized,
        "fraction": f"{normalized}/{FUEL_LEVEL_MAX_EIGHTHS}",
        "percentage": round((normalized / FUEL_LEVEL_MAX_EIGHTHS) * 100, 1),
        "label": FUEL_LEVEL_LABELS.get(normalized, f"{normalized}/8"),
        "color_state": "red" if normalized <= 2 else "amber" if normalized <= 5 else "green",
        "estimated_litres": estimated_litres,
    }