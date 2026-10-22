"""표 구조 쓰기 도구: 행·열 삽입/삭제와 칸 나누기(edit_table_structure_ext), 표 나누기(split_table_ext), 다음 표와 합치기(merge_table_with_next_ext).

표 번호는 format_table_ext·hwpx_read_layout(part="tables")와 같다(hwpx_locate.table_at). 쓰기 절차는 hwpx_common._commit.
hwpx_edit는 가져오지 않는다(순환 import 방지).
"""
from copy import deepcopy
from typing import Any

from hwpx.oxml._document_primitives import _clear_paragraph_layout_cache
from hwpx.oxml.namespaces import HP
from hwpx.table_patch import TableStructureError, _merge_table_rows, _split_table_rows
from lxml import etree

from hwpx_common import ToolInputError, _check_keys, _commit, _refuse_dangling_ids, _renumber_endnotes, _renumber_footnotes
from hwpx_locate import table_at

#: op 이름 -> (필수 인수, 선택 인수)
_OPS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "insert_rows": (frozenset({"row"}), frozenset({"count", "side", "blank"})),
    "insert_columns": (frozenset({"column"}), frozenset({"count", "side", "blank", "keep_width"})),
    "delete_rows": (frozenset({"rows"}), frozenset()),
    "delete_columns": (frozenset({"columns"}), frozenset()),
    "split_cell": (frozenset({"row", "col"}), frozenset({"rows", "cols"})),
}


def _whole(value: Any, label: str, low: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise ToolInputError(f"{label} must be a whole number >= {low}, got {value!r}")
    return value


def _lines(value: Any, label: str) -> list[int]:
    items = [value] if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(items, list) or not items:
        raise ToolInputError(f"{label} must be a whole number or a non-empty list of them, got {value!r}")
    return [_whole(item, label) for item in items]


def _check_ops(ops: Any) -> list[dict[str, Any]]:
    if not isinstance(ops, list) or not ops:
        raise ToolInputError("ops must be a non-empty list of operations")
    for number, op in enumerate(ops):
        label = f"ops[{number}]"
        if not isinstance(op, dict) or op.get("op") not in _OPS:
            raise ToolInputError(f"{label}.op must be one of {sorted(_OPS)}, got {op.get('op') if isinstance(op, dict) else op!r}")
        required, optional = _OPS[op["op"]]
        _check_keys({key: value for key, value in op.items() if key != "op"}, required | optional, f"{label} ({op['op']})")
        missing = sorted(required - set(op))
        if missing:
            raise ToolInputError(f"{label} ({op['op']}) needs {missing}")
        if op["op"] in ("insert_rows", "insert_columns"):
            _whole(op["row" if op["op"] == "insert_rows" else "column"], f"{label}.{'row' if op['op'] == 'insert_rows' else 'column'}")
            _whole(op.get("count", 1), f"{label}.count", 1)
            sides = ("below", "above") if op["op"] == "insert_rows" else ("right", "left")
            if op.get("side", sides[0]) not in sides:
                raise ToolInputError(f"{label}.side must be one of {list(sides)}, got {op['side']!r}")
            for flag in ("blank", "keep_width"):
                if flag in op and not isinstance(op[flag], bool):
                    raise ToolInputError(f"{label}.{flag} must be true or false, got {op[flag]!r}")
        elif op["op"] == "split_cell":
            _whole(op["row"], f"{label}.row")
            _whole(op["col"], f"{label}.col")
            for key in ("rows", "cols"):
                if not 1 <= _whole(op.get(key, 1), f"{label}.{key}", 1) <= 63:
                    raise ToolInputError(f"{label}.{key} must be 1-63")
            if op.get("rows", 1) == 1 and op.get("cols", 1) == 1:
                raise ToolInputError(f"{label}: rows and cols are both 1 - nothing to split into")
        else:
            _lines(op["rows" if op["op"] == "delete_rows" else "columns"], f"{label}.{'rows' if op['op'] == 'delete_rows' else 'columns'}")
    return ops


def _keep_width(table: Any, width: int, number: int) -> None:
    """Give the table its old total *width* back by shrinking all columns in proportion (what insert_columns grew)."""
    widths = _column_widths(table.element)
    missing = [c for c in range(table.column_count) if c not in widths]
    if missing:
        raise ToolInputError(f"ops[{number}].keep_width cannot tell the width of column(s) {missing}: they are covered only by merged cells")
    table.element.find(f"{HP}sz").set("width", str(width))
    table.set_column_widths([widths[c] for c in range(table.column_count)])


def edit_table_structure_ext(
    filename: str,
    table_index: int,
    ops: list[dict[str, Any]],
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Change the structure of an existing table the way Hancom does: insert or delete rows and columns, split a cell into rows x columns. Applied in the order given, all or nothing (a refused step saves nothing).
    table_index: document-wide table number, as in format_table_ext and hwpx_read_layout part="tables" (nested tables count after their parent). Rows and columns are 0-based grid positions; the numbers of later steps refer to the table as the earlier steps left it.
    ops: a non-empty list; each item has "op" and its arguments:
    {"op": "insert_rows", "row": R, "count": 1, "side": "below"|"above", "blank": true} - new rows next to row R, each as high as R and with the cell formats of R; blank=true (default, as Hancom does) leaves each new cell with one empty paragraph of that format, blank=false copies R's text too (refused when R holds an equation, footnote, bookmark or hyperlink);
    {"op": "insert_columns", "column": C, "count": 1, "side": "right"|"left", "blank": true, "keep_width": false} - the same for columns; each new column is as wide as C and the table grows by it, unless keep_width=true: then all columns shrink in proportion so that the table keeps its width (use it for a table that already fills the page);
    {"op": "delete_rows", "rows": [R, ...]} and {"op": "delete_columns", "columns": [C, ...]} (the table keeps its width; deleting every row or column is refused - delete the table instead);
    {"op": "split_cell", "row": R, "col": C, "rows": 1, "cols": 1} - split the cell at (R, C), 2-63 each; a cell that was merged is split back; the content stays in the first part.
    A cell merged across new rows or columns grows over them. A table that holds another table is refused. Deleting rows or columns deletes what is in their cells; endnotes and footnotes in them are removed and the others renumbered, pictures no longer used are dropped (counted in the result). To merge cells use format_table_ext(merges=). The table's stored height is not recalculated here (Hancom does that when it lays the page out).
    Returns `steps` (what each op did), the table's `rows` and `cols` afterwards, and `removedNotes` / `removedPictures`. dry_run=true saves nothing."""
    steps = _check_ops(ops)

    def apply(doc: Any) -> dict[str, Any]:
        table = table_at(doc, table_index)
        count = lambda tags: sum(1 for tag in tags for _ in table.element.iter(f"{HP}{tag}"))  # noqa: E731
        notes_before, pictures_before = count(("endNote", "footNote")), count(("pic",))
        done = []
        for number, op in enumerate(steps):
            name = op["op"]
            try:
                if name == "insert_rows":
                    table.insert_rows(op["row"], op.get("count", 1), side=op.get("side", "below"), blank=op.get("blank", True))
                elif name == "insert_columns":
                    width = int(table.element.find(f"{HP}sz").get("width") or 0)
                    table.insert_columns(op["column"], op.get("count", 1), side=op.get("side", "right"), blank=op.get("blank", True))
                    if op.get("keep_width"):
                        _keep_width(table, width, number)
                elif name == "delete_rows":
                    table.delete_rows(_lines(op["rows"], "rows"))
                elif name == "delete_columns":
                    table.delete_columns(_lines(op["columns"], "columns"))
                else:
                    table.split_cell(op["row"], op["col"], rows=op.get("rows", 1), cols=op.get("cols", 1))
            except ToolInputError:
                raise
            except Exception as error:  # the library's refusal names the reason; say which step it was
                raise ToolInputError(f"ops[{number}] ({name}) was refused: {error}") from error
            done.append({"op": name, "rows": table.row_count, "cols": table.column_count})
        removed_notes, removed_pictures = notes_before - count(("endNote", "footNote")), pictures_before - count(("pic",))
        if removed_notes:
            _renumber_endnotes(doc)
            _renumber_footnotes(doc)
        if removed_pictures:
            doc.media.remove_unused_images()
        _refuse_dangling_ids(doc)
        return {"steps": done, "rows": table.row_count, "cols": table.column_count, "tableIndex": table_index, "removedNotes": removed_notes, "removedPictures": removed_pictures}

    return _commit(filename, expected_revision, dry_run, apply)


# ---------------------------------------------------------------- split_table_ext / merge_table_with_next_ext

def _body_level(table: Any, what: str) -> Any:
    """The paragraph element holding *table* if it is a body paragraph of its section (not in a cell, note, header or footer)."""
    paragraph = table.paragraph
    if paragraph.element.getparent() is not paragraph.section.element:
        raise ToolInputError(f"{what} works on a table in a body paragraph, not on one inside a table cell, note, header or footer")
    return paragraph.element


def _inline(table: Any, table_index: int) -> None:
    pos = table.element.find(f"{HP}pos")
    if pos is None or pos.get("treatAsChar") != "1":
        raise ToolInputError(f"table {table_index} floats (it is not treated as a character): two floating halves would lie on top of each other - make it inline first with format_table_ext(treat_as_char=true)")
    zones = table.element.find(f"{HP}cellzoneList")
    if zones is not None and len(zones):
        raise ToolInputError(f"table {table_index} has cell zones (cell-wide formatting ranges), which cannot be divided safely")


def _alone(paragraph: Any, table: Any) -> bool:
    """Whether the paragraph holds the table and nothing else (empty text elements and the line cache do not count)."""
    for child in paragraph:
        if child.tag == f"{HP}linesegarray":
            continue
        if child.tag != f"{HP}run":
            return False
        for item in child:
            if item is table:
                continue
            if item.tag != f"{HP}t" or (item.text or "").strip() or len(item):
                return False
    return True


def _put(table: Any, xml: str) -> None:
    """Make *table* (an element) the table described by *xml*, in place, so that wrappers to it stay valid."""
    new = etree.fromstring(xml)
    for child in list(table):
        table.remove(child)
    table.attrib.clear()
    table.attrib.update(new.attrib)
    table.text = new.text
    table.extend(list(new))


def _xml(table: Any) -> str:
    return etree.tostring(table, encoding="unicode", with_tail=False)


def _row_heights(table: Any) -> list[int]:
    """The stored height of each row: its tallest single-row cell."""
    heights: dict[int, int] = {}
    for tc in table.iter(f"{HP}tc"):
        if int(tc.find(f"{HP}cellSpan").get("rowSpan") or 1) == 1:
            row = int(tc.find(f"{HP}cellAddr").get("rowAddr"))
            heights[row] = max(heights.get(row, 0), int(tc.find(f"{HP}cellSz").get("height") or 0))
    return [heights.get(row, 0) for row in range(int(table.get("rowCnt")))]


def _declared_height(table: Any) -> int:
    return int(table.find(f"{HP}sz").get("height") or 0)


def _set_height(table: Any, height: int) -> None:
    table.find(f"{HP}sz").set("height", str(max(height, 0)))


def _column_widths(table: Any) -> dict[int, int]:
    return {int(tc.find(f"{HP}cellAddr").get("colAddr")): int(tc.find(f"{HP}cellSz").get("width") or 0)
            for tc in table.iter(f"{HP}tc") if int(tc.find(f"{HP}cellSpan").get("colSpan") or 1) == 1}


def _largest_id(section: Any, tag: str) -> int:
    return max((int(e.get("id")) for e in section.element.iter(f"{HP}{tag}") if (e.get("id") or "").isdigit()), default=0)


def split_table_ext(
    filename: str,
    table_index: int,
    row: int,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Split one table into two tables in front of row `row` (Hancom's 표 나누기): rows 0..row-1 stay in the table, rows `row`.. become a new table in a new paragraph right after it.
    table_index: document-wide table number as in format_table_ext and hwpx_read_layout part="tables". row: 1..rows-1 (0-based; the first row of the lower table).
    Refused: a table inside a table cell, note, header or footer; a table that floats (not treated as a character - make it inline first with format_table_ext); a table that holds another table or has cell zones; a merged cell reaching over the cut.
    The lower table keeps the column layout; its rows are renumbered from 0; the stored table height is shared between the two in proportion to their row heights (Hancom recalculates it when it lays the page out). A caption stays with the upper table.
    The new paragraph copies the paragraph shape and style of the table's paragraph and holds only the lower table. Returns the numbers of the two tables (the lower one is table_index + 1), their row counts and the new paragraph's number in its section. dry_run=true saves nothing."""
    if isinstance(row, bool) or not isinstance(row, int):
        raise ToolInputError(f"row must be a whole number, got {row!r}")

    def apply(doc: Any) -> dict[str, Any]:
        table = table_at(doc, table_index)
        host = _body_level(table, "split_table_ext")
        _inline(table, table_index)
        element, section = table.element, table.paragraph.section
        height, heights = _declared_height(element), _row_heights(element)
        try:
            top_xml, bottom_xml = _split_table_rows(_xml(element), row)
        except TableStructureError as error:
            raise ToolInputError(f"row {row} cannot be cut: {error}") from error
        bottom = etree.fromstring(bottom_xml)
        for caption in bottom.findall(f"{HP}label"):
            bottom.remove(caption)
        weight = sum(heights[:row]) / sum(heights) if sum(heights) else row / len(heights)
        top_height = round(height * weight)
        _put(element, top_xml)
        _set_height(element, top_height)
        _set_height(bottom, height - top_height)
        for name in ("id", "instid"):
            if bottom.get(name, "").isdigit():
                bottom.set(name, str(_largest_id(section, "tbl") + 1))
        if _alone(host, element):
            fresh = deepcopy(host)
            lower = next(fresh.iter(f"{HP}tbl"))
            lower.getparent().replace(lower, bottom)
        else:  # the paragraph holds more than the table: the lower table gets a paragraph of its own
            fresh = host.makeelement(host.tag, {key: ("0" if key in ("pageBreak", "columnBreak") else value) for key, value in host.attrib.items()})
            run = element.getparent()
            lower_run = fresh.makeelement(run.tag, dict(run.attrib))
            lower_run.append(bottom)
            fresh.append(lower_run)
        for stale in fresh.findall(f"{HP}linesegarray"):
            fresh.remove(stale)
        ids = [int(p.get("id")) for p in section.element.iter(f"{HP}p") if (p.get("id") or "").isdigit()]
        if "id" in fresh.attrib:
            fresh.set("id", str(max(ids, default=0) + 1))
        host.addnext(fresh)
        _clear_paragraph_layout_cache(host)
        section.mark_dirty()
        _refuse_dangling_ids(doc)
        number = [p for p in section.element if p.tag == f"{HP}p"].index(fresh)
        return {"upperTable": table_index, "lowerTable": table_index + 1, "upperRows": int(element.get("rowCnt")), "lowerRows": int(bottom.get("rowCnt")), "newParagraphIndex": number}

    return _commit(filename, expected_revision, dry_run, apply)


def merge_table_with_next_ext(filename: str, table_index: int, dry_run: bool = False, expected_revision: str | None = None) -> dict[str, Any]:
    """Join a table with the table right below it into one table (Hancom's 표 합치기): the rows of the lower table are appended to this one and the lower table's paragraph is removed.
    table_index: document-wide table number of the UPPER table, as in format_table_ext. The lower table must be alone in the body paragraph right after the upper table's paragraph (no text or other objects, no paragraph in between), both tables must be inline (treated as characters) body tables with the same columns (same count and same widths).
    The upper table's settings stay (border fill, page-break and header-row settings of the lower table are dropped - `warnings` says so when they differed); the stored heights are added. Returns the row count of the merged table. dry_run=true saves nothing."""

    def apply(doc: Any) -> dict[str, Any]:
        table = table_at(doc, table_index)
        host = _body_level(table, "merge_table_with_next_ext")
        _inline(table, table_index)
        element, section = table.element, table.paragraph.section
        following = host.getnext()
        lower = following.find(f"{HP}run/{HP}tbl") if following is not None and following.tag == f"{HP}p" else None
        if lower is None or not _alone(following, lower):
            raise ToolInputError("the paragraph right after the table's paragraph must hold the next table and nothing else (no text, no other object)")
        pos = lower.find(f"{HP}pos")
        if pos is None or pos.get("treatAsChar") != "1":
            raise ToolInputError("the lower table floats (it is not treated as a character); make it inline first with format_table_ext(treat_as_char=true)")
        upper_widths, lower_widths = _column_widths(element), _column_widths(lower)
        shared = set(upper_widths) & set(lower_widths)
        if element.get("colCnt") != lower.get("colCnt") or not shared or any(upper_widths[c] != lower_widths[c] for c in shared):
            raise ToolInputError(f"the tables do not share their columns: upper has {element.get('colCnt')} columns with widths {sorted(upper_widths.items())}, lower {lower.get('colCnt')} with {sorted(lower_widths.items())}")
        warnings = [f"the lower table's {name} ({lower.get(name)!r}) differed from the upper table's ({element.get(name)!r}) and was dropped"
                    for name in ("borderFillIDRef", "pageBreak", "repeatHeader") if lower.get(name) != element.get(name)]
        height = _declared_height(element) + _declared_height(lower)
        try:
            merged = _merge_table_rows(_xml(element), _xml(lower))
        except TableStructureError as error:
            raise ToolInputError(f"the tables cannot be merged: {error}") from error
        _put(element, merged)
        _set_height(element, height)
        section.element.remove(following)
        _clear_paragraph_layout_cache(host)
        section.mark_dirty()
        _renumber_endnotes(doc)
        _renumber_footnotes(doc)
        _refuse_dangling_ids(doc)
        return {"table": table_index, "rows": int(element.get("rowCnt")), "warnings": warnings}

    return _commit(filename, expected_revision, dry_run, apply)
