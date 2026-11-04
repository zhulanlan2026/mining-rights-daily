# 5 分钟跑通矿权日报

简报问题固定为：`给我生成一份关于 Pilbara 锂矿的今日简报`。

输出是一份 Markdown，包含新闻摘要、NI 43-101 储量、参考价格走势、风险提示和引用。价格、储量和新闻里的数字只来自三个 MCP 工具。不配置密钥时，这些章节由模板直接生成。配置 `DEEPSEEK_API_KEY` 后，DeepSeek（默认模型 `deepseek-chat`）只补「简要研判」，并在规则无法归类时做意图分类。

## 这条命令不需要 Docker

在 `mining-rights-daily` 目录：

```powershell
uv sync
$env:NEWS_ENABLE_LIVE = "0"
$env:PYTHONIOENCODING = "utf-8"
uv run mining-daily-agent --query "给我生成一份关于 Pilbara 锂矿的今日简报" --as-of 2026-10-28 --output out/pilbara-lithium-briefing.md
```

`--as-of 2026-10-27` 把新闻窗口和价格日钉在样本数据的最后一天。不传它时，新闻按当天计算；如果当天没有样本，agent 会把窗口扩大到 14、120、800 天，并在简报里写明。

价格序列覆盖到 2026-10-28。更晚的日期会退回最后一个交易日，简报里有说明。

打开 `out/pilbara-lithium-briefing-2026-10-28.md`。文件名和文首都会带上简报日期。stderr 里每一行 `[react]` 是一次工具调用。

跑检查和测试：

```powershell
uv sync
uv run ruff check .
uv run pytest
```

推到 GitHub 后，`.github/workflows/ci.yml` 会跑同样的两步。镜像用 uid 1000 的 `app` 用户，三个 server 提供 `GET /healthz`，compose 用它做健康检查。容器日志是 JSON。

## 一条 docker compose

需要 Docker Compose v2。在 `mining-rights-daily` 目录：

```powershell
docker compose up --build --abort-on-container-exit --exit-code-from briefing
```

这条命令会构建镜像，拉起三个 MCP server 和一个 agent，把简报写到 `out/pilbara-lithium-briefing.md`，然后退出。三个 server 的地址：

| 服务 | 工具 | 本机端口 |
| --- | --- | --- |
| mining-news | `search`、`fetch_article` | 8001 |
| mineral-pdf | `extract_resources` | 8002 |
| lme-price | `get_price`、`get_trend` | 8003 |

容器内用 Streamable HTTP，路径是 `/mcp`。`mining-news` 的 `NEWS_ENABLE_LIVE=1`，会拉取 ASX 上 PLS 的公告。外网失败时仍用离线样本出稿，失败原因写在简报里。本地那条 PowerShell 命令继续用 `NEWS_ENABLE_LIVE=0`，方便没有外网时复现。

没有 Docker 时，可以用同一条 HTTP 协议在本机跑一遍。它会拉起三个 server，写出 `out/pilbara-lithium-http.md`，然后关掉进程：

```powershell
uv run python scripts/http_smoke.py
```

## 接到 Cursor 或 Claude Desktop

`mcp-config.json` 使用 stdio。把里面的 `mcpServers` 合并进：

- Cursor：设置里的 MCP，或项目 `.cursor/mcp.json`
- Claude Desktop：`%APPDATA%\Claude\claude_desktop_config.json`

目录写的是本机路径。仓库换位置后，改每个 server 的 `--directory`。三个进程分别是：

```text
python -m mining_rights_daily.servers.news
python -m mining_rights_daily.servers.pdf
python -m mining_rights_daily.servers.price
```

Claude 或 Cursor 自己就是编排端，可以直接调用这些工具。本仓库的 `mining-daily-agent` 在没有 DeepSeek 密钥时也能复现同一份简报。

## 编排

主图只做意图和路由。日报子图按固定顺序取数：`search` → `fetch_article` → `extract_resources` → `get_price` + `get_trend`，然后按 `src/mining_rights_daily/skills/mining-daily-report/SKILL.md` 写 Markdown。单独问价格、走势、新闻或储量时，不进入日报子图。

续聊会话存在 Checkpoint 后端。本机默认 SQLite（`--checkpoint out/checkpoints.sqlite`）。设置 `DATABASE_URL` 后（或 `AGENT_CHECKPOINT_BACKEND=postgres`）改用 PostgreSQL，同一库以后还给 RAG 用，表与 Checkpoint 分开。`docker compose` 已带 `postgres` 服务。

```powershell
uv run mining-daily-agent --query "给我生成一份关于 Pilbara 锂矿的今日简报" --as-of 2026-10-28 --thread-id pilbara --checkpoint out/checkpoints.sqlite
uv run mining-daily-agent --query "上一轮简报是哪一天" --thread-id pilbara --checkpoint out/checkpoints.sqlite
```

PostgreSQL 示例：

```powershell
$env:AGENT_CHECKPOINT_BACKEND = "postgres"
$env:DATABASE_URL = "postgresql://mining:mining@127.0.0.1:5432/mining"
uv run mining-daily-agent --query "给我生成一份关于 Pilbara 锂矿的今日简报" --thread-id pilbara
```

DeepSeek 使用 OpenAI 兼容接口，地址默认 `https://api.deepseek.com`，模型默认 `deepseek-chat`。研判里如果出现工具结果中没有的数字，这一节会被丢弃。

MCP 工具与 DeepSeek 调用默认最多重试 3 次（指数退避）。超时、连接失败、HTTP 429/5xx 会重试；参数错误、401/403/404 等不重试。整次请求还有总时长预算（默认 240 秒），用尽后不再重试并走「未获取到数据」降级。可用环境变量调整：`AGENT_TOOL_RETRIES`、`AGENT_TOOL_RETRY_DELAY`、`AGENT_REQUEST_BUDGET`、`AGENT_TOOL_TIMEOUT`。

```powershell
$env:DEEPSEEK_API_KEY = "<your-key>"
$env:DEEPSEEK_MODEL = "deepseek-chat"
```

本地流式输出：

```powershell
uv run mining-daily-agent --serve --port 8765
```

然后请求 `http://127.0.0.1:8765/v1/briefing?query=生成%20Pilbara%20锂矿今日简报&thread_id=pilbara`。响应是 `text/event-stream`：先推节点进度，最后一条 `event: report` 是整篇 Markdown。

## 企业微信

对话入口是企业微信自建应用，不是小程序。在应用里给「接收消息」配置一个公网 HTTPS 地址，指向本机回调：

```text
https://你的域名/wecom/callback
```

接收方式选安全模式。本地先起服务：

```powershell
$env:WECOM_CORP_ID = "<企业ID>"
$env:WECOM_AGENT_ID = "<应用ID>"
$env:WECOM_SECRET = "<应用Secret>"
$env:WECOM_TOKEN = "<接收消息Token>"
$env:WECOM_ENCODING_AES_KEY = "<43位EncodingAESKey>"
uv run mining-daily-agent --wecom --port 8780
```

企业微信把用户的一句话发到这个地址。服务立刻回复 `success`，再在原会话里先发「正在生成，请稍等。」，生成结束后把简报按段发回。同一个人的后续问题共用会话 `wecom:<用户ID>`。简报超过企业微信单条长度时会分成多条。

五个配置只放在环境变量里，不要写进仓库，也不要贴到聊天记录。本机没有公网地址时，用隧道把 `127.0.0.1:8780` 转到上面的 HTTPS 地址。三个 MCP 已在 compose 里运行时，加上 `$env:MCP_TRANSPORT = "http"`。

单独看 HTTP 端口时：

```powershell
$env:MCP_TRANSPORT = "streamable-http"
$env:MCP_HOST = "127.0.0.1"
$env:MCP_PORT = "8001"
uv run python -m mining_rights_daily.servers.news
```

## 数据边界

- 新闻默认会尝试合并两条公开源：`https://www.mining.com/feed/`（10 秒，CloudFront 拒绝过短的 User-Agent，所以 RSS 请求带上 `Mozilla/5.0 (compatible; mining-rights-daily/0.1)`）和 ASX 上 PLS 的公告列表（15 秒）。两条请求并行。公告日期按悉尼时间计入窗口。其中一条失败时，另一条和离线样本仍然返回，失败原因写在简报里。关掉在线源：`NEWS_ENABLE_LIVE=0`。`fixture://` 链接是本仓库写的样本，不是通讯社原文。ASX 条目是交易所公告，PDF 链接来自公开文件接口。
- `catalog:pilgangoora-ni43101-sample` 是合成的 NI 43-101 文本 PDF，用来验证 Indicated / Inferred 解析。它不是 Pilbara Minerals 的正式披露。`extract_resources` 也可以传公开的 http(s) PDF；扫描件会被拒绝。
- 价格序列覆盖 2026-09-01 到 2026-10-28 的工作日。它不是 LME 结算价，也不能当成辉石精矿价。`--as-of 2026-10-27` 仍可读到当天收盘 10460 USD/t。

## 换一个问题

```powershell
uv run mining-daily-agent --query "最近铜价怎么样" --as-of 2026-10-27
```

商品可以是 lithium、copper、nickel、gold、iron_ore，也认「锂 / 铜 / 镍 / 金 / 铁矿」。只有 Pilbara 锂在报告目录里有样本 PDF，其他标的会明确写「没有匹配的技术报告」，不会编造吨位。
