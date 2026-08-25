"""Safely rebuild one or more RAG collections.

This command clears only the selected Chroma collection, its BM25 cache, and
its file-sync records before loading the documents again with the embedding
provider configured in ``.env``.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Direct execution starts with ``rag/`` on sys.path, so add the project root
# before importing sibling packages.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.vector_store import VectorStore
from utils.config_handler import chroma_config
from utils.path_tool import get_project_path


COLLECTIONS = ("acgn_daily", "anime", "game", "novel")


def _persist_directory() -> Path:
    configured = Path(str(chroma_config["persist_directory"]))
    return configured if configured.is_absolute() else get_project_path(configured)


def _clear_collection(store: VectorStore, collection: str) -> tuple[int, int]:
    """Delete only one collection's vectors and bookkeeping records."""
    chroma = store._get_store(collection)
    existing_ids = chroma.get().get("ids", [])
    if existing_ids:
        chroma.delete(ids=existing_ids)

    bm25_path = _persist_directory() / f"bm25_{collection}.pkl"
    if bm25_path.exists():
        bm25_path.unlink()

    with sqlite3.connect(store._file_index_path) as connection:
        cursor = connection.execute(
            "DELETE FROM knowledge_files WHERE collection_name = ?",
            (collection,),
        )
        removed_records = cursor.rowcount

    store._bm25_indexes.pop(collection, None)
    return len(existing_ids), removed_records


def rebuild(collections: list[str]) -> None:
    store = VectorStore()
    for collection in collections:
        vectors, records = _clear_collection(store, collection)
        print(
            f"[{collection}] 已清理向量 {vectors} 条，文件索引 {records} 条；"
            "开始重建..."
        )
        store.load_document(collection)
        rebuilt = store._get_store(collection).get().get("ids", [])
        print(f"[{collection}] 重建完成，当前向量 {len(rebuilt)} 条")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按 collection 安全重建 RAG 索引")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--collection", choices=COLLECTIONS, help="只重建一个集合")
    group.add_argument("--all", action="store_true", help="重建全部集合")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    rebuild(list(COLLECTIONS) if args.all else [args.collection])
