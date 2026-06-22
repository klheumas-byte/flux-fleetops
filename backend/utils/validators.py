import re


EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"^\+?\d{9,15}$")


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    normalized = "".join(character for character in value.strip() if character.isdigit() or character == "+")
    return normalized or None


def validate_email(value: str | None) -> bool:
    if not value:
        return False
    return EMAIL_PATTERN.match(value) is not None


def validate_phone(value: str | None) -> bool:
    if not value:
        return False
    return PHONE_PATTERN.match(value) is not None
