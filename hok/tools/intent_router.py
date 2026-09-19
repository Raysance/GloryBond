"""Entity-aware local embedding router for natural-language bot requests."""

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
import re
from typing import Optional


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
NONE_INTENT = "__none__"


@lru_cache(maxsize=4096)
def _exact_phonetic_key(value):
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return None
    return "".join(lazy_pinyin(str(value))).casefold()


INTENT_EXAMPLES = {
    "representative_battle": [
        "#看看我昨天的代表局",
        "#查一下我今天最有代表性的比赛",
        "#上周我的高光代表局是什么",
        "#找出<PLAYER>前天的代表局",
        "#看看我这周最离谱的一把",
        "#查询昨天最能代表我水平的对局",
        "#给我看看今天的典型比赛",
        "#找一下<PLAYER>昨天的最佳代表局",
        "#我昨天打得最好和最差的代表局",
        "#查看本周代表性战绩",
    ],
    "atall": [
        "大家上号打王者",
        "喊群友启动游戏",
        "今晚来内战",
        "催大家上线",
        "叫人来打五排",
        "兄弟们该启动了",
        "uw",
        "今晚有没有人一起玩",
        "召集群友开黑",
        "让大家赶紧上游戏",
    ],
    "btlview": [
        "展示对局总览",
        "看看近期战局汇总",
        "最近十场整体情况",
        "给我看战绩概览图",
        "查看一段时间的战况总览",
        "给我综合战绩面板",
        "近期比赛总览",
        "生成战局汇总",
        "把大家最近的对局放一起看",
        "看一下全员战绩概况",
    ],
    "btldetail": [
        "查看更多对局详情",
        "打开刚才那局详细数据",
        "上一把的完整战报",
        "刚刚那场更多信息",
        "继续看这局详情",
        "展示上一局详细面板",
        "最近一把的局内详情",
        "看看那局完整数据",
        "打开对局详情链接",
        "给我刚才比赛的详细战绩",
    ],
    "heropower": [
        "看看我的英雄战力",
        "查询<PLAYER>的全部英雄战力",
        "我的英雄分数怎么样",
        "展示<PLAYER>的英雄战力",
        "查我的玩家战力概览",
        "看看我各英雄的战力",
        "列出<PLAYER>的英雄分数",
        "我的战力英雄列表",
        "查看我的个人英雄分数表",
        "查询我的全部英雄战力",
    ],
    "history_query": [
        "查我昨天用<HERO>赢的对局",
        "找出上周评分超过十二的比赛",
        "查询这个赛季所有巅峰赛",
        "我和<PLAYER>一起打的那些局",
        "找前天凌晨输掉的排位",
        "查询<HERO>伤害超过百分之三十的局",
        "找我评分队内第一的比赛",
        "查看六月到七月的胜利记录",
        "查找经济占比最高的几局",
        "检索符合条件的历史战绩",
        "我要看和<PLAYER>双排赢的比赛",
        "查找上个月评分最高的对局",
        "我的<HERO>的排位赛有哪些",
    ],
    "herostatistics": [
        "我的<HERO>",
        "<PLAYER>的<HERO>",
        "我本赛季的英雄",
        "群友的<HERO>",
        "查询<PLAYER>使用<HERO>的数据",
        "看看我所有英雄的统计",
        "比较群友的<HERO>表现",
        "统计<PLAYER>本赛季各英雄",
        "查看大家玩<HERO>的数据",
        "我的<HERO>赛季统计",
        "统计我这赛季玩<HERO>的数据",
        "<PLAYER>的<HERO>胜率怎么样",
    ],
    "todayhero": [
        "今日英雄",
        "今天推荐我玩什么英雄",
        "给我抽一个今日英雄",
        "今天适合玩谁",
        "随机推荐今日英雄",
        "生成我的今日英雄",
        "今天拿什么英雄上分",
        "看看今日英雄卡片",
        "今日适合的本命英雄",
        "帮我随机挑个英雄玩",
    ],
    "showonline": [
        "谁在线",
        "看看现在谁在游戏里",
        "群友在线状态",
        "有哪些人正在打王者",
        "查询大家是否在线",
        "现在谁正在对局",
        "显示在线玩家",
        "看看群里谁上号了",
        "实时游戏状态",
        "给我在线名单",
    ],
    "gradeanalyze": [
        "分析我的评分走势",
        "看看<PLAYER>最近上分状态",
        "生成我的战绩评分分析",
        "分析我的最近表现",
        "我的评分趋势怎么样",
        "查看<PLAYER>的状态曲线",
        "评估我的近期竞技状态",
        "分析我这段时间打得好不好",
        "给我一张评分分析图",
        "看看我的上分趋势",
        "我这周打得有没有进步",
    ],
    "watchbattle": [
        "ob<PLAYER>",
        "观战<PLAYER>",
        "看看<PLAYER>正在打的对局",
        "获取我的实时战局截图",
        "我要OB<PLAYER>",
        "查看<PLAYER>正在进行的比赛",
        "生成我的观战画面",
        "看看<PLAYER>现在这把",
        "实时观察<PLAYER>的对局",
        "截一张<PLAYER>当前战局",
    ],
    "spoiler": [
        "预言<PLAYER>这局",
        "预测当前对局结果",
        "算算这把能不能赢",
        "看看实时阵容胜算",
        "给正在打的比赛做预言",
        "预测<PLAYER>这把输赢",
        "分析当前战局底蕴",
        "这把胜率怎么样",
        "预判正在进行的对局",
        "计算实时比赛结果",
        "<PLAYER>正在打的这把有戏吗",
    ],
    "recentpower": [
        "看看我的底蕴",
        "<PLAYER>最近七天底蕴",
        "分析我的英雄池底蕴",
        "查看我的近期对位实力",
        "给我个人底蕴报告",
        "查<PLAYER>的底蕴数据",
        "分析我的英雄池实力底子",
        "查看我的对位能力报告",
        "群友底蕴排行榜",
        "最近一周谁底蕴最强",
        "谁的英雄池最深",
        "把大家的对位能力排个名",
    ],
    "recentgames": [
        "看看我的游戏时长",
        "<PLAYER>最近玩了多久",
        "查询我的最近游戏时间",
        "我的本周王者时长",
        "统计<PLAYER>的游玩时长",
        "我最近打了多少小时",
        "查看我的个人在线时长",
        "群友时长排行",
        "今天谁玩得最久",
        "本周大家游戏时长榜",
        "比较群友在线时间",
    ],
    "rank": [
        "看看群排行",
        "谁最近打得最好",
        "给大家排个名",
        "本周战绩排名",
        "群里谁上分最猛",
        "查看综合排行榜",
        "最近胜率排行",
        "大家的王者名次",
        "按表现排一下群友",
        "生成群内战绩榜",
        "最近群里谁状态最好",
    ],
    "single": [
        "看看我的战绩",
        "查一下<PLAYER>最近打得怎样",
        "我的近期战况",
        "看<PLAYER>上一把战绩",
        "我今天打得怎么样",
        "查看<PLAYER>的最近对局",
        "给我个人战绩报告",
        "查询我的王者表现",
        "看看<PLAYER>这赛季战况",
        "展示我最近一局比赛",
        "<PLAYER>战绩",
        "瞅瞅<PLAYER>这两天发挥如何",
        "给我看看<PLAYER>上一局表现",
    ],
    "bili_subscribe": [
        "订阅影视飓风",
        "帮我关注这个B站UP主",
        "订阅小约翰可汗的最新视频",
        "以后提醒我这个UP更新",
        "关注一下影视飓风的视频",
        "给我订阅这个哔哩哔哩作者",
        "添加一个UP主订阅",
        "我想收到某个UP的视频推送",
        "订阅B站博主老师好我叫何同学",
        "帮我追踪这个UP主的新视频",
    ],
    "bili_unsubscribe": [
        "取消订阅影视飓风",
        "不要再提醒这个UP更新",
        "移除小约翰可汗的视频订阅",
        "取消关注这个B站UP主",
        "停止推送这个博主的视频",
        "把影视飓风从订阅里删掉",
        "退订这个UP主",
        "我不想再看这个作者的更新",
        "取消我的B站视频提醒",
        "停止追踪这个UP的新视频",
        "别再推送影视飓风的视频了",
    ],
    "bili_latest": [
        "看看订阅UP的最新视频",
        "我的订阅最近更新了什么",
        "查询最新视频",
        "订阅的UP有新视频吗",
        "给我看关注博主的最近投稿",
        "最近有哪些B站更新",
        "查看订阅列表的最新一期",
        "我关注的UP刚发了什么",
        "列出订阅UP的最新投稿",
        "查询我的订阅最新视频",
    ],
    "bili_mine": [
        "我的订阅",
        "查看我的UP订阅列表",
        "我关注了哪些B站作者",
        "查询订阅状态",
        "列出我订阅的所有UP主",
        "我的B站关注列表",
        "看看视频推送名单",
        "显示当前UP订阅",
        "我都订阅了谁",
        "查看我的视频订阅设置",
    ],
    NONE_INTENT: [
        "今天晚上吃什么",
        "这个表情包太好笑了",
        "我先去洗澡了",
        "<PLAYER>今天上班吗",
        "<PLAYER>这辈子能上荣耀吗",
        "让<PLAYER>拿我的号玩游戏",
        "<HERO>这个皮肤真好看",
        "我刚才看到一个B站视频",
        "我的手机快没电了",
        "今晚可能要下雨",
        "谁知道这个怎么弄",
        "这个消息是真的吗",
        "我订阅了好多频道",
        "<HERO>玩家都这么凶吗",
        "<REGION>今天好热",
        "我在<REGION>出差",
        "最近工作有点忙",
        "明天早点叫我起床",
        "你们在聊什么",
        "哈哈哈哈笑死我了",
    ],
}


@dataclass(frozen=True)
class EntityNormalization:
    text: str
    entity_types: frozenset
    values: dict


@dataclass(frozen=True)
class IntentDecision:
    intent: Optional[str]
    score: float
    margin: float
    normalized_text: str
    entities: EntityNormalization
    candidates: tuple


class EntityNormalizer:
    PLACEHOLDERS = {
        "player": "<PLAYER>",
        "hero": "<HERO>",
        "region": "<REGION>",
    }

    _HERO_CONTEXT = (
        "我玩", "我用", "我的", "玩", "用", "拿", "选", "练", "英雄",
        "战力", "胜率", "出装", "铭文", "熟练度", "对线", "技能", "攻略",
        "查询", "数据", "统计", "表现", "战绩", "对局", "皮肤",
    )
    _PLAYER_CONTEXT = (
        "战绩", "战况", "底蕴", "时长", "在线", "观战", "预言", "评分",
        "上分", "英雄", "最近", "现在", "这把", "的", "查", "看", "分析",
    )
    _HERO_PHONETIC_LEFT = (
        "我的", "我玩", "我用", "玩", "用", "拿", "选", "练", "使用",
        "查询", "查", "看看", "查看", "统计", "分析", "推荐", "的",
    )
    _HERO_PHONETIC_RIGHT = (
        "战力", "胜率", "数据", "统计", "表现", "战绩", "对局", "排位",
        "巅峰赛", "出装", "铭文", "熟练度", "技能", "攻略", "皮肤",
        "伤害", "玩家", "怎么样", "如何", "怎么出", "的",
    )
    _PLAYER_PHONETIC_LEFT = (
        "查询", "查询一下", "查", "查一下", "看看", "给我看看", "看",
        "查看", "观战", "ob", "预言", "预测", "分析", "统计", "比较",
        "找", "找出", "和", "跟", "叫", "催", "的",
    )
    _PLAYER_PHONETIC_RIGHT = (
        "战绩", "战况", "底蕴", "时长", "在线", "最近", "现在", "这把",
        "上一把", "上一局", "本赛季", "使用", "玩", "正在", "的", "表现",
        "评分", "状态", "上分", "英雄",
    )

    def __init__(self, player_aliases=(), hero_aliases=(), region_aliases=()):
        aliases = {}
        for entity_type, values in (
            ("player", player_aliases),
            ("hero", hero_aliases),
            ("region", region_aliases),
        ):
            for value in values:
                alias = str(value or "").strip()
                if not alias:
                    continue
                aliases.setdefault(alias, set()).add(entity_type)
        self._literal_aliases = []
        self._chinese_exact = {}
        self._phonetic_exact = {}
        self._lazy_pinyin = None
        try:
            from pypinyin import lazy_pinyin

            self._lazy_pinyin = lazy_pinyin
        except ImportError:
            pass

        for alias, entity_types in aliases.items():
            if re.fullmatch(r"[\u4e00-\u9fff]+", alias):
                exact_key = (len(alias), alias)
                self._chinese_exact.setdefault(exact_key, set()).update(entity_types)
                phonetic_types = entity_types.intersection({"player", "hero"})
                if self._lazy_pinyin is not None and phonetic_types:
                    phonetic_key = (len(alias), "".join(self._lazy_pinyin(alias)))
                    self._phonetic_exact.setdefault(phonetic_key, set()).update(
                        phonetic_types
                    )
            else:
                self._literal_aliases.append((alias, entity_types))
        self._literal_aliases = tuple(
            sorted(self._literal_aliases, key=lambda item: (-len(item[0]), item[0]))
        )
        self._chinese_lengths = tuple(
            sorted({length for length, _ in self._chinese_exact}, reverse=True)
        )

    @staticmethod
    def district_aliases(payload):
        result = set()

        def visit(nodes):
            for node in nodes or []:
                for key in ("shortName", "fullName"):
                    value = str(node.get(key) or "").strip()
                    if len(value) >= 2:
                        result.add(value)
                visit(node.get("list"))

        visit(((payload or {}).get("data") or {}).get("list") or [])
        return result

    @staticmethod
    def _is_ascii_token(value):
        return bool(re.fullmatch(r"[A-Za-z0-9_]+", value))

    def _one_char_hero_has_context(self, text, start, end):
        if text.strip() == text[start:end]:
            return True
        window = text[max(0, start - 4):min(len(text), end + 5)]
        return any(marker in window for marker in self._HERO_CONTEXT)

    def _one_char_player_has_context(self, text, start, end):
        if text.strip() == text[start:end]:
            return True
        window = text[max(0, start - 4):min(len(text), end + 6)]
        return any(marker in window for marker in self._PLAYER_CONTEXT)

    def _phonetic_has_context(self, entity_type, text, start, end):
        if text.strip() == text[start:end]:
            return True
        left = text[:start].rstrip()
        right = text[end:].lstrip()
        if entity_type == "hero":
            left_markers = self._HERO_PHONETIC_LEFT
            right_markers = self._HERO_PHONETIC_RIGHT
        else:
            left_markers = self._PLAYER_PHONETIC_LEFT
            right_markers = self._PLAYER_PHONETIC_RIGHT
        left_boundary = not left or any(left.endswith(item) for item in left_markers)
        right_boundary = not right or any(
            right.startswith(item) for item in right_markers
        )
        return left_boundary and right_boundary

    @staticmethod
    def _resolve_ambiguous_type(text, start, end, entity_types):
        if len(entity_types) == 1:
            return next(iter(entity_types))
        left = text[max(0, start - 4):start]
        right = text[end:min(len(text), end + 6)]
        if "hero" in entity_types and any(
            marker in left for marker in ("玩", "用", "拿", "选", "练", "我的")
        ):
            return "hero"
        if "player" in entity_types and any(
            marker in right for marker in ("战绩", "战况", "底蕴", "时长", "在线", "现在", "最近", "的")
        ):
            return "player"
        return None

    def normalize(self, text):
        source = str(text or "").strip()
        matches = []
        for entity_type, placeholder in self.PLACEHOLDERS.items():
            offset = 0
            while True:
                index = source.find(placeholder, offset)
                if index < 0:
                    break
                matches.append(
                    (index, index + len(placeholder), entity_type, placeholder)
                )
                offset = index + len(placeholder)
        for alias, entity_types in self._literal_aliases:
            if self._is_ascii_token(alias):
                pattern = re.compile(
                    rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
                    re.IGNORECASE,
                )
                spans = (match.span() for match in pattern.finditer(source))
            else:
                spans = []
                offset = 0
                while True:
                    index = source.find(alias, offset)
                    if index < 0:
                        break
                    spans.append((index, index + len(alias)))
                    offset = index + 1
            for start, end in spans:
                selected_type = self._resolve_ambiguous_type(
                    source, start, end, entity_types
                )
                if selected_type is None:
                    continue
                if (
                    selected_type == "hero"
                    and len(alias) == 1
                    and not self._one_char_hero_has_context(source, start, end)
                ):
                    continue
                if (
                    selected_type == "player"
                    and len(alias) == 1
                    and not self._one_char_player_has_context(source, start, end)
                ):
                    continue
                matches.append((start, end, selected_type, alias))

        for run_match in re.finditer(r"[\u4e00-\u9fff]+", source):
            run = run_match.group(0)
            syllables = self._lazy_pinyin(run) if self._lazy_pinyin is not None else ()
            for length in self._chinese_lengths:
                if length > len(run):
                    continue
                for relative_start in range(len(run) - length + 1):
                    candidate = run[relative_start:relative_start + length]
                    exact_types = self._chinese_exact.get(
                        (length, candidate), set()
                    )
                    phonetic_types = set()
                    if syllables:
                        phonetic_key = "".join(
                            syllables[relative_start:relative_start + length]
                        )
                        phonetic_types = self._phonetic_exact.get(
                            (length, phonetic_key), set()
                        )
                    entity_types = exact_types.union(phonetic_types)
                    if not entity_types:
                        continue
                    start = run_match.start() + relative_start
                    end = start + length
                    selected_type = self._resolve_ambiguous_type(
                        source, start, end, entity_types
                    )
                    if selected_type is None:
                        continue
                    is_exact = selected_type in exact_types
                    if not is_exact and not self._phonetic_has_context(
                        selected_type, source, start, end
                    ):
                        continue
                    if (
                        selected_type == "hero"
                        and length == 1
                        and not self._one_char_hero_has_context(source, start, end)
                    ):
                        continue
                    if (
                        selected_type == "player"
                        and length == 1
                        and not self._one_char_player_has_context(source, start, end)
                    ):
                        continue
                    matches.append((start, end, selected_type, candidate))

        selected = []
        occupied_until = -1
        for item in sorted(matches, key=lambda row: (row[0], -(row[1] - row[0]))):
            start, end, _, _ = item
            if start < occupied_until:
                continue
            selected.append(item)
            occupied_until = end

        if not selected:
            return EntityNormalization(source, frozenset(), {})

        chunks = []
        cursor = 0
        values = {"player": [], "hero": [], "region": []}
        for start, end, entity_type, alias in selected:
            chunks.append(source[cursor:start])
            chunks.append(self.PLACEHOLDERS[entity_type])
            values[entity_type].append(alias)
            cursor = end
        chunks.append(source[cursor:])
        present = frozenset(key for key, items in values.items() if items)
        return EntityNormalization(
            "".join(chunks),
            present,
            {key: tuple(items) for key, items in values.items() if items},
        )

    def extract_surface(self, text, entity_type, precise=False):
        result = self.normalize(text)
        values = result.values.get(entity_type, ())
        if not values:
            return None
        if precise and result.text != self.PLACEHOLDERS[entity_type]:
            return None
        return values[0]


def resolve_exact_phonetic_target(surface, alias_targets):
    """Resolve one complete surface form without substring or edit-distance matching."""
    source = str(surface or "").strip()
    if not source:
        return None
    direct_targets = {
        target
        for alias, target in alias_targets.items()
        if str(alias).strip().casefold() == source.casefold()
    }
    if len(direct_targets) == 1:
        return next(iter(direct_targets))
    if len(direct_targets) > 1:
        return None
    source_key = _exact_phonetic_key(source)
    if source_key is None:
        return None
    phonetic_targets = {
        target
        for alias, target in alias_targets.items()
        if _exact_phonetic_key(alias) == source_key
    }
    if len(phonetic_targets) == 1:
        return next(iter(phonetic_targets))
    return None


class FastEmbedBackend:
    def __init__(
        self,
        cache_dir,
        model_name=MODEL_NAME,
        local_files_only=True,
        threads=1,
    ):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=cache_dir,
            threads=int(threads),
            providers=["CPUExecutionProvider"],
            lazy_load=False,
            local_files_only=local_files_only,
        )

    def encode(self, texts, batch_size=32):
        return list(self._model.embed(list(texts), batch_size=batch_size))


class EmbeddingIntentRouter:
    def __init__(
        self,
        normalizer,
        embedder,
        cache_loader=None,
        cache_writer=None,
        min_score=0.60,
        min_margin=0.025,
    ):
        self.normalizer = normalizer
        self.embedder = embedder
        self.min_score = float(min_score)
        self.min_margin = float(min_margin)
        self._labels = []
        normalized_examples = []
        for intent, examples in INTENT_EXAMPLES.items():
            for example in examples:
                self._labels.append(intent)
                normalized_examples.append(self._prepare_text(example))
        fingerprint_source = json.dumps(
            {
                "model": getattr(embedder, "model_name", MODEL_NAME),
                "examples": normalized_examples,
                "labels": self._labels,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.fingerprint = hashlib.sha256(
            fingerprint_source.encode("utf-8")
        ).hexdigest()[:20]
        embeddings = cache_loader(self.fingerprint) if cache_loader else None
        if embeddings is None or len(embeddings) != len(self._labels):
            embeddings = embedder.encode(normalized_examples)
            embeddings = self._normalize_vectors(embeddings)
            if cache_writer:
                cache_writer(self.fingerprint, embeddings)
        else:
            embeddings = self._normalize_vectors(embeddings)
        self._embeddings = embeddings
        self._intent_indices = {}
        for index, label in enumerate(self._labels):
            self._intent_indices.setdefault(label, []).append(index)

    @staticmethod
    def _strip_single_prefix(text):
        stripped = str(text or "").strip()
        if stripped.startswith("#") or stripped.startswith("＃"):
            return stripped[1:].strip()
        return stripped

    def _prepare_text(self, text):
        return self.normalizer.normalize(self._strip_single_prefix(text)).text

    @staticmethod
    def _normalize_vectors(vectors):
        normalized = []
        for vector in vectors:
            values = [float(item) for item in vector]
            norm = math.sqrt(sum(item * item for item in values)) or 1.0
            normalized.append([item / norm for item in values])
        return normalized

    @staticmethod
    def _dot(left, right):
        return sum(a * b for a, b in zip(left, right))

    @staticmethod
    def _contains_self_or_group(raw):
        return any(word in raw for word in ("我", "自己", "群友", "大家", "全员", "群u"))

    def _valid_for_intent(self, intent, raw, entities, has_prefix):
        types = entities.entity_types
        has_player = "player" in types or self._contains_self_or_group(raw)
        has_hero = "hero" in types

        if intent == "representative_battle":
            return has_prefix
        if intent == "atall":
            return any(
                word in raw.lower()
                for word in (
                    "大家", "群友", "兄弟", "有人", "来", "一起", "召集", "催",
                    "叫", "赶紧", "上号", "启动", "内战", "五排", "开黑", "uw",
                )
            )
        if intent == "herostatistics":
            history_retrieval = any(
                word in raw
                for word in ("哪些", "找出", "查找", "昨天", "前天", "上周", "上个月")
            ) and any(
                word in raw for word in ("对局", "比赛", "排位", "巅峰赛", "局")
            )
            if history_retrieval:
                return False
            return (has_hero or "英雄" in raw) and has_player
        if intent in {"heropower", "gradeanalyze", "watchbattle", "single"}:
            return has_player
        if intent == "recentpower":
            return has_player or any(word in raw for word in ("排行", "排名", "谁", "全员", "大家"))
        if intent == "recentgames":
            return has_player or any(word in raw for word in ("排行", "排名", "谁", "全员", "大家"))
        if intent == "bili_subscribe":
            direct_subscribe = raw.startswith("订阅") and raw not in {
                "订阅", "订阅最新视频", "订阅UP最新视频", "订阅up最新视频",
            }
            has_subject = any(
                word in raw.lower() for word in ("up", "b站", "视频", "博主", "作者")
            )
            return direct_subscribe or (has_subject and any(
                word in raw
                for word in (
                    "订阅", "帮我关注", "关注一下", "添加", "追踪", "收到",
                    "提醒我", "视频推送",
                )
            ))
        if intent == "bili_unsubscribe":
            return any(
                word in raw
                for word in (
                    "取消订阅", "退订", "停止推送", "取消关注", "不再提醒",
                    "不要再提醒", "移除", "删掉", "不想再看", "取消我的", "停止追踪",
                    "别再推送",
                )
            )
        if intent == "bili_latest":
            has_video_subject = "视频" in raw or "订阅" in raw or any(
                word in raw.lower() for word in ("up", "b站", "博主", "投稿")
            )
            return has_video_subject and any(
                word in raw for word in ("最新", "新视频", "更新", "最近", "投稿", "发了")
            )
        if intent == "bili_mine":
            has_subject = "订阅" in raw or "视频推送" in raw or any(
                word in raw.lower() for word in ("up", "b站")
            )
            return has_subject and any(
                word in raw
                for word in ("我的", "列表", "状态", "哪些", "谁", "名单", "关注", "列出", "显示")
            )
        return True

    def classify(self, text):
        raw = str(text or "").strip()
        if not raw:
            empty_entities = self.normalizer.normalize("")
            return IntentDecision(None, 0.0, 0.0, "", empty_entities, ())
        normalized_hash = raw.replace("＃", "#")
        if normalized_hash.startswith("##"):
            entities = self.normalizer.normalize(raw)
            return IntentDecision(None, 0.0, 0.0, entities.text, entities, ())
        has_prefix = raw.startswith("#") or raw.startswith("＃")
        prepared_raw = self._strip_single_prefix(raw)
        entities = self.normalizer.normalize(prepared_raw)
        query = self._normalize_vectors(self.embedder.encode([entities.text], batch_size=1))[0]
        intent_scores = {}
        for intent, indices in self._intent_indices.items():
            example_scores = sorted(
                (self._dot(query, self._embeddings[index]) for index in indices),
                reverse=True,
            )
            top = example_scores[:3]
            intent_scores[intent] = (0.7 * top[0]) + (0.3 * sum(top) / len(top))

        valid_scores = []
        for intent, score in intent_scores.items():
            if intent == NONE_INTENT or self._valid_for_intent(
                intent, prepared_raw, entities, has_prefix
            ):
                valid_scores.append((intent, score))
        valid_scores.sort(key=lambda item: item[1], reverse=True)
        candidates = tuple((name, round(score, 6)) for name, score in valid_scores[:5])
        if not valid_scores:
            return IntentDecision(None, 0.0, 0.0, entities.text, entities, candidates)
        best_intent, best_score = valid_scores[0]
        second_score = valid_scores[1][1] if len(valid_scores) > 1 else 0.0
        margin = best_score - second_score
        if (
            best_intent == NONE_INTENT
            or best_score < self.min_score
            or margin < self.min_margin
        ):
            best_intent = None
        return IntentDecision(
            best_intent,
            round(best_score, 6),
            round(margin, 6),
            entities.text,
            entities,
            candidates,
        )


def collect_player_aliases(namenick, nameref, extra_namenick=None):
    values = set(str(item) for item in (namenick or {}).keys())
    values.update(str(item) for item in (namenick or {}).values())
    values.update(str(item) for item in (nameref or {}).keys())
    values.update(str(item) for item in (extra_namenick or {}).keys())
    values.update(str(item) for item in (extra_namenick or {}).values())
    for aliases in (nameref or {}).values():
        values.update(str(item) for item in aliases)
    return values


def collect_hero_aliases(hero_list, replacements):
    aliases = {
        str(item)
        for item in list((hero_list or {}).values()) + list((replacements or {}).values())
        if str(item or "").strip()
    }
    try:
        from pypinyin import lazy_pinyin

        aliases.update(
            "".join(lazy_pinyin(alias))
            for alias in tuple(aliases)
            if re.search(r"[\u4e00-\u9fff]", alias)
        )
    except ImportError:
        pass
    return aliases
