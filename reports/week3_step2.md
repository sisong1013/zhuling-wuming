# 第 3 周 · Step 3.2：添加 AI 玩家（room:addAI）

- 状态：**完成**（本步 6 条用例全绿；第 1/2 周 128 条回归同时保持全绿）

## 改了哪些文件

- `server/state_machine.py`：`add_ai_players()`（1–2 个/次）、`add_ai_player()`（兼容旧事件）、`_next_ai_nickname()`（预设名池）
- `server/ws_handlers.py`：新事件 `room:addAI {count}` → 回 `room:aiAdded`
- `server/models.py`：`Player.ai_memory`；`public_view()` 增加 `isAi`
- `static/index.html` + `static/app.js` + `static/style.css`：团长台新增「玩法」「陪演（AI）」两行按钮，名册打 AI 标签
- `tests/test_week3_step2_add_ai.py`：6 条用例

## 测试

本步新增 **6** 条用例。

## 已知限制

- AI 没有 WebSocket 连接，`connected=1`（占位在线）；重连 API 对 AI 不适用

## 下一步

见 `reports/week3_final.md`。

## 验证

```bash
cd game
bash scripts/selftest.sh                              # 全量（第 1/2/3 周）
bash scripts/selftest.sh tests/test_week3_stepX_*.py   # 单步
```

> 本机没有配 `LLM_API_KEY`，所有 AI 用例跑的是**兜底路径**（确定性决策/台词）；
> LLM 真正联网的那条路径由 `test_week3_step1_llm.py` 用 monkeypatch 覆盖（成功/超时/500/JSON 围栏）。
