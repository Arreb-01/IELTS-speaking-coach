# -*- coding: utf-8 -*-
"""M1 spike: 提取三份 PDF 前 N 页的文本与样式信息，供人工确认结构规则。

输出到 scripts/parsed/spike/：
- {name}_text.txt   纯文本（每页以 [PAGE n] 分隔）
- {name}_spans.json 前 3 页的 span 级样式（字号/颜色/字体），用于定标题与标签颜色规则
"""
import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]  # 仓库根
PDF_DIR = ROOT / "2026年5-8月雅思口语素材P123"
OUT_DIR = Path(__file__).resolve().parent / "parsed" / "spike"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PDFS = {
    "p1": "2026年5-8月雅思口语素材p1.pdf",
    "p2p3": "2026年5-8月雅思口语素材p2和p3.pdf",
    "linked": "2026年5-8月雅思口语素材p2串联版.pdf",
}

TEXT_PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 10
SPAN_PAGES = 3


def dump_spans(doc: pymupdf.Document, limit: int) -> list:
    pages = []
    for pno in range(min(limit, doc.page_count)):
        spans = []
        for block in doc[pno].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text:
                        spans.append({
                            "text": text[:80],
                            "size": round(span["size"], 1),
                            "color": f"#{span['color']:06x}",
                            "font": span["font"],
                        })
        pages.append({"page": pno + 1, "spans": spans})
    return pages


def main() -> None:
    for name, fname in PDFS.items():
        path = PDF_DIR / fname
        if not path.exists():
            print(f"[MISS] {path}")
            continue
        with pymupdf.open(path) as doc:
            text_parts = []
            for pno in range(min(TEXT_PAGES, doc.page_count)):
                text_parts.append(f"\n[PAGE {pno + 1}]\n" + doc[pno].get_text())
            (OUT_DIR / f"{name}_text.txt").write_text("".join(text_parts), encoding="utf-8")
            (OUT_DIR / f"{name}_spans.json").write_text(
                json.dumps(dump_spans(doc, SPAN_PAGES), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            chars = sum(len(p.get_text()) for p in doc)
            print(f"[OK] {name}: {doc.page_count} pages, {chars} chars total, "
                  f"avg {chars // doc.page_count}/page")


if __name__ == "__main__":
    main()
