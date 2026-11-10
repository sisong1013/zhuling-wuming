"""运行期依赖完整性：server/ 里 import 的第三方模块，必须都在 requirements.txt 里。

为什么要有这条：生产镜像只装 requirements.txt；如果某个模块被挪到 requirements-dev.txt，
本地因为装了 dev 依赖不会暴露，但线上会 `ModuleNotFoundError` 直接起不来
（Railway 上就是"构建成功、健康检查失败"）。这个坑真实发生过一次（httpx）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"

# 模块名 → 分发名（requirements 里写的是分发名）
DIST_ALIAS = {
    "dotenv": "python-dotenv",
    "starlette": "fastapi",
    "pydantic": "fastapi",
    "pydantic_core": "fastapi",
    "anyio": "fastapi",
}
# uvicorn[standard] 带来的可选依赖，不用单独写
PROVIDED = {"uvicorn", "fastapi", "python-dotenv", "httpx"}

IMPORT_RE = re.compile(r"^(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)


def _runtime_modules() -> set[str]:
    mods: set[str] = set()
    for path in SERVER.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for mod in IMPORT_RE.findall(text):
            if mod == "server":
                continue
            if mod in getattr(sys, "stdlib_module_names", set()):
                continue
            mods.add(mod)
    return mods


def test_server_imports_are_covered_by_runtime_requirements():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    missing = []
    for mod in sorted(_runtime_modules()):
        dist = DIST_ALIAS.get(mod, mod)
        if dist in PROVIDED or dist in req:
            continue
        missing.append(f"{mod} (应该是 {dist})")
    assert not missing, (
        "生产镜像只装 requirements.txt，但 server/ 依赖了这些未声明的包："
        + ", ".join(missing)
    )


def test_httpx_is_a_runtime_dependency():
    """LLM 客户端直接 import httpx，它必须在运行期依赖里。"""
    assert "httpx" in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "httpx" in (SERVER / "llm_client.py").read_text(encoding="utf-8")


def test_dev_requirements_include_runtime():
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in dev, "dev 依赖应当继承运行期依赖"
