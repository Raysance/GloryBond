"""One bounded Parser Lite download. This file must not import the Bot entrypoint."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import shutil
import sys
from fractions import Fraction
import math
from urllib.parse import parse_qs, urlsplit


def video_budget(duration, request):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid media duration")
    # The duration-based target is soft; only the per-video limit is mandatory.
    return min(request["max_size_mb"] * 1024 * 1024,
               request["max_output_size_mb"] * 1_000_000,
               max(65536, int(duration * request["target_size_mb_per_5min"] * 1_000_000 / 300)))


async def run_media_command(*arguments):
    process = await asyncio.create_subprocess_exec(*arguments, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    output, _ = await process.communicate()
    if process.returncode:
        raise RuntimeError("Media processing failed")
    return output


async def prepare_video(source, request):
    """Prefer quick delivery; compress only to fit resolution or the video limit."""
    info = json.loads(await run_media_command("ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate", "-of", "json", str(source)))
    duration = float(info["format"]["duration"])
    budget = video_budget(duration, request)
    output_limit = request["max_output_size_mb"] * 1_000_000
    video = next(stream for stream in info["streams"] if stream.get("codec_type") == "video")
    audio = [stream for stream in info["streams"] if stream.get("codec_type") == "audio"]
    height = request["max_height"]
    width = 854 if height == 480 else 1280
    output = Path(request["directory"]) / "video.mp4"
    if (source.stat().st_size <= output_limit and video.get("codec_name") == "h264"
            and video["height"] <= height and video["width"] <= width
            and all(stream.get("codec_name") == "aac" for stream in audio)):
        shutil.copyfile(source, output)
        return {"ok": True}
    try:
        fps = max(1, min(30, float(Fraction(video.get("avg_frame_rate") or "30/1"))))
    except (ValueError, ZeroDivisionError):
        fps = 25
    audio_rate = 48000 if audio else 0
    video_rate = max(16000, int((budget - 16384) * 8 / duration * 0.92) - audio_rate)
    scale = f"scale=w='min({width},iw)':h='min({height},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
    for _ in range(2):
        await run_media_command("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "-1",
            "-vf", scale, "-r", str(fps or 25), "-c:v", "libx264", "-preset", "veryfast",
            "-threads", "2", "-b:v", str(video_rate), "-maxrate", str(video_rate),
            "-bufsize", str(video_rate * 2), "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-b:a", str(audio_rate or 48000), "-ac", "2", "-movflags", "+faststart", str(output))
        if 0 < output.stat().st_size <= output_limit:
            return {"ok": True}
        video_rate = max(16000, int(video_rate * 0.75))
    output.unlink(missing_ok=True)
    return {"ok": False, "code": "size"}


async def download(request):
    # Configure before importing the downloader, whose limits are initialized on import.
    from nonebot_plugin_parser_lite import configure

    configure(plite_max_size=request["max_size_mb"],
              plite_bili_video_quality=32 if request["max_height"] == 480 else 64,
              plite_bili_video_codes=["avc"], plite_max_comments=0, plite_max_retries=1,
              plite_bsb_api_base=None, plite_media_speedup_rules=[])
    from nonebot_plugin_parser_lite.parsers.bilibili import BilibiliParser
    from nonebot_plugin_parser_lite.download import StreamDownloader
    from nonebot_plugin_parser_lite.exception import SizeLimitException

    parsed = urlsplit(request["url"])
    identifier = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    page = int(parse_qs(parsed.query).get("p", ["1"])[0])
    parser, downloader = BilibiliParser(), StreamDownloader()
    try:
        kwargs = {"bvid": identifier} if identifier.startswith("BV") else {"avid": int(identifier[2:])}
        video, audio = await parser.get_download_streams(**kwargs, page_index=page - 1)
        streams = [video, audio] if audio else [video]
        sizes = await asyncio.gather(*(downloader.head_size(stream.url, ext_headers=parser.headers) for stream in streams))
        if sum(size or 0 for size in sizes) > request["max_size_mb"] * 1024 * 1024:
            return {"ok": False, "code": "size"}
        options = {"cache_key": f"glorybond:{identifier}:{page}", "ext_headers": parser.headers}
        if audio:
            path = await downloader.download_av_and_merge(
                video_url=video.url, audio_url=audio.url,
                video_fallback_urls=video.backup_url, audio_fallback_urls=audio.backup_url, **options)
        else:
            path = await downloader.download_video(url=video.url, fallback_urls=video.backup_url, **options)
        if path.suffix.lower() != ".mp4":
            from anyio import Path as AsyncPath
            from nonebot_plugin_parser_lite.utils.ffmpeg import FFmpeg
            path = await FFmpeg.remux_to_mp4(path, AsyncPath(request["directory"]) / "remux.mp4")
        source = Path(str(path))
        if not 0 < source.stat().st_size <= request["max_size_mb"] * 1024 * 1024:
            return {"ok": False, "code": "size"}
        return await prepare_video(source, request)
    except SizeLimitException:
        return {"ok": False, "code": "size"}
    finally:
        await parser.aclose()
        await downloader.aclose()


def main():
    request = json.loads(sys.stdin.read(8192))
    os.environ["PARSER_LITE_BASE_DIR"] = str(Path(request["directory"]) / "parser-lite")
    result = {"ok": False, "code": "unavailable"}
    try:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            result["code"] = "dependency"
        else:
            with contextlib.redirect_stdout(sys.stderr):
                result = asyncio.run(download(request))
    except ImportError:
        result["code"] = "dependency"
    except Exception:
        pass  # Provider text, signed URLs and plugin diagnostics stay out of replies/logs.
    print(json.dumps(result))


if __name__ == "__main__":
    main()
