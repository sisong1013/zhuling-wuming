"""应用入口：静态页托管 + WebSocket 通道 + 内存注册表装配。

第一周「热座版」：单进程、纯内存、无数据库、无账号、无断线重连。
本文件只负责装配，游戏逻辑在 models / rules / state_machine / ws_handlers。
"""

from __future__ import annotations

import json
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# 可选依赖：装了 python-dotenv 就自动读 .env
# 查找顺序：game/.env（推荐）→ 当前工作目录/.env → dotenv 自己向上搜索
GAME_ROOT = Path(__file__).resolve().parents[1]

def load_local_llm_config() -> Path | None:
    """额外支持 config/llm.json（便于脚本化配置，不碰 .env）。

    形如：{"apiKey": "...", "baseUrl": "...", "model": "...", "fallbacks": ["..."]}
    已存在的环境变量优先，这里只补空缺。
    """
    path = GAME_ROOT / "config" / "llm.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("读取 config/llm.json 失败：%s", exc)
        return None

    mapping = {
        "LLM_API_KEY": data.get("apiKey"),
        "LLM_BASE_URL": data.get("baseUrl"),
        "LLM_MODEL": data.get("model"),
        "LLM_MAX_TOKENS": data.get("maxTokens"),
    }
    for key, value in mapping.items():
        if value and not os.environ.get(key):
            os.environ[key] = str(value)

    fallbacks = data.get("fallbacks")
    if fallbacks and not os.environ.get("LLM_MODEL_FALLBACKS"):
        os.environ["LLM_MODEL_FALLBACKS"] = ",".join(str(x) for x in fallbacks)
    return path


ENV_CANDIDATES = (GAME_ROOT / ".env", Path.cwd() / ".env")
ENV_FILE: Path | None = None
try:
    from dotenv import load_dotenv

    for _candidate in ENV_CANDIDATES:
        if _candidate.is_file():
            load_dotenv(_candidate, override=False)  # 已存在的环境变量优先，.env 只补缺
            ENV_FILE = _candidate
            break
    else:  # 都没找到就交给 dotenv 自己从 cwd 往上找
        load_dotenv()
except Exception:  # noqa: BLE001 - 没装 python-dotenv 也不影响开服
    load_dotenv = None  # type: ignore[assignment]

from . import llm_client, rules, ws_handlers
from .state_machine import GameRegistry

STATIC_DIR = Path(__file__).resolve().parent / "static"

log = logging.getLogger("game")
LLM_CONFIG_FILE = load_local_llm_config()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# 全局单例：一个进程一套内存状态
HUB = ws_handlers.ConnectionHub()
REGISTRY = GameRegistry(HUB)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await REGISTRY.start_watchdog()  # 心跳看门狗（第 2 周）
    log.info("桌上剧团 · 诸伶无名 启动（内存态）")
    if llm_client.is_available():
        log.info(
            "LLM 已就绪：model=%s base=%s（来源：%s）",
            llm_client.model_name(),
            llm_client.base_url(),
            ENV_FILE or LLM_CONFIG_FILE or "环境变量",
        )
    else:
        log.info("LLM 未配置：AI 将使用确定性兜底（见 game/env.example 的配置说明）")
    yield
    await REGISTRY.stop_watchdog()
    await REGISTRY.timers.shutdown()
    log.info("桌上剧团关闭")


app = FastAPI(title="桌上剧团 · 诸伶无名", version="0.1.0", lifespan=lifespan)

# 静态资源（原生 HTML + CSS + ES Module，不用任何前端框架）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index(request: Request) -> HTMLResponse:
    """入口页：顺手把 og:image 的绝对地址注入进去（分享卡片需要绝对 URL）。"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    origin = str(request.base_url).rstrip("/")
    return HTMLResponse(html.replace("__OG_BASE__", origin))


@app.get("/debug/ai")
async def debug_ai() -> dict:
    """AI 观测口（仅 AI_DEBUG=1 时开放）：LLM 状态 + AI 的 Prompt/决策留痕。

    测试用它抓「Prompt 里有没有泄露编号→昵称映射」。
    """
    if os.environ.get("AI_DEBUG") != "1":
        raise HTTPException(status_code=404, detail="not found")
    ais = []
    for room in REGISTRY.rooms.values():
        for p in room.players.values():
            if not p.is_ai:
                continue
            mem = p.ai_memory
            ais.append(
                {
                    "room": room.code,
                    "playerId": p.id,
                    "nickname": p.nickname,
                    "roomNo": p.room_no,
                    "prompts": list(getattr(mem, "prompts", []))[-6:],
                    "decisions": list(getattr(mem, "decisions", []))[-30:],
                    "board": {str(k): v for k, v in getattr(mem, "board", {}).items()},
                }
            )
    rooms = [
        {
            "roomCode": room.code,
            "status": room.status,
            "gameMode": room.game_mode,
            "round": room.round,
            # ⚠️ 仅 AI_DEBUG=1（自动化测试）时下发真值，用于「整局跑到结束」的收尾；
            #    游戏逻辑从不读这个字段，正式环境该端点直接 404。
            "truth": {str(k): v for k, v in rules.truth_for(room).items()},
        }
        for room in REGISTRY.rooms.values()
    ]
    return {
        "llm": llm_client.stats(),
        "ais": ais,
        "log": REGISTRY.ai_log[-80:],
        "rooms": rooms,
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """浏览器默认会来要 /favicon.ico；直接回 SVG 图标，免得日志里天天 404。"""
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/healthz")
async def healthz() -> dict:
    """健康检查，测试启动时用它确认端口已就绪。"""
    return {"ok": True, "service": "zhuling-wuming", "week": 4, "rooms": len(REGISTRY.rooms)}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """唯一的 WebSocket 入口：一条连接一个 Session。"""
    await ws.accept()
    session = ws_handlers.Session(ws=ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await session.send({"type": "error", "code": "BAD_JSON", "message": "消息不是合法 JSON"})
                continue
            if not isinstance(msg, dict):
                await session.send({"type": "error", "code": "BAD_JSON", "message": "消息必须是对象"})
                continue
            await ws_handlers.dispatch(REGISTRY, session, msg)
    except WebSocketDisconnect:
        pass
    finally:
        if session.player_id:
            REGISTRY.unregister_session(session.player_id, session)
            HUB.unbind(session.player_id, ws)
            room = REGISTRY.mark_disconnected(session.player_id)
            if room is not None:
                await REGISTRY.broadcast_state(room)
