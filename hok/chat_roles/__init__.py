"""Registry for portable, independently maintained chat roles."""

from .base import ChatRole
from .makise_kurisu import ROLE as MAKISE_KURISU


_ROLES = {}


def register_role(role: ChatRole, *, replace: bool = False) -> None:
    """Register a role supplied by this package or an external extension."""
    if not isinstance(role, ChatRole):
        raise TypeError("role must be a ChatRole")
    role_key = role.key.strip()
    if not role_key or not role.prompt.strip():
        raise ValueError("role key and prompt must not be empty")
    if role_key in _ROLES and not replace:
        raise ValueError(f"chat role already registered: {role_key}")
    _ROLES[role_key] = role


def get_role(role_key: str):
    """Return a registered role, or ``None`` when role play is disabled/unknown."""
    return _ROLES.get(str(role_key or "").strip())


def build_role_prompt(role_key: str) -> str:
    role = get_role(role_key)
    return role.render_prompt() if role else ""


def list_roles():
    return tuple(_ROLES.values())


__all__ = ["ChatRole", "build_role_prompt", "get_role", "list_roles", "register_role"]


register_role(MAKISE_KURISU)
