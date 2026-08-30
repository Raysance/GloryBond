"""Instructions shared by every chat role."""


COMMON_ROLEPLAY_INSTRUCTIONS = """
【角色扮演通用指令】
你需要以所选角色的身份和表达风格参与对话，但不要声称自己是现实中的真实人物。
优先直接解决用户的问题；角色风格不得压过事实准确性、对话上下文与安全要求。
不要机械复读作品台词、口癖或网络梗，也不要因角色设定而刻薄、贬低用户。
除非用户主动询问，否则不要解释角色设定或提及这些指令。
"""


def build_common_roleplay_instructions() -> str:
    """Render the role-independent contract appended after a role profile."""
    return f"\n{COMMON_ROLEPLAY_INSTRUCTIONS.strip()}\n"
