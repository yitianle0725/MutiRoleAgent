# Session 驱动的 Chat / Work 主链

## 核心原则

Session 在创建时绑定 `user_id + persona_id + mode`。这三个字段在 Session 生命周期内不可修改；切换角色或模式意味着创建或进入另一个 Session。

```text
入口
  -> ConversationCoordinator
  -> SessionContextBuilder
  -> ChatExecutor | WorkExecutor
  -> StreamEvent
  -> TurnFinishHook
```

- `chat`：完整角色 Prompt，无工具，直接流式调用聊天模型。
- `work`：完整角色 Prompt，通过 `LangGraphAgentCore` 运行模型与工具循环。
- 请求只提交 `session_id + message`，User、Persona 和 Mode 以数据库记录为准。

## 上下文作用域

```text
User Global
  ├─ 稳定画像
  └─ 跨角色长期事实

User × Persona
  ├─ 称呼和关系状态
  └─ 共同经历与角色专属记忆

Session
  ├─ Chat / Work 模式
  ├─ 历史与摘要
  └─ workspace 和临时状态
```

Session 隔离对话状态，Persona 隔离角色关系，User 保存稳定画像。

## API

创建会话：

```json
{
  "user_id": "local_user",
  "persona_id": "cyrene",
  "mode": "chat"
}
```

发送消息：

```json
{
  "session_id": "session-id",
  "message": "你好"
}
```

旧会话会幂等迁移为 `local_user + cyrene + chat`，旧表保留作为回滚来源。
