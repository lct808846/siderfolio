"""Project-scoped N-body drafts, execution control and immutable results."""

import json
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from langchain_core.messages import HumanMessage, SystemMessage
from psycopg.errors import UndefinedTable

from astroagent import compute_tasks as queue
from astroagent.api.conversations import Service
from astroagent.compute_exports import experiment_zip, plot_svg, snapshot_csv
from astroagent.compute_schemas import (
    ComputeConfirm,
    ComputeDescribe,
    ComputeDraft,
    ComputeEdit,
    ComputeList,
    ComputeProposal,
    ComputeStatus,
    ComputeTask,
    PlotKind,
    SimulationParameters,
    SimulationResult,
    binary_template,
)
from astroagent.config import Settings
from astroagent.errors import ServiceError
from astroagent.execution import MODEL_TASK_SLOTS
from astroagent.model_client import chat_model
from astroagent.schemas import ErrorResponse

status_router = APIRouter(prefix="/api/v1/compute", tags=["compute"])


@status_router.get("/status", response_model=ComputeStatus)
def compute_status(service: Service):
    is_enabled = queue.enabled()
    engines = queue.worker_engines() if is_enabled else []
    return {
        "enabled": is_enabled,
        "worker_ready": bool(engines),
        "engines": engines,
    }


router = APIRouter(
    prefix="/api/v1/projects/{project_id}/compute-tasks",
    tags=["compute"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 413, 415, 422, 503)},
)


@contextmanager
def access(request, project_id, *, mutation=False):
    queue.availability()
    owner = queue.owner_fields(request, project_id)
    try:
        with request.app.state.identity.store.connect() as db:
            if mutation:
                queue.lock(db)
            if not queue.available_project(db, owner[0], owner[2], project_id):
                raise ServiceError(404, "project_not_found", "找不到该项目。")
            yield db, owner
    except UndefinedTable as exc:
        raise ServiceError(503, "compute_schema_missing", "计算任务数据表等待初始化。") from exc


@router.get("", response_model=ComputeList)
def list_tasks(project_id: UUID, request: Request, service: Service):
    with access(request, project_id) as (db, owner):
        engines = queue.worker_engines()
        return {
            "worker_ready": bool(engines),
            "engines": engines,
            "tasks": queue.summary(db, owner),
        }


@router.get("/templates/binary", response_model=SimulationParameters)
def template(project_id: UUID, request: Request, service: Service):
    with access(request, project_id):
        return binary_template()


@router.post("/describe", response_model=ComputeProposal)
def describe(project_id: UUID, body: ComputeDescribe, request: Request, service: Service):
    with access(request, project_id) as (db, _):
        db.execute("SELECT 1 FROM public.compute_tasks LIMIT 0")
    if not body.description.strip():
        raise ServiceError(422, "compute_description_required", "请输入实验描述。")
    settings = Settings().for_model(body.model_id)
    if not settings.deepseek_api_key.get_secret_value().strip():
        raise ServiceError(503, "model_not_configured", "请先在模型设置中配置服务商。")
    if not MODEL_TASK_SLOTS.acquire(blocking=False):
        raise ServiceError(503, "model_busy", "模型正在处理其他请求，请稍后再试。")
    try:
        model = chat_model(settings, max_tokens=5000, json_mode=True)
        schema = json.dumps(ComputeProposal.model_json_schema(), ensure_ascii=False)
        answer = model.invoke(
            [
                SystemMessage(
                    content=(
                        "你将用户明确给出的小规模孤立牛顿点质量系统转成 JSON 参数草稿。"
                        "固定单位 AU、yr、M_sun、AU/yr。没有明确给出粒子质量、三维坐标、"
                        "三维速度、持续时间或采样数时，返回中文 clarification 并留空 parameters。"
                        "存在不兼容物理条件时同样追问。模拟程序由用户选择，省略 engine 字段。"
                        "不要补造物理量、执行任务或输出代码。"
                        f"仅返回符合此 JSON Schema 的对象：{schema}"
                    )
                ),
                HumanMessage(content=body.description),
            ]
        )
        proposal = ComputeProposal.model_validate_json(answer.content)
        if proposal.clarification:
            return ComputeProposal(clarification=proposal.clarification)
        if proposal.parameters is None:
            raise ValueError("Missing proposal")
        return proposal
    except Exception as exc:
        raise ServiceError(
            502,
            "compute_proposal_failed",
            "模型未返回完整参数。请补充初始条件，或使用表单录入。",
        ) from exc
    finally:
        MODEL_TASK_SLOTS.release()


@router.post("", response_model=ComputeTask, status_code=201)
def create(project_id: UUID, body: ComputeDraft, request: Request, service: Service):
    with access(request, project_id, mutation=True) as (db, owner):
        return queue.create(db, owner, body)


@router.get("/{task_id}", response_model=ComputeTask)
def detail(project_id: UUID, task_id: UUID, request: Request, service: Service):
    with access(request, project_id) as (db, owner):
        return queue.task(db, owner, task_id)


@router.patch("/{task_id}", response_model=ComputeTask)
def edit(project_id: UUID, task_id: UUID, body: ComputeEdit, request: Request, service: Service):
    with access(request, project_id, mutation=True) as (db, owner):
        return queue.edit(db, queue.task(db, owner, task_id, update=True), body)


@router.post("/{task_id}/confirm", response_model=ComputeTask)
def confirm(
    project_id: UUID, task_id: UUID, body: ComputeConfirm, request: Request, service: Service
):
    with access(request, project_id, mutation=True) as (db, owner):
        return queue.confirm(db, queue.task(db, owner, task_id, update=True), body)


@router.post("/{task_id}/cancel", response_model=ComputeTask)
def cancel(project_id: UUID, task_id: UUID, request: Request, service: Service):
    with access(request, project_id, mutation=True) as (db, owner):
        return queue.cancel(db, queue.task(db, owner, task_id, update=True))


@router.post("/{task_id}/copy", response_model=ComputeTask, status_code=201)
def copy(project_id: UUID, task_id: UUID, request: Request, service: Service):
    with access(request, project_id, mutation=True) as (db, owner):
        row = queue.task(db, owner, task_id, update=True)
        return queue.create(
            db,
            owner,
            ComputeDraft(
                name=row["name"],
                source=row["source"],
                parameters=row["parameters"],
            ),
            origin=task_id,
        )


@router.delete("/{task_id}", status_code=204)
def delete(project_id: UUID, task_id: UUID, request: Request, service: Service):
    with access(request, project_id, mutation=True) as (db, owner):
        queue.deletable(db, queue.task(db, owner, task_id, update=True))
    return Response(status_code=204)


def published(request, project_id, task_id):
    with access(request, project_id) as (db, owner):
        row = queue.task(db, owner, task_id, result=True)
    if row["state"] != "succeeded":
        raise ServiceError(409, "compute_result_pending", "这项实验没有已发布的计算结果。")
    return row


@router.get("/{task_id}/result", response_model=SimulationResult)
def result(project_id: UUID, task_id: UUID, request: Request, service: Service):
    return published(request, project_id, task_id)["result"]


@router.get("/{task_id}/plots/{kind}", response_class=Response)
def plot(
    project_id: UUID,
    task_id: UUID,
    kind: PlotKind,
    request: Request,
    service: Service,
    sample: int | None = Query(default=None, ge=0, le=511),
):
    return Response(
        plot_svg(published(request, project_id, task_id), kind, sample),
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'",
        },
    )


@router.get(
    "/{task_id}/snapshots",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def snapshots(project_id: UUID, task_id: UUID, request: Request, service: Service):
    return Response(
        snapshot_csv(published(request, project_id, task_id)),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="astroagent-snapshots-{task_id}.csv"'
        },
    )


@router.get("/{task_id}/archive", response_class=Response)
def archive(
    project_id: UUID,
    task_id: UUID,
    request: Request,
    service: Service,
    plots: Annotated[list[PlotKind] | None, Query(max_length=3)] = None,
    sample: Annotated[int | None, Query(ge=0, le=511)] = None,
):
    return Response(
        experiment_zip(published(request, project_id, task_id), plots or [], sample),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="astroagent-experiment-{task_id}.zip"'
        },
    )
