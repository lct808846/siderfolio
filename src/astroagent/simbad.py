"""真实 SIMBAD 名称查询；不使用硬编码天体数据或模型生成的字段。"""

import math
from datetime import UTC, datetime
from urllib.parse import urlencode

import numpy as np
from astroquery.simbad import Simbad
from requests import Session
from requests.exceptions import Timeout

from astroagent.schemas import ErrorInfo, ObjectData, ObjectQuery, QueryResult, Source


class BoundedSession(Session):
    """同时限制 PyVO 元数据请求与 TAP 请求的连接、读取等待。"""

    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def request(self, method, url, **kwargs):
        kwargs["timeout"] = self.timeout
        return super().request(method, url, **kwargs)


def _value(row, name: str):
    if name not in row.colnames:
        return None
    value = row[name]
    if np.ma.is_masked(value):
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value.strip() or None
    value = float(value)
    return value if math.isfinite(value) else None


def _is_timeout(exc: Exception) -> bool:
    # PyVO 会把 requests 的超时包装成 DALServiceError。
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (Timeout, TimeoutError)):
            return True
        if "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class SimbadService:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout

    def query(self, object_name: str) -> QueryResult:
        name = ObjectQuery(object_name=object_name).object_name
        source = Source(
            url="https://simbad.cds.unistra.fr/simbad/sim-id?"
            + urlencode({"Ident": name, "output.format": "HTML"}),
            retrieved_at=datetime.now(UTC),
        )
        try:
            # 每次查询独立实例和 session，避免并发请求修改共享查询配置。
            with BoundedSession(self.timeout) as session:
                # Passing timeout to the constructor eagerly fetches TAP capabilities
                # before our bounded session is installed. Set it only after injection.
                client = Simbad()
                client._session.close()
                client._session = session
                client.timeout = self.timeout
                client.ROW_LIMIT = 1
                client.add_votable_fields("otype", "sp_type")
                table = client.query_object(name, wildcard=False)
            if table is None or len(table) == 0:
                return QueryResult(
                    object_name=name,
                    status="not_found",
                    source=source,
                    error=ErrorInfo(code="object_not_found", message="SIMBAD 未找到该天体名称。"),
                )
            row = table[0]
            main_id = _value(row, "main_id")
            if not main_id:
                raise ValueError("Missing main_id")
            data = ObjectData(
                main_id=main_id,
                ra_deg=_value(row, "ra"),
                dec_deg=_value(row, "dec"),
                object_type=_value(row, "otype"),
                spectral_type=_value(row, "sp_type"),
                coordinate_bibcode=_value(row, "coo_bibcode"),
            )
            return QueryResult(object_name=name, status="success", source=source, data=data)
        except Exception as exc:
            timed_out = _is_timeout(exc)
            return QueryResult(
                object_name=name,
                status="error",
                source=source,
                error=ErrorInfo(
                    code="simbad_timeout" if timed_out else "simbad_unavailable",
                    message="SIMBAD 查询超时，请稍后重试。"
                    if timed_out
                    else "SIMBAD 查询失败，暂时无法获取真实数据。",
                    retryable=True,
                ),
            )
