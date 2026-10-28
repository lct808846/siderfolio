"""合成 VOTable；只验证转换契约，不作为观测数据。"""

from xml.etree import ElementTree as ET

from astroagent.gaia import GAIA_COLUMNS, GAIA_UNITS, GaiaService
from astroagent.schemas import GaiaQuery

SOURCE_ID = "5853498713190525696"


def source_row(**updates):
    return {
        **dict.fromkeys(GAIA_COLUMNS),
        "source_id": SOURCE_ID,
        "ra": 56.75,
        "dec": 24.12,
        "ref_epoch": 2016.0,
        "parallax": 10.0,
        "parallax_error": 0.5,
        "pmra": 2.0,
        "pmdec": -3.0,
        "ruwe": 1.1,
        "astrometric_params_solved": 31,
        "duplicated_source": False,
        "separation_deg": 0.001,
        **updates,
    }


def votable(rows=None, *, before="OK", after=None, cone=False, missing=(), types=None, units=None):
    rows = [source_row()] if rows is None else rows
    root = ET.Element("VOTABLE", version="1.3", xmlns="http://www.ivoa.net/xml/VOTable/v1.3")
    resource = ET.SubElement(root, "RESOURCE", type="results")
    if before is not None:
        ET.SubElement(resource, "INFO", name="QUERY_STATUS", value=before).text = "Synthetic status"
    table = ET.SubElement(resource, "TABLE")
    columns = [name for name in GAIA_COLUMNS if name not in missing]
    if cone:
        columns.append("separation_deg")
    for name in columns:
        datatype = {
            "source_id": "long",
            "duplicated_source": "boolean",
            "astrometric_params_solved": "short",
        }.get(name, "double")
        unit = "deg" if name == "separation_deg" else GAIA_UNITS[name]
        field = ET.SubElement(
            table,
            "FIELD",
            name=name,
            ID=name,
            datatype=(types or {}).get(name, datatype),
            unit=(units or {}).get(name, unit),
        )
        if field.get("datatype") in {"char", "unicodeChar"}:
            field.set("arraysize", "*")
    data = ET.SubElement(ET.SubElement(table, "DATA"), "TABLEDATA")
    for row in rows:
        tr = ET.SubElement(data, "TR")
        for name in columns:
            value = row.get(name)
            ET.SubElement(tr, "TD").text = (
                "" if value is None else (str(value).lower() if type(value) is bool else str(value))
            )
    if after is not None:
        ET.SubElement(resource, "INFO", name="QUERY_STATUS", value=after).text = "Synthetic status"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class FakeResponse:
    def __init__(self, body=b"", status=200, chunks=None):
        self.body, self.status_code, self.chunks = body, status, chunks
        self.closed = False

    def iter_content(self, chunk_size):
        if self.chunks is not None:
            yield from self.chunks
        else:
            yield self.body

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else FakeResponse(votable())
        self.error = error
        self.calls = []
        self.closed = False

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def execute(body=None, *, query=None, **response_options):
    response = FakeResponse(votable() if body is None else body, **response_options)
    session = FakeSession(response)
    query = query or GaiaQuery(mode="source_id", source_id=SOURCE_ID)
    return GaiaService(session=session).query(query), session, response
