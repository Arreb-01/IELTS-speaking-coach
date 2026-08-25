"""种子题库导入：python -m app.seed.load

幂等：按 name_en 判断，已存在的话题跳过。
Part D 的 PDF 全量题库导入后，本种子数据自然并入。
"""

import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import Question, Topic

logger = logging.getLogger(__name__)
SEED_FILE = Path(__file__).parent / "topics_seed.json"


async def load_seed(session_factory=None) -> dict[str, int]:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    created_topics = 0
    created_questions = 0
    factory = session_factory or async_session_factory

    async with factory() as db:
        for item in data["part1_topics"]:
            exists = await db.scalar(select(Topic).where(Topic.name_en == item["name_en"]))
            if exists:
                continue
            topic = Topic(
                name_en=item["name_en"],
                name_zh=item["name_zh"],
                category=item["category"],
                tag=item["tag"],
            )
            db.add(topic)
            await db.flush()
            for i, text in enumerate(item["questions"]):
                db.add(Question(topic_id=topic.id, part=1, content_en=text, sort=i))
                created_questions += 1
            created_topics += 1

        for item in data["part23_topics"]:
            exists = await db.scalar(select(Topic).where(Topic.name_en == item["name_en"]))
            if exists:
                continue
            topic = Topic(
                name_en=item["name_en"],
                name_zh=item["name_zh"],
                category=item["category"],
                tag=item["tag"],
            )
            db.add(topic)
            await db.flush()
            cue = item["cue_card"]
            # Part2：题目正文即 Cue Card 提示句
            db.add(
                Question(
                    topic_id=topic.id,
                    part=2,
                    content_en=cue["prompt"],
                    cue_card=cue,
                    sort=0,
                )
            )
            created_questions += 1
            # Part3：追问种子入库（content_en 为题干）
            for i, text in enumerate(item["followup_seeds"]):
                db.add(Question(topic_id=topic.id, part=3, content_en=text, sort=i))
                created_questions += 1
            created_topics += 1

        await db.commit()

    logger.info("种子导入完成：%d 个话题 / %d 道题", created_topics, created_questions)
    return {"topics": created_topics, "questions": created_questions}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(load_seed())
    print(f"seed loaded: {result}")
