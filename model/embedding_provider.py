"""
Embedding Provider 接口 + 多厂商实现
=====================================

参照 TypeScript 昔涟 Agent 的 EmbeddingProvider 架构：

- ``LocalONNXProvider`` — fastembed → BAAI/bge-m3 (1024d), ONNX CPU
- ``OpenAICompatProvider`` — /embeddings 兼容端点 (OpenAI/Ollama/DeepSeek 等)
- ``DashScopeProvider`` — 阿里云原生 SDK (向后兼容)
- ``AutoProvider`` — 按 EMBEDDING_MODE 自动选择 + 降级链

所有 Provider 都实现 LangChain Embeddings 接口 (embed_query / embed_documents)，
可直接传入 ``Chroma(embedding_function=...)`` 使用。

Usage::

    from model.embedding_provider import AutoProvider
    provider = AutoProvider()
    vec = provider.embed_query("测试文本")
    # → list[float] of 1024 dims (bge-m3)

降级链 (auto 模式): local → cloud → dashscope → null
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Sequence

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("model.embedding_provider")

# ==================== 配置常量 ====================

_EMBEDDING_MODE = os.getenv("EMBEDDING_MODE", "auto")

_EMBEDDING_API_KEY = (
    os.getenv("EMBEDDING_API_KEY")
    or os.getenv("LLM_API_KEY")
    or os.getenv("DASHSCOPE_API_KEY")
)
_EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "")
_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")


# ==================== Abstract Base ====================

class EmbeddingProvider(ABC):
    """Embedding Provider 统一接口。

    每个 provider 负责:
      - 模型加载/下载
      - 返回向量 + 维度元数据
      - is_available() 健康检查
      - cache_identity 用于维度校验的跨 provider 识别
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识 (如 'fastembed', 'openai', 'dashscope')。"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """实际使用的模型名 (如 'BAAI/bge-m3', 'text-embedding-3-small')。"""
        ...

    @property
    @abstractmethod
    def dims(self) -> int:
        """向量维度。初次调用后缓存。"""
        ...

    @property
    def cache_identity(self) -> dict:
        """返回 provider 标识字典，用于维度校验。

        DimensionGuard 用此字典判断 provider 是否与旧数据兼容。
        """
        return {
            "provider": self.name,
            "model": self.model_name,
            "dims": self.dims,
        }

    @abstractmethod
    def is_available(self) -> bool:
        """检查 provider 是否可服务。

        - 本地: 模型是否加载成功
        - 云端: API 是否可达
        """
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """嵌入单条查询文本。"""
        ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """嵌入多条文档文本。"""
        ...


# ==================== Local ONNX Provider (fastembed) ====================

class LocalONNXProvider(EmbeddingProvider):
    """本地 embedding 提供者（sentence-transformers）。

    使用 sentence-transformers 加载 BAAI/bge-m3 模型（1024 维）。
    支持 HF_ENDPOINT 国内镜像设置。

    线程安全：embed_query/embed_documents 加锁。

    .. note::

        bge-m3 当前通过 sentence-transformers (PyTorch) 加载。
        ONNX 加速可通过 optimum-cli 导出后切换:
          optimum-cli export onnx --model BAAI/bge-m3 models/bge-m3-onnx/
    """

    _MODEL_ID = "BAAI/bge-m3"
    _EXPECTED_DIMS = 1024

    def __init__(self, cache_dir: str | None = None):
        self._model = None
        self._dims: int | None = None
        self._lock = __import__("threading").Lock()
        self._cache_dir = cache_dir or os.path.join(
            os.path.dirname(__file__), "..", "models"
        )

    @property
    def name(self) -> str:
        return "local-bge-m3"

    @property
    def model_name(self) -> str:
        return self._MODEL_ID

    @property
    def dims(self) -> int:
        if self._dims is None:
            self._ensure_loaded()
        return self._dims  # type: ignore[return-value]

    def is_available(self) -> bool:
        try:
            self._ensure_loaded()
            return True
        except Exception as e:
            logger.warning(f"[LocalONNXProvider] 不可用: {e}")
            return False

    def _ensure_loaded(self):
        """懒加载 bge-m3 模型。"""
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return

            try:
                from sentence_transformers import SentenceTransformer

                logger.info(
                    f"[LocalONNXProvider] 加载 {self._MODEL_ID} (首次启动需下载 ~2.2GB)..."
                )

                # 使用 sentence-transformers 加载 bge-m3
                # 自动支持 HF_ENDPOINT 镜像环境变量
                self._model = SentenceTransformer(
                    self._MODEL_ID,
                    cache_folder=self._cache_dir if os.path.isdir(self._cache_dir) else None,
                    device="cpu",
                )

                # 探测维度
                probe = self._model.encode(
                    ["__dim_probe__"],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                self._dims = int(probe.shape[1])
                logger.info(
                    f"[LocalONNXProvider] 加载成功, dims={self._dims}"
                )

            except ImportError:
                raise RuntimeError(
                    "sentence-transformers 未安装。"
                    "请执行: pip install sentence-transformers"
                )
            except Exception as e:
                self._model = None
                self._dims = None
                raise RuntimeError(
                    f"[LocalONNXProvider] 模型加载失败: {e}"
                ) from e

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        with self._lock:
            embeddings = self._model.encode(  # type: ignore[union-attr]
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=32,
            )
        return embeddings.tolist()


# ==================== OpenAI 兼容云端 Provider ====================

class OpenAICompatProvider(EmbeddingProvider):
    """OpenAI 兼容 embedding 提供者。

    复用现有 langchain_openai.OpenAIEmbeddings，支持任何 /embeddings 端点。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self._api_key = api_key or _EMBEDDING_API_KEY
        self._base_url = base_url or _EMBEDDING_BASE_URL
        self._model_id = model or _EMBEDDING_MODEL
        self._client = None
        self._dims: int | None = None

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_id

    @property
    def dims(self) -> int:
        if self._dims is None:
            self._ensure_loaded()
        return self._dims  # type: ignore[return-value]

    def is_available(self) -> bool:
        if not self._base_url:
            return False
        try:
            self._ensure_loaded()
            return True
        except Exception as e:
            logger.warning(f"[OpenAICompatProvider] 不可用: {e}")
            return False

    def _ensure_loaded(self):
        if self._client is not None:
            return

        from langchain_openai import OpenAIEmbeddings
        import httpx

        self._client = OpenAIEmbeddings(
            model=self._model_id,
            api_key=self._api_key,  # type: ignore[arg-type]
            base_url=self._base_url,
            http_async_client=httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
            ),
        )

        # 探测维度
        probe = self._client.embed_documents(["__dim_probe__"])
        self._dims = len(probe[0])
        logger.info(
            f"[OpenAICompatProvider] 已连接 {self._base_url}, "
            f"model={self._model_id}, dims={self._dims}"
        )

    def embed_query(self, text: str) -> list[float]:
        self._ensure_loaded()
        return self._client.embed_query(text)  # type: ignore[union-attr]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        return self._client.embed_documents(texts)  # type: ignore[union-attr]


# ==================== DashScope Provider (向后兼容) ====================

class DashScopeProvider(EmbeddingProvider):
    """阿里云 DashScope embedding 提供者（向后兼容）。

    不设置任何额外环境变量时的默认兜底方案。
    """

    def __init__(self, model: str | None = None):
        self._model_id = model or _EMBEDDING_MODEL
        self._client = None
        self._dims: int | None = None

    @property
    def name(self) -> str:
        return "dashscope"

    @property
    def model_name(self) -> str:
        return self._model_id

    @property
    def dims(self) -> int:
        if self._dims is None:
            self._ensure_loaded()
        return self._dims  # type: ignore[return-value]

    def is_available(self) -> bool:
        try:
            self._ensure_loaded()
            return True
        except Exception as e:
            logger.warning(f"[DashScopeProvider] 不可用: {e}")
            return False

    def _ensure_loaded(self):
        if self._client is not None:
            return

        from langchain_community.embeddings import DashScopeEmbeddings

        self._client = DashScopeEmbeddings(model=self._model_id)

        # 探测维度
        probe = self._client.embed_documents(["__dim_probe__"])
        self._dims = len(probe[0])
        logger.info(
            f"[DashScopeProvider] 已连接, model={self._model_id}, dims={self._dims}"
        )

    def embed_query(self, text: str) -> list[float]:
        self._ensure_loaded()
        return self._client.embed_query(text)  # type: ignore[union-attr]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        return self._client.embed_documents(texts)  # type: ignore[union-attr]


# ==================== Auto Provider (降级链) ====================

class AutoProvider(EmbeddingProvider):
    """自动选择可用的 embedding provider。

    选择策略 (EMBEDDING_MODE):
      - "local"    — 强制本地 ONNX
      - "cloud"    — 强制云端 OpenAI 兼容
      - "dashscope" — 强制 DashScope
      - "auto"     — 降级链: local → cloud → dashscope → None

    Usage::

        provider = AutoProvider()
        if not provider.is_available():
            print("WARNING: 无可用的 embedding provider")
    """

    def __init__(self):
        self._active: EmbeddingProvider | None = None
        self._mode = _EMBEDDING_MODE
        self._select()

    # ---- 委托属性 ----

    @property
    def name(self) -> str:
        return self._active.name if self._active else "none"

    @property
    def model_name(self) -> str:
        return self._active.model_name if self._active else "none"

    @property
    def dims(self) -> int:
        if self._active is None:
            raise RuntimeError("没有可用的 embedding provider")
        return self._active.dims

    @property
    def cache_identity(self) -> dict:
        if self._active is None:
            return {"provider": "none", "model": "none", "dims": 0}
        return self._active.cache_identity

    @property
    def active_provider(self) -> EmbeddingProvider | None:
        """返回当前活跃的底层 provider，供调试使用。"""
        return self._active

    def is_available(self) -> bool:
        return self._active is not None

    def _select(self):
        """按降级链选择 provider。"""
        candidates: list[tuple[str, callable]] = []

        if self._mode == "local":
            candidates = [("local", lambda: LocalONNXProvider())]
        elif self._mode == "cloud":
            candidates = [("cloud", lambda: OpenAICompatProvider())]
        elif self._mode == "dashscope":
            candidates = [("dashscope", lambda: DashScopeProvider())]
        else:  # auto
            if _EMBEDDING_BASE_URL:
                # cloud 配置了 → local → cloud → dashscope
                candidates = [
                    ("local", lambda: LocalONNXProvider()),
                    ("cloud", lambda: OpenAICompatProvider()),
                    ("dashscope", lambda: DashScopeProvider()),
                ]
            else:
                # 未配置 cloud → local → dashscope
                candidates = [
                    ("local", lambda: LocalONNXProvider()),
                    ("dashscope", lambda: DashScopeProvider()),
                ]

        for label, factory in candidates:
            try:
                provider = factory()
                if provider.is_available():
                    self._active = provider
                    logger.info(
                        f"[AutoProvider] 选定: {label} "
                        f"(model={provider.model_name}, dims={provider.dims})"
                    )
                    return
            except Exception as e:
                logger.warning(f"[AutoProvider] {label} 不可用: {e}")

        self._active = None
        logger.error(
            "[AutoProvider] 所有 embedding provider 均不可用！"
            "RAG 检索将无法工作。"
        )

    def embed_query(self, text: str) -> list[float]:
        if self._active is None:
            raise RuntimeError("没有可用的 embedding provider")
        return self._active.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._active is None:
            raise RuntimeError("没有可用的 embedding provider")
        return self._active.embed_documents(texts)
