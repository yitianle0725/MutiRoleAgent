# MutiRoleAgent

一个面向动漫、小说和游戏资料场景的多角色 AI Agent。项目同时提供 React Web 前端、FastAPI 后端和 Streamlit 兼容入口，支持本地知识库问答、联网检索、结构化输出、会话记忆、角色人设、语音对话以及 ACGN 数据采集。

## 功能概览

### Agent 与对话

- 基于 LangChain / LangGraph 的 ReAct Agent，模型可以根据问题自主调用工具。
- Decision Engine + CITA 语义分析：区分闲聊、知识库问答、联网查询和复杂任务。
- 支持多会话隔离，SQLite 持久化会话标题、消息和统计信息。
- 支持角色人设切换、角色风格、世界观和人物关系文件。
- 支持流式文本、工具调用事件、结构化结果和性能监控。

### 知识库与 RAG

- ChromaDB 向量库保存本地文档切片。
- Vector + BM25 混合检索，可选 reranker 重排序。
- 文档入库使用 `mtime` 快速判断和 MD5 二次校验，避免重复解析和向量化。
- 支持 TXT、PDF、JSON、Markdown 等资料格式。
- 动漫资料单独使用 `anime` collection；角色世界观使用 `worldbook` collection。

### 联网与数据采集

- 动漫：Bangumi、AniList、Jikan、YUC，本地聚合后可使用 WebSearch MCP 兜底。
- 小说：起点搜索、排行榜、分类列表、具体作品详情，不抓取正文。
- 游戏：使用 Crawl4AI 获取米游社原神、崩坏：星穹铁道、绝区零官方公告、资讯、活动和社区地图。
- ACGN 日报：从 `search/acgn_daily/feeds.yaml` 配置的 RSS/API 源聚合每日动漫、漫画、游戏和小说资讯。

### 语音

- ASR：阿里云 `qwen-audio-3.0-asr-flash-streaming`。
- TTS：阿里云 `qwen-audio-3.0-tts-plus`。
- Realtime：阿里云 `qwen-audio-3.0-realtime-plus`。
- VAD：本地 Silero-VAD。
- 语音状态机：`IDLE -> LISTENING -> THINKING -> SPEAKING`。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| Python | Python 3.12+ |
| Agent | LangChain、LangGraph、Pydantic |
| LLM | OpenAI 兼容接口，默认适配 DashScope / Qwen |
| Web 后端 | FastAPI、Uvicorn、SSE、WebSocket |
| Web 前端 | React、TypeScript、Vite、Ant Design X |
| 旧版 UI | Streamlit |
| RAG | ChromaDB、BM25、jieba、可选 reranker |
| 存储 | SQLite、ChromaDB、JSON、Markdown |
| 抓取 | requests、BeautifulSoup、Crawl4AI、RSS |
| 语音 | DashScope、websockets、Silero-VAD |
| 配置 | `.env`、YAML |

## 快速开始

### 环境准备

建议使用独立虚拟环境，不要直接污染 Anaconda `base`：

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
```

网页采集和本地 Embedding 不是所有环境都必需；需要时再安装：

```powershell
python -m pip install crawl4ai fastembed jieba sentence-transformers
```

首次使用 Crawl4AI 可能还需要按其提示安装浏览器运行时。前端开发需要 Node.js 18+ 和 npm。

如果 PowerShell 禁止执行脚本，可以直接使用：

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

最少配置一个 LLM：

```dotenv
LLM_API_KEY=你的模型密钥
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3-max
DASHSCOPE_API_KEY=你的DashScope密钥
```

### 启动 React + FastAPI

终端一，在项目根目录启动后端：

```powershell
python -m uvicorn channels.platforms.fastapi:app --reload --port 8000
```

终端二启动前端：

```powershell
cd apps/web
npm install
npm run dev
```

访问：

- Web 前端：`http://localhost:5173`
- FastAPI 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`

前端 Vite 会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

### 构建并由后端托管前端

```powershell
cd apps/web
npm run build
cd ../..
python -m uvicorn channels.platforms.fastapi:app --port 8000
```

然后访问 `http://localhost:8000`。

### 启动 Streamlit 兼容入口

```powershell
streamlit run app.py
```

Streamlit 入口主要用于旧版页面、知识库文件上传和兼容测试；当前 React 页面推荐使用 FastAPI 入口。

## 环境变量

### 模型

```dotenv
LLM_API_KEY=...
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3-max
DASHSCOPE_API_KEY=...
```

可替换为 OpenAI、DeepSeek、Kimi 或 Ollama 的 OpenAI 兼容地址。

### Embedding

```dotenv
EMBEDDING_MODE=dashscope
```

支持 `dashscope`、`cloud`、`local` 和自动降级模式。切换 embedding 模型或维度后，可能需要清理并重建对应 Chroma collection。

### 语音

```dotenv
VOICE_ENABLED=true
DASHSCOPE_API_KEY=...
ALI_ASR_MODEL=qwen-audio-3.0-asr-flash-streaming
ALI_REALTIME_MODEL=qwen-audio-3.0-realtime-plus
ALI_TTS_MODEL=qwen-audio-3.0-tts-plus
ALI_TTS_VOICE=longanhuan_v3.6
```

语音是可选功能。没有配置时，文字对话仍可正常使用。

### WebSearch MCP

默认使用 DashScope WebSearch MCP：

```dotenv
WEBSEARCH_MCP_URL=https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp
WEBSEARCH_MCP_KEY=...
```

如果使用 `DASHSCOPE_API_KEY`，可以不单独设置 `WEBSEARCH_MCP_KEY`。远程工具还需要在 `config/gate.yaml` 的白名单中。

## 项目结构

```text
MutiRoleAgent/
├── agent/                     # Agent 核心、路由、Persona、结构化输出
│   ├── react_agent.py         # LangGraph ReAct Agent 主循环
│   ├── decision_engine.py     # chat / agent 路由
│   ├── action_gate.py         # 工具白名单和危险操作拦截
│   ├── execution_policy.py    # 工具参数校验
│   ├── cita/                  # 意图、实体、上下文语义分析
│   ├── persona/               # 角色人设与世界观运行时
│   └── structured_output/     # Pydantic 结构化输出和重试
├── api/                      # 旧版 FastAPI 路由模块
├── channels/platforms/       # 当前 FastAPI Channel 入口
├── apps/web/                 # React + TypeScript + Vite 前端
├── tools/                    # 本地工具、MCP 客户端、统一中间件、语音
├── model/                    # LLM、Embedding、维度检查、Embedding worker
├── rag/                      # Chroma、混合检索、BM25、上下文构建
├── memory/                   # SQLite 会话、内存历史、上下文压缩
├── search/                   # 动漫、小说、游戏和 ACGN 日报采集器
│   ├── anime/
│   ├── novel/
│   ├── game/
│   └── acgn_daily/
├── data/                     # 采集结果、知识库文档和角色世界观资料
├── prompts/                  # 系统提示词、角色提示词和工具规则
├── skills/                   # 可自动发现的 SKILL.md 技能
├── config/                   # YAML 配置
├── db/                       # 知识库文件索引和 SQLite 文件
├── chroma_db/                # ChromaDB 持久化数据
├── eval/                     # RAG、历史会话和回归评测
├── test/                     # 自动化测试
├── app.py                    # Streamlit 兼容入口
└── requirements.txt          # Python 依赖
```

## 工具调用规则

Agent 并不是每条消息都调用工具。流程如下：

1. Decision Engine 判断是闲聊还是 Agent 任务。
2. Agent 任务进入 LangGraph ReAct 循环。
3. LLM 根据工具 schema 选择工具。
4. UnifiedMiddleware 执行 Action Gate、参数校验、超时和错误处理。
5. 工具结果回传给模型，模型再生成最终回答。

典型调用顺序：

- 具体动漫：`search_anime -> fetch_anime`
- 小说：`search_novel -> fetch_novel`
- 游戏官方资讯：`search_game_official`
- 本地知识问答：`rag_summarize`
- 抓取失败或结果为空：`web_search` 兜底

涉及“最新、今天、当前、实时、公告、资讯、活动、章节、搜索”的问题会强制进入 Agent 路径，避免聊天缓存绕过工具。

## 数据采集命令

命令均从项目根目录执行，并使用正斜杠。

```powershell
# AniList 通用/定向搜索
python search/anime/search_anilist.py --search "死神"

# Jikan 数据采集
python search/anime/search_jikan.py

# 起点小说搜索
python search/novel/crawl_book_info.py --search "斗破苍穹"

# 起点排行榜
python search/novel/crawl_book_info.py --rank

# 米游社官方公告、资讯、活动
python search/game/crawl_hoyolab_wiki.py --official --game ys --limit 5

# ACGN 日报聚合
python search/acgn_daily/aggregate.py
```

结果默认写入 `data/anime`、`data/novel`、`data/game` 或 `data/acgn_daily`。Markdown 原始抓取结果通常通过 `--keep-md` 显式保留。

## RAG 数据准备

- `data/worldbook/`：角色、世界观、人物关系等长期知识。
- `data/anime/`：动漫 JSON 和采集结果，可被动漫相关检索使用。
- `data/novel/`、`data/game/`：小说和游戏采集结果，可作为后续知识库导入来源。
- 用户上传文件：通过 Streamlit 页面上传并写入知识库。

角色人设文件和文档知识库是两套概念：角色人设在 Agent 初始化或会话创建时从磁盘重新读取；知识库文档则经过清洗、切片、Embedding 和索引后持久化。

## 常见问题

### 1. 前端提示“会话列表加载失败，重试”

必须启动当前 FastAPI Channel，而不是旧的 `api.main`：

```powershell
python -m uvicorn channels.platforms.fastapi:app --reload --port 8000
```

前端请求路径是 `/api/v1/sessions`。可直接访问 `http://localhost:8000/api/v1/sessions` 验证。

### 2. 模型回答没有调用工具、出现幻觉

检查：

- 后端是否为 `channels.platforms.fastapi:app`。
- 日志是否出现 `Decision: route=agent`。
- 日志是否出现 `调用工具:`。
- WebSearch MCP 是否加载成功。
- `config/gate.yaml` 是否包含 `web_search` 或 `web_search_prime`。

修改 `config/decision.yaml`、Prompt 或 `.env` 后必须重启后端。

### 3. WebSearch 不可用

确认 `DASHSCOPE_API_KEY` 或 `WEBSEARCH_MCP_KEY` 已配置，并检查启动日志中的 `websearch` 工具加载信息。没有 MCP 时，动漫、小说、游戏工具仍可使用；联网兜底会失败并返回来源不足提示。

### 4. 语音提示未配置

设置：

```dotenv
VOICE_ENABLED=true
DASHSCOPE_API_KEY=...
ALI_ASR_MODEL=qwen-audio-3.0-asr-flash-streaming
ALI_REALTIME_MODEL=qwen-audio-3.0-realtime-plus
ALI_TTS_MODEL=qwen-audio-3.0-tts-plus
```

不要再配置已经废弃的 `cosyvoice-v1`。

### 5. `Model not found (cosyvoice-v1)`

说明旧配置仍被读取。检查 `.env`、`.env.example` 和当前进程环境变量，确保 `ALI_TTS_MODEL=qwen-audio-3.0-tts-plus`，然后完全重启后端。

### 6. `Missing required parameter payload.input`

这是阿里云语音协议参数结构不正确，通常来自旧版 ASR/TTS 代码或音频发送时机错误。确认使用当前 `tools/voice` 下的 Qwen 适配器，并确保音频帧在 Started 回调后发送。

### 7. Crawl4AI 只返回 `Loading...`

米游社是前端 SPA，需要浏览器渲染、隐身配置、等待页面就绪和较长超时。先使用 `--keep-md` 保留原始 Markdown，确认页面确实加载成功，再解析 JSON。

### 8. `ModuleNotFoundError: No module named 'utils'`

从项目根目录执行脚本：

```powershell
python search/novel/crawl_book_info.py --search "斗破苍穹"
```

不要把工作目录切换到 `search/novel` 后直接运行。

### 9. pip 报 `rich` 与 `instructor` 冲突

当前 `instructor` 要求 `rich<15`，可以执行：

```powershell
python -m pip install "rich>=13.7,<15"
python -m pip check
```

更推荐使用项目独立虚拟环境，不要长期在 Anaconda `base` 环境中混装依赖。

### 10. Chroma 维度不匹配

这是切换 Embedding 模型或维度后，旧向量库仍然存在。先备份 `chroma_db/`，再按当前 Embedding 配置重建 collection，避免混用不同维度的向量。

### 11. 如何查看工具是否真的执行

查看 `logs/agent_YYYYMMDD.log`，重点搜索：

```text
Decision: route=agent
调用工具:
AGENT_TOOL
AGENT_TOOL_DONE
```

如果只有 `route=chat` 或 `chat cache`，说明请求走了无工具聊天路径。

## 测试与检查

```powershell
# Python 编译检查
python -m py_compile agent/react_agent.py agent/decision_engine.py api/main.py

# 运行测试
python -m pytest -q

# 前端类型检查和构建
cd apps/web
npm run build
```

网络爬虫和外部 MCP 测试依赖网络、API Key 和目标站点状态，失败时应结合日志判断，不能只根据单次网络结果判断代码是否正确。

## 许可证

MIT
