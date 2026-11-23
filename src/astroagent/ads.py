"""固定 ADS Search API 的单页查询、严格转换与安全错误映射。"""

from datetime import UTC, datetime
from urllib.parse import quote, urlencode

import requests
from pydantic import SecretStr

from astroagent.schemas import ErrorInfo, LiteratureQuery, LiteratureSearchResult, PaperData, Source
from astroagent.usage import reserve_request

ADS_ENDPOINT = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_FIELDS = "bibcode,title,author,year,pub,doi,abstract,citation_count"
ADS_FILTER = "database:astronomy"
ADS_SORTS = {"date_desc": "date desc", "citation_count_desc": "citation_count desc"}


def search_url(arguments: LiteratureQuery) -> str:
    # ADS UI uses query parameters in its /search/ route, rather than /search?q=.
    params = {
        "q": arguments.query,
        "fq": ADS_FILTER,
        "sort": ADS_SORTS.get(arguments.sort, "score desc"),
        "start": arguments.start,
        "p_": 0,
    }
    return "https://ui.adsabs.harvard.edu/search/" + urlencode(params, quote_via=quote)


def _text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected text")
    return value if value.strip() else None


def _strings(value):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Expected text array")
    return value


def _paper(doc: dict, retrieved_at: datetime) -> PaperData:
    if not isinstance(doc, dict):
        raise ValueError("Expected document")
    bibcode = _text(doc.get("bibcode"))
    if bibcode is None:
        raise ValueError("Missing bibcode")
    titles = _strings(doc.get("title"))
    year = doc.get("year")
    if year is not None:
        if isinstance(year, str) and year.isascii() and year.isdigit():
            year = int(year)
        if type(year) is not int or not 1 <= year <= 9999:
            raise ValueError("Invalid year")
    citations = doc.get("citation_count")
    if citations is not None and (type(citations) is not int or citations < 0):
        raise ValueError("Invalid citation count")
    return PaperData(
        bibcode=bibcode,
        title=next((title for title in titles if title.strip()), None),
        authors=_strings(doc.get("author")),
        year=year,
        publication=_text(doc.get("pub")),
        doi=_strings(doc.get("doi")),
        abstract=_text(doc.get("abstract")),
        citation_count=citations,
        source=Source(
            name="ADS",
            url=f"https://ui.adsabs.harvard.edu/abs/{quote(bibcode, safe='')}/abstract",
            retrieved_at=retrieved_at,
        ),
    )


class AdsService:
    def __init__(self, token: SecretStr | str = "", timeout: float = 20, *, session=None):
        self._token = token if isinstance(token, SecretStr) else SecretStr(token)
        self.timeout = timeout
        # A fresh requests Session has zero retries. Injected sessions are for offline tests.
        self._session = session

    def search(self, arguments: LiteratureQuery) -> LiteratureSearchResult:
        source = Source(name="ADS", url=search_url(arguments), retrieved_at=datetime.now(UTC))
        base = {**arguments.model_dump(), "source": source}

        def failure(code, message, retryable=False):
            return LiteratureSearchResult(
                **base,
                status="error",
                error=ErrorInfo(code=code, message=message, retryable=retryable),
            )

        token = self._token.get_secret_value().strip()
        if not token:
            return failure("ads_not_configured", "请在服务端配置 ADS_API_TOKEN 后检索文献。")
        reserve_request("astronomy_queries")
        params = {
            "q": arguments.query,
            "fl": ADS_FIELDS,
            "fq": ADS_FILTER,
            "rows": arguments.rows,
            "start": arguments.start,
        }
        if arguments.sort != "relevance":
            params["sort"] = ADS_SORTS[arguments.sort]
        owned_session = self._session is None
        session = self._session or requests.Session()
        try:
            response = session.get(
                ADS_ENDPOINT,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=(self.timeout, self.timeout),
                allow_redirects=False,
            )
            try:
                status = response.status_code
                if status in (401, 403):
                    return failure("ads_authentication_failed", "ADS 认证失败，请检查凭证或权限。")
                if status == 429:
                    return failure("ads_rate_limited", "ADS 请求受限，请稍后重试。", True)
                if status == 400:
                    return failure("ads_invalid_query", "ADS 拒绝了检索式，请修改检索条件。")
                if 500 <= status <= 599:
                    return failure("ads_unavailable", "ADS 服务暂时不可用。", True)
                if status != 200:
                    return failure("ads_unexpected_response", "ADS 返回了非预期的 HTTP 响应。")
                payload = response.json()
            finally:
                response.close()
            if not isinstance(payload, dict):
                raise ValueError("Invalid response envelope")
            if "error" in payload:
                raise ValueError("Error in success response")
            header = payload.get("responseHeader", {})
            if not isinstance(header, dict) or header.get("status", 0) != 0:
                raise ValueError("Invalid response header")
            if header.get("partialResults", False) not in (False, None):
                raise ValueError("Partial upstream response")
            page = payload["response"]
            total, start, docs = page["numFound"], page["start"], page["docs"]
            if (
                type(total) is not int
                or total < 0
                or type(start) is not int
                or start != arguments.start
                or not isinstance(docs, list)
                or len(docs) > arguments.rows
                or (docs and start + len(docs) > total)
                or (not docs and start < total)
                or len(docs) != min(arguments.rows, max(total - start, 0))
            ):
                raise ValueError("Inconsistent pagination")
            papers = {}
            for doc in docs:
                paper = _paper(doc, source.retrieved_at)
                papers.setdefault(paper.bibcode, paper)
            return LiteratureSearchResult(
                **base,
                status="success" if papers else "not_found",
                total_found=total,
                returned_count=len(papers),
                has_more=start + len(docs) < total,
                papers=list(papers.values()),
            )
        except requests.exceptions.JSONDecodeError:
            return failure("ads_invalid_response", "ADS 返回的数据不是有效 JSON。")
        except requests.Timeout:
            return failure("ads_timeout", "ADS 查询超时，请稍后重试。", True)
        except requests.RequestException:
            return failure("ads_unavailable", "无法连接 ADS 服务，请稍后重试。", True)
        except (ValueError, KeyError, TypeError, OverflowError):
            return failure("ads_invalid_response", "ADS 返回的数据或分页信息无效。")
        finally:
            if owned_session:
                session.close()
