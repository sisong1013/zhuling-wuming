# 桌上剧团 · 诸伶无名

> THE NAMELESS TROUPE · 一台关于编号与身份的社会推理游戏

> 一个跑在浏览器里的社交推理小游戏：**猜真人**（REAL）与**人设卡**（PERSONA）两种玩法，
> 支持多房间联机、断线重连、AI 陪演、赛后名场面复盘。
> 后端 FastAPI + 纯内存状态机，前端原生 HTML/CSS/ES Module —— 无数据库、无前端框架、无 socket.io。

---

## 1. 玩法一页看懂

| 模式 | 你要猜什么 | 终局揭晓 |
| --- | --- | --- |
| **REAL（猜真人）** | 每个编号背后是**哪位真人** | 编号 → 昵称 + 名场面时间线 |
| **PERSONA（人设卡）** | 每个编号拿到的是**哪张人设卡** | 编号 → 卡名/卡文/作者 + 名场面时间线 |

**一局怎么走**

1. 团长「组建剧团」拿到 6 位号码；其他人凭号码入场（2–8 人，可加 1–2 个 AI 陪演）。
2. PERSONA 模式多两步：**写卡**（每人写一张人设卡）→ 队长触发**错位分配**（保证谁都不会拿到自己的卡）→ **读卡**（看自己的卡）。
3. **第一幕 · 讯问**：每轮一次机会 —— 问某人 / 呈上看板 / 略过。答错冷却 3 轮（每轮 -1）。
4. **第二幕 · 应答**：被问者作答（可以撒谎），全员并行、公开可见；超时记 TIMEOUT（不罚）。
5. **第三幕 · 复述**：复诵本轮问答，全员示意后进入下一轮。
6. 看板全对 → 立刻谢幕。第 12 轮（可配）全员强制作答。
7. 谢幕页有 **真实映射 + 名场面时间线**（开场第一问 / 超时 / 神准提问 / 自曝身份 / 名场面台词）。

> **自己那格是白送的**：你当然知道自己的编号/自己拿到的卡名，所以看板里那一格自动锁定填好。

---

## 2. 本地启动

```bash
cd game
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

.venv/Scripts/python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000/
```

想 4 个标签页开一局看效果 → 见 [`DEMO.md`](DEMO.md)。

### 2.1 接 LLM（可选，不配也能玩）

不配 Key 时所有 AI 走**离线确定性兜底**（固定卡池 + 模板问答 + 约束推理）。
配上真模型后，写卡 / 盘问 / 作答 / 提交前推理都交给模型。

**两种配置方式，选一种：**

A. config/llm.json（推荐，方便脚本化）

`json
{
  "apiKey": "sk-...",
  "baseUrl": "https://wb2api.264133.xyz/v1",
  "model": "cn:deepseek-v4.1-flash",
  "fallbacks": [],
  "maxTokens": 2400
}
`

B. game/.env

`ini
LLM_API_KEY=sk-...
LLM_BASE_URL=https://wb2api.264133.xyz/v1
LLM_MODEL=cn:deepseek-v4.1-flash
LLM_MODEL_FALLBACKS=
LLM_MAX_TOKENS=2400
`

已存在的环境变量优先；config/llm.json 只是补空缺。

| 参数 | 作用 | 默认 |
| --- | --- | --- |
| LLM_MODEL | 主模型 | gpt-4o-mini |
| LLM_MODEL_FALLBACKS | 降级链（逗号分隔），主模型失败自动换 | 空 |
| LLM_MAX_TOKENS | 单次输出预算；**思考型模型会先烧 reasoning token，给少了 content 会是空的** | 2400 |
| LLM_DISABLE=1 | 强制离线兜底（自动化测试用，pytest 默认打开） | 未设 |

**接思考型模型踩过的三个坑（代码里已处理）：**

1. 预算被推理吃光 → inish_reason=length 且 content 为空时自动翻倍预算重试一次；
2. 无视 
esponse_format: json_object → 改用更硬的**单行契约**（卡名||说明 / ASK|编号|问题 / 编号=取值），同时保留 JSON、markdown 的宽松解析；
3. 跑偏写成人物卡表格 → 写卡 prompt 换成「节目单上一行角色说明」+ 三个少样本示例，并加质量闸门（卡名 3–14 字、禁姓名年龄外貌清单、禁英文）。

**自检三件套：**

`ash
python scripts/check_llm.py        # 通不通 / 模型是谁 / JSON 行不行
python scripts/check_llm_game.py   # 用游戏真实 prompt 生成卡、作答、推理轮
python scripts/demo_llm_game.py    # 连真机跑一局（需服务在 8000）
`

启动日志会打 \LLM 已就绪：model=… base=…（来源：…）\；GET /debug/ai 的 llm 段可见
configured / chain / maxTokens / lastModel / fallbacks。

## 3. 目录结构

```
game/
├── server/
│   ├── main.py            # 装配：静态托管 + /ws + /healthz + /debug/ai
│   ├── models.py          # 数据模型：Phase/GameMode/GameConfig/Player/Room/PersonaCard
│   ├── rules.py           # 纯规则：昵称、编号、判定、错位分配、复盘时间线
│   ├── state_machine.py   # GameRegistry：全部状态流转与 action_*
│   ├── ws_handlers.py     # 事件表 + 分发（client ↔ registry）
│   ├── timers.py          # 可取消定时器（阶段/题目/回收/AI）
│   ├── llm_client.py      # OpenAI 兼容封装（超时兜底、强制 JSON）
│   ├── ai.py              # AI 内容生成（LLM 优先 + 离线兜底）
│   ├── ai_agent.py        # AI 大脑：记忆 / Prompt / 决策（防上帝视角）
│   └── static/
│       ├── index.html     # 单页外壳（#stage #hud #view #side #board）
│       ├── style.css      # 主题（暗金 + 红幕 + 纸面）
│       ├── style.v4.css   # 第 4 周：玻璃 / 抽屉 / 时间线 / 响应式
│       ├── app.js         # 入口：按 phase 选视图（import 下面全部模块）
│       └── js/
│           ├── ws.js      # 唯一网络层：连接/重连/心跳/事件总线/状态仓库
│           ├── ui.js      # 工具：查询、转义、Toast
│           ├── timer.js   # 环形倒计时（读 deadline 本地算）
│           ├── board.js   # 观众板抽屉
│           ├── lobby.js   # 入口页
│           ├── waiting.js # 等待室（含加 AI）
│           ├── card.js    # 写卡
│           ├── reading.js # 读卡
│           ├── phase1.js  # 第一幕
│           ├── phase2.js  # 第二幕
│           ├── phase3.js  # 第三幕
│           └── over.js    # 谢幕 + 名场面时间线
├── tests/                 # 第 1–4 周全部自动化测试
├── scripts/{selftest.sh, stress_ws.py, fetch_miyoushe_images.py}
├── reports/               # 每周交付报告 + final_final.md
├── Dockerfile / docker-compose.yml / env.example / DEMO.md
```

**前端原则**：不维护业务逻辑。`ws.js` 把服务端事件落进一个 `state` 对象，视图模块只读 `state` 渲染；
视图重渲染只在「阶段/轮次/关键标记」变化时发生，避免打断输入框。

---

## 4. WebSocket 协议

客户端 → 服务端

| 事件 | 载荷 | 说明 |
| --- | --- | --- |
| `room:create` | `{nickname}` | 建房（发起人即团长） |
| `room:join` | `{roomCode, nickname}` | 凭 6 位码入场 |
| `conn:reconnect` | `{roomCode, playerId, token}` | 断线重连 |
| `setup:config` | `{gameMode?, phase1Seconds?, ...}` | 团长改配置/玩法 |
| `room:addAI` | `{count:1\|2}` | 团长在等待室加 AI |
| `game:start` | `{}` | 开演 |
| `card:submit` | `{name, content}` | 写卡（1–20 字唯一卡名 / ≤300 字卡面） |
| `captain:startAssign` | `{}` | 队长触发错位分配 |
| `reading:confirm` | `{}` | 读卡示意 |
| `phase1:ask` | `{targetRoomNo, text}` | 讯问 |
| `phase1:submit` | `{board}` | 呈上看板 |
| `phase1:skip` | `{}` | 略过本轮 |
| `board:saveDraft` | `{board}` | 存草稿 |
| `phase2:answer` | `{questionId, text}` | 作答 |
| `phase3:confirm` | `{}` | 复述示意 |
| `ping` | `{}` | 心跳（20s 一次，服务端 60s 无消息判掉线） |

服务端 → 客户端：`room:state` / `game:started` / `phase:changed` / `persona:assigned` / `card:progress` /
`card:submitted` / `reading:progress` / `question:received` / `question:public` / `answer:public` /
`phase2:progress` / `phase3:replay` / `cooldown:updated` / `submit:result` / `room:aiAdded` / `ai:thinking` /
`reconnect:ok` / `reconnect:failed` / `game:over` / `error`。

**`game:over` 载荷**：`{winnerId, gameMode, fullBoard | reveal, timeline[], stats{rounds,questions,answered,timedOut,highlights,players,aiPlayers}}`。

**防作弊约定**：编号 ↔ 真人 / 编号 ↔ 卡 的映射**只在 `game:over` 出现一次**；
`room:state.players[]` 不含 `roomNo`；重连快照只带自己的看板与自己的卡。

---

## 5. 测试

```bash
cd game
bash scripts/selftest.sh                 # 全量（Windows 下用 Git Bash）
bash scripts/selftest.sh tests/test_week4_step3_ui.py    # 单文件
python scripts/stress_ws.py --players 8 --rounds 2       # 手动压测
```

覆盖：第 1 周 64 条（基础流程）、第 2 周 64 条（联机/人设卡）、第 3 周 35 条（AI/防泄题）、
第 4 周 24 条（UI 冒烟 / 复盘 / 安全 / 并发压力）。

---

## 6. 部署

> 完整步骤、平台对比、排错表都在 **[DEPLOY.md](DEPLOY.md)**。这里只给最短路径。

**⚠️ 这是个有状态的长连接服务**（WebSocket + 房间在内存里），所以 Vercel / Netlify /
Cloudflare Pages 这类"无状态函数 + 静态页"的平台**不能用**；且必须 **单副本 + 单 worker**。

| 平台 | 结论 |
| --- | --- |
| Fly.io / Railway / Render / Koyeb / HF Spaces (Docker) | ✅ 可用 |
| Vercel / Netlify / CF Pages | ❌ 长连接活不下来 |
| 任意多副本 | ❌ 房间会分裂 |

### 6.1 本地 Docker

```bash
cd game
docker compose up -d --build          # 8000 端口
curl -s http://127.0.0.1:8000/healthz
```

### 6.2 云平台（仓库里已备好配置）

```bash
# Fly.io
fly launch --no-deploy --copy-config && fly deploy      # 读 fly.toml
# Railway：面板连 GitHub 仓库，自动读 railway.json
# Render ：面板 New → Blueprint，自动读 render.yaml
```

镜像跟随平台注入的 `$PORT`，`--proxy-headers` 已开，健康检查走 `/healthz`。

### 6.3 部署后自检（必做）

```bash
python scripts/smoke_remote.py https://你的域名
# 24 项：HTTP / 静态资源 / WS 建房入场 / 加 AI / 开演 / 非法操作拦截 / 断线回座
# 末尾打印「🎭 这台机器可以发给朋友玩了」= 成功
```

再确认 **`/debug/ai` 返回 404**（线上必须关掉 AI 调试口，否则会泄露 AI 的 Prompt 与真值）。


## 7. 已知限制

1. 纯内存：进程重启房间全丢；不支持多 worker / 多副本。
2. 无账号体系：昵称 + 6 位房间码即身份，重连靠 `reconnectToken`（存 localStorage）。
3. 文本只做长度/唯一性校验，无敏感词过滤、无频控、无审核。
4. `room:state` 全量广播（8 人上限下可忽略），未做增量 diff。
5. AI 的「像不像人设」靠 Prompt，没有二次校验；AI 在阅读阶段视为已示意、回放 1–3s 自动确认。
6. `/debug/ai`（含 Prompt 留痕与真值）只在 `AI_DEBUG=1` 时开放，生产务必保持关闭。
