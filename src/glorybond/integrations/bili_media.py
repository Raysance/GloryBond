"""Constrained Bilibili video references and Parser Lite worker transport."""

import html
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from urllib.parse import parse_qs, urljoin, urlsplit

import requests


class BiliVideoError(RuntimeError):
    MESSAGES = {
        "invalid": "未识别到有效的 B站视频地址。",
        "unavailable": "B站视频暂时无法下载，可能已失效、受访问限制或接口暂时不可用。",
        "timeout": "B站视频下载超时，请稍后再试。",
        "size": "B站视频超过下载或发送大小上限。",
        "busy": "B站视频下载繁忙，请稍后再试。",
        "dependency": "B站视频下载组件暂不可用。",
        "disabled": "B站视频下载已关闭。",
    }

    def __init__(self, code):
        self.code = code if code in self.MESSAGES else "unavailable"
        super().__init__(self.MESSAGES[self.code])


_ID = r"(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,19})"
_URL = re.compile(r"https?://[^\s<>\"'，。！？、（）]+|(?<![\w./@-])(?:www\.|m\.)?bilibili\.com/[^\s<>\"'，。！？、（）]+|(?<![\w./@-])(?:b23\.tv|bili2233\.cn)/[A-Za-z0-9]+")
_BARE_ID = re.compile(r"(?<![A-Za-z0-9_/.])" + _ID + r"(?![A-Za-z0-9_])")
_VIDEO_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}
_SHORT_HOSTS = {"b23.tv", "bili2233.cn"}


def normalize_video_reference(value):
    value = html.unescape(str(value or "")).strip().rstrip(".,;!?)】]")
    if re.fullmatch(_ID, value):
        return "https://www.bilibili.com/video/" + value
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password or parsed.port:
            return None
    except ValueError:
        return None
    if parsed.hostname in _SHORT_HOSTS and re.fullmatch(r"/[A-Za-z0-9]{1,64}/?", parsed.path):
        return "https://" + parsed.hostname + parsed.path.rstrip("/")
    if parsed.hostname not in _VIDEO_HOSTS:
        return None
    match = re.fullmatch(r"/(?:video/)?(" + _ID + r")/?", parsed.path)
    if not match:
        return None
    page = parse_qs(parsed.query).get("p", ["1"])[0]
    if not page.isascii() or not page.isdecimal() or not 1 <= int(page) <= 1000:
        return None
    url = "https://www.bilibili.com/video/" + match[1]
    return url + (f"?p={int(page)}" if int(page) > 1 else "")


def video_references(text, *, limit=3):
    """Match explicit URLs and bare IDs; never mine IDs from unrelated URLs."""
    text = html.unescape(str(text or ""))[:32768]
    found = []
    spans = []
    for match in _URL.finditer(text):
        spans.append(match.span())
        if reference := normalize_video_reference(match[0]):
            found.append((match.start(), reference))
    for match in _BARE_ID.finditer(text):
        if not any(start <= match.start() < end for start, end in spans):
            found.append((match.start(), normalize_video_reference(match[0])))
    return list(dict.fromkeys(value for _, value in sorted(found) if value))[:limit]


def resolve_video_reference(reference):
    """Follow only Bilibili short-link redirects, without fetching their bodies."""
    reference = normalize_video_reference(reference)
    if not reference:
        raise BiliVideoError("invalid")
    try:
        with requests.Session() as session:
            for _ in range(4):
                if urlsplit(reference).hostname in _VIDEO_HOSTS:
                    return reference
                with session.get(reference, allow_redirects=False, stream=True, timeout=10) as response:
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        raise BiliVideoError("unavailable")
                    target = normalize_video_reference(urljoin(reference, response.headers.get("Location", "")))
                if not target:
                    raise BiliVideoError("invalid")
                reference = target
    except requests.Timeout:
        raise BiliVideoError("timeout") from None
    except requests.RequestException:
        raise BiliVideoError("unavailable") from None
    raise BiliVideoError("invalid")


def download_bili_video(reference, directory, *, max_size_mb=90, timeout_seconds=180,
                       max_height=480, target_size_mb_per_5min=10, max_output_size_mb=50):
    """Run only the Bilibili portion of the pinned standalone dependency."""
    reference = normalize_video_reference(reference)
    if not reference or urlsplit(reference).hostname not in _VIDEO_HOSTS:
        raise BiliVideoError("invalid")
    directory = Path(directory).resolve()
    worker = Path(__file__).with_name("bili_media_worker.py")
    request = json.dumps({"url": reference, "directory": str(directory), "max_size_mb": max_size_mb,
                          "max_height": max_height, "target_size_mb_per_5min": target_size_mb_per_5min,
                          "max_output_size_mb": max_output_size_mb})
    # A separate process contains plugin logs, temporary state and FFmpeg children.
    with subprocess.Popen([sys.executable, str(worker)], cwd=directory, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                          start_new_session=True) as process:
        try:
            stdout, _ = process.communicate(request, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise BiliVideoError("timeout") from None
    try:
        result = json.loads(stdout)
    except (ValueError, TypeError):
        raise BiliVideoError("unavailable") from None
    if process.returncode or not result.get("ok"):
        raise BiliVideoError(result.get("code", "unavailable"))
    path = directory / "video.mp4"
    output_limit = min(max_size_mb * 1024 * 1024, max_output_size_mb * 1_000_000)
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        raise BiliVideoError("unavailable")
    if path.stat().st_size > output_limit:
        raise BiliVideoError("size")
    metadata_path = directory / "metadata.json"
    if not metadata_path.is_file() or metadata_path.is_symlink() or metadata_path.stat().st_size > 8192:
        raise BiliVideoError("unavailable")
    return path
