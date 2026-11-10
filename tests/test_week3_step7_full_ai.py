"""Step 3.7：整局人机混战（2 真人 + 2 AI，跑到结束）。"""

from __future__ import annotations

import pytest

from helpers import (
    add_ai,
    ai_config,
    ai_decisions,
    close_all,
    collect_assigned,
    fetch_ai_debug,
    full_room,
    start_game,
    state_of,
    submit_all_cards,
    wait_phase,
)


def _base_of(ws_base: str) -> str:
    return ws_base.replace("ws://", "http://").replace("/ws", "")


async def test_full_game_two_humans_two_ai(ws_base):
    """PERSONA 整局：写卡(含 AI) → 分配 → 阅读 → 一轮混战 → 真人拿下看板。"""
    clients = await full_room(
        ws_base,
        ["甲", "乙"],
        config=ai_config(
            gameMode="PERSONA",
            readingSeconds=5,
            phase1Seconds=8,
            phase2Seconds=3,
            phase3Seconds=3,
            forcedSubmitRound=6,
        ),
    )
    base = _base_of(ws_base)
    try:
        # ---- 等待室：加 2 个 AI ----
        await add_ai(clients[0], 2)
        st = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("count") == 4, timeout=8
        )
        bots = [p for p in st["players"] if p.get("isAi")]
        assert len(bots) == 2
        bot_names = {p["nickname"] for p in bots}

        # ---- 写卡：真人两张 + AI 两张 ----
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "CARD_WRITING", timeout=10)
        await submit_all_cards(clients)  # 只替真人交
        prog = await clients[0].wait_for(
            "card:progress", pred=lambda m: m.get("submitted") == 4, timeout=20
        )
        assert prog["total"] == 4

        # ---- 分配 + 阅读 ----
        await clients[0].send("captain:startAssign")
        for c in clients:
            await wait_phase(c, "READING", timeout=12)
        await collect_assigned(clients)
        for c in clients:
            await c.send("reading:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=25)

        # ---- 第一轮：真人放弃，让 AI 自己动 ----
        for c in clients:
            await c.send("phase1:skip")

        # AI 行动 + 第二幕（AI 的问题超时也放行） + 第三幕 → 第二轮
        for c in clients:
            await wait_phase(c, "PHASE1", 2, timeout=90)
        st2 = await clients[0].wait_for(
            "room:state", pred=lambda m: m.get("round", 1) >= 2, timeout=20
        )
        assert st2["round"] >= 2, "AI 参与后应该能推进到下一轮"

        # ---- 第二轮：用调试口拿真值，真人一锤定音 ----
        debug = await fetch_ai_debug(base)
        room_meta = [r for r in debug["rooms"] if r["roomCode"] == clients[0].room_code][0]
        truth = room_meta["truth"]
        assert len(truth) == 4

        board = {str(no): name for no, name in truth.items()}
        await clients[0].send("phase1:submit", board=board)

        over = await clients[0].wait_for("game:over", timeout=30)
        assert over["gameMode"] == "PERSONA"
        assert over["winnerId"] == clients[0].player_id
        reveal = over["reveal"]
        assert len(reveal) == 4

        authors = {item["authorNickname"] for item in reveal}
        assert bot_names <= authors, "两个 AI 写的卡都应该在揭晓里"
        assert all(item["cardName"] and item["cardContent"] for item in reveal)

        # ---- AI 全程留痕（说明它真的在参与，不是摆设）----
        debug2 = await fetch_ai_debug(base)
        cards = ai_decisions(debug2, "write_card", room=clients[0].room_code)
        decisions = ai_decisions(debug2, "phase1", room=clients[0].room_code)
        assert len(cards) >= 2, f"AI 写卡记录不足：{cards}"
        assert len(decisions) >= 2, f"AI 第一幕决策记录不足：{decisions}"
        assert all(d["action"] in ("ASK", "SUBMIT", "SKIP") for d in decisions)
    finally:
        await close_all(clients)


async def test_full_game_real_mode_with_ai(ws_base):
    """REAL 整局：2 真人 + 1 AI，跑到结束（AI 也走同一套冷却/提交规则）。"""
    clients = await full_room(
        ws_base,
        ["甲", "乙"],
        config=ai_config(
            **{
                "readingSeconds": 5,
                "phase1Seconds": 6,
                "phase2Seconds": 3,
                "phase3Seconds": 3,
                "aiThinkSeconds": 0.3,
            }
        ),
    )
    base = _base_of(ws_base)
    try:
        await add_ai(clients[0], 1)
        await clients[0].wait_for("room:state", pred=lambda m: m.get("count") == 3, timeout=8)
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)

        for c in clients:
            await c.send("phase1:skip")
        for c in clients:
            await wait_phase(c, "PHASE1", 2, timeout=90)

        debug = await fetch_ai_debug(base)
        room_meta = [r for r in debug["rooms"] if r["roomCode"] == clients[0].room_code][0]
        truth = room_meta["truth"]

        await clients[0].send("phase1:submit", board={str(k): v for k, v in truth.items()})
        over = await clients[0].wait_for("game:over", timeout=30)
        assert over["gameMode"] == "REAL"
        assert over["winnerId"] == clients[0].player_id
        assert over["fullBoard"]
    finally:
        await close_all(clients)
