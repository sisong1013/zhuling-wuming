# 第 3 周 · Step 3.1：LLM 客户端封装

- 状态：**完成**（本步 8 条用例全绿；第 1/2 周 128 条回归同时保持全绿）

## 改了哪些文件

- `server/llm_client.py`（新）：`call_llm()` / `call_llm_json()` / `parse_json()` / `is_available()` / `stats()`
- `server/main.py`：启动时尝试 `load_dotenv()` 读 `.env`（装了 python-dotenv 才生效，缺失不报错）
- `tests/test_week3_step1_llm.py`：8 条用例

## 测试

本步新增 **8** 条用例。

## 已知限制

- 没配 `LLM_API_KEY` 时**不发任何请求**，直接返回空串（省一次 15s 超时）
- 超时/HTTP 错误/非 JSON 一律返回空串 + 一条 warning 日志，绝不抛异常

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
