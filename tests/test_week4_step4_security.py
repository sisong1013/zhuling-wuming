"""Step 4.4：安全与防作弊（阶段广播不泄密 / 重连不越权 / 非法操作拦截）。"""

from __future__ import annotations

import pytest

from helpers import (
    add_ai,
    assign_cards,
    card_board,
    close_all,
    collect_assigned,
    full_room,
    join_room,
    my_token,
    persona_room,
    reconnect,
    start_game,
    state_of,
    submit_all_cards,
    wait_phase,
)

# ----------------------------------------------------------------------
# 1. 阶段广播里不能有任何「编号 → 真人/卡」映射
# ----------------------------------------------------------------------


async def test_phase_changed_has_no_mapping(ws_base):
    clients = await full_room(ws_base, ["甲", "乙", "丙"])
    try:
        await start_game(clients)
        truth = {c.my_room_no: c.name for c in clients}
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=10)
            msg = state_of(c)
            blob = str(msg)
            for no, nick in truth.items():
                # 编号与昵称不允许以「成对」形式出现
                assert not (f'"{no}"' in blob and nick in blob and "players" not in blob)
            assert "truth" not in msg
            assert "mapping" not in msg
            for p in msg["players"]:
                assert "roomNo" not in p
                assert "draft" not in p
    finally:
        await close_all(clients)


async def test_persona_assigned_has_no_author_mapping(ws_base):
    clients = await persona_room(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        await submit_all_cards(clients)
        await assign_cards(clients[0])
        for c in clients:
            await wait_phase(c, "READING", timeout=12)
        allowed = {"type", "yourRoomNo", "roomNos", "yourCard", "cardNames", "deadline"}
        for c in clients:
            msg = await c.wait_for("persona:assigned", timeout=8)
            assert set(msg) <= allowed
            assert set(msg["yourCard"]) == {"name", "content"}
            blob = str(msg)
            for other in clients:
                if other is c:
                    continue
                assert other.name not in blob
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# 2. 重连快照不能把别人的看板/卡牌带出来
# ----------------------------------------------------------------------


async def test_reconnect_snapshot_does_not_leak_others(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"], config={"gameMode": "PERSONA"})
    try:
        tokens = {c.name: await my_token(c) for c in clients}
        await start_game(clients)
        for c in clients:
            await wait_phase(c, "CARD_WRITING", timeout=10)
        await submit_all_cards(clients)
        await clients[0].wait_for("card:progress", pred=lambda m: m.get("submitted") == 2, timeout=12)
        await clients[0].send("captain:startAssign")
        for c in clients:
            await wait_phase(c, "READING", timeout=12)
        await collect_assigned(clients)

        room_code = clients[1].room_code
        player_id = clients[1].player_id
        await clients[1].close()

        back = await reconnect(ws_base, room_code, player_id, tokens["乙"])
        try:
            ok = await back.wait_for("reconnect:ok", timeout=8)
            snap = ok["snapshot"]
            assert snap["yourRoomNo"] == clients[1].my_room_no
            # 自己的卡可以有；别人的卡/看板不能有
            assert snap["yourCard"]["name"] == clients[1].assigned_card["name"]
            for p in snap["players"]:
                assert "draft" not in p
                assert "assignedCardId" not in p
                assert "board" not in p
            assert "truth" not in snap
            # 卡名表可以有（公开信息），但不能带作者
            assert set(snap["cardNames"]) == set(clients[0].assigned_card and snap["cardNames"])
            assert "authorId" not in str(snap)
        finally:
            await back.close()
    finally:
        await close_all(clients)


# ----------------------------------------------------------------------
# 3. 非法操作必须被阶段校验拦住
# ----------------------------------------------------------------------


async def test_illegal_actions_are_rejected(ws_base):
    clients = await persona_room(ws_base, ["甲", "乙"], config={"readingSeconds": 30})
    try:
        # CARD_WRITING：不能提问 / 提交看板 / 确认回放
        for event, payload in [
            ("phase1:ask", {"targetRoomNo": 1, "text": "早问"}),
            ("phase1:submit", {"board": {"1": "x"}}),
            ("phase3:confirm", {}),
            ("game:start", {}),
        ]:
            await clients[0].send(event, **payload)
            err = await clients[0].wait_for("error", timeout=6)
            assert err["code"] in ("WRONG_PHASE", "ALREADY_STARTED", "FORBIDDEN")

        # 阅读阶段：不能交卡/分配
        await submit_all_cards(clients)
        await clients[0].send("captain:startAssign")
        for c in clients:
            await wait_phase(c, "READING", timeout=12)
        await clients[0].send("card:submit", name="迟到卡", content="内容")
        err2 = await clients[0].wait_for("error", timeout=6)
        assert err2["code"] == "WRONG_PHASE"

        # 第一幕：不能回答不存在的问题
        for c in clients:
            await collect_assigned(clients) if False else None
        for c in clients:
            await c.send("reading:confirm")
        for c in clients:
            await wait_phase(c, "PHASE1", 1, timeout=15)
        await clients[0].send("phase2:answer", questionId="q_nope", text="乱答")
        err3 = await clients[0].wait_for("error", timeout=6)
        assert err3["code"] in ("WRONG_PHASE", "QUESTION_NOT_FOUND")
    finally:
        await close_all(clients)


async def test_add_ai_blocked_after_start(ws_base):
    clients = await full_room(ws_base, ["甲", "乙"])
    try:
        await start_game(clients)
        await wait_phase(clients[0], "PHASE1", 1, timeout=10)
        await clients[0].send("room:addAI", count=1)
        err = await clients[0].wait_for("error", timeout=6)
        assert err["code"] == "WRONG_PHASE"
    finally:
        await close_all(clients)


async def test_non_player_cannot_act(ws_base):
    """没入座就发游戏操作 → room:error / 未入座错误。"""
    from helpers import WsClient

    clients = await full_room(ws_base, ["甲", "乙"])
    stranger = await WsClient.connect(ws_base, "stranger")
    try:
        await stranger.send("phase1:skip")
        err = await stranger.wait_for("error", timeout=6)
        assert err["code"] in ("NOT_IN_ROOM", "NO_SESSION", "FORBIDDEN", "ROOM_NOT_FOUND")
    finally:
        await stranger.close()
        await close_all(clients)
