"""练习会话引擎：驱动一次 Part 1/2/3 语音练习的完整流程。

职责：
- 维护 WS 连接与阶段状态机（preparing / examiner_asks / user_answers / finished）
- 每轮作答：ASR 会话生命周期 + PCM 归档 + 轮次落库
- 考官台词：按句切分流式 TTS，音频块实时下推
- 考官决策：追问判断（LLM）、Part 3 出题（LLM，种子题兜底）
- 计时上限、暂停/重来、断线重连（引擎实例在注册表中保活 5 分钟）

设计约束：strict=True（模考，Part F 使用）时拒绝暂停与重来。
"""

import asyncio
import base64
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.base import async_session_factory
from app.db.models import PracticeSession, PracticeTurn, Question, Topic, User
from app.services.examiner import examiner as examiner_svc
from app.services.examiner import prompts
from app.services.practice_engine import constants as C
from app.services.storage import StorageService
from app.services.volcengine import speech
from app.services.volcengine.asr import AsrError

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str, max_chars: int = 180) -> list[str]:
    """按句切分考官台词；超长句按逗号再切，控制单次 TTS 延迟。"""
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    result: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            result.append(sentence)
            continue
        buf = ""
        for part in [p.strip() for p in sentence.split(", ") if p.strip()]:
            candidate = f"{buf}, {part}" if buf else part
            if len(candidate) > max_chars and buf:
                result.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            result.append(buf)
    return result or [text]


class PracticeEngine:
    """一个练习会话对应一个引擎实例（断线后保留，重连续用）。"""

    def __init__(
        self,
        *,
        user: User,
        session: PracticeSession,
        topic: Topic | None,
        questions: list[Question],
    ) -> None:
        self.user = user
        self.session = session
        self.topic = topic
        self.questions = questions
        self.strict = session.mode == "mock"

        self.phase = "idle"
        self.ws: WebSocket | None = None
        self._send_lock = asyncio.Lock()
        self._closed = False

        self.accent = session.accent
        self.speed = session.speed

        self._turn_seq = 0
        self._current_question: str | None = None
        self._current_is_followup = False
        self._current_turn: PracticeTurn | None = None
        self._asr = None
        self._storage = StorageService(session.id)
        self._session_audio_bytes = 0

        self._turn_started_at: float | None = None
        self._watchdog: asyncio.Task | None = None
        self._silence_prompted = False
        self._paused = False
        self._pause_started_at: float | None = None
        self._pause_total = 0.0

        # Part 1 游标：已问的正式题数（追问不计）
        self._p1_index = 0
        # Part 3 状态
        self._p3_seeds = [q.content_en for q in questions if q.part == 3]
        self._p3_asked: list[str] = []
        self._p3_answers: list[str] = []
        self._p3_index = 0

        self.last_activity = time.monotonic()

    # ------------------------------------------------------------------
    # 消息发送
    # ------------------------------------------------------------------

    async def send(self, payload: dict[str, Any]) -> None:
        if self.ws is None or self._closed:
            return
        async with self._send_lock:
            try:
                await self.ws.send_json(payload)
            except Exception:
                logger.debug("发送失败（连接已断开）：%s", payload.get("type"))

    async def _send_audio_chunk(self, data: bytes) -> None:
        await self.send({"type": "audio_chunk", "data": base64.b64encode(data).decode("ascii")})

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def run(self, websocket: WebSocket) -> None:
        self.ws = websocket
        await self.send(
            {
                "type": "session_started",
                "session_id": str(self.session.id),
                "part": self.session.part,
                "mode": self.session.mode,
                "topic": (
                    {
                        "id": str(self.topic.id),
                        "name_en": self.topic.name_en,
                        "name_zh": self.topic.name_zh,
                    }
                    if self.topic
                    else None
                ),
            }
        )
        try:
            await self._start_part_flow()
            await self._pump()
        finally:
            await self._teardown()

    async def _pump(self) -> None:
        """接收并分发客户端消息，直到连接关闭或会话结束。"""
        while not self._closed:
            self.last_activity = time.monotonic()
            try:
                message = await self.ws.receive()
            except Exception:
                # 连接断开：保留状态等待重连（注册表负责超时清理）
                self.ws = None
                return
            if message["type"] == "websocket.disconnect":
                self.ws = None
                return
            if message.get("text") is not None:
                await self._handle_json(_safe_json(message["text"]))
            elif message.get("bytes") is not None:
                await self._handle_audio(message["bytes"])

    # ------------------------------------------------------------------
    # 客户端消息处理
    # ------------------------------------------------------------------

    async def _handle_json(self, data: dict[str, Any]) -> None:
        msg_type = data.get("type")
        if msg_type == "begin_turn":
            await self._begin_turn()
        elif msg_type == "end_turn":
            await self._end_turn(speech_events=data.get("speech_events") or [])
        elif msg_type == "silence":
            await self._handle_silence()
        elif msg_type == "pause":
            await self._pause()
        elif msg_type == "resume":
            await self._resume()
        elif msg_type == "retry":
            await self._retry()
        elif msg_type == "end_session":
            await self._finish(abandon=False)
        elif msg_type == "p2_ready":
            await self._start_p2_speaking()
        elif msg_type == "settings":
            accent = data.get("accent")
            speed = data.get("speed")
            if accent in C.ACCENTS:
                self.accent = accent
            if speed in C.SPEEDS:
                self.speed = speed
            await self.send({"type": "settings_updated", "accent": self.accent, "speed": self.speed})
        elif msg_type == "ping":
            await self.send({"type": "pong"})

    async def _handle_audio(self, pcm: bytes) -> None:
        if self.phase != C.PHASE_USER_ANSWERS or self._paused or self._asr is None:
            return
        if self._storage.size >= C.MAX_TURN_AUDIO_BYTES:
            await self._end_turn(speech_events=[])
            return
        if self._session_audio_bytes >= C.MAX_SESSION_AUDIO_BYTES:
            await self.send({"type": "error", "code": "session_audio_limit",
                             "message": "会话音频量已达上限，请结束练习"})
            await self._finish(abandon=False)
            return
        self._storage.feed(pcm)
        self._session_audio_bytes += len(pcm)
        try:
            await self._asr.feed(pcm)
        except AsrError as exc:
            await self.send({"type": "error", "code": "asr_error", "message": f"语音识别中断：{exc}"})
            await self._finish(abandon=False)

    # ------------------------------------------------------------------
    # 各 Part 流程
    # ------------------------------------------------------------------

    async def _start_part_flow(self) -> None:
        part = self.session.part
        if part == 1:
            await self._opening(1)
            await self._ask_next_part1()
        elif part == 2:
            await self._start_part2()
        elif part == 3:
            await self._opening(3)
            await self._ask_next_part3()

    async def _opening(self, part: int) -> None:
        template = prompts.OPENING_LINES[part]
        line = template.format(topic=self.topic.name_en if self.topic else "everyday topics")
        await self._speak(line)

    def _p1_questions(self) -> list[str]:
        return [q.content_en for q in self.questions if q.part == 1][: C.PART1_QUESTION_COUNT]

    async def _ask_next_part1(self) -> None:
        questions = self._p1_questions()
        if self._p1_index >= len(questions):
            await self._speak(prompts.CLOSING_LINE)
            await self._finish(abandon=False)
            return
        await self._ask_question(
            questions[self._p1_index], index=self._p1_index, total=len(questions)
        )
        self._p1_index += 1

    async def _start_part2(self) -> None:
        question = next((q for q in self.questions if q.part == 2), None)
        cue = question.cue_card if question and question.cue_card else None
        if cue is None:
            await self.send({"type": "error", "code": "no_cue_card", "message": "该话题缺少 Cue Card"})
            await self._finish(abandon=True)
            return
        await self._opening(2)
        await self.send({"type": "cue_card", "card": cue, "prep_seconds": C.PART2_PREP_SECONDS})
        await self._set_phase(C.PHASE_PREPARING, extra={"prep_seconds": C.PART2_PREP_SECONDS})
        self._current_question = question.content_en
        self._watchdog = asyncio.create_task(self._prep_timer())

    async def _prep_timer(self) -> None:
        try:
            await asyncio.sleep(C.PART2_PREP_SECONDS)
        except asyncio.CancelledError:
            return
        if self.phase == C.PHASE_PREPARING:
            await self._start_p2_speaking()

    async def _start_p2_speaking(self) -> None:
        if self.phase != C.PHASE_PREPARING:
            return
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        await self.send({"type": "prep_end"})
        await self._speak(prompts.P2_START_LINE)
        await self._enter_user_answers()

    async def _ask_next_part3(self) -> None:
        if self._p3_index >= C.PART3_QUESTION_COUNT:
            await self._speak(prompts.CLOSING_LINE)
            await self._finish(abandon=False)
            return
        depth = C.PART3_DEPTH_PLAN[min(self._p3_index, len(C.PART3_DEPTH_PLAN) - 1)]
        question = await self._generate_p3_question(depth)
        self._p3_asked.append(question)
        await self._ask_question(question, index=self._p3_index, total=C.PART3_QUESTION_COUNT)
        self._p3_index += 1

    async def _generate_p3_question(self, depth: int) -> str:
        async with async_session_factory() as db:
            user = await db.get(User, self.user.id)
            question = await examiner_svc.generate_part3_question(
                user,
                db,
                topic_name=self.topic.name_en if self.topic else "the topic",
                seed_questions=self._p3_seeds,
                depth_level=depth,
                recent_answers=self._p3_answers,
                asked_questions=self._p3_asked,
            )
        if question:
            return question
        # LLM 不可用：按序使用种子题兜底
        unused = [q for q in self._p3_seeds if q not in self._p3_asked]
        if unused:
            return unused[0]
        return (
            random.choice(self._p3_seeds)
            if self._p3_seeds
            else "What do you think about this topic in general?"
        )

    async def _ask_question(
        self, text: str, *, index: int, total: int, is_followup: bool = False
    ) -> None:
        self._current_question = text
        self._current_is_followup = is_followup
        await self.send(
            {"type": "question", "text": text, "index": index, "total": total, "is_followup": is_followup}
        )
        await self._speak(text)
        await self._enter_user_answers()

    # ------------------------------------------------------------------
    # 轮次生命周期
    # ------------------------------------------------------------------

    async def _enter_user_answers(self) -> None:
        await self._set_phase(
            C.PHASE_USER_ANSWERS,
            extra={"max_seconds": C.TURN_MAX_SECONDS[self.session.part]},
        )

    async def _begin_turn(self) -> None:
        if self.phase != C.PHASE_USER_ANSWERS or self._asr is not None or self._paused:
            return
        self._turn_seq += 1
        self._current_turn = PracticeTurn(
            session_id=self.session.id,
            seq=self._turn_seq,
            question_text=self._current_question,
            is_followup=self._current_is_followup,
            started_at=datetime.now(timezone.utc),
        )
        async with async_session_factory() as db:
            db.add(self._current_turn)
            await db.commit()
            await db.refresh(self._current_turn)

        self._storage.reset()
        self._silence_prompted = False
        self._turn_started_at = time.monotonic()
        self._pause_total = 0.0

        try:
            await self._create_asr()
        except AsrError as exc:
            await self.send({"type": "error", "code": "asr_error", "message": f"语音识别启动失败：{exc}"})
            await self._finish(abandon=False)
            return

        await self.send({"type": "turn_started", "seq": self._turn_seq})
        self._watchdog = asyncio.create_task(
            self._turn_watchdog(C.TURN_MAX_SECONDS[self.session.part])
        )

    async def _create_asr(self) -> None:
        async with async_session_factory() as db:
            user = await db.get(User, self.user.id)
            credentials = None
            if not get_settings().volc_mock:
                credentials = await speech.resolve_asr_credentials(user, db)
                if credentials is None:
                    await self.send(
                        {"type": "error", "code": "asr_no_credentials",
                         "message": "未配置语音识别凭据，转写使用模拟数据；可在「API 设置」页配置火山引擎凭据。"}
                    )
            self._asr = speech.create_asr_session(
                credentials, on_partial=self._on_asr_partial, uid=str(self.user.id)
            )
        await self._asr.start()

    async def _on_asr_partial(self, text: str) -> None:
        await self.send({"type": "asr_partial", "text": text})

    async def _turn_watchdog(self, max_seconds: float) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                if self._paused or self._turn_started_at is None:
                    continue
                elapsed = time.monotonic() - self._turn_started_at - self._pause_total
                if elapsed >= max_seconds:
                    await self.send({"type": "time_up", "max_seconds": max_seconds})
                    await self._end_turn(speech_events=[])
                    return
        except asyncio.CancelledError:
            return

    async def _end_turn(self, *, speech_events: list[dict[str, Any]]) -> None:
        if self.phase != C.PHASE_USER_ANSWERS or self._current_turn is None:
            return
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None

        turn = self._current_turn
        asr = self._asr
        self._asr = None
        self._current_turn = None
        self._turn_started_at = None

        transcript = ""
        try:
            result = await asr.finish() if asr is not None else None
            transcript = (result.text if result else "").strip()
        except AsrError as exc:
            logger.warning("ASR finish 失败：%s", exc)

        turn.user_transcript = transcript or None
        turn.ended_at = datetime.now(timezone.utc)
        if speech_events:
            turn.speech_events = speech_events
        turn.audio_path = self._storage.flush_to_wav(turn.id)

        async with async_session_factory() as db:
            db_turn = await db.get(PracticeTurn, turn.id)
            if db_turn is not None:
                db_turn.user_transcript = turn.user_transcript
                db_turn.ended_at = turn.ended_at
                db_turn.speech_events = turn.speech_events
                db_turn.audio_path = turn.audio_path
                await db.commit()

        await self.send(
            {"type": "asr_final", "text": transcript, "seq": turn.seq, "turn_id": str(turn.id)}
        )

        # Part 3 累积用户回答（供后续出题锚定）
        if self.session.part == 3 and transcript:
            self._p3_answers.append(transcript)

        # 考官决策：追问 or 下一题（回答过短不追问）
        if transcript and len(transcript.split()) >= 3:
            async with async_session_factory() as db:
                user = await db.get(User, self.user.id)
                followup = await examiner_svc.decide_followup(
                    user, db, part=self.session.part,
                    question=self._current_question or "", answer=transcript,
                )
            if followup:
                if self.session.part == 1:
                    await self._ask_question(
                        followup, index=max(self._p1_index - 1, 0),
                        total=len(self._p1_questions()), is_followup=True,
                    )
                else:
                    await self._ask_question(
                        followup, index=max(self._p3_index - 1, 0),
                        total=C.PART3_QUESTION_COUNT, is_followup=True,
                    )
                return

        if self.session.part == 1:
            await self._ask_next_part1()
        elif self.session.part == 3:
            await self._ask_next_part3()
        else:
            await self._speak(prompts.CLOSING_LINE)
            await self._finish(abandon=False)

    async def _handle_silence(self) -> None:
        if self.phase != C.PHASE_USER_ANSWERS or self._silence_prompted:
            return
        self._silence_prompted = True
        await self.send({"type": "silence_prompt"})
        # 不切换阶段：用户仍处于作答中，提示音叠加播放
        await self._speak(prompts.SILENCE_PROMPT, set_phase=False)

    # ------------------------------------------------------------------
    # 暂停 / 重来 / 结束
    # ------------------------------------------------------------------

    async def _pause(self) -> None:
        if self.strict:
            await self.send({"type": "error", "code": "strict_mode", "message": "模考模式不支持暂停"})
            return
        if self.phase not in (C.PHASE_USER_ANSWERS, C.PHASE_PREPARING) or self._paused:
            return
        self._paused = True
        self._pause_started_at = time.monotonic()
        await self.send({"type": "paused"})

    async def _resume(self) -> None:
        if not self._paused:
            return
        if self._pause_started_at is not None:
            self._pause_total += time.monotonic() - self._pause_started_at
        self._pause_started_at = None
        self._paused = False
        await self.send({"type": "resumed"})

    async def _retry(self) -> None:
        if self.strict:
            await self.send({"type": "error", "code": "strict_mode", "message": "模考模式不支持重来"})
            return
        if self.phase != C.PHASE_USER_ANSWERS:
            return
        question = self._current_question
        asr = self._asr
        self._asr = None
        self._current_turn = None
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        if asr is not None:
            await asr.close()
        self._storage.reset()
        await self.send({"type": "turn_reset"})
        await self._speak(question or "Let's try that again.")
        await self._enter_user_answers()

    async def _finish(self, *, abandon: bool) -> None:
        if self._closed:
            return
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        if self._asr is not None:
            await self._asr.close()
            self._asr = None
        async with async_session_factory() as db:
            db_session = await db.get(PracticeSession, self.session.id)
            if db_session is not None:
                db_session.status = "abandoned" if abandon else "completed"
                db_session.ended_at = datetime.now(timezone.utc)
                await db.commit()
        self.session.status = "abandoned" if abandon else "completed"
        self.phase = C.PHASE_FINISHED
        report_available = False
        if not abandon:
            # 正常结束：自动触发评分流水线（后台任务），前端收到提示后跳报告页轮询
            try:
                from app.services.scoring import engine as scoring_engine

                await scoring_engine.ensure_report(self.session.id, self.user.id)
                asyncio.create_task(scoring_engine.run_scoring(self.session.id))
                report_available = True
            except Exception:
                logger.exception("触发评分失败（不影响练习结束）：%s", self.session.id)
        await self.send(
            {
                "type": "finished",
                "session_id": str(self.session.id),
                "abandoned": abandon,
                "report_available": report_available,
            }
        )
        self._closed = True
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass

    async def _teardown(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        if self._asr is not None:
            await self._asr.close()
            self._asr = None

    # ------------------------------------------------------------------
    # 考官台词：句级切分流式 TTS
    # ------------------------------------------------------------------

    async def _speak(self, text: str, *, set_phase: bool = True) -> None:
        if set_phase:
            await self._set_phase(C.PHASE_EXAMINER_ASKS)
        await self.send({"type": "audio_start", "encoding": "pcm", "rate": 24000, "text": text})
        for i, chunk in enumerate(split_sentences(text)):
            try:
                async with async_session_factory() as db:
                    user = await db.get(User, self.user.id)
                    await speech.synthesize_tts_stream(
                        chunk,
                        user,
                        db,
                        voice_key=self.accent,
                        speed_key=self.speed,
                        on_audio=self._send_audio_chunk,
                    )
            except Exception as exc:
                logger.warning("TTS 合成失败（第 %d 句）：%s", i + 1, exc)
                await self.send(
                    {"type": "error", "code": "tts_error",
                     "message": "语音合成暂时不可用，考官将以文字形式展示"}
                )
                break
        await self.send({"type": "audio_end"})

    async def _set_phase(self, phase: str, *, extra: dict[str, Any] | None = None) -> None:
        self.phase = phase
        payload: dict[str, Any] = {"type": "phase", "phase": phase}
        if extra:
            payload.update(extra)
        await self.send(payload)


def _safe_json(raw: str) -> dict[str, Any]:
    import json

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}
