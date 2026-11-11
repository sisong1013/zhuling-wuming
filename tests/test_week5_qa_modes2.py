"""第 5 周（二批）：问答三档可见性、草稿、冷却只锁看板的回归测试（全离线）。"""

from __future__ import annotations

from pathlib import Path

from server import rules
from server.models import GameConfig, GameMode, Player, Question, Room, Visibility

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"


def make_room(mode: str = "PUBLIC", visibility: Visibility = Visibility.PUBLIC):
    room = Room(code="888888", config=GameConfig(qa_visibility=mode))
    room.game_mode = GameMode.REAL.value
    room.round = 1
    players = [
        Player(id=f"p{i}", nickname=n, room_no=i + 1) for i, n in enumerate(["甲", "乙", "丙"])
    ]
    room.players = {p.id: p for p in players}
    room.captain_id = players[0].id
    q = Question(
        id="q1",
        asker_id=players[0].id,
        target_id=players[1].id,
        text="你昨晚在哪？",
        round=1,
        visibility=visibility,
    )
    room.questions.append(q)
    return room, players, q


def test_config_accepts_qa_visibility():
    patched, errors = GameConfig().patched({"qaVisibility": "SEMI"})
    assert not errors, errors
    assert patched.qa_visibility == "SEMI"
    assert patched.to_public()["qaVisibility"] == "SEMI"


def test_config_rejects_bad_qa_visibility():
    _, errors = GameConfig().patched({"qaVisibility": "WHISPER"})
    assert errors, "非法值必须被拒"


def test_visibility_for_reads_config():
    room, _, _ = make_room("PRIVATE")
    assert rules.visibility_for(room) is Visibility.PRIVATE


def test_public_everyone_sees_question_and_answer():
    room, players, q = make_room("PUBLIC", Visibility.PUBLIC)
    q.answer = "在钟楼上。"
    for viewer in players:
        assert rules.question_public_payload(room, q, viewer.id)["text"] == "你昨晚在哪？"
        assert rules.answer_public_payload(room, q, viewer.id)["answer"] == "在钟楼上。"


def test_semi_question_visible_to_all_but_answer_only_to_parties():
    room, players, q = make_room("SEMI", Visibility.SEMI)
    asker, target, bystander = players
    q.answer = "在钟楼上。"

    for viewer in players:
        assert rules.question_public_payload(room, q, viewer.id)["text"] == "你昨晚在哪？"

    assert rules.answer_public_payload(room, q, asker.id)["answer"] == "在钟楼上。"
    assert rules.answer_public_payload(room, q, target.id)["answer"] == "在钟楼上。"
    masked = rules.answer_public_payload(room, q, bystander.id)
    assert masked is not None and masked["answer"] is None, "半公开：旁观者看不到回答内容"


def test_private_thread_hidden_from_bystanders():
    room, players, q = make_room("PRIVATE", Visibility.PRIVATE)
    asker, target, bystander = players
    q.answer = "在钟楼上。"

    assert rules.question_public_payload(room, q, bystander.id) is None, "私密：旁观者连问题都不该收到"
    assert rules.answer_public_payload(room, q, bystander.id) is None
    assert rules.question_public_payload(room, q, asker.id)["text"] == "你昨晚在哪？"
    assert rules.answer_public_payload(room, q, target.id)["answer"] == "在钟楼上。"


def test_clip_text_kind_matters():
    assert (
        rules.clip_text(
            Visibility.SEMI, "回答", asker_id="a", target_id="b", viewer_id="c", kind="answer"
        )
        is None
    )
    assert (
        rules.clip_text(
            Visibility.SEMI, "问题", asker_id="a", target_id="b", viewer_id="c", kind="question"
        )
        == "问题"
    )


def test_state_payload_carries_draft():
    room, players, _ = make_room()
    players[0].draft = {"2": "乙", "3": "丙"}
    payload = room.to_state(viewer=players[0])
    assert payload["you"]["draft"] == {"2": "乙", "3": "丙"}, "草稿必须随 room:state 回传"


def test_ask_is_not_gated_by_cooldown():
    machine = (ROOT / "server" / "state_machine.py").read_text(encoding="utf-8")
    check_block = machine.split("def _check_phase1")[1].split("async def action_ask")[0]
    assert "cooldown" not in check_block, "冷却不应拦提问"

    phase1 = (STATIC / "js" / "phase1.js").read_text(encoding="utf-8")
    can_ask_line = [ln for ln in phase1.splitlines() if "const canAsk" in ln][0]
    assert "cooldown" not in can_ask_line, f"前端 canAsk 不应受冷却影响：{can_ask_line}"


def test_feed_has_round_pager():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="feed-prev"' in html and 'id="feed-next"' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "feedViewRound" in app and "feedRounds" in app


def test_waiting_room_has_qa_mode_selector():
    waiting = (STATIC / "js" / "waiting.js").read_text(encoding="utf-8")
    assert 'id="qa-mode"' in waiting
    for mode in ("PUBLIC", "SEMI", "PRIVATE"):
        assert mode in waiting
    assert "qaVisibility" in waiting


def test_board_shows_per_cell_result_marks():
    board = (STATIC / "js" / "board.js").read_text(encoding="utf-8")
    assert "lastSubmit" in board and "猜错" in board and "未猜" in board


def test_question_text_is_dark_for_contrast():
    css = (STATIC / "style.v5.css").read_text(encoding="utf-8")
    assert ".question-text" in css
    assert "#241f18" in css, "问题文字应为深色（米色卡片上浅色字费眼）"
