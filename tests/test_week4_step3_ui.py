"""Step 4.3：前端静态资源与容器冒烟测试（防前端炸掉）。"""

from __future__ import annotations

import re

import httpx
import pytest

HTML_ASSETS = ["/", "/static/index.html"]
CSS_ASSETS = ["/static/style.css", "/static/style.v4.css", "/static/style.v5.css"]
ASSET_EXTRAS = ["/static/favicon.svg", "/favicon.ico", "/static/og.png"]
JS_ASSETS = [
    "/static/js/mycard.js",
    "/static/app.js",
    "/static/js/ws.js",
    "/static/js/ui.js",
    "/static/js/timer.js",
    "/static/js/board.js",
    "/static/js/lobby.js",
    "/static/js/waiting.js",
    "/static/js/card.js",
    "/static/js/reading.js",
    "/static/js/phase1.js",
    "/static/js/phase2.js",
    "/static/js/phase3.js",
    "/static/js/over.js",
]

REQUIRED_IDS = [
    "stage",
    "board",
    "timer",
    "hud",
    "view",
    "side",
    "feed",
    "roster",
    "conn",
    "btn-open-board",
    "toasts",
]

REQUIRED_MODULES = [
    "js/ws.js",
    "js/lobby.js",
    "js/waiting.js",
    "js/card.js",
    "js/reading.js",
    "js/phase1.js",
    "js/phase2.js",
    "js/phase3.js",
    "js/board.js",
    "js/over.js",
]


def _get(base: str, path: str) -> httpx.Response:
    return httpx.get(base + path, timeout=10)


@pytest.mark.parametrize("path", HTML_ASSETS + CSS_ASSETS + JS_ASSETS + ASSET_EXTRAS)
def test_static_assets_are_served(base, path):
    """所有静态资源都能取到，且不是 404。"""
    resp = _get(base, path)
    assert resp.status_code == 200, f"{path} → {resp.status_code}"
    assert resp.text.strip(), f"{path} 内容为空"


def test_html_has_required_containers(base):
    """关键容器 id 必须在（UI 冒烟的最低保障）。"""
    html = _get(base, "/").text
    for node_id in REQUIRED_IDS:
        assert re.search(rf'id="{node_id}"', html), f"缺少容器 #{node_id}"


def test_app_js_wires_all_modules(base):
    """入口必须 import 到所有视图模块（拆错文件名会立刻暴露）。"""
    js = _get(base, "/static/app.js").text
    for module in REQUIRED_MODULES:
        assert module in js, f"app.js 没有引用 {module}"


def test_no_legacy_monolith_leftovers(base):
    """旧版单体 app.js 不应再被页面引用。"""
    html = _get(base, "/").text
    assert "app.legacy.js" not in html
    assert _get(base, "/static/app.js").status_code == 200


def test_each_module_is_esm(base):
    """每个模块都必须是 ES Module（有 export），而不是脚本片段。"""
    for path in JS_ASSETS:
        if path == "/static/app.js":
            continue
        body = _get(base, path).text
        assert "export " in body, f"{path} 没有 export"


def test_style_defines_responsive_and_glass(base):
    """响应式断点与玻璃质感类必须在样式里。"""
    css = _get(base, "/static/style.v4.css").text
    assert "backdrop-filter" in css
    assert "@media (max-width: 900px)" in css
    assert "100dvh" in css


async def test_dom_renders_without_console_errors(base):
    """有 Playwright 就真开浏览器；没有就退化为静态断言（任务允许的兜底）。"""
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception:
        html = _get(base, "/").text
        assert 'type="module"' in html
        assert "/static/app.js" in html
        assert all(re.search(rf'id="{i}"', html) for i in REQUIRED_IDS)
        return

    errors: list[str] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(base + "/", wait_until="networkidle")
        await page.wait_for_selector("#view .card", timeout=8000)
        assert await page.is_visible("#view")
        assert await page.is_visible("#stage")
        await browser.close()

    real_errors = [e for e in errors if "chrome-extension://" not in e]
    assert not real_errors, f"浏览器控制台有报错：{real_errors}"

def test_brand_meta_and_favicon(base):
    """图标 / 描述 / 品牌名齐备，且 favicon 不再 404。"""
    html = _get(base, "/").text
    assert 'rel="icon"' in html and "/static/favicon.svg" in html
    assert 'name="description"' in html
    assert 'name="game-name"' in html and "诸伶无名" in html
    assert "THE NAMELESS TROUPE" in html
    assert "谁是几号" not in html, "旧名字不该再出现"

    ico = _get(base, "/favicon.ico")
    assert ico.status_code == 200
    assert "svg" in ico.headers.get("content-type", "")

    health = _get(base, "/healthz").json()
    assert health["service"] == "zhuling-wuming"

def test_share_card_meta(base):
    """分享卡片：og/twitter meta 齐备，且 og:image 是绝对地址。"""
    html = _get(base, "/").text
    assert 'property="og:image"' in html
    assert "/static/og.png" in html
    assert base.rstrip("/") in html, "og:image 应该是绝对地址"
    assert 'name="twitter:card"' in html
    assert "summary_large_image" in html
    assert "__OG_BASE__" not in html, "占位符必须被替换掉"
