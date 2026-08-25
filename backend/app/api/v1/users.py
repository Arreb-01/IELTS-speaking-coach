"""用户信息：查看与更新个人资料。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import User
from app.schemas.auth import UserOut
from app.schemas.user import UserUpdateRequest

router = APIRouter()


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.put("/me", response_model=UserOut)
async def update_me(
    body: UserUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.target_band is not None:
        user.target_band = body.target_band
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)
