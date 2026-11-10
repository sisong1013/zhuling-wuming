"""Step 3.4：AI 第一幕决策（ASK / SUBMIT / SKIP）。"""

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
    state_of,
    wait_ai_decision,
    wait_phase,
)


def _base_of(ws_base: str) -> str:
    return ws_base.replace("ws://", "http://").replace("/ws", "")


async def _real_room_with_ai(ws_base, extra: dict | None = None):
    cfg = ai_config(**{"phase1Seconds": 30, "aiThinkSeconds": 0.3})
    if extra:
        cfg.update(extra)
    clients = await full_room(ws_base, ["甲", "乙"], config=cfg)
    await add_ai(clients[0], 1)
    await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
    await start_game(clients)
    for c in clients:
        await wait_phase(c, "PHASE1", 1, timeout=10)
    return clients


async def test_ai_decides_in_phase1(ws_base):
    """AI 在第一幕会自己产出一个合法决策（ASK/SUBMIT/SKIP 之一）。"""
    clients = await _real_room_with_ai(ws_base)
    try:
        # 两个真人都放弃 → 只要 AI 也行动，就会进入第二幕
        for c in clients:
            await c.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE2", 1, timeout=20)

        debug = await fetch_ai_debug(_base_of(ws_base))
        decisions = ai_decisions(debug, "phase1", room=clients[0].room_code)
        assert decisions, "AI 没有留下第一幕决策记录"
        last = decisions[-1]
        assert last["action"] in ("ASK", "SUBMIT", "SKIP")
    finally:
        await close_all(clients)


async def test_ai_never_asks_itself(ws_base):
    """AI 提问目标不能是自己。"""
    clients = await _real_room_with_ai(ws_base)
    try:
        await wait_ai_decision(_base_of(ws_base), clients[0].room_code, "phase1", timeout=15)
        debug = await fetch_ai_debug(_base_of(ws_base))
        ais = {a["nickname"]: a["roomNo"] for a in debug["ais"]}
        asks = [d for d in ai_decisions(debug, "phase1", room=clients[0].room_code) if d.get("action") == "ASK"]
        assert asks, "兜底策略应当会去提问"
        for item in asks:
            own_no = ais.get(item["_nickname"])
            assert item["targetRoomNo"] != own_no, "AI 不能问自己"
            assert item["text"].strip()
    finally:
        await close_all(clients)


async def test_ai_question_reaches_human(ws_base):
    """AI 的提问会真的送到被问的真人手里（走同一条 question:received 通道）。"""
    clients = await _real_room_with_ai(ws_base)
    try:
        hit = None
        for c in clients:
            try:
                msg = await c.wait_for("question:received", timeout=20)
                hit = (c, msg)
                break
            except Exception:
                continue
        assert hit is not None, "AI 的提问没有送达任何真人"
        client, msg = hit
        assert msg["text"].strip()
        assert msg["askerNickname"] not in {c.name for c in clients}
    finally:
        await close_all(clients)


def test_cooldown_forces_ai_to_skip():
    """冷却中的 AI 只能放弃（纯单元测试，不依赖服务端）。"""
    from server import ai_agent
    from server.models import GameMode, Player, Room

    room = Room(code="123456", config=__import__("server.models", fromlist=["GameConfig"]).GameConfig())
    room.game_mode = GameMode.REAL.value
    human = Player(id="p1", nickname="甲", room_no=1)
    bot = Player(id="p2", nickname="星辉剑士", room_no=2, is_ai=True, cooldown=3)
    room.players = {human.id: human, bot.id: bot}
    room.captain_id = human.id

    decision = ai_agent._fallback_decision(room, bot)
    assert decision["action"] == "SKIP"
    assert decision["reason"] == "cooldown"


async def test_ai_submit_when_forced_round(ws_base):
    """到强制提交轮，AI 会立刻交出看板（而不是继续提问）。"""
    clients = await full_room(
        ws_base,
        ["甲", "乙"],
        config=ai_config(
            **{"phase1Seconds": 30, "aiThinkSeconds": 0.2, "forcedSubmitRound": 1}
        ),
    )
    try:
        await add_ai(clients[0], 1)
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)

        await wait_ai_decision(_base_of(ws_base), clients[0].room_code, "phase1", timeout=15)
        debug = await fetch_ai_debug(_base_of(ws_base))
        decisions = ai_decisions(debug, "phase1", room=clients[0].room_code)
        assert decisions
        assert any(d.get("action") == "SUBMIT" for d in decisions), (
            f"强制轮 AI 应该提交看板，实际：{decisions}"
        )
        # 真正提交的看板来自「推理轮」（kind=submit）
        verdicts = ai_decisions(debug, "submit", room=clients[0].room_code)
        assert verdicts, "提交前应该跑一次推理轮"
        assert verdicts[-1]["board"], "看板不能为空"
        board = {int(k): v for k, v in verdicts[-1]["board"].items()}
        assert len(set(board.values())) == len(board), "一人一号，取值不能重复"
    finally:
        await close_all(clients)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
