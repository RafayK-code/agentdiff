from __future__ import annotations

from agentdiff.model.types import Change, FileDiff, Hunk

_KIND_PREFIX = {"ctx": " ", "add": "+", "del": "-"}


def _hunk_header(hunk: Hunk) -> str:
    old_count = sum(1 for line in hunk.lines if line.kind in ("ctx", "del"))
    new_count = sum(1 for line in hunk.lines if line.kind in ("ctx", "add"))
    old = str(hunk.old_start) if old_count == 1 else f"{hunk.old_start},{old_count}"
    new = str(hunk.new_start) if new_count == 1 else f"{hunk.new_start},{new_count}"
    return f"@@ -{old} +{new} @@"


def _serialize_file(fd: FileDiff) -> list[str]:
    old = fd.old_path or fd.path
    parts = [f"diff --git a/{old} b/{fd.path}"]
    is_new = fd.old_path is None and fd.new_mode is not None and fd.old_mode is None
    is_deleted = fd.old_path is None and fd.old_mode is not None and fd.new_mode is None
    if is_new:
        parts.append(f"new file mode {fd.new_mode}")
    elif is_deleted:
        parts.append(f"deleted file mode {fd.old_mode}")
    if not fd.hunks:
        if fd.old_path is not None and fd.old_path != fd.path:
            parts.append("similarity index 100%")
            parts.append(f"rename from {fd.old_path}")
            parts.append(f"rename to {fd.path}")
        elif (
            fd.old_mode is not None
            and fd.new_mode is not None
            and fd.old_mode != fd.new_mode
        ):
            parts.append(f"old mode {fd.old_mode}")
            parts.append(f"new mode {fd.new_mode}")
        elif fd.is_binary:
            parts.append(f"Binary files a/{old} and b/{fd.path} differ")
    else:
        if is_new:
            parts.append("--- /dev/null")
            parts.append(f"+++ b/{fd.path}")
        elif is_deleted:
            parts.append(f"--- a/{old}")
            parts.append("+++ /dev/null")
        else:
            parts.append(f"--- a/{old}")
            parts.append(f"+++ b/{fd.path}")
        for hunk in fd.hunks:
            parts.append(_hunk_header(hunk))
            for line in hunk.lines:
                parts.append(f"{_KIND_PREFIX[line.kind]}{line.text}")
    return parts


def serialize_unified_diff(change: Change) -> str:
    """Canonical git-style unified diff text for a Change. Inverse of the
    parser for well-formed diffs (R7).
    """
    blocks = ["\n".join(_serialize_file(fd)) for fd in change.files]
    return "\n\n".join(blocks) + "\n"
