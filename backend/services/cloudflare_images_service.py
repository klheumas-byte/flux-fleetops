"""Small, server-only Cloudflare Images adapter for incident evidence."""

import base64
import binascii
import json
import re
import mimetypes
import secrets
import urllib.error
import urllib.request
from pathlib import PurePosixPath

from flask import current_app

from utils.api_error import ApiError


IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class CloudflareImagesError(Exception):
    """Provider/validation error kept free of credentials and response bodies."""


def _settings():
    config = current_app.config
    if not config.get("CLOUDFLARE_IMAGES_ENABLED"):
        raise ApiError("Cloudflare Images is not enabled.", status_code=503)
    values = {name: str(config.get(name) or "").strip() for name in (
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_IMAGES_API_TOKEN",
        "CLOUDFLARE_IMAGES_ACCOUNT_HASH",
        "CLOUDFLARE_IMAGES_PUBLIC_VARIANT",
        "CLOUDFLARE_IMAGES_THUMBNAIL_VARIANT",
    )}
    if any(not value for value in values.values()):
        raise ApiError("Cloudflare Images configuration is incomplete.", status_code=503)
    return values


def validate_image(data: bytes | str, filename: str | None = None, content_type: str | None = None, *, mime_type: str | None = None):
    if isinstance(data, str) and data.startswith("data:"):
        match = re.match(r"^data:(?P<mime>[^;]+);base64,(?P<body>.+)$", data, re.IGNORECASE | re.DOTALL)
        if not match:
            raise ApiError("Invalid image data.", status_code=400)
        try:
            data = base64.b64decode(re.sub(r"\s+", "", match.group("body")), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ApiError("Invalid image data.", status_code=400) from exc
        content_type = content_type or match.group("mime")
    normalized_mime = mime_type or content_type
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_IMAGE_BYTES:
        raise ApiError("Image is empty or exceeds the allowed size.", status_code=400)
    normalized_mime = str(normalized_mime or "").strip().lower()
    if normalized_mime == "image/jpg":
        normalized_mime = "image/jpeg"
    if normalized_mime not in IMAGE_MIME_TYPES:
        raise ApiError("Only JPG, PNG, and WEBP images are supported.", status_code=400)
    suffix = PurePosixPath(str(filename or "")).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    expected = {"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"}, "image/webp": {".webp"}}[normalized_mime]
    if suffix and suffix not in expected:
        raise ApiError("Image extension does not match its content type.", status_code=400)
    signatures = {
        "image/jpeg": data[:3] == b"\xff\xd8\xff",
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }
    if not signatures[normalized_mime]:
        raise ApiError("The uploaded image is corrupt or has an invalid file signature.", status_code=400)
    return bytes(data), normalized_mime


def _request(url: str, *, method: str = "GET", body: bytes | None = None, headers: dict | None = None):
    settings = _settings()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {settings['CLOUDFLARE_IMAGES_API_TOKEN']}", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as error:
        status = error.code
        message = {
            401: "Cloudflare authentication failed.",
            403: "Cloudflare Images permission or account scope is invalid.",
            404: "Cloudflare Images account or asset was not found.",
            409: "Cloudflare Images request conflicts with existing state.",
            429: "Cloudflare Images rate limit reached.",
        }.get(status, "Cloudflare Images request failed.")
        raise ApiError(message, status_code=502) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ApiError("Cloudflare Images is temporarily unavailable.", status_code=503) from error


def upload_image(data: bytes, *, filename: str, mime_type: str | None = None, content_type: str | None = None) -> dict:
    validated_data, validated_mime = validate_image(data, mime_type=mime_type or content_type, filename=filename)
    settings = _settings()
    boundary = f"----FluxFleetOps{secrets.token_hex(12)}".encode()
    fields = []
    disposition = b'Content-Disposition: form-data; name="file"; filename="' + PurePosixPath(filename).name.encode("utf-8", "ignore") + b'"\r\n'
    fields.append(b"--" + boundary + b"\r\n" + disposition + b"Content-Type: " + validated_mime.encode() + b"\r\n\r\n" + validated_data + b"\r\n")
    body = b"".join(fields) + b"--" + boundary + b"--\r\n"
    status, response = _request(
        f"https://api.cloudflare.com/client/v4/accounts/{settings['CLOUDFLARE_ACCOUNT_ID']}/images/v1",
        method="POST",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
    )
    result = response.get("result") or {}
    asset_id = result.get("id")
    if status < 200 or status >= 300 or not response.get("success") or not asset_id:
        raise ApiError("Cloudflare Images did not return a valid image asset.", status_code=502)
    public_variant = settings["CLOUDFLARE_IMAGES_PUBLIC_VARIANT"]
    thumbnail_variant = settings["CLOUDFLARE_IMAGES_THUMBNAIL_VARIANT"]
    return {
        "provider_asset_id": asset_id,
        "variants": result.get("variants") or [],
        "public_variant": public_variant,
        "thumbnail_variant": thumbnail_variant,
        "public_url": build_variant_url(asset_id, public_variant),
        "thumbnail_url": build_variant_url(asset_id, thumbnail_variant),
    }


def delete_image(asset_id: str) -> bool:
    settings = _settings()
    try:
        status, response = _request(
            f"https://api.cloudflare.com/client/v4/accounts/{settings['CLOUDFLARE_ACCOUNT_ID']}/images/v1/{asset_id}",
            method="DELETE",
        )
    except ApiError as error:
        # Idempotent cleanup: an already-deleted provider asset is safe.
        if "not found" in str(error).lower():
            return True
        raise
    return 200 <= status < 300 and bool(response.get("success"))


def build_variant_url(asset_id: str, variant: str) -> str:
    settings = _settings()
    allowed = {settings["CLOUDFLARE_IMAGES_PUBLIC_VARIANT"], settings["CLOUDFLARE_IMAGES_THUMBNAIL_VARIANT"]}
    if variant not in allowed:
        raise ApiError("Unsupported Cloudflare Images variant.", status_code=400)
    return f"https://imagedelivery.net/{settings['CLOUDFLARE_IMAGES_ACCOUNT_HASH']}/{asset_id}/{variant}"


def health_check() -> bool:
    settings = _settings()
    status, response = _request(
        f"https://api.cloudflare.com/client/v4/accounts/{settings['CLOUDFLARE_ACCOUNT_ID']}/images/v1/variants"
    )
    return status == 200 and bool(response.get("success"))
