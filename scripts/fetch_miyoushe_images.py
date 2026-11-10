"""从米游社帖子抓取「桌上剧团」壁纸图，下载到指定目录。

用法: python fetch_miyoushe_images.py [post_id] [out_dir]

- 图片清单优先取 post.images；
- 若 structured_content 里有折叠标题（角色名），就把文件命名成「壁纸-角色名.png」。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

API = "https://bbs-api.miyoushe.com/post/wapi/getPostFull?post_id={post_id}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://m.miyoushe.com/",
    "Accept": "application/json, text/plain, */*",
}


def get_post(post_id: str) -> dict:
    req = urllib.request.Request(API.format(post_id=post_id), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return data["data"]["post"]["post"]


def fold_titles(structured: str) -> list[tuple[str, str]]:
    """从 structured_content 里抽出 (标题, 图片URL) 的对应关系。"""
    pairs: list[tuple[str, str]] = []
    if not structured:
        return pairs
    try:
        blocks = json.loads(structured)
    except Exception:  # noqa: BLE001
        return pairs
    for block in blocks:
        ins = block.get("insert")
        if not isinstance(ins, dict):
            continue
        fold = ins.get("fold")
        if not fold:
            continue
        title_raw = fold.get("title", "")
        content_raw = fold.get("content", "")
        name = ""
        try:
            for tb in json.loads(title_raw):
                if isinstance(tb.get("insert"), str):
                    name += tb["insert"].strip()
        except Exception:  # noqa: BLE001
            pass
        url = ""
        try:
            for cb in json.loads(content_raw):
                v = cb.get("insert")
                if isinstance(v, dict) and v.get("image"):
                    url = v["image"]
                    break
        except Exception:  # noqa: BLE001
            pass
        if url:
            pairs.append((name or "", url))
    return pairs


def safe(name: str) -> str:
    return re.sub(r'[*"/\\:<>|?\r\n]+', "_", name).strip() or "未命名"


def main() -> None:
    post_id = sys.argv[1] if len(sys.argv) > 1 else "76771479"
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\相册\桌上剧团")
    out_dir.mkdir(parents=True, exist_ok=True)

    post = get_post(post_id)
    subject = post.get("subject", "")
    print("标题:", subject)
    print("UID:", post.get("uid"), "图片数:", len(post.get("images") or []))

    pairs = fold_titles(post.get("structured_content") or "")
    named = {url: name for name, url in pairs if name}

    urls = list(post.get("images") or [])
    for _, u in pairs:
        if u not in urls:
            urls.append(u)

    ok = 0
    for i, url in enumerate(urls, 1):
        ext = url.rsplit(".", 1)[-1].lower()
        base = named.get(url)
        fname = f"壁纸-{safe(base)}.{ext}" if base else f"壁纸 {i:02d}.{ext}"
        target = out_dir / fname
        if target.exists():
            print(f"  跳过已存在: {fname}")
            ok += 1
            continue
        try:
            req = urllib.request.Request(url, headers={**HEADERS, "Accept": "image/*"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                blob = resp.read()
            target.write_bytes(blob)
            print(f"  OK {fname}  {len(blob)/1024/1024:.2f} MB")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {url} -> {exc}")
    print(f"完成：{ok}/{len(urls)} -> {out_dir}")


if __name__ == "__main__":
    main()
