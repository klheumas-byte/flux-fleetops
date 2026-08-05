from __future__ import annotations


PERSONAL_USE_TYPE = "personal_use"
PERSONAL_USE_CATEGORY = "PERSONAL_USE"

# Accepted at API/service boundaries so older clients and records remain usable.
PERSONAL_USE_TYPE_ALIASES = frozenset(
    {
        PERSONAL_USE_TYPE,
        "PERSONAL_USE",
        "personal-use",
        "personal use",
        "Personal Use",
        "personal_vehicle_use",
        "PERSONAL_VEHICLE_USE",
        "Personal Vehicle Use",
    }
)


def normalize_type_token(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "personal_vehicle_use":
        return PERSONAL_USE_TYPE
    return normalized or None


def personal_use_query_values() -> list[str]:
    return sorted(PERSONAL_USE_TYPE_ALIASES)
