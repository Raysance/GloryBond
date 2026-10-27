"""Role and preference data contracts, independent of the agent kernel."""

from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RoleSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=300)
    url: str = Field(max_length=2000)

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("角色来源必须是网页链接")
        return value


class VoiceExample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=600)
    reply: str = Field(min_length=1, max_length=1000)


class RoleVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: str = Field(default="", max_length=1200)
    habits: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=8
    )
    avoid: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=8
    )
    examples: list[VoiceExample] = Field(default_factory=list, max_length=5)


class RoleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=120)
    work: str = Field(default="", max_length=120)
    profile: str = Field(min_length=1, max_length=12000)
    kind: Literal["builtin", "web"] = "builtin"
    sources: list[RoleSource] = Field(default_factory=list, max_length=10)
    created_at: str = ""
    voice: RoleVoice | None = None


class ReplyPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    length: Literal["concise", "standard", "detailed"] = "concise"
    address: str = Field(default="", max_length=80)
    style: str = Field(default="", max_length=1000)


class GeneratedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    background: str = Field(min_length=1, max_length=3000)
    personality: str = Field(min_length=1, max_length=2000)
    speech_style: str = Field(min_length=1, max_length=2000)
    uncertainties: str = Field(default="", max_length=1500)
    voice: RoleVoice | None = None
