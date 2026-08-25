"""考官决策：调用豆包 LLM（Ark）做追问判断与 Part 3 出题。

所有调用走 BYOK 解析（用户 Key > 平台 Key）。解析失败时返回安全的
默认行为（next / None），保证练习不因 LLM 故障而中断。
"""

import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import User
from app.services.volcengine import ark
from app.services.volcengine.resolver import resolve_ark_credentials

logger = logging.getLogger(__name__)

_MAX_ANSWER_CHARS = 2000  # 控制 token 消耗


def _extract_json(raw: str) -> dict | None:
    """从模型输出中鲁棒地抽取 JSON（容忍 markdown 围栏等噪音）。"""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def _ask_llm(user: User, db: AsyncSession, system: str, user_content: str) -> dict | None:
    api_key, _source = await resolve_ark_credentials(user, db)
    if api_key is None:
        logger.warning("无可用 LLM Key，考官决策降级为默认行为")
        return None
    try:
        result = await ark.chat_completions(
            api_key,
            get_settings().volc_ark_test_model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=200,
            temperature=0.4,
        )
        content = result["choices"][0]["message"]["content"]
        return _extract_json(content)
    except (ark.ArkError, KeyError, IndexError, TypeError) as exc:
        logger.warning("考官 LLM 调用失败：%s", exc)
        return None


async def decide_followup(
    user: User,
    db: AsyncSession,
    *,
    part: int,
    question: str,
    answer: str,
) -> str | None:
    """返回追问文本；None 表示进入下一题。"""
    from app.services.examiner import prompts

    system = (
        prompts.PART3_FOLLOWUP_DECISION_SYSTEM if part == 3 else prompts.FOLLOWUP_DECISION_SYSTEM
    )
    data = await _ask_llm(
        user,
        db,
        system,
        f"Question: {question}\n\nCandidate answer: {answer[:_MAX_ANSWER_CHARS]}",
    )
    if data and data.get("action") == "followup":
        question_text = str(data.get("question", "")).strip()
        if 5 <= len(question_text) <= 200:
            return question_text
    return None


async def generate_part3_question(
    user: User,
    db: AsyncSession,
    *,
    topic_name: str,
    seed_questions: list[str],
    depth_level: int,
    recent_answers: list[str],
    asked_questions: list[str],
) -> str | None:
    """生成一道 Part 3 讨论题；失败返回 None（上层用种子题兜底）。"""
    from app.services.examiner import prompts

    seeds = "\n".join(f"- {q}" for q in seed_questions[:6]) or "(none)"
    asked = "\n".join(f"- {q}" for q in asked_questions[-6:]) or "(none)"
    answers = " | ".join(a[:300] for a in recent_answers[-3:]) or "(none)"
    user_content = (
        f"Part 2 topic: {topic_name}\n"
        f"Depth level: {depth_level} (of 5)\n"
        f"Seed questions for reference:\n{seeds}\n\n"
        f"Questions already asked (do NOT repeat):\n{asked}\n\n"
        f"Recent candidate answers (optional anchor):\n{answers}"
    )
    data = await _ask_llm(user, db, prompts.PART3_QUESTION_SYSTEM, user_content)
    if data and data.get("question"):
        question_text = str(data["question"]).strip()
        if 10 <= len(question_text) <= 250:
            return question_text
    return None
