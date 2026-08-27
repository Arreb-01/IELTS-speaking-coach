# -*- coding: utf-8 -*-
"""Part D E2E：话题库（搜索/筛选/翻页）→ 详情（范文/表达）→ 词汇本 → 错题本占位。

前置：后端 8000（VOLC_MOCK=1，PG 已导入 PDF 题库+表达库）、前端 5173。
用法：由 with_server.py 拉起双服务后执行。
"""

import random
import string
import sys

from playwright.sync_api import expect, sync_playwright

BASE = "http://localhost:5173"


def random_email() -> str:
    name = "e2e" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{name}@example.com"


def run() -> int:
    failures: list[str] = []

    def check(name: str, fn):
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"[FAIL] {name}: {str(exc)[:200]}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE)
        page.wait_for_load_state("networkidle")

        # ---- 注册并进入
        email = random_email()
        page.goto(f"{BASE}/register")
        page.fill('input[type="email"]', email)
        page.locator('input[placeholder="怎么称呼你？"]').fill("E2E 考生")
        page.fill('input[type="password"]', "pass1234")
        page.locator('input[placeholder="再次输入密码"]').fill("pass1234")
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/", timeout=15000)
        check("注册并登录", lambda: None)

        # ---- 话题库：Part1 卡片与分页
        page.goto(f"{BASE}/topics")
        page.wait_for_selector(".topic-card", timeout=15000)
        check("话题库加载卡片", lambda: expect(page.locator(".topic-card")).to_have_count(12))

        check("分页组件存在（59 话题 > 12/页）",
              lambda: expect(page.locator(".el-pagination")).to_be_visible())
        page.locator(".el-pagination .btn-next").click()
        page.wait_for_timeout(1200)
        check("翻页后仍显示 12 张卡", lambda: expect(page.locator(".topic-card")).to_have_count(12))
        page.locator(".el-pagination .btn-prev").click()
        page.wait_for_timeout(1200)

        # ---- 搜索（英文）
        page.fill(".topics__search-input", "Hometown")
        page.wait_for_timeout(1200)  # 防抖+请求
        check("搜索 Hometown 过滤", lambda: expect(page.locator(".topic-card")).to_have_count(1))
        page.fill(".topics__search-input", "")
        page.wait_for_timeout(1200)

        # ---- 标签筛选
        page.select_option(".topics__select >> nth=0", "must")
        page.wait_for_timeout(1200)
        n_must = page.locator(".topic-card").count()
        check(f"标签筛选 must（{n_must} 张卡）", lambda: assert_true(n_must >= 1 and n_must < 12))
        page.select_option(".topics__select >> nth=0", "")

        # ---- Part2 tab + 分类下拉
        page.click("text=Part 2 · 独白")
        page.wait_for_timeout(1500)
        check("Part2 话题加载", lambda: assert_true(page.locator(".topic-card").count() > 0))
        selects = page.locator(".topics__select")
        check("Part2 显示两个下拉（分类+标签）", lambda: expect(selects).to_have_count(2))
        page.select_option(".topics__select >> nth=0", "person")
        page.wait_for_timeout(1200)
        total_text = page.locator(".el-pagination__total").inner_text()
        n_person_total = int("".join(filter(str.isdigit, total_text)))
        check(f"分类筛选 person（共 {n_person_total} 个话题，应为 p2p3 子集）",
              lambda: assert_true(10 <= n_person_total < 70))
        page.screenshot(path="scripts/parsed/e2e_topics_p2.png", full_page=True)

        # ---- 详情页：选一个有串联的 person 话题（发小）
        page.select_option(".topics__select >> nth=0", "")
        page.wait_for_timeout(1200)
        card = page.locator(".topic-card", has_text="A Childhood Friend").first
        card.locator(".topic-card__title").click()
        page.wait_for_url("**/topics/*", timeout=10000)
        page.wait_for_selector(".detail-section", timeout=15000)
        check("详情页加载", lambda: expect(page.locator(".detail-head__title")).to_be_visible())

        # Cue Card 与主范文
        check("Cue Card 渲染", lambda: expect(page.locator(".cue-card__prompt")).to_contain_text("Describe"))
        page.locator(".answer-collapse__title", has_text="参考范文").first.click()
        page.wait_for_timeout(500)
        check("范文展开", lambda: assert_true(page.locator(".answer-text").first.inner_text().strip() != ""))

        # 高分表达收藏
        expr_items = page.locator(".expr-item")
        if expr_items.count() > 0:
            first_word = expr_items.first.locator(".expr-item__text").inner_text()
            expr_items.first.locator(".expr-item__save").click()
            page.wait_for_timeout(1000)
            check("表达收藏成功提示", lambda: expect(page.locator(".el-message")).to_contain_text("已加入词汇本"))
        else:
            first_word = None
            print("[SKIP] 该话题无表达（表达库生成未完成？）")

        # 串联提示（发小所在组）
        links = page.locator(".link-tip")
        check(f"串联提示区（{links.count()} 组）", lambda: assert_true(links.count() >= 1))
        page.screenshot(path="scripts/parsed/e2e_detail.png", full_page=True)

        # ---- 词汇本
        page.goto(f"{BASE}/vocab")
        page.wait_for_selector(".vocab-item, .el-empty", timeout=15000)
        if first_word:
            check("词汇本出现收藏词条", lambda: expect(page.locator(".vocab-item__word").first).to_have_text(first_word))
            # 收藏切换与删除
            page.locator(".vocab-item__icon-btn").first.click()
            page.wait_for_timeout(800)
            page.locator(".vocab-item__icon-btn.is-danger").first.click()
            page.wait_for_timeout(500)
            # Element Plus 的确认框是 DOM 渲染，需点击其确定按钮
            page.locator(".el-message-box__btns .el-button--primary").click()
            page.wait_for_timeout(1000)
            check("删除词条后列表为空", lambda: expect(page.locator(".el-empty")).to_be_visible())
        else:
            check("词汇本空状态", lambda: expect(page.locator(".el-empty")).to_be_visible())
        page.screenshot(path="scripts/parsed/e2e_vocab.png", full_page=True)

        # ---- 错题本占位
        page.goto(f"{BASE}/mistakes")
        page.wait_for_selector(".mistakes", timeout=10000)
        check("错题本占位页", lambda: expect(page.locator(".mistakes__title")).to_contain_text("错题本即将上线"))

        browser.close()

    print(f"\n{'=' * 40}\n{'ALL PASS' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


def assert_true(cond: bool):
    assert cond, "condition false"


if __name__ == "__main__":
    sys.exit(run())
