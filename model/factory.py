"""
模型工厂
========
统一管理 LLM 和 Embedding 模型的创建。

LLM 统一走 OpenAI 兼容协议，默认连接阿里百炼 DashScope 兼容端点
（``https://dashscope.aliyuncs.com/compatible-mode/v1``）。

Embedding 使用 AutoProvider 自动选择:
  - ``EMBEDDING_MODE=local`` → 本地 ONNX bge-m3 (fastembed, 1024d)
  - ``EMBEDDING_MODE=cloud`` → OpenAI 兼容云端 /embeddings
  - ``EMBEDDING_MODE=dashscope`` → DashScope 原生 SDK（向后兼容）
  - ``EMBEDDING_MODE=auto`` → 降级链: local → cloud → dashscope → null

LLM 配置（环境变量）:
- ``LLM_API_KEY``   : API 密钥（fallback: ``DASHSCOPE_API_KEY``）
- ``LLM_BASE_URL``  : 自定义 API 地址（默认阿里百炼兼容端点）
- ``LLM_MODEL``     : 模型名称（默认 qwen3-max）

Embedding 配置（环境变量，均为可选）:
- ``EMBEDDING_MODE``       : 模式选择 auto/local/cloud/dashscope (默认 auto)
- ``HF_ENDPOINT``          : HuggingFace 镜像（国内用户建议 https://hf-mirror.com）
- ``EMBEDDING_API_KEY``    : API 密钥（fallback: LLM_API_KEY → DASHSCOPE_API_KEY）
- ``EMBEDDING_BASE_URL``   : 云端 /embeddings 地址
- ``EMBEDDING_MODEL``      : 模型名（默认 text-embedding-v4）

切换示例:
  LLM → DeepSeek:  LLM_BASE_URL=https://api.deepseek.com/v1
  LLM → Kimi:      LLM_BASE_URL=https://api.moonshot.cn/v1
  LLM → OpenAI:    LLM_BASE_URL=https://api.openai.com/v1
  LLM → Ollama:    LLM_BASE_URL=http://localhost:11434/v1

  Embedding → 本地 ONNX:  EMBEDDING_MODE=local（默认，无需配置）
  Embedding → OpenAI:      EMBEDDING_BASE_URL=https://api.openai.com/v1
  Embedding → Ollama:      EMBEDDING_BASE_URL=http://localhost:11434/v1

.. note::

    Embedding 模型不可跨厂商混用——不同模型产出的向量互不兼容。
    切换 embedding 厂商后 DimensionGuard 会自动检测并清空旧数据。
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import httpx

from utils.config_handler import rag_config

load_dotenv()

# ---- LLM 配置 ----
_LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
_LLM_BASE_URL = os.getenv("LLM_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
_LLM_MODEL = os.getenv("LLM_MODEL") or rag_config.get("chat_model_name", "qwen3-max")


def _create_chat_model() -> ChatOpenAI:
    """创建 LLM 聊天模型。

    统一使用 OpenAI 兼容协议，通过 ``LLM_BASE_URL`` 区分不同厂商。
    默认连接阿里百炼 DashScope 兼容端点。
    """
    return ChatOpenAI(
        model=_LLM_MODEL,
        api_key=_LLM_API_KEY,  # type: ignore[arg-type]
        base_url=_LLM_BASE_URL,
        timeout=httpx.Timeout(
            connect=15.0,   # 连接超时：15 秒连不上就报错
            read=300.0,     # 读取超时：qwen3-max 推理可能较慢
            write=30.0,     # 写入超时：发送请求体最多 30 秒
            pool=15.0,      # 连接池超时：与 connect 一致，避免假死
        ),
        max_retries=2,
    )


def _create_embedding_model():
    """创建 Embedding 模型（使用 AutoProvider 自动选择）。

    降级链 (EMBEDDING_MODE=auto):
      local(fastembed/bge-m3) → cloud(OpenAI兼容) → dashscope(兜底)

    也可通过 EMBEDDING_MODE 强制指定: local / cloud / dashscope
    """
    from model.embedding_provider import AutoProvider
    return AutoProvider()


chat_model = _create_chat_model()
embedding_model = _create_embedding_model()
