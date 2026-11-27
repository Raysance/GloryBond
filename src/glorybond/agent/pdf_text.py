"""Disposable, bounded PDF text extraction; invoked by the webpage adapter."""
import io
import json
import logging
import resource
import sys


def extract(raw, start, count, page_chars, total_chars):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        return {"error": "PDF 已加密，无法提取文字"}
    total_pages = len(reader.pages)
    if start > total_pages:
        return {"error": f"PDF 页码超出范围，文件共 {total_pages} 页"}
    pages, links, remaining, link_chars = [], [], total_chars, 0
    for index in range(start - 1, min(start - 1 + count, total_pages)):
        if remaining <= 0:
            break
        page = reader.pages[index]
        text = (page.extract_text() or "").strip()
        size = min(page_chars, remaining)
        pages.append({"page": index + 1, "text": text[:size], "truncated": len(text) > size,
                      "text_available": bool(text)})
        remaining -= min(len(text), size)
        for ref in page.get("/Annots", [])[:100]:
            annotation = ref.get_object()
            action = annotation.get("/A")
            if action is not None:
                action = action.get_object()
                if action.get("/S") == "/URI" and isinstance(action.get("/URI"), str):
                    uri = action["/URI"]
                    if len(uri) <= 2048 and len(links) < 50 and link_chars + len(uri) <= 6000:
                        links.append((uri, f"PDF 第 {index + 1} 页链接"))
                        link_chars += len(uri)
    end = pages[-1]["page"] if pages else start - 1
    return {"title": str((reader.metadata or {}).get("/Title") or "")[:300],
            "page_count": total_pages, "start_page": start, "end_page": end,
            "next_page": end + 1 if end < total_pages else None,
            "pages": pages, "truncated": any(page["truncated"] for page in pages),
            "text_available": any(page["text_available"] for page in pages),
            "extraction": "text_only_no_ocr", "link_entries": links,
            "notice": "仅提取指定页的文字层，空白或扫描页未做 OCR；表格与复杂排版可能丢失布局。"}


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    logging.disable(logging.CRITICAL)
    try:
        args = [int(value) for value in sys.argv[1:]]
        raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("oversized input")
        result = extract(raw, *args)
    except Exception:
        result = {"error": "PDF 文字解析失败，文件可能损坏或超过资源限制"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
