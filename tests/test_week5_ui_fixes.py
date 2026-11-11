"""第 5 周 UI 修补的回归：问答载荷带 targetNo + 观众板不再把对象塞进 HTML。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_question_public_carries_target_no():
    rules = (ROOT / "server" / "rules.py").read_text(encoding="utf-8")
    q_block = rules.split('"type": "question:public"')[1].split('"type": "answer:public"')[0]
    assert '"targetNo"' in q_block, "question:public 必须带 targetNo，否则前端只能显示「？号」"


def test_answer_public_carries_target_no():
    rules = (ROOT / "server" / "rules.py").read_text(encoding="utf-8")
    a_block = rules.split('"type": "answer:public"')[1]
    assert '"targetNo"' in a_block, "answer:public 也要带 targetNo，回答才知道挂在谁名下"


def test_board_cells_are_plain_strings():
    """regression: raw() 返回对象，被 map().join() 拼成了 [object Object]。"""
    board = (ROOT / "server" / "static" / "js" / "board.js").read_text(encoding="utf-8")
    cells_block = board.split("const cells =")[1].split("const cooldown")[0]
    assert "raw(`" not in cells_block, "格子模板不能包 raw()，它是对象，join 会变 [object Object]"
    assert "return `" in cells_block, "格子必须直接返回字符串"


def test_feed_threads_are_grouped():
    app = (ROOT / "server" / "static" / "app.js").read_text(encoding="utf-8")
    ws = (ROOT / "server" / "static" / "js" / "ws.js").read_text(encoding="utf-8")
    assert "renderFeedItem" in app, "feed 要按线程渲染"
    assert 'kind === "thread"' in app
    assert "upsertThread" in ws, "ws.js 要把同一 questionId 的问题与回答合并"
    # 问题行 + 回答行都要有
    assert "feed-q" in app and "feed-a" in app


def test_feed_and_board_css_have_contrast_rules():
    css = (ROOT / "server" / "static" / "style.v4.css").read_text(encoding="utf-8")
    for sel in (".feed-item.thread", ".feed-a::before", ".question-text", ".board-cell select"):
        assert sel in css, f"缺少样式：{sel}"
    assert "#fffdf7" in css, "问题文字要用高对比色"
