"""真实 SIMBAD 名称查询；不使用硬编码天体数据或模型生成的字段。"""

import math
from datetime import UTC, datetime
from urllib.parse import urlencode

import numpy as np
from astroquery.simbad import Simbad
from pyvo.dal.exceptions import DALFormatError, DALQueryError, DALServiceError
from requests import Session
from requests.exceptions import ConnectionError, HTTPError, Timeout

from astroagent.schemas import ErrorInfo, ObjectData, ObjectQuery, QueryResult, Source

SIMBAD_SERVERS = ("simbad.cds.unistra.fr", "simbad.cfa.harvard.edu")


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


def _causes(exc):
    seen, pending = set(), [exc]
    while pending:
        item = pending.pop()
        if not isinstance(item, Exception) or id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        pending.extend((item.__cause__, item.__context__, getattr(item, "cause", None)))


def _is_timeout(exc: Exception) -> bool:
    # PyVO may wrap a requests timeout without setting Python's exception cause.
    return any(
        isinstance(item, (Timeout, TimeoutError))
        or "timed out" in str(item).lower()
        or "timeout" in str(item).lower()
        for item in _causes(exc)
    )


def _unreachable(exc):
    if _is_timeout(exc):
        return True
    causes = list(_causes(exc))
    for item in causes:
        if isinstance(item, ConnectionError):
            return True
        code = item.code if isinstance(item, DALServiceError) else None
        if isinstance(item, HTTPError) and item.response is not None:
            code = item.response.status_code
        if isinstance(code, int) and (code in (408, 429) or 500 <= code <= 599):
            return True
    # Metadata discovery may discard its connection error. Do not turn an
    # explicitly wrapped query/format error into a transport retry.
    return any(
        isinstance(item, DALServiceError) and item.code in (None, 0) for item in causes
    ) and not any(isinstance(item, (ValueError, DALFormatError, DALQueryError)) for item in causes)


class SimbadService:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout

    def query(self, object_name: str) -> QueryResult:
        name = ObjectQuery(object_name=object_name).object_name
        for index, server in enumerate(SIMBAD_SERVERS):
            source = Source(
                url=f"https://{server}/simbad/sim-id?"
                + urlencode({"Ident": name, "output.format": "HTML"}),
                retrieved_at=datetime.now(UTC),
            )
            try:
                return self._query(name, server, source)
            except Exception as exc:
                if index == 0 and _unreachable(exc):
                    continue
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

    def _query(self, name, server, source):
        # Each endpoint gets an independent client and bounded session. A successful
        # no-match or a malformed response is never retried at another mirror.
        with BoundedSession(self.timeout) as session:
            client = Simbad()
            client._session.close()
            client._session = session
            # astroquery 0.4.x lists the legacy simbad.harvard.edu alias only.
            # Its TAP getter uses this per-instance host; avoid mutating conf.server
            # or conf.servers_list, which are shared by concurrent queries.
            client._server = server
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
