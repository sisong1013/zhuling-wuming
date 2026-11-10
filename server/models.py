"""数据模型：房间、玩家、问题、配置、可见性枚举、错误类型。

设计要点
- 纯内存对象，没有 ORM / 数据库。
- 房间状态对外只通过 `Room.to_state()` 输出；编号→昵称的映射**永不**出现在里面。
- 可见性枚举第一周只实现 PUBLIC，SEMI / PRIVATE 保留枚举 + 裁剪函数骨架（rules.clip_text）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Phase(str, Enum):
    """房间所处阶段（第 2 周：SETUP / CARD_WRITING / READING 三个新阶段）。"""

    LOBBY = "LOBBY"
    SETUP = "SETUP"
    CARD_WRITING = "CARD_WRITING"
    READING = "READING"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    OVER = "OVER"


class GameMode(str, Enum):
    """玩法模式：REAL=猜真人（第 1 周），PERSONA=人设卡（第 2 周）。"""

    REAL = "REAL"
    PERSONA = "PERSONA"


def status_of(phase: Phase) -> str:
    """对外状态：三阶段循环统一报 PLAYING（前端按 status 切视图，按 phase 切幕次）。"""
    if phase in (Phase.PHASE1, Phase.PHASE2, Phase.PHASE3):
        return "PLAYING"
    return phase.value



class Visibility(str, Enum):
    """问答内容的可见性。第一周只落地 PUBLIC，其余两个是接口骨架。"""

    PUBLIC = "PUBLIC"
    SEMI = "SEMI"
    PRIVATE = "PRIVATE"


class QuestionStatus(str, Enum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"
    TIMEOUT = "TIMEOUT"


class ActionKind(str, Enum):
    ASK = "ASK"
    SUBMIT = "SUBMIT"
    SKIP = "SKIP"


class GameError(Exception):
    """业务错误：直接翻译成 error / room:error 消息回给前端。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def new_id(prefix: str) -> str:
    """生成短 id（内存里唯一即可）。"""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class GameConfig:
    """房间配置，队长可在开始前修改（测试也靠它把 60s/12 轮缩短）。"""

    phase1_seconds: float = 60.0
    phase2_seconds: float = 30.0  # 每题回答时限
    phase3_seconds: float = 30.0
    reading_seconds: float = 180.0  # 人设卡模式：阅读阶段时长
    forced_submit_round: int = 12
    max_players: int = 8
    min_players: int = 2
    cooldown_rounds: int = 3
    forced_wrong_penalty: int = 1
    forced_wrong_in_cooldown_penalty: int = 2
    heartbeat_seconds: float = 60.0  # 服务端多久没收到消息判定掉线
    over_retention_seconds: float = 600.0  # 结束后保留多久可复盘
    # 第 3 周：AI 节奏（全部可配，测试里压到 0.1s 级别）
    ai_think_seconds: float = 6.0  # 第一幕思考延迟基准（实际 0.8–1.7 倍随机）
    ai_card_delay_seconds: float = 2.0  # 写卡后多久提交
    ai_answer_delay_seconds: float = 3.0  # 回答打字延迟基准
    ai_confirm_delay_seconds: float = 2.0  # 回放确认延迟基准
    ai_llm_timeout_seconds: float = 45.0  # 单次 LLM 调用超时（思考型模型很慢）

    # --- 序列化 ---
    def to_public(self) -> dict[str, Any]:
        return {
            "phase1Seconds": self.phase1_seconds,
            "phase2Seconds": self.phase2_seconds,
            "phase3Seconds": self.phase3_seconds,
            "readingSeconds": self.reading_seconds,
            "forcedSubmitRound": self.forced_submit_round,
            "maxPlayers": self.max_players,
            "minPlayers": self.min_players,
            "cooldownRounds": self.cooldown_rounds,
            "aiThinkSeconds": self.ai_think_seconds,
            "aiCardDelaySeconds": self.ai_card_delay_seconds,
            "aiAnswerDelaySeconds": self.ai_answer_delay_seconds,
            "aiConfirmDelaySeconds": self.ai_confirm_delay_seconds,
            "aiLlmTimeoutSeconds": self.ai_llm_timeout_seconds,
        }

    # --- 客户端补丁 ---
    _INT_FIELDS = {
        "forcedSubmitRound": "forced_submit_round",
        "maxPlayers": "max_players",
        "minPlayers": "min_players",
        "cooldownRounds": "cooldown_rounds",
    }
    _SEC_FIELDS = {
        "phase1Seconds": "phase1_seconds",
        "phase2Seconds": "phase2_seconds",
        "phase3Seconds": "phase3_seconds",
        "readingSeconds": "reading_seconds",
        "heartbeatSeconds": "heartbeat_seconds",
        "overRetentionSeconds": "over_retention_seconds",
        "aiThinkSeconds": "ai_think_seconds",
        "aiCardDelaySeconds": "ai_card_delay_seconds",
        "aiAnswerDelaySeconds": "ai_answer_delay_seconds",
        "aiConfirmDelaySeconds": "ai_confirm_delay_seconds",
        "aiLlmTimeoutSeconds": "ai_llm_timeout_seconds",
    }
    _RANGES = {
        "forcedSubmitRound": (1, 99),
        "maxPlayers": (2, 8),  # 第一周硬上限 8 人
        "minPlayers": (2, 8),
        "cooldownRounds": (0, 10),
    }

    def patched(self, patch: dict[str, Any], player_count: int = 0) -> tuple["GameConfig", list[str]]:
        """返回 (新配置, 错误列表)。校验失败时不落盘，全部按原值。"""
        errors: list[str] = []
        values: dict[str, Any] = {}
        for key, raw in patch.items():
            if key in self._SEC_FIELDS:
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    errors.append(f"{key} 必须是数字")
                    continue
                # AI 相关节奏允许 0（测试/快速模式），其余秒数仍要求 >=1
                target_attr = self._SEC_FIELDS[key]
                low = 0 if target_attr.startswith("ai_") else 1
                if not (low <= val <= 600):
                    errors.append(f"{key} 必须在 {low}..600 秒之间")
                    continue
                values[self._SEC_FIELDS[key]] = val
            elif key in self._INT_FIELDS:
                try:
                    val = int(raw)
                except (TypeError, ValueError):
                    errors.append(f"{key} 必须是整数")
                    continue
                lo, hi = self._RANGES[key]
                if not (lo <= val <= hi):
                    errors.append(f"{key} 必须在 {lo}..{hi} 之间")
                    continue
                values[self._INT_FIELDS[key]] = val
            else:
                errors.append(f"未知配置项 {key}")

        new = GameConfig(**{**self.__dict__, **values})
        if new.min_players > new.max_players:
            errors.append("minPlayers 不能大于 maxPlayers")
        if player_count and new.max_players < player_count:
            errors.append(f"房间已有 {player_count} 人，maxPlayers 不能小于该值")
        return (self if errors else new), errors


@dataclass
class Player:
    """房间内的一名玩家（热座：一个标签页一个人）。"""

    id: str
    nickname: str
    is_captain: bool = False
    connected: bool = True
    room_no: int | None = None  # 本局编号，只回给本人
    cooldown: int = 0  # 剩余冷却轮数（>0 时不能提交）
    draft: dict[str, str] = field(default_factory=dict)  # 看板草稿：编号(字符串) → 昵称
    action_round: int = 0  # 最近一次行动的轮次（用于「每人每轮一次」）
    action_kind: str | None = None
    submit_round: int = 0
    submitted_board: dict[str, str] | None = None
    confirmed_round: int = 0  # 最近一次确认回放的轮次
    # --- 第 2 周新增 ---
    reconnect_token: str = ""  # 入座时签发，重连凭据
    card_submitted: bool = False  # 人设卡是否已提交
    assigned_card_id: str | None = None  # 被分配到的人设卡
    reading_confirmed: bool = False  # 阅读阶段是否已示意
    is_ai: bool = False  # AI 玩家
    ai_memory: Any = None  # AI 私有记忆（ai_agent.AIMemory）

    def acted_in(self, round_no: int) -> bool:
        return self.action_round == round_no

    # 规格里的别名（board_json / submit_cooldown），与内部字段同源
    @property
    def board_json(self) -> dict[str, str]:
        return self.draft

    @board_json.setter
    def board_json(self, value: dict[str, str]) -> None:
        self.draft = value

    @property
    def submit_cooldown(self) -> int:
        return self.cooldown

    @submit_cooldown.setter
    def submit_cooldown(self, value: int) -> None:
        self.cooldown = value

    def public_view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nickname": self.nickname,
            "isCaptain": self.is_captain,
            "isAi": self.is_ai,
            "connected": self.connected,
            "cooldown": self.cooldown,
        }


@dataclass
class Question:
    """一条公开提问（第一周固定 PUBLIC）。"""

    id: str
    asker_id: str
    target_id: str
    text: str
    round: int
    created_at: float = field(default_factory=time.time)
    status: QuestionStatus = QuestionStatus.PENDING
    answer: str | None = None
    visibility: Visibility = Visibility.PUBLIC
    deadline: float | None = None


@dataclass
class PersonaCard:
    """人设卡：由玩家（或 AI）手写，错位分配给别人。"""

    id: str
    game_id: str  # 房间码
    author_id: str
    name: str
    content: str = ""
    assigned_room_no: int | None = None

    def public_view(self) -> dict[str, Any]:
        """对外的卡面（不含作者）。"""
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "assignedRoomNo": self.assigned_room_no,
        }


@dataclass
class Room:
    """一个房间的全部状态。"""

    code: str
    config: GameConfig = field(default_factory=GameConfig)
    captain_id: str = ""
    players: dict[str, Player] = field(default_factory=dict)
    phase: Phase = Phase.LOBBY
    round: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    deadline: float | None = None
    questions: list[Question] = field(default_factory=list)  # 全部轮次的问题
    winner_id: str | None = None
    forced_submit: bool = False
    replay: list[dict[str, Any]] = field(default_factory=list)  # 本轮回放条目
    phase2_active: dict[str, str] = field(default_factory=dict)  # 被问者 → 当前进行中的问题 id
    last_phase_result: dict[str, Any] = field(default_factory=dict)
    # --- 第 2 周新增 ---
    game_mode: str = GameMode.REAL.value
    visibility: str = Visibility.PUBLIC.value
    cards: list[PersonaCard] = field(default_factory=list)
    card_submitted: set[str] = field(default_factory=set)  # 已交卡的 player_id
    assigned: bool = False  # 人设卡是否已完成错位分配
    finished_at: float | None = None  # 结束时间（用于回收）

    # ---------------- 查询 ----------------
    @property
    def count(self) -> int:
        return len(self.players)

    @property
    def status(self) -> str:
        """对外状态：LOBBY / SETUP / CARD_WRITING / READING / PLAYING / OVER。"""
        return status_of(self.phase)

    @property
    def online_count(self) -> int:
        """在线人数（只有 connected 才算）。"""
        return sum(1 for p in self.players.values() if p.connected)

    def active_players(self) -> list[Player]:
        """「全员行动/全员确认」只看在线玩家；全掉线时退回全部（避免死锁）。"""
        online = [p for p in self.ordered_players() if p.connected]
        return online or self.ordered_players()

    def card_of(self, player: Player) -> PersonaCard | None:
        """该玩家被分配到的人设卡。"""
        if not player.assigned_card_id:
            return None
        for card in self.cards:
            if card.id == player.assigned_card_id:
                return card
        return None

    def card_by_author(self, author_id: str) -> PersonaCard | None:
        for card in self.cards:
            if card.author_id == author_id:
                return card
        return None

    def card_names(self) -> list[str]:
        return [c.name for c in self.cards]

    def ordered_players(self) -> list[Player]:
        """按入房顺序返回玩家（dict 保序）。"""
        return list(self.players.values())

    def player(self, player_id: str) -> Player | None:
        return self.players.get(player_id)

    def by_nickname(self, nickname: str) -> Player | None:
        for p in self.players.values():
            if p.nickname == nickname:
                return p
        return None

    def player_by_room_no(self, room_no: int) -> Player | None:
        for p in self.players.values():
            if p.room_no == room_no:
                return p
        return None

    def room_nos(self) -> list[int]:
        """全部编号（升序）。空位（LOBBY/未开始）返回空列表。"""
        return sorted(p.room_no for p in self.players.values() if p.room_no is not None)

    def round_questions(self, round_no: int | None = None) -> list[Question]:
        rnd = self.round if round_no is None else round_no
        return [q for q in self.questions if q.round == rnd]

    def full_board(self) -> dict[str, dict[str, Any]]:
        """真实映射：编号 → {nickname, playerId}。只在 game:over 时下发。"""
        return {
            str(p.room_no): {"nickname": p.nickname, "playerId": p.id}
            for p in self.ordered_players()
            if p.room_no is not None
        }

    # ---------------- 对外状态 ----------------
    def to_state(self, viewer: Player | None = None) -> dict[str, Any]:
        """room:state 载荷。**绝不包含编号→昵称映射**，只把本人的编号回给本人。"""
        payload: dict[str, Any] = {
            "type": "room:state",
            "roomCode": self.code,
            "phase": self.phase.value,
            "status": self.status,
            "gameMode": self.game_mode,
            "visibility": self.visibility,
            "round": self.round,
            "captainId": self.captain_id,
            "started": bool(self.started_at),
            "count": self.count,
            "onlineCount": self.online_count,
            "maxPlayers": self.config.max_players,
            "minPlayers": self.config.min_players,
            "deadline": self.deadline,
            "forcedSubmit": self.forced_submit,
            "players": [p.public_view() for p in self.ordered_players()],
            "config": self.config.to_public(),
            "winnerId": self.winner_id,
        }
        if self.game_mode == GameMode.PERSONA.value:
            payload["cards"] = {
                "submitted": len(self.card_submitted),
                "assigned": self.assigned,
            }
        if viewer is not None:
            payload["you"] = {
                "id": viewer.id,
                "nickname": viewer.nickname,
                "isCaptain": viewer.is_captain,
                "roomNo": viewer.room_no,  # 只回本人
                "cooldown": viewer.cooldown,
                "acted": viewer.acted_in(self.round),
                "draft": dict(viewer.draft),
                "reconnectToken": viewer.reconnect_token,
                "cardSubmitted": viewer.card_submitted,
                "readingConfirmed": viewer.reading_confirmed,
            }
        return payload
