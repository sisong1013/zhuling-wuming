"""Step 3.6：AI 记忆与看板推理（含防泄题扫描）。"""

from __future__ import annotations

import pytest

from helpers import (
    add_ai,
    ai_config,
    ai_decisions,
    close_all,
    fetch_ai_debug,
    full_room,
    start_game,
    wait_ai_decision,
    wait_phase,
)


def _base_of(ws_base: str) -> str:
    return ws_base.replace("ws://", "http://").replace("/ws", "")


def _room_with_ai(mode: str = "PERSONA"):
    """手工搭一个房间：3 个真人 + 1 个 AI（PERSONA 会带卡）。"""
    from server.models import GameConfig, GameMode, PersonaCard, Player, Room

    room = Room(code="654321", config=GameConfig())
    room.game_mode = GameMode.PERSONA.value if mode == "PERSONA" else GameMode.REAL.value
    players = [
        Player(id="p1", nickname="甲", room_no=1),
        Player(id="p2", nickname="乙", room_no=2),
        Player(id="p3", nickname="星辉剑士", room_no=3, is_ai=True),
    ]
    room.players = {p.id: p for p in players}
    room.captain_id = "p1"
    if mode == "PERSONA":
        names = ["雾港更夫", "折纸诗人", "青苔占星师"]
        cards = [
            PersonaCard(id=f"c{i}", game_id=room.code, author_id=p.id, name=names[i], content="卡面")
            for i, p in enumerate(players)
        ]
        for i, p in enumerate(players):
            p.assigned_card_id = cards[i].id
            cards[i].assigned_room_no = p.room_no
        room.cards = cards
        room.assigned = True
    return room, players[-1]


def _leaks(prompt: str, mapping: dict[int, str]) -> list[str]:
    """找出「同一个其他人：编号与昵称出现在同一行」的行。"""
    bad: list[str] = []
    for line in prompt.splitlines():
        for no, nickname in mapping.items():
            if str(no) in line and nickname in line:
                bad.append(line)
    return bad


def test_prompt_never_pairs_number_with_nickname_persona():
    """PERSONA：Prompt 里不能出现「别人编号 + 别人昵称」同行。"""
    from server import ai_agent

    room, bot = _room_with_ai("PERSONA")
    system, user = ai_agent.build_phase1_prompt(room, bot)
    truth = {1: "甲", 2: "乙"}
    assert not _leaks(user, {k: v for k, v in truth.items() if k != bot.room_no}), (
        f"Prompt 泄露了编号→昵称：{_leaks(user, truth)}"
    )
    # 也不该出现「自己的编号 + 别人的卡名」这种配对（自己编号出现是允许的）
    assert f"{bot.room_no} 号" in user


def test_prompt_never_pairs_number_with_nickname_real():
    from server import ai_agent

    room, bot = _room_with_ai("REAL")
    _system, user = ai_agent.build_phase1_prompt(room, bot)
    assert not _leaks(user, {1: "甲", 2: "乙"})


def test_prompt_contains_public_history_only():
    """Prompt 里的问答历史只有公开字段（问者昵称 + 被问编号 + 问答文本）。"""
    from server import ai_agent
    from server.models import Question, QuestionStatus

    room, bot = _room_with_ai("PERSONA")
    q = Question(
        id="q1",
        round=1,
        asker_id="p1",
        target_id="p3",
        text="你最怕什么？",
        status=QuestionStatus.ANSWERED,
        answer="怕化妝油。",
    )
    room.questions = [q]

    lines = ai_agent.public_qa_lines(room)
    assert lines and "你最怕什么？" in lines[0]
    assert "怕化妝油。" in lines[0]
    assert "甲" in lines[0]          # 问者昵称（公开）
    assert "3 号" in lines[0]        # 被问者只给编号
    assert "星辉剑士" not in lines[0], "被问者昵称不该出现在公开历史里"

    _system, user = ai_agent.build_phase1_prompt(room, bot)
    assert "你最怕什么？" in user


def test_ai_board_fills_own_cell_correctly():
    """兜底看板：自己那格必须对，且覆盖所有编号。"""
    from server import ai_agent

    room, bot = _room_with_ai("PERSONA")
    board = ai_agent.fallback_board(room, bot)
    assert set(board) == {1, 2, 3}
    assert board[bot.room_no] == "青苔占星师"  # 自己拿到的那张

    room_real, bot_real = _room_with_ai("REAL")
    board_real = ai_agent.fallback_board(room_real, bot_real)
    assert board_real[bot_real.room_no] == bot_real.nickname


async def test_live_prompts_have_no_mapping(ws_base):
    """真实对局里抓到的 Prompt 也不能出现编号→昵称配对。"""
    clients = await full_room(
        ws_base,
        ["甲", "乙"],
        config=ai_config(**{"phase1Seconds": 20, "aiThinkSeconds": 0.3}),
    )
    base = _base_of(ws_base)
    try:
        await add_ai(clients[0], 1)
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)

        await wait_ai_decision(base, clients[0].room_code, "phase1", timeout=20)
        debug = await fetch_ai_debug(base)

        prompts = [
            (item.get("system", "") + "\n" + item.get("user", ""))
            for item in debug["log"]
            if item.get("room") == clients[0].room_code and item.get("kind") == "phase1"
        ]
        assert prompts, "没有抓到 AI 的第一幕 Prompt"

        truth_by_room = {r["roomCode"]: r["truth"] for r in debug["rooms"]}
        truth = {int(k): v for k, v in truth_by_room[clients[0].room_code].items()}
        for prompt in prompts:
            assert not _leaks(prompt, truth), f"Prompt 泄露编号→昵称：\n{prompt}"
    finally:
        await close_all(clients)


async def test_live_ai_board_own_cell_matches_truth(ws_base):
    """真实对局的 AI 看板：自己那格与真值一致（其余允许错）。"""
    clients = await full_room(
        ws_base,
        ["甲", "乙"],
        config=ai_config(
            **{"phase1Seconds": 20, "aiThinkSeconds": 0.2, "forcedSubmitRound": 1}
        ),
    )
    base = _base_of(ws_base)
    try:
        await add_ai(clients[0], 1)
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)

        await wait_ai_decision(base, clients[0].room_code, "phase1", timeout=20)
        verdicts = await wait_ai_decision(base, clients[0].room_code, "submit", timeout=20)
        assert verdicts, "提交前应该跑一次推理轮"

        debug = await fetch_ai_debug(base)
        ai_meta = [a for a in debug["ais"] if a["room"] == clients[0].room_code][0]
        room_meta = [
            r for r in debug["rooms"] if r["roomCode"] == clients[0].room_code
        ][0]
        truth = {int(k): v for k, v in room_meta["truth"].items()}
        board = {int(k): v for k, v in verdicts[-1]["board"].items()}
        assert set(board) == set(truth), "看板要覆盖所有编号"
        assert board[ai_meta["roomNo"]] == truth[ai_meta["roomNo"]], (
            f"自己那格必须对：{board} vs truth {truth}"
        )
    finally:
        await close_all(clients)
