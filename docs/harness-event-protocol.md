# HarnessEvent 公共事件协议

MutiRoleAgent 使用一套 `HarnessEvent` 贯穿 Harness、FastAPI SSE、WebSocket 和 React。
项目不引入 AG-UI，也不维护第二套前端事件模型。

## 事件信封

```json
{
  "version": 1,
  "type": "final_text",
  "run_id": "run-123",
  "sequence": 6,
  "data": {
    "text": "这是最终回答",
    "delta": false
  }
}
```

- `version`：协议版本。
- `type`：事件类型，也是 SSE 的 `event` 名称。
- `run_id`：一次用户请求的运行标识。
- `sequence`：同一运行中从 1 开始严格递增的序号。
- `data`：当前事件的载荷。

## 公共事件

| type | 用途 | 写入会话历史 |
|---|---|---|
| `run_start` | 一轮运行开始 | 否 |
| `process_text` | 带工具调用的 LLM 中间文本 | 否 |
| `tool_start` | 用户可见工具开始 | 否 |
| `tool_end` | 用户可见工具结束 | 否 |
| `structured_data` | 前端卡片数据 | 否 |
| `final_text` | 无工具调用的终止轮文本 | 是 |
| `run_end` | 完成、失败、超时或取消 | 否 |

`tool_start` 和 `tool_end` 必须使用 `tool_call_id` 配对，不能按工具名称猜测。

## 文本判定规则

```text
AIMessage 有 tool_calls
  → content 只能成为 process_text

AIMessage 没有 tool_calls
  → content 才能成为 final_text
```

结构化 JSON 校验成功后从最终自然语言中移除，并通过 `structured_data` 独立发送。
React 不应再从 Assistant 正文中猜测或删除 JSON。

## 内部事件

Skill 激活、retry、checkpoint、runtime feedback 和 compaction 只进入日志、RunStore
或 CheckpointStore，不进入公共事件流。`invoke_skill` 和 `list_skills` 也不会产生前端 Tool Card。

## 传输约定

SSE：

```text
event: final_text
data: {完整 HarnessEvent JSON}
```

WebSocket 直接发送同一个 `HarnessEvent` JSON，不增加转换层。
