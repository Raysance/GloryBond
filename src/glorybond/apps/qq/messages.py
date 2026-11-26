"""Framework-independent values passed to the QQ message outlet."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoWithMetadata:
    text: str
    video: str
