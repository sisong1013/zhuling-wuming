# 第 3 周 · Step 3.6：AI 记忆与看板推理（防泄题）

- 状态：**完成**（本步 6 条用例全绿；第 1/2 周 128 条回归同时保持全绿）

## 改了哪些文件

- `server/ai_agent.py`：`AIMemory`（公开历史 + 看板 + 置信度）、`public_qa_lines()`、`board_lines()`；Prompt 只含公开信息
- `server/main.py`：`/debug/ai`（仅 `AI_DEBUG=1` 开放）暴露 Prompt/决策留痕，测试用它做泄题扫描
- `tests/test_week3_step6_ai_memory.py`：6 条用例（含 4 条防泄题/推理断言）

## 测试

本步新增 **6** 条用例。

## 已知限制

- 防泄题靠「同一行不得同时出现某个人的编号与昵称」来判定，属结构性断言，不排除更隐蔽的措辞泄露
- `/debug/ai` 里带了 `truth` 字段（供自动化收尾），**只在 AI_DEBUG=1 时存在**，正式环境该端点 404

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
