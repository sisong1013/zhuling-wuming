# 第 3 周 · Step 3.7：整局人机混战

- 状态：**完成**（本步 2 条用例全绿；第 1/2 周 128 条回归同时保持全绿）

## 改了哪些文件

- `tests/test_week3_step7_full_ai.py`：2 条用例（PERSONA 2 真人 + 2 AI / REAL 2 真人 + 1 AI）

## 测试

本步新增 **2** 条用例。

## 已知限制

- 「整局跑到结束」用调试口读真值收尾，否则 4 人局的看板几乎不可能全对（游戏本身没有必赢推理路径）
- AI 在阅读阶段视为已示意、回放阶段 1–3s 自动确认，避免卡住全员门槛

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
