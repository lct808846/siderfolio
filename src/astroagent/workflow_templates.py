"""程序内固定模板及输入映射；用户文本不会被解释为流程定义。"""

import hashlib
import importlib.metadata
import platform

from astroagent.conversations import encode
from astroagent.projects import software_versions
from astroagent.schemas import GaiaQuery
from astroagent.workflow_schemas import AdsEvidenceParameters, GaiaFieldParameters, StepDependency

TEMPLATE_VERSION = "1"
DEFINITIONS = {
    "gaia_field": (
        ("resolve_name", "解析名称 / 确认ICRS坐标"),
        ("query_gaia", "查询Gaia与程序统计"),
        ("save_snapshot", "保存完整项目快照"),
        ("export_results", "生成数据包与所选图表"),
    ),
    "ads_evidence": (
        ("query_ads", "执行确认的ADS检索式"),
        ("evidence_table", "整理原始摘要证据表"),
        ("save_snapshot", "保存完整项目快照"),
        ("export_results", "导出书目与原始响应"),
    ),
}


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def environment():
    result = {**software_versions(), "python": platform.python_version(), "workflow": "1"}
    for name in ("requests", "pyvo", "pydantic"):
        result[name] = importlib.metadata.version(name)
    from astroagent.plots import STYLE_VERSION

    result["plot_style"] = STYLE_VERSION
    return result


def step_software(step_id):
    dependencies = {
        "resolve_name": ("astroquery", "astropy", "requests", "pyvo"),
        "query_gaia": ("requests", "astropy", "numpy"),
        "query_ads": ("requests",),
        "evidence_table": (),
        "save_snapshot": ("pydantic",),
        "export_results": ("matplotlib", "numpy", "astropy", "plot_style", "pydantic"),
    }
    values = environment()
    return {
        key: values[key] for key in ("astroagent", "python", "workflow", *dependencies[step_id])
    }


def completed_attempt(run, step_id):
    step = next(s for s in run.steps if s.id == step_id)
    if step.state != "succeeded" or not step.attempts or step.attempts[-1].state != "succeeded":
        raise ValueError("上游步骤尚无完整成功输出")
    return step.attempts[-1]


def response_attempt(run):
    return completed_attempt(run, "query_gaia" if run.template_id == "gaia_field" else "query_ads")


def prepare_input(run, step_id):
    p = run.parameters
    dependencies = []

    def depends(identifier):
        attempt = completed_attempt(run, identifier)
        dependencies.append(
            StepDependency(step_id=identifier, attempt_id=attempt.id, sha256=attempt.output_sha256)
        )
        return attempt

    if step_id == "resolve_name":
        value = {"family": "simbad", "parameters": {"object_name": p["object_name"]}}
    elif step_id == "query_gaia":
        position = depends("resolve_name").output["coordinates"] if p["input_mode"] == "name" else p
        query = GaiaQuery(
            mode="cone",
            ra_deg=position["ra_deg"],
            dec_deg=position["dec_deg"],
            **{
                key: p.get(key)
                for key in (
                    "radius_arcmin",
                    "limit",
                    "ruwe_max",
                    "parallax_snr_min",
                    "parallax_min",
                    "parallax_max",
                    "pmra_min",
                    "pmra_max",
                    "pmdec_min",
                    "pmdec_max",
                    "g_mag_max",
                    "estimate_distance",
                )
            },
        )
        value = {"family": "gaia", "parameters": query.effective_parameters()}
    elif step_id == "query_ads":
        value = {"family": "ads", "parameters": p}
    elif step_id == "evidence_table":
        source = depends("query_ads")
        value = {
            "response_sha256": digest(source.output["response"]),
            "format_version": "1",
            "csv_field_limit": 32767,
        }
    elif step_id == "save_snapshot":
        source = depends("query_gaia" if run.template_id == "gaia_field" else "query_ads")
        if run.template_id == "ads_evidence":
            depends("evidence_table")
        value = {"response_sha256": digest(source.output["response"]), "snapshot_contract": "1"}
    else:
        source = depends("save_snapshot")
        value = {
            "snapshot_sha256": source.output["response_sha256"],
            "plots": [{"kind": kind, "gaia_result_index": 0} for kind in p.get("plots", [])],
        }
    return value, dependencies


def input_digest(run, step, value, dependencies, software):
    return digest(
        {
            "template": run.template_id,
            "template_version": run.template_version,
            "step": step.id,
            "step_version": step.version,
            "input": value,
            "dependencies": [{"step_id": d.step_id, "sha256": d.sha256} for d in dependencies],
            "software": software,
        }
    )


def parameters(template_id, raw):
    model = GaiaFieldParameters if template_id == "gaia_field" else AdsEvidenceParameters
    return model.model_validate(raw).model_dump(mode="json")


def templates():
    values = []
    for key, steps in DEFINITIONS.items():
        gaia = key == "gaia_field"
        values.append(
            {
                "id": key,
                "version": TEMPLATE_VERSION,
                "title": "Gaia视场候选源" if gaia else "ADS摘要证据表",
                "description": "明确名称或坐标，查询完整交付样本并导出。"
                if gaia
                else "按已确认检索式整理书目和返回的原始摘要。",
                "steps": [{"id": sid, "version": "1", "title": title} for sid, title in steps],
                "input_schema": (
                    GaiaFieldParameters if gaia else AdsEvidenceParameters
                ).model_json_schema(),
                "warnings": (
                    ["位置候选源不等于星团成员；未做自行传播。", "统计和图表只描述交付样本。"]
                    if gaia
                    else ["仅整理返回的书目与原摘要，不是全文阅读或系统综述。"]
                )
                + ["流程不调用模型；启动或继续会按需访问外部科研服务。"],
            }
        )
    return values
