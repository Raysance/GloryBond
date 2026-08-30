"""Role profile primitives for the chat prompt pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatRole:
    """A portable role definition with no dependency on the bot runtime."""

    key: str
    display_name: str
    profile: str

    def render_profile(self) -> str:
        """Render only the selected character's identity and mannerisms."""
        return f"\n【角色信息：{self.display_name}】\n{self.profile.strip()}\n"
