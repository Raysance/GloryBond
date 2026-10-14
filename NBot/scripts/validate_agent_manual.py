"""Validate manual routing, document coverage and curated AST source locations."""
import json
from pathlib import Path
import sys

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_console.bot_manual import BotManual, load_manual_documents


def main():
    catalog = json.loads((ROOT / "shared/agent/manual/catalog.json").read_text())
    documents = load_manual_documents(ROOT, catalog)
    reader = BotManual(ROOT, catalog, documents)
    known_paths = {str(path.relative_to(ROOT)) for path in (ROOT / "shared/agent/manual/chapters").glob("*.md")}
    if set(documents) != known_paths:
        raise ValueError("手册文件未被目录声明：" + ", ".join(sorted(known_paths - set(documents))))
    for path, content in documents.items():
        declared = {node["document"].get("heading") for node in catalog["topics"]
                    if node.get("document", {}).get("path") == path}
        if None in declared:
            continue
        tokens = MarkdownIt("commonmark").parse(content)
        headings = {tokens[i + 1].content for i, token in enumerate(tokens)
                    if token.type == "heading_open" and token.tag in {"h2", "h3"}}
        if headings != declared:
            raise ValueError("手册小节未完整纳入目录：" + path)
    sources = set()
    for node in catalog["topics"]:
        for reference in reader._related(node["id"], "code"):
            identity = (reference["path"], reference["symbol"], reference.get("focus"))
            if identity not in sources:
                reader._source(reference, reader.limits["max_code_chars"])
                sources.add(identity)
    print(f"Validated {len(reader.topics)} nodes, {len(documents)} documents, {len(sources)} source locations")


if __name__ == "__main__":
    main()
