import base64
import binascii
import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

from flask import current_app

from utils.api_error import ApiError


DEFAULT_MAX_UPLOAD_SIZE_MB = 5
DEFAULT_MAX_FILE_COUNT = 10
INVALID_UPLOAD_MESSAGE = "Invalid file type or file size exceeds allowed limit."
RAW_STRING_UPLOAD_MESSAGE = "Invalid file type or file size exceeds allowed limit."
ALLOWED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
SAFE_REFERENCE_PREFIXES = ("/uploads/", "uploads/")
DATA_URL_PATTERN = re.compile(
    r"^data:(?P<mime>[a-z0-9.+-]+/[a-z0-9.+-]+);base64,(?P<data>[a-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
FILENAME_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def get_max_upload_size_bytes() -> int:
    configured_value = current_app.config.get("MAX_UPLOAD_SIZE_MB", DEFAULT_MAX_UPLOAD_SIZE_MB)
    try:
        size_mb = int(configured_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("MAX_UPLOAD_SIZE_MB must be a positive integer.") from exc
    if size_mb <= 0:
        raise RuntimeError("MAX_UPLOAD_SIZE_MB must be greater than zero.")
    return size_mb * 1024 * 1024


def sanitize_filename(filename: str | None, *, default_stem: str = "upload") -> str:
    candidate = (filename or "").strip()
    path_name = PurePosixPath(candidate).name if candidate else default_stem
    if "." in path_name:
        stem, suffix = path_name.rsplit(".", 1)
        suffix = f".{suffix.lower()}"
    else:
        stem, suffix = path_name, ""
    sanitized_stem = FILENAME_SANITIZE_PATTERN.sub("_", stem).strip("._-") or default_stem
    return f"{sanitized_stem}{suffix}"


def validate_file_reference(
    value,
    *,
    field_name: str,
    file_name: str | None = None,
    content_type: str | None = None,
) -> str:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        _raise_invalid_upload()

    candidate = value.strip()
    if not candidate:
        _raise_invalid_upload()

    data_url_match = DATA_URL_PATTERN.match(candidate)
    if data_url_match:
        return _validate_data_url(
            candidate,
            field_name=field_name,
            file_name=file_name,
            content_type=content_type,
        )

    if _is_safe_stored_reference(candidate):
        return _validate_safe_reference(
            candidate,
            field_name=field_name,
            file_name=file_name,
            content_type=content_type,
        )

    raise ApiError(RAW_STRING_UPLOAD_MESSAGE, status_code=400)


def validate_file_reference_list(
    values,
    *,
    field_name: str,
    max_files: int = DEFAULT_MAX_FILE_COUNT,
) -> list[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        _raise_invalid_upload()
    if len(values) > max_files:
        _raise_invalid_upload()

    normalized_values: list[str] = []
    for index, item in enumerate(values, start=1):
        normalized_value = validate_file_reference(
            item,
            field_name=f"{field_name}[{index}]",
        )
        if normalized_value:
            normalized_values.append(normalized_value)
    return normalized_values


def validate_attachment_list(
    attachments,
    *,
    field_name: str = "attachments",
    max_files: int = DEFAULT_MAX_FILE_COUNT,
) -> list[dict]:
    if attachments in (None, ""):
        return []
    if not isinstance(attachments, list):
        _raise_invalid_upload()
    if len(attachments) > max_files:
        _raise_invalid_upload()

    normalized_attachments: list[dict] = []
    for index, item in enumerate(attachments, start=1):
        if isinstance(item, str):
            normalized_attachments.append(
                {
                    "name": sanitize_filename(f"attachment-{index}"),
                    "file_name": sanitize_filename(f"attachment-{index}"),
                    "file_kind": "document",
                    "content_type": _content_type_for_reference(item),
                    "data_url": validate_file_reference(item, field_name=f"{field_name}[{index}]"),
                    "size_bytes": _size_for_reference(item),
                }
            )
            continue

        if not isinstance(item, dict):
            _raise_invalid_upload()

        file_name = sanitize_filename(
            item.get("file_name") or item.get("name") or f"attachment-{index}"
        )
        normalized_reference = validate_file_reference(
            item.get("data_url"),
            field_name=f"{field_name}[{index}]",
            file_name=file_name,
            content_type=item.get("content_type"),
        )
        normalized_attachments.append(
            {
                "id": item.get("id"),
                "name": sanitize_filename(item.get("name") or file_name),
                "file_name": file_name,
                "file_kind": _normalize_file_kind(item.get("file_kind")),
                "content_type": _content_type_for_reference(
                    normalized_reference,
                    fallback=item.get("content_type"),
                ),
                "data_url": normalized_reference,
                "size_bytes": _size_for_reference(normalized_reference),
            }
        )
    return normalized_attachments


def validate_document_upload(document_upload, *, field_name: str = "document_upload") -> dict | None:
    if document_upload in (None, ""):
        return None
    if isinstance(document_upload, str):
        normalized_reference = validate_file_reference(document_upload, field_name=field_name)
        return {
            "file_name": sanitize_filename("document"),
            "content_type": _content_type_for_reference(normalized_reference),
            "data_url": normalized_reference,
            "size_bytes": _size_for_reference(normalized_reference),
        }
    if not isinstance(document_upload, dict):
        _raise_invalid_upload()

    file_name = sanitize_filename(document_upload.get("file_name"), default_stem="document")
    normalized_reference = validate_file_reference(
        document_upload.get("data_url"),
        field_name=field_name,
        file_name=file_name,
        content_type=document_upload.get("content_type"),
    )
    return {
        "file_name": file_name,
        "content_type": _content_type_for_reference(
            normalized_reference,
            fallback=document_upload.get("content_type"),
        ),
        "data_url": normalized_reference,
        "size_bytes": _size_for_reference(normalized_reference),
    }


def _validate_data_url(
    data_url: str,
    *,
    field_name: str,
    file_name: str | None,
    content_type: str | None,
) -> str:
    match = DATA_URL_PATTERN.match(data_url)
    if not match:
        _raise_invalid_upload()

    mime_type = match.group("mime").lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        _raise_invalid_upload()

    encoded_data = re.sub(r"\s+", "", match.group("data"))
    if not encoded_data:
        _raise_invalid_upload()

    try:
        decoded_bytes = base64.b64decode(encoded_data, validate=True)
    except (ValueError, binascii.Error):
        _raise_invalid_upload()

    if not decoded_bytes:
        _raise_invalid_upload()
    if len(decoded_bytes) > get_max_upload_size_bytes():
        _raise_invalid_upload()

    detected_mime_type = _detect_mime_type(decoded_bytes)
    if detected_mime_type != mime_type:
        _raise_invalid_upload()

    normalized_file_name = sanitize_filename(
        file_name,
        default_stem=_default_stem_for_mime(detected_mime_type),
    )
    extension = PurePosixPath(normalized_file_name).suffix.lower()
    if not extension:
        normalized_file_name = f"{normalized_file_name}{ALLOWED_MIME_TYPES[detected_mime_type]}"
        extension = PurePosixPath(normalized_file_name).suffix.lower()
    if extension == ".jpeg":
        extension = ".jpg"
    if extension not in ALLOWED_EXTENSIONS:
        _raise_invalid_upload()

    normalized_content_type = (content_type or "").strip().lower()
    if normalized_content_type and normalized_content_type != detected_mime_type:
        _raise_invalid_upload()

    return f"data:{detected_mime_type};base64,{encoded_data}"


def _validate_safe_reference(
    reference: str,
    *,
    field_name: str,
    file_name: str | None,
    content_type: str | None,
) -> str:
    del field_name
    parsed = urlparse(reference)
    path = parsed.path or reference
    if ".." in path.replace("\\", "/"):
        _raise_invalid_upload()

    safe_name = sanitize_filename(file_name or PurePosixPath(path).name, default_stem="upload")
    extension = PurePosixPath(safe_name or path).suffix.lower()
    if extension == ".jpeg":
        extension = ".jpg"
    if extension not in ALLOWED_EXTENSIONS:
        _raise_invalid_upload()

    normalized_content_type = (content_type or "").strip().lower()
    if normalized_content_type and normalized_content_type not in ALLOWED_MIME_TYPES:
        _raise_invalid_upload()
    if normalized_content_type:
        expected_extension = ALLOWED_MIME_TYPES[normalized_content_type]
        if expected_extension == ".jpg":
            if extension not in {".jpg", ".jpeg"}:
                _raise_invalid_upload()
        elif extension != expected_extension:
            _raise_invalid_upload()

    return reference.strip()


def _is_safe_stored_reference(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return True
    normalized_value = value.replace("\\", "/")
    return normalized_value.startswith(SAFE_REFERENCE_PREFIXES)


def _content_type_for_reference(reference: str, fallback: str | None = None) -> str | None:
    if not reference:
        return None
    data_url_match = DATA_URL_PATTERN.match(reference)
    if data_url_match:
        return data_url_match.group("mime").lower()
    if fallback:
        normalized_fallback = str(fallback).strip().lower()
        if normalized_fallback in ALLOWED_MIME_TYPES:
            return normalized_fallback
    extension = PurePosixPath(urlparse(reference).path or reference).suffix.lower()
    if extension == ".jpeg":
        extension = ".jpg"
    for mime_type, mime_extension in ALLOWED_MIME_TYPES.items():
        if mime_extension == extension or (mime_extension == ".jpg" and extension in {".jpg", ".jpeg"}):
            return mime_type
    return None


def _size_for_reference(reference: str) -> int | None:
    data_url_match = DATA_URL_PATTERN.match(reference or "")
    if not data_url_match:
        return None
    encoded_data = re.sub(r"\s+", "", data_url_match.group("data"))
    decoded_size = (len(encoded_data) * 3) // 4
    padding = encoded_data.count("=")
    return max(decoded_size - padding, 0)


def _normalize_file_kind(file_kind) -> str:
    candidate = str(file_kind or "").strip().lower()
    return candidate if candidate in {"photo", "document"} else "document"


def _default_stem_for_mime(mime_type: str) -> str:
    if mime_type == "application/pdf":
        return "document"
    return "image"


def _detect_mime_type(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _raise_invalid_upload() -> None:
    raise ApiError(INVALID_UPLOAD_MESSAGE, status_code=400)
