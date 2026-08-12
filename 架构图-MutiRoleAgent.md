# 🏗️ MutiRoleAgent 架构图

> Python Streamlit AI 助手 | ReAct Agent + RAG + MCP + Skill

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit 前端 (app.py)                   │
│                                                             │
│  ┌────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ 聊天面板    │  │ 会话管理     │  │ 知识库上传           │ │
│  │ (主界面)    │  │ (侧边栏)     │  │ (TXT/PDF/JSON)      │ │
│  └────────────┘  └─────────────┘  └─────────────────────┘ │
│  ┌────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ 角色切换    │  │ Skill 列表   │  │ 用户 ID             │ │
│  │ (4 角色)    │  │ (12 个)     │  │                     │ │
│  └────────────┘  └─────────────┘  └─────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   ReactAgent (react_agent.py)                │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  System Prompt                                       │   │
│  │  ├─ 基础 Prompt (从 YAML 加载)                        │   │
│  │  ├─ Skill 摘要 (动态注入)                              │   │
│  │  └─ Persona Overlay (角色人设覆盖)                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         LangGraph ReAct Agent (create_agent)          │   │
│  │                                                       │   │
│  │   ┌──────┐   ┌───────────┐   ┌──────┐   ┌────────┐  │   │
│  │   │思考  │──▶│ 调用工具   │──▶│观察  │──▶│ 回复   │  │   │
│  │   │(LLM) │   │(Tool Call)│   │(观察)│   │ (LLM)  │  │   │
│  │   └──────┘   └─────┬─────┘   └──────┘   └────────┘  │   │
│  │                    │                                  │   │
│  │         ┌──────────▼──────────┐                      │   │
│  │         │  UnifiedMiddleware  │                      │   │
│  │         │  ┌────────────────┐ │                      │   │
│  │         │  │ 1. Action Gate │ │ ← 白名单/黑名单过滤    │   │
│  │         │  │ 2. Policy      │ │ ← 参数 Pydantic 校验   │   │
│  │         │  │ 3. Timeout     │ │ ← 超时控制             │   │
│  │         │  │ 4. CITA        │ │ ← 意图分类 + Token注入  │   │
│  │         │  │ 5. Persona     │ │ ← 角色语气覆盖          │   │
│  │         │  └────────────────┘ │                      │   │
│  │         └────────────────────┘                      │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
┌─────────▼──┐  ┌──────────▼─────┐  ┌──────▼──────────┐
│   Tools    │  │    Skills      │  │   Memory / RAG  │
│  工具系统   │  │   技能系统      │  │   记忆和知识库   │
└────────────┘  └────────────────┘  └─────────────────┘
```

---

## 核心分层

```
┌────────────────────────────────────────────────────────────┐
│                   1. 前端层 (Streamlit)                      │
│                                                            │
│  app.py                                                    │
│  ├─ 聊天面板 (主界面)                                       │
│  │   ├─ 流式输出（逐字渲染 + 光标动画）                       │
│  │   ├─ ToolEvent 状态提示（"正在检索…"）                    │
│  │   └─ 时间戳显示                                         │
│  ├─ 侧边栏                                                 │
│  │   ├─ 会话管理（新建/切换/删除 + 统计信息）                 │
│  │   ├─ 角色人设（4 角色可切换 + 懒加载）                    │
│  │   ├─ 知识库上传（TXT/PDF/JSON → ChromaDB）              │
│  │   └─ Skill 列表（按分类展开/折叠）                        │
│  └─ 状态管理                                               │
│      ├─ session_id（URL 参数持久化）                        │
│      └─ SQLite 历史恢复（刷新不丢失）                        │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                2. Agent 层 (react_agent.py)                  │
│                                                            │
│  ReactAgent                                                │
│  ├─ init_agent()         ← 异步初始化（MCP 工具 + Skill 加载）│
│  ├─ execute_stream()     ← 流式执行入口                      │
│  │   ├─ trim_history()    ← 上下文裁剪（Token/Round 限制）    │
│  │   ├─ create_agent_state() ← 构建 State                   │
│  │   ├─ agent.astream()   ← LangGraph 流式执行              │
│  │   └─ 双写持久化 (内存 + SQLite)                          │
│  ├─ 会话管理                                                │
│  │   ├─ 新建/切换/清除                                      │
│  │   ├─ 自定义标题生成（LLM 自动命名）                       │
│  │   └─ 用户画像提取（异步，不阻塞）                          │
│  └─ 事件流                                                  │
│      ├─ TextChunk (文字片段)                                │
│      └─ ToolEvent (工具开始/结束)                           │
└───────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│              3. 中间件层 (UnifiedMiddleware)                  │
│                                                            │
│  每个 Tool Call 依次经过 5 层检查：                           │
│                                                            │
│  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ ① Gate     │→│ ② Policy │→│ ③ Timeout│→│ ④ CITA   │→  │
│  │ 门控拦截   │ │ 参数校验  │ │ 超时控制  │ │ 意图注入  │   │
│  └────────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                                                           │
│  ⑤ Persona (人设覆盖) → 最终执行 handler                    │
│                                                            │
│  Gate:    白名单/黑名单 → 路径穿越检测 → 风险拦截             │
│  Policy:  Pydantic Schema 校验 → 友好错误返回                │
│  Timeout: 每工具独立超时（fetch: 60s, default: 30s）        │
│  CITA:    ANIME / WEATHER / FILE / REPORT / CHAT 五分类     │
│  Persona: 按当前角色注入语气指令                              │
└──────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                 4. 能力层 (Capabilities)                     │
│                                                            │
│  ┌─────────────────────┐  ┌─────────────────────────────┐ │
│  │ 本地 Tools (7+)      │  │ MCP Tools (远端)            │ │
│  │                      │  │                             │ │
│  │ search_anime         │  │ maps_weather (高德天气)     │ │
│  │ fetch_anime          │  │ maps_ip_location (IP定位)   │ │
│  │ get_season_anime     │  │ maps_direction_* (路线规划)  │ │
│  │ rag_summarize        │  │ maps_text_search (地点搜索)  │ │
│  │ switch_persona       │  │ web_search (网页搜索)       │ │
│  │ reset_persona        │  │ web_search_prime (专业搜索) │ │
│  │ get_public_ip        │  │                             │ │
│  └─────────────────────┘  └─────────────────────────────┘ │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Skills (12 个)                                      │   │
│  │                                                     │   │
│  │ 自建 (6):            官方 (6):                       │   │
│  │ 🎬 recommend-anime    📄 pdf                         │   │
│  │ 📺 season-overview    📊 pptx                        │   │
│  │ 🔍 anime-deep-dive    📈 xlsx                        │   │
│  │ 🌤️ weather-lifestyle  📝 docx                        │   │
│  │ 📖 download-novel     🛠️ skill-creator               │   │
│  │ 📁 file-processor     🔌 mcp-builder                 │   │
│  │                                                     │   │
│  │ 匹配策略: Slash Command → 关键词 N-gram → LLM 自选   │   │
│  └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│              5. 数据和持久化层                               │
│                                                            │
│  DB:                          RAG:                         │
│  ├─ chat_db.py                ├─ rag_service.py            │
│  │   SQLite 持久化             │   LLM 总结 + 向量检索       │
│  │   ├─ 会话元数据             ├─ vector_store.py           │
│  │   ├─ 消息历史               │   ChromaDB                 │
│  │   └─ 用户画像               │   ├─ FAQ 集合              │
│  │                             │   ├─ WorldBook 集合        │
│  ├─ session_store.py           │   └─ Anime 集合            │
│  │   内存缓存 (dict-based)     │                             │
│  │                             ├─ knowledge_base.py         │
│  └─ context_trimmer.py         │   文件上传 → 向量入库       │
│      Token + Round 双重限制    │                             │
│                              └─ file_handler.py             │
│                                 TXT/PDF/JSON 加载器          │
│                                                            │
│  Anime:                        Novels:                     │
│  ├─ crawl_bangumi.py           ├─ crawl_novel.py           │
│  │   Bangumi 番剧数据           │   小说爬虫                  │
│  ├─ crawl_yuc.py               ├─ download_novel.py        │
│  │   Yuc 动漫数据               │   下载模块                  │
│  └─ retry_handler.py           └─ layout_novel.py          │
│      熔断 + 退避重试               排版清洗                   │
└────────────────────────────────────────────────────────────┘
```

---

## 与 EchoBot / Cyrene-Agent 的对应关系

```
概念               EchoBot              Cyrene-Agent          MutiRoleAgent (我们)
───────────────────────────────────────────────────────────────────────────────
Agent 核心         AgentCore            CyreneAgent           ReactAgent
Agent 框架         LangGraph            LangGraph             LangGraph
决策路由           DecisionEngine       TaskRouter            CITA (意图分类)
工具安全           N/A (middleware)     ActionGate            ActionGate
参数校验           无                    ToolArgValidator      ExecutionPolicy
上下文管理         内联                  CITA (独立系统)        ContextTrimmer
角色扮演           RoleplayEngine       Soul + Styles         Persona Loader
Skill 系统         skill_support/       skills/ (TS)          skill_support/
Skill 格式         SKILL.md (YAML)      SKILL.md + manifest   SKILL.md (YAML)
渠道               QQ/Telegram/Console  WeChat/Feishu/Web     仅 Streamlit
前端               FastAPI + Live2D     Electron + React      Streamlit
语音               TTS + ASR            TTS (5引擎) + ASR     无
Live2D             ✅ (内置模型)          ✅ (Cyrene 角色)       ❌ (计划中)
记忆               内存 + 文件           ContextStore          SQLite + ChromaDB
多模型             OpenAI Compatible    多厂商适配             阿里百炼
```

---

## 数据流（一轮对话）

```
用户输入 "推荐几部热血番"
    │
    ▼
┌──────────────────────┐
│ 1. 加载会话历史        │  session_store.get_history()
│    裁剪超限上下文       │  trim_history(max_tokens=6000)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ 2. 构建 AgentState    │  query + history + persona + user_id
└──────────┬───────────┘
           │
           ▼
┌────────────────────────────────────────────────┐
│ 3. LangGraph Agent Loop (astream)              │
│                                                │
│   Thought: "用户想找热血番剧，我先查看 Skill"    │
│       │                                        │
│       ▼                                        │
│   Tool Call: invoke_skill("recommend-anime")   │
│       │    → UnifiedMiddleware 5 层检查         │
│       │    → 返回 SKILL.md 完整指令             │
│       ▼                                        │
│   Observation: 获得推荐工作流指令                │
│       │                                        │
│       ▼                                        │
│   Thought: "按 Skill 指令，调 search_anime"     │
│       │                                        │
│       ▼                                        │
│   Tool Call: search_anime(genre="热血")        │
│       │    → UnifiedMiddleware 5 层检查         │
│       │    → Bangumi API 返回数据               │
│       ▼                                        │
│   Observation: 找到 15 部热血番                  │
│       │                                        │
│       ▼                                        │
│   Final Answer: "为你推荐以下热血番…"            │
└────────────────┬───────────────────────────────┘
                 │
                 ▼
┌──────────────────────┐
│ 4. 双写持久化          │  session_store.append_pair()  (内存)
│    异步提取用户画像     │  chat_db.save_pair()          (SQLite)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ 5. 流式输出到前端       │  TextChunk → Streamlit 逐字渲染
│                       │  ToolEvent → 状态提示更新
└──────────────────────┘
```

---

## 关键目录

```
MutiRoleAgent/
├── app.py                    ← ★ Streamlit 前端入口
├── agent/
│   ├── react_agent.py          ← ★ ReAct Agent 主控制器
│   ├── stream_events.py        ← 流式事件 (TextChunk / ToolEvent)
│   ├── agent_state.py          ← AgentState 数据结构
│   ├── action_gate.py          ← 工具白名单/黑名单
│   ├── execution_policy.py     ← 参数 Pydantic 校验
│   ├── cita_classifier.py      ← 意图分类 (5 类)
│   ├── tool_wrapper.py         ← 工具超时 + 安全执行
│   ├── user_profile_extractor  ← 用户画像提取
│   ├── knowledge_base.py       ← 文件 → 向量入库
│   ├── skill_support/          ← ★ Skill 框架
│   │   ├── models.py           ← Skill / SkillMatch 数据类
│   │   ├── loader.py           ← YAML 解析 + 目录扫描
│   │   ├── registry.py         ← 注册表 + 关键词匹配
│   │   └── tools.py            ← invoke_skill / list_skills
│   └── tools/
│       ├── agent_tools.py      ← 本地工具定义
│       ├── mcp_client.py       ← MCP 远端工具连接
│       ├── unified_middleware   ← 5 层中间件
│       └── middleware.py       ← 旧版中间件（替换中）
├── skills/                     ← ★ Skill 目录 (12 个)
│   ├── recommend-anime/        ← 自建：动漫推荐
│   ├── season-overview/        ← 自建：季度新番
│   ├── anime-deep-dive/        ← 自建：作品分析
│   ├── weather-lifestyle/      ← 自建：天气生活
│   ├── download-novel/         ← 自建：小说下载
│   ├── file-processor/         ← 自建：文件处理
│   ├── pdf/                    ← 官方：PDF 处理
│   ├── pptx/                   ← 官方：PPT 生成
│   ├── xlsx/                   ← 官方：Excel 处理
│   ├── docx/                   ← 官方：Word 文档
│   ├── skill-creator/          ← 官方：元 Skill
│   └── mcp-builder/            ← 官方：MCP 构建
├── rag/                        ← RAG 知识库
│   ├── rag_service.py          ← 检索 + 总结
│   └── vector_store.py         ← ChromaDB 管理
├── db/
│   └── chat_db.py              ← SQLite 会话存储
├── utils/
│   ├── prompt_loader.py        ← 加载 YAML Prompt
│   ├── persona_loader.py       ← 角色人设加载
│   ├── context_trimmer.py      ← 上下文裁剪
│   ├── session_store.py        ← 内存会话缓存
│   └── config_handler.py       ← 配置中心
├── anime/                      ← 动漫数据
│   ├── crawl_bangumi.py        ← Bangumi 爬虫
│   └── crawl_yuc.py            ← Yuc 爬虫
├── novels/                     ← 小说下载
├── config/                     ← YAML 配置文件
├── data/                       ← 运行时数据
└── prompts/                    ← Prompt YAML 模板
```
