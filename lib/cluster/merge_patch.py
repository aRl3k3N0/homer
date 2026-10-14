"""
JSON Merge Patch (RFC 7396) for dict updates.

merge_patch(target, patch) -> new dict
    - dict values are merged recursively
    - non-dict values replace
    - None values delete the key

Used to safely apply concurrent updates where each side touched
different keys.
"""

from __future__ import annotations

from typing import Any


def merge_patch(target: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        return patch

    if not isinstance(target, dict):
        target = {}

    result = dict(target)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def diff_patch(before: dict, after: dict) -> dict:
    """
    Produce a minimal patch that transforms `before` into `after`.
    Used when saving user edits: instead of writing the whole config,
    we send only the changed keys.
    """
    patch: dict[str, Any] = {}
    for key, value in after.items():
        if isinstance(value, dict) and isinstance(before.get(key), dict):
            sub = diff_patch(before[key], value)
            if sub:
                patch[key] = sub
        else:
            if before.get(key) != value:
                patch[key] = value

    for key in before:
        if key not in after:
            patch[key] = None
    return patch
