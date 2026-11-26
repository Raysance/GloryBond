"""Host-owned chat input selection; stored history and the ReAct loop stay raw."""

from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
import json
import math
import re

from pydantic import BaseModel, ConfigDict, Field


class ChatContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history_tokens: int = Field(default=1800, ge=0, le=32000)
    group_tokens: int = Field(default=1400, ge=0, le=16000)
    background_tokens: int = Field(default=3000, ge=0, le=48000)
    reference_tokens: int = Field(default=1200, ge=100, le=16000)
    memory_tokens: int = Field(default=500, ge=0, le=8000)


def estimated_tokens(value):
    """A conservative text estimate, never a claim about image or billed tokens."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(len(text.encode("utf-8")) / 3)


def fit_items(items, budget, *, newest_first=False):
    selected, used = [], 0
    for item in reversed(items) if newest_first else items:
        size = estimated_tokens(item)
        if used + size > budget:
            continue
        selected.append(item)
        used += size
    return list(reversed(selected)) if newest_first else selected


def text_content(value):
    if isinstance(value, str):
        return value
    return "\n".join(part.get("text", "") for part in value or () if part.get("type") == "text")


def current_message(text, *, actor, message_id=None, quote=None, images=(), quoted_images=(), documents=(), quoted_documents=()):
    """Keep authorship and media next to the question without interpreting it."""
    parts = []
    if quote:
        parts.append({"type": "text", "text": "引用消息（资料）：\n" + json.dumps(
            {key: value for key, value in quote.items() if key not in {"image_urls", "native_faces"}},
            ensure_ascii=False, separators=(",", ":"))})
        parts.extend(quoted_documents)
        parts.extend(image.content_part() for image in quoted_images)
    parts.append({"type": "text", "text": "当前提问：\n" + json.dumps(
        {"sender": actor, "message_id": message_id, "text": text},
        ensure_ascii=False, separators=(",", ":"))})
    parts.extend(documents)
    parts.extend(image.content_part() for image in images)
    return parts


def participant_identity(snapshot, user_id):
    records = [player for player in snapshot.get("context", {}).get("catalogs", {}).get("players", [])
               if str(user_id) in {str(value) for value in player.get("qq", [])}]
    direct = [player for player in records if not player.get("id_sources", {}).get("qq")]
    records = direct or records
    names = list(dict.fromkeys(player["name"] for player in records if player.get("name")))
    return {"user_id": str(user_id), **({"name": names[0]} if len(names) == 1 else {"names": names} if names else {})}


def group_identities(rows, snapshot):
    result = deepcopy(rows)
    for row in result:
        speaker = row.get("speaker", {})
        if speaker.get("user_id"):
            speaker.update(participant_identity(snapshot, speaker["user_id"]))
        for field in ("requester_id", "mention_user_id"):
            if row.get(field):
                row[field.removesuffix("_id")] = participant_identity(snapshot, row[field])
    return result


def reference_projection(snapshot, *, user_ids=(), query="", budget=1200):
    ids = {str(value) for value in user_ids if value is not None}
    players = snapshot.get("context", {}).get("catalogs", {}).get("players", [])
    direct, named = [], []
    for player in players:
        record = {key: deepcopy(player[key]) for key in ("player_key", "name", "aliases", "qq", "id_sources") if key in player}
        if ids.intersection(str(value) for value in player.get("qq", [])):
            direct.append(record)
        elif any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(str(name)) + r"(?![A-Za-z0-9_])", query, re.I)
                 for name in (player.get("name"), player.get("player_key"), *player.get("aliases", []))
                 if name and len(str(name)) > 1):
            named.append(record)
    # All collisions for a matched name/QQ stay together; never choose one account.
    records = direct + named
    if estimated_tokens(records) > budget:
        records = direct
    return {
        "source": snapshot.get("context", {}).get("source"),
        "version": snapshot.get("context", {}).get("version"),
        "catalogs": [{key: item[key] for key in ("name", "description", "id_namespace") if key in item}
                     for item in snapshot.get("directory", {}).get("catalogs", [])],
        "players": records,
        "other_records": "通过references类别的lookup_reference_data查询；省略不代表不存在。",
    }


@dataclass
class ChatTurn:
    run_id: str
    policy: ChatContextPolicy
    current: object
    context_count: int
    group_rows: list
    record: dict
    prefix: list | None = None
    raw_prefix_count: int = 0
    diagnostics: dict = field(default_factory=dict)


_turn = ContextVar("application_chat_turn", default=None)


def active_turn():
    return _turn.get()


def chat_metadata(*, current, context_count, policy=None, group_rows=(), **record):
    return {"version": 1, "current": current, "context_count": context_count,
            "policy": ChatContextPolicy.model_validate(policy or {}).model_dump(),
            "has_group_context": bool(group_rows), "record": record}


def _history_pairs(messages):
    pairs, current = [], []
    for message in messages:
        if message.get("role") == "user" and current:
            pairs.append(current)
            current = []
        current.append(message)
    if current:
        pairs.append(current)
    return pairs


def select_history(messages, turn):
    """Deduplicate only the same identified turn or an exact legacy Q/A pair."""
    groups = turn.group_rows
    selected = []
    pairs = _history_pairs(messages)
    quote_id = str(turn.record["quote_message_id"]) if turn.record.get("quote_message_id") is not None else None
    source = turn.record.get("quote_sender_id")
    external_quote = source is not None and str(source) not in {
        str(turn.record.get("user_id")), str(turn.record.get("bot_id"))}
    selected_pairs = pairs
    if external_quote:
        selected_pairs = [pair for pair in pairs if quote_id is not None and any(
            str(m.get("turn", {}).get("message_id")) == quote_id
            or str(m.get("turn", {}).get("quote_message_id")) == quote_id for m in pair
            if m.get("role") == "user")]
    elif source is None:
        # A short follow-up continues the last explicit third-party branch.
        for index in range(len(pairs) - 1, -1, -1):
            record = pairs[index][0].get("turn", {})
            previous_source = record.get("quote_sender_id")
            if previous_source is not None and str(previous_source) not in {
                str(turn.record.get("user_id")), str(turn.record.get("bot_id"))}:
                selected_pairs = pairs[index:]
                break
    turn.diagnostics["history_turns_outside_branch"] = len(pairs) - len(selected_pairs)
    for pair in selected_pairs:
        user = next((m for m in pair if m.get("role") == "user"), {})
        answer = next((m for m in pair if m.get("role") == "assistant"), {})
        record = user.get("turn", {})
        message_id = record.get("message_id")
        matching = [row for row in groups if message_id is not None
                    and str(row.get("message_id")) == str(message_id)
                    and str(row.get("user_id")) == str(turn.record.get("user_id"))]
        # Legacy storage has no IDs. Require both the question and answer plus
        # the same requester; a repeated sentence alone is never a duplicate.
        if message_id is None and user and answer:
            questions = [row for row in groups if str(row.get("user_id")) == str(turn.record.get("user_id"))
                         and row.get("text", "").strip().lstrip("#＃").strip() == text_content(user.get("content")).strip()]
            matching = [row for row in groups if any(str(row.get("reply_to_message_id")) == str(q.get("message_id")) for q in questions)
                        and str(row.get("requester_id")) == str(turn.record.get("user_id"))
                        and row.get("text") == text_content(answer.get("content"))]
        # Keep the detailed direct answer, and remove its shorter public copy.
        ids = set()
        if matching:
            ids = {str(row.get("message_id")) for row in matching}
            ids.update(str(row.get("message_id")) for row in groups
                       if str(row.get("reply_to_message_id")) in ids
                       and str(row.get("requester_id")) == str(turn.record.get("user_id")))
        clean = []
        for message in pair:
            item = {key: deepcopy(value) for key, value in message.items()
                    if key in {"role", "content", "reasoning_content"}}
            if message.get("role") == "user" and record.get("input"):
                item["content"] = deepcopy(record["input"])
            clean.append(item)
        selected.append((clean, ids))
    budget = min(turn.policy.history_tokens, turn.policy.background_tokens)
    # Keep consecutive complete turns. Never skip a large recent answer and
    # silently substitute an older, unrelated topic that happens to fit.
    kept, used = [], 0
    duplicate_ids = set()
    for pair, ids in reversed(selected):
        size = estimated_tokens(pair)
        if budget == 0 or (kept and used + size > budget):
            break
        kept.insert(0, pair)
        duplicate_ids.update(ids)
        used += size
    turn.diagnostics.update(history_turns_available=len(selected), history_turns_kept=len(kept),
                            history_estimated_tokens=used, duplicate_public_messages=len(duplicate_ids),
                            duplicate_group_ids=sorted(duplicate_ids), history_over_budget=used > budget)
    return [message for pair in kept for message in pair]


def _compile_prefix(messages, turn):
    current_index = max(i for i, message in enumerate(messages) if message.get("role") == "user")
    context_index = current_index - turn.context_count
    history = select_history(messages[1:context_index], turn)
    background = deepcopy(messages[context_index:current_index])
    duplicates = set(turn.diagnostics.get("duplicate_group_ids", []))
    if turn.group_rows and background:
        # The group block is always the first supplied context message.
        header, payload = background[0]["content"].split("\n", 1)
        data = json.loads(payload)
        rows = [row for row in data["messages"] if str(row.get("message_id")) not in duplicates]
        source = turn.record.get("quote_sender_id")
        external_quote = source is not None and str(source) not in {
            str(turn.record.get("user_id")), str(turn.record.get("bot_id"))}
        all_rows = rows
        remaining = min(turn.policy.group_tokens, max(0, turn.policy.background_tokens - estimated_tokens(history)))
        # Explicit reply ancestors are kept even when outside the recent tail.
        index = {str(row["message_id"]): row for row in rows if row.get("message_id") is not None}
        identifier = data.get("current_turn", {}).get("reply_to_message_id")
        ancestors = set()
        while identifier is not None and str(identifier) not in ancestors:
            identifier = str(identifier)
            ancestors.add(identifier)
            identifier = index.get(identifier, {}).get("reply_to_message_id")
        if external_quote:
            rows = [row for row in rows if str(row.get("reply_to_message_id")) in ancestors
                    or str(row.get("message_id")) in ancestors]
        kept, used = [], 0
        for row in reversed(rows):
            size = estimated_tokens(row)
            if used + size > remaining:
                break
            kept.insert(0, row)
            used += size
        data["messages"] = [row for row in rows if row in kept or str(row.get("message_id")) in ancestors]
        data["combined_truncated"] |= len(data["messages"]) < len(all_rows)
        background[0]["content"] = header + "\n" + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        turn.diagnostics.update(group_messages_available=len(turn.group_rows), group_messages_kept=len(data["messages"]),
                                group_estimated_tokens=estimated_tokens(data["messages"]))
    available = turn.diagnostics["history_turns_outside_branch"] + turn.diagnostics["history_turns_available"] - turn.diagnostics["history_turns_kept"]
    if available:
        background.append({"role": "user", "content": json.dumps({"other_direct_history": {
            "omitted_turns": available, "category": "chat_history", "tool": "read_direct_history"}}, separators=(",", ":"))})
    turn.raw_prefix_count = current_index + 1
    turn.prefix = [deepcopy(messages[0]), *history, *background,
                   {"role": "user", "content": deepcopy(turn.current)}]
    turn.diagnostics.update(version=1, text_estimated_tokens=estimated_tokens(turn.prefix),
                            system_estimated_tokens=estimated_tokens(messages[0]),
                            current_estimated_text_tokens=estimated_tokens(text_content(turn.current)),
                            images=sum(part.get("type") == "image_url" for part in turn.current) if isinstance(turn.current, list) else 0)


def prepare_request(request):
    turn = active_turn()
    if turn is None:
        return request
    if turn.prefix is None:
        _compile_prefix(request.messages, turn)
    return replace(request, messages=deepcopy(turn.prefix) + deepcopy(request.messages[turn.raw_prefix_count:]))


def observe_chat_event(event):
    """Bind selection to a runtime task, just like existing model metadata."""
    kind = event["kind"]
    if kind == "run.start":
        data = event.get("metadata", {}).get("chat_context")
        group_rows = []
        if data and data.get("has_group_context"):
            context = event["data"]["context_messages"][0]["content"]
            group_rows = json.loads(context.split("\n", 1)[1])["messages"]
        _turn.set(ChatTurn(event["run_id"], ChatContextPolicy.model_validate(data["policy"]),
                           data["current"], data["context_count"], group_rows, data["record"])
                  if data and data.get("version") == 1 else None)
    elif kind == "model.request":
        turn = active_turn()
        if turn and turn.run_id == event["run_id"]:
            from agent_runtime import ModelRequest
            event["data"]["messages"] = prepare_request(ModelRequest(event["data"]["messages"], [])).messages
            event["data"]["context_assembly"] = deepcopy(turn.diagnostics)
    elif kind == "run.end":
        _turn.set(None)


class ChatModel:
    """Project application input before handing a structured call to its model."""
    def __init__(self, model):
        self.model = model

    async def complete_request(self, request, delta):
        request = prepare_request(request)
        if callable(getattr(self.model, "complete_request", None)):
            return await self.model.complete_request(request, delta)
        return await self.model.complete(request.messages, request.tools, delta)
