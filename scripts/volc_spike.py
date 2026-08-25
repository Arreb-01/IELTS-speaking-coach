"""火山引擎语音协议验证 spike。

用途：拿到真实凭据后验证 ASR / TTS 协议实现是否与服务端一致。
用法（在 backend 目录下）：
    .venv/Scripts/python ../scripts/volc_spike.py asr --appid XXX --token YYY [--resource-id volc.seedasr.sauc.duration]
    .venv/Scripts/python ../scripts/volc_spike.py tts --appid XXX --token YYY [--voice en_female_anna]

ASR 测试：读取 scripts/spike_sample.wav（16k/16bit/单声道），流式送入并打印识别结果。
TTS 测试：合成 "Hello, this is a test."，写出 scripts/spike_tts_out.mp3。
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.volcengine.asr import AsrCredentials, VolcAsrSession  # noqa: E402
from app.services.volcengine.protocol import build_audio_frame  # noqa: E402
from app.services.volcengine.tts import TtsCredentials, synthesize_http, synthesize_stream  # noqa: E402


async def spike_asr(args: argparse.Namespace) -> None:
    wav_path = Path(__file__).parent / "spike_sample.wav"
    if not wav_path.exists():
        print(f"[!] 缺少测试音频 {wav_path}")
        print("    可用任意 16kHz/16bit/单声道 WAV；或用 Python 生成静音文件验证鉴权。")
        generate_silent_wav(wav_path)

    pcm = wav_path.read_bytes()[44:]  # 跳过 WAV 头（44 字节标准头）
    print(f"[*] 加载音频 {len(pcm)} 字节（约 {len(pcm) / 32000:.1f} 秒）")

    credentials = AsrCredentials(args.appid, args.token, args.resource_id)
    partials: list[str] = []

    async def on_partial(text: str) -> None:
        partials.append(text)
        print(f"[partial] {text}")

    session = VolcAsrSession(credentials, on_partial=on_partial)
    await session.start()
    print("[*] ASR 连接与配置下发成功（鉴权通过）")

    # 每 100ms 送 3200 字节（模拟实时流）
    chunk_size = 3200
    for i in range(0, len(pcm), chunk_size):
        await session.feed(pcm[i : i + chunk_size])
        await asyncio.sleep(0.1)
    result = await session.finish()
    print(f"[*] 最终识别：{result.text}")
    print(f"[*] 时长：{result.duration_ms}ms，utterances={len(result.utterances)}")
    print("[✓] ASR spike 通过" if result.text or partials else "[!] 未见识别文本，检查音频内容")


def generate_silent_wav(path: Path, seconds: float = 2.0) -> None:
    import struct

    sample_rate = 16000
    n = int(sample_rate * seconds)
    data = b"\x00\x00" * n
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ",
        16, 1, 1, sample_rate, sample_rate * 2, 2, 16, b"data", len(data),
    )
    path.write_bytes(header + data)
    print(f"[*] 已生成 {seconds}s 静音音频（仅可验证鉴权，无识别文本）")


async def spike_tts(args: argparse.Namespace) -> None:
    credentials = TtsCredentials(args.appid, args.token, args.resource_id)
    out = Path(__file__).parent / "spike_tts_out.mp3"

    print("[*] 测试 HTTP 单次合成 …")
    try:
        audio = await synthesize_http(
            "Hello, this is a test.", credentials, voice_key=args.voice
        )
        out.write_bytes(audio)
        print(f"[✓] HTTP 合成成功，{len(audio)} 字节 → {out}")
    except Exception as exc:
        print(f"[!] HTTP 合成失败：{exc}")

    print("[*] 测试 WS 流式合成 …")
    chunks = []

    async def on_audio(data: bytes) -> None:
        chunks.append(data)

    try:
        audio = await synthesize_stream(
            "Hello, this is a streaming test.",
            credentials,
            voice_key=args.voice,
            on_audio=on_audio,
        )
        print(f"[✓] WS 流式合成成功，总 {len(audio)} 字节，分 {len(chunks)} 块推送")
    except Exception as exc:
        print(f"[!] WS 流式合成失败：{exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="火山引擎语音协议 spike")
    sub = parser.add_subparsers(dest="service", required=True)

    asr = sub.add_parser("asr")
    asr.add_argument("--appid", required=True)
    asr.add_argument("--token", required=True)
    asr.add_argument("--resource-id", default="volc.seedasr.sauc.duration")

    tts = sub.add_parser("tts")
    tts.add_argument("--appid", required=True)
    tts.add_argument("--token", required=True)
    tts.add_argument("--resource-id", default="volc.megatts.default")
    tts.add_argument("--voice", default="en_female_anna")

    args = parser.parse_args()
    if args.service == "asr":
        asyncio.run(spike_asr(args))
    else:
        asyncio.run(spike_tts(args))


if __name__ == "__main__":
    main()
