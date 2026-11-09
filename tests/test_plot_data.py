"""Changed V1.3 ingestion preserves synthetic identifiers and rejects invalid input."""

from uuid import uuid4

import pytest

from astroagent.errors import ServiceError
from astroagent.plot_data import dataset, from_snapshot, table


def test_long_ids_negative_values_and_missing_cells_are_preserved():
    raw = b"source_id,parallax,flux\n5853498713190525696,-0.25,\n5853498713190525697,1.5,3\n"
    header, rows = table(raw, "synthetic.csv")
    info, normalized = dataset(str(uuid4()), str(uuid4()), "synthetic.csv", raw, header, rows)
    assert info["columns"][0]["kind"] == "identifier"
    assert info["columns"][1]["kind"] == "number"
    assert info["columns"][2]["missing"] == 1
    assert all(column["unit"] is None for column in info["columns"])
    assert normalized == raw


def test_snapshot_import_uses_all_one_hundred_delivered_rows():
    rows = [{"source_id": str(5853498713190525600 + i), "parallax": -0.1 + i} for i in range(100)]
    snapshot = {
        "id": str(uuid4()),
        "name": "synthetic",
        "response": {"gaia_results": [{"status": "success", "data": rows, "truncated": False}]},
    }
    info, data, _ = from_snapshot(str(uuid4()), str(uuid4()), snapshot, 0)
    assert info["rows"] == 100
    assert len(table(data, "snapshot.csv")[1]) == 100
    assert rows[-1]["source_id"].encode() in data


@pytest.mark.parametrize("raw", [b"x,x\n1,2\n", b"x,y\n1\n", b"x\n\xff\n"])
def test_invalid_csv_is_rejected_without_partial_import(raw):
    with pytest.raises(ServiceError):
        table(raw, "invalid.csv")
