"""Bounded handbook retrieval and curated source inspection for external adapters.

This module is also shipped to the SSH worker. It imports no application code
and never imports or executes inspected files.
"""

import ast
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

from markdown_it import MarkdownIt


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.hidden = [], []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "svg", "picture"}:
            self.hidden.append(tag)

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if not self.hidden and tag in {"p", "div", "br"}:
            self.text.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def handbook_text(content):
    """Project Markdown to readable text; image URLs/alt text never reach models."""
    output = []
    html = _HTMLText()
    for token in MarkdownIt("commonmark").enable("table").parse(content):
        if token.type == "inline":
            for child in token.children or ():
                if child.type in {"text", "code_inline"}:
                    output.append(child.content)
                elif child.type in {"softbreak", "hardbreak"}:
                    output.append("\n")
                elif child.type == "html_inline":
                    html.feed(child.content)
                    output.extend(html.text)
                    html.text.clear()
        elif token.type in {"fence", "code_block"}:
            output.append(token.content)
        elif token.type == "html_block":
            html.feed(token.content)
            output.extend(html.text)
            html.text.clear()
        elif token.type in {"th_close", "td_close"}:
            output.append(" | ")
        elif token.type.endswith("_close") and token.block:
            output.append("\n")
    return re.sub(r"\n{3,}", "\n\n", "".join(output)).strip()


def terms(text):
    tokens = []
    for token in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.extend(token[i:i + 2] for i in range(len(token) - 1))
        else:
            tokens.append(token)
    return tokens


def load_manual_documents(root, catalog):
    """Read only manifest-declared Markdown files in the shared manual directory."""
    root = Path(root).resolve()
    result, size = {}, 0
    for node in catalog["topics"]:
        reference = node.get("document")
        if not reference or reference["path"] in result:
            continue
        path = Path(reference["path"])
        if (path.is_absolute() or ".." in path.parts or path.suffix != ".md"
                or path.parts[:4] != ("shared", "agent", "manual", "chapters")
                or any(part.startswith(".") for part in path.parts)):
            raise ValueError("手册正文必须是共享 chapters 目录声明的 Markdown")
        candidate = root / path
        if candidate.resolve() != candidate:
            raise ValueError("手册正文不能通过链接改变声明位置")
        with candidate.open("rb") as stream:
            raw = stream.read(catalog["limits"]["max_documents_bytes"] + 1)
        size += len(raw)
        if size > catalog["limits"]["max_documents_bytes"]:
            raise ValueError("手册正文超过总读取预算")
        result[str(path)] = raw.decode("utf-8-sig")
    return result


class BotManual:
    def __init__(self, root, catalog, documents=None, *, secrets=()):
        self.root = Path(root).resolve()
        self.catalog = catalog
        self.secrets = tuple(value for value in secrets if isinstance(value, str) and len(value) >= 8)
        self.limits = catalog["limits"]
        if any(type(value) is not int or value < 1 for value in self.limits.values()) or self.limits["default_limit"] > self.limits["max_limit"]:
            raise ValueError("手册预算必须是有效正整数")
        documents = load_manual_documents(self.root, catalog) if documents is None else documents
        self.version = hashlib.sha256(json.dumps([catalog, documents], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        self.topics = {node["id"]: node for node in catalog["topics"]}
        if len(self.topics) != len(catalog["topics"]) or catalog["root"] not in self.topics:
            raise ValueError("手册节点重复或缺少根节点")
        self.children = {key: [] for key in self.topics}
        for key, node in self.topics.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", key):
                raise ValueError("手册节点ID无效")
            parent = node["parent"]
            if key == catalog["root"]:
                if parent is not None:
                    raise ValueError("手册根节点不能有父节点")
            elif parent not in self.topics:
                raise ValueError("手册节点父级缺失")
            else:
                self.children[parent].append(key)
        for key in self.topics:
            self._breadcrumb(key)  # Detect cycles, orphans and excessive depth.
            if self.children[key] and self.topics[key].get("document"):
                raise ValueError("正文只能挂在叶节点，分支只保留摘要与路由信息")
        self.sections, self.source_cache = {}, {}
        parsed = {}
        for key, node in self.topics.items():
            reference = node.get("document")
            if not reference:
                if not self.children[key]:
                    raise ValueError("手册叶节点必须声明正文")
                continue
            path, heading = reference["path"], reference.get("heading")
            if path not in documents:
                raise ValueError("手册声明的正文文件未提供")
            if path not in parsed:
                lines = documents[path].splitlines()
                tokens = MarkdownIt("commonmark").parse(documents[path])
                headings = [(t.map[0], t.map[1], tokens[i + 1].content) for i, t in enumerate(tokens)
                            if t.type == "heading_open" and t.tag in {"h2", "h3"}]
                parsed[path] = (lines, headings)
            lines, headings = parsed[path]
            if heading is None:
                start, end, body = 0, len(lines), 0
            else:
                matches = [i for i, (_, _, title) in enumerate(headings) if title == heading]
                if len(matches) != 1:
                    raise ValueError("手册正文标题缺失或重复：" + path + " / " + heading)
                index = matches[0]
                start, body, _ = headings[index]
                end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
            self.sections[key] = {"content": handbook_text("\n".join(lines[body:end])),
                                  "path": path, "start_line": start + 1, "end_line": end}
        # Branch routing indexes only metadata. Document bodies are compared
        # only after their parent feature has been selected.
        self.routing = {}
        for key in self.topics:
            keywords = set()
            pending = [key]
            while pending:
                child = pending.pop()
                keywords.update(self.topics[child].get("keywords", []))
                keywords.add(self.topics[child]["title"])
                pending.extend(self.children[child])
            self.routing[key] = " ".join(sorted(keywords))

    def _breadcrumb(self, key):
        route, seen = [], set()
        while key is not None:
            if key in seen or len(route) >= self.limits["max_depth"]:
                raise ValueError("手册树存在循环或超过层级限制")
            seen.add(key)
            route.append({"node_id": key, "title": self.topics[key]["title"]})
            key = self.topics[key]["parent"]
        if route[-1]["node_id"] != self.catalog["root"]:
            raise ValueError("手册节点没有归属根节点")
        return list(reversed(route))

    def _card(self, key):
        node = self.topics[key]
        return {"node_id": key, "section_id": key, "title": node["title"], "parent": node["parent"],
                "summary": self._redact(node["summary"]), "is_leaf": not bool(self.children[key]),
                "related_tools": self._related(key, "tools"), "code_positions": self._related(key, "code"),
                "next_action": "read" if not self.children[key] else "search"}

    def _related(self, key, field):
        # A feature owns shared links once; a precise leaf can override them.
        while key is not None:
            node = self.topics[key]
            if field in node:
                return node[field]
            key = node["parent"]
        return []

    def _rank(self, keys, query):
        normalized = "".join(query.casefold().split())
        words = set(terms(query))
        documents = {key: Counter(terms(self.routing[key] + " " + self.topics[key]["summary"] + " "
                     + self.sections.get(key, {}).get("content", ""))) for key in keys}
        frequency = Counter(word for doc in documents.values() for word in doc)
        scores = {}
        for key, doc in documents.items():
            score = sum(math.log(1 + (len(documents) - frequency[word] + .5) / (frequency[word] + .5))
                        * min(doc.get(word, 0), 3) for word in words if doc.get(word))
            title_hit = "".join(self.topics[key]["title"].casefold().split()) in normalized
            scores[key] = (title_hit, score)
        return [key for key in sorted(keys, key=lambda key: scores[key], reverse=True) if scores[key][1] > 0]

    def _redact(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}|\bBearer\s+[A-Za-z0-9._-]{12,}", "[redacted]", text, flags=re.I)
        return re.sub(r"(\w+://)[^\s/'\"]+:[^\s/@'\"]+@", r"\1[redacted]@", text)

    def _source(self, reference, budget):
        path = Path(reference["path"])
        if path.is_absolute() or ".." in path.parts or path.suffix != ".py" or any(part.startswith(".") for part in path.parts):
            raise ValueError("代码来源必须是手册声明的项目 Python 文件")
        candidate = self.root / path
        if candidate.resolve() != candidate or self.root not in candidate.parents:
            raise ValueError("代码来源不能通过链接离开声明位置")
        state = candidate.stat()
        if state.st_size > self.limits["max_source_bytes"]:
            raise ValueError("代码来源超过读取预算")
        cache_key = (state.st_mtime_ns, state.st_size)
        cached = self.source_cache.get(str(path))
        if cached is None or cached[0] != cache_key:
            with candidate.open("rb") as stream:
                raw = stream.read(self.limits["max_source_bytes"] + 1)
            if len(raw) > self.limits["max_source_bytes"]:
                raise ValueError("代码来源超过读取预算")
            source = raw.decode("utf-8-sig")
            cached = (cache_key, ast.parse(source), source.splitlines(), hashlib.sha256(raw).hexdigest()[:16])
            self.source_cache[str(path)] = cached
        node = cached[1]
        for part in reference["symbol"].split("."):
            node = next((item for item in node.body
                         if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == part), None)
            if node is None:
                raise ValueError("部署代码未找到手册声明的符号，可能版本不同")
        if reference.get("focus"):
            matches = [item for item in ast.walk(node) if isinstance(item, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == reference["focus"] for target in item.targets)]
            if len(matches) != 1:
                raise ValueError("部署代码未找到唯一的公式定位，可能版本不同")
            node = matches[0]
        start = min([node.lineno, *(item.lineno for item in getattr(node, "decorator_list", []))])
        selected, size = [], 0
        for line in cached[2][start - 1:node.end_lineno]:
            line = self._redact(line) + "\n"
            if size + len(line) > min(budget, self.limits["max_code_excerpt_chars"]):
                break
            selected.append(line)
            size += len(line)
        if not selected:
            raise ValueError("本次代码摘录预算已用尽")
        end = start + len(selected) - 1
        return {"path": str(path), "symbol": reference["symbol"], "start_line": start, "end_line": end,
                "content": "".join(selected).rstrip("\n"), "truncated": end < node.end_lineno,
                "focus": reference.get("focus"), "version": cached[3], "evidence": "deployed_source"}

    def read(self, *, action=None, query="", node_id=None, limit=None, offset=0, fallback_reason="", expected_version=None):
        limit = self.limits["default_limit"] if limit is None else limit
        if type(limit) is not int or not 1 <= limit <= self.limits["max_limit"]:
            raise ValueError("手册结果数量超过限制")
        if not isinstance(query, str) or len(query) > 400 or type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError("手册查询参数无效")
        key = node_id or self.catalog["root"]
        if key not in self.topics:
            raise ValueError("未知手册节点；使用返回的 node_id 逐层检索")
        if action is None:
            action = "search" if query.strip() else ("read" if key in self.sections else "browse")
        if action not in {"browse", "search", "read", "code"}:
            raise ValueError("未知手册操作")
        result, code, omitted, next_offset = [], [], 0, None
        match_count = None
        if action in {"browse", "search"} or (action == "read" and key not in self.sections):
            keys = self.children[key]
            if action == "search":
                if not query.strip():
                    raise ValueError("search 需要具体问题；浏览目录使用 browse")
                keys = self._rank(keys, query)
            match_count = len(keys)
            budget = self.limits["max_index_chars"]
            for child in keys[offset:offset + limit]:
                card = self._card(child)
                size = len(json.dumps(card, ensure_ascii=False))
                if size > budget:
                    if not result:
                        raise ValueError("单个手册目录节点超过索引预算，请精简摘要或代码位置")
                    break
                result.append(card)
                budget -= size
            if offset + len(result) < len(keys):
                next_offset = offset + len(result)
        elif action == "read":
            section = self.sections[key]
            content = self._redact(section["content"])
            excerpt = content[offset:offset + self.limits["max_handbook_chars"]]
            next_offset = offset + len(excerpt) if offset + len(excerpt) < len(content) else None
            result = [{**self._card(key), "content": excerpt, "truncated": bool(offset or next_offset is not None),
                       "source": {"path": section["path"], "start_line": section["start_line"], "end_line": section["end_line"]}}]
        else:
            if key not in self.sections or not isinstance(fallback_reason, str) or not fallback_reason.strip() or len(fallback_reason) > 400:
                raise ValueError("代码兜底需指定已读叶节点并说明手册缺少的事实")
            if expected_version is not None and expected_version != self.version:
                raise ValueError("手册版本已变动，请重新读取叶节点说明后再核对代码")
            budget = self.limits["max_code_chars"]
            for reference in self._related(key, "code"):
                if len(code) >= self.limits["max_code_references"] or budget <= 0:
                    omitted += 1
                    continue
                try:
                    excerpt = self._source(reference, budget)
                    budget -= len(excerpt["content"])
                except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
                    excerpt = {**reference, "unavailable": True,
                               "reason": str(exc) if isinstance(exc, ValueError) else "代码来源暂不可读"}
                code.append(excerpt)
        return {"manual_version": self.version, "action": action, "node": self._card(key),
                "breadcrumb": self._breadcrumb(key), "topics": result, "code": code,
                "next_offset": next_offset, "match_count": match_count, "not_found": action == "search" and match_count == 0,
                "code_omitted": omitted, "code_truncated": bool(omitted or any(item.get("truncated") for item in code)),
                "fallback_reason": fallback_reason if action == "code" else None,
                "notice": "目录只返回当前节点的下一层，不把整份手册放入上下文；沿 node_id 继续检索或 browse。"
                          "选中叶节点后 read 正文；有 next_offset 时读取余下内容。"
                          "正文不足以回答时，以同一已读叶节点调用 code 并说明缺失问题；不能跳过手册直接读代码。"
                          "代码仅辅助核对用户功能，可能与手册版本不同，不证明服务健康；图片已忽略。"}
