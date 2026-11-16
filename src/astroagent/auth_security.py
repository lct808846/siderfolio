"""Bounded password hashing, one-use credentials, encrypted mail and TOTP."""

import base64
import hashlib
import hmac
import ipaddress
import secrets
import struct
import time
import unicodedata
from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from email_validator import EmailNotValidError, validate_email

from astroagent.errors import ServiceError

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)


def email_address(value):
    try:
        address = validate_email(value, check_deliverability=False, allow_smtputf8=False)
        # Local parts remain case-sensitive; do not merge aliases or provider dots.
        return f"{address.local_part}@{address.ascii_domain.lower()}", value.strip()
    except (EmailNotValidError, TypeError, ValueError) as exc:
        raise ServiceError(422, "invalid_email", "请输入有效邮箱地址。") from exc


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def opaque():
    return secrets.token_urlsafe(32)


def cipher(settings):
    try:
        return Fernet(settings.secret.get_secret_value().encode("ascii"))
    except Exception as exc:
        raise ServiceError(503, "identity_configuration_invalid", "身份服务尚未配置。") from exc


def keyed(settings, purpose, value):
    return hmac.new(
        settings.secret.get_secret_value().encode(), f"{purpose}:{value}".encode(), hashlib.sha256
    ).hexdigest()


def normalize_client_source(value):
    raw = (value or "").strip().lower()
    if not raw or raw in {"localhost", "testclient", "unknown"}:
        return "local"
    if raw.startswith("::ffff:"):
        raw = raw[7:]
    try:
        ip = ipaddress.ip_address(raw)
        if ip.is_loopback or ip.is_private or ip.is_link_local:
            return "local"
        return ip.exploded
    except ValueError:
        return raw


@lru_cache(maxsize=4)
def blocklist(path, expected):
    try:
        raw = path.read_bytes()
        if len(raw) > 16 * 1024**2 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Invalid password blocklist")
        values = frozenset(
            unicodedata.normalize("NFC", line).casefold() for line in raw.decode().splitlines()
        )
        if len(values) < 9000:
            raise ValueError("Password blocklist is incomplete")
        return values
    except Exception as exc:
        raise ServiceError(
            503, "password_policy_unavailable", "密码安全词表未配置，请联系管理员。"
        ) from exc


def hash_password(password, settings):
    password = unicodedata.normalize("NFC", password)
    if not 8 <= len(password) <= 128 or len(password.encode()) > 1024:
        raise ServiceError(422, "password_policy", "密码至少需要 8 个字符")
    if not settings.password_blocklist or not settings.password_blocklist_sha256:
        raise ServiceError(503, "password_policy_unavailable", "密码安全词表尚未配置。")
    if (
        password.casefold()
        in blocklist(settings.password_blocklist, settings.password_blocklist_sha256)
        or len(set(password)) == 1
    ):
        raise ServiceError(422, "password_common", "该密码过于常见，请换用独立的长密码。")
    return PASSWORDS.hash(password)


def verify_password(encoded, password):
    try:
        return PASSWORDS.verify(encoded, unicodedata.normalize("NFC", password))
    except (VerificationError, InvalidHashError, ValueError):
        return False


def totp_step(secret, code, last_step=-1):
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    counter = int(time.time()) // 30
    key = base64.b32decode(secret, casefold=True)
    for step in (counter, counter - 1, counter + 1):
        mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
        position = mac[-1] & 15
        value = (struct.unpack(">I", mac[position : position + 4])[0] & 0x7FFFFFFF) % 1000000
        if step > last_step and hmac.compare_digest(f"{value:06d}", code):
            return step
    return None
