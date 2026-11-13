"""有界的固定 Gaia DR3 TAP 查询；外部 XML 先验证，再以 Astropy 解析。"""

import math
import struct
from datetime import UTC, datetime
from io import BytesIO

import numpy as np
import requests
from astropy import units as u
from astropy.io.votable import parse
from astropy.io.votable.exceptions import VOWarning
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from astroagent.analysis import analyze_sources
from astroagent.schemas import ErrorInfo, GaiaQuery, GaiaQueryResult, GaiaSourceData, Source

GAIA_ENDPOINT = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_ARCHIVE = "https://gea.esac.esa.int/archive/"
GAIA_TABLE = "gaiadr3.gaia_source"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
GAIA_UNITS = {
    "source_id": "1",
    "ra": "deg",
    "dec": "deg",
    "ref_epoch": "yr",
    "ra_error": "mas",
    "dec_error": "mas",
    "parallax": "mas",
    "parallax_error": "mas",
    "pmra": "mas/yr",
    "pmra_error": "mas/yr",
    "pmdec": "mas/yr",
    "pmdec_error": "mas/yr",
    "phot_g_mean_mag": "mag",
    "phot_bp_mean_mag": "mag",
    "phot_rp_mean_mag": "mag",
    "bp_rp": "mag",
    "radial_velocity": "km/s",
    "radial_velocity_error": "km/s",
    "ruwe": "1",
    "astrometric_params_solved": "1",
    "duplicated_source": "1",
    "separation_arcsec": "arcsec",
}
GAIA_COLUMNS = tuple(name for name in GAIA_UNITS if name != "separation_arcsec")
INTEGER_TYPES = {"unsignedByte", "short", "int", "long"}
NUMBER_TYPES = INTEGER_TYPES | {"float", "double"}
POSITION_WARNING = (
    "圆锥结果仅为位置候选源；最近或唯一一行也不是确认匹配。输入历元未提供或未校正，"
    "未进行自行传播；ICRS 相同不代表历元相同，高自行源或拥挤视场可能漏配。"
)
SAMPLE_WARNING = (
    "统计仅描述本次实际交付行，不代表视场总体或星团成员；pmra 已含 cos(dec)。"
    "质量筛选会改变选择函数，阈值不能保证无污染；未额外计数，不能给出被排除数量。"
)
DISTANCE_WARNING = (
    "距离为程序计算的高信噪比视差倒数近似（SNR≥10），不是 Gaia 直接测量的距离。"
    "误差仅为一阶随机误差；未校正视差零点、系统误差、消光或选择偏差，未做贝叶斯估计。"
)


class TapQueryError(ValueError):
    pass


class ResponseTooLarge(ValueError):
    pass


def build_adql(query: GaiaQuery) -> tuple[str, int]:
    columns = ", ".join(GAIA_COLUMNS)
    if query.mode == "source_id":
        return f"SELECT TOP 2 {columns} FROM {GAIA_TABLE} WHERE source_id = {query.source_id}", 2
    ra, dec, radius = repr(query.ra_deg), repr(query.dec_deg), repr(query.radius_arcmin / 60)
    point = f"POINT('ICRS', {ra}, {dec})"
    adql = (
        f"SELECT TOP {query.limit + 1} {columns}, "
        f"DISTANCE(POINT('ICRS', ra, dec), {point}) AS separation_deg "
        f"FROM {GAIA_TABLE} WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {ra}, {dec}, {radius}))"
    )
    if query.ruwe_max is not None:
        adql += f" AND ruwe <= {query.ruwe_max!r}"
    if query.parallax_snr_min is not None:
        adql += (
            " AND parallax > 0 AND parallax_error > 0"
            f" AND parallax / parallax_error >= {query.parallax_snr_min!r}"
        )
    return adql + " ORDER BY separation_deg ASC, source_id ASC", query.limit + 1


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _validate_xml(body: bytes):
    # Reject DTDs/entities even if unused. Astropy only receives inspected in-memory XML.
    root = SafeET.fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if _tag(root) != "VOTABLE":
        raise ValueError("Not a VOTable")
    for element in root.iter():
        if _tag(element) == "FITS" or any(
            key.rsplit("}", 1)[-1] == "href" for key in element.attrib
        ):
            raise ValueError("External VOTable references are forbidden")
    resources = [e for e in root.iter() if _tag(e) == "RESOURCE" and e.get("type") == "results"]
    if len(resources) != 1:
        raise ValueError("Missing or ambiguous results resource")
    resource = resources[0]
    statuses = [
        e.get("value")
        for e in resource.iter()
        if _tag(e) == "INFO" and e.get("name") == "QUERY_STATUS"
    ]
    if "ERROR" in statuses:
        raise TapQueryError("TAP query failed")
    if not statuses or statuses[0] != "OK" or any(s not in {"OK", "OVERFLOW"} for s in statuses):
        raise ValueError("Invalid TAP status")
    tables = [e for e in root.iter() if _tag(e) == "TABLE"]
    if len(tables) != 1 or not any(e is tables[0] for e in resource.iter()):
        raise ValueError("Missing or ambiguous result table")
    if len([e for e in tables[0] if _tag(e) == "DATA"]) != 1:
        raise ValueError("Missing table data")
    return tables[0], "OVERFLOW" in statuses


def _validate_fields(table_xml, query: GaiaQuery):
    fields = {}
    for field in table_xml:
        if _tag(field) != "FIELD":
            continue
        name = field.get("name")
        if name in fields:
            raise ValueError("Duplicate field name")
        fields[name] = field
    required = set(GAIA_COLUMNS) | ({"separation_deg"} if query.mode == "cone" else set())
    if not required <= fields.keys():
        raise ValueError("Missing result columns")
    for name in required:
        field = fields[name]
        datatype = field.get("datatype")
        if name == "source_id":
            allowed = INTEGER_TYPES | {"char", "unicodeChar"}
        elif name == "astrometric_params_solved":
            allowed = INTEGER_TYPES
        elif name == "duplicated_source":
            allowed = {"boolean"}
        else:
            allowed = NUMBER_TYPES
        if datatype not in allowed or (name != "source_id" and field.get("arraysize", "1") != "1"):
            raise ValueError("Invalid column type")
        unit = field.get("unit", "")
        if unit == "---":  # CDS dimensionless spelling used by Astropy's VOTable writer.
            unit = ""
        expected = "deg" if name == "separation_deg" else GAIA_UNITS[name]
        # ESA leaves computed ADQL DISTANCE aliases without a FIELD unit.
        # Its fixed POINT geometry returns degrees; catalogue columns still require units.
        if name == "separation_deg" and not unit:
            continue
        if u.Unit(unit) != u.Unit(expected):
            raise ValueError("Unexpected column unit")


def _validate_layout(table_xml, maxrec: int):
    # VOTable allocation hints must not turn a small response into a huge array.
    nrows = table_xml.get("nrows")
    if nrows is not None and (not nrows.isascii() or not nrows.isdigit() or int(nrows) > maxrec):
        raise ValueError("Invalid declared row count")
    fields = [e for e in table_xml if _tag(e) == "FIELD"]
    if len(fields) > 64:
        raise ValueError("Too many fields")
    tabledata = [e for e in table_xml.iter() if _tag(e) == "TABLEDATA"]
    if tabledata and len(tabledata[0]) > maxrec:
        raise ValueError("Too many table rows")
    for field in fields:
        size = field.get("arraysize", "1")
        if field.get("datatype") in {"char", "unicodeChar"}:
            if size == "*" and tabledata:
                continue  # XML text is already byte-bounded; no binary length prefixes.
            if not size.isascii() or not size.isdigit() or not 1 <= int(size) <= 4096:
                raise ValueError("Unbounded string array")
        elif size != "1":
            raise ValueError("Non-scalar field")


def _value(row, name):
    value = row[name]
    if np.ma.is_masked(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def _source(row, query: GaiaQuery) -> GaiaSourceData:
    values = {}
    for name in GAIA_COLUMNS:
        value = _value(row, name)
        if name == "source_id":
            if type(value) is int:
                value = str(value)
            elif not isinstance(value, str):
                raise ValueError("Source ID must never pass through float")
        elif name == "astrometric_params_solved":
            if value is not None and type(value) is not int:
                raise ValueError("Expected integer")
        elif name == "duplicated_source":
            if value is not None and type(value) is not bool:
                raise ValueError("Expected boolean")
        elif value is not None:
            if type(value) not in (float, int):
                raise ValueError("Expected scalar number")
            value = float(value)
            if not math.isfinite(value):
                value = None
        values[name] = value
    if query.mode == "cone":
        separation = _value(row, "separation_deg")
        if type(separation) not in (int, float) or not math.isfinite(separation):
            raise ValueError("Invalid angular separation")
        values["separation_arcsec"] = separation * 3600
    return GaiaSourceData(**values)


def parse_result(body: bytes, query: GaiaQuery, maxrec: int):
    table_xml, overflow = _validate_xml(body)
    _validate_fields(table_xml, query)
    _validate_layout(table_xml, maxrec)
    parsed = parse(BytesIO(body), verify="exception").get_first_table()
    # Work directly on Astropy's masked records; no extra Table copy is needed.
    table = parsed.array
    if len(table) > maxrec or (query.mode == "source_id" and len(table) > 1):
        raise ValueError("Unexpected row count")
    sources = [
        _source({field.name: row[field.ID] for field in parsed.fields}, query) for row in table
    ]
    if len({s.source_id for s in sources}) != len(sources):
        raise ValueError("Duplicate source IDs")
    if query.mode == "source_id" and sources and sources[0].source_id != query.source_id:
        raise ValueError("Wrong source ID")
    if overflow and not sources:
        raise ValueError("Overflow without data is not a complete empty result")
    if query.mode == "cone":
        order = [(s.separation_arcsec, int(s.source_id)) for s in sources]
        if order != sorted(order):
            raise ValueError("Unsorted cone result")
        for source in sources:
            if source.separation_arcsec > query.radius_arcmin * 60 + 1e-6:
                raise ValueError("Source outside cone")
            if query.ruwe_max is not None and (source.ruwe is None or source.ruwe > query.ruwe_max):
                raise ValueError("RUWE filter violated")
            if query.parallax_snr_min is not None and (
                source.parallax is None
                or source.parallax <= 0
                or source.parallax_error is None
                or source.parallax_error <= 0
                or source.parallax / source.parallax_error < query.parallax_snr_min
            ):
                raise ValueError("Parallax filter violated")
    has_more = overflow or (query.mode == "cone" and len(sources) > query.limit)
    return sources[: query.limit] if query.mode == "cone" else sources, has_more, overflow


class GaiaService:
    def __init__(self, timeout: float = 45, *, session=None):
        self.timeout = timeout
        self._session = session  # Injected only by offline tests; construction never accesses TAP.

    def query(self, arguments: GaiaQuery) -> GaiaQueryResult:
        adql, maxrec = build_adql(arguments)
        warnings = [SAMPLE_WARNING]
        if arguments.mode == "cone":
            warnings.append(POSITION_WARNING)
        if arguments.estimate_distance:
            warnings.append(DISTANCE_WARNING)
        base = dict(
            query=arguments.effective_parameters(),
            adql=adql,
            maxrec=maxrec,
            source=Source(name="Gaia", url=GAIA_ARCHIVE, retrieved_at=datetime.now(UTC)),
            units=GAIA_UNITS,
            warnings=warnings,
        )

        def failure(code, message, retryable=False, *, status="error"):
            return GaiaQueryResult(
                **base,
                status=status,
                error=ErrorInfo(code=code, message=message, retryable=retryable),
                **(
                    {"has_more": False, "truncated": False, "archive_overflow": False}
                    if status == "not_found"
                    else {}
                ),
            )

        owned = self._session is None
        session = self._session if self._session is not None else requests.Session()
        try:
            response = session.post(
                GAIA_ENDPOINT,
                data={
                    "REQUEST": "doQuery",
                    "LANG": "ADQL",
                    "FORMAT": "votable",
                    "QUERY": adql,
                    "MAXREC": maxrec,
                },
                timeout=(min(10, self.timeout), self.timeout),
                allow_redirects=False,
                stream=True,
            )
            try:
                status = response.status_code
                if status in (401, 403):
                    return failure("gaia_access_denied", "Gaia 拒绝访问此查询。")
                if status == 429:
                    return failure("gaia_rate_limited", "Gaia 请求受限，请稍后重试。", True)
                if status == 400:
                    return failure("gaia_query_failed", "Gaia 拒绝了固定查询，请检查服务兼容性。")
                if 500 <= status <= 599:
                    return failure("gaia_unavailable", "Gaia 服务暂时不可用。", True)
                if status != 200:
                    return failure("gaia_unexpected_response", "Gaia 返回了非预期 HTTP 响应。")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ResponseTooLarge("Response exceeds decompressed size limit")
            finally:
                response.close()
            sources, has_more, overflow = parse_result(bytes(body), arguments, maxrec)
            if not sources:
                return failure(
                    "gaia_not_found", "本次查询条件下无匹配的 Gaia DR3 源。", status="not_found"
                )
            if has_more:
                warnings.append("结果已截断，统计仅限交付行；未执行总数查询或自动翻页。")
            if overflow:
                warnings.append("Gaia Archive 报告 OVERFLOW：服务器截断了结果。")
            return GaiaQueryResult(
                **base,
                status="success",
                returned_count=len(sources),
                data=sources,
                has_more=has_more,
                truncated=has_more,
                archive_overflow=overflow,
                analysis=analyze_sources(sources, arguments, truncated=has_more),
            )
        except ResponseTooLarge:
            return failure("gaia_response_too_large", "Gaia 响应超过 2 MiB 上限，已终止读取。")
        except TapQueryError:
            return failure("gaia_query_failed", "Gaia TAP 报告查询失败，请检查固定模板。")
        except requests.Timeout:
            return failure("gaia_timeout", "Gaia 查询超时，本次未取得数据；请稍后手动重试。", True)
        except requests.ConnectionError as exc:
            # requests wraps urllib3 ReadTimeoutError in ConnectionError during iter_content.
            from urllib3.exceptions import ReadTimeoutError

            if exc.args and isinstance(exc.args[0], ReadTimeoutError):
                return failure(
                    "gaia_timeout", "Gaia 读取超时，本次未取得完整数据；请稍后手动重试。", True
                )
            return failure("gaia_unavailable", "无法连接 Gaia 服务，请稍后重试。", True)
        except requests.RequestException:
            return failure("gaia_unavailable", "无法连接 Gaia 服务，请稍后重试。", True)
        except (
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            OSError,
            SafeET.ParseError,
            DefusedXmlException,
            VOWarning,
            IndexError,
            EOFError,
            struct.error,
        ):
            return failure("gaia_unexpected_response", "Gaia 返回的数据、字段或表结构无效。")
        finally:
            if owned:
                session.close()
