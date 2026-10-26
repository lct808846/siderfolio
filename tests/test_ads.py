"""合成 ADS 响应的离线契约测试，不代表真实文献或联网验收。"""

from copy import deepcopy
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import requests
from pydantic import ValidationError

from astroagent.ads import ADS_ENDPOINT, ADS_FIELDS, AdsService, search_url
from astroagent.schemas import LiteratureQuery


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.closed = False

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def close(self):
        self.closed = True


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def payload(docs=None, total=None, start=0):
    docs = [{"bibcode": "synthetic&A/1"}] if docs is None else docs
    return {
        "response": {
            "numFound": len(docs) if total is None else total,
            "start": start,
            "docs": docs,
        }
    }


def search(data, *, status=200, **arguments):
    session = Session(Response(data, status))
    result = AdsService("private-token", timeout=7, session=session).search(
        LiteratureQuery(query='title:"binary clusters"', **arguments)
    )
    assert session.response.closed
    return result, session


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": " "},
        {"query": "x" * 1001},
        {"query": "中" * 112},
        {"query": "x", "sort": "random"},
        {"query": "x", "rows": "5"},
        {"query": "x", "rows": True},
        {"query": "x", "rows": 1.0},
        {"query": "x", "rows": 0},
        {"query": "x", "rows": 11},
        {"query": "x", "start": "1"},
        {"query": "x", "start": -1},
        {"query": "x", "start": 91},
        {"query": "x", "url": "https://example.test"},
    ],
)
def test_invalid_arguments(arguments):
    with pytest.raises(ValidationError):
        LiteratureQuery(**arguments)


def test_argument_boundaries_and_strip():
    assert LiteratureQuery(query=" x ", start=90, rows=10).query == "x"
    assert len(LiteratureQuery(query="x" * 1000).query) == 1000
    assert LiteratureQuery(query="中" * 111).rows == 5


@pytest.mark.parametrize(
    "sort,external",
    [
        ("relevance", None),
        ("date_desc", "date desc"),
        ("citation_count_desc", "citation_count desc"),
    ],
)
def test_fixed_request_contract(sort, external):
    result, session = search(payload(), sort=sort)
    assert result.status == "success"
    args, kwargs = session.calls[0]
    assert args == (ADS_ENDPOINT,)
    assert kwargs["headers"] == {"Authorization": "Bearer private-token"}
    assert kwargs["timeout"] == (7, 7)
    assert kwargs["allow_redirects"] is False
    assert kwargs["params"] == {
        "q": 'title:"binary clusters"',
        "fl": ADS_FIELDS,
        "fq": "database:astronomy",
        "rows": 5,
        "start": 0,
        **({"sort": external} if external else {}),
    }
    assert len(session.calls) == 1
    assert result.filters == ["database:astronomy"]


def test_full_field_mapping_deduplication_and_raw_page_count():
    doc = {
        "bibcode": "synthetic&A/1",
        "title": ["", "First title", "Second title"],
        "author": ["B, A", "A, B"],
        "year": "2024",
        "pub": "Synthetic Journal",
        "doi": ["10.synthetic/first", "10.synthetic/second"],
        "abstract": "original abstract",
        "citation_count": 0,
    }
    duplicate = {**doc, "title": ["Ignored duplicate"]}
    result, _ = search(payload([doc, duplicate], total=3), rows=2)
    assert result.returned_count == 1 and result.has_more is True
    paper = result.papers[0]
    assert paper.title == "First title"
    assert paper.authors == doc["author"] and paper.doi == doc["doi"]
    assert paper.year == 2024 and paper.publication == "Synthetic Journal"
    assert paper.abstract == "original abstract" and paper.citation_count == 0
    assert paper.source.name == "ADS"
    assert paper.source.retrieved_at == result.source.retrieved_at
    assert paper.source.url.endswith("/synthetic%26A%2F1/abstract")


def test_optional_missing_and_null_fields():
    for doc in (
        {"bibcode": "id"},
        {
            "bibcode": "id",
            **dict.fromkeys(
                ["title", "author", "year", "pub", "doi", "abstract", "citation_count"]
            ),
        },
    ):
        result, _ = search(payload([doc]))
        paper = result.papers[0]
        assert paper.title is paper.year is paper.publication is paper.abstract is None
        assert paper.citation_count is None
        assert paper.authors == paper.doi == []


@pytest.mark.parametrize(
    "docs,total,start,rows,status,more",
    [
        ([], 0, 0, 5, "not_found", False),
        ([], 1, 5, 5, "not_found", False),
        ([{"bibcode": "id"}], 6, 5, 5, "success", False),
        ([{"bibcode": "id"}], 10, 0, 1, "success", True),
    ],
)
def test_pagination(docs, total, start, rows, status, more):
    result, _ = search(payload(docs, total, start), rows=rows, start=start)
    assert result.status == status and result.has_more is more
    assert result.total_found == total
    assert result.returned_count == len(result.papers)
    assert result.error is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("bibcode", None),
        ("bibcode", " "),
        ("bibcode", 1),
        ("title", "bad"),
        ("title", [1]),
        ("author", [None]),
        ("author", "bad"),
        ("doi", [1]),
        ("doi", {}),
        ("year", "unknown"),
        ("year", True),
        ("year", 2024.0),
        ("year", 0),
        ("year", "10000"),
        ("pub", []),
        ("abstract", {}),
        ("citation_count", -1),
        ("citation_count", "0"),
        ("citation_count", True),
    ],
)
def test_present_malformed_field_invalidates_entire_page(field, value):
    result, _ = search(payload([{"bibcode": "id", field: value}]))
    assert result.status == "error" and result.error.code == "ads_invalid_response"
    assert result.papers == [] and result.total_found is result.has_more is None


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"response": None},
        payload([{}]),
        payload(["bad"]),
        payload(total=True),
        payload(total=-1),
        payload(total="1"),
        payload(total=0),
        payload(start=1),
        payload([], total=1),
        payload([{"bibcode": "a"}] * 6, total=6),
        {**payload(), "responseHeader": {"status": 1}},
        {**payload(), "responseHeader": {"partialResults": True}},
        {**payload(), "error": {"message": "secret"}},
        ValueError("secret"),
        requests.exceptions.JSONDecodeError("secret", "", 0),
    ],
)
def test_invalid_responses(data):
    result, _ = search(deepcopy(data))
    assert result.error.code == "ads_invalid_response"
    assert "secret" not in result.model_dump_json()
    assert not result.papers


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "ads_authentication_failed", False),
        (403, "ads_authentication_failed", False),
        (429, "ads_rate_limited", True),
        (400, "ads_invalid_query", False),
        (500, "ads_unavailable", True),
        (503, "ads_unavailable", True),
        (302, "ads_unexpected_response", False),
        (404, "ads_unexpected_response", False),
        (204, "ads_unexpected_response", False),
    ],
)
def test_http_errors_are_safe_without_retry(status, code, retryable):
    result, session = search({"secret": "private-token"}, status=status)
    assert result.error.code == code and result.error.retryable is retryable
    assert "private-token" not in result.model_dump_json()
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "exception,code",
    [
        (requests.ConnectTimeout("private-token"), "ads_timeout"),
        (requests.ReadTimeout("private-token"), "ads_timeout"),
        (requests.ConnectionError("private-token"), "ads_unavailable"),
    ],
)
def test_transport_errors(exception, code):
    session = Session(exception)
    result = AdsService("private-token", session=session).search(LiteratureQuery(query="x"))
    assert result.error.code == code and result.error.retryable
    assert len(session.calls) == 1 and "private-token" not in result.model_dump_json()


def test_missing_token_never_opens_network():
    session = Session(AssertionError("must not execute"))
    result = AdsService(" ", session=session).search(LiteratureQuery(query="x"))
    assert result.error.code == "ads_not_configured" and not session.calls


def test_owned_session_has_no_retries_and_is_closed(monkeypatch):
    original = requests.Session
    closed = []

    def factory():
        session = original()
        assert all(adapter.max_retries.total == 0 for adapter in session.adapters.values())
        session.get = lambda *a, **kw: Response(payload())
        session.close = lambda: closed.append(True)
        return session

    monkeypatch.setattr(requests, "Session", factory)
    assert AdsService("secret").search(LiteratureQuery(query="x")).status == "success"
    assert closed == [True]


def test_search_link_encodes_query_filter_offset_and_sort():
    query = LiteratureQuery(query='bibcode:"2007A&A...474..653V"', start=5, sort="date_desc")
    url = urlsplit(search_url(query))
    assert url.scheme == "https" and url.netloc == "ui.adsabs.harvard.edu"
    params = parse_qs(url.path.removeprefix("/search/"))
    assert params["q"] == [query.query] and params["fq"] == ["database:astronomy"]
    assert params["start"] == ["5"] and params["sort"] == ["date desc"]
    assert unquote(search_url(query)).count(query.query) == 1
