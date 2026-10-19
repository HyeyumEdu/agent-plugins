"""쪽·구역 도구: 구역 옵션(줄 번호·격자·글자 방향·첫 쪽 감추기·시작 번호)과 문단의 쪽 제어(쪽 감추기·새 번호).

hwpx_common만 가져온다(hwpx_edit import 금지: 순환 방지). 불리언은 한컴 표기대로 0/1로 저장한다.
"""
from typing import Any, Literal

from hwpx.oxml.namespaces import HP

from hwpx_common import ToolInputError, _body_paragraph, _check_keys, _commit, _section

_LINE_KEYS = frozenset({"restart_type", "count_by", "distance", "start_number", "show"})
_GRID_KEYS = frozenset({"line", "char", "wongoji"})
_HIDE_FIRST_KEYS = frozenset({"header", "footer", "master_page", "page_num", "empty_line"})
_START_KEYS = frozenset({"page", "picture", "table", "equation", "page_starts_on"})
_HIDE_KEYS = frozenset({"header", "footer", "master_page", "border", "fill", "page_num"})
_RESTART_KEYS = frozenset({"number", "kind"})
_PAGE_STARTS_ON = ("BOTH", "ODD", "EVEN")
_DIRECTIONS = ("HORIZONTAL", "VERTICAL", "VERTICALALL")


def _given(spec: dict[str, Any] | None, allowed: frozenset[str], what: str, flags: frozenset[str] = frozenset()) -> dict[str, Any]:
    """spec에서 값이 있는 옵션만(None 제외). 모르는 이름은 거절하고, flags의 이름은 true/false여야 한다."""
    spec = spec or {}
    _check_keys(spec, allowed, what)
    given = {key: value for key, value in spec.items() if value is not None}
    for key in flags & set(given):
        if not isinstance(given[key], bool):
            raise ToolInputError(f"{what}.{key} must be true or false; got {given[key]!r}")
    return given


def _int_option(what: str, key: str, given: dict[str, Any], high: int) -> None:
    value = given.get(key)
    if key in given and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high):
        raise ToolInputError(f"{what}.{key} must be an integer from 0 to {high}; got {value!r}")


def set_page_options_ext(
    filename: str,
    section_index: int = 0,
    line_numbers: dict[str, Any] | None = None,
    grid: dict[str, Any] | None = None,
    text_direction: Literal["HORIZONTAL", "VERTICAL", "VERTICALALL"] | None = None,
    hide_first: dict[str, bool] | None = None,
    start_numbering: dict[str, Any] | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Set section-level page options that the other page tools do not cover: line numbers, grid, text direction, first-page hiding, start numbers. Only what you pass changes.
    section_index: which section (0-based, default 0 = the first). Give at least one of the options below.
    line_numbers: {"restart_type": 0 continue | 1 restart on every page (only these two are documented; other values are refused), "count_by": show a number every N lines (0-65535), "distance": gap between the number and the text in HWPUNIT (7200 per inch, 283.465 = 1 mm), "start_number": 0-65535, "show": true/false}. Numbers are drawn only while show is true.
    grid: {"line": line grid spacing in HWPUNIT (0 = off), "char": character grid spacing in HWPUNIT (0 = off), "wongoji": true/false manuscript-paper (원고지) format}.
    text_direction: HORIZONTAL, VERTICAL or VERTICALALL.
    hide_first: {"header", "footer", "master_page", "page_num", "empty_line"}, each true/false: hide that element on the first page of the section only (a false turns it back on).
    start_numbering: {"page", "picture", "table", "equation": 0-65535 number to start from (0 = go on from the previous section), "page_starts_on": BOTH | ODD | EVEN}.
    Booleans are stored as 0/1 like Hancom does. dry_run=true saves nothing."""
    lines = _given(line_numbers, _LINE_KEYS, "line_numbers", frozenset({"show"}))
    grids = _given(grid, _GRID_KEYS, "grid", frozenset({"wongoji"}))
    hidden = _given(hide_first, _HIDE_FIRST_KEYS, "hide_first", _HIDE_FIRST_KEYS)
    starts = _given(start_numbering, _START_KEYS, "start_numbering")
    _int_option("line_numbers", "restart_type", lines, 1)
    _int_option("line_numbers", "count_by", lines, 0xFFFF)
    _int_option("line_numbers", "distance", lines, 2**31 - 1)
    _int_option("line_numbers", "start_number", lines, 0xFFFF)
    _int_option("grid", "line", grids, 0xFFFF)
    _int_option("grid", "char", grids, 0xFFFF)
    for key in ("page", "picture", "table", "equation"):
        _int_option("start_numbering", key, starts, 0xFFFF)
    if starts.get("page_starts_on") not in (None, *_PAGE_STARTS_ON):
        raise ToolInputError(f"start_numbering.page_starts_on must be one of {list(_PAGE_STARTS_ON)}; got {starts['page_starts_on']!r}")
    if text_direction is not None and text_direction not in _DIRECTIONS:
        raise ToolInputError(f"text_direction must be one of {list(_DIRECTIONS)}; got {text_direction!r}")
    if not (lines or grids or hidden or starts or text_direction):
        raise ToolInputError("nothing to set: give at least one option in line_numbers, grid, text_direction, hide_first or start_numbering")

    def apply(doc: Any) -> dict[str, Any]:
        page, section = doc.page, _section(doc, section_index)
        at = {"section_index": section_index}
        shape = {key: lines[key] for key in ("restart_type", "count_by", "distance", "start_number") if key in lines}
        if shape:
            page.set_line_numbers(**shape, **at)
        visibility = {f"hide_first_{key}": value for key, value in hidden.items()}
        if "show" in lines:
            visibility["show_line_number"] = lines["show"]
        if visibility:
            page.set_visibility(**visibility, **at)
        if grids:
            page.set_grid(line_grid=grids.get("line"), char_grid=grids.get("char"), wonggoji_format=grids.get("wongoji"), **at)
        if text_direction:
            page.set_text_direction(text_direction, **at)
        if starts:
            section.properties.set_start_numbering(**starts)
        pr = section.properties.element
        touched = [tag for tag, on in (("lineNumberShape", shape), ("visibility", visibility), ("grid", grids), ("startNum", starts)) if on]
        for tag in touched:  # 라이브러리는 visibility·wonggojiFormat을 true/false로 쓰지만 한컴은 0/1
            element = pr.find(f"{HP}{tag}")
            for name, value in list(element.attrib.items()):
                if value in ("true", "false"):
                    element.set(name, "1" if value == "true" else "0")
        section.mark_dirty()
        result = {"section_index": section_index, "secPr": {tag: dict(pr.find(f"{HP}{tag}").attrib) for tag in touched}}
        if text_direction:
            result["text_direction"] = text_direction
        return result

    return _commit(filename, expected_revision, dry_run, apply)


def add_page_control_ext(
    filename: str,
    paragraph_index: int,
    hide: dict[str, bool] | None = None,
    restart_page_number: dict[str, Any] | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Attach a page control to a body paragraph: hide page elements on that paragraph's page only, and/or restart a running number from it.
    paragraph_index: 0-based body paragraph (counted over the whole file, as in the other paragraph tools). Give hide, restart_page_number or both.
    hide: {"header", "footer", "master_page", "border", "fill", "page_num"}, each true/false; at least one must be true. Hancom's "hide on the current page only": the next page shows them again.
    restart_page_number: {"number": 0-65535 (default 1), "kind": PAGE | FOOTNOTE | ENDNOTE | PICTURE | TABLE | EQUATION | TOTAL_PAGE (default PAGE)}; {} restarts the page number at 1. The count restarts from this paragraph onward.
    The control is appended to the end of the paragraph, so for a paragraph that spans two pages it sits on the last of them. Booleans are stored as 0/1 like Hancom does. dry_run=true saves nothing."""
    hidden = _given(hide, _HIDE_KEYS, "hide", _HIDE_KEYS)
    restart = _given(restart_page_number, _RESTART_KEYS, "restart_page_number")
    if hide is None and restart_page_number is None:
        raise ToolInputError("nothing to do: give hide or restart_page_number")
    if hide is not None and not any(hidden.values()):
        raise ToolInputError(f"hide must set at least one of {sorted(_HIDE_KEYS)} to true; got {hide!r}")
    _int_option("restart_page_number", "number", restart, 0xFFFF)

    def apply(doc: Any) -> dict[str, Any]:
        paragraph = _body_paragraph(doc, paragraph_index)
        result: dict[str, Any] = {"paragraph_index": paragraph_index}
        if hidden:
            doc.page.hide_page_elements(paragraph, **hidden)
            result["hide"] = sorted(key for key, value in hidden.items() if value)
        if restart_page_number is not None:
            doc.page.restart_page_number(paragraph, **restart)
            result["restart_page_number"] = {"number": restart.get("number", 1), "kind": str(restart.get("kind", "PAGE")).upper()}
        return result

    return _commit(filename, expected_revision, dry_run, apply)
