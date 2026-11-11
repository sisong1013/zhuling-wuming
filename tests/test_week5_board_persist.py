"""看板选择持久化 & 问答可读性：结构与逻辑测试。"""

from __future__ import annotations

from pathlib import Path

from server import rules
from server.models import GameConfig, GameMode, Player, Room

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"


def test_board_render_is_memoized():
    """regression：每次 state 广播都重建看板 DOM → 用户已选的人被清空。"""
    src = (STATIC / "js" / "board.js").read_text(encoding="utf-8")
    assert "boardKey" in src and "signature === boardKey" in src, "需要一个渲染签名守卫"
    assert 'root.querySelector(".board")) return' in src, "签名没变就该直接返回，别重建"


def test_submit_saves_draft_first():
    src = (STATIC / "js" / "board.js").read_text(encoding="utf-8")
    idx = src.index('send("phase1:submit"')
    window = src[max(0, idx - 300):idx]
    assert "board:saveDraft" in window, "提交前先把当前选择存草稿，失败也不丢"


def test_draft_survives_wrong_submit():
    """提交失败后，服务端草稿要保留这次的看板。"""
    room = Room(code="666666", config=GameConfig())
    room.game_mode = GameMode.REAL.value
    room.round = 1
    player = Player(id="p0", nickname="甲", room_no=1)
    room.players = {"p0": player}
    player.draft = rules.normalize_board_for_storage({"1": "甲", "2": "随便猜的"})
    assert player.draft == {"1": "甲", "2": "随便猜的"}

    payload = room.to_state(viewer=player)
    assert payload["you"]["draft"]["2"] == "随便猜的", "room:state 必须把草稿回传"


def test_feed_question_has_light_card():
    css = (STATIC / "style.v5.css").read_text(encoding="utf-8")
    block = css.rsplit(".feed-q {", 1)[1].split("}")[0]
    assert "#f7efdd" in block, "问题要有浅底"
    assert "#23202a" in block, "问题要用深色字"


def test_feed_defaults_to_current_round_only():
    """侧栏默认只显示本轮，历史靠翻页，不然会堆成一条长河。"""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    block = app.split("const source = viewRound")[1].split(";")[0]
    assert "item.round === state.round" in block, "默认视图必须按当前轮过滤"


def test_over_mapping_handles_object_values():
    """fullBoard 是 {编号: {nickname, playerId}}，直接 esc 会变 [object Object]。"""
    over = (STATIC / "js" / "over.js").read_text(encoding="utf-8")
    assert "who.nickname" in over or "who?.nickname" in over or "(who && who.nickname)" in over
    assert 'typeof who === "string"' in over


def test_over_page_has_high_contrast_styles():
    css = (STATIC / "style.v5.css").read_text(encoding="utf-8")
    for sel in (".over-card .map-who", ".over-card .tl-q", ".over-card .tl-a", ".over-card .hl"):
        assert sel in css, f"缺少样式：{sel}"
    assert "#ffffff" in css and "#2a2114" in css
