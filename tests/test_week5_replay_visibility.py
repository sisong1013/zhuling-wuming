"""复述/复盘也遵守三档可见性：单元测试。"""

from __future__ import annotations

from pathlib import Path

from server import rules
from server.models import GameConfig, GameMode, Player, Question, QuestionStatus, Room, Visibility

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"


def make_room(visibility: Visibility, answered: bool = True):
    room = Room(code="777777", config=GameConfig(qa_visibility=visibility.value))
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
    if answered:
        q.answer = "在钟楼上。"
        q.status = QuestionStatus.ANSWERED
    room.questions.append(q)
    return room, players, q


def _answer_item(items):
    return next((i for i in items if i["kind"] == "answer"), None)


def test_replay_public_shows_answer_to_all():
    room, players, _ = make_room(Visibility.PUBLIC)
    for viewer in players:
        items = rules.build_replay_items(room, viewer_id=viewer.id)
        item = _answer_item(items)
        assert item and item["answer"] == "在钟楼上。"
        assert item["masked"] is False


def test_replay_semi_masks_answer_for_bystanders():
    room, players, _ = make_room(Visibility.SEMI)
    asker, target, bystander = players
    for party in (asker, target):
        item = _answer_item(rules.build_replay_items(room, viewer_id=party.id))
        assert item["answer"] == "在钟楼上。" and item["masked"] is False
    masked = _answer_item(rules.build_replay_items(room, viewer_id=bystander.id))
    assert masked["answer"] is None and masked["masked"] is True


def test_replay_private_hidden_from_bystanders():
    room, players, _ = make_room(Visibility.PRIVATE)
    asker, target, bystander = players
    assert rules.build_replay_items(room, viewer_id=bystander.id) == []
    assert rules.build_replay_items(room, viewer_id=asker.id), "当事人仍要看得到"


def test_timeline_semi_masks_answer_and_answer_tags():
    room, players, _ = make_room(Visibility.SEMI)
    asker, target, bystander = players
    seen = rules.build_timeline(room, winner_id=target.id, viewer_id=bystander.id)
    assert seen, "半公开：问题仍然出现在时间线里"
    entry = seen[0]
    assert entry["answer"] is None and entry["masked"] is True
    assert "self_reveal" not in entry["highlights"], "答案类高亮对旁观者要隐藏"

    full = rules.build_timeline(room, winner_id=target.id, viewer_id=asker.id)
    assert full[0]["answer"] == "在钟楼上。"


def test_timeline_private_hidden_from_bystanders():
    room, players, _ = make_room(Visibility.PRIVATE)
    asker, target, bystander = players
    assert rules.build_timeline(room, viewer_id=bystander.id) == []
    assert rules.build_timeline(room, viewer_id=target.id)


def test_phase3_pairs_question_and_answer_items():
    """前端把「问题条目+回答条目」按 questionId 配对，否则复述页会串行。"""
    src = (STATIC / "js" / "phase3.js").read_text(encoding="utf-8")
    assert "threads.find" in src, "需要按 questionId 配对"
    assert "is-masked" in src and "内容仅当事人可见" in src


def test_over_timeline_marks_masked_answer():
    src = (STATIC / "js" / "over.js").read_text(encoding="utf-8")
    assert "item.masked" in src and "内容仅当事人可见" in src
