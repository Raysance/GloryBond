"""Render model Markdown as QQ plain text without changing literal code/math."""

from markdown_it import MarkdownIt
import re


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
