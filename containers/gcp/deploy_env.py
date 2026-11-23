"""Prepare private input and validate effective Compose settings without printing secrets."""

import base64
import ipaddress
import json
import re
import secrets
import sys
from pathlib import Path

HEX_SECRET = re.compile("[0-9a-f]{64}")
HOST_LABEL = re.compile("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
EMAIL = re.compile(r"[\w.!#$%&'*+/=?^_{|}~-]+@[a-zA-Z0-9.-]+\.[a-zA-Z0-9-]+", re.ASCII)


def prepare(directory):
    env_file = directory / ".env"
    generated = {
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "ASTROAGENT_DB_PASSWORD": secrets.token_hex(32),
        "ASTROAGENT_PROXY_TOKEN": secrets.token_hex(32),
        "ASTROAGENT_AUTH_SECRET": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    }
    example = (directory / ".env.example").read_text(encoding="utf-8")
    for name, value in generated.items():
        example = example.replace(f"\n{name}=\n", f"\n{name}={value}\n", 1)
    try:
        with env_file.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(example)
    except FileExistsError:
        print("已有 .env，原有凭据已保留。")
    else:
        print("已生成 .env。请填写公网主机名、Gemini 和 SMTP 配置。")


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify_compose():
    services = json.load(sys.stdin)["services"]
    ingress = services["ingress"]["environment"]
    backend = services["backend"]["environment"]
    postgres = services["postgres"]["environment"]
    frontend = services["frontend"]["environment"]

    host = ingress["PUBLIC_HOST"]
    mode = ingress["SITE_MODE"]
    if mode == "ip":
        try:
            public_ip = ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            raise ValueError("IP 模式下 PUBLIC_HOST 必须是公网 IPv4。") from None
        check(
            public_ip.is_global and not public_ip.is_multicast and not public_ip.is_reserved,
            "IP 模式下 PUBLIC_HOST 必须是实际分配的公网 IPv4。",
        )
    elif mode == "domain":
        labels = host.split(".")
        check(
            len(host) <= 253
            and len(labels) >= 2
            and not labels[-1].isdigit()
            and all(HOST_LABEL.fullmatch(label) for label in labels),
            "域名模式使用小写域名（IDN 使用 ASCII 形式），不带协议和端口。",
        )
    else:
        raise ValueError("SITE_MODE 只能为 domain 或 ip。")

    # Caddy expands these values before parsing its configuration. Allow only a single token.
    contact = ingress.get("ACME_CONTACT", "")
    check(
        not contact or (contact.startswith("email ") and EMAIL.fullmatch(contact[6:])),
        "ACME_EMAIL 必须是有效的联系邮箱。",
    )
    check(
        backend["ASTROAGENT_AUTH_REGISTRATION_ENABLED"] in {"true", "false"},
        "REGISTRATION_ENABLED 只能为 true 或 false。",
    )
    check(EMAIL.fullmatch(backend["ASTROAGENT_AUTH_SMTP_FROM"]), "请填写 SMTP_FROM 邮箱地址。")
    check(
        backend["ASTROAGENT_AUTH_SMTP_MODE"] in {"tls", "starttls"},
        "SMTP_MODE 只能为 tls 或 starttls。",
    )
    for settings, name in (
        (postgres, "POSTGRES_PASSWORD"),
        (postgres, "ASTROAGENT_DB_PASSWORD"),
        (backend, "ASTROAGENT_PROXY_TOKEN"),
    ):
        check(HEX_SECRET.fullmatch(settings[name]), f"{name} 应为 prepare 生成的 64 位十六进制值。")
    check(
        len(
            {
                postgres["POSTGRES_PASSWORD"],
                postgres["ASTROAGENT_DB_PASSWORD"],
                backend["ASTROAGENT_PROXY_TOKEN"],
            }
        )
        == 3,
        "数据库管理密码、应用密码和代理凭据必须独立。",
    )
    secret = backend["ASTROAGENT_AUTH_SECRET"]
    check(
        re.fullmatch("[A-Za-z0-9_-]{43}=", secret),
        "ASTROAGENT_AUTH_SECRET 应为 prepare 生成的密钥。",
    )
    check(
        frontend["ASTROAGENT_PROXY_TOKEN"] == backend["ASTROAGENT_PROXY_TOKEN"],
        "前端与后端的代理凭据必须一致。",
    )
    api_key = backend["DEEPSEEK_API_KEY"]
    check(
        re.fullmatch(r"[!-~]+", api_key),
        "Gemini 密钥不能含有空白或控制字符。",
    )
    check(
        re.fullmatch("[A-Za-z0-9][A-Za-z0-9._-]{0,127}", backend["DEEPSEEK_MODEL"]),
        "GEMINI_MODEL 应为模型 ID，不带 models/ 前缀。",
    )
    compute = backend["ASTROAGENT_COMPUTE_ENABLED"]
    check(compute in {"0", "1"}, "COMPUTE_ENABLED 只能为 0 或 1。")
    print(host, compute)


def main():
    if sys.argv[1:] == ["prepare"]:
        prepare(Path(__file__).resolve().parent)
        return
    if sys.argv[1:] == ["verify"]:
        try:
            verify_compose()
        except (KeyError, TypeError, json.JSONDecodeError):
            raise SystemExit("无法读取有效的 Compose 配置。") from None
        except ValueError as error:
            raise SystemExit(str(error)) from None
        return
    raise SystemExit("Use prepare or verify.")


if __name__ == "__main__":
    main()
