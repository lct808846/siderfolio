"""User profile, avatar upload/removal, and private workspace usage summary."""

from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile

from astroagent.api.auth import actor, runtime
from astroagent.api.conversations import get_service
from astroagent.errors import ServiceError
from astroagent.profile_schemas import AvatarResponse, ProfileSummary
from astroagent.profile_service import (
    MAX_AVATAR_BYTES,
    build_profile_summary,
    delete_user_avatar,
    save_user_avatar,
)

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("/summary", response_model=ProfileSummary)
def summary(request: Request):
    identity, user = runtime(request), actor(request)
    service = get_service(request)
    return build_profile_summary(identity, user, service)


@router.post("/avatar", response_model=AvatarResponse)
async def upload_avatar(request: Request, file: Annotated[UploadFile, File()]):
    identity, user = runtime(request), actor(request)
    chunks = bytearray()
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        if len(chunks) + len(chunk) > MAX_AVATAR_BYTES:
            raise ServiceError(413, "avatar_too_large", "头像图片不能超过 5 MiB。")
        chunks.extend(chunk)
    avatar_url = save_user_avatar(identity, user["id"], bytes(chunks))
    return AvatarResponse(message="头像已更新。", avatar_url=avatar_url)


@router.delete("/avatar", response_model=AvatarResponse)
def remove_avatar(request: Request):
    identity, user = runtime(request), actor(request)
    avatar_url = delete_user_avatar(identity, user["id"])
    return AvatarResponse(message="已恢复默认头像。", avatar_url=avatar_url)
