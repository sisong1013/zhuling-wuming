"""Round-4 layout fixes from the art director's final review."""

from __future__ import annotations

from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "server" / "static" / "style.css"
css = CSS.read_text(encoding="utf-8")

reps: list[tuple[str, str]] = [
    # 1) 看板 4 格同行，不再 3+1
    (".board { display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); gap: 14px; }",
     ".board { display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 12px; }"),
    # 2) 头部改成「统计 + 提示」同一行，右侧不再留空
    (".game-head { display: flex; flex-direction: column; gap: 10px; }",
     """.game-head { display: flex; flex-wrap: wrap; align-items: stretch; gap: 10px; }"""),
    (""".pill-group {
  display: grid;
  grid-template-columns: repeat(4, minmax(96px, 138px));
  gap: 8px;
}
@media (max-width: 720px) {
  .pill-group { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}""",
     """.pill-group {
  display: grid;
  grid-template-columns: 126px minmax(150px, auto) 126px 126px;
  gap: 8px;
}
@media (max-width: 720px) {
  .pill-group { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}"""),
    # 3) 幕次不再折行
    ("""#phase-name {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 15px;
  letter-spacing: 0.5px;
  line-height: 1.35;
  max-width: 152px;
}""",
     """#phase-name {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 15px;
  letter-spacing: 0;
  line-height: 1.35;
  white-space: nowrap;
  max-width: none;
}"""),
    # 4) 提示条进同一行、吃掉右侧空白
    (""".phase-hint {
  margin: 0;
  padding: 10px 15px;""",
     """.phase-hint {
  flex: 1 1 300px;
  display: flex;
  align-items: center;
  min-height: 100%;
  margin: 0;
  padding: 10px 16px;"""),
    # 5) 两栏等高
    (".game-body { display: grid; grid-template-columns: 1.05fr 1fr; gap: 18px; align-items: start; }",
     ".game-body { display: grid; grid-template-columns: 1.05fr 1fr; gap: 18px; align-items: stretch; }"),
    # 6) 问答区与操作区的分界再加一道内线
    ("  box-shadow: 0 1px 4px rgba(60, 40, 60, 0.13) inset;",
     "  box-shadow:\n    0 0 0 1px rgba(176, 132, 66, 0.3) inset,\n    0 1px 4px rgba(60, 40, 60, 0.12) inset;"),
    # 7) 底部尾花上移，吸收左栏余量
    ("  margin-top: 18px;\n  height: 22px;", "  margin-top: auto;\n  padding-top: 18px;\n  height: 22px;"),
]

missing: list[str] = []
for old, new in reps:
    if old in css:
        css = css.replace(old, new, 1)
    else:
        missing.append(old.strip()[:60])

CSS.write_text(css, encoding="utf-8")
print("missing:", missing)
