# -*- coding: utf-8 -*-
"""PDF 素材 → 中间 JSON 解析管线（Part D M2）。

三份 PDF 的结构规则见 docs/part-d-plan.md 附一（M1 spike 结论）。
产出：
  scripts/parsed/p1.json     P1 话题（题目+范文，question 级）
  scripts/parsed/p2p3.json   P2&3 话题（Cue Card+中文概要+英文范文+P3 问答）
  scripts/parsed/linked.json P2 串联组（一份范文适配多个 Cue Card）
  scripts/parsed/report.md   校验报告（话题/题目计数、缺字段清单）

用法：
  python scripts/parse_pdf.py             # 全量：规则解析 + LLM 兜底（英文名/别名匹配）
  python scripts/parse_pdf.py --skip-llm  # 只跑规则（不联网，name_zh/name_en 留空）
  python scripts/parse_pdf.py --only p1   # 只解析一份（p1 | p2p3 | linked）

解析一次、导入可重复：JSON 是唯一事实源，改解析重跑本脚本即可。
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "2026年5-8月雅思口语素材P123"
OUT_DIR = Path(__file__).resolve().parent / "parsed"

PDFS = {
    "p1": "2026年5-8月雅思口语素材p1.pdf",
    "p2p3": "2026年5-8月雅思口语素材p2和p3.pdf",
    "linked": "2026年5-8月雅思口语素材p2串联版.pdf",
}

# 正文起始页（0 基）：p1 目录+总览占 0-4；p2p3 目录+总览占 0-6；linked 目录占 0-1
BODY_START = {"p1": 5, "p2p3": 7, "linked": 2}

P1_OVERVIEW_PAGE = 4      # p1 标签颜色总览页（0 基）
P1_MUST_COLOR = 0xE00000  # 红=必考
P1_NEW_COLOR = 0x1880E2   # 蓝=新题
PAGE_NO_COLOR = 0x868686  # 页脚页码灰

P23_CATEGORY_PAGES = (5, 6)  # p2p3 总览（人物/事件/事物/地点）
P23_CATEGORIES = {"人物": "person", "事件": "event", "事物": "object", "地点": "place"}

# 串联版每组的固定说明行（前缀匹配清洗）
LINKED_INTRO_PREFIXES = ("同学可以结合", "1.为了", "2.针对", "3.一定注意")

RE_P1_TITLE = re.compile(r"^Part 1\s*(新题|必考题)?\s*[:：]?\s*(.+)$")
RE_P23_TITLE = re.compile(r"^&?\s*Part 2&3\s*(新题)?\s*[:：]?\s*(.+)$")
RE_LINKED_TITLE = re.compile(r"^Part 2串题\s*(新题)?\s*[:：]?\s*(.+)$")
RE_NUMBERED = re.compile(r"^\s*(\d{1,2})\.\s*(.+)$")
RE_EXTRA_MARK = re.compile(r"【([^】]+)】")

logger = logging.getLogger("parse_pdf")


def norm(s: str) -> str:
    """规范化比较键：去所有非字母数字（含 CJK）。"""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s.lower())


def cjk_ratio(text: str) -> float:
    body = text.replace(" ", "")
    if not body:
        return 0.0
    cjk = sum(1 for c in body if "\u4e00" <= c <= "\u9fff")
    return cjk / len(body)


@dataclass
class Line:
    text: str
    size: float
    page: int  # 1 基页码


def iter_lines(doc: pymupdf.Document, start_page: int) -> list[Line]:
    """重建正文行流：过滤页脚页码（9 号灰字），跨 span 拼接整行。"""
    lines: list[Line] = []
    for pno in range(start_page, doc.page_count):
        for block in doc[pno].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                kept = [
                    (s["text"], s["size"], s["color"])
                    for s in line["spans"]
                    if not (s["size"] < 10 and s["color"] == PAGE_NO_COLOR)
                ]
                if not kept:
                    continue
                text = "".join(t for t, _, _ in kept).strip()
                if text:
                    lines.append(Line(text, max(sz for _, sz, _ in kept), pno + 1))
    return lines


def split_numbered_questions(text: str) -> list[tuple[int, str]]:
    """拆同行多问：'1. A? 2. B?' → [(1, 'A?'), (2, 'B?')]；无编号返回空。"""
    parts = re.split(r"(?=\b\d{1,2}\.\s)", text)
    out = []
    for p in parts:
        m = RE_NUMBERED.match(p.strip())
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
    return out


def is_question_line(text: str) -> bool:
    stripped = text.strip()
    return bool(RE_NUMBERED.match(stripped)) and stripped.rstrip().endswith(("?", "？"))


# ---------------------------------------------------------------- p1

def parse_p1(doc: pymupdf.Document, tag_overview: dict[str, list[str]]) -> dict:
    lines = iter_lines(doc, BODY_START["p1"])
    topics: list[dict] = []
    cur_topic = None
    cur_q: dict | None = None

    for ln in lines:
        if ln.size > 15:  # 22 号话题标题
            m = RE_P1_TITLE.match(ln.text)
            if not m:
                continue
            marks = RE_EXTRA_MARK.findall(m.group(2))
            name = RE_EXTRA_MARK.sub("", m.group(2)).strip()
            cur_topic = {
                "name_en": re.sub(r"\s+", " ", name),
                "name_zh": "",
                "tag_title": "new" if m.group(1) else None,
                "note": " ".join(marks),
                "page": ln.page,
                "questions": [],
            }
            topics.append(cur_topic)
            cur_q = None
            continue
        if cur_topic is None:
            continue
        if is_question_line(ln.text):
            no, qtext = RE_NUMBERED.match(ln.text.strip()).groups()
            cur_q = {"no": int(no), "question": qtext, "answer": ""}
            cur_topic["questions"].append(cur_q)
        elif cur_q is not None:
            cur_q["answer"] = (cur_q["answer"] + " " + ln.text).strip()

    # 标签：总览页颜色组优先（must 只能来自红组），标题"新题"兜底。
    # 红/蓝组 span 顺序拼接成整段后做子串匹配（云图 span 有碎片），
    # 只做 话题名 in 组文本 单向匹配，避免短碎片反向误伤。
    must_text = norm(" ".join(tag_overview["must"]))
    new_text = norm(" ".join(tag_overview["new"]))
    for t in topics:
        n = norm(t["name_en"])
        if n and n in must_text:
            t["tag"] = "must"
        elif (n and n in new_text) or t["tag_title"] == "new":
            t["tag"] = "new"
        else:
            t["tag"] = "retained"
        del t["tag_title"]

    return {"topics": topics}


def p1_tag_overview(doc: pymupdf.Document) -> dict[str, list[str]]:
    """p1 第 5 页总览：红组=必考、蓝组=新题（span 碎片原样收集）。"""
    groups: dict[str, list[str]] = {"must": [], "new": []}
    for block in doc[P1_OVERVIEW_PAGE].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                t = s["text"].strip()
                if not t:
                    continue
                if s["color"] == P1_MUST_COLOR:
                    groups["must"].append(t)
                elif s["color"] == P1_NEW_COLOR:
                    groups["new"].append(t)
    return groups


# ---------------------------------------------------------------- p2p3

def parse_p2p3(doc: pymupdf.Document, category_groups: dict[str, str]) -> dict:
    lines = iter_lines(doc, BODY_START["p2p3"])
    topics: list[dict] = []
    cur: dict | None = None
    mode = "cue"  # cue | should_say | summary | sample | p3

    for ln in lines:
        if ln.size > 15:  # 话题标题
            m = RE_P23_TITLE.match(ln.text)
            if not m:
                continue
            marks = RE_EXTRA_MARK.findall(m.group(2))
            cur = {
                "name_zh": RE_EXTRA_MARK.sub("", m.group(2)).strip(),
                "name_en": "",
                "tag": "new" if m.group(1) else "retained",
                "note": " ".join(marks),
                "page": ln.page,
                "cue_prompt": "",
                "you_should_say": [],
                "summary_zh": "",
                "sample_en": "",
                "p3_questions": [],
            }
            topics.append(cur)
            mode = "cue"
            cur_p3 = None
            continue
        if cur is None:
            continue

        text = ln.text.strip()
        if text.startswith("笔记区"):
            mode = "p3"
            cur_p3 = None
            continue

        if mode == "cue":
            if "You should say" in text:
                # 个别话题 Cue 句与 You should say 粘连在同一行（PDF 排版缺陷）
                before, after = text.split("You should say", 1)
                if before.strip():
                    cur["cue_prompt"] = (cur["cue_prompt"] + " " + before.strip()).strip()
                mode = "should_say"
                text = after.strip().lstrip(":：").strip()
                if not text:
                    continue
                # fallthrough：粘连行剩余部分按 should_say 处理
                if cjk_ratio(text) > 0.3:
                    mode = "summary"
                    cur["summary_zh"] = text
                    continue
                cur["you_should_say"].append(text)
            elif text.startswith("Describe "):
                cur["cue_prompt"] = text
            elif cur["cue_prompt"] and cjk_ratio(text) < 0.3:
                # Cue 主题句跨行延续（Describe 后的英文行）
                cur["cue_prompt"] += " " + text
            # 标题后重复的中文话题名行：忽略
        elif mode == "should_say":
            if cjk_ratio(text) > 0.3:
                mode = "summary"
                cur["summary_zh"] = text
            else:
                cur["you_should_say"].append(text)
        elif mode == "summary":
            if cjk_ratio(text) > 0.3:
                cur["summary_zh"] += text
            else:
                mode = "sample"
                cur["sample_en"] = text
        elif mode == "sample":
            if cjk_ratio(text) > 0.3:
                # 范文中的整行中文（罕见）并入概要之后继续
                cur["summary_zh"] += text
            else:
                cur["sample_en"] += " " + text
        elif mode == "p3":
            if text.startswith("Part 2&3"):  # P3 小节标题行
                continue
            m_q = RE_NUMBERED.match(text)
            if m_q and ("?" in text or "？" in text):
                # 问题行：编号开头且行内含问号（问题可能跨行延续，
                # 同行多问拆分；范文叙述体不会以编号+问号开头）
                for no, qtext in split_numbered_questions(text):
                    cur["p3_questions"].append({"no": no, "question": qtext, "answer": ""})
            elif cur["p3_questions"]:
                last = cur["p3_questions"][-1]
                if not last["question"].rstrip().endswith(("?", "？")):
                    # 上一问题尚未完结：本行是问题的跨行延续
                    last["question"] = (last["question"] + " " + text).strip()
                else:
                    last["answer"] = (last["answer"] + " " + text).strip()

    # 分类：总览组文本子串匹配
    for t in topics:
        n = norm(t["name_zh"])
        t["category"] = next(
            (cat for cat, joined in category_groups.items() if n and n in joined), ""
        )
        # 个别话题要点行在 PDF 中重复排版两遍，保序去重
        seen = set()
        t["you_should_say"] = [s for s in t["you_should_say"] if not (s in seen or seen.add(s))]

    return {"topics": topics}


def p23_category_groups(doc: pymupdf.Document) -> dict[str, str]:
    """p2p3 总览页：按 人物/事件/事物/地点 分组标题切分 span 流并拼接。"""
    raw: list[str] = []
    for pno in P23_CATEGORY_PAGES:
        for block in doc[pno].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for s in line["spans"]:
                    t = s["text"].strip()
                    if t and s["size"] > 11:
                        raw.append(t)
    groups: dict[str, str] = {}
    current = None
    for t in raw:
        if t in P23_CATEGORIES:
            current = P23_CATEGORIES[t]
            groups.setdefault(current, "")
        elif current:
            groups[current] += norm(t)
    return groups


# ---------------------------------------------------------------- linked

def parse_linked(doc: pymupdf.Document) -> dict:
    # 重建行流时把同页连续大字号行合并为完整标题（linked 标题固定占 2 行）
    lines = iter_lines(doc, BODY_START["linked"])
    merged: list[Line] = []
    for ln in lines:
        if ln.size > 15 and merged and merged[-1].size > 15 and merged[-1].page == ln.page:
            merged[-1] = Line(merged[-1].text + ln.text, ln.size, ln.page)
        else:
            merged.append(ln)

    groups: list[dict] = []
    cur: dict | None = None
    mode = "summary"
    for ln in merged:
        if ln.size > 15:
            m = RE_LINKED_TITLE.match(ln.text)
            if not m:
                continue
            aliases = [a.strip() for a in m.group(2).split("+") if a.strip()]
            cur = {
                "group_name": " + ".join(aliases),
                "aliases": aliases,
                "tag": "new" if m.group(1) else "retained",
                "page": ln.page,
                "summary_zh": "",
                "sample_en": "",
                "matched": [{"alias": a, "name_zh": None} for a in aliases],
            }
            groups.append(cur)
            mode = "summary"
            continue
        if cur is None:
            continue
        text = ln.text.strip()
        if text.startswith("笔记区"):
            continue  # 组结束（后续行属于笔记区空白）
        if any(text.startswith(p) for p in LINKED_INTRO_PREFIXES):
            continue
        if mode == "summary":
            if cjk_ratio(text) > 0.3:
                cur["summary_zh"] += text
            else:
                mode = "sample"
                cur["sample_en"] = text
        else:
            if cjk_ratio(text) > 0.3:
                cur["summary_zh"] += text  # 范文中夹的整行中文并入概要
            else:
                cur["sample_en"] += " " + text

    return {"groups": groups}


def match_linked_aliases(linked: dict, p2p3: dict) -> tuple[int, int]:
    """规则匹配串联别名 → p2p3 话题：精确 → 双向子串。返回 (matched, total)。"""
    names = [t["name_zh"] for t in p2p3["topics"]]
    name_norms = {norm(n): n for n in names}
    for g in linked["groups"]:
        for item in g["matched"]:
            a = item["alias"]
            an = norm(a)
            hit = name_norms.get(an)
            if hit is None:
                # 别名是话题名的子串（"新法律" ⊂ "想颁布的新法律"）或反之
            # 双向包含取最长命中
                contains = [n for nn, n in name_norms.items() if an and (an in nn or nn in an)]
                if contains:
                    hit = max(contains, key=len)
            item["name_zh"] = hit
    total = sum(len(g["matched"]) for g in linked["groups"])
    matched = sum(1 for g in linked["groups"] for i in g["matched"] if i["name_zh"])
    return matched, total


# ---------------------------------------------------------------- LLM 兜底

async def get_llm_key() -> str | None:
    """脚本无用户上下文：取库内任一 LLM BYOK Key，否则平台默认。"""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.crypto import decrypt_secret
    from app.db.base import async_session_factory
    from app.db.models import UserApiKey

    async with async_session_factory() as db:
        row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == "llm"))
        if row is not None:
            key = decrypt_secret(row.key_encrypted)
            if key:
                return key
    return get_settings().volc_ark_default_api_key


async def ask_llm_json(system: str, user: str, max_tokens: int = 8000) -> dict | None:
    from app.services.volcengine import ark

    key = await get_llm_key()
    if not key:
        logger.warning("无可用 LLM Key，跳过 LLM 兜底")
        return None
    try:
        result = await ark.chat_completions(
            key,
            "doubao-seed-2-1-turbo-260628",
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
            timeout=180,
            thinking={"type": "disabled"},
        )
        content = result["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 — 脚本层兜底，任何失败降级
        logger.warning("LLM 调用失败：%s", exc)
        return None
    m = re.search(r"\{.*\}", content, re.DOTALL) or re.search(r"\[.*\]", content, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def llm_fill_names(p1: dict, p2p3: dict) -> None:
    """中英文名互译：p2p3 中文名→英文名（upsert 键），p1 英文名→中文名。"""
    zh_names = [t["name_zh"] for t in p2p3["topics"]]
    data = await ask_llm_json(
        "你是雅思口语教研编辑。将中文话题名译为简洁的英文话题名"
        "（Title Case，6 词以内，如\"描述一个发小\"→\"A Childhood Friend\"）。"
        '仅输出 JSON 对象 {"中文名": "English Name"}，不要多余文字。',
        json.dumps(zh_names, ensure_ascii=False),
    )
    if isinstance(data, dict):
        for t in p2p3["topics"]:
            t["name_en"] = str(data.get(t["name_zh"], "")).strip() or t["name_en"]
        logger.info("LLM 生成 p2p3 英文名 %d/%d", sum(1 for t in p2p3["topics"] if t["name_en"]), len(zh_names))
    else:
        logger.warning("p2p3 英文名生成失败，name_en 留空（导入时会跳过）")

    en_names = [t["name_en"] for t in p1["topics"]]
    data = await ask_llm_json(
        "你是雅思口语教研编辑。将英文口语话题名译为简洁中文话题名（3-8 字）。"
        '仅输出 JSON 对象 {"English Name": "中文名"}，不要多余文字。',
        json.dumps(en_names, ensure_ascii=False),
    )
    if isinstance(data, dict):
        for t in p1["topics"]:
            t["name_zh"] = str(data.get(t["name_en"], "")).strip() or t["name_zh"]
        logger.info("LLM 生成 p1 中文名 %d/%d", sum(1 for t in p1["topics"] if t["name_zh"]), len(en_names))


async def llm_match_linked(linked: dict, p2p3: dict) -> None:
    """规则未匹配的串联别名交 LLM 对到 p2p3 话题。"""
    names = [t["name_zh"] for t in p2p3["topics"]]
    pending = [
        item
        for g in linked["groups"]
        for item in g["matched"]
        if item["name_zh"] is None
    ]
    if not pending:
        return
    data = await ask_llm_json(
        "你是雅思口语教研编辑。左列是串联题组的别名（缩写），右列是完整话题名。"
        "为每个别名选出对应的完整话题名（语义相同即匹配），没有合理对应填 null。"
        '仅输出 JSON 对象 {"别名": "完整话题名或null"}。',
        "别名列表：" + json.dumps([i["alias"] for i in pending], ensure_ascii=False)
        + "\n完整话题名列表：" + json.dumps(names, ensure_ascii=False),
    )
    if isinstance(data, dict):
        for item in pending:
            v = data.get(item["alias"])
            if isinstance(v, str) and v in names:
                item["name_zh"] = v


# ---------------------------------------------------------------- 校验报告

def build_report(p1: dict, p2p3: dict, linked: dict) -> str:
    r: list[str] = ["# PDF 解析校验报告\n"]

    r.append("## p1\n")
    r.append(f"- 话题数：{len(p1['topics'])}（基线 59，PRD 要求 40+）")
    qs = sum(len(t["questions"]) for t in p1["topics"])
    r.append(f"- 题目数：{qs}")
    tags = {}
    for t in p1["topics"]:
        tags[t["tag"]] = tags.get(t["tag"], 0) + 1
    r.append(f"- 标签分布：{tags}")
    no_answer = [t["name_en"] for t in p1["topics"] for q in t["questions"] if not q["answer"]]
    r.append(f"- 无范文题目：{len(no_answer)}" + (f" {no_answer[:5]}" if no_answer else ""))
    no_zh = [t["name_en"] for t in p1["topics"] if not t["name_zh"]]
    r.append(f"- 缺中文名：{len(no_zh)}" + (f" {no_zh[:5]}" if no_zh else ""))

    r.append("\n## p2p3\n")
    r.append(f"- 话题数：{len(p2p3['topics'])}（基线 77，PRD 要求 50+）")
    r.append(f"- 缺 Cue Card：{[t['name_zh'] for t in p2p3['topics'] if not t['cue_prompt']]}")
    r.append(f"- 缺中文概要：{[t['name_zh'] for t in p2p3['topics'] if not t['summary_zh']]}")
    r.append(f"- 缺英文范文：{[t['name_zh'] for t in p2p3['topics'] if not t['sample_en']]}")
    r.append(f"- 缺英文名：{[t['name_zh'] for t in p2p3['topics'] if not t['name_en']]}")
    no_cat = [t["name_zh"] for t in p2p3["topics"] if not t["category"]]
    r.append(f"- 缺分类：{len(no_cat)} {no_cat}")
    p3_total = sum(len(t["p3_questions"]) for t in p2p3["topics"])
    r.append(f"- P3 问题数：{p3_total}")
    no_p3 = [t["name_zh"] for t in p2p3["topics"] if not t["p3_questions"]]
    r.append(f"- 零 P3 问题话题：{no_p3 or '无'}")
    no_p3_answer = [f"{t['name_zh']}#{q['no']}" for t in p2p3["topics"] for q in t["p3_questions"] if not q["answer"]]
    r.append(f"- P3 无答案：{len(no_p3_answer)} {no_p3_answer[:8]}")

    r.append("\n## linked\n")
    r.append(f"- 串联组数：{len(linked['groups'])}（基线 13，PRD 要求 10+）")
    matched, total = sum(1 for g in linked['groups'] for i in g['matched'] if i['name_zh']), sum(len(g['matched']) for g in linked['groups'])
    r.append(f"- 别名匹配：{matched}/{total}")
    unmatched = [i["alias"] for g in linked["groups"] for i in g["matched"] if not i["name_zh"]]
    r.append(f"- 未匹配别名：{unmatched}")
    r.append(f"- 缺范文组：{[g['group_name'] for g in linked['groups'] if not g['sample_en']]}")
    return "\n".join(r) + "\n"


# ---------------------------------------------------------------- main

async def run(targets: list[str], skip_llm: bool) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p1 = p2p3 = linked = None

    if "p1" in targets:
        with pymupdf.open(PDF_DIR / PDFS["p1"]) as doc:
            p1 = parse_p1(doc, p1_tag_overview(doc))
        (OUT_DIR / "p1.json").write_text(json.dumps(p1, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"p1: {len(p1['topics'])} topics, "
              f"{sum(len(t['questions']) for t in p1['topics'])} questions")

    if "p2p3" in targets:
        with pymupdf.open(PDF_DIR / PDFS["p2p3"]) as doc:
            p2p3 = parse_p2p3(doc, p23_category_groups(doc))
        (OUT_DIR / "p2p3.json").write_text(json.dumps(p2p3, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"p2p3: {len(p2p3['topics'])} topics, "
              f"{sum(len(t['p3_questions']) for t in p2p3['topics'])} p3 questions")

    if "linked" in targets:
        with pymupdf.open(PDF_DIR / PDFS["linked"]) as doc:
            linked = parse_linked(doc)
        if p2p3 is None:
            p2p3 = json.loads((OUT_DIR / "p2p3.json").read_text(encoding="utf-8"))
        match_linked_aliases(linked, p2p3)
        (OUT_DIR / "linked.json").write_text(json.dumps(linked, ensure_ascii=False, indent=1), encoding="utf-8")
        matched = sum(1 for g in linked["groups"] for i in g["matched"] if i["name_zh"])
        total = sum(len(g["matched"]) for g in linked["groups"])
        print(f"linked: {len(linked['groups'])} groups, rule-matched {matched}/{total}")

    if not skip_llm and (p1 or p2p3):
        if p1 is None:
            p1 = json.loads((OUT_DIR / "p1.json").read_text(encoding="utf-8"))
        if p2p3 is None:
            p2p3 = json.loads((OUT_DIR / "p2p3.json").read_text(encoding="utf-8"))
        await llm_fill_names(p1, p2p3)
        (OUT_DIR / "p1.json").write_text(json.dumps(p1, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT_DIR / "p2p3.json").write_text(json.dumps(p2p3, ensure_ascii=False, indent=1), encoding="utf-8")
        if linked is None and (OUT_DIR / "linked.json").exists():
            linked = json.loads((OUT_DIR / "linked.json").read_text(encoding="utf-8"))
        if linked:
            await llm_match_linked(linked, p2p3)
            (OUT_DIR / "linked.json").write_text(json.dumps(linked, ensure_ascii=False, indent=1), encoding="utf-8")

    # 报告读取最新 JSON
    p1 = json.loads((OUT_DIR / "p1.json").read_text(encoding="utf-8"))
    p2p3 = json.loads((OUT_DIR / "p2p3.json").read_text(encoding="utf-8"))
    linked = json.loads((OUT_DIR / "linked.json").read_text(encoding="utf-8"))
    (OUT_DIR / "report.md").write_text(build_report(p1, p2p3, linked), encoding="utf-8")
    print("report -> scripts/parsed/report.md")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["p1", "p2p3", "linked"], help="只解析一份")
    ap.add_argument("--skip-llm", action="store_true", help="跳过 LLM 兜底（不联网）")
    args = ap.parse_args()
    targets = [args.only] if args.only else ["p1", "p2p3", "linked"]
    asyncio.run(run(targets, args.skip_llm))


if __name__ == "__main__":
    main()
