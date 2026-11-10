# 部署手册 · 桌上剧团 · 诸伶无名

> 这份文档分两段：**我已经做完的**、**必须你本人做的**。
> 你不在的时候我做到"只差你的登录"为止；剩下每一步都写清楚了命令和预期结果。

---

## 0. 一句话结论

这是一个**有状态的长连接服务**（WebSocket + 房间状态全在内存里），所以：

| 平台 | 能不能用 | 说明 |
| --- | --- | --- |
| **Fly.io** | ✅ 推荐 | WS 原生支持；可闲置停机省钱；免费额度够玩 |
| **Railway** | ✅ 推荐 | 试用额度 / $5 起；部署最简单 |
| **Render** | ✅ 可以 | 免费档会休眠（首次访问冷启动 ~30s）；WS 支持 |
| **Koyeb / Hugging Face Spaces** | ✅ 可以 | 都支持 Docker + WS |
| **Vercel / Netlify / Cloudflare Pages** | ❌ 不行 | 它们只跑无状态函数/静态页，**长连接活不下来** |
| 任何"多副本"配置 | ❌ 不行 | 两个副本 = 两个世界，玩家互相看不见 |

**必须遵守的三条：**

1. `--workers 1` + **副本数 1**（已写死在各配置文件里）
2. **不要开 `AI_DEBUG`**（它会把 AI 的 Prompt 和"真实编号映射"暴露在 `/debug/ai`）
3. 进程重启 = 房间清空（内存态，这就是当前设计）

---

## 1. 我已经做完的（不需要你动）

| 项目 | 内容 |
| --- | --- |
| 生产镜像 | `Dockerfile`：python:3.11-slim、非 root、`HEALTHCHECK`、**跟随平台注入的 `$PORT`**、`--proxy-headers`（平台边缘终结 TLS 后必须信任转发的头）、`--workers 1` |
| 依赖拆分 | `requirements.txt`（运行期 3 个）/ `requirements-dev.txt`（pytest 等）→ 镜像更小、攻击面更小 |
| 平台配置 | `fly.toml`（sin 区、512MB、闲置停机、健康检查宽限 20s）<br>`render.yaml`（Blueprint，`numInstances: 1`，env 预置）<br>`railway.json`（Dockerfile 构建 + `/healthz` 健康检查 + 单副本） |
| 环境变量约定 | `PORT`、`AI_DEBUG=0`、`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_MAX_TOKENS` |
| 线上自检脚本 | `scripts/smoke_remote.py <URL>`：24 项检查（HTTP、静态资源、favicon、og、WS 建房入场、加 AI、开演、非法操作拦截、断线回座） |
| 本机已验证 | 用"生产同款"启动参数（`AI_DEBUG=0` + `--proxy-headers` + `$PORT`）跑通冒烟：**24/24 通过** |
| 文档 | 本文件 + `README.md` 部署章节 + `DEMO.md` 演示脚本 |

**我做不到的部分**：各家平台的账号登录 / 绑卡 / 域名，都需要你本人的凭据。我这边没有 Docker，也没有 fly / railway / render 的 CLI 和 token，所以**最后一步必须你点**。

---

## 2. 你必须做的（选一个平台，5–10 分钟）

### 2.1 路线 A：Fly.io（推荐，最稳）

```bash
# 1) 装 CLI（Windows PowerShell）
iwr https://fly.io/install.ps1 -useb | iex

# 2) 登录（会开浏览器，需要邮箱 + 绑卡：Fly 现在要求验证支付方式）
fly auth signup        # 或 fly auth login

# 3) 进项目目录，改 app 名（全局唯一，随便起）
cd D:\工作区\长期任务\game
#    编辑 fly.toml 第一行 app = "你的名字"

# 4) 建应用（不要让它改你的配置）
fly launch --no-deploy --copy-config

# 5) 配 LLM（可选，不配也能玩，AI 走离线兜底）
fly secrets set LLM_API_KEY=sk-xxx
fly secrets set LLM_BASE_URL=https://wb2api.264133.xyz/v1
fly secrets set LLM_MODEL=cn:deepseek-v4.1-flash
fly secrets set LLM_MAX_TOKENS=2400

# 6) 部署
fly deploy

# 7) 自检（把 URL 换成你的）
python scripts\smoke_remote.py https://你的app名.fly.dev

# 8) 免费额度下闲置会停机，第一次访问慢是正常的；想 7x24 常驻：
fly scale count 1
```

预期：`fly deploy` 结束会打印 `Visit your newly deployed app at https://xxx.fly.dev`；
冒烟脚本最后一行打印 `🎭 这台机器可以发给朋友玩了`。

### 2.2 路线 B：Railway（最省事）

1. 打开 https://railway.app → **Login with GitHub**
2. **New Project → Deploy from GitHub repo** → 选这个仓库
   （先把 `game/` 目录推到一个 GitHub 仓库：`git init && git add . && git commit && git push`）
3. Railway 会自动读 `railway.json`（Dockerfile 构建、`/healthz` 健康检查）
4. **Variables** 里加：`LLM_API_KEY`（其余三个可留空/填默认）
   `AI_DEBUG` 不用加，默认就是 0
5. **Settings → Networking → Generate Domain** 拿到公网地址
6. 自检：`python scripts\smoke_remote.py https://你的域名`

⚠️ Railway 里确认 **Replicas = 1**（多副本会分裂房间）。

### 2.3 路线 C：Render（有免费档）

1. https://render.com → 登录 → **New → Blueprint** → 连 GitHub 仓库
2. 它会读 `render.yaml`，自动建一个 Docker 服务
3. 在服务页填 `LLM_API_KEY`
4. 等状态变 **Live**，拿 `https://xxx.onrender.com`
5. 自检同上

⚠️ Render 免费档 **15 分钟无访问会休眠**，第一次打开要等 30–60 秒（页面上会转圈，属于正常）。
想不睡就升 Starter（$7/月）。

### 2.4 路线 D：Hugging Face Spaces（零成本，公开）

1. https://huggingface.co/new-space → **SDK 选 Docker** → Blank
2. 上传 `game/` 下的 `Dockerfile`、`server/`、`requirements.txt`（或直接 `git push`）
3. Space 设置里加环境变量 `LLM_API_KEY`
4. 端口：HF 固定用 `7860`，在 Space 设置里把 **App port 改成 8000**，或把 Dockerfile 的 `PORT` 默认值改成 `7860`
5. 地址形如 `https://用户名-空间名.hf.space`

⚠️ 公开 Space = 任何人能访问，且不支持私有（付费才可）。

---

## 3. 部署后必须做的三件事

1. **跑冒烟**：`python scripts\smoke_remote.py https://你的域名` → 必须 24/24
2. **确认调试口关着**：浏览器打开 `https://你的域名/debug/ai` → 应该是 **404**。
   如果返回 JSON，说明 `AI_DEBUG` 没关，立刻在平台环境变量里设 `AI_DEBUG=0` 重新部署。
3. **手机开一局**：手机浏览器打开首页 → 建房 → 把 6 位号码发给朋友 → 两人都能进去、能开演 = 成功。

---

## 4. 安全与成本

- **LLM key**：只放平台环境变量 / 本地 `config/llm.json`（已 gitignore）。**别提交进仓库**。
  我这个 key 已经在聊天里出现过，建议用完重置。
- **花费**：本游戏一次 AI 决策 = 1 次模型调用；一局 4 人 12 轮大约 30–60 次调用。
  `cn:deepseek-v4.1-flash` 单次约 0.1–0.2 credit（自测观察值），放心玩。
  想彻底不花钱：不配 `LLM_API_KEY`，AI 走离线兜底，功能完整只是"话少"。
- **公开性**：任何拿到链接的人都能建房玩。没有账号系统、没有敏感词过滤。
  要发朋友圈就在群里发链接即可；不想被搜到就别公开贴。

---

## 5. 出问题怎么查（常见 6 个）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 页面能开，但一直"连接中…" | 平台不支持 WS，或反代没转发 Upgrade | 换平台（Vercel 必踩）；确认用的是 `wss://` |
| 两人能看到房间但互相看不见 | 起了多副本 / 多 worker | 副本改成 1，`--workers 1` |
| 打开很慢（30–60 秒） | 免费档休眠冷启动 | 正常；或升级常驻 |
| 开局后很快"掉线" | 平台的空闲超时或反代 keep-alive 太短 | 已设 `--timeout-keep-alive 75`；再短就调大 |
| 部署成功但 `/healthz` 502 | 进程启动失败（依赖/端口） | 看平台日志；确认 `$PORT` 被使用 |
| AI 说话很模板 | `LLM_API_KEY` 没生效 | 看启动日志 `LLM 已就绪…`；或 `/debug/ai`（本地才有） |

**回滚**：Fly `fly releases` → `fly deploy --image <上一版>`；Railway/Render 在面板上点 **Redeploy** 选上一个 commit。

---

## 6. 如果你希望我接手到底

我需要你提供**其中一样**：

- Fly：`fly tokens create org` 生成的 token（我只用它 `fly deploy`，其余不动）
- Railway：项目页 **Settings → Tokens** 的 project token
- Render：**Account Settings → API Keys** 的 key + 仓库地址
- 或者：你本地跑一条 `fly deploy`，把输出贴给我，我帮你判错

给了我就能自己部署 + 冒烟 + 把地址交给你；不给也没关系，按 §2 走 5 分钟就好。

---

## 7. 还没做的（部署相关的已知缺口）

1. **没有持久化**：重启即清房。要做就得把房间状态外置（Redis/Postgres）+ 加锁，工作量大，第 6 周再说。
2. **没有账号体系**：昵称可重名、无法封禁。公网小范围玩够了。
3. **没有限流**：被恶意刷建房只能靠平台层（Cloudflare 前面套一层更稳）。
4. **没有自定义域名 / HTTPS 证书**：Fly/Render/Railway 自带子域名 HTTPS 足够；要自己的域名在平台加 CNAME 即可。
