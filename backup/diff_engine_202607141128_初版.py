"""Line-level alignment and character-level highlight ranges for log comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

TagName = Literal["match", "mismatch", "gap", "prefix"]


@dataclass(frozen=True)
class CharSpan:
    """Inclusive-exclusive character range within a displayed line (no newline)."""

    start: int
    end: int
    tag: TagName


@dataclass
class AlignedLine:
    """One row after alignment; empty string means a gap (blank line inserted)."""

    text: str
    is_gap: bool
    spans: list[CharSpan] = field(default_factory=list)


@dataclass
class DiffResult:
    left: list[AlignedLine]
    right: list[AlignedLine]


def _split_lines(text: str) -> list[str]:
    if text == "":
        return []
    # Keep content without trailing newline artifacts from Text widget
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _prefix_length(
    line: str,
    *,
    skip_chars: int | None = None,
    skip_marker: str | None = None,
) -> int:
    """Return how many leading characters to ignore for comparison on this line."""
    if skip_marker is not None:
        idx = line.find(skip_marker)
        return idx if idx >= 0 else 0
    if skip_chars is not None and skip_chars > 0:
        return min(skip_chars, len(line))
    return 0


def _normalize(
    line: str,
    *,
    skip_chars: int | None = None,
    skip_marker: str | None = None,
) -> str:
    prefix = _prefix_length(line, skip_chars=skip_chars, skip_marker=skip_marker)
    return line[prefix:]


def _char_spans(
    left: str,
    right: str,
    *,
    skip_chars: int | None = None,
    skip_marker: str | None = None,
) -> tuple[list[CharSpan], list[CharSpan]]:
    """Build display spans for a paired (non-gap) line pair."""
    left_spans: list[CharSpan] = []
    right_spans: list[CharSpan] = []

    left_prefix = _prefix_length(left, skip_chars=skip_chars, skip_marker=skip_marker)
    right_prefix = _prefix_length(right, skip_chars=skip_chars, skip_marker=skip_marker)

    if left_prefix:
        left_spans.append(CharSpan(0, left_prefix, "prefix"))
    if right_prefix:
        right_spans.append(CharSpan(0, right_prefix, "prefix"))

    left_body = left[left_prefix:]
    right_body = right[right_prefix:]
    matcher = SequenceMatcher(a=left_body, b=right_body, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            if i2 > i1:
                left_spans.append(CharSpan(left_prefix + i1, left_prefix + i2, "match"))
            if j2 > j1:
                right_spans.append(CharSpan(right_prefix + j1, right_prefix + j2, "match"))
        elif tag == "replace":
            if i2 > i1:
                left_spans.append(CharSpan(left_prefix + i1, left_prefix + i2, "mismatch"))
            if j2 > j1:
                right_spans.append(
                    CharSpan(right_prefix + j1, right_prefix + j2, "mismatch")
                )
        elif tag == "delete":
            if i2 > i1:
                left_spans.append(CharSpan(left_prefix + i1, left_prefix + i2, "mismatch"))
        elif tag == "insert":
            if j2 > j1:
                right_spans.append(
                    CharSpan(right_prefix + j1, right_prefix + j2, "mismatch")
                )

    return left_spans, right_spans


def _gap_line() -> AlignedLine:
    return AlignedLine(text="", is_gap=True, spans=[])


def _full_line_spans(text: str, tag: TagName) -> list[CharSpan]:
    if not text:
        return []
    return [CharSpan(0, len(text), tag)]


def compare_logs(
    left_text: str,
    right_text: str,
    *,
    skip_chars: int | None = None,
    skip_marker: str | None = None,
) -> DiffResult:
    """
    Align left/right logs by line (LCS), insert blank lines for gaps,
    then mark character-level match/mismatch (and optional ignored prefix).

    If both skip_chars and skip_marker are set, skip_marker takes precedence.
    """
    left_lines = _split_lines(left_text)
    right_lines = _split_lines(right_text)

    left_norm = [
        _normalize(line, skip_chars=skip_chars, skip_marker=skip_marker)
        for line in left_lines
    ]
    right_norm = [
        _normalize(line, skip_chars=skip_chars, skip_marker=skip_marker)
        for line in right_lines
    ]

    matcher = SequenceMatcher(a=left_norm, b=right_norm, autojunk=False)

    left_out: list[AlignedLine] = []
    right_out: list[AlignedLine] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for li, ri in zip(range(i1, i2), range(j1, j2)):
                l_text = left_lines[li]
                r_text = right_lines[ri]
                l_spans, r_spans = _char_spans(
                    l_text,
                    r_text,
                    skip_chars=skip_chars,
                    skip_marker=skip_marker,
                )
                left_out.append(AlignedLine(text=l_text, is_gap=False, spans=l_spans))
                right_out.append(AlignedLine(text=r_text, is_gap=False, spans=r_spans))
        elif tag == "replace":
            # Pair differing lines; pad the shorter side with gaps.
            left_chunk = left_lines[i1:i2]
            right_chunk = right_lines[j1:j2]
            pair_count = min(len(left_chunk), len(right_chunk))
            for k in range(pair_count):
                l_text = left_chunk[k]
                r_text = right_chunk[k]
                l_spans, r_spans = _char_spans(
                    l_text,
                    r_text,
                    skip_chars=skip_chars,
                    skip_marker=skip_marker,
                )
                left_out.append(AlignedLine(text=l_text, is_gap=False, spans=l_spans))
                right_out.append(AlignedLine(text=r_text, is_gap=False, spans=r_spans))
            for l_text in left_chunk[pair_count:]:
                left_out.append(
                    AlignedLine(
                        text=l_text,
                        is_gap=False,
                        spans=_full_line_spans(l_text, "mismatch"),
                    )
                )
                right_out.append(_gap_line())
            for r_text in right_chunk[pair_count:]:
                left_out.append(_gap_line())
                right_out.append(
                    AlignedLine(
                        text=r_text,
                        is_gap=False,
                        spans=_full_line_spans(r_text, "mismatch"),
                    )
                )
        elif tag == "delete":
            for li in range(i1, i2):
                l_text = left_lines[li]
                left_out.append(
                    AlignedLine(
                        text=l_text,
                        is_gap=False,
                        spans=_full_line_spans(l_text, "mismatch"),
                    )
                )
                right_out.append(_gap_line())
        elif tag == "insert":
            for ri in range(j1, j2):
                r_text = right_lines[ri]
                left_out.append(_gap_line())
                right_out.append(
                    AlignedLine(
                        text=r_text,
                        is_gap=False,
                        spans=_full_line_spans(r_text, "mismatch"),
                    )
                )

    return DiffResult(left=left_out, right=right_out)
