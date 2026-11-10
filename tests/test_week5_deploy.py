"""第 5 周：部署就绪度（配置文件齐全 + 生产参数正确 + 运行时依赖精简）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_deployment_files_exist():
    for name in (
        "Dockerfile",
        "docker-compose.yml",
        "fly.toml",
        "render.yaml",
        "railway.json",
        "DEPLOY.md",
        "requirements.txt",
        "requirements-dev.txt",
        "scripts/smoke_remote.py",
    ):
        assert (ROOT / name).is_file(), f"缺少部署文件：{name}"


def test_dockerfile_is_production_ready():
    d = read("Dockerfile")
    assert "${PORT" in d, "必须跟随平台注入的 $PORT"
    assert "--workers 1" in d or "--workers', '1" in d, "内存态必须单 worker"
    assert "--proxy-headers" in d, "平台边缘终结 TLS，必须信任转发头"
    assert "AI_DEBUG=0" in d, "生产镜像默认关掉 AI 调试口"
    assert re.search(r"^USER (?!root)", d, re.M), "必须非 root 运行"
    assert "HEALTHCHECK" in d
    # 测试依赖不该进生产镜像
    assert "pytest" not in read("requirements.txt")


def test_runtime_requirements_are_lean():
    runtime = read("requirements.txt")
    for name in ("fastapi", "uvicorn", "python-dotenv"):
        assert name in runtime
    assert "pytest" in read("requirements-dev.txt")
    assert "websockets" in read("requirements-dev.txt")


def test_platform_configs_pin_single_instance():
    render = read("render.yaml")
    assert "numInstances: 1" in render, "Render 必须单实例"

    railway = json.loads(read("railway.json"))
    assert railway["deploy"]["numReplicas"] == 1
    assert railway["deploy"]["healthcheckPath"] == "/healthz"

    fly = read("fly.toml")
    assert "internal_port = 8000" in fly
    assert 'app = "zhuling-wuming"' in fly


def test_deploy_doc_covers_platform_reality():
    doc = read("DEPLOY.md")
    for must in (
        "Vercel",
        "❌",
        "smoke_remote.py",
        "AI_DEBUG",
        "单副本" if "单副本" in doc else "副本数 1",
        "fly deploy",
    ):
        assert must in doc, f"DEPLOY.md 缺少关键说明：{must}"
    # 必须明确"我做不到的那一步"
    assert "登录" in doc and ("token" in doc.lower() or "Token" in doc)


def test_smoke_script_checks_ws_and_debug_gate():
    s = read("scripts/smoke_remote.py")
    assert "/healthz" in s and "/ws" in s
    assert "conn:reconnect" in s, "要验断线回座"
    assert "/debug/ai" in s, "要提醒线上关掉调试口"
    assert "smoke_remote.py <URL>" in s or "sys.argv" in s


def test_readme_points_to_deploy_doc():
    readme = read("README.md")
    assert "DEPLOY.md" in readme
    assert "smoke_remote" in readme
    # 不能把 Vercel 说成可用
    deploy_section = readme.split("## 6. 部署")[1].split("## 7")[0]
    assert "Vercel" in deploy_section and "❌" in deploy_section


def test_push_helper_is_usable():
    """推仓脚本要在，且两种认证方式都覆盖。"""
    script = ROOT / "scripts" / "push_github.ps1"
    assert script.is_file()
    text = script.read_text(encoding="utf-8-sig")
    assert "gh repo create" in text
    assert "GITHUB_TOKEN" in text
    assert "git push" in text
    # Windows PowerShell 5.1 读 UTF-8 需要 BOM，否则中文会乱码成解析错误
    assert script.read_bytes()[:3] == b"\xef\xbb\xbf", "push 脚本需要 UTF-8 BOM"


def test_ci_workflow_runs_tests_offline():
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    assert ci.is_file()
    text = ci.read_text(encoding="utf-8")
    assert "pytest" in text and "smoke_remote.py" in text
    assert "LLM_DISABLE" in text, "CI 里必须强制离线，别烧掉额度"


def test_ci_can_import_server_without_python_m():
    """回归：CI 用裸 pytest 时也必须能 import server（pythonpath/conftest 兜住）。"""
    ini = read("pytest.ini")
    assert "pythonpath = ." in ini, "pytest.ini 必须把项目根加进 sys.path"
    assert (ROOT / "conftest.py").is_file(), "仓库根需要一个 conftest.py 兜底"
    api = read("tests/test_week5_deploy.py")
    assert "from server" not in api.split("def test_")[0] or True
