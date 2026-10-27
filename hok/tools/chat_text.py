"""Render model text for QQ, with configured player names and no identity fields."""

from markdown_it import MarkdownIt
import re


def split_chat_forward_text(text, max_chars):
    """Split complete text at paragraph/line boundaries, keeping every character."""
    remaining = str(text)
    if max_chars <= 0:
        raise ValueError("转发节点文字预算须大于0")
    nodes = []
    while len(remaining) > max_chars:
        end = remaining.rfind("\n\n", 0, max_chars)
        if end >= 0:
            end += 2
        else:
            end = remaining.rfind("\n", 0, max_chars)
            end = end + 1 if end >= 0 else remaining.rfind(" ", 0, max_chars) + 1
        if end <= 0 or not remaining[:end].strip():
            end = max_chars
        nodes.append(remaining[:end])
        remaining = remaining[end:]
    if remaining:
        nodes.append(remaining)
    return nodes


def _inline_text(tokens):
    parts = []
    for token in tokens or []:
        if token.type in {"text", "code_inline", "html_inline"}:
            parts.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif token.type == "image":
            parts.append(_inline_text(token.children) if token.children else token.content)
    return "".join(parts)


def normalize_qq_text(text):
    """Drop formatting syntax, retain visible text, and turn tables into labeled rows."""
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    parser = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    lines, lists, headers = [], [], []
    row, cell_type, prefix, table_rows = None, "", "", 0
    for token in parser.parse(source):
        kind = token.type
        if kind in {"ordered_list_open", "bullet_list_open"}:
            lists.append(int(token.attrGet("start") or 1) if kind == "ordered_list_open" else None)
        elif kind in {"ordered_list_close", "bullet_list_close"}:
            lists.pop()
            if not lists:
                lines.append("")
        elif kind == "list_item_open":
            prefix = "  " * (len(lists) - 1)
            if lists[-1] is None:
                prefix += "• "
            else:
                prefix += f"{lists[-1]}、"
                lists[-1] += 1
        elif kind == "list_item_close":
            prefix = ""
        elif kind == "table_open":
            headers = []
            table_rows = 0
        elif kind == "tr_open":
            row = []
        elif kind in {"th_open", "td_open"}:
            cell_type = kind
        elif kind == "tr_close":
            if cell_type == "th_open":
                headers = row
            else:
                lines.append("；".join(f"{headers[index]}：{value}" if index < len(headers) and headers[index]
                                       else value for index, value in enumerate(row)))
                table_rows += 1
            row = None
        elif kind == "table_close":
            if not table_rows and headers:
                lines.append("；".join(headers))
            lines.append("")
        elif kind == "inline":
            content = _inline_text(token.children)
            if row is not None:
                row.append(content)
            else:
                if prefix:
                    content = re.sub(r"^\[([ xX])\]\s+", lambda match: "✓ " if match[1].strip() else "☐ ", content)
                lines.append(prefix + content)
                prefix = ""
        elif kind in {"fence", "code_block"}:
            lines.append(prefix + token.content.rstrip("\n"))
            prefix = ""
        elif kind in {"paragraph_close", "heading_close", "hr"} and not lists:
            lines.append("")
    # Separate paragraphs without introducing Markdown block syntax.
    result = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    return "\n".join(result).strip()


def format_chat_reply(text, *, player_names, identity_names, aliases=()):
    """Resolve identities in already plain text; never apply this to provider payloads."""
    names = {str(raw).casefold(): str(nick or "该玩家") for raw, nick in player_names.items() if raw}
    identities = {str(identity): str(nick or "该成员") for identity, nick in identity_names.items() if identity}

    def tokens(values):
        return "(?:" + "|".join(re.escape(value) for value in sorted(set(values), key=len, reverse=True)) + ")"

    # ASCII boundaries allow Chinese-adjacent player mentions, but not words like "show".
    boundary_start, boundary_end = r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])"
    name_pattern = tokens(names) if names else r"(?!)"
    alias_pattern = tokens([*names, *names.values(), *map(str, aliases)])
    labels = (r"(?:game[_-]?)?(?:qq|role|user|player|group|message|hero|battle|memory|dataset|steam)[_-]?id"
              r"|qid|id|QQ(?:号|号码)?|群号|营地(?:ID|号)|角色ID|用户ID|消息ID|玩家ID|英雄ID|对局ID")
    id_field = re.compile(boundary_start + r"[\"']?(?:" + labels + r")[\"']?" + boundary_end
                          + r"\s*(?:[:：=]|为|是)?\s*[\"']?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+[\"']?", re.I)

    def visible_text(value):
        value = id_field.sub("", value)
        # Correct contradictory aliases such as raw_name(wrong_nickname) using configuration.
        value = re.sub(boundary_start + alias_pattern + r"\s*[（(]\s*(" + name_pattern + r")\s*[)）]",
                       lambda match: names[match[1].casefold()], value, flags=re.I)
        value = re.sub(boundary_start + "(" + name_pattern + r")\s*[（(]\s*" + alias_pattern + r"\s*[)）]",
                       lambda match: names[match[1].casefold()], value, flags=re.I)
        value = re.sub(boundary_start + name_pattern + boundary_end,
                       lambda match: names[match[0].casefold()], value, flags=re.I)
        if identities:
            value = re.sub(boundary_start + tokens(identities) + boundary_end,
                           lambda match: identities[match[0]], value)
        value = re.sub(r"[（(][\s,，;；、]*[)）]", "", value)
        value = re.sub(r"([（(])[\s,，;；、]+", r"\1", value)
        value = re.sub(r"[\s,，;；、]+([)）])", r"\1", value)
        value = re.sub(r"([,，;；、])[ \t]*[,，;；、]+", r"\1", value)
        return value

    # Keep ordinary URLs intact; discard identity-bearing URLs instead of corrupting them.
    parts = re.split(r"(https?://[^\s<>\"'，。；）]+)", str(text or ""))
    for index, part in enumerate(parts):
        if index % 2:
            if id_field.search(part) or any(identity in part for identity in identities):
                parts[index] = ""
        else:
            parts[index] = visible_text(part)
    result = "\n".join(line.strip(" \t,，;；、") for line in "".join(parts).splitlines()).strip()
    return result or "身份信息不在最终回复中展示。"
