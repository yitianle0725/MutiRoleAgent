"""
RAG 总结服务（多 Collection 路由）
==================================
根据用户查询内容自动路由到 FAQ 或 Worldbook 向量库，
必要时同时检索两个库并合并结果。

路由规则
--------
- 产品问题（保养/故障/选购/维护）→ ``faq`` collection
- 角色/世界观问题（角色名/剧情/世界观）→ ``worldbook`` collection
- 模糊/综合问题 → 两个库都检索，faq 结果优先

使用方式::

    from rag.rag_service import RagSummarizeService

    rag = RagSummarizeService()
    result = rag.rag_summarize("昔涟是谁？")
    # → 自动路由到 worldbook collection
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from model.factory import chat_model
from rag.vector_store import (
    COLLECTION_ACGN_DAILY,
    COLLECTION_ANIME,
    COLLECTION_GAME,
    COLLECTION_NOVEL,
    vector_store,
)
from utils.config_handler import keywords_config
from utils.logger_handler import logger
from utils.prompt_loader import load_rag_prompts
from rag.retrieval_trace import retrieval_trace_store
from rag.context_builder import build_context
from utils.config_handler import chroma_config


# ==================== 路由关键词（从 keywords.yaml 读取） ====================

_RK = keywords_config.get("rag_routing", {})
_ACGN_DAILY_KEYWORDS: list[str] = _RK.get("acgn_daily", ["最新", "资讯", "新闻", "更新"])
_ANIME_KEYWORDS: list[str] = _RK.get("anime", [])
_GAME_KEYWORDS: list[str] = _RK.get("game", ["原神", "崩坏", "星穹铁道", "绝区零", "米游社", "游戏攻略"])
_NOVEL_KEYWORDS: list[str] = _RK.get("novel", ["小说", "起点", "作者", "章节", "榜单"])
_CONTEXT_MAX_CHARS = int(chroma_config.get("retrieval", {}).get("context_max_chars", 8000))

_COLLECTION_LABELS = {
    COLLECTION_ACGN_DAILY: "每日 ACGN 资讯库",
    COLLECTION_ANIME: "动漫资料库",
    COLLECTION_GAME: "游戏资料库",
    COLLECTION_NOVEL: "小说资料库",
}

def _route_query(query: str) -> list[str]:
    """根据查询内容返回应检索的 collection 列表。

    Returns:
        ``["faq"]`` / ``["worldbook"]`` / ``["anime"]`` / 组合
    """
    # 具体领域优先于泛化的 ACGN 资讯关键词。
    if any(kw in query for kw in _ANIME_KEYWORDS):
        return [COLLECTION_ANIME]
    if any(kw in query for kw in _GAME_KEYWORDS):
        return [COLLECTION_GAME]
    if any(kw in query for kw in _NOVEL_KEYWORDS):
        return [COLLECTION_NOVEL]
    if any(kw in query for kw in _ACGN_DAILY_KEYWORDS):
        return [COLLECTION_ACGN_DAILY]

    logger.debug("[RAG route] 默认 → 全部")
    return [COLLECTION_ACGN_DAILY, COLLECTION_ANIME, COLLECTION_GAME, COLLECTION_NOVEL]


# ==================== RAG 服务 ====================

class RagSummarizeService:
    """多 Collection RAG 总结服务。

    自动路由到 faq / worldbook，必要时合并两库结果。
    """

    def __init__(self):
        self.prompt_text = load_rag_prompts()
        self.prompt_text += (
            "\n\n补充要求：只使用参考资料中的证据；关键结论在句末标注对应的[参考资料N]。"
            "如果资料之间存在冲突，明确说明冲突及来源，不要自行选择未被证据支持的结论。"
        )
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = chat_model
        self.chain = self.prompt_template | self.model | StrOutputParser()

    # ---- 检索 ----

    def retrieve_docs(self, query: str, collection_name: str = COLLECTION_ANIME):
        """从指定 collection 检索相关文档。"""
        retriever = vector_store.get_retriever(collection_name)
        return retriever.invoke(query)

    def retrieve_all(self, query: str) -> dict[str, list]:
        """从所有 collection 检索，返回各库结果。"""
        results = {}
        for name, retriever in vector_store.get_all_retrievers().items():
            results[name] = retriever.invoke(query)
        return results

    # ---- 总结 ----

    def rag_summarize(self, query: str) -> str:
        """智能路由 RAG 总结。

        1. 根据 query 关键词路由到 faq / worldbook
        2. 检索 top-k 文档
        3. 格式化为参考上下文
        4. 调用 LLM 总结
        """
        collections = _route_query(query)
        context = ""
        retrieved_documents: list[tuple[str, object]] = []
        counter = 0
        retrieval_trace: dict[str, object] = {"collections": {}}

        for coll_name in collections:
            try:
                retriever = vector_store.get_retriever(coll_name)
                docs = retriever.invoke(query)
                retrieved_documents.extend((coll_name, doc) for doc in docs)
                retrieval_trace["collections"][coll_name] = retriever.last_trace
            except Exception as e:
                logger.warning(f"[RAG] {coll_name} 检索失败: {e}")
                retrieval_trace["collections"][coll_name] = {"error": str(e)}
                continue

            source_label = _COLLECTION_LABELS[coll_name]
            for doc in docs:
                counter += 1
                context += (
                    f"【参考资料{counter}】(来源: {source_label})"
                    f"内容：{doc.page_content}"
                    f"|元数据：{doc.metadata}\n"
                )

        context_result = build_context(retrieved_documents, max_chars=_CONTEXT_MAX_CHARS)
        context = context_result.text
        counter = len(context_result.evidence)
        retrieval_trace["context"] = {
            "evidence": context_result.evidence,
            "duplicate_count": context_result.duplicate_count,
            "truncated": context_result.truncated,
            "max_chars": _CONTEXT_MAX_CHARS,
        }

        try:
            retrieval_trace["returned_document_count"] = counter
            retrieval_trace_store.save(query, collections, retrieval_trace)
        except Exception as error:
            logger.warning(f"[RAG] 保存检索追踪失败: {error}")

        if counter == 0:
            return "未在知识库中找到相关资料。"

        logger.info(
            f"[RAG] 检索完成: query='{query[:40]}', "
            f"collections={collections}, docs={counter}"
        )

        return self.chain.invoke({"input": query, "context": context})
