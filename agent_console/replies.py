"""Preserve the main answer and produce an optional short delivery version."""

import asyncio
import json
import re
from dataclasses import replace
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_runtime import FinalAnswer
from .reply_style import default_assistant_instruction


class DeliveryHistory:
    """Preserve accepted answer parts without reloading tool/model transcripts."""

    def __init__(self):
        self.parts = {}

    def record(self, event):
        run = event["run_id"]
        data = event.get("data", {})
        if event["kind"] == "output.message" and data.get("kind") == "partial":
            text = data.get("text", "")
            if isinstance(text, str) and text.strip():
                self.parts.setdefault(run, []).append(text)
        elif event["kind"] == "run.end":
            self.parts.pop(run, None)

    def preserve(self, answer, request, formatter=lambda text: text):
        parts = self.parts.get(request.run_id, [])
        if not parts:
            return answer
        return replace(answer, history_text="\n\n".join(
            [*(formatter(text) for text in parts), answer.history_text or answer.text]))


class ReplyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_max_chars: int = Field(default=280, ge=80, le=2000)
    concise_max_chars: int = Field(default=100, ge=40, le=2000)
    source_max_chars: int = Field(default=16000, ge=1000, le=100000)
    max_attempts: int = Field(default=2, ge=1, le=2)
    timeout_seconds: float = Field(default=60, gt=0, le=120)
    history_variant: Literal["detailed", "chat"] = "detailed"
    select_delivery_variant: bool = False


class ChatReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat: str = Field(min_length=1)
    detailed: str | None = Field(default=None, min_length=1)
    default_variant: Literal["chat", "detailed"] = "chat"


def numeric_values(text):
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s*)?\d+[.)、]\s+", "", text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    values = set()
    for token in re.findall(
        r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?:[%％])?(?![A-Za-z0-9_])", text
    ):
        percentage = token.endswith(("%", "％"))
        value = Decimal(token[:-1] if percentage else token)
        values.add(value / 100 if percentage else value)
    return values


def source_urls(text):
    return {
        url.rstrip(".,;!?，。；！？)")
        for url in re.findall(r"https?://[^\s<>\"'\\]+", text)
    }


def validate_chat(content, evidence, policy):
    reply = ChatReply.model_validate_json(content)
    reply.chat = reply.chat.strip()
    if not reply.chat:
        raise ValueError("群聊回复不得为空")
    if len(reply.chat) > policy.chat_max_chars:
        raise ValueError("回复超过长度限制，请压缩句子而非截断内容")
    if (
        "```" in reply.chat
        or "**" in reply.chat
        or re.search(r"(?m)^\s*(?:#{1,6}\s|[-*]\s|\|)", reply.chat)
    ):
        raise ValueError(
            "群聊版须为自然的纯文本，不使用标题、列表、表格、粗体或代码围栏"
        )
    # A cheap guard against new literals, not a semantic fact validator.
    # Numeric relationships are preserved at the source: one canonical answer,
    # a presentation-only task and no second interpretation of raw evidence.
    if numeric_values(reply.chat) - numeric_values(evidence):
        raise ValueError("出现资料未提供的新数值，保留资料中的数字与单位")
    if source_urls(reply.chat) - source_urls(evidence):
        raise ValueError("出现资料未提供的新链接，请保留原始来源链接")
    if reply.detailed is not None and reply.detailed != evidence:
        raise ValueError("详细正文由主模型确定，简版整理不得改写；detailed应为null")
    return reply.chat


def source_packet(context):
    """All evidence is interpreted once by ReAct; presentation gets its answer.

    Deliberately never inspect messages. This excludes tool catalogues, retrieved
    dialogue, examples and alternate stale answers without tool-name patches.
    """
    result = {"question": context.request.user_message, "answer": context.draft}
    current = context.request.metadata.get("chat_context", {}).get("current")
    if current:
        from .chat_context import text_content
        result["input_reference"] = text_content(current)
    return result


def expression_role(role):
    """Voice is sufficient for presentation; biographies belong to reasoning."""
    if role.get("voice"):
        result = {"name": role["name"], "voice": role["voice"]}
        if role.get("role_id") == "assistant":
            result["default_style"] = default_assistant_instruction()
        return result
    if role.get("role_id") == "assistant":
        return {"name": role["name"], "expression": default_assistant_instruction()}
    profile = role["profile"]
    try:
        data = json.loads(profile)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        profile = {
            key: data[key]
            for key in ("personality", "speech_style")
            if key in data
        } or profile
    # Legacy user roles have no voice card; keep their original expression data.
    return {"name": role["name"], "expression": profile}


def reply_instruction(policy):
    contract = '仅输出JSON对象 {"detailed":null,"chat":"简版"}。'
    if policy.select_delivery_variant:
        contract += '另含default_variant字段，按本次要求和preferences选择chat或detailed。'
    return (
        "answer是主模型已完成的完整回复，包含本轮的对象、事实和语气；你只负责生成它的简版。"
        "question和input_reference提供当前提问的来源关系，不重新调查或重新解释用户意图。"
        + contract +
        "提取正文中最有用的一至三句，保持同一对象、立场、确定程度、数字关系和来源。"
        "不能增加归因、调侃对象、执行状态或新的话题；无法保留的复杂数字整组省略。"
        "作品保留代表原句，完整内容在详细版中；引文、代码及事实关系不作重构。"
        "已有角色语气自然保留，使用纯文本，不加标题、列表、表格或额外邀请。"
        f"chat最多{policy.chat_max_chars}字，详细正文保持原样。"
    )


class ReplyComposer:
    def __init__(self, *, model, roles, policy=None, delivery_history=None):
        self.model, self.roles = model, roles
        self.policy = policy or ReplyPolicy()
        self.delivery_history = delivery_history

    def preserve_history(self, answer, context):
        return self.delivery_history.preserve(answer, context.request) if self.delivery_history else answer

    async def finalize(self, context, emit):
        try:
            async with asyncio.timeout(self.policy.timeout_seconds):
                snapshot = (
                    await self.roles.manage(context.request.principal)
                    if "roleplay.use" in context.request.principal.scopes
                    else None
                )
                snapshot = snapshot or {
                    "selected": {
                        "role_id": "assistant",
                        "name": "通用助手",
                        "profile": "自然、清楚、直接，不扮演虚构人物。",
                    },
                    "preferences": {"length": "concise", "address": "", "style": ""},
                }
                policy = self.policy
                if snapshot["preferences"]["length"] == "concise":
                    policy = policy.model_copy(
                        update={"chat_max_chars": min(
                            policy.chat_max_chars, policy.concise_max_chars
                        )}
                    )
                try:
                    validate_chat(json.dumps({"chat": context.draft}, ensure_ascii=False), context.draft, policy)
                except ValueError:
                    pass
                else:
                    await emit("reply.preserved", {"reason": "complete_short_answer"})
                    return self.preserve_history(FinalAnswer(
                        context.draft, variants={"detailed": context.draft, "chat": context.draft},
                        metadata={"role_name": snapshot["selected"]["name"],
                                  "role_id": snapshot["selected"]["role_id"], "default_variant": "chat"},
                        history_text=context.draft), context)
                data = {
                    **source_packet(context),
                    "role": {"name": snapshot["selected"]["name"]},
                    "preferences": snapshot["preferences"],
                }
                content = json.dumps(data, ensure_ascii=False)
                if len(content) > self.policy.source_max_chars:
                    raise ValueError("群聊表达输入超过预算，保留完整底稿，不截断事实")
                messages = [
                    {"role": "system", "content": reply_instruction(policy)},
                    {"role": "user", "content": content},
                ]
                for attempt in range(1, self.policy.max_attempts + 1):
                    await emit(
                        "reply.model.request",
                        {
                            "attempt": attempt,
                            "messages": messages,
                            "tools": [],
                            "role_name": snapshot["selected"]["name"],
                            "context_chars": {
                                key: len(json.dumps(value, ensure_ascii=False))
                                for key, value in data.items()
                            },
                        },
                    )

                    async def delta(channel, text):
                        await emit(
                            "reply.model.delta",
                            {"attempt": attempt, "channel": channel, "text": text},
                            transient=True,
                        )

                    response = await self.model.complete(messages, [], delta)
                    await emit("reply.model.response", {"attempt": attempt, **response})
                    message = response["message"]
                    try:
                        if message.get("tool_calls"):
                            raise ValueError("回复整理阶段不能调用工具")
                        chat = validate_chat(
                            message.get("content") or "", context.draft, policy
                        )
                        presentation = ChatReply.model_validate_json(message["content"])
                        detailed = context.draft
                        if policy.select_delivery_variant and 'default_variant' not in presentation.model_fields_set:
                            raise ValueError("QQ回复须明确提供default_variant选择展示版本")
                        variant = presentation.default_variant if policy.select_delivery_variant else "chat"
                    except ValueError as exc:
                        await emit(
                            "reply.validation",
                            {"attempt": attempt, "error": str(exc)[:500]},
                        )
                        if attempt == self.policy.max_attempts:
                            raise
                        messages.extend(
                            [
                                {
                                    "role": "assistant",
                                    "content": message.get("content") or "",
                                },
                                {
                                    "role": "user",
                                    "content": "刚才JSON未通过检查："
                                    + str(exc)[:400]
                                    + "。只修正输出结构、长度和表达，保留已有事实；不要创造数据或新动作。",
                                },
                            ]
                        )
                        continue
                    return self.preserve_history(FinalAnswer(
                        detailed if variant == "detailed" else chat,
                        variants={"detailed": detailed, "chat": chat},
                        metadata={
                            "role_name": snapshot["selected"]["name"],
                            "role_id": snapshot["selected"]["role_id"],
                            "default_variant": variant,
                        },
                        history_text=detailed
                        if self.policy.history_variant == "detailed"
                        else chat,
                    ), context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await emit(
                "reply.failure", {"error": str(exc)[:1000], "type": type(exc).__name__}
            )
            await emit("run.warning", {"error": "回复整理未完成，保留原始回答。"})
            return self.preserve_history(FinalAnswer(
                context.draft,
                variants={
                    "detailed": context.draft,
                    "chat": context.draft,
                },
                metadata={"default_variant": "detailed" if self.policy.select_delivery_variant else "chat", "degraded": True},
                history_text=context.draft,
            ), context)
