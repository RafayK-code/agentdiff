from __future__ import annotations

from agentdiff.model import Change, Comment


def _location(comment: Comment) -> str:
    """`NEW 2-2` / `OLD 1-3` for line-scoped comments, else `file-level`. (R4)"""
    if comment.range is None:
        return "file-level"
    side = comment.range.side.value
    return f"{side} {comment.range.start}-{comment.range.end}"


def _bullet(comment: Comment) -> str:
    return (
        f"- {comment.id}: {comment.text} ({_location(comment)}) "
        f"[{comment.author}, {comment.state.value}]"
    )


def export_markdown(change: Change, comments: list[Comment]) -> str:
    """Human-readable, per-file sections with location-annotated bullets. (R4)"""
    by_file: dict[str, list[Comment]] = {}
    for comment in comments:
        by_file.setdefault(comment.file, []).append(comment)

    sections: list[str] = [f"# Change {change.id}", ""]
    for file in change.files:
        sections.append(f"## {file.path}")
        sections.extend(_bullet(c) for c in by_file.pop(file.path, []))
        sections.append("")
    for path in by_file:
        sections.append(f"## {path}")
        sections.extend(_bullet(c) for c in by_file[path])
        sections.append("")
    return "\n".join(sections)
