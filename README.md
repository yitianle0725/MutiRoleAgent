# MutiRoleAgent —— 多角色 AI Agent 框架

基于 **LangChain + LangGraph ReAct Agent** 构建的多角色智能助手，支持动漫推荐、天气查询、知识库 RAG、角色扮演等场景。

## 核心特性

### 多角色人设切换
- 内置 **Persona Engine**，支持动态切换角色（如 Cyrene）
- 角色卡 YAML 格式，可自由扩展：外观、性格、背景故事、对话风格、扮演指南
- 切换时自动生成符合角色语气的过渡消息

### 智能路由决策
- **Decision Engine** 快/慢路由：闲聊直走 LLM（低延迟），复杂任务走完整 ReAct Agent
- **CITA 2.0 语义分析**：提取主意图、实体、判断是否需要 RAG 检索
- **动态工具裁剪**：根据语义分析结果只发送相关工具（减少 30-40% token 消耗）

### 知识库 RAG（v2 混合检索）
- **3 个独立 Collection**：FAQ、Worldbook（世界观）、Anime（番剧数据）
- **混合检索**：Dense Vector (70%) + BM25 稀疏检索 (30%)
- **多种 Embedding 支持**：DashScope 云端 → OpenAI 兼容 → 本地 bge-m3（降级链）
- **维度校验**：跨 provider 切换自动检测 mismatch 并清空旧数据
- **Worker 线程池**：并行分块 + 嵌入，批量入库加速

### 工具系统
| 类别 | 工具 | 说明 |
|------|------|------|
| 动漫 | `search_anime` | bangumi 搜索，熔断 fallback 到本地知识库 |
| 动漫 | `fetch_anime` | 获取作品详情（章节/简介/标签/角色） |
| 动漫 | `get_season_anime` | 获取季度新番列表（yuc.wiki） |
| 天气 | `maps_weather` | Open-Meteo 免费全球天气（高德可选） |
| 天气 | `maps_ip_location` | IP → 城市名定位 |
| 知识库 | `rag_summarize` | 本地知识库 RAG 检索 + LLM 总结 |
| 角色 | `switch_persona` | 动态切换角色人设 |
| 角色 | `reset_persona` | 重置为默认模式 |
| 搜索 | `web_search` | MCP 实时网络搜索 |
| 时间 | `get_current_time` | 当前日期时间 |
| 网络 | `get_public_ip` | 本机公网 IP |

### 安全防护
- **Action Gate**：工具白名单/黑名单/运行时拦截
- **执行策略**：工具超时控制 + 自动重试 + 熔断降级
- **上下文裁剪**：自动裁剪超限历史消息（token/轮数双阈值）

### Skill 插件系统
- `weather-lifestyle` — 天气 + 穿衣/运动/护肤建议
- `anime-deep-dive` — 番剧深度分析
- `season-overview` — 季度新番总览
- `recommend-anime` — 个性化番剧推荐
- 可通过 `skill-creator` 创建自定义 Skill

### 会话管理
- **多 session 隔离**：URL 参数持久化 session_id
- **SQLite 持久化**：消息历史自动存储 + 启动恢复
- **Streamlit 前端**：侧边栏文件上传、角色切换、会话管理

## 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                 │
├─────────────────────────────────────────────────────────┤
│                    ReactAgent                            │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐    │
│  │ Decision  │  │  CITA    │  │  UnifiedMiddleware │    │
│  │ Engine    │  │ Semantic │  │  (动态工具裁剪)     │    │
│  └──────────┘  └──────────┘  └────────────────────┘    │
│  ┌──────────────────────────────────────────────────┐   │
│  │  LangGraph ReAct Agent (create_agent)             │   │
│  │  ┌────────┐  ┌──────────┐  ┌─────────────────┐   │   │
│  │  │ Tools  │  │ Action   │  │ Persona Engine  │   │   │
│  │  │ 10+    │  │ Gate     │  │                 │   │   │
│  │  └────────┘  └──────────┘  └─────────────────┘   │   │
│  └──────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│  Model Layer          │  RAG Layer (v2)                  │
│  ┌─────────────────┐  │  ┌──────────────────────────┐   │
│  │ ChatOpenAI       │  │  │ HybridRetriever          │   │
│  │ (DeepSeek/百炼)  │  │  │ Vector(70%)+BM25(30%)    │   │
│  ├─────────────────┤  │  │ + Reranker(bge-reranker)  │   │
│  │ EmbeddingProvider│  │  ├──────────────────────────┤   │
│  │ Local→Cloud→Dash │  │  │ ChromaDB (3 collections) │   │
│  │ DimensionGuard   │  │  │ ChineseBM25 (jieba分词)  │   │
│  │ EmbeddingWorker  │  │  └──────────────────────────┘   │
│  └─────────────────┘  │                                  │
├─────────────────────────────────────────────────────────┤
│  Storage: SQLite (chat) + ChromaDB (vectors) + YAML (config) │
└─────────────────────────────────────────────────────────┘
```

## 快速开始

### 环境要求
- Python 3.12+
- Windows / macOS / Linux

### 1. 安装依赖

```bash
pip install -r requirements.txt

# Embedding 升级所需额外依赖
pip install fastembed jieba sentence-transformers
```

### 2. 配置 API Key

编辑 `.env`：

```bash
# LLM（必填，OpenAI 兼容协议）
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3-max

# DashScope（兼容旧变量 + Embedding fallback）
DASHSCOPE_API_KEY=sk-your-key

# 高德天气（可选，不设则用免费 Open-Meteo）
# AMAP_API_KEY=your_amap_key
```

支持的 LLM 厂商（修改 `LLM_BASE_URL` 即可切换）：

| 厂商 | LLM_BASE_URL |
|------|-------------|
| 阿里百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Kimi | `https://api.moonshot.cn/v1` |
| Ollama | `http://localhost:11434/v1` |

### 3. 启动

```bash
streamlit run app.py
```

### 4. 载入知识库

将文档放入对应目录：
- `data/faq/` — FAQ 知识库（`.txt` / `.pdf`）
- `data/worldbook/` — 世界观/角色设定（`.txt` / `.pdf`）
- `data/anime/` — 番剧 JSON 数据（`.json`）

启动后自动载入，MD5 去重避免重复入库。

## 项目结构

```
MutiRoleAgent/
├── app.py                  # Streamlit 前端入口
├── requirements.txt        # Python 依赖
├── .env                    # API Key 配置
│
├── agent/                  # Agent 核心
│   ├── react_agent.py      # ReAct Agent 主控制器
│   ├── agent_state.py      # Agent 状态管理
│   ├── decision_engine.py  # 快/慢路由决策
│   ├── action_gate.py      # 工具白名单/黑名单/拦截
│   ├── execution_policy.py # 工具超时 + 重试 + 熔断
│   ├── knowledge_base.py   # 用户上传 → 知识库
│   ├── stream_events.py    # 流式事件类型
│   ├── user_profile_extractor.py  # 用户画像提取
│   ├── cita/               # CITA 2.0 语义分析
│   │   └── semantic.py     # 意图识别 / 实体提取
│   ├── persona/            # 角色人设系统
│   │   └── engine.py       # Persona Engine
│   ├── skill_support/      # Skill 插件支持
│   ├── structured_output/  # 结构化输出（天气报告等）
│   └── tools/              # 工具集
│       ├── agent_tools.py  # 所有本地工具定义
│       ├── mcp_client.py   # MCP 远端工具客户端
│       └── unified_middleware.py  # 动态工具裁剪
│
├── model/                  # 模型工厂
│   ├── factory.py          # LLM + Embedding 单例
│   ├── embedding_provider.py  # Embedding Provider (v2)
│   ├── dimension_guard.py  # 维度校验
│   └── embedding_worker.py # 并行嵌入线程池
│
├── rag/                    # RAG 检索层 (v2)
│   ├── vector_store.py     # 3 Collection ChromaDB 管理
│   ├── rag_service.py      # 智能路由 RAG 总结
│   ├── hybrid_retriever.py # 混合检索器 (Vector+BM25+Reranker)
│   └── bm25.py             # 中文 BM25 稀疏检索 (jieba)
│
├── anime/                  # 动漫数据爬虫
│   ├── crawl_bangumi.py    # bangumi 搜索 + 详情
│   ├── crawl_yuc.py        # yuc.wiki 季度新番
│   └── retry_handler.py    # 熔断器
│
├── config/                 # YAML 配置
│   ├── agent.yaml          # Agent 参数（裁剪/超时）
│   ├── chroma.yaml         # ChromaDB + 检索参数
│   ├── decision.yaml       # 快/慢路由决策规则
│   ├── gate.yaml           # 工具白名单/黑名单
│   ├── keywords.yaml       # RAG 路由关键词
│   └── rag.yaml            # RAG 模型配置
│
├── prompts/                # 提示词模板
│   ├── system/             # 系统提示词 (tools/output/system)
│   ├── soul/               # 角色灵魂提示词
│   ├── styles/             # 风格提示词
│   └── worldbook/          # 世界观设定
│
├── skills/                 # Skill 插件
│   ├── weather-lifestyle/  # 天气生活建议
│   ├── anime-deep-dive/    # 番剧深度分析
│   ├── season-overview/    # 季度新番总览
│   ├── recommend-anime/    # 个性化推荐
│   └── skill-creator/      # Skill 创建工具
│
├── utils/                  # 工具模块
│   ├── config_handler.py   # YAML 配置加载
│   ├── prompt_loader.py    # 提示词加载
│   ├── session_store.py    # 会话历史（内存）
│   ├── context_trimmer.py  # 上下文裁剪
│   ├── file_handler.py     # 文件加载 (txt/pdf/json)
│   ├── logger_handler.py   # 日志配置
│   └── path_tool.py        # 路径工具
│
├── db/                     # 数据持久化
│   └── chat_db.py          # SQLite 聊天记录
│
├── eval/                   # 评测
│   └── __init__.py
│
├── test/                   # 测试
│
├── data/                   # 知识库文档
│   ├── faq/                # FAQ 文档
│   ├── worldbook/          # 世界观文档
│   └── anime/              # 番剧 JSON
│
├── chroma_db/              # ChromaDB 持久化目录
└── logs/                   # 日志文件
```

## Embedding 配置

默认使用 DashScope 云端 embedding，零配置可用。

```bash
# 本地 bge-m3 模型（需先下载，约 2.2GB）
EMBEDDING_MODE=local
HF_ENDPOINT=https://hf-mirror.com   # 国内镜像

# OpenAI 兼容云端
EMBEDDING_MODE=cloud
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

## 混合检索配置

`config/chroma.yaml`：

```yaml
retrieval:
  dense_weight: 0.7       # 向量检索权重
  sparse_weight: 0.3      # BM25 权重
  reranker_enabled: false  # bge-reranker-base 重排（~1.1GB）
```

## 安全特性

- **工具黑名单**：`delete / remove / exec / shell / sudo / kill` 等危险操作默认拦截
- **MCP 白名单**：远端工具默认拒绝，需手动加入 `gate.yaml`
- **路径穿越检测**：参数含 `../` 或 `..\` 自动拦截
- **鉴权工具检查**：敏感工具需 user_id 方可执行

## License

MIT
