"""Parse sanitized browser/OS/device details, network prefixes and trusted locations."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

DeviceType = Literal["desktop", "mobile", "tablet", "unknown"]

COUNTRY_NAMES_ZH: dict[str, str] = {
    "CN": "中国",
    "HK": "中国香港",
    "MO": "中国澳门",
    "TW": "中国台湾",
    "US": "美国",
    "JP": "日本",
    "SG": "新加坡",
    "KR": "韩国",
    "GB": "英国",
    "DE": "德国",
    "FR": "法国",
    "CA": "加拿大",
    "AU": "澳大利亚",
    "NL": "荷兰",
    "CH": "瑞士",
    "SE": "瑞典",
    "IT": "意大利",
    "ES": "西班牙",
    "RU": "俄罗斯",
    "IN": "印度",
    "BR": "巴西",
    "MY": "马来西亚",
    "TH": "泰国",
    "VN": "越南",
    "ID": "印度尼西亚",
    "PH": "菲律宾",
    "NZ": "新西兰",
    "IE": "爱尔兰",
    "FI": "芬兰",
    "NO": "挪威",
    "DK": "丹麦",
    "PL": "波兰",
    "AT": "奥地利",
    "BE": "比利时",
    "PT": "葡萄牙",
    "AE": "阿联酋",
    "IL": "以色列",
    "TR": "土耳其",
    "MX": "墨西哥",
    "CL": "智利",
    "ZA": "南非",
    "T1": "Tor 匿名网络",
}

ANOMALY_LABELS_ZH: dict[str, str] = {
    "different_location": "异地登录（地区变化）",
    "new_network": "新网络位置登录",
    "new_device": "新设备登录",
}

_VERSION_TOKEN = r"([0-9]+(?:\.[0-9]+)?)"
_LOCAL_V4_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
_LOCAL_V6_NETWORKS = (ipaddress.IPv6Network("fc00::/7"),)


@dataclass(frozen=True)
class ClientContext:
    ip: str
    is_local: bool
    network_prefix: str
    country_code: str
    location: str
    device_type: DeviceType
    device_name: str
    os: str
    browser: str
    user_agent: str


def sanitize_header_text(value: str | None, *, max_length: int = 128) -> str:
    if not value:
        return ""
    cleaned = "".join(
        ch if not unicodedata.category(ch).startswith("C") else " " for ch in str(value)
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length]


def normalize_ip_display(value: str | None) -> tuple[str, bool, str]:
    """Return (display_ip, is_local, network_prefix)."""
    raw = sanitize_header_text(value, max_length=96)
    lower = raw.lower()
    if not lower or lower in {"unknown", "testclient", "localhost"}:
        return ("本地回环" if lower in {"localhost", "testclient"} else ""), True, "local"
    if lower.startswith("::ffff:"):
        raw = raw[7:]
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return raw[:64], False, ""
    is_lan = (
        any(ip in net for net in _LOCAL_V4_NETWORKS)
        if isinstance(ip, ipaddress.IPv4Address)
        else any(ip in net for net in _LOCAL_V6_NETWORKS)
    )
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or is_lan:
        return str(ip), True, "local"
    if isinstance(ip, ipaddress.IPv4Address):
        prefix = str(ipaddress.IPv4Network(f"{ip}/24", strict=False))
    else:
        prefix = str(ipaddress.IPv6Network(f"{ip}/48", strict=False))
    return str(ip), False, prefix


def sanitize_country_code(value: str | None) -> str:
    code = sanitize_header_text(value, max_length=8).upper()
    if re.fullmatch(r"[A-Z]{2}|T1", code) and code != "XX":
        return code
    return ""


def format_location(
    *,
    is_local: bool,
    country_code: str = "",
    region: str = "",
    city: str = "",
) -> str:
    if is_local:
        return "本地 / 局域网"
    code = sanitize_country_code(country_code)
    clean_region = sanitize_header_text(region, max_length=64)
    clean_city = sanitize_header_text(city, max_length=64)
    parts: list[str] = []
    if code:
        parts.append(COUNTRY_NAMES_ZH.get(code, code))
    if clean_region and clean_region not in parts:
        parts.append(clean_region)
    if clean_city and clean_city not in parts and clean_city.lower() != clean_region.lower():
        parts.append(clean_city)
    if parts:
        return " · ".join(parts)
    return "公网位置未上报"


def _unquote_ch(value: str | None) -> str:
    text = sanitize_header_text(value, max_length=128)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text.strip()


def _parse_sec_ch_ua_browser(sec_ch_ua: str) -> str:
    if not sec_ch_ua:
        return ""
    pairs = re.findall(r'"([^"]+)";\s*v="([^"]+)"', sec_ch_ua)
    brand_map = [
        ("Microsoft Edge", "Edge"),
        ("Google Chrome", "Chrome"),
        ("Opera", "Opera"),
        ("Brave", "Brave"),
        ("Vivaldi", "Vivaldi"),
        ("Arc", "Arc"),
        ("Chromium", "Chromium"),
    ]
    for token, label in brand_map:
        for brand, version in pairs:
            if brand.lower() == token.lower():
                major = version.split(".", 1)[0]
                return f"{label} {major}" if major.isdigit() else label
    return ""


def _parse_browser(ua: str, sec_ch_ua: str = "") -> str:
    if not ua and sec_ch_ua:
        return _parse_sec_ch_ua_browser(sec_ch_ua) or "未知浏览器"
    if not ua:
        return "未知浏览器"

    patterns = (
        (r"MicroMessenger/" + _VERSION_TOKEN, "微信内置浏览器"),
        (r"DingTalk/" + _VERSION_TOKEN, "钉钉内置浏览器"),
        (r"Lark/" + _VERSION_TOKEN, "飞书内置浏览器"),
        (r"Edg(?:A|iOS)?/" + _VERSION_TOKEN, "Edge"),
        (r"OPR/" + _VERSION_TOKEN, "Opera"),
        (r"SamsungBrowser/" + _VERSION_TOKEN, "Samsung Internet"),
        (r"HuaweiBrowser/" + _VERSION_TOKEN, "华为浏览器"),
        (r"QQBrowser/" + _VERSION_TOKEN, "QQ 浏览器"),
        (r"UCBrowser/" + _VERSION_TOKEN, "UC 浏览器"),
        (r"Quark/" + _VERSION_TOKEN, "夸克浏览器"),
        (r"Vivaldi/" + _VERSION_TOKEN, "Vivaldi"),
        (r"Firefox/" + _VERSION_TOKEN, "Firefox"),
        (r"FxiOS/" + _VERSION_TOKEN, "Firefox"),
        (r"CriOS/" + _VERSION_TOKEN, "Chrome"),
        (r"Chrome/" + _VERSION_TOKEN, "Chrome"),
        (r"Chromium/" + _VERSION_TOKEN, "Chromium"),
        (r"Version/" + _VERSION_TOKEN + r".*Safari/", "Safari"),
    )
    for pattern, label in patterns:
        match = re.search(pattern, ua)
        if match:
            ver = match.group(1).split(".", 1)[0]
            if label == "Chrome" and sec_ch_ua:
                hint = _parse_sec_ch_ua_browser(sec_ch_ua)
                if hint:
                    return hint
            return f"{label} {ver}" if ver else label

    if "Safari/" in ua and "Chrome/" not in ua and "Chromium/" not in ua:
        return "Safari"
    ch_hint = _parse_sec_ch_ua_browser(sec_ch_ua)
    if ch_hint:
        return ch_hint
    for tool_pat, label in (
        (r"curl/" + _VERSION_TOKEN, "curl"),
        (r"python-httpx/" + _VERSION_TOKEN, "Python httpx"),
        (r"python-requests/" + _VERSION_TOKEN, "Python requests"),
        (r"PostmanRuntime", "Postman"),
    ):
        match = re.search(tool_pat, ua, re.I)
        if match:
            return label
    return "其他客户端"


def _parse_os_and_device(
    ua: str,
    *,
    ch_platform: str = "",
    ch_mobile: str = "",
    ch_model: str = "",
) -> tuple[DeviceType, str, str]:
    """Return (device_type, os_label, hardware_hint)."""
    platform = _unquote_ch(ch_platform)
    model = _unquote_ch(ch_model)
    is_mobile_hint = ch_mobile.strip() == "?1"

    if re.search(r"iPad", ua) or (re.search(r"Macintosh", ua) and "Mobile" in ua):
        m = re.search(r"OS\s+([0-9]+_[0-9]+)", ua)
        ver = m.group(1).replace("_", ".") if m else ""
        return "tablet", f"iPadOS {ver}".strip(), "iPad"

    if re.search(r"iPhone", ua):
        m = re.search(r"iPhone OS\s+([0-9]+_[0-9]+)", ua)
        ver = m.group(1).replace("_", ".") if m else ""
        return "mobile", f"iOS {ver}".strip(), "iPhone"

    if re.search(r"HarmonyOS", ua, re.I):
        m = re.search(r"HarmonyOS\s*([0-9]+(?:\.[0-9]+)?)", ua, re.I)
        ver = m.group(1) if m else ""
        dtype: DeviceType = "tablet" if re.search(r"Tablet|Pad", ua, re.I) else "mobile"
        return dtype, f"HarmonyOS {ver}".strip(), model

    if re.search(r"Android", ua, re.I) or platform.lower() == "android":
        m = re.search(r"Android\s+([0-9]+(?:\.[0-9]+)?)", ua, re.I)
        ver = m.group(1) if m else ""
        is_tablet = ("Mobile" not in ua and "Android" in ua) or bool(
            re.search(r"Tablet|Pad|SM-T|SM-X", ua, re.I)
        )
        dtype = "tablet" if is_tablet else "mobile"
        return dtype, f"Android {ver}".strip(), model

    if re.search(r"Windows NT", ua) or platform.lower() == "windows":
        m = re.search(r"Windows NT\s+([0-9]+\.[0-9]+)", ua)
        nt = m.group(1) if m else ""
        win_label = {
            "10.0": "Windows 10/11",
            "6.3": "Windows 8.1",
            "6.2": "Windows 8",
            "6.1": "Windows 7",
        }.get(nt, "Windows")
        return "desktop", win_label, ""

    if re.search(r"Mac OS X|Macintosh", ua) or platform.lower() == "macos":
        m = re.search(r"Mac OS X\s+([0-9]+_[0-9]+)", ua)
        ver = m.group(1).replace("_", ".") if m else ""
        return "desktop", f"macOS {ver}".strip(), "Mac"

    if re.search(r"CrOS", ua) or platform.lower() in {"chrome os", "chromeos"}:
        return "desktop", "ChromeOS", "Chromebook"

    if re.search(r"Linux|X11|Ubuntu|Fedora|Debian", ua) or platform.lower() == "linux":
        if is_mobile_hint:
            return "mobile", "Linux Mobile", model
        return "desktop", "Linux", ""

    if platform:
        dtype = "mobile" if is_mobile_hint else "desktop"
        return dtype, platform, model

    if is_mobile_hint or re.search(r"Mobile", ua):
        return "mobile", "移动系统", model
    return "unknown", "未知系统", ""


def extract_client_context(request, raw_ip: str) -> ClientContext:
    headers = request.headers
    raw_ua = sanitize_header_text(headers.get("user-agent"), max_length=300)
    sec_ch_ua = sanitize_header_text(headers.get("sec-ch-ua"), max_length=200)
    ch_platform = sanitize_header_text(headers.get("sec-ch-ua-platform"), max_length=64)
    ch_mobile = sanitize_header_text(headers.get("sec-ch-ua-mobile"), max_length=8)
    ch_model = sanitize_header_text(headers.get("sec-ch-ua-model"), max_length=64)

    ip_text, is_local, prefix = normalize_ip_display(raw_ip)
    country = sanitize_country_code(getattr(request.state, "trusted_client_country", ""))
    region = sanitize_header_text(
        getattr(request.state, "trusted_client_region", ""), max_length=64
    )
    city = sanitize_header_text(getattr(request.state, "trusted_client_city", ""), max_length=64)
    location = format_location(is_local=is_local, country_code=country, region=region, city=city)

    device_type, os_label, hardware_hint = _parse_os_and_device(
        raw_ua,
        ch_platform=ch_platform,
        ch_mobile=ch_mobile,
        ch_model=ch_model,
    )
    browser = _parse_browser(raw_ua, sec_ch_ua)

    if hardware_hint and hardware_hint.lower() not in os_label.lower():
        device_subject = f"{hardware_hint} ({os_label})"
    else:
        device_subject = os_label

    if os_label == "未知系统" and browser != "未知浏览器":
        device_name = browser
    else:
        device_name = f"{device_subject} · {browser}"

    return ClientContext(
        ip=ip_text,
        is_local=is_local,
        network_prefix=prefix,
        country_code=country,
        location=location,
        device_type=device_type,
        device_name=device_name[:120],
        os=os_label[:64],
        browser=browser[:64],
        user_agent=raw_ua,
    )


def device_fingerprint(os_name: str, browser_name: str, device_type: str) -> str:
    """Coarse device+browser family key (ignores minor version bumps on auto-updates)."""
    os_family = (os_name or "").strip().split(" ", 1)[0].lower()
    browser_family = (browser_name or "").strip().split(" ", 1)[0].lower()
    return f"{(device_type or 'unknown').lower()}|{os_family}|{browser_family}"


def detect_login_anomalies(
    *,
    current: ClientContext,
    current_source_hash: str,
    recent_sessions: list[dict],
) -> list[str]:
    """Compare current login against the user's recent 30-day sessions.

    Returns a list of anomaly reason codes (empty if first login or matches known history).
    Never forces logout; used only for auditing, UI badges, and security notification emails.
    """
    if not recent_sessions:
        return []

    reasons: list[str] = []

    known_countries = {
        (row.get("country_code") or "").strip().upper()
        for row in recent_sessions
        if (row.get("country_code") or "").strip()
    }
    known_locations = {
        (row.get("login_location") or "").strip()
        for row in recent_sessions
        if (row.get("login_location") or "").strip()
        and (row.get("login_location") or "").strip() not in {"本地 / 局域网", "公网位置未上报"}
    } | {
        (row.get("last_location") or "").strip()
        for row in recent_sessions
        if (row.get("last_location") or "").strip()
        and (row.get("last_location") or "").strip() not in {"本地 / 局域网", "公网位置未上报"}
    }
    known_sources = {
        (row.get("source_hash") or "").strip()
        for row in recent_sessions
        if (row.get("source_hash") or "").strip()
    }
    known_prefixes = {
        (row.get("network_prefix") or "").strip()
        for row in recent_sessions
        if (row.get("network_prefix") or "").strip()
    }

    location_changed = False
    if current.country_code and known_countries and current.country_code not in known_countries:
        location_changed = True
    elif (
        current.location
        and current.location not in {"本地 / 局域网", "公网位置未上报"}
        and known_locations
        and current.location not in known_locations
    ):
        location_changed = True

    if location_changed:
        reasons.append("different_location")
    else:
        network_known = (current_source_hash and current_source_hash in known_sources) or (
            current.network_prefix and current.network_prefix in known_prefixes
        )
        if not network_known and (known_sources or known_prefixes):
            reasons.append("new_network")

    known_devices = {
        device_fingerprint(row.get("os", ""), row.get("browser", ""), row.get("device_type", ""))
        for row in recent_sessions
        if (row.get("device_name") or "").strip()
        or (row.get("os") or "").strip()
        or (row.get("browser") or "").strip()
    }
    current_fp = device_fingerprint(current.os, current.browser, current.device_type)
    if known_devices and current_fp not in known_devices:
        reasons.append("new_device")

    return reasons


def format_anomaly_labels(reasons: list[str]) -> list[str]:
    return [ANOMALY_LABELS_ZH.get(code, code) for code in reasons if code]


def parse_anomaly_reasons(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def build_anomalous_login_email(
    *,
    current: ClientContext,
    reasons: list[str],
    mfa_used: bool,
    when_beijing: str,
) -> str:
    reason_text = "、".join(format_anomaly_labels(reasons)) or "异常登录"
    device_type_label = {
        "desktop": "桌面设备",
        "mobile": "移动设备",
        "tablet": "平板设备",
        "unknown": "未知设备类型",
    }.get(current.device_type, "未知设备类型")
    ip_display = current.ip or "未上报"
    mfa_display = "已通过双因素验证" if mfa_used else "未启用双因素验证"
    lines = [
        f"检测到您的 Siderfolio 账号发生了{reason_text}，以下为本次登录详情：",
        "",
        f"• 异常原因：{reason_text}",
        f"• 登录时间：{when_beijing}（北京时间）",
        f"• 登录设备：{current.device_name}（{device_type_label}）",
        f"• 操作系统：{current.os}",
        f"• 浏览器：{current.browser}",
        f"• 网络地址：{ip_display}",
        f"• 大致位置：{current.location}",
        f"• 验证方式：{mfa_display}",
        "",
        "为保障多设备正常使用，本次登录不会强制退出您当前或其他设备的登录状态。",
        (
            "如果这是您本人操作，无需处理；如非本人操作，请立即登录 Siderfolio "
            "前往「设置 → 账户安全与登录 → 已登录设备」强制退出该设备，并尽快修改登录密码。"
        ),
    ]
    return "\n".join(lines)
