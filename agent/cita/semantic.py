"""
CITA 2.0 语义引擎
=================
从用户消息中提取结构化语义信息：实体、情绪、意图、上下文关联度。

与 V1.0 (cita_classifier.py) 的改进：
- 实体提取：番名/角色/地点/时间 四类实体
- 情绪检测：强度打分（0-1）+ 否定翻转 + 多情绪共存
- 意图分类：多标签（chitchat+task 可同时存在）+ 优先级权重
- 上下文关联：计算历史消息与当前查询的相关性

使用方式::

    from agent.cita.semantic import SemanticEngine

    engine = SemanticEngine()
    analysis = engine.analyze("推荐几部像《鬼灭之刃》一样的热血番")
    # analysis.entities → [Entity(type="anime", value="鬼灭之刃"), ...]
    # analysis.intents → [IntentLabel(type="task", confidence=0.9), ...]
    # analysis.emotions → []
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from utils.config_handler import keywords_config
from utils.logger_handler import logger

# 加载 CITA 2.0 配置
def _load_cita_cfg():
    try:
        from utils.config_handler import get_abs_path
        import yaml
        path = get_abs_path("config/cita.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    except Exception:
        return {}

_CITA_CFG = _load_cita_cfg()
_ENTITY_CFG = _CITA_CFG.get("entities", {})
_EMOTION_CFG = _CITA_CFG.get("emotions", {})
_INTENT_CFG = _CITA_CFG.get("intent", {})

# V1 关键词（兼容）
_KW = keywords_config
_EMOTION_KEYWORDS: dict[str, list[tuple[str, float]]] = {}
_raw_emotions = _KW.get("cita_emotions", {})
if _raw_emotions:
    for emotion, items in _raw_emotions.items():
        _EMOTION_KEYWORDS[emotion] = [(kw, float(wt)) for kw, wt in items]

_INTENT_PATTERNS: dict[str, list[str]] = _KW.get("cita_intent", {})
_EMOTION_SOOTHE_PHRASES: dict[str, str] = _KW.get("cita_soothe", {})


# ==================== 数据结构 ====================

@dataclass
class Entity:
    """提取的命名实体。

    Attributes:
        type: 实体类型 — ``"anime"`` / ``"character"`` / ``"location"`` / ``"time"``。
        value: 实体文本。
        confidence: 置信度 0.0 ~ 1.0。
        position: 在原文本中的位置（start, end），-1 表示未知。
    """
    type: str
    value: str
    confidence: float = 1.0
    position: tuple[int, int] = (-1, -1)

    def __hash__(self):
        return hash((self.type, self.value))


@dataclass
class EmotionSignal:
    """情绪检测结果。

    Attributes:
        emotion: 情绪类型 — ``"angry"`` / ``"urgent"`` / ``"confused"`` / ``"polite"`` / ``"sad"`` / ``"happy"``。
        intensity: 强度 0.0 ~ 1.0。
        confidence: 置信度 0.0 ~ 1.0。
        negated: 是否被否定（如 "不着急" 中的 urgent 被否定）。
    """
    emotion: str
    intensity: float = 0.5
    confidence: float = 0.5
    negated: bool = False

    @property
    def effective_intensity(self) -> float:
        """否定后的有效强度（被否定时归零）。"""
        return 0.0 if self.negated else self.intensity

    def __eq__(self, other) -> bool:
        """支持与字符串比较：``'angry' in emotions`` 在 V1 兼容模式下可用。"""
        if isinstance(other, str):
            return self.emotion == other
        if isinstance(other, EmotionSignal):
            return self.emotion == other.emotion
        return NotImplemented

    def __hash__(self):
        return hash(self.emotion)

    def __repr__(self) -> str:
        return (
            f"EmotionSignal(emotion='{self.emotion}', "
            f"intensity={self.intensity}, confidence={self.confidence}, "
            f"negated={self.negated})"
        )


@dataclass
class IntentLabel:
    """意图标签（支持多标签分类）。

    Attributes:
        intent_type: 意图类型 — ``"chitchat"`` / ``"task"`` / ``"report"`` / ``"emergency"``。
        confidence: 置信度 0.0 ~ 1.0。
        priority: 优先级权重（用于排序和路由决策）。
    """
    intent_type: str
    confidence: float = 0.5
    priority: float = 0.5

    def __post_init__(self):
        if self.priority == 0.5:  # 未显式设置
            weights = _INTENT_CFG.get("weights", {})
            self.priority = weights.get(self.intent_type, 0.5)


@dataclass
class SemanticAnalysis:
    """完整的语义分析结果。

    Attributes:
        text: 原始输入文本。
        entities: 提取的实体列表。
        emotions: 检测到的情绪列表（按强度降序）。
        intents: 意图标签列表（按优先级降序）。
        primary_intent: 最高优先级意图（向后兼容 V1 的 intent_type）。
        needs_rag: 是否需要 RAG 检索。
        needs_web_search: 是否需要联网搜索。
        relevance_score: 整体相关性评分 0.0 ~ 1.0。
        summary: 分析摘要（用于日志/调试）。
    """
    text: str
    entities: list[Entity] = field(default_factory=list)
    emotions: list[EmotionSignal] = field(default_factory=list)
    intents: list[IntentLabel] = field(default_factory=list)
    primary_intent: str = "task"
    needs_rag: bool = False
    needs_web_search: bool = False
    relevance_score: float = 1.0
    summary: str = ""

    # V1 兼容属性
    @property
    def intent_type(self) -> str:
        return self.primary_intent

    @property
    def confidence(self) -> float:
        if self.intents:
            return self.intents[0].confidence
        return 0.5


# ==================== 实体提取器 ====================

class EntityExtractor:
    """从文本中提取命名实体。

    支持四类实体：
    - anime: 番名（《...》格式、已知关键词后缀）
    - character: 角色名（从 persona 配置加载）
    - location: 地名（城市名、省份名）
    - time: 时间表达式
    """

    # 番名模式
    _ANIME_BRACKET = re.compile(r'《([^》]{1,30})》')
    _ANIME_QUOTE = re.compile(r'「([^」]{1,30})」')

    # 地点模式
    _LOCATION_PATTERNS: list[re.Pattern] = []
    for _pat in _ENTITY_CFG.get("location_indicators", []):
        try:
            _LOCATION_PATTERNS.append(re.compile(_pat))
        except re.error:
            pass

    # 城市白名单
    _CITIES: set[str] = {
        "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉",
        "南京", "天津", "重庆", "苏州", "西安", "长沙", "郑州",
        "东莞", "青岛", "沈阳", "宁波", "昆明", "大连", "厦门",
        "合肥", "福州", "无锡", "佛山", "济南", "哈尔滨", "长春",
        "温州", "石家庄", "泉州", "南宁", "贵阳", "南昌", "太原",
        "烟台", "嘉兴", "南通", "金华", "珠海", "惠州", "常州",
        "徐州", "绍兴", "中山", "兰州", "海口", "乌鲁木齐", "呼和浩特",
        "银川", "西宁", "拉萨", "桂林", "三亚", "香港", "澳门", "台北",
    }

    # 时间表达式
    _TIME_WORDS = set(_ENTITY_CFG.get("time_patterns", [
        "今天", "明天", "昨天", "本周", "这周", "本月", "今年",
        "最近", "当前", "现在", "刚才", "刚刚",
    ]))

    def __init__(self):
        # 角色名（从配置加载 + 内置）
        self._character_names: set[str] = set(
            _ENTITY_CFG.get("character_names", [])
        )
        # 番名后缀
        self._title_suffixes: list[str] = _ENTITY_CFG.get("anime_title", {}).get(
            "title_suffixes", []
        )

    def extract(self, text: str) -> list[Entity]:
        """从文本中提取所有实体。"""
        entities: list[Entity] = []

        entities.extend(self._extract_anime(text))
        entities.extend(self._extract_characters(text))
        entities.extend(self._extract_locations(text))
        entities.extend(self._extract_time(text))

        return entities

    def _extract_anime(self, text: str) -> list[Entity]:
        """提取番名实体。"""
        entities: list[Entity] = []

        # 书名号模式
        for match in self._ANIME_BRACKET.finditer(text):
            entities.append(Entity(
                type="anime",
                value=match.group(1),
                confidence=0.95,
                position=(match.start(), match.end()),
            ))

        # 引号模式
        for match in self._ANIME_QUOTE.finditer(text):
            value = match.group(1)
            # 避免重复（如果已被书名号匹配）
            if not any(e.value == value and e.type == "anime" for e in entities):
                entities.append(Entity(
                    type="anime",
                    value=value,
                    confidence=0.7,
                    position=(match.start(), match.end()),
                ))

        return entities

    def _extract_characters(self, text: str) -> list[Entity]:
        """提取角色名实体。"""
        entities: list[Entity] = []
        for name in self._character_names:
            if name in text:
                idx = text.find(name)
                entities.append(Entity(
                    type="character",
                    value=name,
                    confidence=0.9,
                    position=(idx, idx + len(name)),
                ))
        return entities

    def _extract_locations(self, text: str) -> list[Entity]:
        """提取地点实体。"""
        entities: list[Entity] = []

        # 城市白名单匹配
        for city in self._CITIES:
            if city in text:
                idx = text.find(city)
                entities.append(Entity(
                    type="location",
                    value=city,
                    confidence=0.85,
                    position=(idx, idx + len(city)),
                ))

        # 正则模式匹配
        for pattern in self._LOCATION_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if not any(e.value == value for e in entities):
                    entities.append(Entity(
                        type="location",
                        value=value,
                        confidence=0.6,
                        position=(match.start(), match.end()),
                    ))

        # "本地" / "这里"
        for loc_word in ["本地", "这里", "那里"]:
            if loc_word in text:
                idx = text.find(loc_word)
                if not any(e.value == loc_word for e in entities):
                    entities.append(Entity(
                        type="location",
                        value=loc_word,
                        confidence=0.5,
                        position=(idx, idx + len(loc_word)),
                    ))

        return entities

    def _extract_time(self, text: str) -> list[Entity]:
        """提取时间表达式。"""
        entities: list[Entity] = []
        for tw in self._TIME_WORDS:
            if tw in text:
                idx = text.find(tw)
                entities.append(Entity(
                    type="time",
                    value=tw,
                    confidence=0.9,
                    position=(idx, idx + len(tw)),
                ))
        return entities


# ==================== 情绪检测器 ====================

class EmotionDetector:
    """增强情绪检测：强度打分 + 否定翻转 + 多情绪共存。"""

    # 否定词
    _NEGATION_WORDS = set(_EMOTION_CFG.get("negation_words", [
        "不", "没", "没有", "别", "不要", "并非", "未必",
    ]))

    # 否定窗口（否定词前/后 N 个字符内查找情绪词）
    _NEGATION_WINDOW = 5

    # 强度级别
    _INTENSITY_LOW = _EMOTION_CFG.get("intensity", {}).get("low", 0.3)
    _INTENSITY_MEDIUM = _EMOTION_CFG.get("intensity", {}).get("medium", 0.6)
    _INTENSITY_HIGH = _EMOTION_CFG.get("intensity", {}).get("high", 0.8)

    def detect(self, text: str) -> list[EmotionSignal]:
        """检测文本中的所有情绪信号。

        Args:
            text: 用户输入文本。

        Returns:
            按有效强度降序排列的情绪列表。
        """
        signals: list[EmotionSignal] = []

        for emotion, keywords in _EMOTION_KEYWORDS.items():
            signal = self._detect_single(text, emotion, keywords)
            if signal and signal.effective_intensity > 0:
                signals.append(signal)

        # 按有效强度降序
        signals.sort(key=lambda s: s.effective_intensity, reverse=True)
        return signals

    def _detect_single(
        self, text: str, emotion: str, keywords: list[tuple[str, float]]
    ) -> EmotionSignal | None:
        """检测单个情绪。"""
        best_kw = ""
        best_weight = 0.0
        best_pos = -1

        for kw, weight in keywords:
            pos = text.find(kw)
            if pos >= 0 and weight > best_weight:
                best_kw = kw
                best_weight = weight
                best_pos = pos

        if not best_kw:
            return None

        # 否定检查
        negated = self._check_negation(text, best_kw, best_pos)

        # 强度计算（否定翻转后清零）
        if negated:
            return EmotionSignal(
                emotion=emotion,
                intensity=0.0,
                confidence=best_weight,
                negated=True,
            )

        # 强度分级
        if best_weight >= 0.8:
            intensity = self._INTENSITY_HIGH
        elif best_weight >= 0.5:
            intensity = self._INTENSITY_MEDIUM
        else:
            intensity = self._INTENSITY_LOW

        return EmotionSignal(
            emotion=emotion,
            intensity=intensity,
            confidence=best_weight,
            negated=False,
        )

    def _check_negation(self, text: str, keyword: str, kw_pos: int) -> bool:
        """检查关键词是否被否定词修饰。"""
        # 检查关键词前面的窗口
        pre_start = max(0, kw_pos - self._NEGATION_WINDOW)
        pre_context = text[pre_start:kw_pos]

        for neg_word in self._NEGATION_WORDS:
            if neg_word in pre_context:
                # 确保否定词直接修饰（中间不隔着句号/逗号）
                last_punct = max(
                    pre_context.rfind("。"),
                    pre_context.rfind("，"),
                    pre_context.rfind("！"),
                    pre_context.rfind("？"),
                    pre_context.rfind("、"),
                )
                neg_pos = pre_context.rfind(neg_word)
                if neg_pos > last_punct:
                    return True

        return False


# ==================== 意图分类器 ====================

class IntentClassifier:
    """多标签意图分类器。

    与 V1 的关键区别：
    - 支持多标签：一条消息可同时标记为 chitchat + task
    - 上下文感知：参考最近消息判断意图连续性
    - 实体加权：检测到实体时提升 task/report 置信度
    """

    # 意图关键词（从 keywords.yaml 加载）
    _CHITCHAT_KW: list[str] = []
    _REPORT_KW: list[str] = []
    _RAG_NEED_KW: list[str] = []
    _WEB_SEARCH_KW: list[str] = []

    def __init__(self):
        intent_cfg = _KW.get("cita_intent", {})
        self._CHITCHAT_KW = intent_cfg.get("chitchat", [])
        self._REPORT_KW = intent_cfg.get("report", [])
        self._RAG_NEED_KW = intent_cfg.get("rag_need", [])
        self._WEB_SEARCH_KW = intent_cfg.get("web_search", [])

    def classify(
        self,
        text: str,
        entities: list[Entity] | None = None,
        emotions: list[EmotionSignal] | None = None,
        context: list[str] | None = None,
    ) -> tuple[list[IntentLabel], bool, bool]:
        """对文本进行多标签意图分类。

        Args:
            text: 用户输入文本。
            entities: 已提取的实体（用于加权）。
            emotions: 已检测的情绪（用于加权）。
            context: 最近 N 条历史消息文本（用于上下文感知）。

        Returns:
            (intent_labels, needs_rag, needs_web_search)
        """
        entities = entities or []
        emotions = emotions or []
        labels: list[IntentLabel] = []

        # 检测消息结构特征
        has_question = "?" in text or "？" in text
        has_request = any(
            kw in text for kw in [
                "推荐", "查", "找", "搜索", "帮我", "我要", "想要",
                "怎么", "如何", "什么", "哪个", "哪部", "有没有",
                "能不能", "可以", "请", "麻烦", "想看", "看点",
                "求", "下载", "导出", "生成", "播放",
            ]
        )
        has_statement_only = not has_question and not has_request

        # 1) Chitchat 检测
        chitchat_conf = self._detect_chitchat(text)
        if chitchat_conf > 0:
            labels.append(IntentLabel(
                intent_type="chitchat",
                confidence=chitchat_conf,
            ))

        # 2) Report 检测
        report_conf = self._detect_report(text)
        if report_conf > 0:
            labels.append(IntentLabel(
                intent_type="report",
                confidence=report_conf,
            ))

        # 3) Task 检测
        task_conf = self._detect_task(text, entities, emotions, context)
        if task_conf > 0:
            labels.append(IntentLabel(
                intent_type="task",
                confidence=task_conf,
            ))

        # 4) Emergency 检测
        emergency_conf = self._detect_emergency(text, emotions)
        if emergency_conf > 0:
            labels.append(IntentLabel(
                intent_type="emergency",
                confidence=emergency_conf,
            ))

        # 如果没有检测到任何意图，默认弱 chitchat
        if not labels:
            labels.append(IntentLabel(
                intent_type="chitchat",
                confidence=0.3,
            ))

        # 排序：考虑消息结构
        # - 有明确请求 → task/report/emergency 优先
        # - 纯陈述 + 强 chitchat 信号 → chitchat 优先
        # - 否则按 priority × confidence 排序
        if has_request:
            # 有请求词 → task 类优先，但 emergency 永远最高
            labels.sort(key=lambda l: (
                0 if l.intent_type == "emergency" else
                1 if l.intent_type in ("task", "report") else
                2,
                -l.confidence
            ))
        elif has_statement_only and chitchat_conf > 0.5:
            # 纯陈述 + 强社交信号 → chitchat 优先
            labels.sort(key=lambda l: (
                0 if l.intent_type == "chitchat" else 1,
                -l.confidence
            ))
        else:
            # 默认：综合排序
            labels.sort(key=lambda l: (l.priority * l.confidence, l.confidence), reverse=True)

        # RAG / Web Search 预判
        needs_rag = self._detect_rag_need(text, entities)
        needs_web_search = self._detect_web_search_need(text, entities)

        return labels, needs_rag, needs_web_search

        # RAG / Web Search 预判
        needs_rag = self._detect_rag_need(text, entities)
        needs_web_search = self._detect_web_search_need(text, entities)

        return labels, needs_rag, needs_web_search

    def _detect_chitchat(self, text: str) -> float:
        """检测闲聊意图，返回置信度。"""
        match_count = 0
        total_weight = 0.0

        for kw in self._CHITCHAT_KW:
            if kw in text:
                match_count += 1
                # 短关键词（你好/嗨）高权重
                if len(kw) <= 2:
                    total_weight += 0.9
                else:
                    total_weight += 0.7

        if match_count == 0:
            return 0.0

        # 纯社交信号（无实质内容）
        text_stripped = text.strip()
        if text_stripped in self._CHITCHAT_KW:
            return 0.95

        return min(0.9, total_weight / max(match_count, 1))

    def _detect_report(self, text: str) -> float:
        """检测报告意图。"""
        for kw in self._REPORT_KW:
            if kw in text:
                return 0.9
        return 0.0

    def _detect_task(
        self,
        text: str,
        entities: list[Entity],
        emotions: list[EmotionSignal],
        context: list[str] | None,
    ) -> float:
        """检测任务意图。实体和上下文提供加权。

        注意：基础置信度从 0 开始——只有检测到信号才提升。
        避免纯闲聊被误判为 task。
        """
        conf = 0.0
        signal_count = 0

        # 有明确请求/指令词 → 任务信号
        # 注意：先排除自介类问题（"你是谁"/"你能做什么"等属于 chitchat）
        self_intro_patterns = [
            "你是谁", "你叫什么", "你能做什么", "你是什么",
            "介绍一下.*你", "你.*介绍.*自己",
        ]
        is_self_intro = any(re.search(p, text) for p in self_intro_patterns)

        if not is_self_intro:
            request_keywords = [
                "推荐", "查", "找", "搜索", "帮我", "我要", "想要",
                "怎么", "如何", "哪个", "哪部", "有没有", "能不能",
                "可以.*吗", "下载", "导出", "生成", "播放", "告诉",
                "介绍", "解释", "说明", "教", "求", "想看", "看点",
                "找.*番", "找.*动漫", "求.*番", "来.*部",
            ]
            for kw in request_keywords:
                if re.search(kw, text):
                    conf += 0.25
                    signal_count += 1
                    break  # 只计一次

        # 有实体 → 更可能是任务
        if entities:
            conf += 0.3 * min(len(entities), 3)
            signal_count += 1

        # 有 RAG/搜索关键词 → 更可能是任务
        rag_hits = sum(1 for kw in self._RAG_NEED_KW if kw in text)
        if rag_hits > 0:
            conf += 0.15 * min(rag_hits, 3)
            signal_count += 1

        web_hits = sum(1 for kw in self._WEB_SEARCH_KW if kw in text)
        if web_hits > 0:
            conf += 0.15 * min(web_hits, 3)
            signal_count += 1

        # 问号 → 可能是任务（但自介类问题除外）
        if not is_self_intro and ("?" in text or "？" in text):
            conf += 0.1
            signal_count += 1

        # 上下文关联（前一条是任务 → 当前可能继续）
        if context:
            last = context[-1] if context else ""
            if last and any(kw in last for kw in self._RAG_NEED_KW):
                conf += 0.05
                signal_count += 1

        # 无任何任务信号 → 返回 0（不作为 task）
        if signal_count == 0:
            return 0.0

        return min(0.95, conf + 0.2)

    def _detect_emergency(
        self, text: str, emotions: list[EmotionSignal]
    ) -> float:
        """检测紧急意图。"""
        conf = 0.0

        # urgent 情绪 + 高置信度 → emergency
        for emo in emotions:
            if emo.emotion == "urgent" and emo.effective_intensity >= 0.7:
                conf = max(conf, emo.effective_intensity)

        # 紧急关键词
        emergency_kw = ["救命", "紧急", "马上", "立刻", "在线等", "着急"]
        for kw in emergency_kw:
            if kw in text:
                conf = max(conf, 0.85)

        return conf

    def _detect_rag_need(self, text: str, entities: list[Entity]) -> bool:
        """判断是否需要 RAG 检索。"""
        # 关键词匹配
        for kw in self._RAG_NEED_KW:
            if kw in text:
                return True
        # 有 anime 实体 → 可能需要
        if any(e.type == "anime" for e in entities):
            return True
        return False

    def _detect_web_search_need(self, text: str, entities: list[Entity]) -> bool:
        """判断是否需要联网搜索。"""
        for kw in self._WEB_SEARCH_KW:
            if kw in text:
                return True
        # 有时间实体 → 可能需要实时信息
        if any(e.type == "time" for e in entities):
            return True
        # 有地点实体 → 可能需要天气
        if any(e.type == "location" for e in entities):
            return True
        return False


# ==================== 上下文关联度计算 ====================

class RelevanceScorer:
    """计算历史消息与当前查询的相关性评分。

    用于 Reducer 决定保留/裁剪哪些历史消息。
    """

    def score(
        self,
        query: str,
        history_message: str,
        query_entities: list[Entity] | None = None,
    ) -> float:
        """计算单条历史消息与查询的相关性。

        Returns:
            0.0 ~ 1.0，越高越相关。
        """
        if not history_message or not query:
            return 0.0

        score = 0.0
        query_entities = query_entities or []

        # 1) 实体重叠（最高权重）
        if query_entities:
            overlap_count = sum(
                1 for e in query_entities
                if e.value in history_message
            )
            if overlap_count > 0:
                score += 0.4 * min(overlap_count / len(query_entities), 1.0)

        # 2) 关键词重叠
        query_words = set(query)
        history_words = set(history_message)
        if query_words and history_words:
            jaccard = len(query_words & history_words) / len(query_words | history_words)
            score += 0.3 * jaccard

        # 3) 相同问句结构
        if "?" in query and "?" in history_message:
            score += 0.1
        if "？" in query and "？" in history_message:
            score += 0.1

        # 4) 长度相似度（相近长度的消息更可能属于同一话题）
        len_ratio = min(len(query), len(history_message)) / max(
            len(query), len(history_message), 1
        )
        score += 0.1 * len_ratio

        return min(1.0, score)

    def score_messages(
        self,
        query: str,
        history_texts: list[str],
        query_entities: list[Entity] | None = None,
    ) -> list[tuple[int, float]]:
        """批量计算历史消息与查询的相关性。

        Returns:
            [(消息索引, 相关性分数), ...]，按分数降序排列。
        """
        scores = []
        for i, text in enumerate(history_texts):
            s = self.score(query, text, query_entities)
            scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores


# ==================== 语义引擎主类 ====================

class SemanticEngine:
    """CITA 2.0 语义引擎。

    整合实体提取、情绪检测、意图分类、上下文关联度计算。

    使用示例::

        engine = SemanticEngine()
        analysis = engine.analyze("今天杭州天气怎么样？")
        print(analysis.entities)   # [Entity(type="location", value="杭州"), Entity(type="time", value="今天")]
        print(analysis.primary_intent)  # "task"
        print(analysis.needs_web_search)  # True
    """

    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.emotion_detector = EmotionDetector()
        self.intent_classifier = IntentClassifier()
        self.relevance_scorer = RelevanceScorer()

    def analyze(
        self,
        text: str,
        context: list[str] | None = None,
        history_texts: list[str] | None = None,
    ) -> SemanticAnalysis:
        """对用户消息进行完整语义分析。

        Args:
            text: 用户输入文本。
            context: 最近 N 条历史消息文本（用于意图上下文感知）。
            history_texts: 全部历史消息文本（用于相关性计算）。

        Returns:
            ``SemanticAnalysis`` 包含所有分析结果。
        """
        if not text or not text.strip():
            return SemanticAnalysis(
                text=text or "",
                primary_intent="chitchat",
                summary="空输入",
            )

        # 1) 实体提取
        entities = self.entity_extractor.extract(text)

        # 2) 情绪检测
        emotions = self.emotion_detector.detect(text)

        # 3) 意图分类
        intents, needs_rag, needs_web_search = self.intent_classifier.classify(
            text, entities, emotions, context
        )

        # 4) 主要意图
        primary = intents[0].intent_type if intents else "task"

        # 5) 相关性评分（默认 1.0，有历史时计算）
        relevance = 1.0
        if history_texts and len(history_texts) > 0:
            # 取与最近一条历史消息的相关性
            relevance = self.relevance_scorer.score(
                text, history_texts[-1], entities
            )

        # 6) 生成摘要
        summary_parts = []
        if entities:
            entity_summary = ", ".join(
                f"[{e.type}]{e.value}" for e in entities
            )
            summary_parts.append(f"实体: {entity_summary}")
        if emotions:
            emotion_summary = ", ".join(
                f"{s.emotion}({s.effective_intensity:.1f})"
                for s in emotions[:3]
            )
            summary_parts.append(f"情绪: {emotion_summary}")
        if intents:
            intent_summary = ", ".join(
                f"{i.intent_type}({i.confidence:.0%})" for i in intents[:3]
            )
            summary_parts.append(f"意图: {intent_summary}")

        return SemanticAnalysis(
            text=text,
            entities=entities,
            emotions=emotions,
            intents=intents,
            primary_intent=primary,
            needs_rag=needs_rag,
            needs_web_search=needs_web_search,
            relevance_score=relevance,
            summary="; ".join(summary_parts) if summary_parts else "无特殊信号",
        )

    # ==================== V1 兼容方法 ====================

    def classify_intent(self, text: str) -> SemanticAnalysis:
        """V1 兼容：等同于 analyze()，返回 SemanticAnalysis（兼容 IntentResult 访问）。"""
        return self.analyze(text)

    def build_overlay(self, analysis: SemanticAnalysis) -> str:
        """根据语义分析结果生成 CITA 提示词叠加层（V2 增强版）。

        相比 V1 的 build_cita_overlay()，增加了：
        - 实体感知提示
        - 多情绪叠加安抚
        - 多意图协调指令
        """
        parts: list[str] = []

        # 1) 情绪安抚指令（多情绪叠加）
        for emotion_signal in analysis.emotions:
            if emotion_signal.effective_intensity < 0.3:
                continue
            phrase = _EMOTION_SOOTHE_PHRASES.get(emotion_signal.emotion)
            if phrase:
                intensity_label = (
                    "强烈" if emotion_signal.effective_intensity >= 0.7
                    else "中等" if emotion_signal.effective_intensity >= 0.5
                    else "轻微"
                )
                parts.append(f"[情绪: {emotion_signal.emotion}({intensity_label})] {phrase}")

        # 2) 实体感知提示
        if analysis.entities:
            entity_parts = []
            for e in analysis.entities:
                if e.type == "anime":
                    entity_parts.append(f"番名「{e.value}」")
                elif e.type == "character":
                    entity_parts.append(f"角色「{e.value}」")
                elif e.type == "location":
                    entity_parts.append(f"地点「{e.value}」")
                elif e.type == "time":
                    entity_parts.append(f"时间「{e.value}」")
            if entity_parts:
                parts.append(
                    f"用户提及了以下实体：{'、'.join(entity_parts)}。"
                    f"如涉及工具调用，请优先使用这些实体作为参数。"
                )

        # 3) 意图路由提示（多标签协调）
        intent_types = [i.intent_type for i in analysis.intents[:2]]
        if "chitchat" in intent_types and "task" in intent_types:
            parts.append(
                "用户同时表达了社交和任务意图。"
                "请先简短回应社交部分，再处理任务部分。"
            )
        elif "emergency" in intent_types:
            parts.append(
                "用户情况紧急！请跳过寒暄，直接给出最有效的解决方案。"
                "优先处理最关键的问题。"
            )
        elif "report" in intent_types:
            parts.append(
                "用户意图为生成使用报告，请按报告生成流程执行："
                "get_user_id → get_current_month → fill_cotext_for_report → fetch_external_data。"
            )
        elif "chitchat" in intent_types and len(intent_types) == 1:
            parts.append(
                "用户正在进行社交闲聊，请友好简短回应，"
                "不需要调用工具或展开复杂分析。"
            )

        # 4) 检索建议
        if analysis.needs_rag and "chitchat" not in intent_types:
            parts.append(
                "用户问题涉及专业知识，"
                "建议调用 rag_summarize 工具检索知识库以获取准确信息。"
            )

        if not parts:
            return ""

        return "\n".join(parts)


# ==================== 模块级实例 ====================

semantic_engine = SemanticEngine()


# ==================== V1 兼容函数 ====================

def classify_intent(text: str):
    """V1 兼容：返回 SemanticAnalysis（可像 IntentResult 一样访问 .intent_type, .emotions 等）。"""
    return semantic_engine.analyze(text)


def build_cita_overlay(analysis) -> str:
    """V1 兼容：生成 CITA 提示词叠加层。

    接受 SemanticAnalysis（V2）或 IntentResult（V1）。
    """
    if isinstance(analysis, SemanticAnalysis):
        return semantic_engine.build_overlay(analysis)
    # V1 IntentResult 兼容
    parts: list[str] = []
    emotions = getattr(analysis, "emotions", [])
    for emotion in (emotions if isinstance(emotions, list) else []):
        if isinstance(emotion, str):
            phrase = _EMOTION_SOOTHE_PHRASES.get(emotion)
            if phrase:
                parts.append(phrase)
        elif isinstance(emotion, EmotionSignal):
            if emotion.effective_intensity >= 0.3:
                phrase = _EMOTION_SOOTHE_PHRASES.get(emotion.emotion)
                if phrase:
                    parts.append(phrase)

    intent_type = getattr(analysis, "intent_type", "task")
    if intent_type == "chitchat":
        parts.append(
            "用户正在进行社交闲聊，请友好简短回应，"
            "不需要调用工具或展开复杂分析。"
        )
    elif intent_type == "report":
        parts.append(
            "用户意图为生成使用报告，请按报告生成流程执行："
            "get_user_id → get_current_month → fill_cotext_for_report → fetch_external_data。"
        )

    needs_rag = getattr(analysis, "needs_rag", False)
    if needs_rag and intent_type != "chitchat":
        parts.append(
            "用户问题涉及专业知识，"
            "建议调用 rag_summarize 工具检索知识库以获取准确信息。"
        )

    if not parts:
        return ""
    return "\n".join(parts)


# ==================== 测试 ====================

if __name__ == "__main__":
    engine = SemanticEngine()

    test_cases = [
        "你好呀，今天天气真好",
        "推荐几部像《鬼灭之刃》一样的热血番",
        "我的扫地机器人边刷不转了怎么办？？在线等！！",
        "帮我查一下杭州的实时天气",
        "最近有什么好看的新番吗？",
        "谢谢你的帮助！",
        "心情不好，想看点开心的动漫",
        "帮我生成这个月的使用报告",
    ]

    for text in test_cases:
        analysis = engine.analyze(text)
        print(f"\n{'='*60}")
        print(f"输入: {text}")
        print(f"摘要: {analysis.summary}")
        print(f"主意图: {analysis.primary_intent} (conf={analysis.confidence:.2f})")
        print(f"实体: {[(e.type, e.value) for e in analysis.entities]}")
        print(f"RAG: {analysis.needs_rag}, Web: {analysis.needs_web_search}")

        overlay = engine.build_overlay(analysis)
        if overlay:
            print(f"Overlay:\n{overlay[:200]}...")
