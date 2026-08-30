"""Role profile primitives for the chat prompt pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatRole:
    """A portable role definition with no dependency on the bot runtime."""

    key: str
    display_name: str
    prompt: str

    def render_prompt(self) -> str:
        return f"\n【角色扮演：{self.display_name}】\n{self.prompt.strip()}\n"
