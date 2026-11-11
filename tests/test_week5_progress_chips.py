"""进度三态 + 人设卡回顾：结构/逻辑测试。"""

from __future__ import annotations

from pathlib import Path

from server.models import GameConfig, GameMode, Player, Room

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"


def test_phase1_progress_reports_action_kinds():
    """第一幕进度要带上「谁做了什么」，前端才能显示三态。"""
    src = (ROOT / "server" / "state_machine.py").read_text(encoding="utf-8")
    block = src.split("def phase1_progress")[1].split("async def on_phase1_timeout")[0]
    assert '"kinds"' in block, "缺少 kinds 字段"
    assert "action_kind" in block


def test_chips_show_three_states():
    src = (STATIC / "js" / "phase1.js").read_text(encoding="utf-8")
    for label in ("已提问", "已呈看板", "已略过", "待行动", "冷却中"):
        assert label in src, f"缺少状态文案：{label}"
    assert "progress.kinds" in src


def test_phase3_shows_who_confirmed():
    src = (STATIC / "js" / "phase3.js").read_text(encoding="utf-8")
    assert "confirmedIds" in src, "phase3:progress 的 confirmed 是数组，要按 id 判断"
    assert "已示意" in src and "还没看" in src


def test_my_card_button_and_drawer():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-my-card"' in html and 'id="my-card"' in html
    assert 'id="btn-my-card"' in html and "hidden" in html.split('id="btn-my-card"')[1][:120]

    js = (STATIC / "js" / "mycard.js").read_text(encoding="utf-8")
    assert "PERSONA" in js and "yourCard" in js, "只有人设卡模式才显示按钮"
    assert "mycard__content" in js, "要展示卡面内容"
    assert "别报自己的编号" in js


def test_state_has_your_card_after_assignment():
    """快照/分配里都带 yourCard，前端才能随时回顾。"""
    room = Room(code="333333", config=GameConfig())
    room.game_mode = GameMode.PERSONA.value
    player = Player(id="p0", nickname="甲", room_no=1)
    room.players = {"p0": player}
    snap = room.to_state(viewer=player)
    assert "you" in snap
