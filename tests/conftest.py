"""pytest 公共设施：起一个真实 uvicorn 子进程，测试用真正的 WebSocket 客户端连它。

为什么不用 TestClient：我们需要真实的多条并发 WebSocket 连接
（多人热座、并行提问），用真端口最省心。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

GAME_DIR = Path(__file__).resolve().parents[1]
SERVER_LOG = Path(tempfile.gettempdir()) / "guesswho-server.log"


def _free_port() -> int:
    """问内核要一个空闲端口，避免并行跑测试时撞端口。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def server_base() -> str:
    """启动一个 uvicorn 子进程，返回 http://127.0.0.1:PORT 。"""
    port = _free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(GAME_DIR)
    env["PYTHONUNBUFFERED"] = "1"
    env["AI_DEBUG"] = "1"          # 暴露 /debug/ai（只读，测试用）
    env.pop("LLM_API_KEY", None)   # 测试一律不真的调 LLM
    env["LLM_DISABLE"] = "1"       # 即使 config/llm.json 里有 key 也强制离线
    log_fh = SERVER_LOG.open("wb")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(GAME_DIR),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 40
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            if httpx.get(base + "/healthz", timeout=0.5).status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.1)
    if not ready:
        proc.terminate()
        tail = SERVER_LOG.read_text(encoding="utf-8", errors="replace")[-3000:]
        raise RuntimeError(f"服务端没能启动，日志尾部：\n{tail}")
    try:
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_fh.close()


@pytest.fixture
def base(server_base: str) -> str:
    return server_base


@pytest.fixture
def ws_base(base: str) -> str:
    return base.replace("http://", "ws://") + "/ws"
