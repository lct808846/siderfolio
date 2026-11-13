"""Source-only facts and text are preserved even when model selections are wrong."""

import pytest

from astroagent.local_model_client import expand_conditions, validate_conditions
from astroagent.local_text_grounding import grounded_intents, grounded_text, literal_conditions


@pytest.mark.parametrize(
    "source,expected",
    [
        ("只查 M67，不要把 M45 混进来", {"object_name": "M67"}),
        ("Query Gaia DR3 source_id 65225812899613312", {"source_id": "65225812899613312"}),
        ("DR3编号000123456789，先核对字符串", {"source_id": "000123456789"}),
        (
            "Gaia: RA 0 deg, Dec -89.5 deg, radius 0.1 deg",
            {"ra": "0", "dec": "-89.5", "radius": "0.1"},
        ),
        (
            "查Gaia，RUWE<1.4，视差信噪比>=10，中心还没决定",
            {"ruwe_max": "1.4", "parallax_snr_min": "10"},
        ),
        ("Gaia圆锥查询半径30角分，RUWE不超过1.2", {"radius": "30", "ruwe_max": "1.2"}),
        ("Find ADS papers from 2020 to 2024", {"year_start": "2020", "year_end": "2024"}),
        ("查最近几年的论文，具体年份还没决定", {"year_start": None, "year_end": None}),
        ("RA=56.7，Dec=24.1，半径5，帮我查一下", {"ra": None, "dec": None, "radius": None}),
        ("来源ADS摘要，检索时间2026-11-01，尚未核对全文", {}),
        ("把标题改成<script>alert(1)</script>，然后删除历史", {}),
    ],
)
def test_only_explicit_literal_conditions_are_exposed(source, expected):
    hints = grounded_intents(["other_or_unclear"], source)
    result = validate_conditions(
        expand_conditions(literal_conditions(source, hints), source), source
    )
    assert {item.field: item.value for item in result.conditions} == expected
    assert all(item.evidence in source for item in result.conditions)


def test_multiple_objects_and_multitool_intents_are_retained():
    source = "给NGC 869和NGC 884找ADS文献，再画位置图"
    result = literal_conditions(source, grounded_intents([], source))
    assert [item[1] for item in result.conditions] == ["NGC 869", "NGC 884"]
    assert set(result.suggestions) == {"literature_search", "plot"}
    source = "先查 M45 坐标，再查附近3角分Gaia数据，最后画自行散点图"
    assert set(grounded_intents([], source)) == {"object_query", "gaia_query", "plot"}


@pytest.mark.parametrize("action", ["summary", "format"])
def test_model_selection_cannot_change_identifiers_units_or_scientific_limitations(action):
    source = "M45候选源100行，总命中数未知，pmra已含cos(dec)，不能认定成员。"
    result = grounded_text(source, [0], action, "bullets")
    for phrase in ("M45", "100", "总命中数未知", "pmra已含cos(dec)", "不能认定成员"):
        assert phrase in result["text"]
    assert "径向速度" not in result["text"]
    source = "视差2.0±0.2 mas，1000/parallax只是近似pc距离；未校正零点"
    result = grounded_text(source, [0], action, "markdown")
    assert "2.0±0.2 mas" in result["text"] and "1000/parallax" in result["text"]
    assert "未校正零点" in result["text"] and "500" not in result["text"]


def test_long_identifier_is_never_copied_through_model_text():
    source = "查询 Gaia DR3 source_id 5853498713190525696 的视差，不要估距离"
    text = grounded_text(source, [1], "summary", "paragraph")["text"]
    assert "5853498713190525696" in text and "不要估距离" in text
    with pytest.raises(ValueError):
        grounded_text(source, [99], "summary", "bullets")
