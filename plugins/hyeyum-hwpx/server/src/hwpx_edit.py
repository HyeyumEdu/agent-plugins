"""쓰기 도구: 업스트림 도구가 열지 않은 포크 라이브러리의 서식 기능. 저장 절차는 hwpx_common._commit."""
from typing import Any, Literal

from hwpx.oxml.namespaces import HH, HP
from hwpx.oxml.table_sizes import set_cell_margins
from hwpx_automation.core.formatting import _paragraph_length
from hwpx_inline import (  # noqa: F401  (insert_inline_ext: tests call it as hwpx_edit.insert_inline_ext)
    build_items, build_table, check_items, check_table, insert_inline_ext, paragraph_style, table_at, table_indexes,
)
from hwpx_runs import split_run
from hwpx_common import (  # noqa: F401  (patch_error_messages: tests call it as hwpx_edit.patch_error_messages)
    _PARA_KEYS, ToolInputError, _body_paragraph, _check_keys, _check_paragraph_indexes, _commit, _holds_section_definition,
    _para_kwargs, _refuse_dangling_ids, _renumber_endnotes, _renumber_footnotes, _run_kwargs, patch_error_messages,
)

#: keys of a paragraph spec (add_paragraphs_ext, add_endnote_ext, format_table_ext cells)
_PARAGRAPH_KEYS = frozenset({"text", "runs", "char", "format", "para_pr_id", "style_id", "style", "table", "page_break", "tab"})
_TAB_KEYS = frozenset({"width", "leader", "type"})


def _paragraph_plans(paragraphs: list[dict[str, Any]], where: str, tables: bool = True) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Validate paragraph specs ({text | runs, char, format, para_pr_id, style_id | style, table, page_break, tab}) and return (spec, runs) pairs.
    A paragraph that holds a ``table`` may have neither text nor runs."""
    if not paragraphs:
        raise ToolInputError(f"{where} must not be empty")
    plans = []
    for number, spec in enumerate(paragraphs):
        label = f"{where}[{number}]"
        _check_keys(spec, _PARAGRAPH_KEYS, label)
        given = ("text" in spec) + ("runs" in spec)
        if given > 1 or (given == 0 and "table" not in spec):
            raise ToolInputError(f"{label}: give exactly one of text or runs")
        if "style" in spec and "style_id" in spec:
            raise ToolInputError(f"{label}: give style or style_id, not both")
        runs = spec["runs"] if "runs" in spec else [{"text": spec["text"], **spec.get("char", {})}] if "text" in spec else []
        if not runs and "table" not in spec:
            raise ToolInputError(f"{label}: runs must not be empty")
        check_items(runs, f"{label}.runs")
        _check_keys(spec.get("format", {}), _PARA_KEYS, f"{label} format")
        if "table" in spec:
            if not tables:
                raise ToolInputError(f"{label}: a table cannot be placed in an endnote paragraph (format_table_ext could not reach it)")
            check_table(spec["table"], f"{label}.table")
        plans.append((spec, runs))
    return plans


def _border_from_id(doc: Any, border: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """A paragraph ``border`` mapping that names a header borderFill (``border_fill_id``) becomes the sides/type/width/color that
    borderFill draws, so the library finds that same definition again (see ensure_border_fill); the id is checked afterwards."""
    if "border_fill_id" not in border:
        return border, None
    wanted = str(border["border_fill_id"])
    header = doc.oxml.headers[0].element
    fill = next((e for e in header.iter(f"{HH}borderFill") if e.get("id") == wanted), None)
    if fill is None:
        raise ToolInputError(f"border_fill_id {wanted!r} is not defined in the file's header")
    drawn = {side: fill.find(f"{HH}{side}Border") for side in ("left", "right", "top", "bottom")}
    drawn = {side: element for side, element in drawn.items() if element is not None and element.get("type") != "NONE"}
    if not drawn:
        raise ToolInputError(f"borderFill {wanted} draws no border line, so it cannot be a paragraph border")
    lines = {(e.get("type"), e.get("width"), e.get("color")) for e in drawn.values()}
    if len(lines) != 1:
        raise ToolInputError(f"borderFill {wanted} has different lines on different sides; give sides/type/width/color instead of border_fill_id")
    (line_type, width, color), = lines
    rest = {key: value for key, value in border.items() if key != "border_fill_id"}
    return {**rest, "sides": list(drawn), "type": line_type, "width": width, "color": color}, wanted


def _check_border_id(doc: Any, paragraphs: list[Any], wanted: str | None) -> None:
    if wanted is None:
        return
    header = doc.oxml.headers[0].element
    shapes = {e.get("id"): e for e in header.iter(f"{HH}paraPr")}
    for paragraph in paragraphs:
        border = shapes[str(paragraph.para_pr_id_ref)].find(f"{HH}border")
        if border is None or border.get("borderFillIDRef") != wanted:
            raise ToolInputError(f"borderFill {wanted} cannot be attached by id: it differs from a plain box in a way a paragraph border cannot reproduce")


def _set_tabs(tabs: list[Any], width: int, leader: int, tab_type: int) -> None:
    for tab in tabs:
        tab.set("width", str(int(width)))
        tab.set("leader", str(int(leader)))
        tab.set("type", str(int(tab_type)))


def _apply_shapes(doc: Any, built: list[tuple[Any, dict[str, Any]]]) -> None:
    """Paragraph shapes last: a new paragraph copies a neighbour's shape, so format only after all exist."""
    for target, spec in built:
        if "page_break" in spec:
            target.element.set("pageBreak", "1" if spec["page_break"] else "0")
        if "tab" in spec:
            tab = spec["tab"]
            _check_keys(tab, _TAB_KEYS, "tab")
            _set_tabs(target.element.findall(f"{HP}run/{HP}t/{HP}tab"), tab.get("width", 0), tab.get("leader", 0), tab.get("type", 1))
        if "para_pr_id" in spec:
            target.para_pr_id_ref = str(spec["para_pr_id"])
        if "style_id" in spec:
            target.style_id_ref = str(spec["style_id"])
        if "style" in spec:  # para_pr_id wins over the style's paragraph shape (Hancom saves such an override as another shape)
            style = paragraph_style(doc, spec["style"], "style")
            target.style_id_ref = str(style.id)
            if "para_pr_id" not in spec and style.para_pr_id_ref is not None:
                target.para_pr_id_ref = str(style.para_pr_id_ref)
        if spec.get("format"):
            fmt = dict(spec["format"])
            wanted = None
            if fmt.get("border"):
                fmt["border"], wanted = _border_from_id(doc, fmt["border"])
            doc.styles.apply_paragraph_format(paragraphs=[target], **_para_kwargs(fmt))
            _check_border_id(doc, [target], wanted)


def _build_paragraph(doc: Any, target: Any, spec: dict[str, Any], runs: list[dict[str, Any]], tables: list[Any], where: str, first_run: Any | None = None) -> None:
    """Write one planned paragraph's inline items into *target* (on top of its style's character shape) and its ``table``, if any, whose element goes to *tables*."""
    base = None
    if "style" in spec:
        base = paragraph_style(doc, spec["style"], f"{where}.style").char_pr_id_ref
    build_items(doc, target, runs, None if base is None else str(base), first_run, f"{where}.runs")
    if "table" in spec:
        tables.append(build_table(target, spec["table"]))


def set_paragraph_format_ext(
    filename: str,
    paragraph_index: int | None = None,
    paragraph_indexes: list[int] | None = None,
    alignment: str | None = None,
    line_spacing_percent: float | None = None,
    indent_left_mm: float | None = None,
    indent_right_mm: float | None = None,
    first_line_indent_mm: float | None = None,
    spacing_before_pt: float | None = None,
    spacing_after_pt: float | None = None,
    outline_level: int | None = None,
    keep_with_next: bool | None = None,
    keep_lines: bool | None = None,
    page_break_before: bool | None = None,
    column_break: bool | None = None,
    page_break: bool | None = None,
    para_pr_id: str | None = None,
    break_non_latin_word: Literal["KEEP_WORD", "BREAK_WORD"] | None = None,
    break_latin_word: Literal["KEEP_WORD", "HYPHENATION", "BREAK_WORD"] | None = None,
    condense: int | None = None,
    snap_to_grid: bool | None = None,
    tab_stops: list[dict[str, Any]] | None = None,
    auto_tab_left: bool | None = None,
    auto_tab_right: bool | None = None,
    border: dict[str, Any] | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Superset of set_paragraph_format (same arguments, same keep-what-you-do-not-set behavior) plus options it lacks.
    Only the arguments you pass change; alignment, line-break mode, spacing and borders you leave out are kept.
    Omitting both paragraph_index and paragraph_indexes formats every body paragraph, except with page_break (then one is required).
    break_non_latin_word: "BREAK_WORD" wraps Hangul lines at spaces (어절), "KEEP_WORD" may wrap between any two characters (the names read backwards).
    break_latin_word: KEEP_WORD / HYPHENATION / BREAK_WORD. condense: minimum space width 0-100 % (공백 최소값). snap_to_grid: paper line grid on/off.
    column_break / page_break: set the paragraph's own columnBreak / pageBreak attribute (a forced break before it), not the shared paragraph style.
    para_pr_id: attach a paragraph shape that already exists in the file (by id) to the chosen paragraphs; the other options then change a copy of that shape. Needs paragraph_index(es); an unknown id is refused.
    first_line_indent_mm: first-line indent; a NEGATIVE value is a hanging indent (내어쓰기: the lines after the first are indented by that much more).
    tab_stops: [{"pos_mm": mm  or  "pos": HWPUNIT (7200 per inch, 283.465 = 1 mm), "type": LEFT|RIGHT|CENTER|DECIMAL, "leader": NONE|...}] in ascending pos; auto_tab_left/auto_tab_right: automatic tabs at paragraph margins.
    border: {"sides": ["left","right","top","bottom"], "type": "SOLID", "width": "0.12 mm", "color": "#000000", "offset_mm": number or [left,right,top,bottom], "connect": true, "ignore_margin": false}, or {"border_fill_id": "6", "connect": true, ...} to use a plain-box borderFill already in the file (a borderFill with the same lines is reused, never duplicated);
    connect=true draws consecutive paragraphs with the same paragraph shape as one box. dry_run=true saves nothing. Spacing in pt, indents in mm, line spacing in %."""
    targets = list(paragraph_indexes or ([] if paragraph_index is None else [paragraph_index]))
    if (page_break is not None or para_pr_id is not None) and not targets:
        raise ToolInputError("page_break and para_pr_id need paragraph_index or paragraph_indexes")

    def apply(doc: Any) -> dict[str, Any]:
        _check_paragraph_indexes(doc, targets)
        options = _para_kwargs(dict(
            alignment=alignment, line_spacing_percent=line_spacing_percent, indent_left_mm=indent_left_mm,
            indent_right_mm=indent_right_mm, first_line_indent_mm=first_line_indent_mm, spacing_before_pt=spacing_before_pt,
            spacing_after_pt=spacing_after_pt, outline_level=outline_level, keep_with_next=keep_with_next,
            keep_lines=keep_lines, page_break_before=page_break_before, column_break=column_break,
            break_non_latin_word=break_non_latin_word, break_latin_word=break_latin_word, condense=condense,
            snap_to_grid=snap_to_grid, tab_stops=tab_stops, auto_tab_left=auto_tab_left,
            auto_tab_right=auto_tab_right, border=border,
        ))
        wanted_border = None
        if options.get("border"):
            options["border"], wanted_border = _border_from_id(doc, options["border"])
        if para_pr_id is not None:
            for index in targets:
                doc.paragraphs[index].para_pr_id_ref = str(para_pr_id)
        if options or not targets:
            result = doc.styles.apply_paragraph_format(
                paragraph_index=paragraph_index, paragraph_indexes=paragraph_indexes, **options
            ).to_dict()
        else:
            result = {"formatted": 0, "paragraphs": []}
        if wanted_border is not None:
            _check_border_id(doc, [doc.paragraphs[index] for index in result["paragraphs"]], wanted_border)
        if page_break is not None:
            for index in targets:
                paragraph = doc.paragraphs[index]
                paragraph.element.set("pageBreak", "1" if page_break else "0")
                paragraph.section.mark_dirty()
            result["pageBreakSet"] = targets
        if para_pr_id is not None:
            _refuse_dangling_ids(doc)
            result["paraPrIdSet"] = targets
        return result

    return _commit(filename, expected_revision, dry_run, apply)


def format_text_ext(
    filename: str,
    paragraph_index: int,
    start_pos: int,
    end_pos: int,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    underline_shape: str | None = None,
    underline_color: str | None = None,
    strike: bool | None = None,
    strike_shape: str | None = None,
    color: str | None = None,
    highlight: str | None = None,
    font_name: str | None = None,
    font_size: float | None = None,
    ratio: int | None = None,
    letter_spacing: int | None = None,
    script: Literal["sup", "sub"] | None = None,
    offset: int | None = None,
    use_font_space: bool | None = None,
    emphasis_mark: str | None = None,
    use_kerning: bool | None = None,
    char_pr_id: str | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Superset of format_text: character formatting for a text range [start_pos, end_pos) of one body paragraph, with options format_text lacks.
    Only the arguments you pass change; everything else of each run's current character shape is kept.
    ratio: character width in % (장평). letter_spacing: spacing between characters in % of the font size (자간; negative tightens).
    underline_shape / strike_shape: SOLID, DOT, DASH, ... (OWPML line types). script: sup / sub. offset: vertical position in % (글자 위치).
    use_font_space: 글꼴에 어울리는 빈칸. emphasis_mark: DOT_ABOVE, RING_ABOVE, ... (강조점). font_size in pt. color / underline_color / highlight as #RRGGBB.
    char_pr_id: instead of the options, attach a character shape that already exists in the file (by id) to the range; an unknown id is refused.
    Positions count characters of the paragraph text (a tab or line break counts as one character). A range outside the text is refused.
    An EMPTY paragraph (e.g. a 3 pt spacer line) has no text to select: pass start_pos=0 and end_pos=0 to give its character shape (font_size, char_pr_id ...). dry_run=true saves nothing."""
    options = _run_kwargs(dict(
        bold=bold, italic=italic, underline=underline, underline_shape=underline_shape, underline_color=underline_color,
        strike=strike, strike_shape=strike_shape, color=color, highlight=highlight, font_name=font_name, font_size=font_size,
        ratio=ratio, letter_spacing=letter_spacing, script=script, offset=offset, use_font_space=use_font_space,
        emphasis_mark=emphasis_mark, use_kerning=use_kerning,
    ))
    if char_pr_id is not None and options:
        raise ToolInputError("char_pr_id cannot be combined with other character options")
    if not options and char_pr_id is None:
        raise ToolInputError("pass at least one character option")
    if start_pos < 0 or end_pos < start_pos:
        raise ToolInputError(f"start_pos {start_pos} / end_pos {end_pos} are out of range (0 <= start_pos <= end_pos)")

    def apply(doc: Any) -> dict[str, Any]:
        paragraph = _body_paragraph(doc, paragraph_index)
        length = _paragraph_length(paragraph)

        def char_id_for(run_ref: str | None) -> str:
            return str(char_pr_id) if char_pr_id is not None else doc.styles.ensure_run(base_char_pr_id=run_ref, **options)

        ids: list[str] = []
        if length == 0:  # an empty paragraph keeps its character shape in its run
            if start_pos or end_pos:
                raise ToolInputError(f"the paragraph is empty: use start_pos=0 and end_pos=0 to set its character shape, got {start_pos}..{end_pos}")
            if not paragraph.runs:
                paragraph.add_run("")
            for run in paragraph.runs:
                run.char_pr_id_ref = char_id_for(run.char_pr_id_ref)
                ids.append(run.char_pr_id_ref)
            paragraph.section.mark_dirty()
        else:
            if start_pos >= length or end_pos == start_pos:
                raise ToolInputError(f"range {start_pos}..{end_pos} selects no text: the paragraph text has {length} characters (a tab or line break counts as one)")
            span_end = min(end_pos, length)
            cursor = start_pos
            while cursor < span_end:
                offset_in_text = 0
                for run in paragraph.runs:
                    run_length = len(run.text or "")
                    run_start, offset_in_text = offset_in_text, offset_in_text + run_length
                    if run_length and offset_in_text > cursor:
                        break
                else:
                    break
                char_id = char_id_for(run.char_pr_id_ref)
                split_run(run, max(0, cursor - run_start), min(run_length, span_end - run_start), char_id)
                ids.append(char_id)
                cursor = min(span_end, offset_in_text)
        if char_pr_id is not None:
            _refuse_dangling_ids(doc)
        return {"formatted": bool(ids), "paragraph_index": paragraph_index, "range": [start_pos, min(end_pos, length)], "charPrIds": ids}

    return _commit(filename, expected_revision, dry_run, apply)


def set_tab_attributes(
    filename: str,
    paragraph_index: int,
    width: int,
    leader: int = 0,
    tab_type: int = 1,
    tab_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Give the tab characters of one body paragraph the attributes Hancom writes: <hp:tab width= leader= type=/>.
    Write the tab as "\\t" in the text first (add_paragraph, update text); it is stored as a bare <hp:tab/>, and this sets its attributes.
    width: distance the tab spans in HWPUNIT (7200 per inch; Hancom recomputes it when it lays the line out). leader: 0 = none (Hancom files use 3 with a right tab for a dotted leader).
    tab_type: 1 = left tab, 2 = right tab, as Hancom-saved files use them. tab_index: which tab of the paragraph (0-based); omit for every tab in it. dry_run=true saves nothing."""

    def apply(doc: Any) -> dict[str, Any]:
        paragraph = _body_paragraph(doc, paragraph_index)
        tabs = paragraph.element.findall(f"{HP}run/{HP}t/{HP}tab")
        if tab_index is not None and not 0 <= tab_index < len(tabs):
            raise ToolInputError(f"tab_index {tab_index} out of range: the paragraph has {len(tabs)} tab(s)")
        if not tabs:
            raise ToolInputError(f"paragraph {paragraph_index} has no tab character; write a tab (\\t) into its text first")
        chosen = tabs if tab_index is None else [tabs[tab_index]]
        _set_tabs(chosen, width, leader, tab_type)
        paragraph.section.mark_dirty()
        return {"paragraph_index": paragraph_index, "tabsSet": len(chosen), "tabsInParagraph": len(tabs)}

    return _commit(filename, expected_revision, dry_run, apply)


def add_endnote_ext(
    filename: str,
    paragraph_index: int,
    paragraphs: list[dict[str, Any]],
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Attach an endnote (미주) after the last run of body paragraph `paragraph_index`, with as many paragraphs as you give, each with its own formatting.
    paragraphs: a non-empty list; every item is {"text": "...", "char": {...}} or {"runs": [{"text": "...", ...}, ...]} plus optional "format": {...}, "para_pr_id", "style_id" or "style",
    "page_break": true (the paragraph's own pageBreak attribute) and "tab": {"width": HWPUNIT, "leader": 0, "type": 1} (attributes for every tab written as "\\t" in the item; as set_tab_attributes).
    A run is an inline item with exactly one kind key, written in the order given: {"text": "...", "special": false} (the options below go beside it; special=true turns \\t, \\n, U+00A0, U+3000, U+00AD into tab, line break, no-break space, full-width space, soft hyphen elements),
    {"equation": "EqEdit script"} or {"latex": "..."} (+ "base_unit": 1/100 pt, default 1000), {"picture": {"path" | "image_base64", "width_mm", "height_mm"}}, {"footnote": "..."} (not in a note), {"hyperlink": {"url", "text"}},
    {"bookmark": "name"}, {"check_box": {"caption", "checked"}}, {"ruby": {"base", "text", "pos_type"}}, {"composed": {"text", "circle_type"}} (details: insert_inline_ext). A run may carry "char": {options} too.
    "style": a paragraph style by name, English name or id (not together with style_id): the paragraph gets the style's paragraph shape (para_pr_id still wins) and its runs the style's character shape, with their options on top.
    The first item becomes the note's first paragraph; Hancom shows the automatic note number (autoNum) in front of it. Later items are further paragraphs; "" makes an empty one.
    To reuse shapes already in the file give ids: "para_pr_id" / "style_id" per paragraph and "char_pr_id" per run (see hwpx_read_layout / get_document_info); a missing id is refused.
    Without ids, "char" / per-run options create (or reuse) a character shape: bold, italic, underline, underline_shape, underline_color, strike, strike_shape, color, highlight, font_name, font_size (pt),
    ratio, letter_spacing, script (sup|sub), offset, use_font_space, emphasis_mark, use_kerning (as in format_text_ext). "format" options: alignment, line_spacing_percent, indent_left_mm, indent_right_mm,
    first_line_indent_mm, spacing_before_pt, spacing_after_pt, keep_with_next, keep_lines, break_non_latin_word, break_latin_word, condense, snap_to_grid, tab_stops, border ... (as in set_paragraph_format_ext).
    Paragraphs without ids/format keep the note's default shape. A paragraph that already has an endnote gets another one. "table" is not allowed in a note. dry_run=true saves nothing."""
    plans = _paragraph_plans(paragraphs, "paragraphs", tables=False)

    def apply(doc: Any) -> dict[str, Any]:
        note = doc.notes.add_endnote("", paragraph=_body_paragraph(doc, paragraph_index))
        built = []
        for number, (spec, runs) in enumerate(plans):
            target = note.body_paragraph if number == 0 else note.add_paragraph("")
            _build_paragraph(doc, target, spec, runs, [], f"paragraphs[{number}]", first_run=target.runs[0])
            built.append((target, spec))
        _apply_shapes(doc, built)
        _refuse_dangling_ids(doc)
        _renumber_endnotes(doc)
        return {"paragraph_index": paragraph_index, "noteParagraphs": len(plans)}

    return _commit(filename, expected_revision, dry_run, apply)


_CELL_KEYS = frozenset({"row", "col", "border", "border_fill_id", "margin", "vertical_align", "paragraphs"})
_BORDER_KEYS = frozenset({"sides", "type", "width", "color", "fill_color"})


def _border_fill_id(doc: Any, border: dict[str, Any], where: str) -> str:
    _check_keys(border, _BORDER_KEYS, where)
    return doc.styles.ensure_border_fill(
        border_color=border.get("color", "#000000"), border_width=border.get("width", "0.12 mm"),
        fill_color=border.get("fill_color"), border_type=border.get("type", "SOLID"),
        active_borders=border.get("sides", ["left", "right", "top", "bottom"]),
    )


def _column_widths(table: Any) -> list[float]:
    widths = [0.0] * table.column_count
    for entry in table.iter_grid():
        if entry.cell.span[1] == 1 and entry.cell.address[1] == entry.column and not widths[entry.column]:
            widths[entry.column] = entry.cell.width
    return [width or 1.0 for width in widths]


def format_table_ext(
    filename: str,
    table_index: int,
    merges: list[list[int]] | None = None,
    column_widths: list[int] | None = None,
    width: int | None = None,
    row_heights: list[int] | None = None,
    height: int | None = None,
    treat_as_char: bool | None = None,
    page_break: Literal["NONE", "CELL", "TABLE"] | None = None,
    repeat_header: bool | None = None,
    out_margin: dict[str, int] | None = None,
    in_margin: dict[str, int] | None = None,
    position: dict[str, Any] | None = None,
    border: dict[str, Any] | None = None,
    border_fill_id: str | None = None,
    cells_border: dict[str, Any] | None = None,
    cells: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Superset of format_table for table `table_index` (same numbering as format_table; nested tables count after their parent). Only what you pass changes. Applied in this order:
    merges [[row1,col1,row2,col2],...] (0-based, inclusive); column_widths (HWPUNIT per column, 7200 per inch, 283.465 = 1 mm; table width becomes their sum) or width (total, columns keep proportions);
    row_heights (HWPUNIT per row, 0 allowed; table height becomes their sum); height (declared table height); treat_as_char; page_break (NONE|CELL|TABLE); repeat_header;
    out_margin / in_margin {left,right,top,bottom} in HWPUNIT; position {horz_rel_to: PAPER|PAGE|COLUMN|PARA, vert_rel_to: PAPER|PAGE|PARA, horz_offset, vert_offset};
    border {sides:[left,right,top,bottom], type: SOLID|DASH|DOT|DOUBLE_SLIM|..., width: "0.12 mm", color: "#000000", fill_color} or border_fill_id (a borderFill already in the file) for the table's own borderFill.
    cells_border (same keys as border) gives EVERY cell the same lines: a table's cells have their own borderFills, so use it to change all the table lines at once (e.g. thicker grid).
    cells: [{row, col, border | border_fill_id, margin {left,right,top,bottom} (HWPUNIT; turns the cell's own margin on), vertical_align TOP|CENTER|BOTTOM,
    paragraphs: [{text | runs, char, format, para_pr_id, style_id | style, table, page_break, tab}, ...] (replaces the cell's content; same items as add_endnote_ext, so a cell paragraph can mix text, equations, pictures ...;
    "table": {"rows", "cols", "width", "height" (HWPUNIT), "border_fill_id"} puts a table in the paragraph, and `tableIndex` in the result lists the numbers of the tables made, in document order, for the next format_table_ext call)}].
    Ids you give must exist in the file's header or the call is refused. dry_run=true saves nothing."""
    cell_specs = cells or []
    plans = []
    for number, spec in enumerate(cell_specs):
        _check_keys(spec, _CELL_KEYS, f"cells[{number}]")
        if "row" not in spec or "col" not in spec:
            raise ToolInputError(f"cells[{number}] needs row and col")
        plans.append(_paragraph_plans(spec["paragraphs"], f"cells[{number}].paragraphs") if "paragraphs" in spec else None)

    def apply(doc: Any) -> dict[str, Any]:
        table = table_at(doc, table_index)
        made: list[Any] = []
        sz = table.element.find(f"{HP}sz")
        for first_row, first_col, last_row, last_col in merges or []:
            table.merge_cells(first_row, first_col, last_row, last_col)
        if column_widths is not None:
            sz.set("width", str(sum(column_widths)))
            table.set_column_widths(column_widths)
        elif width is not None:
            weights = _column_widths(table)
            sz.set("width", str(width))  # set_column_widths spreads the sz width over the weights
            table.set_column_widths(weights)
        if row_heights is not None:
            _set_row_heights(table, row_heights)
        if height is not None:
            table.set_height(height)
        if treat_as_char is not None:
            table.set_treat_as_char(treat_as_char)
        if page_break is not None:
            table.page_break = page_break
        if repeat_header is not None:
            table.repeat_header = repeat_header
        if out_margin:
            table.set_out_margins(**out_margin)
        if in_margin:
            table.set_in_margins(**in_margin)
        if position:
            table.set_position(**position)
        if border is not None or border_fill_id is not None:
            table.element.set("borderFillIDRef", str(border_fill_id) if border_fill_id is not None else _border_fill_id(doc, border, "border"))
            table.mark_dirty()
        bordered = 0
        if cells_border is not None:
            every = _border_fill_id(doc, cells_border, "cells_border")
            for entry in _each_cell(table):
                table.set_cell_border_fill(entry.row, entry.column, every)
                bordered += 1
        for number, (spec, plan) in enumerate(zip(cell_specs, plans)):
            try:
                cell = table.cell(spec["row"], spec["col"])
            except (IndexError, KeyError, ValueError) as error:
                raise ToolInputError(f"cells[{number}]: no cell at row {spec['row']}, col {spec['col']}") from error
            if "border" in spec or "border_fill_id" in spec:
                table.set_cell_border_fill(spec["row"], spec["col"], spec["border_fill_id"] if "border_fill_id" in spec else _border_fill_id(doc, spec["border"], f"cells[{number}].border"))
            if spec.get("margin"):
                set_cell_margins(cell, **spec["margin"])
            if "vertical_align" in spec:
                cell.vertical_align = spec["vertical_align"]
            if plan is not None:
                _fill_cell(doc, cell, plan, made, f"cells[{number}].paragraphs")
        if any("footnote" in run for plan in plans if plan for _, runs in plan for run in runs):
            _renumber_footnotes(doc)
        _refuse_dangling_ids(doc)
        result = {"table_index": table_index, "rows": table.row_count, "cols": table.column_count, "cellsFormatted": len(cell_specs), "cellsBordered": bordered}
        if made:
            result["tableIndex"] = table_indexes(doc, made)
        return result

    return _commit(filename, expected_revision, dry_run, apply)


def _each_cell(table: Any):
    """Grid entries, one per cell (a merged cell covers several grid positions)."""
    seen: set[Any] = set()  # the elements themselves, not id(): a kept reference cannot be freed and its id reused
    for entry in table.iter_grid():
        if entry.cell.element not in seen:
            seen.add(entry.cell.element)
            yield entry


def _set_row_heights(table: Any, heights: list[int]) -> None:
    """Like the library's set_row_heights, but 0 is allowed (Hancom stores cellSz height 0 for rows that fit their text)."""
    if len(heights) != table.row_count or any(isinstance(h, bool) or not isinstance(h, int) or h < 0 for h in heights):
        raise ToolInputError(f"row_heights needs {table.row_count} whole numbers >= 0 (HWPUNIT), one per row; got {heights!r}")
    for entry in _each_cell(table):
        start_row, _ = entry.cell.address
        span_row, span_col = entry.cell.span
        if span_row > 0 and span_col > 0:
            entry.cell.set_size(height=sum(heights[start_row:start_row + span_row]))
            entry.cell._clear_own_layout_caches()
    table.element.find(f"{HP}sz").set("height", str(sum(heights)))
    table.mark_dirty()


def _fill_cell(doc: Any, cell: Any, plans: list[tuple[dict[str, Any], list[dict[str, Any]]]], tables: list[Any], where: str) -> None:
    cell.set_text("")
    built = []
    for number, (spec, runs) in enumerate(plans):
        if number == 0:
            target = cell.paragraphs[0]
            blank = target.runs[0] if len(target.runs) == 1 and not (target.runs[0].text or "") else None
        else:
            target = cell.add_paragraph("")
            blank = target.runs[0]
        _build_paragraph(doc, target, spec, runs, tables, f"{where}[{number}]", first_run=blank)
        built.append((target, spec))
    _apply_shapes(doc, built)


def set_columns_ext(
    filename: str,
    columns: int = 2,
    gap: int = 2268,
    column_type: Literal["NEWSPAPER", "BALANCED_NEWSPAPER", "PARALLEL"] = "NEWSPAPER",
    layout: Literal["LEFT", "RIGHT", "MIRROR"] = "LEFT",
    column_widths: list[list[int]] | None = None,
    separator_type: str | None = None,
    separator_width: str | None = None,
    separator_color: str | None = None,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Set the column layout of a section (default: the first), including the separator line that set_page_setup cannot draw.
    columns: number of columns (1 turns columns off). gap: space between columns in HWPUNIT (7200 per inch, 283.465 = 1 mm; 2268 = 8 mm).
    column_widths: [[width, gap], ...] per column in HWPUNIT for unequal columns (omit for equal columns). separator_type (SOLID, DASH, DOT, ...),
    separator_width ("0.12 mm") and separator_color ("#000000") draw the line between columns; leave all three out for no line. dry_run=true saves nothing."""
    if columns < 1:
        raise ToolInputError("columns must be at least 1")

    def apply(doc: Any) -> dict[str, Any]:
        doc.page.set_columns(
            columns, section_index=section_index, col_type=column_type, layout=layout, same_size=column_widths is None, same_gap=gap,
            column_widths=[tuple(pair) for pair in column_widths] if column_widths else None,
            separator_type=separator_type, separator_width=separator_width, separator_color=separator_color,
        )
        return {"columns": columns, "section_index": section_index or 0}

    return _commit(filename, expected_revision, dry_run, apply)


def add_paragraphs_ext(
    filename: str,
    paragraphs: list[dict[str, Any]],
    before_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Add body paragraphs with exactly the shapes you give, never inheriting the previous paragraph's paragraph/character shape (add_paragraph does).
    paragraphs: a non-empty list of {"text": "...", "char": {...}} or {"runs": [{"text": "...", ...}, ...]} with optional "format": {...}, "para_pr_id", "style_id" or "style", "page_break": true, "tab": {"width", "leader", "type"}
    (same items as add_endnote_ext: runs are inline items - text, equation, latex, picture, footnote, hyperlink, bookmark, check_box, ruby, composed; "char_pr_id" per run).
    "table": {"rows", "cols", "width", "height" (HWPUNIT), "border_fill_id"} makes the paragraph hold a table (text or runs may be left out); `tableIndex` in the result lists the numbers of the tables made, in document order, to format with format_table_ext.
    A paragraph without ids/format gets the file's defaults (paragraph shape 0, style 0, character shape 0).
    An empty paragraph with a character option, e.g. {"text": "", "char": {"font_size": 3}}, is a 3 pt spacer line.
    before_index: insert before this body paragraph (0..count); omit to append at the end. Returns the index of the first new paragraph. Unknown ids are refused. dry_run=true saves nothing."""
    plans = _paragraph_plans(paragraphs, "paragraphs")

    def apply(doc: Any) -> dict[str, Any]:
        total = len(doc.paragraphs)
        tables: list[Any] = []
        if before_index is not None and not 0 <= before_index <= total:
            raise ToolInputError(f"before_index {before_index} is out of range (0..{total})")
        anchor = doc.paragraphs[before_index] if before_index is not None and before_index < total else None
        if anchor is not None and _holds_section_definition(anchor):
            raise ToolInputError(f"before_index {before_index}: that paragraph holds the section definition (page setup, columns), "
                                 "which must stay first; use before_index 1 or later")
        built = []
        for number, (spec, runs) in enumerate(plans):
            created = doc.add_paragraph("", inherit_style=False, **({"section": anchor.section} if anchor is not None else {}))
            _build_paragraph(doc, created, spec, runs, tables, f"paragraphs[{number}]", first_run=created.runs[0] if created.runs else None)
            built.append((created, spec))
        _apply_shapes(doc, built)
        if anchor is not None:
            for created, _ in built:
                anchor.element.addprevious(created.element)
            anchor.section.mark_dirty()
        if any("footnote" in run for _, runs in plans for run in runs):
            _renumber_footnotes(doc)
        _refuse_dangling_ids(doc)
        result = {"added": len(built), "firstParagraphIndex": before_index if before_index is not None else total}
        if tables:
            result["tableIndex"] = table_indexes(doc, tables)
        return result

    return _commit(filename, expected_revision, dry_run, apply)
