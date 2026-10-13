"""Local image storage and provider projection; no image IO enters the runtime."""

import base64
import copy
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from uuid import uuid4
import warnings

from PIL import Image, UnidentifiedImageError

from agent_runtime import ImageInput


@dataclass(frozen=True)
class ImageLimits:
    max_images: int = 4
    max_image_bytes: int = 4194304
    max_total_bytes: int = 8388608
    max_context_bytes: int = 16777216
    max_side: int = 8192
    max_pixels: int = 32000000

    def __post_init__(self):
        if any(
            not isinstance(v, int) or isinstance(v, bool) or v < 1
            for v in vars(self).values()
        ):
            raise ValueError("图片限制必须为正整数")
        if self.max_context_bytes < self.max_total_bytes:
            raise ValueError("图片上下文预算不得小于单次输入预算")


class ImageStore:
    formats = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }

    def __init__(self, directory, limits=None):
        self.directory = Path(directory)
        self.limits = limits or ImageLimits()
        self._wire_references = {}

    def _path(self, image_id, suffix):
        if not re.fullmatch(r"[a-f0-9]{32}", image_id):
            raise ValueError("无效图片 ID")
        path = self.directory / (image_id + suffix)
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError("无效图片路径")
        return path

    def save(self, data, name=""):
        if not data or len(data) > self.limits.max_image_bytes:
            raise ValueError("图片为空或超过单张大小限制")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    mime = self.formats.get(image.format)
                    width, height = image.size
                    if not mime:
                        raise ValueError("仅支持 PNG、JPEG、WebP 和 GIF")
                    if (
                        max(width, height) > self.limits.max_side
                        or width * height > self.limits.max_pixels
                    ):
                        raise ValueError("图片分辨率超过限制")
                    image.verify()
                with Image.open(BytesIO(data)) as decoded:
                    decoded.load()
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise ValueError("图片文件无效或无法解码") from exc
        image_id = uuid4().hex
        filename = (str(name).replace("\\", "/").rsplit("/", 1)[-1])[:200] or "图片"
        metadata = {
            "id": image_id,
            "name": filename,
            "mime": mime,
            "width": width,
            "height": height,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(image_id, ".image").write_bytes(data)
        self._path(image_id, ".json").write_text(
            json.dumps(metadata, ensure_ascii=False)
        )
        return {**metadata, "url": "/api/images/" + image_id}

    def load(self, image_id):
        try:
            info = json.loads(self._path(image_id, ".json").read_text())
            path = self._path(image_id, ".image")
            if path.stat().st_size > self.limits.max_image_bytes:
                raise ValueError("图片大小超过限制")
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError("图片不存在或已清理，请重新上传") from exc
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise ValueError("图片内容已损坏，请重新上传")
        return info, data

    def inputs(self, image_ids):
        if len(image_ids) > self.limits.max_images:
            raise ValueError("图片数量超过限制")
        if len(set(image_ids)) != len(image_ids):
            raise ValueError("同一图片不应重复附加")
        result, size = [], 0
        for image_id in image_ids:
            info, data = self.load(image_id)
            size += len(data)
            result.append(ImageInput("attachment://" + image_id, name=info["name"]))
        if size > self.limits.max_total_bytes:
            raise ValueError("本次图片总大小超过限制")
        return tuple(result)

    def model_messages(self, messages):
        """Prioritize the newest images; retain explicit notices for omitted history."""
        projected = copy.deepcopy(messages)
        used, omitted = 0, 0
        for message in reversed(projected):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for index in reversed(range(len(content))):
                part = content[index]
                source = (part.get("image_url") or {}).get("url", "")
                if part.get("type") != "image_url" or not source.startswith(
                    "attachment://"
                ):
                    continue
                info, data = self.load(source.removeprefix("attachment://"))
                if used + len(data) > self.limits.max_context_bytes:
                    content[index] = {
                        "type": "text",
                        "text": "[历史图片超出本轮视觉上下文预算，未提供其像素；需要查看时请用户重新附图，不得猜测。]",
                    }
                    omitted += 1
                    continue
                used += len(data)
                data_url = (
                    "data:"
                    + info["mime"]
                    + ";base64,"
                    + base64.b64encode(data).decode()
                )
                part["image_url"]["url"] = data_url
                self._wire_references[hashlib.sha256(data_url.encode()).digest()] = (
                    source
                )
        return projected, {"image_bytes": used, "omitted_history_images": omitted}

    def project_event(self, event):
        """Keep image bytes once on disk; snapshots reference the exact owned blob."""
        converted = False

        def visit(value):
            nonlocal converted
            if isinstance(value, dict):
                result = {k: visit(v) for k, v in value.items()}
                image_url = result.get("image_url")
                if isinstance(image_url, dict):
                    source = image_url.get("url", "")
                    if isinstance(source, str) and source.startswith("data:image/"):
                        reference = self._wire_references.get(
                            hashlib.sha256(source.encode()).digest()
                        )
                        if reference:
                            image_url["url"] = reference
                            converted = True
                return result
            if isinstance(value, list):
                return [visit(v) for v in value]
            return value

        result = visit(event)
        if converted:
            result["data"]["image_payload_storage"] = (
                "local_attachment_refs; original bytes available at /api/images/{id}"
            )
        return result
