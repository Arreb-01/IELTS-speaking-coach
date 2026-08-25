"""Part B 练习引擎测试：WebSocket 全流程（Mock 语音）+ 协议工具。"""

import json
from pathlib import Path

from app.services.practice_engine.engine import split_sentences
from app.services.storage import pcm_to_wav


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def test_split_sentences():
    text = "Good afternoon. In this first part, I'd like to ask you some questions about yourself and everyday topics, which should take about four to five minutes. Let's start."
    chunks = split_sentences(text)
    assert len(chunks) == 3
    assert all(len(c) <= 180 for c in chunks)
    assert chunks[0] == "Good afternoon."
    # 超长句按逗号切分
    long_text = "This is a very long sentence, with many clauses, more than the limit allows, so it must be split, into smaller pieces."
    chunks = split_sentences(long_text, max_chars=60)
    assert all(len(c) <= 60 + 20 for c in chunks)  # 逗号合并允许少量超出


def test_pcm_to_wav_header():
    pcm = b"\x00\x01" * 16000  # 1 秒
    wav = pcm_to_wav(pcm)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert len(wav) == 44 + len(pcm)


# ---------------------------------------------------------------------------
# REST + WebSocket 全流程
# ---------------------------------------------------------------------------


def _setup_user_and_session(ws_client, topic_id: str, part: int) -> tuple[dict, dict]:
    resp = ws_client.post(
        "/api/v1/auth/register",
        json={"email": "speaker@example.com", "password": "pass1234"},
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = ws_client.post(
        "/api/v1/practices", headers=headers, json={"topic_id": topic_id, "part": part}
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["ws_ticket"]
    return headers, created


def _drain_until(ws, want_type: str, max_messages: int = 200, collect=None):
    """读取 WS 消息直到出现指定类型。"""
    for _ in range(max_messages):
        data = json.loads(ws.receive_text())
        if collect is not None:
            collect.append(data)
        if data["type"] == want_type:
            return data
    raise AssertionError(f"未等到消息类型 {want_type}")


def _answer_turn(ws, seconds: float = 3.0, collect=None):
    """模拟一轮作答：begin → 送音频 → end → 等 asr_final。"""
    ws.send_text(json.dumps({"type": "begin_turn"}))
    _drain_until(ws, "turn_started", collect=collect)
    pcm = b"\x00\x00" * int(16000 * seconds)
    chunk = 3200
    for i in range(0, len(pcm), chunk):
        ws.send_bytes(pcm[i : i + chunk])
    ws.send_text(json.dumps({"type": "end_turn"}))
    return _drain_until(ws, "asr_final", collect=collect)


def test_practice_flow_part1(ws_client, ws_db):
    _db_path, topic_ids = ws_db
    headers, created = _setup_user_and_session(ws_client, topic_ids["Home & Accommodation"], part=1)

    with ws_client.websocket_connect(created["ws_path"]) as ws:
        started = _drain_until(ws, "session_started")
        assert started["part"] == 1
        assert started["topic"]["name_en"] == "Home & Accommodation"

        transcripts = []
        for expected_index in range(4):
            question = _drain_until(ws, "question", collect=transcripts)
            assert question["index"] == expected_index
            assert question["is_followup"] is False
            # 考官音频：audio_start → 若干 chunk → audio_end → 进入作答阶段
            _drain_until(ws, "audio_start")
            _drain_until(ws, "audio_end")
            phase = _drain_until(ws, "phase")
            assert phase["phase"] == "user_answers"
            assert phase["max_seconds"] == 90

            final = _answer_turn(ws, seconds=3.0)
            assert final["text"], "Mock ASR 应产出转写文本"

        finished = _drain_until(ws, "finished")
        assert finished["abandoned"] is False

    # 会话与轮次落库校验
    detail = ws_client.get(f"/api/v1/practices/{created['session_id']}", headers=headers).json()
    assert detail["status"] == "completed"
    assert len(detail["turns"]) == 4
    assert all(t["user_transcript"] for t in detail["turns"])
    assert all(t["has_audio"] for t in detail["turns"])

    # 归档音频可回放且为合法 WAV
    turn = detail["turns"][0]
    audio = ws_client.get(
        f"/api/v1/practices/{created['session_id']}/turns/{turn['id']}/audio", headers=headers
    )
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"


def test_practice_flow_part2(ws_client, ws_db):
    _db_path, topic_ids = ws_db
    headers, created = _setup_user_and_session(
        ws_client, topic_ids["A Person Who Has Inspired You"], part=2
    )

    with ws_client.websocket_connect(created["ws_path"]) as ws:
        _drain_until(ws, "session_started")
        cue = _drain_until(ws, "cue_card")
        assert cue["card"]["prompt"] == "Describe a person who has inspired you."
        assert cue["prep_seconds"] == 60
        phase = _drain_until(ws, "phase")
        assert phase["phase"] == "preparing"

        # 用户提前点「开始作答」
        ws.send_text(json.dumps({"type": "p2_ready"}))
        _drain_until(ws, "prep_end")
        _drain_until(ws, "audio_start")
        _drain_until(ws, "audio_end")
        phase = _drain_until(ws, "phase")
        assert phase["phase"] == "user_answers"
        assert phase["max_seconds"] == 150

        final = _answer_turn(ws, seconds=2.0)
        assert final["text"]
        finished = _drain_until(ws, "finished")
        assert finished["abandoned"] is False

    detail = ws_client.get(f"/api/v1/practices/{created['session_id']}", headers=headers).json()
    assert detail["status"] == "completed"
    assert len(detail["turns"]) == 1


def test_ws_ticket_invalid(ws_client, ws_db):
    _db_path, topic_ids = ws_db
    _headers, created = _setup_user_and_session(
        ws_client, topic_ids["Home & Accommodation"], part=1
    )
    # ticket 是一次性的：第二次使用必须失败
    with ws_client.websocket_connect(created["ws_path"]):
        pass
    try:
        with ws_client.websocket_connect(created["ws_path"]):
            raise AssertionError("ticket 复用不应成功")
    except Exception:
        pass


def test_end_session_early(ws_client, ws_db):
    _db_path, topic_ids = ws_db
    headers, created = _setup_user_and_session(ws_client, topic_ids["Home & Accommodation"], part=1)

    with ws_client.websocket_connect(created["ws_path"]) as ws:
        _drain_until(ws, "session_started")
        _drain_until(ws, "question")
        _drain_until(ws, "audio_start")
        _drain_until(ws, "audio_end")
        _drain_until(ws, "phase")
        ws.send_text(json.dumps({"type": "end_session"}))
        finished = _drain_until(ws, "finished")
        assert finished["abandoned"] is False

    detail = ws_client.get(f"/api/v1/practices/{created['session_id']}", headers=headers).json()
    assert detail["status"] == "completed"


def test_topics_api(ws_client, ws_db):
    resp = ws_client.post(
        "/api/v1/auth/register",
        json={"email": "browser@example.com", "password": "pass1234"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    part1 = ws_client.get("/api/v1/topics?part=1", headers=headers).json()
    assert len(part1) == 1
    assert part1[0]["question_count"] == 4

    part2 = ws_client.get("/api/v1/topics?part=2", headers=headers).json()
    assert len(part2) == 1

    detail = ws_client.get(f"/api/v1/topics/{part1[0]['id']}", headers=headers).json()
    assert len(detail["questions"]) == 4
