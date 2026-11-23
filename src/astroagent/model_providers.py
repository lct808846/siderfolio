"""Encrypted provider settings in the existing server control-plane metadata."""

import hashlib
import ipaddress
import json
import math
import socket
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from astroagent.errors import ServiceError
from astroagent.model_schemas import ChatModelCatalog, ChatModelOption

KEY = "model_providers_v1"
FAKE_IP_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("2001:2::/48"),
)


def directory_address_allowed(value, *, local_proxy=False):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if (
        address.is_multicast
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
    ):
        return False
    if address.is_global:
        return True
    # Only explicitly configured loopback deployments may use these proxy DNS ranges.
    # Private LAN/ULA addresses and literal Fake-IP URLs remain blocked.
    return local_proxy and any(address in network for network in FAKE_IP_NETWORKS)


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    label: str = Field(min_length=1, max_length=80)
    input_price_per_1m: float | None = Field(default=None, ge=0, le=10000)
    output_price_per_1m: float | None = Field(default=None, ge=0, le=10000)
    price_currency: Literal["USD", "CNY"] = "USD"

    @field_validator("input_price_per_1m", "output_price_per_1m")
    @classmethod
    def finite_price(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("模型单价必须为有效非负数字。")
        return value


def provider_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(c.isspace() for c in value)
        or "\\" in value
        or len(value) > 500
        or parsed.hostname.lower() in {"localhost", "host.docker.internal"}
        or parsed.hostname.lower().endswith((".local", ".internal", ".localhost"))
    ):
        raise ValueError("请填写不含凭据或查询参数的公共 HTTPS API 地址。")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if "." not in parsed.hostname:
            raise ValueError("请使用公共模型服务域名。") from None
    else:
        if not address.is_global or address.is_multicast:
            raise ValueError("此入口仅支持公共 HTTPS 服务。")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("API 端口无效。")
    return value.rstrip("/")


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)
    revision: int = Field(ge=0)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,23}$")
    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=1, max_length=500)
    protocol: Literal["openai_chat", "openai_responses", "anthropic", "gemini"] = "openai_chat"
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    enabled: bool = True
    thinking_parameter: Literal["none", "thinking", "enable_thinking"] = "none"
    models: list[ProviderModel] = Field(default_factory=list, max_length=32)

    @field_validator("base_url")
    @classmethod
    def url(cls, value):
        return provider_url(value)

    @model_validator(mode="after")
    def unique_models(self):
        if len({model.id for model in self.models}) != len(self.models):
            raise ValueError("模型 ID 不能重复。")
        if self.api_key and any(
            c.isspace() or ord(c) < 32 for c in self.api_key.get_secret_value()
        ):
            raise ValueError("API 密钥不能含空白或控制字符。")
        return self


class ProviderRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class DefaultModelInput(ProviderRevision):
    model: str = Field(min_length=1, max_length=128)


def model_key(provider, model):
    # Environment model identifiers remain valid for existing conversations.
    if provider["id"] == "system":
        return model["id"]
    suffix = hashlib.sha256(model["id"].encode()).hexdigest()[:24]
    return f"{provider['id']}:{suffix}"


class ProviderRegistry:
    def __init__(self, store, environment):
        self.store, self.environment = store, environment

    def initial(self):
        value = self.environment
        return {
            "revision": 0,
            "default_model": value.deepseek_model,
            "providers": [
                {
                    "id": "system",
                    "name": "现有模型服务",
                    "base_url": str(value.deepseek_base_url).rstrip("/"),
                    "protocol": value.model_protocol,
                    "api_key": value.deepseek_api_key.get_secret_value(),
                    "enabled": True,
                    "thinking_parameter": value.llm_thinking_parameter,
                    "models": [{"id": m.id, "label": m.label} for m in value.available_models],
                }
            ],
        }

    def read(self, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.read(connection)
        row = db.execute("SELECT value FROM public.auth_meta WHERE key=%s", (KEY,)).fetchone()
        if not row:
            return self.initial()
        try:
            value = json.loads(self.store.crypto.decrypt(row["value"].encode()))
            if not isinstance(value["providers"], list) or not isinstance(value["revision"], int):
                raise ValueError()
            return value
        except Exception as exc:
            raise ServiceError(
                503, "provider_configuration_invalid", "模型服务配置无法读取，请联系管理员。"
            ) from exc

    def catalog(self, value=None):
        value = value if value is not None else self.read()
        options = [
            ChatModelOption(
                id=model_key(provider, model), label=model["label"], provider=provider["name"]
            )
            for provider in value["providers"]
            if provider["enabled"] and provider["api_key"]
            for model in provider["models"]
        ]
        enabled = {model.id for model in options}
        default = value["default_model"]
        if default not in enabled:
            default = options[0].id if options else ""
        return ChatModelCatalog(configured=bool(options), default_model=default, models=options)

    def public(self, value=None):
        from astroagent.trace_runtime import lookup_reference_pricing

        value = value if value is not None else self.read()
        providers = []
        for provider in value["providers"]:
            models_out = []
            for model in provider["models"]:
                ref = lookup_reference_pricing(
                    [str(model.get("id") or ""), str(model.get("label") or "")]
                )
                entry = {**model, "selection_id": model_key(provider, model)}
                if ref is not None:
                    entry["reference_input_price_per_1m"] = ref["input_per_1m"]
                    entry["reference_output_price_per_1m"] = ref["output_per_1m"]
                    entry["reference_price_currency"] = (
                        ref["currency"] if ref.get("currency") in ("USD", "CNY") else "USD"
                    )
                models_out.append(entry)
            providers.append(
                {
                    **{k: v for k, v in provider.items() if k != "api_key"},
                    "key_configured": bool(provider["api_key"]),
                    "models": models_out,
                }
            )
        return {
            "revision": value["revision"],
            "default_model": self.catalog(value).default_model,
            "providers": providers,
        }

    def save(self, db, value, revision):
        if value["revision"] != revision:
            raise ServiceError(409, "provider_revision_changed", "配置已被更新，请刷新后重试。")
        if sum(len(p["models"]) for p in value["providers"]) > 256:
            raise ServiceError(422, "provider_model_limit", "最多启用 256 个模型。")
        value["default_model"] = self.catalog(value).default_model
        value["revision"] += 1
        encrypted = self.store.crypto.encrypt(
            json.dumps(value, ensure_ascii=False).encode()
        ).decode()
        db.execute(
            "INSERT INTO public.auth_meta(key,value) VALUES (%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            (KEY, encrypted),
        )
        return self.public(value)

    def provider(self, body, value):
        existing = next((p for p in value["providers"] if p["id"] == body.id), None)
        key = body.api_key.get_secret_value() if body.api_key else ""
        if not key and existing:
            if body.base_url != existing["base_url"] or body.protocol != existing["protocol"]:
                raise ServiceError(
                    422, "provider_key_required", "更改 API 地址或协议时请重新填写密钥。"
                )
            key = existing["api_key"]
        if not key:
            raise ServiceError(422, "provider_key_required", "请填写此服务商的 API 密钥。")
        return {**body.model_dump(exclude={"revision", "api_key"}), "api_key": key}

    def resolve(self, model_id):
        value = self.read()
        catalog = self.catalog(value)
        if not catalog.configured:
            raise ServiceError(
                503, "model_not_configured", "尚未配置可用模型，请由管理员添加服务商并启用模型。"
            )
        selected = model_id if model_id is not None else catalog.default_model
        for provider in value["providers"]:
            if not provider["enabled"] or not provider["api_key"]:
                continue
            for model in provider["models"]:
                if model_key(provider, model) == selected:
                    raw_in = model.get("input_price_per_1m")
                    raw_out = model.get("output_price_per_1m")
                    currency = model.get("price_currency")
                    return self.environment.model_copy(
                        update={
                            "deepseek_model": model["id"],
                            "selected_model_id": selected,
                            "selected_model_label": model.get("label") or model["id"],
                            "model_input_price_per_1m": (
                                float(raw_in) if isinstance(raw_in, (int, float)) else None
                            ),
                            "model_output_price_per_1m": (
                                float(raw_out) if isinstance(raw_out, (int, float)) else None
                            ),
                            "model_price_currency": (
                                currency if currency in ("USD", "CNY") else "USD"
                            ),
                            "deepseek_api_key": SecretStr(provider["api_key"]),
                            "deepseek_base_url": provider["base_url"],
                            "model_protocol": provider["protocol"],
                            "llm_thinking_parameter": provider["thinking_parameter"]
                            if provider["protocol"] == "openai_chat"
                            else "none",
                        }
                    )
        raise ServiceError(422, "model_not_enabled", "所选模型未启用，请刷新模型列表。")

    def pricing_index(self, value=None) -> tuple[dict[str, dict], dict[str, list[str]]]:
        value = value if value is not None else self.read()
        pricing: dict[str, dict] = {}
        aliases: dict[str, list[str]] = {}
        for provider in value["providers"]:
            for model in provider.get("models", []):
                sel_id = model_key(provider, model)
                upstream_id = str(model.get("id") or "")
                label = str(model.get("label") or "")
                candidates = [c for c in (sel_id, upstream_id, label) if c]
                for key in candidates:
                    aliases[key] = candidates
                raw_in = model.get("input_price_per_1m")
                raw_out = model.get("output_price_per_1m")
                if isinstance(raw_in, (int, float)) and isinstance(raw_out, (int, float)):
                    if raw_in >= 0 and raw_out >= 0:
                        currency = model.get("price_currency")
                        entry = {
                            "input_per_1m": float(raw_in),
                            "output_per_1m": float(raw_out),
                            "currency": currency if currency in ("USD", "CNY") else "USD",
                            "version": "已配置单价",
                        }
                        for key in candidates:
                            pricing[key] = entry
        return pricing, aliases

    def discover(self, body):
        from astroagent.model_client import provider_headers

        provider = self.provider(body, self.read())
        parsed = urlsplit(provider["base_url"])
        try:
            addresses = socket.getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
            local_proxy = self.store.settings.local_http
            if not addresses or any(
                not directory_address_allowed(item[4][0], local_proxy=local_proxy)
                for item in addresses
            ):
                raise ServiceError(
                    422,
                    "provider_address_invalid",
                    "服务域名解析到了本机、内网或受限地址，请检查 DNS／代理设置。",
                )
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                with client.stream(
                    "GET",
                    provider["base_url"] + "/models",
                    headers={
                        **provider_headers(provider["protocol"], provider["api_key"]),
                    },
                ) as response:
                    if response.status_code in (401, 403):
                        raise ServiceError(
                            422, "provider_auth_failed", "服务商拒绝访问，请核对 API 密钥。"
                        )
                    if response.status_code != 200:
                        raise ServiceError(
                            502,
                            "provider_discovery_failed",
                            "未能读取模型目录，可手动添加模型 ID。",
                        )
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 1024 * 1024:
                            raise ServiceError(
                                502, "provider_catalog_too_large", "模型目录过大，请手动添加模型。"
                            )
            data = json.loads(content)
            result = {}
            entries = data.get("models" if provider["protocol"] == "gemini" else "data", [])
            for item in entries[:2048]:
                if not isinstance(item, dict):
                    continue
                identifier = item.get("name" if provider["protocol"] == "gemini" else "id")
                if provider["protocol"] == "gemini":
                    if "generateContent" not in item.get("supportedGenerationMethods", []):
                        continue
                    identifier = (
                        identifier.removeprefix("models/") if isinstance(identifier, str) else None
                    )
                if isinstance(identifier, str):
                    try:
                        from astroagent.trace_runtime import lookup_reference_pricing

                        label = item.get("displayName") or item.get("display_name") or identifier
                        in_price = None
                        out_price = None
                        currency = "USD"
                        raw_pricing = item.get("pricing")
                        if isinstance(raw_pricing, dict):
                            try:
                                p_in = float(raw_pricing["prompt"])
                                p_out = float(raw_pricing["completion"])
                                if (
                                    math.isfinite(p_in)
                                    and math.isfinite(p_out)
                                    and p_in >= 0
                                    and p_out >= 0
                                ):
                                    # OpenRouter / compatible APIs report USD per single token.
                                    in_price = round(p_in * 1_000_000.0, 6) if p_in < 0.01 else p_in
                                    out_price = (
                                        round(p_out * 1_000_000.0, 6) if p_out < 0.01 else p_out
                                    )
                            except (KeyError, TypeError, ValueError):
                                pass
                        if in_price is None or out_price is None:
                            ref = lookup_reference_pricing([identifier, str(label)])
                            if ref is not None:
                                in_price = ref["input_per_1m"]
                                out_price = ref["output_per_1m"]
                                ref_currency = ref.get("currency")
                                currency = ref_currency if ref_currency in ("USD", "CNY") else "USD"
                        model = ProviderModel(
                            id=identifier,
                            label=label[:80],
                            input_price_per_1m=in_price,
                            output_price_per_1m=out_price,
                            price_currency=currency,
                        )
                    except ValueError:
                        continue
                    result[model.id] = model.model_dump()
                    if len(result) >= 512:
                        break
            return {
                "models": sorted(result.values(), key=lambda m: m["id"]),
                "truncated": bool(data.get("has_more") or data.get("nextPageToken"))
                or len(entries) > 512,
            }
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(
                502,
                "provider_discovery_failed",
                "无法读取服务商模型目录，请核对地址或手动添加模型 ID。",
            ) from exc


def configured_registry(environment):
    import os

    from pydantic import ValidationError

    from astroagent.auth_config import AuthSettings
    from astroagent.auth_store import AuthStore
    from astroagent.config import LocalSettings

    try:
        auth = AuthSettings()
    except ValidationError as exc:
        if not os.getenv("ASTROAGENT_AUTH_SECRET"):
            return None
        raise ServiceError(503, "identity_configuration_invalid", "模型服务配置尚未就绪。") from exc
    if not auth.secret.get_secret_value():
        return None
    return ProviderRegistry(AuthStore(LocalSettings(), auth), environment)


def configured_pricing_snapshot(environment=None) -> tuple[dict[str, dict], dict[str, list[str]]]:
    from astroagent.config import Settings

    try:
        reg = configured_registry(environment or Settings())
        if reg is None:
            return {}, {}
        return reg.pricing_index()
    except Exception:
        return {}, {}
