"""个人词汇本：从高分表达收藏/取消，手动增删，列表与收藏筛选。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import Topic, User, UserVocabWord
from app.schemas.topic import VocabWordCreateRequest, VocabWordOut

router = APIRouter()


async def _to_out(db: AsyncSession, w: UserVocabWord) -> VocabWordOut:
    topic_name = None
    if w.source_topic_id is not None:
        topic = await db.get(Topic, w.source_topic_id)
        if topic is not None:
            topic_name = topic.name_zh or topic.name_en
    return VocabWordOut(
        id=w.id,
        word=w.word,
        context_en=w.context_en,
        source_topic_id=w.source_topic_id,
        source_topic_name=topic_name,
        is_favorite=w.is_favorite,
        created_at=w.created_at,
    )


@router.get("", response_model=dict)
async def list_vocab_words(
    favorite: bool | None = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(UserVocabWord).where(UserVocabWord.user_id == user.id)
    if favorite is True:
        stmt = stmt.where(UserVocabWord.is_favorite.is_(True))
    if search:
        kw = f"%{search.strip()}%"
        stmt = stmt.where(UserVocabWord.word.ilike(kw))
    total = (await db.scalar(select(func.count()).select_from(stmt.subquery()))) or 0
    rows = (
        await db.scalars(
            stmt.order_by(UserVocabWord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [await _to_out(db, w) for w in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=VocabWordOut)
async def add_vocab_word(
    payload: VocabWordCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VocabWordOut:
    word = payload.word.strip()
    if not word:
        raise HTTPException(422, "单词不能为空")
    exists = await db.scalar(
        select(UserVocabWord).where(
            UserVocabWord.user_id == user.id, UserVocabWord.word == word
        )
    )
    if exists is not None:
        # 已收藏过：补上下文/来源后幂等返回
        if payload.context_en and not exists.context_en:
            exists.context_en = payload.context_en
        if payload.source_topic_id and exists.source_topic_id is None:
            exists.source_topic_id = payload.source_topic_id
        await db.commit()
        return await _to_out(db, exists)
    row = UserVocabWord(
        user_id=user.id,
        word=word,
        context_en=payload.context_en,
        source_topic_id=payload.source_topic_id,
    )
    db.add(row)
    await db.commit()
    return await _to_out(db, row)


@router.patch("/{word_id}/favorite", response_model=VocabWordOut)
async def toggle_favorite(
    word_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VocabWordOut:
    import uuid as uuid_mod

    try:
        row_uuid = uuid_mod.UUID(word_id)
    except ValueError:
        raise HTTPException(404, "词条不存在")
    row = await db.get(UserVocabWord, row_uuid)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "词条不存在")
    row.is_favorite = not row.is_favorite
    await db.commit()
    return await _to_out(db, row)


@router.delete("/{word_id}")
async def delete_vocab_word(
    word_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    import uuid as uuid_mod

    try:
        row_uuid = uuid_mod.UUID(word_id)
    except ValueError:
        raise HTTPException(404, "词条不存在")
    row = await db.get(UserVocabWord, row_uuid)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "词条不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
