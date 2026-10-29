# 5 分钟跑通矿权日报

简报问题固定为：`给我生成一份关于 Pilbara 锂矿的今日简报`。

输出是一份 Markdown，包含新闻摘要、NI 43-101 储量、参考价格走势、风险提示和引用。数字只来自三个 MCP 工具，不需要大模型 API key。

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

Claude 或 Cursor 自己就是编排端，可以直接调用这些工具。本仓库的 `mining-daily-agent` 是不依赖模型密钥的编排端，方便在终端复现同一份简报。

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
