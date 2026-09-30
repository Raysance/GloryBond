"""Registry for portable, independently maintained chat roles."""

from .base import ChatRole
from .custom import build_custom_role_prompt, normalize_custom_role_record
from .instructions import build_common_roleplay_instructions
from .makise_kurisu import ROLE as MAKISE_KURISU


_ROLES = {}


def register_role(role: ChatRole, *, replace: bool = False) -> None:
    """Register a role supplied by this package or an external extension."""
    if not isinstance(role, ChatRole):
        raise TypeError("role must be a ChatRole")
    role_key = role.key.strip()
    if not role_key or not role.profile.strip():
        raise ValueError("role key and profile must not be empty")
    if role_key in _ROLES and not replace:
        raise ValueError(f"chat role already registered: {role_key}")
    _ROLES[role_key] = role


def get_role(role_key: str):
    """Return a registered role, or ``None`` when role play is disabled/unknown."""
    return _ROLES.get(str(role_key or "").strip())


def build_role_prompt(role_key: str) -> str:
    role = get_role(role_key)
    if not role:
        return ""
    role_prompt = role.render_profile()
    role_prompt += build_common_roleplay_instructions()
    return role_prompt


def list_roles():
    return tuple(_ROLES.values())


__all__ = ["ChatRole", "build_custom_role_prompt", "build_role_prompt", "get_role", "list_roles",
           "normalize_custom_role_record", "register_role"]


register_role(MAKISE_KURISU)
