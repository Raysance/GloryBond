"""Backward-compatible KPL collector imports.

The authoritative acquisition flow lives in :mod:`glorybond.integrations.kpl`. New code should
import its two JSON entry points directly.
"""

from glorybond.integrations.kpl import get_full_match_list
from glorybond.integrations.kpl import get_match_content
from glorybond.integrations.kpl import get_match_detail_json
from glorybond.integrations.kpl import get_match_list_json

__all__ = [
    "get_match_list_json",
    "get_match_detail_json",
    "get_full_match_list",
    "get_match_content",
]
