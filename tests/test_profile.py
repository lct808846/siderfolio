"""Profile image acceptance using synthetic bytes, never personal images."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from astroagent.auth_store import AuthStore
from astroagent.errors import ServiceError
from astroagent.profile_service import MAX_AVATAR_BYTES, normalize_avatar


def image_bytes(fmt="PNG", size=(80, 60), **kwargs):
    buffer = io.BytesIO()
    Image.new("RGB", size, "green").save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
def test_avatar_is_normalized_raster_without_appended_payload(fmt):
    raw = image_bytes(fmt) + b"synthetic-private-polyglot-payload"
    normalized, media = normalize_avatar(raw)
    assert media == "image/png"
    with Image.open(io.BytesIO(normalized)) as image:
        assert image.format == "PNG" and image.size == (256, 256)
    assert b"synthetic-private-polyglot-payload" not in normalized


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"", "avatar_empty"),
        (b"not an image", "invalid_avatar_image"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "invalid_avatar_image"),
        (b"x" * (MAX_AVATAR_BYTES + 1), "avatar_too_large"),
    ],
    ids=["empty", "invalid", "svg", "oversize"],
)
def test_avatar_rejects_invalid_or_oversized_input(raw, code):
    with pytest.raises(ServiceError) as error:
        normalize_avatar(raw)
    assert error.value.error.code == code


def test_avatar_rejects_unsupported_valid_image():
    with pytest.raises(ServiceError) as error:
        normalize_avatar(image_bytes("BMP"))
    assert error.value.error.code == "invalid_avatar_format"


def test_avatar_strips_private_exif_and_applies_orientation():
    exif = Image.Exif()
    exif[0x010E] = "synthetic-private-camera-location"
    exif[0x0112] = 6
    normalized, _ = normalize_avatar(image_bytes("JPEG", exif=exif))
    with Image.open(io.BytesIO(normalized)) as image:
        assert not image.getexif()
        assert not image.info.get("icc_profile")
    assert b"synthetic-private-camera-location" not in normalized


def test_avatar_enforces_declared_source_pixel_limit():
    # A highly compressed image can be far below the byte limit while exceeding
    # the intended decode budget. This is an actual image, not a forged header.
    with pytest.raises(ServiceError) as error:
        normalize_avatar(image_bytes(size=(4097, 4096)))
    assert error.value.error.code == "invalid_avatar_image"


def test_avatar_version_changes_for_updates_in_the_same_second():
    user = {
        "id": "synthetic",
        "email_display": "observer@example.org",
        "username": "Observer",
        "admin": False,
        "totp_secret": None,
        "mfa_at": None,
        "avatar_updated_at": datetime(2026, 11, 16, tzinfo=UTC),
    }
    before = AuthStore.public_user(user)["avatar_url"]
    user["avatar_updated_at"] += timedelta(microseconds=100)
    after = AuthStore.public_user(user)["avatar_url"]
    assert before != after
