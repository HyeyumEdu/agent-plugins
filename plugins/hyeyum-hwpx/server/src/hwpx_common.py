"""쓰기 도구 공용 바탕: 오류 형식, 저장 절차, 옵션 검사, 각주·미주 번호 다시 매기기.

새 모듈은 hwpx_edit가 아니라 여기서 가져온다(순환 import 방지).
"""
from typing import Any

from hwpx.errors import HwpxError
from hwpx.oxml.namespaces import HP
from hwpx.tools.id_integrity import check_id_integrity
from hwpx_automation.core.document import open_doc
from hwpx_automation.handlers._shared import (
    _revision_guard,
    _save_doc_verification,
    _with_dry_run_verification,
    _with_save_verification,
)
from hwpx_automation.utils.helpers import resolve_path


_HWPUNIT_PER_MM = 7200 / 25.4


class ToolInputError(ValueError):
    """A refusal whose message is safe to show the caller (argument names, ids, counts - never file paths)."""


def patch_error_messages() -> None:
    """Let a ToolInputError keep its message: upstream replaces every ValueError by one fixed INVALID_ARGUMENT sentence."""
    from hwpx_automation import runtime
    from hwpx_automation.errors import build_error_payload

    original = runtime._classified_error_payload

    def classified(exc: BaseException | None) -> dict[str, Any]:
        for item in runtime._exception_chain(exc) if exc is not None else ():
            if isinstance(item, ToolInputError):
                return build_error_payload(code="INVALID_ARGUMENT", message=str(item))
        return original(exc)

    runtime._classified_error_payload = classified


def _refuse_dangling_ids(doc: Any) -> None:
    report = check_id_integrity(doc)
    if not report.ok:
        raise ToolInputError("id not found in the file's header: " + "; ".join(str(item) for item in report.dangling[:5]))


def _body_paragraph(doc: Any, index: int) -> Any:
    paragraphs = doc.paragraphs
    if isinstance(index, bool) or not 0 <= index < len(paragraphs):
        raise ToolInputError(f"invalid paragraph_index {index!r} (the file has {len(paragraphs)} body paragraphs)")
    return paragraphs[index]


def _check_paragraph_indexes(doc: Any, indexes: list[int]) -> None:
    bad = [index for index in indexes if not 0 <= index < len(doc.paragraphs)]
    if bad:
        raise ToolInputError(f"invalid paragraph index {bad} (the file has {len(doc.paragraphs)} body paragraphs)")


def _section(doc: Any, index: int, name: str = "section_index") -> Any:
    sections = doc.sections
    if isinstance(index, bool) or not 0 <= index < len(sections):
        raise ToolInputError(f"invalid {name} {index!r} (the file has {len(sections)} sections: 0-{len(sections) - 1})")
    return sections[index]


def _holds_section_definition(paragraph: Any) -> bool:
    """구역 정의(쪽·단 설정)를 가진 문단: 구역의 첫 문단이어야 하므로 그 앞에 넣거나 복제할 수 없다."""
    return paragraph.element.find(f".//{HP}secPr") is not None


def _renumber_notes(doc: Any, note_tag: str, pr_tag: str) -> None:
    """``number`` and the first ``autoNum@num`` of every note, in document order (per section when the notes restart on each)."""
    counter = 0
    for section in doc.oxml.sections:
        element = section.element
        pr = next(element.iter(f"{HP}{pr_tag}"), None)
        numbering = pr.find(f"{HP}numbering") if pr is not None else None
        if numbering is not None and numbering.get("type") == "ON_SECTION":
            counter = 0
        for note in element.iter(f"{HP}{note_tag}"):
            counter += 1
            note.set("number", str(counter))
            auto = next(note.iter(f"{HP}autoNum"), None)
            if auto is not None:
                auto.set("num", str(counter))
        section.mark_dirty()


def _renumber_endnotes(doc: Any) -> None:
    _renumber_notes(doc, "endNote", "endNotePr")


def _renumber_footnotes(doc: Any) -> None:
    _renumber_notes(doc, "footNote", "footNotePr")


def _char_ref(doc: Any, run: dict[str, Any], base: str | None = None) -> str | None:
    """Character shape id for a run spec: its own ``char_pr_id``, else one made from its options on top of *base* (default: the file's first shape)."""
    if "char_pr_id" in run:
        return str(run["char_pr_id"])
    options = _run_kwargs({key: value for key, value in run.items() if key not in ("text", "char_pr_id")})
    return doc.styles.ensure_run(base_char_pr_id=base, **options) if options else base


def _commit(filename: str, expected_revision: str | None, dry_run: bool, apply) -> dict[str, Any]:
    """Upstream's write procedure: path and revision checks, open, ``apply(doc)``, then (unless dry_run) backup, save, verify.
    Library errors raised by *apply* become ToolInputError so their text reaches the caller."""
    path = resolve_path(filename)
    guard = _revision_guard(path, expected_revision)
    if guard is not None:
        raise ToolInputError(
            f"document revision mismatch: expected_revision {guard.get('expected_revision')!r}, file is at {guard.get('document_revision')!r}; "
            "re-read it (get_document_info) and retry with that document_revision"
        )
    doc = open_doc(path)
    try:
        result = apply(doc)
    except ToolInputError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, HwpxError) as error:
        hint = getattr(error, "suggestion", None)
        raise ToolInputError(f"{type(error).__name__}: {error}" + (f" ({hint})" if hint else "")) from error
    result["filename"] = filename
    if dry_run:
        return _with_dry_run_verification(result, doc, path)
    return _with_save_verification(result, _save_doc_verification(doc, path))


#: paragraph shape options of a ``format`` dict (as in set_paragraph_format_ext)
_PARA_KEYS = frozenset({
    "alignment", "line_spacing_percent", "indent_left_mm", "indent_right_mm", "first_line_indent_mm", "spacing_before_pt",
    "spacing_after_pt", "outline_level", "keep_with_next", "keep_lines", "page_break_before", "column_break",
    "break_non_latin_word", "break_latin_word", "condense", "snap_to_grid", "tab_stops", "auto_tab_left", "auto_tab_right",
    "border",
})

#: character options (as in format_text_ext)
_RUN_KEYS = frozenset({
    "bold", "italic", "underline", "underline_shape", "underline_color", "strike", "strike_shape", "color", "highlight",
    "font_name", "font_size", "ratio", "letter_spacing", "script", "offset", "use_font_space", "emphasis_mark", "use_kerning",
})


def _check_keys(spec: dict[str, Any], allowed: frozenset[str], what: str) -> None:
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ToolInputError(f"unknown {what} option(s) {unknown}; allowed: {sorted(allowed)}")


def _para_kwargs(spec: dict[str, Any]) -> dict[str, Any]:
    """``apply_paragraph_format`` keyword arguments from *spec* (None dropped, tab stop ``pos`` HWPUNIT -> ``pos_mm``)."""
    kwargs = {key: value for key, value in spec.items() if value is not None}
    if "tab_stops" in kwargs:
        positions = [stop.get("pos", stop.get("pos_mm")) for stop in kwargs["tab_stops"]]
        if any(position is None for position in positions) or positions != sorted(positions):
            raise ToolInputError(f"tab_stops need a pos for every stop, in ascending order; got {positions}")
        kwargs["tab_stops"] = [
            {**stop, "pos_mm": stop["pos"] / _HWPUNIT_PER_MM} if "pos" in stop else stop for stop in kwargs["tab_stops"]
        ]
    return kwargs


def _run_kwargs(spec: dict[str, Any]) -> dict[str, Any]:
    """``ensure_run`` keyword arguments from *spec* (None dropped, ``font_name``/``font_size`` -> ``font``/``size``)."""
    renamed = {"font_name": "font", "font_size": "size"}
    return {renamed.get(key, key): value for key, value in spec.items() if value is not None}
