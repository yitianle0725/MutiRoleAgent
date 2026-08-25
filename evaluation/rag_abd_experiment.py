"""Build and compare DashScope and local bge-m3 anime retrieval indexes.

The experiment intentionally uses a small, fixed corpus:

* ``data/anime/yuc/yuc_202601.json``
* ``data/anime/yuc/yuc_202604.json``
* ``data/anime/yuc/yuc_202607.json``
* every JSON file below ``data/anime/bangumi``

It creates isolated Chroma collections under ``chroma_db/experiments``. The
production RAG collections are never read, deleted, or modified.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Direct execution starts with ``evaluation/`` on sys.path. Add the project
# root so imports behave the same as ``python -m evaluation.rag_abd_experiment``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_chroma import Chroma
from langchain_core.documents import Document

from model.embedding_provider import DashScopeProvider, LocalONNXProvider
from rag.bm25 import ChineseBM25
from rag.hybrid_retriever import HybridRetriever
from utils.path_tool import get_project_path


EXPERIMENT_ROOT = get_project_path("chroma_db/experiments")
DATASET_PATH = get_project_path("evaluation/datasets/acgn_retrieval_100.json")
REPORT_DIRECTORY = get_project_path("evaluation/reports")
YUC_FILES = (
    get_project_path("data/anime/yuc/yuc_202601.json"),
    get_project_path("data/anime/yuc/yuc_202604.json"),
    get_project_path("data/anime/yuc/yuc_202607.json"),
)
BANGUMI_DIRECTORY = get_project_path("data/anime/bangumi")
DOMAIN_DIRECTORIES = {
    "acgn_daily": get_project_path("data/acgn_daily"),
    "game": get_project_path("data/game"),
    "novel": get_project_path("data/novel"),
}
EMBEDDING_BATCH_SIZE = 16


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _non_empty(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _build_yuc_documents(path: Path) -> list[Document]:
    payload = _read_json(path)
    season = _non_empty(payload.get("info", {}).get("季度"))
    documents: list[Document] = []
    for item in payload.get("animes", []):
        staff = item.get("staff", {})
        staff_text = "；".join(
            f"{key}: {_non_empty(value)}" for key, value in staff.items() if _non_empty(value)
        )
        title = _non_empty(item.get("title_cn"))
        content = "\n".join(
            part for part in (
                f"作品名: {title}",
                f"日文名: {_non_empty(item.get('title_jp'))}",
                f"季度: {season}",
                f"类型: {_non_empty(item.get('type'))}",
                f"标签: {_non_empty(item.get('tag'))}",
                f"播出: {_non_empty(item.get('broadcast'))}",
                f"制作信息: {staff_text}",
            ) if part.split(": ", 1)[-1]
        )
        if title:
            documents.append(Document(
                page_content=content,
                metadata={"source": str(path), "title": title, "dataset": "yuc"},
            ))
    return documents


def _build_bangumi_document(path: Path) -> Document | None:
    payload = _read_json(path)
    title = _non_empty(payload.get("title_cn")) or path.stem
    tags = [
        _non_empty(tag.get("name"))
        for tag in payload.get("tags", [])
        if isinstance(tag, dict) and _non_empty(tag.get("name"))
    ]
    stats = payload.get("stats", {})
    episode_rows = []
    for episode in payload.get("episodes", [])[:12]:
        if isinstance(episode, dict):
            episode_rows.append(
                "第{ep}话 {title}".format(
                    ep=_non_empty(episode.get("ep")),
                    title=_non_empty(episode.get("title_cn")) or _non_empty(episode.get("title_jp")),
                ).strip()
            )
    content = "\n".join(
        part for part in (
            f"作品名: {title}",
            f"日文名: {_non_empty(payload.get('title_jp'))}",
            f"评分: {_non_empty(stats.get('rating'))}",
            f"排名: {_non_empty(stats.get('rank'))}",
            f"评价: {_non_empty(stats.get('rating_desc'))}",
            f"标签: {'、'.join(tags)}",
            f"简介: {_non_empty(payload.get('summary_cn')) or _non_empty(payload.get('summary_jp'))}",
            f"剧集示例: {'；'.join(episode_rows)}",
        ) if part.split(": ", 1)[-1]
    )
    return Document(
        page_content=content,
        metadata={"source": str(path), "title": title, "dataset": "bangumi"},
    )


def _find_titles(payload: object) -> list[str]:
    """Extract likely title fields without flattening every nested JSON value."""
    titles: list[str] = []
    if isinstance(payload, dict):
        for key in ("title", "title_cn", "book_title", "name", "game", "category"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                titles.append(value.strip())
        for key in ("items", "books", "articles", "animes"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value[:80]:
                    titles.extend(_find_titles(item))
    elif isinstance(payload, list):
        for item in payload[:80]:
            titles.extend(_find_titles(item))
    return list(dict.fromkeys(titles))


def _build_generic_document(path: Path, domain: str) -> Document | None:
    """Build one compact searchable document per non-anime source file."""
    payload = _read_json(path)
    title_candidates = _find_titles(payload)
    title = title_candidates[0] if title_candidates else path.stem
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Keep enough context for retrieval while avoiding huge archives.
    content = f"领域: {domain}\n文件: {path.name}\n标题: {'、'.join(title_candidates[:80])}\n资料: {compact[:30000]}"
    return Document(
        page_content=content,
        metadata={"source": str(path), "title": title, "dataset": domain},
    )


def _build_acgn_documents(path: Path) -> list[Document]:
    """Split daily ACGN aggregates into one retrievable document per item."""
    payload = _read_json(path)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list) or not items:
        document = _build_generic_document(path, "acgn_daily")
        return [document] if document else []
    documents: list[Document] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = _non_empty(item.get("title")) or _non_empty(item.get("name")) or f"日报条目 {index + 1}"
        content = json.dumps(item, ensure_ascii=False, indent=2)
        documents.append(Document(
            page_content=f"领域: acgn_daily\n标题: {title}\n日期: {_non_empty(payload.get('date'))}\n{content}",
            metadata={"source": str(path), "title": title, "dataset": "acgn_daily"},
        ))
    return documents


def load_experiment_documents() -> list[Document]:
    """Load only the fixed anime sample used by the A/B/D experiment."""
    documents = [document for path in YUC_FILES for document in _build_yuc_documents(path)]
    for path in sorted(BANGUMI_DIRECTORY.glob("*.json")):
        document = _build_bangumi_document(path)
        if document is not None:
            documents.append(document)
    return documents


def load_domain_documents(domain: str) -> list[Document]:
    if domain == "anime":
        return load_experiment_documents()
    directory = DOMAIN_DIRECTORIES[domain]
    documents: list[Document] = []
    for path in sorted(directory.glob("*.json")):
        if domain == "acgn_daily":
            documents.extend(_build_acgn_documents(path))
        else:
            document = _build_generic_document(path, domain)
            if document is not None:
                documents.append(document)
    return documents


def _create_collection(name: str, provider, documents: list[Document], reuse_index: bool) -> Chroma:
    EXPERIMENT_ROOT.mkdir(parents=True, exist_ok=True)
    store = Chroma(
        collection_name=name,
        embedding_function=provider,
        persist_directory=str(EXPERIMENT_ROOT),
    )
    existing_ids = store.get(include=[]).get("ids", [])
    if existing_ids and reuse_index:
        print(f"[{name}] 复用已有索引，共 {len(existing_ids)} 条向量")
        return store
    if existing_ids:
        store.delete(ids=existing_ids)

    total = len(documents)
    for start in range(0, total, EMBEDDING_BATCH_SIZE):
        batch = documents[start:start + EMBEDDING_BATCH_SIZE]
        store.add_documents(batch)
        print(f"[{name}] 向量化 {min(start + len(batch), total)}/{total}")
    return store


def _load_cases(domain: str | None = None) -> list[dict]:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if domain is None:
        return cases
    return [case for case in cases if case.get("domain", "anime") == domain]


def _evaluate(name: str, store: Chroma, documents: list[Document], config: dict, domain: str) -> dict:
    bm25 = ChineseBM25()
    bm25.index(documents)
    retriever = HybridRetriever(name, store, bm25, config=config)
    details = []
    reciprocal_ranks: list[float] = []
    dcg_values: list[float] = []
    precisions: list[float] = []
    recalls: list[float] = []
    latencies: list[float] = []

    # Exclude one-time tokenizer/ONNX/Chroma initialization from query latency.
    retriever.retrieve("动漫作品信息", top_k=3)

    cases = _load_cases(domain)
    for case in cases:
        started = time.perf_counter()
        results = retriever.retrieve(case["query"], top_k=3)
        latency_ms = (time.perf_counter() - started) * 1000
        expected_title = case["expected_title"]
        ranks = [index for index, doc in enumerate(results, start=1) if expected_title in doc.page_content]
        rank = ranks[0] if ranks else None
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        dcg_values.append(1 / __import__("math").log2(rank + 1) if rank else 0.0)
        recalls.append(1.0 if rank else 0.0)
        precisions.append((1.0 / len(results)) if rank and results else 0.0)
        latencies.append(latency_ms)
        details.append({
            "id": case["id"],
            "query": case["query"],
            "expected_title": expected_title,
            "rank": rank,
            "latency_ms": round(latency_ms, 2),
            "retrieved_titles": [doc.metadata.get("title", "") for doc in results],
        })

    return {
        "strategy": name,
        "domain": domain,
        "config": config,
        "metrics": {
            "recall_at_3": round(statistics.mean(recalls), 4),
            "precision_at_3": round(statistics.mean(precisions), 4),
            "mrr": round(statistics.mean(reciprocal_ranks), 4),
            "ndcg_at_3": round(statistics.mean(dcg_values), 4),
            "mean_latency_ms": round(statistics.mean(latencies), 2),
            "p95_latency_ms": round(sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 2),
        },
        "details": details,
    }


def run(backend: str, reuse_index: bool, domains: list[str] | None = None) -> Path:
    selected_domains = domains or ["anime"]

    results: list[dict] = []
    corpus_counts: dict[str, int] = {}
    for domain in selected_domains:
        documents = load_domain_documents(domain)
        corpus_counts[domain] = len(documents)
        print(f"[{domain}] 实验语料: {len(documents)} 条记录")
        if not documents:
            continue
        if backend in {"all", "dashscope"}:
            provider = DashScopeProvider()
            store = _create_collection(f"{domain}_dashscope", provider, documents, reuse_index)
            results.append(_evaluate(
                f"A_{domain}_dashscope_bm25", store, documents,
                {"dense_weight": 0.7, "sparse_weight": 0.3, "reranker_enabled": False}, domain,
            ))
        if backend in {"all", "local"}:
            provider = LocalONNXProvider()
            store = _create_collection(f"{domain}_bge_m3", provider, documents, reuse_index)
            results.append(_evaluate(
                f"B_{domain}_bge_m3_onnx_bm25", store, documents,
                {"dense_weight": 0.7, "sparse_weight": 0.3, "reranker_enabled": False}, domain,
            ))
            results.append(_evaluate(
                f"D_{domain}_bge_m3_onnx_bm25_reranker", store, documents,
                {"dense_weight": 0.7, "sparse_weight": 0.3, "reranker_enabled": True,
                 "reranker_top_k": 10, "reranker_final_k": 3}, domain,
            ))

    generated_at = datetime.now(timezone.utc).astimezone().isoformat()
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIRECTORY / f"anime_abd_{datetime.now():%Y%m%d_%H%M%S}.json"
    report = {
        "generated_at": generated_at,
        "corpus": {
            "document_counts": corpus_counts,
            "sources": [str(path.relative_to(get_project_path())) for path in YUC_FILES]
            + ["data/anime/bangumi/*.json"],
        },
        "dataset": str(DATASET_PATH.relative_to(get_project_path())),
        "case_count": len(_load_cases()),
        "results": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已保存: {report_path}")
    for result in results:
        print(result["strategy"], result["metrics"])
    return report_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 Anime 小样本 A/B/D RAG 检索实验")
    parser.add_argument("--backend", choices=("all", "dashscope", "local"), default="all")
    parser.add_argument("--reuse-index", action="store_true", help="复用已有实验 collection")
    parser.add_argument("--domains", nargs="+", choices=("anime", "acgn_daily", "game", "novel"),
                        default=["anime"], help="参与实验的知识库领域")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = _parse_args()
    run(arguments.backend, arguments.reuse_index, arguments.domains)
