from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from astropy.table import MaskedColumn, Table
from pyvo.dal.exceptions import DALServiceError
from requests import Session
from requests.exceptions import ConnectionError, ReadTimeout

from astroagent.simbad import BoundedSession, SimbadService


def mock_client(monkeypatch, table=None, error=None):
    class Client:
        def __init__(self, **kwargs):
            self.timeout = kwargs["timeout"]

        def add_votable_fields(self, *fields):
            assert fields == ("otype", "sp_type")

        def query_object(self, name, wildcard):
            assert wildcard is False
            assert self.ROW_LIMIT == 1
            assert self._session.timeout == self.timeout
            if error:
                raise error
            return table

    monkeypatch.setattr("astroagent.simbad.Simbad", Client)


def test_real_table_serialization_and_source_encoding(monkeypatch):
    table = Table(
        {
            "main_id": ["synthetic-star"],
            "ra": [12.5],
            "dec": [-30.2],
            "otype": ["Star"],
            "sp_type": ["G2V"],
            "coo_bibcode": ["test-reference"],
        }
    )
    mock_client(monkeypatch, table)
    name = "star + &?/'α"
    result = SimbadService().query(name)
    assert result.status == "success"
    assert result.data.ra_deg == 12.5
    assert result.data.coordinate_frame == "ICRS"
    assert result.data.coordinate_bibcode == "test-reference"
    assert parse_qs(urlparse(result.source.url).query)["Ident"] == [name]
    assert result.source.retrieved_at.tzinfo is not None


def test_masked_nonfinite_and_absent_fields_are_null(monkeypatch):
    table = Table({"main_id": ["synthetic"], "ra": [np.nan], "dec": [np.inf]})
    table.add_column(MaskedColumn(["unknown"], name="sp_type", mask=[True]))
    mock_client(monkeypatch, table)
    result = SimbadService().query("synthetic")
    assert result.status == "success"
    assert result.data.ra_deg is result.data.dec_deg is result.data.spectral_type is None
    assert result.data.object_type is None
    result.model_dump_json()  # 不允许 NaN/Inf 进入 JSON 科研结果。


@pytest.mark.parametrize("table", [None, Table(names=["main_id"])])
def test_unknown_object_returns_explicit_not_found(monkeypatch, table):
    mock_client(monkeypatch, table)
    result = SimbadService().query("missing")
    assert result.status == "not_found"
    assert result.data is None
    assert result.error.code == "object_not_found"


@pytest.mark.parametrize(
    "error,code",
    [
        (ReadTimeout("secret"), "simbad_timeout"),
        (DALServiceError("Read timed out: secret"), "simbad_timeout"),
        (ConnectionError("secret"), "simbad_unavailable"),
        (ValueError("secret malformed VOTable"), "simbad_unavailable"),
    ],
)
def test_remote_failure_is_sanitized(monkeypatch, error, code):
    mock_client(monkeypatch, error=error)
    result = SimbadService().query("synthetic")
    assert result.status == "error"
    assert result.error.code == code
    assert result.error.retryable
    assert "secret" not in result.model_dump_json()
    assert result.data is None


def test_missing_identifier_is_not_a_success(monkeypatch):
    mock_client(monkeypatch, Table({"ra": [12.0]}))
    assert SimbadService().query("synthetic").status == "error"


def test_session_limits_even_metadata_requests(monkeypatch):
    captured = {}

    def request(self, method, url, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(Session, "request", request)
    with BoundedSession(7) as session:
        session.get("https://example.test", timeout=None)
    assert captured["timeout"] == 7
