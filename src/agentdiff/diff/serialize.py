from __future__ import annotations

from agentdiff.model.types import Change, FileDiff, Hunk

_KIND_PREFIX = {"ctx": " ", "add": "+", "del": "-"}


def _hunk_header(hunk: Hunk) -> str:
    old_count = sum(1 for line in hunk.lines if line.kind in ("ctx", "del"))
    new_count = sum(1 for line in hunk.lines if line.kind in ("ctx", "add"))
    old = str(hunk.old_start) if old_count == 1 else f"{hunk.old_start},{old_count}"
    new = str(hunk.new_start) if new_count == 1 else f"{hunk.new_start},{new_count}"
    return f"@@ -{old} +{new} @@"


def _path_headers(fd: FileDiff, old: str, is_new: bool, is_deleted: bool) -> list[str]:
    if is_new:
        return ["--- /dev/null", f"+++ b/{fd.path}"]
    if is_deleted:
        return [f"--- a/{old}", "+++ /dev/null"]
    return [f"--- a/{old}", f"+++ b/{fd.path}"]


def _hunks_less_body(fd: FileDiff, old: str) -> list[str]:
    if fd.old_path is not None and fd.old_path != fd.path:
        return [
            "similarity index 100%",
            f"rename from {fd.old_path}",
            f"rename to {fd.path}",
        ]
    if (
        fd.old_mode is not None
        and fd.new_mode is not None
        and fd.old_mode != fd.new_mode
    ):
        return [f"old mode {fd.old_mode}", f"new mode {fd.new_mode}"]
    if fd.is_binary:
        return [f"Binary files a/{old} and b/{fd.path} differ"]
    return []


def _hunks_body(fd: FileDiff, old: str, is_new: bool, is_deleted: bool) -> list[str]:
    parts = _path_headers(fd, old, is_new, is_deleted)
    for hunk in fd.hunks:
        parts.append(_hunk_header(hunk))
        for line in hunk.lines:
            parts.append(f"{_KIND_PREFIX[line.kind]}{line.text}")
    return parts


def _serialize_file(fd: FileDiff) -> list[str]:
    old = fd.old_path or fd.path
    parts = [f"diff --git a/{old} b/{fd.path}"]
    is_new = fd.old_path is None and fd.new_mode is not None and fd.old_mode is None
    is_deleted = fd.old_path is None and fd.old_mode is not None and fd.new_mode is None
    if is_new:
        parts.append(f"new file mode {fd.new_mode}")
    elif is_deleted:
        parts.append(f"deleted file mode {fd.old_mode}")
    if fd.hunks:
        parts.extend(_hunks_body(fd, old, is_new, is_deleted))
    else:
        parts.extend(_hunks_less_body(fd, old))
    return parts


def serialize_unified_diff(change: Change) -> str:
    """Canonical git-style unified diff text for a Change. Inverse of the
    parser for well-formed diffs (R7).
    """
    blocks = ["\n".join(_serialize_file(fd)) for fd in change.files]
    return "\n\n".join(blocks) + "\n"
