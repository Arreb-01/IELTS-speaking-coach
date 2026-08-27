"""LLM 评分封装：四维打分（turbo）与中文反馈（pro）。

- BYOK：用户配置的模型优先；平台默认走 turbo/pro 分工
- 输出 JSON 解析容错：markdown 围栏、缺字段、超界值钳制
- 任何失败返回 None，由编排层降级（规则分 / 无反馈）
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import User, UserApiKey
from app.services.scoring import prompts
from app.services.volcengine import ark
from app.services.volcengine.resolver import resolve_ark_credentials

logger = logging.getLogger(__name__)

SCORE_MODEL_DEFAULT = "doubao-seed-2-1-turbo-260628"
FEEDBACK_MODEL_DEFAULT = "doubao-seed-2-1-pro-260628"

DIMENSION_KEYS = ("fluency", "lexical", "grammar", "pronunciation")
ISSUE_TYPES = ("grammar", "vocab", "fluency", "pronunciation")
SEVERITIES = ("minor", "moderate", "major")


def clamp_band(value, low: float = 3.0, high: float = 9.0) -> float:
    """钳制到 [low, high] 并四舍五入到 0.5 步长（与引擎融合口径一致）。非法值返回 low。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return low
    num = max(low, min(num, high))
    return round(int(num * 2 + 0.5) / 2, 1)


def _extract_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def _user_model(db: AsyncSession, user: User) -> str | None:
    row = await db.scalar(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id, UserApiKey.service_type == "llm"
        )
    )
    model = (row.config or {}).get("model") if row else None
    return str(model) if model else None


async def _ask_llm(
    user: User,
    db: AsyncSession,
    system: str,
    user_content: str,
    *,
    model: str,
    max_tokens: int,
    timeout: float,
) -> dict | None:
    api_key, _source = await resolve_ark_credentials(user, db)
    if api_key is None:
        logger.warning("无可用 LLM Key，评分降级")
        return None
    try:
        result = await ark.chat_completions(
            api_key,
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
            timeout=timeout,
            # seed 系模型默认深度思考，思考 token 不受 max_tokens 限制，
            # 评分类小 JSON 任务会因长思考超时（2026-08 实测：开启时 >30s，
            # 关闭后 ~3s），故评分链路一律禁用
            thinking={"type": "disabled"},
        )
        content = result["choices"][0]["message"]["content"]
    except (ark.ArkError, KeyError, IndexError, TypeError) as exc:
        logger.warning("评分 LLM 调用失败（%s）：%s", model, exc)
        return None
    return _extract_json(content)


async def score_dimensions(
    user: User, db: AsyncSession, *, user_content: str
) -> tuple[dict | None, str]:
    """快速四维打分：输出仅 4 个数字（今日实测 seed-2.1 生成约 12 tok/s，
    大 JSON 输出无法在 10s 预算内完成，故深度内容拆到 deep_analysis）。

    返回 ({scores: {...}}, 实际使用的模型)；失败返回 (None, model)。"""
    model = await _user_model(db, user) or SCORE_MODEL_DEFAULT
    data = await _ask_llm(
        user, db, prompts.SCORE_SYSTEM, user_content,
        model=model, max_tokens=120, timeout=25,
    )
    if data is None:
        return None, model
    scores = {key: clamp_band(data.get(key)) for key in DIMENSION_KEYS}
    return {"scores": scores}, model


def _sanitize_turns(raw_turns) -> list[dict]:
    """逐句分析容错：字段名/枚举值不合法的条目就地修正或丢弃。"""
    turns_out: list[dict] = []
    if not isinstance(raw_turns, list):
        return turns_out
    for t in raw_turns:
        if not isinstance(t, dict):
            continue
        try:
            seq = int(t.get("seq", 0))
        except (TypeError, ValueError):
            continue
        sentences = []
        for s in t.get("sentences") or []:
            if not isinstance(s, dict) or not str(s.get("text", "")).strip():
                continue
            issues = []
            for issue in s.get("issues") or []:
                if not isinstance(issue, dict):
                    continue
                itype = str(issue.get("type", ""))
                if itype not in ISSUE_TYPES:
                    itype = "vocab" if "vocab" in itype or "word" in itype else "grammar"
                severity = str(issue.get("severity", ""))
                if severity not in SEVERITIES:
                    severity = "moderate"
                issues.append(
                    {
                        "type": itype,
                        "severity": severity,
                        "explanation_zh": str(issue.get("explanation_zh", ""))[:300],
                        "suggestion": str(issue.get("suggestion", ""))[:300],
                    }
                )
            sentences.append({"text": str(s.get("text", ""))[:500], "issues": issues})
        turns_out.append({"seq": seq, "sentences": sentences})
    return turns_out


def _parse_feedback(data: dict) -> dict:
    def _str_list(value, limit: int = 6) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()][:limit]

    upgrades = []
    for u in data.get("expression_upgrades") or []:
        if not isinstance(u, dict):
            continue
        original, upgraded = str(u.get("original", "")).strip(), str(u.get("upgraded", "")).strip()
        if original and upgraded:
            upgrades.append(
                {"original": original[:200], "upgraded": upgraded[:300],
                 "note_zh": str(u.get("note_zh", ""))[:200]}
            )

    return {
        "overall_comment_zh": str(data.get("overall_comment_zh", "")).strip()[:1000],
        "strengths": _str_list(data.get("strengths")),
        "improvements": _str_list(data.get("improvements")),
        "expression_upgrades": upgrades[:5],
    }


async def deep_analysis(
    user: User, db: AsyncSession, *, user_content: str
) -> tuple[dict | None, str]:
    """深度分析（无 10s 约束，后台补齐）：逐句分析 + 中文反馈一次产出。

    返回 ({turns, feedback}, model)；失败返回 (None, model)。"""
    model = await _user_model(db, user) or FEEDBACK_MODEL_DEFAULT
    data = await _ask_llm(
        user, db, prompts.DEEP_ANALYSIS_SYSTEM, user_content,
        model=model, max_tokens=4000, timeout=170,
    )
    if data is None:
        return None, model
    feedback = _parse_feedback(data)
    has_sentences = any(t.get("sentences") for t in _sanitize_turns(data.get("turns")))
    if not feedback["overall_comment_zh"] and not has_sentences:
        return None, model
    return {"turns": _sanitize_turns(data.get("turns")), "feedback": feedback}, model
