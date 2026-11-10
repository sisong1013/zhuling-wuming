# 第 3 周交付报告：人机混战（AI 玩家接入）

> 状态：**Step 3.1–3.7 全部完成，无 BLOCKED**。
> 全量自动验收：`bash scripts/selftest.sh` → **163 passed**（第 1 周 64 + 第 2 周 64 + 第 3 周 35），退出码 0。
> 无 xfail / 无 skip / 未删改任何旧断言。

---

## 1. 怎么开（含 LLM 配置）

### 1.1 不接 LLM 也能玩

AI 有确定性兜底：会自己写卡（固定池）、按人设说一句套模板的台词、第一幕「提问 → 冷却则放弃 → 强制轮交看板」。
所以**零配置**就能跑人机局：

```bash
cd game
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/ → 组建剧团 → 团长台「+1 AI / +2 AI」→「人设卡」→ 开演
```

### 1.2 接真 LLM（OpenAI 兼容接口）

在 `game/` 下放一个 `.env`（或直接设环境变量）：

```ini
LLM_API_KEY=sk-你的key
LLM_BASE_URL=https://api.openai.com/v1     # 也可换成任何兼容网关
LLM_MODEL=gpt-4o-mini                     # 便宜档；国内可换 qwen-turbo / glm-flash
```

模板见仓库里 `game/env.example`（`cp env.example .env` 再填 Key）。
`server/main.py` 启动时会尝试 `load_dotenv("game/.env")`；没装 python-dotenv 也不会崩，只是不读文件。
配置是否生效看 `GET /debug/ai` 的 `llm.configured`（需 `AI_DEBUG=1`）。

**成本估算**（按 `gpt-4o-mini` 官方价，input $0.15 / output $0.60 每百万 token）：

| 场景 | 每局调用 | 估算 token | 估算成本 |
| --- | --- | --- | --- |
| 写卡 1 次 | 1 | ~350 in / 90 out | ~$0.0001 |
| 第一幕决策（每轮每 AI 1 次） | 5–12 | ~700 in / 120 out | ~$0.0002 / 次 |
| 作答（每次被问） | 3–8 | ~450 in / 80 out | ~$0.0001 / 次 |
| **一局 4 人（2 AI）× 8 轮** | ~25 | ~15k | **≈ $0.004（4 分钱人民币级别）** |

单个 AI 每局约 $0.002。想再省：把 `LLM_MODEL` 换成 `qwen-turbo` 或更小模型；或把 `aiThinkSeconds` 调大减少轮次。

---

## 2. 架构与关键设计

```
client ──ws──> ws_handlers.dispatch ──> GameRegistry（状态机）
                                          ├── ai_agent（Prompt/记忆/决策）──> llm_client ──> LLM
                                          └── ai.py（离线兜底生成）
```

- **AI 无特权**：一切动作都调用真人的 `action_ask / action_submit / action_skip / action_answer / action_confirm`，
  冷却、强制轮、阶段校验、错误码完全同一套；被拒就降级（例如冷却中 → 放弃本轮）。
- **AI 无上帝视角**：Prompt 只组装「自己的编号 + 自己拿到的卡 + 公开问答历史 + 全场卡名/昵称表（公开）+ 可选目标编号」。
  绝不注入「编号 → 真人 / 编号 → 卡」的映射。测试用「同一行不得同时出现某人的编号与昵称」做结构性扫描（含真实对局的 Prompt）。
- **记忆**：`AIMemory` 存公开问答（谁问谁什么、怎么答的）+ 自己的看板与置信度；每轮决策都基于它自己积累的历史。
- **节奏**：写卡延迟（默认 2s）、第一幕思考 0.8–1.7 倍随机（基准 6s，即 5–10s）、作答按字数 2–5s、回放确认 1–3s。
  全部可配（`aiCardDelaySeconds / aiThinkSeconds / aiAnswerDelaySeconds / aiConfirmDelaySeconds / aiLlmTimeoutSeconds`）。
- **绝不卡死**：LLM 未配置 / 超时（15s）/ HTTP 错误 / 非法 JSON → 立刻走兜底，游戏照常推进。

## 3. 新增事件与字段

client → server：`room:addAI {count}`（1–2，仅队长、仅等待室）
server → client：`room:aiAdded {players, count}`、`ai:thinking {playerId, nickname, kind}`、
`persona:assigned` / `card:progress` / `card:submitted` / `reading:progress`（第 2 周已有，前端本周补齐）

新增调试口：`GET /debug/ai`（**仅 `AI_DEBUG=1`**）：`{llm, ais[{nickname,roomNo,prompts,decisions,board}], log, rooms[{truth}]}`。
`truth` 仅供自动化收尾，正式环境该端点 404。

## 4. 测试结果

| 文件 | 用例 | 结果 |
| --- | --- | --- |
| `test_week3_step1_llm.py` | 8 | ✅ |
| `test_week3_step2_add_ai.py` | 6 | ✅ |
| `test_week3_step3_ai_card.py` | 4 | ✅ |
| `test_week3_step4_ai_phase1.py` | 6 | ✅ |
| `test_week3_step5_ai_answer.py` | 4 | ✅ |
| `test_week3_step6_ai_memory.py` | 6 | ✅ |
| `test_week3_step7_full_ai.py` | 2 | ✅ |
| 第 1/2 周回归 | 128 | ✅ |
| **合计** | **163** | ✅ 163 passed / 0 failed |

## 5. BLOCKED 项

**无。** 本机没有 `LLM_API_KEY`，按任务预案**用兜底 + mock 继续**：
- 真实联网路径由 `test_week3_step1_llm.py` 用 monkeypatch 覆盖（成功 / 超时 / 502 / JSON 围栏）。
- 游戏内 AI 行为在无 Key 下走确定性兜底，全部流程测试通过。
- 想验证真 LLM：配好 `.env` 后跑 `bash scripts/selftest.sh tests/test_week3_step7_full_ai.py`，AI 的台词与看板会变成模型输出。

## 6. 已知限制

1. 一局只能挂 2 个 AI（`room:addAI` 限 1–2），且只能在等待室加。
2. AI 的「像不像人设」纯靠 Prompt；没有二次校验，模型跑偏就会说出戏的话。
3. 防泄题测试是结构性的（编号/昵称同行扫描），不能证明绝对无泄露。
4. AI 在 `READING` 视为已示意、`PHASE3` 1–3s 自动确认——严格说要「模拟玩家」，但为了不卡住门槛做了简化。
5. 无 token 预算控制、无并发限流；多个 AI 同时决策会各打一次 LLM。
6. `AIMemory` 只增不减（一局内最多几十条），跨局不保留。

## 7. 第 4 周待办

1. **AI 策略升级**：让模型基于历史做「谁在撒谎」的推理，而不是每轮独立决策；引入置信度更新与主动追问。
2. **看板推理闭环**：AI 提交前先自检「自己那格必然对」，其余按置信度排序，提高无外挂下的胜率。
3. **成本与稳定性**：加 token 预算/速率限制、失败重试与降级模型（先小模型再大模型）、按房间统计用量。
4. **前端**：AI 头像与「思考中」气泡动画、AI 台词打字机效果、谢幕页展示「哪张卡是 AI 写的」。
5. **可观测性**：`/debug/ai` 做成受登录保护的面板，展示每轮 Prompt 与决策（复盘 AI 为什么这么猜）。
6. **多实例**：`GameRegistry` 抽存储接口，AI 任务队列外置（Redis/Celery），为多进程铺路。
