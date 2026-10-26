"""服务健康检查接口。"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["health"])
def get_health() -> dict[str, str]:
    """返回服务存活状态。"""
    return {"status": "ok"}
