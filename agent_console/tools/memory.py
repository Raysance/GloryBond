"""Pure fact validation, history limits and BM25/RRF shared by agent adapters."""
import json
import math
import re
from collections import Counter
from typing import List


def memory_policy_prompt():
    """Application memory policy; semantic decisions remain in the tool loop."""
    return (
        "长期记忆由当前用户直接表达的信息触发，不要求必须出现‘记住’。"
        "用户明确纠正你的认知、澄清个人背景或使用约定，或描述与旧记忆/先前推断冲突的稳定新信息时，"
        "应发现memory能力，先用recall_memory查相关旧记录，再调用remember_memory保存或更新。"
        "例如‘不是辅助，我一直主玩中路’、‘现在不喜欢安琪拉，主玩小乔了’，都应按新说明更新；"
        "你的原先推断没有对应记忆时，可以新增有依据的纠正事实。"
        "只存清晰、对后续对话有用的事实/偏好/使用约定，不存整段对话、仅一次的短期状态。"
        "先判断是否真的冲突：长期喜欢安琪拉与今天这局想试小乔可以同时成立，换一个话题/对象不代表偏好变化。"
        "‘今天这局想玩小乔试试’只影响本次回答，不调用remember_memory，不把它推成今后主玩小乔，"
        "也不靠补上日期/‘以后想尝试’把临时信息伪装成长期记忆。"
        "‘现在主玩小乔，不再喜欢安琪拉’才明确改变稳定认知，应更新；"
        "‘你刚才猜我是辅助，其实我一直主玩中路’明确澄清稳定背景，也应更新。"
        "只说‘不对’而未提供新信息时先澄清，不把否定词本身写进记忆；疑问、假设、玩笑和引用也不当作本人新事实。"
        "当前用户自己的稳定偏好与背景以最新明确说明为准，旧记忆不是不可纠正的真相。"
        "外部客观事实的纠正需核验依据；未核实时只能保留为该用户的说法/约定，不能作为通用真相或覆盖权威身份映射和查询结果。"
        "更新已查到的旧记录必须传memory_id并写完整的新事实，保留不受本次纠正影响的内容；"
        "同一事实还有多条冲突/重复旧记录时，把其余已查询的ID放入supersedes，原子替换，不能先删后存。"
        "确需保存的稳定信息若新旧说法因时期/条件不同可同时成立，就保留时间或条件，不删除无关记忆。已有等价记忆不要重复新增。"
        "只在当前用户具备memory.use时操作，nomem请求和没有直接用户新说明的后台任务不自动写记忆。"
        "工具成功后才能简短确认更新，本轮回答也采用已澄清的新信息；失败时不要声称已记住。"
    )


def replacement_memory_ids(memory_id, supersedes):
    """Validate replacement targets without inferring semantic contradictions."""
    if not isinstance(supersedes, (list, tuple)) or len(supersedes) > 20:
        raise ValueError("chat_memory: invalid supersedes list")
    targets = []
    for identifier in ([memory_id] if memory_id else []) + list(supersedes):
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier):
            raise ValueError("chat_memory: invalid memory_id")
        if identifier.startswith("legacy-"):
            raise ValueError("chat_memory: legacy memories are read-only")
        if identifier not in targets:
            targets.append(identifier)
    return targets


def recent_history_limits(config=None):
    """Configuration defaults shared by tool schemas and the portable worker."""
    limits = {
        "window_minutes": 15, "max_window_minutes": 60,
        "limit": 20, "max_limit": 50, "max_message_chars": 600,
    }
    supplied = {} if config is None else config
    if not isinstance(supplied, dict) or set(supplied) - set(limits):
        raise ValueError("AgentHistory contains unknown settings")
    limits.update(supplied)
    if any(type(value) is not int or value < 1 for value in limits.values()):
        raise ValueError("AgentHistory settings must be positive integers")
    if limits["window_minutes"] > limits["max_window_minutes"] or limits["limit"] > limits["max_limit"]:
        raise ValueError("AgentHistory defaults exceed their limits")
    return limits

def _validate_fact_content(content, max_chars):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("chat_memory: content must be non-empty text")
    content = content.strip()
    if len(content) > max_chars:
        raise ValueError(f"chat_memory: content exceeds {max_chars} characters")
    if "\x00" in content:
        raise ValueError("chat_memory: content contains an invalid control character")
    if re.search(r"\bsk-[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._-]{12,}", content, re.IGNORECASE):
        raise ValueError("chat_memory: credentials cannot be stored as personal memory")
    return content


def prepare_fact_memory(content, *, memory_id, timestamp, existing=None, max_chars=2000):
    """Build a fact record; callers own user authorization, IDs, time and storage."""
    content = _validate_fact_content(content, max_chars)
    if not isinstance(memory_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", memory_id):
        raise ValueError("chat_memory: invalid memory_id")
    if memory_id.startswith("legacy-") or (existing and existing.get("read_only")):
        raise ValueError("chat_memory: legacy memories are read-only")
    if existing and existing.get("memory_id") != memory_id:
        raise ValueError("chat_memory: memory_id does not match the existing record")
    return {
        "memory_id": memory_id,
        "content": content,
        "created_at": (existing or {}).get("created_at") or timestamp,
        "updated_at": timestamp,
        "source": "direct_user",
        "read_only": False,
    }


def parse_fact_memories(raw_records, *, max_chars=2000):
    """Decode only the current user's supplied fact hash values."""
    records = {}
    values = raw_records.values() if isinstance(raw_records, dict) else raw_records
    for raw in values or []:
        try:
            record = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            if not isinstance(record, dict):
                continue
            normalized = prepare_fact_memory(
                record.get("content"),
                memory_id=record.get("memory_id"),
                timestamp=str(record.get("updated_at") or record.get("created_at") or ""),
                existing=record,
                max_chars=max_chars,
            )
        except (TypeError, ValueError):
            continue
        records[normalized["memory_id"]] = normalized
    return list(records.values())


def search_fact_memories(records, query="", *, limit=20):
    """List recent facts or rank explicit retrieval with the existing BM25 helper."""
    if not isinstance(query, str):
        raise ValueError("chat_memory: query must be text")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("chat_memory: limit must be a positive integer")
    candidates = sorted(
        records or [],
        key=lambda item: (str(item.get("updated_at") or ""), str(item.get("memory_id") or "")),
        reverse=True,
    )
    if not query.strip():
        return [dict(item) for item in candidates[:limit]]
    documents = [tokenize_history_text(item["content"]) for item in candidates]
    scores = _bm25_scores(tokenize_history_text(query), documents)
    indexes = sorted(range(len(candidates)), key=lambda index: (-scores[index], index))
    return [dict(candidates[index]) for index in indexes if scores[index] > 0][:limit]


_HISTORY_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def tokenize_history_text(text: str) -> List[str]:
    """Tokenize colloquial group text for deterministic local retrieval."""
    normalized = " ".join(str(text or "").lower().split())
    try:
        import jieba

        rough_tokens = jieba.lcut(normalized)
    except ModuleNotFoundError:
        rough_tokens = _HISTORY_TOKEN_RE.findall(normalized)
    tokens = []
    seen = set()
    for rough in rough_tokens:
        for token in _HISTORY_TOKEN_RE.findall(str(rough).lower()):
            if token and token not in seen:
                tokens.append(token)
                seen.add(token)
            if re.fullmatch(r"[\u4e00-\u9fff]{3,}", token):
                for size in (2, 3):
                    for index in range(len(token) - size + 1):
                        gram = token[index:index + size]
                        if gram not in seen:
                            tokens.append(gram)
                            seen.add(gram)
    return tokens


def _bm25_scores(query_tokens: List[str], documents: List[List[str]]) -> List[float]:
    if not query_tokens or not documents:
        return [0.0 for _ in documents]
    document_count = len(documents)
    average_length = sum(len(document) for document in documents) / max(document_count, 1)
    document_frequency = Counter()
    for document in documents:
        document_frequency.update(set(document))
    scores = []
    for document in documents:
        frequencies = Counter(document)
        document_length = max(len(document), 1)
        score = 0.0
        for term in query_tokens:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            inverse_frequency = math.log(1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * document_length / max(average_length, 1))
            score += inverse_frequency * (frequency * 2.5) / denominator
        scores.append(score)
    return scores


def search_history_records(records, queries, *, user_ids=None, limit=8, exclude_message_id=None):
    """Search group records with multi-query BM25 and reciprocal-rank fusion."""
    normalized_queries = []
    for query in queries or []:
        query = str(query or "").strip()
        if query and query not in normalized_queries:
            normalized_queries.append(query)
    allowed_users = {str(item) for item in user_ids or [] if str(item or "").strip()}
    candidates = []
    for record in records or []:
        if exclude_message_id is not None and str(record.get("message_id")) == str(exclude_message_id):
            continue
        if allowed_users and str(record.get("user_id")) not in allowed_users:
            continue
        if str(record.get("text") or "").strip():
            candidates.append(record)
    documents = [tokenize_history_text(record.get("text", "")) for record in candidates]
    fused_scores = Counter()
    query_scores = {}
    for query in normalized_queries:
        scores = _bm25_scores(tokenize_history_text(query), documents)
        ranking = sorted(range(len(scores)), key=lambda index: (scores[index], index), reverse=True)
        ranking = [index for index in ranking if scores[index] > 0]
        for rank, index in enumerate(ranking[: max(limit * 3, 10)], 1):
            fused_scores[index] += 1.0 / (60 + rank)
            query_scores.setdefault(index, []).append({"query": query, "bm25": round(scores[index], 4)})
    ranked = sorted(fused_scores, key=lambda index: (fused_scores[index], index), reverse=True)[: max(1, int(limit))]
    results = []
    for index in ranked:
        record = dict(candidates[index])
        record["score"] = round(fused_scores[index], 6)
        record["matches"] = query_scores.get(index, [])
        results.append(record)
    return results
