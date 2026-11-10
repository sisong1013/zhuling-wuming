"""WebSocket 消息层：连接表 + client→server 消息分发 + 统一的错误出口。

约定（每个 handler 都按这个顺序校验）：
1. 是否已在房间/已建房（身份）
2. 房间是否存在、游戏是否在跑
3. 阶段是否允许该动作
4. 权限（队长 / 是否本人）
5. 重复动作（每人每轮一次、每题只答一次）
6. 载荷合法性
任何一条不满足 → 回 error（建房/进房失败回 room:error）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from .models import GameError, Player, Room
from .state_machine import GameRegistry

log = logging.getLogger("game.ws")

ROOM_SCOPED_ERRORS = {"room:create", "room:join"}


class ConnectionHub:
    """playerId → WebSocket 的映射。只有在线玩家在表里。"""

    def __init__(self) -> None:
        self._sockets: dict[str, WebSocket] = {}

    def bind(self, player_id: str, ws: WebSocket) -> None:
        self._sockets[player_id] = ws

    def unbind(self, player_id: str, ws: WebSocket | None = None) -> None:
        cur = self._sockets.get(player_id)
        if cur is None:
            return
        if ws is None or cur is ws:
            self._sockets.pop(player_id, None)

    def is_online(self, player_id: str) -> bool:
        return player_id in self._sockets

    def online_ids(self) -> list[str]:
        return list(self._sockets)

    async def send(self, player_id: str, payload: dict[str, Any]) -> bool:
        """发一条消息；发不出去就当该玩家已掉线，不抛异常。"""
        ws = self._sockets.get(player_id)
        if ws is None:
            return False
        try:
            await ws.send_json(payload)
            return True
        except Exception:
            log.debug("发送失败 player=%s type=%s", player_id, payload.get("type"))
            self._sockets.pop(player_id, None)
            return False


@dataclass
class Session:
    """一条连接的会话状态。"""

    ws: WebSocket
    player_id: str | None = None
    room_code: str | None = None
    last_seen: float = field(default_factory=__import__("time").time)  # 心跳判定用
    extra: dict[str, Any] = field(default_factory=dict)

    async def send(self, payload: dict[str, Any]) -> None:
        try:
            await self.ws.send_json(payload)
        except Exception:
            log.debug("会话发送失败 type=%s", payload.get("type"))


Handler = Callable[[GameRegistry, "Session", dict[str, Any]], Awaitable[None]]


# ----------------------------------------------------------------------
# 校验辅助
# ----------------------------------------------------------------------
def _require_bound(registry: GameRegistry, session: Session) -> tuple[Room, Player]:
    """消息必须来自房间内的一手连接。"""
    if not session.player_id:
        raise GameError("NOT_IN_ROOM", "你还没有创建或加入房间")
    room, player = registry.player_of(session.player_id)
    if room is None or player is None:
        raise GameError("NOT_IN_ROOM", "房间不存在或已结束")
    return room, player


def _require_lobby(room: Room) -> None:
    if room.phase.value != "LOBBY":
        raise GameError("WRONG_PHASE", "游戏已经开始，此操作只在等待室可用")


def _text_field(msg: dict[str, Any], key: str, max_len: int) -> str:
    from . import rules

    return rules.sanitize_text(msg.get(key, ""), max_len)


# ----------------------------------------------------------------------
# 房间类 handler
# ----------------------------------------------------------------------
async def handle_room_create(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """建房：拿 6 位码，创建者即队长。"""
    if session.player_id:
        raise GameError("ALREADY_IN_ROOM", "这条连接已经在房间里了")
    room, player = registry.create_room(msg.get("nickname"))
    session.player_id = player.id
    session.room_code = room.code
    session_ws = session.ws
    # 注意：hub 的绑定在 main 里做（Session 不持有 hub），这里通过 registry.hub 绑定
    registry.hub.bind(player.id, session_ws)  # type: ignore[attr-defined]
    registry.register_session(player.id, session)  # type: ignore[attr-defined]
    await session.send(
        {
            "type": "room:created",
            "roomCode": room.code,
            "playerId": player.id,
            "isCaptain": player.is_captain,
            "nickname": player.nickname,
        }
    )
    await registry.broadcast_state(room)


async def handle_room_join(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """用房间码加入。"""
    if session.player_id:
        raise GameError("ALREADY_IN_ROOM", "这条连接已经在房间里了")
    room, player = registry.join_room(msg.get("roomCode"), msg.get("nickname"))
    session.player_id = player.id
    session.room_code = room.code
    registry.hub.bind(player.id, session.ws)  # type: ignore[attr-defined]
    registry.register_session(player.id, session)  # type: ignore[attr-defined]
    await session.send(
        {
            "type": "room:joined",
            "roomCode": room.code,
            "playerId": player.id,
            "isCaptain": player.is_captain,
            "nickname": player.nickname,
        }
    )
    await registry.broadcast_state(room)


async def handle_setup_config(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """队长修改房间配置（只在等待室有效）。"""
    room, player = _require_bound(registry, session)
    patch = {k: v for k, v in msg.items() if k != "type"}
    registry.update_config(room, player, patch)
    await registry.broadcast_state(room)


async def handle_board_save_draft(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """看板草稿：任意阶段都能存（第一周只存服务端内存，不下发别人）。"""
    from . import rules

    room, player = _require_bound(registry, session)
    if room.phase.value == "LOBBY":
        raise GameError("WRONG_PHASE", "游戏还没开始")
    draft = rules.normalize_board_for_storage(msg.get("board"))
    player.draft = draft
    await registry.send_to(
        room, player.id, {"type": "board:draftSaved", "board": draft, "savedAt": __import__("time").time()}
    )


async def handle_game_start(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """队长开始游戏。"""
    room, player = _require_bound(registry, session)
    await registry.start_game(room, player)


async def handle_phase1_ask(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """PHASE1：向某个编号提问。"""
    room, player = _require_bound(registry, session)
    await registry.action_ask(room, player, msg.get("targetRoomNo"), msg.get("text"))


async def handle_phase1_submit(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """PHASE1：提交看板（立即结算）。"""
    room, player = _require_bound(registry, session)
    await registry.action_submit(room, player, msg.get("board"))


async def handle_phase1_skip(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """PHASE1：跳过本轮行动（可顺带存草稿）。"""
    room, player = _require_bound(registry, session)
    await registry.action_skip(room, player, msg.get("board"))


async def handle_phase2_answer(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """PHASE2：被问者回答当前问题。"""
    room, player = _require_bound(registry, session)
    await registry.action_answer(room, player, msg.get("questionId"), msg.get("text"))


async def handle_phase3_confirm(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """PHASE3：确认回放。"""
    room, player = _require_bound(registry, session)
    await registry.action_confirm(room, player)



# ----------------------------------------------------------------------
# 第 2 周：重连 / 人设卡 / 阅读
# ----------------------------------------------------------------------
async def handle_conn_reconnect(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """凭 reconnect_token 抢回座位。"""
    from .models import Phase

    if session.player_id:
        raise GameError("ALREADY_IN_ROOM", "这条连接已经在房间里了")
    try:
        room, player = registry.reconnect(
            msg.get("roomCode"), msg.get("playerId"), msg.get("token")
        )
    except GameError as exc:
        await session.send({"type": "reconnect:failed", "code": exc.code, "message": exc.message})
        return

    session.player_id = player.id
    session.room_code = room.code
    registry.hub.bind(player.id, session.ws)  # type: ignore[attr-defined]
    registry.register_session(player.id, session)
    registry.touch_session(player.id)

    await session.send(
        {"type": "reconnect:ok", "snapshot": registry.snapshot_for(room, player)}
    )
    # 阶段数据补齐（前端重连后能直接继续玩）
    if room.phase is Phase.READING:
        await registry.send_to(room, player.id, registry.persona_assigned_payload(room, player))
    await registry.broadcast_state(room)


async def handle_card_submit(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """写卡阶段提交人设卡。"""
    room, player = _require_bound(registry, session)
    await registry.submit_card(room, player, msg.get("name"), msg.get("content"))


async def handle_captain_start_assign(
    registry: GameRegistry, session: Session, msg: dict[str, Any]
) -> None:
    """队长触发错位分配。"""
    room, player = _require_bound(registry, session)
    await registry.start_assign(room, player)


async def handle_reading_confirm(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """阅读阶段示意。"""
    room, player = _require_bound(registry, session)
    await registry.confirm_reading(room, player)


async def handle_room_add_ai(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """队长在等待室添加 AI 玩家（第 3 周：一次 1–2 个）。"""
    room, player = _require_bound(registry, session)
    added = registry.add_ai_players(room, player, msg.get("count", 1))
    await registry.broadcast_state(room)
    await session.send(
        {
            "type": "room:aiAdded",
            "players": [{"id": p.id, "nickname": p.nickname} for p in added],
            "count": room.count,
        }
    )


async def handle_captain_add_ai(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """兼容第 2 周的 captain:addAi（可指定昵称，等价 count=1）。"""
    room, player = _require_bound(registry, session)
    nickname = msg.get("nickname")
    if nickname:
        registry.add_ai_player(room, player, nickname)
    else:
        registry.add_ai_players(room, player, 1)
    await registry.broadcast_state(room)


# ----------------------------------------------------------------------
# 分发
# ----------------------------------------------------------------------
HANDLERS: dict[str, Handler] = {
    "room:create": handle_room_create,
    "room:join": handle_room_join,
    "setup:config": handle_setup_config,
    "game:start": handle_game_start,
    "board:saveDraft": handle_board_save_draft,
    "phase1:ask": handle_phase1_ask,
    "phase1:submit": handle_phase1_submit,
    "phase1:skip": handle_phase1_skip,
    "phase2:answer": handle_phase2_answer,
    "phase3:confirm": handle_phase3_confirm,
    # 第 2 周
    "conn:reconnect": handle_conn_reconnect,
    "card:submit": handle_card_submit,
    "captain:startAssign": handle_captain_start_assign,
    "reading:confirm": handle_reading_confirm,
    "captain:addAi": handle_captain_add_ai,
    "room:addAI": handle_room_add_ai,
}


async def dispatch(registry: GameRegistry, session: Session, msg: dict[str, Any]) -> None:
    """一条 client→server 消息的入口。"""
    mtype = msg.get("type")
    if not isinstance(mtype, str):
        await session.send({"type": "error", "code": "INVALID_PAYLOAD", "message": "缺少 type 字段"})
        return

    if session.player_id:
        # 心跳：任何消息都算活；同时确保会话表指向「当前这条连接」
        registry.register_session(session.player_id, session)
        registry.touch_session(session.player_id)

    if mtype == "ping":
        await session.send({"type": "pong", "t": msg.get("t")})
        return

    handler = HANDLERS.get(mtype)
    if handler is None:
        await session.send(
            {"type": "error", "code": "UNKNOWN_TYPE", "message": f"未知消息类型：{mtype}"}
        )
        return

    try:
        await handler(registry, session, msg)
    except GameError as exc:
        kind = "room:error" if mtype in ROOM_SCOPED_ERRORS else "error"
        await session.send({"type": kind, "code": exc.code, "message": exc.message, "for": mtype})
    except Exception:
        log.exception("处理消息失败 type=%s", mtype)
        await session.send({"type": "error", "code": "INTERNAL", "message": "服务端处理失败"})
