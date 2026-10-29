"""主站故障转镜像；不重放查无结果或损坏数据，不修改共享配置。"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import pytest
from astropy.table import Table
from astroquery.simbad import conf
from pyvo.dal.exceptions import DALServiceError
from requests import Session
from requests.exceptions import ConnectionError, ReadTimeout

from astroagent.simbad import SIMBAD_SERVERS, BoundedSession, SimbadService


def client_factory(monkeypatch, primary, mirror):
    calls = []
    sessions = []
    before = conf.server, tuple(conf.servers_list)

    class Client:
        def __init__(self):
            self._session = Session()
            self._server = "unconfigured"
            self._timeout = None

        @property
        def timeout(self):
            return self._timeout

        @timeout.setter
        def timeout(self, value):
            assert isinstance(self._session, BoundedSession)
            assert self._server in SIMBAD_SERVERS
            assert self._session.timeout == value
            self._timeout = value

        def add_votable_fields(self, *fields):
            assert fields == ("otype", "sp_type")

        def query_object(self, name, wildcard):
            assert not wildcard and self.ROW_LIMIT == 1
            calls.append((self._server, name))
            sessions.append(self._session)
            value = primary if self._server == SIMBAD_SERVERS[0] else mirror
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr("astroagent.simbad.Simbad", Client)
    return calls, sessions, before


def result_table():
    return Table({"main_id": ["synthetic"], "ra": [56.75], "dec": [24.12]})


@pytest.mark.parametrize(
    "error",
    [
        ReadTimeout("private"),
        ConnectionError("private"),
        DALServiceError("HTTP failure", code=503),
        DALServiceError("Unable to access capabilities endpoint"),
        DALServiceError("wrapped", cause=ConnectionError("private")),
    ],
)
def test_unreachable_primary_falls_back_once_with_real_mirror_source(monkeypatch, error):
    calls, sessions, before = client_factory(monkeypatch, error, result_table())
    name = "synthetic + &α"
    result = SimbadService(7).query(name)
    assert result.status == "success" and result.data.ra_deg == 56.75
    assert calls == [(host, name) for host in SIMBAD_SERVERS]
    assert sessions[0] is not sessions[1]
    source = urlparse(result.source.url)
    assert source.hostname == "simbad.cfa.harvard.edu" and source.path == "/simbad/sim-id"
    assert parse_qs(source.query)["Ident"] == [name]
    assert result.source.retrieved_at.tzinfo is not None
    assert (conf.server, tuple(conf.servers_list)) == before
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize(
    "primary",
    [
        result_table(),
        None,
        Table(names=["main_id"]),
        ValueError("invalid table"),
        DALServiceError("bad query", code=400),
        DALServiceError("invalid reply", cause=ValueError("malformed table")),
    ],
)
def test_valid_no_match_or_invalid_data_does_not_contact_another_mirror(monkeypatch, primary):
    calls, _, _ = client_factory(monkeypatch, primary, result_table())
    result = SimbadService().query("synthetic")
    assert calls == [(SIMBAD_SERVERS[0], "synthetic")]
    assert urlparse(result.source.url).hostname == SIMBAD_SERVERS[0]
    expected = (
        "error"
        if isinstance(primary, Exception)
        else "not_found"
        if primary is None or not len(primary)
        else "success"
    )
    assert result.status == expected


def test_mirror_no_match_is_a_terminal_result(monkeypatch):
    calls, _, _ = client_factory(monkeypatch, ConnectionError("private"), None)
    result = SimbadService().query("missing")
    assert len(calls) == 2 and result.status == "not_found"
    assert result.error.code == "object_not_found" and result.data is None
    assert urlparse(result.source.url).hostname == SIMBAD_SERVERS[1]


def test_both_timeouts_keep_safe_error_and_mirror_provenance(monkeypatch):
    calls, _, _ = client_factory(
        monkeypatch, ReadTimeout("primary private"), ReadTimeout("mirror private")
    )
    result = SimbadService().query("synthetic")
    assert len(calls) == 2 and result.error.code == "simbad_timeout"
    assert result.status == "error" and result.data is None and result.error.retryable
    assert "private" not in result.model_dump_json()
    assert urlparse(result.source.url).hostname == SIMBAD_SERVERS[1]


def test_concurrent_queries_do_not_change_global_server(monkeypatch):
    _, _, before = client_factory(monkeypatch, ConnectionError("private"), result_table())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(SimbadService().query, ["one", "two"]))
    assert all(r.status == "success" for r in results)
    assert [r.object_name for r in results] == ["one", "two"]
    assert (conf.server, tuple(conf.servers_list)) == before
