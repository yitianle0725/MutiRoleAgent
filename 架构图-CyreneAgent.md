# 🏗️ Cyrene-Agent 架构图

> TypeScript Electron 桌面宠物 + AI 助手 | Live2D + LangGraph + CITA

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Electron 桌面应用                          │
│                                                             │
│  ┌──────────────────────┐    ┌───────────────────────────┐ │
│  │    Renderer (前端)     │    │     Main Process (后端)    │ │
│  │    React + Vite       │◀──▶│     Node.js + LangGraph   │ │
│  │                       │IPC │                           │ │
│  │  ├─ Live2D 角色渲染    │    │  ├─ Orchestrator (核心)    │ │
│  │  ├─ 聊天界面           │    │  ├─ Skills (技能系统)      │ │
│  │  ├─ 设置面板           │    │  ├─ Channels (渠道)       │ │
│  │  └─ 音乐播放器         │    │  ├─ TTS / ASR (语音)     │ │
│  └──────────────────────┘    │  ├─ Embedding (本地模型)   │ │
│                               │  └─ Game Bot (游戏自动化)  │ │
│  ┌──────────────────────┐    └───────────────────────────┘ │
│  │    CLI (命令行)        │                                   │
│  │    Node.js 脚本        │                                   │
│  └──────────────────────┘                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 核心分层

```
┌────────────────────────────────────────────────────────────┐
│                   1. 用户界面层                              │
│                                                            │
│  Electron Window              CLI                          │
│  ├─ Live2D 角色 (Cyrene)      ├─ cyrene chat               │
│  │  表情 12 种                 ├─ cyrene code               │
│  │  动作 5 种                  └─ cyrene run                │
│  ├─ 聊天面板                                                │
│  ├─ 设置 / 技能管理                                         │
│  └─ 音乐播放器                                              │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                2. Orchestrator（Agent 核心）                 │
│                                                            │
│  ┌───────────────────────────────────────────────┐        │
│  │  CyreneAgent (cyrene-agent.ts)                │        │
│  │  ┌─────────────────────────────────────────┐  │        │
│  │  │        LangGraph Agent Loop              │  │        │
│  │  │   思考 → 调工具 → 观察 → 回复             │  │        │
│  │  └─────────────────────────────────────────┘  │        │
│  └───────────────────────────────────────────────┘        │
│                                                            │
│  关键子系统：                                               │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────────┐    │
│  │ CITA        │ │ Sub-Agents   │ │ Structured      │    │
│  │ 上下文管理    │ │ 子 Agent      │ │ Output          │    │
│  │             │ │              │ │ 结构化输出        │    │
│  │ - Token 预算 │ │ - doc-agent  │ │ - JSON Schema   │    │
│  │ - 内容裁剪   │ │ - search-agent│ │ - 自动重试       │    │
│  │ - RAG 检索   │ │ - 代码执行    │ │ - 格式校验       │    │
│  └─────────────┘ └──────────────┘ └─────────────────┘    │
│                                                            │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────────┐    │
│  │ Action Gate │ │ Native FC    │ │ Model Config    │    │
│  │ 工具安全过滤  │ │ 原生 Function  │ │ 多模型适配       │    │
│  │             │ │ Calling       │ │                 │    │
│  │ - 白名单     │ │              │ │ - Anthropic     │    │
│  │ - 风险拦截   │ │ - LangChain  │ │ - OpenAI       │    │
│  │ - 权限控制   │ │ - 直连 API   │ │ - MiniMax      │    │
│  └─────────────┘ └──────────────┘ └─────────────────┘    │
└──────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                 3. 能力层 (Capabilities)                     │
│                                                            │
│  Tools (~30+)                     Skills (9+)              │
│  ├─ fs-tools (文件系统)            ├─ pdf / docx / xlsx     │
│  ├─ document-tools (文档)          ├─ pptx-generator        │
│  ├─ life-tools (生活:天气/地图)     ├─ skill-creator         │
│  ├─ email-tools (邮件)             ├─ cyrene-learn-tutor    │
│  ├─ search-code-tools (代码搜索)   ├─ cyrene-music-         │
│  ├─ music-tools (音乐)             │   companion            │
│  ├─ travel-tools (旅行)            ├─ cyrene-obsidian-      │
│  ├─ history-tools (历史查询)       │   workspace            │
│  └─ play-live2d-action (表情动作)  ├─ cyrene-original-      │
│                                    │   voice                │
│  MCP (Model Context Protocol)     ├─ self-improving-       │
│  ├─ mcp-manager                   │   agent                │
│  └─ mcp-adapter                   └─ write-expense-report  │
│                                                            │
│  Code Execution (代码执行)                                  │
│  ├─ cline-runtime (沙箱执行)                                │
│  ├─ code-run-coordinator (执行协调)                         │
│  └─ verification-runner (结果验证)                          │
└──────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                  4. 渠道层 (Channels)                        │
│  ┌──────────────┬──────────────┬──────────────────┐       │
│  │  Web Console │   微信 (iLink) │  飞书 (Feishu)    │       │
│  │  (Electron)  │  (Bot 适配器)  │  (Bot 适配器)     │       │
│  └──────────────┴──────────────┴──────────────────┘       │
└──────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                 5. 基础设施层                                │
│                                                            │
│  TTS (文本转语音)          ASR (语音识别)                    │
│  ├─ GPT-SoVITS            └─ Volcano ASR                   │
│  ├─ MiniMax                                                │
│  ├─ MossLand                                               │
│  └─ Custom Cloud                                           │
│                                                            │
│  Embedding (本地)          Memory                          │
│  ├─ bge-reranker-base      ├─ Social Context (社交上下文)    │
│  └─ ms-marco-MiniLM        ├─ Context Store                │
│                             └─ Token Usage Store            │
│                                                            │
│  Game Bot (游戏自动化)      Stickers (表情包)                │
│  └─ Star Rail 日常          ├─ 嵌入向量检索                  │
│                             └─ 描述生成                     │
└────────────────────────────────────────────────────────────┘
```

---

## CITA 系统（上下文管理核心）

```
        ┌─────────────────────────────────┐
        │         CITA Service            │
        │  Context Injection & Token      │
        │  Allocation                     │
        └───────────────┬─────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
  ┌─────▼─────┐  ┌──────▼──────┐  ┌─────▼─────┐
  │ Semantic  │  │ Structural  │  │ Token     │
  │ Engine    │  │ Reducer     │  │ Budget    │
  │ (语义引擎) │  │ (结构裁剪)   │  │ (Token预算)│
  └───────────┘  └─────────────┘  └───────────┘

  工作流：
  消息 → Semantic 提取关键信息 → Structural 压缩上下文
       → Token Budget 控制总量 → 注入 Agent Prompt
```

---

## 数据流（一轮对话）

```
用户输入 (文本 / 语音 / 图片)
    │
    ▼
┌──────────────┐
│ Channel      │  ← 微信/飞书/控制台
│ Adapter      │     统一格式转换
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ CITA         │  ← 上下文注入 + Token 裁剪
│ Service      │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Action Gate  │  ← 工具安全过滤
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────┐
│       LangGraph Agent Loop           │
│                                      │
│  ┌──────────┐    ┌──────────────┐   │
│  │ 思考     │───▶│ 调用工具      │   │
│  │ (LLM)    │◀───│ (Tool Call)  │   │
│  └──────────┘    └──────────────┘   │
│       │                               │
│       ▼                               │
│  ┌──────────┐                        │
│  │ 回复     │                        │
│  │ (LLM)   │──▶ 结构化输出验证       │
│  └──────────┘                        │
└──────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ TTS + Live2D │  ← 语音合成 + 角色表情同步
│ Action        │
└──────┬───────┘
       │
       ▼
    用户看到/听到回复
```

---

## 关键目录

```
Cyrene-Agent/
├── src/
│   ├── main/
│   │   ├── orchestrator/     ← ★ Agent 核心（100+ 文件）
│   │   │   ├── cyrene-agent.ts        ← 主 Agent
│   │   │   ├── langgraph-agent-loop.ts ← ReAct 循环
│   │   │   ├── context-builder.ts     ← 上下文构建
│   │   │   ├── action-gate.ts         ← 安全门控
│   │   │   ├── sub-agents/            ← 子 Agent (doc/search)
│   │   │   ├── structured-output/     ← 结构化输出
│   │   │   ├── code/                  ← 代码执行引擎
│   │   │   ├── vendors/               ← 多模型适配
│   │   │   └── tools/                 ← 内置工具
│   │   ├── cita/              ← 上下文注入 & Token 分配
│   │   ├── skills/            ← 技能系统
│   │   ├── channels/          ← 多渠道 (微信/飞书)
│   │   ├── tts/               ← 语音合成 (5 引擎)
│   │   ├── asr/               ← 语音识别
│   │   ├── embedding-manager  ← 本地嵌入模型
│   │   ├── game-bot/          ← 游戏自动化
│   │   └── social-context/    ← 社交上下文管理
│   ├── renderer/              ← Electron 前端 (React)
│   └── cli/                   ← 命令行入口
├── prompts/                   ← 独立 Prompt 文件 (30+)
│   ├── chat_system.md         ← 聊天系统提示
│   ├── cita_system.md         ← CITA 系统提示
│   ├── soul.md                ← 角色灵魂 (昔涟人设)
│   ├── styles/                ← 5 种语气风格
│   └── worldbook/             ← 世界观设定
├── skills/                    ← 项目 Skill (9 个)
├── assets/models/cyrene/      ← Live2D 模型
├── models/                    ← 本地嵌入模型
├── vendor/                    ← 第三方 MCP (网易云音乐)
└── game-recipes/              ← 游戏自动化脚本
```
