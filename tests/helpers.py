"""测试用 WebSocket 客户端与常用流程封装。

约定：所有等待都用带超时的 wait_for，禁止长 sleep，也不依赖测试执行顺序。
"""

from __future__ import annotations

import asyncio
import json
import time

from websockets.asyncio.client import connect

DEFAULT_TIMEOUT = 4.0


class WsClient:
    """一条 WebSocket 连接 + 消息缓冲（wait_for 会自动跳过不关心的事件）。"""

    def __init__(self, ws, name: str) -> None:
        self.ws = ws
        self.name = name
        self.backlog: list[dict] = []
        self.player_id: str | None = None
        self.room_code: str | None = None
        self.my_room_no: int | None = None
        self.is_captain: bool = False
        self.room_nos: list[int] = []
        self.nicknames: list[str] = []
        self.phase_log: list[dict] = []  # 收到过的 phase:changed，便于事后取用
        self.last_room_state: dict | None = None  # 最近一条 room:state

    # -- 生命周期 ---------------------------------------------------
    @classmethod
    async def connect(cls, ws_url: str, name: str = "") -> "WsClient":
        ws = await connect(ws_url, open_timeout=8, close_timeout=4, max_size=None)
        return cls(ws, name or "anon")

    async def close(self) -> None:
        try:
            await self.ws.close()
        except Exception:
            pass

    def _note(self, msg: dict) -> None:
        """任何路径收到消息时都记一下最近状态（测试常常只想看「现在是什么状态」）。"""
        if msg.get("type") == "room:state":
            self.last_room_state = msg

    # -- 收发 -------------------------------------------------------
    async def send(self, mtype: str, **payload) -> None:
        await self.ws.send(json.dumps({"type": mtype, **payload}))

    async def recv(self, timeout: float = DEFAULT_TIMEOUT) -> dict:
        if self.backlog:
            msg = self.backlog.pop(0)
            self._note(msg)
            return msg
        raw = await asyncio.wait_for(self.ws.recv(), timeout)
        msg = json.loads(raw)
        self._note(msg)
        return msg

    async def wait_for(self, mtype: str, timeout: float = DEFAULT_TIMEOUT, pred=None) -> dict:
        """等到某类消息；期间收到的其它消息先压在 backlog 里。

        注意：这里必须直接读 socket（不能走 recv()，否则会把 backlog 里的旧消息
        反复取出再压回，形成忙等死循环）。
        """
        for i, m in enumerate(list(self.backlog)):
            if m.get("type") == mtype and (pred is None or pred(m)):
                self._note(m)
                return self.backlog.pop(i)
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise AssertionError(
                    f"[{self.name}] 等 {mtype} 超时（{timeout}s）；期间收到：{seen}"
                    f"；backlog：{[m.get('type') for m in self.backlog]}"
                )
            raw = await asyncio.wait_for(self.ws.recv(), remain)
            m = json.loads(raw)
            self._note(m)
            if m.get("type") == mtype and (pred is None or pred(m)):
                return m
            seen.append(m.get("type"))
            self.backlog.append(m)

    async def collect(self, seconds: float = 0.4) -> list[dict]:
        """在时间窗口内把能收到的消息全收下来（含 backlog）。"""
        out: list[dict] = list(self.backlog)
        self.backlog.clear()
        deadline = time.monotonic() + seconds
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                break
            try:
                raw = await asyncio.wait_for(self.ws.recv(), remain)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            self._note(msg)
            out.append(msg)
        return out

    async def wait_error(self, code: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
        """等待一条 error 消息（可指定 code）。"""
        pred = None if code is None else (lambda m: m.get("code") == code)
        return await self.wait_for("error", timeout=timeout, pred=pred)

    async def ping(self) -> dict:
        await self.send("ping", t=time.time())
        return await self.wait_for("pong")


# ----------------------------------------------------------------------
# 流程封装
# ----------------------------------------------------------------------


async def create_room(ws_url: str, nickname: str) -> WsClient:
    """建房并等 room:created。"""
    c = await WsClient.connect(ws_url, nickname)
    await c.send("room:create", nickname=nickname)
    msg = await c.wait_for("room:created")
    c.player_id = msg["playerId"]
    c.room_code = msg["roomCode"]
    c.is_captain = bool(msg["isCaptain"])
    return c


async def join_room(ws_url: str, code: str, nickname: str) -> WsClient:
    """用房间码加入并等 room:joined。"""
    c = await WsClient.connect(ws_url, nickname)
    await c.send("room:join", roomCode=code, nickname=nickname)
    msg = await c.wait_for("room:joined")
    c.player_id = msg["playerId"]
    c.room_code = msg["roomCode"]
    c.is_captain = bool(msg["isCaptain"])
    return c


async def full_room(ws_url: str, names: list[str], config: dict | None = None) -> list[WsClient]:
    """建一个 n=len(names) 人的房间：第一个人当队长。返回按 names 顺序的客户端列表。"""
    captain = await create_room(ws_url, names[0])
    clients = [captain]
    for nick in names[1:]:
        clients.append(await join_room(ws_url, captain.room_code, nick))
    if config:
        await captain.send("setup:config", **config)
        # 配置若被拒，服务端会回 error：这里必须炸掉，否则测试会带着默认值静默跑
        msgs = await captain.collect(0.5)
        for msg in msgs:
            assert msg.get("type") != "error", f"setup:config 被拒：{msg}"
        assert any(m.get("type") == "room:state" for m in msgs), "配置后没收到 room:state"
    # 等所有连接都把早期 room:state 广播收进来，避免后面串消息
    for c in clients:
        await c.collect(0.15)
    return clients


async def start_game(clients: list[WsClient]) -> None:
    """队长发 game:start，所有人等 game:started。"""
    captain = clients[0]
    await captain.send("game:start")
    for c in clients:
        msg = await c.wait_for("game:started", timeout=6)
        c.my_room_no = msg["yourRoomNo"]
        c.room_nos = msg["roomNos"]
        c.nicknames = msg["nicknames"]


def numbers_to_nicknames(clients: list[WsClient]) -> dict[int, str]:
    """测试侧的「上帝视角」：从各人自己的 yourRoomNo 拼出真实映射。

    服务端永远不会下发这张表，测试靠每个连接各自的私有消息还原。
    """
    return {c.my_room_no: c.name for c in clients}


def correct_board(clients: list[WsClient]) -> dict[str, str]:
    """能赢的看板：{字符串编号: 昵称}。"""
    return {str(c.my_room_no): c.name for c in clients}


def wrong_board(clients: list[WsClient]) -> dict[str, str]:
    """一定错的看板：每个编号都填同一个昵称。"""
    name = clients[0].name
    return {str(c.my_room_no): name for c in clients}


def partial_board(clients: list[WsClient]) -> dict[str, str]:
    """不完整但其余正确的看板：故意漏掉一个编号。"""
    board = correct_board(clients)
    board.pop(str(clients[-1].my_room_no), None)
    return board


async def act_all(clients: list[WsClient], actions: list[str]) -> None:
    """按顺序让每个人做一个 PHASE1 动作（skip / ask）。"""
    for c, kind in zip(clients, actions):
        if kind == "skip":
            await c.send("phase1:skip")
        elif kind == "ask":
            target = next(x for x in clients if x is not c)
            await c.send("phase1:ask", targetRoomNo=target.my_room_no, text=f"{c.name} 问 {target.name}")
        else:
            raise ValueError(kind)


async def finish_round(clients: list[WsClient], round_no: int, timeout: float = 8.0) -> None:
    """当前在 PHASE3(round_no)：全员确认 → 等下一轮的 PHASE1 广播。"""
    for c in clients:
        await c.send("phase3:confirm")
    for c in clients:
        await wait_phase(c, "PHASE1", round_no + 1, timeout=timeout)


async def skip_round(clients: list[WsClient], round_no: int, timeout: float = 8.0) -> None:
    """一整轮什么都不做：全员 SKIP → PHASE3 → 全员确认 → 进入下一轮。"""
    for c in clients:
        await c.send("phase1:skip")
    for c in clients:
        await wait_phase(c, "PHASE3", round_no, timeout=timeout)
    await finish_round(clients, round_no, timeout=timeout)


async def wait_phase(client: WsClient, phase: str, round_no: int | None = None, timeout: float = 8.0) -> dict:
    """等某个阶段广播。"""
    pred = None
    if round_no is not None:
        pred = lambda m: m.get("phase") == phase and m.get("round") == round_no  # noqa: E731
    else:
        pred = lambda m: m.get("phase") == phase  # noqa: E731
    msg = await client.wait_for("phase:changed", timeout=timeout, pred=pred)
    client.phase_log.append(msg)
    return msg


def phase_msg(client: WsClient, phase: str, round_no: int | None = None) -> dict:
    """从已经收到过的 phase:changed 里取一条（避免为了看字段再等一遍）。"""
    for m in reversed(client.phase_log):
        if m.get("phase") == phase and (round_no is None or m.get("round") == round_no):
            return m
    raise AssertionError(
        f"[{client.name}] 没有记录到 {phase}/{round_no}；已有：{[ (m.get('phase'), m.get('round')) for m in client.phase_log ]}"
    )


async def close_all(clients: list[WsClient]) -> None:
    for c in clients:
        await c.close()
    await asyncio.sleep(0)


# ----------------------------------------------------------------------
# 「映射泄露」探测器：服务端永远不该下发 编号→昵称
# ----------------------------------------------------------------------
def find_number_mappings(payload, n: int, path: str = "") -> list[str]:
    """递归找「以 1..n 编号为键、且键数量 ≥2」的对象，也就是映射表的形状。"""
    leaks: list[str] = []
    if isinstance(payload, dict):
        numeric_keys = [k for k in payload if str(k).isdigit() and 1 <= int(k) <= n]
        if len(numeric_keys) >= 2:
            leaks.append(path or "<root>")
        for k, v in payload.items():
            leaks.extend(find_number_mappings(v, n, f"{path}.{k}"))
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            leaks.extend(find_number_mappings(v, n, f"{path}[{i}]"))
    return leaks


def assert_no_mapping(messages: list[dict], n: int) -> None:
    """断言这批消息里没有任何 编号→昵称 映射表。"""
    leaks: list[str] = []
    for m in messages:
        for path in find_number_mappings(m, n):
            leaks.append(f"{m.get('type')}:{path}")
    assert not leaks, f"发现疑似映射下发：{leaks}"

# ----------------------------------------------------------------------
# 第 2 周：模式 / 写卡 / 阅读 / 重连
# ----------------------------------------------------------------------
async def set_mode(captain: "WsClient", mode: str) -> None:
    """队长切模式（SETUP 阶段）。"""
    await captain.send("setup:config", gameMode=mode)
    await captain.wait_for("room:state", pred=lambda m: m.get("gameMode") == mode, timeout=5)


def state_of(client: "WsClient") -> dict:
    """最近一条 room:state（不等新消息）。"""
    assert client.last_room_state is not None, f"[{client.name}] 还没收到过 room:state"
    return client.last_room_state


async def my_token(client: "WsClient", timeout: float = 5.0) -> str:
    """取自己的 reconnectToken：优先最近的 room:state，必要时再等一条。"""
    st = client.last_room_state
    token = ((st or {}).get("you") or {}).get("reconnectToken")
    if token:
        return token
    fresh = await client.wait_for(
        "room:state",
        pred=lambda m: bool((m.get("you") or {}).get("reconnectToken")),
        timeout=timeout,
    )
    return fresh["you"]["reconnectToken"]


async def submit_card(client: "WsClient", name: str, content: str = "这是一张测试人设卡。") -> dict:
    await client.send("card:submit", name=name, content=content)
    return await client.wait_for("card:submitted", timeout=5)


async def persona_room(ws_url: str, names: list[str], config: dict | None = None) -> list["WsClient"]:
    """建 PERSONA 房间并开局（停在 CARD_WRITING）。"""
    cfg = {"gameMode": "PERSONA", "readingSeconds": 5}
    if config:
        cfg.update(config)
    clients = await full_room(ws_url, names, config=cfg)
    await start_game(clients)
    for c in clients:
        await wait_phase(c, "CARD_WRITING", timeout=8)
        # 等 status 也同步到 CARD_WRITING（phase:changed 与 room:state 是两条消息）
        await c.wait_for(
            "room:state", pred=lambda m: m.get("status") == "CARD_WRITING", timeout=8
        )
    return clients


async def submit_all_cards(clients: list["WsClient"], prefix: str = "角色") -> list[str]:
    """每人交一张卡，返回卡名列表（与 clients 同序）。"""
    names: list[str] = []
    for i, c in enumerate(clients, 1):
        card_name = f"{prefix}{i}号"
        await submit_card(c, card_name, f"第 {i} 张卡面：{prefix}{i}号的故事，与昵称无关。")
        names.append(card_name)
    return names


async def assign_cards(captain: "WsClient") -> None:
    await captain.send("captain:startAssign")


async def wait_status(client: "WsClient", status: str, timeout: float = 8.0) -> dict:
    return await client.wait_for("room:state", pred=lambda m: m.get("status") == status, timeout=timeout)


async def collect_assigned(clients: list["WsClient"]) -> dict[str, dict]:
    """等每个人的 persona:assigned，并把卡名/编号记到 client 上。"""
    out: dict[str, dict] = {}
    for c in clients:
        msg = await c.wait_for("persona:assigned", timeout=8)
        c.assigned_card = msg.get("yourCard") or {}
        c.my_room_no = msg.get("yourRoomNo")
        c.room_nos = msg.get("roomNos") or []
        out[c.player_id] = msg
    return out


async def reconnect(ws_url: str, room_code: str, player_id: str, token: str) -> "WsClient":
    """新连接凭 token 回到座位（不自动断言成功）。"""
    c = await WsClient.connect(ws_url, "reconnect")
    c.player_id = player_id
    c.room_code = room_code
    await c.send("conn:reconnect", roomCode=room_code, playerId=player_id, token=token)
    return c


def card_board(clients: list["WsClient"]) -> dict[str, str]:
    """PERSONA 的正确答案：{编号: 自己被分配的卡名}。"""
    return {str(c.my_room_no): (getattr(c, "assigned_card", {}) or {}).get("name", "") for c in clients}


def shuffled_card_board(clients: list["WsClient"]) -> dict[str, str]:
    """一定错的 PERSONA 看板：把卡名整体错位一格。"""
    board = card_board(clients)
    keys = list(board)
    vals = [board[k] for k in keys]
    vals = vals[1:] + vals[:1]
    return {k: v for k, v in zip(keys, vals)}

# ----------------------------------------------------------------------
# 第 3 周：AI 相关
# ----------------------------------------------------------------------
AI_FAST = {
    "aiThinkSeconds": 0.3,
    "aiCardDelaySeconds": 0.2,
    "aiAnswerDelaySeconds": 0.3,
    "aiConfirmDelaySeconds": 0.2,
    "aiLlmTimeoutSeconds": 1.0,
}


def ai_config(**extra) -> dict:
    """把 AI 的各种延迟压到亚秒级，让测试跑得快。"""
    cfg = dict(AI_FAST)
    cfg.update(extra)
    return cfg


async def add_ai(captain: "WsClient", count: int = 1) -> dict:
    """队长添加 AI，等 room:state 与回执。"""
    await captain.send("room:addAI", count=count)
    ack = await captain.wait_for("room:aiAdded", timeout=8)
    return ack


async def fetch_ai_debug(base: str) -> dict:
    """读 /debug/ai（conftest 里给子进程开了 AI_DEBUG=1）。"""
    import httpx

    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(base + "/debug/ai")
    assert resp.status_code == 200, resp.text
    return resp.json()


def ai_prompts(debug: dict, kind: str | None = None) -> list[str]:
    """把 /debug/ai 里的 Prompt 摊平成文本列表。"""
    out: list[str] = []
    for ai in debug.get("ais", []):
        for item in ai.get("prompts", []):
            if kind and item.get("kind") != kind:
                continue
            out.append((item.get("system") or "") + "\n" + (item.get("user") or ""))
    return out


def ai_decisions(debug: dict, kind: str | None = None, room: str | None = None) -> list[dict]:
    """摊平 /debug/ai 的 AI 留痕；可按 kind 和房间码过滤（同一进程里可能残留别的房间）。"""
    out: list[dict] = []
    for item in debug.get("log", []):
        if kind and item.get("kind") != kind:
            continue
        if room and item.get("room") != room:
            continue
        payload = item.get("payload")
        if isinstance(payload, dict):
            out.append({**payload, "_nickname": item.get("nickname"), "_room": item.get("room")})
    return out

async def wait_ai_decision(
    base: str, room_code: str, kind: str = "phase1", timeout: float = 15.0
) -> list[dict]:
    """轮询 /debug/ai，直到某个房间的 AI 留下指定 kind 的决策。"""
    import asyncio
    import time

    deadline = time.time() + timeout
    last: list[dict] = []
    while time.time() < deadline:
        debug = await fetch_ai_debug(base)
        last = ai_decisions(debug, kind, room=room_code)
        if last:
            return last
        await asyncio.sleep(0.2)
    return last
