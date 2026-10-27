def iter_simple_emoji(text: str):
    """Yield (kind, value) where kind is 'text' or 'emoji'.

    This is a minimal splitter: treats any non-BMP codepoint as emoji,
    skips variation selectors, and does not attempt full grapheme cluster parsing.
    """
    buf = []
    for ch in str(text):
        cp = ord(ch)
        if cp in (0xFE0F, 0xFE0E):
            continue
        if cp > 0xFFFF:
            if buf:
                yield ("text", "".join(buf))
                buf = []
            yield ("emoji", ch)
        else:
            buf.append(ch)
    if buf:
        yield ("text", "".join(buf))


def twemoji_codepoint(emoji_char: str):
    cp = ord(emoji_char)
    return f"{cp:x}"


def twemoji_urls(codepoint: str):
    return [
        f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{codepoint}.png",
        f"https://twemoji.maxcdn.com/v/latest/72x72/{codepoint}.png",
        f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{codepoint}.png",
    ]


def ensure_twemoji_png(emoji_char: str, cache_dir: str):
    import os
    try:
        from ..zfile import ensure_dir, download_url_to_file, file_exist
    except Exception as e:
        import requests

        def ensure_dir(p):
            if not p:
                raise Exception("ensure_dir_error: empty dir_path")
            os.makedirs(p, exist_ok=True)
            return p

        def file_exist(p):
            return os.path.exists(p)

        def download_url_to_file(url: str, dst_file: str):
            ensure_dir(os.path.dirname(dst_file))
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(dst_file, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)
            return dst_file

    ensure_dir(cache_dir)
    code = twemoji_codepoint(emoji_char)
    dst_file = os.path.join(cache_dir, f"{code}.png")
    if file_exist(dst_file):
        return dst_file

    last_err = None
    for url in twemoji_urls(code):
        try:
            download_url_to_file(url, dst_file)
            return dst_file
        except Exception as e:
            last_err = e
            continue
    raise Exception(f"twemoji_download_failed: {emoji_char} {code} {repr(last_err)}")


def draw_text_with_emoji(img, xy, text: str, font, fill, emoji_size: int, cache_dir: str):
    import os
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(img)
    x, y = xy
    ascent, descent = font.getmetrics()
    baseline = y + ascent

    for kind, val in iter_simple_emoji(text):
        if kind == "text":
            draw.text((x, y), val, fill=fill, font=font)
            x += draw.textlength(val, font=font)
        else:
            png = ensure_twemoji_png(val, cache_dir)
            em = Image.open(png).convert("RGBA")
            em = em.resize((emoji_size, emoji_size), Image.LANCZOS)
            em_y = int(baseline - emoji_size + 2)
            img.paste(em, (int(x), em_y), em)
            x += emoji_size
    return x, y
