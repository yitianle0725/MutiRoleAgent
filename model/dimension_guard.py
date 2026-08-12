"""
维度校验模块
============
跨 embedding provider 切换时，检测维度 mismatch 并自动清理旧数据。

元数据格式 (chroma_db/.embedding_meta.json)::

    {
        "faq": {
            "provider": "fastembed",
            "model": "BAAI/bge-m3",
            "dims": 1024,
            "updated_at": "2026-08-12T10:00:00"
        },
        ...
    }

Usage::

    from model.dimension_guard import DimensionGuard
    from model.factory import embedding_model

    dg = DimensionGuard("chroma_db")
    dg.check_or_clear("faq", embedding_model, rebuild_fn=...)
"""

import json
import os
import shutil
from datetime import datetime
from typing import Callable

from utils.logger_handler import logger


class DimensionGuard:
    """跨 provider 维度校验器。

    每次访问 ChromaDB collection 时校验当前 provider 的维度
    是否与已存储的向量数据兼容。不匹配时自动清空旧数据。
    """

    def __init__(self, persist_dir: str):
        self._persist_dir = persist_dir
        self._meta_path = os.path.join(persist_dir, ".embedding_meta.json")
        self._metadata: dict[str, dict] = {}
        self._load()

    # ---- 文件 IO ----

    def _load(self):
        """从磁盘加载元数据。"""
        if os.path.exists(self._meta_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
                logger.debug(
                    f"[DimensionGuard] 已加载元数据: "
                    f"{len(self._metadata)} 个 collection"
                )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"[DimensionGuard] 元数据文件损坏，重建: {e}")
                self._metadata = {}

    def _save(self):
        """写入元数据到磁盘。"""
        os.makedirs(self._persist_dir, exist_ok=True)
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, ensure_ascii=False, indent=2)

    # ---- 校验逻辑 ----

    def check_or_clear(
        self,
        collection_name: str,
        provider,
        rebuild_fn: Callable[[], None] | None = None,
    ) -> bool:
        """校验 collection 维度是否与 provider 匹配。

        Args:
            collection_name: Collection 名称 ("faq"/"worldbook"/"anime")
            provider: EmbeddingProvider 实例 (需要有 cache_identity 属性)
            rebuild_fn: mismatch 时调用的重建回调

        Returns:
            True: 维度匹配，无需重建（快速路径）
            False: 维度 mismatch，已清空旧数据（调用方需重建索引）

        Raises:
            RuntimeError: 若 provider 不可用（is_available() → False）
        """
        if not provider.is_available():
            raise RuntimeError(
                f"[DimensionGuard] Provider '{provider.name}' 不可用，"
                f"无法校验 collection '{collection_name}'"
            )

        identity = provider.cache_identity
        stored = self._metadata.get(collection_name)

        # 首次使用 — 写入元数据
        if stored is None:
            self._metadata[collection_name] = {
                "provider": identity["provider"],
                "model": identity["model"],
                "dims": identity["dims"],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            self._save()
            logger.info(
                f"[DimensionGuard] 新建 '{collection_name}' 元数据: "
                f"provider={identity['provider']}, dims={identity['dims']}"
            )
            return True

        # 维度匹配 — 快速通过
        if stored.get("dims") == identity["dims"]:
            # 即使维度相同，更新模型信息（可能换了同维度的不同模型）
            if stored.get("provider") != identity["provider"]:
                stored["provider"] = identity["provider"]
                stored["model"] = identity["model"]
                stored["updated_at"] = datetime.now().isoformat()
                self._save()
                logger.info(
                    f"[DimensionGuard] '{collection_name}' provider 变更: "
                    f"{stored.get('provider')} → {identity['provider']} "
                    f"(dims 相同，无需重建)"
                )
            return True

        # 维度 mismatch — 清空 + 重建
        old_dims = stored.get("dims")
        old_provider = stored.get("provider", "unknown")
        logger.warning(
            f"[DimensionGuard] '{collection_name}' 维度 mismatch: "
            f"旧: {old_provider}/{old_dims}d → "
            f"新: {identity['provider']}/{identity['dims']}d"
            f" — 即将清空旧数据"
        )

        self._clear_collection(collection_name)

        # 更新元数据
        self._metadata[collection_name] = {
            "provider": identity["provider"],
            "model": identity["model"],
            "dims": identity["dims"],
            "created_at": stored.get("created_at", datetime.now().isoformat()),
            "updated_at": datetime.now().isoformat(),
        }
        self._save()

        # 调用重建回调（如果提供）
        if rebuild_fn is not None:
            logger.info(
                f"[DimensionGuard] 触发重建回调: collection='{collection_name}'"
            )
            rebuild_fn()

        return False

    def _clear_collection(self, collection_name: str):
        """清空指定 collection 的 ChromaDB 数据。

        ChromaDB 按 collection 名分目录存储:
          chroma_db/{uuid}/

        直接删除整个 persist_dir 下的所有内容是不安全的（会影响其他 collection）。
        这里通过 ChromaDB 的 API 删除 collection 中的所有文档。
        """
        try:
            from langchain_chroma import Chroma
            from utils.config_handler import chroma_config

            # 获取 collection config 获取 embedding model
            from model.factory import embedding_model

            store = Chroma(
                collection_name=collection_name,
                embedding_function=embedding_model,
                persist_directory=self._persist_dir,
            )

            # 获取所有文档 ID 并删除
            doc_ids = store.get()["ids"]
            if doc_ids:
                store.delete(doc_ids)
                logger.info(
                    f"[DimensionGuard] 已清空 '{collection_name}' "
                    f"({len(doc_ids)} 条文档)"
                )
        except Exception as e:
            logger.error(
                f"[DimensionGuard] 清空 '{collection_name}' 失败: {e}"
            )
            # 兜底: 删除 persist 目录
            chroma_dir = os.path.join(self._persist_dir, collection_name)
            if os.path.exists(chroma_dir):
                shutil.rmtree(chroma_dir, ignore_errors=True)
                logger.warning(
                    f"[DimensionGuard] 强制删除目录: {chroma_dir}"
                )

    # ---- 查询接口 ----

    def get_metadata(self, collection_name: str) -> dict | None:
        """获取指定 collection 的元数据。"""
        return self._metadata.get(collection_name)

    def get_all_metadata(self) -> dict[str, dict]:
        """获取所有 collection 的元数据。"""
        return dict(self._metadata)

    def reset(self, collection_name: str | None = None):
        """手动重置元数据（用于调试/迁移）。"""
        if collection_name:
            self._metadata.pop(collection_name, None)
        else:
            self._metadata.clear()
        self._save()
        logger.info(
            f"[DimensionGuard] 已重置元数据: "
            f"{collection_name or '全部'}"
        )
