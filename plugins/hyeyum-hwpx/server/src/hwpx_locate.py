"""문단 주소: 본문·표 칸·미주·각주·머리말/꼬리말의 문단 하나를 `hwpx_read_layout`이 쓰는 `자리` 이름으로 찾는다.

글 바꾸기·문단 나누기·개체 지우기처럼 이미 있는 문서를 고치는 도구가 같은 인수(paragraph_index | table_index+row+col+cell_paragraph_index |
endnote_number+endnote_paragraph_index | footnote_… | header_index+header_paragraph_index | footer_…)로 문단을 가리키게 하는 공용 바탕이다.
`section_index`를 주지 않으면 번호는 문서 전체에서 센다(다른 쓰기 도구의 paragraph_index와 같다); 주면 그 구역 안에서 센다(`hwpx_read_layout`의 section과 같다).
새 모듈은 hwpx_common에서만 가져온다(hwpx_edit·hwpx_inline이 이 모듈을 가져다 쓴다).
"""
from typing import Any, Iterator

from hwpx.oxml.namespaces import HP
from hwpx.oxml.paragraph import HwpxOxmlParagraph

from hwpx_common import ToolInputError, _holds_section_definition

#: 문단 주소 인수(이름은 hwpx_read_layout의 자리 이름과 같다). 묶음마다 대표 인수가 하나 있고 나머지는 그 묶음 안의 보조 인수다.
ADDRESS_ARGS = (
    "paragraph_index", "table_index", "row", "col", "cell_paragraph_index", "endnote_number", "endnote_paragraph_index",
    "footnote_number", "footnote_paragraph_index", "header_index", "header_paragraph_index", "footer_index", "footer_paragraph_index",
)
_GROUPS = {  # 묶음 이름: (대표 인수, 그 묶음에서 쓸 수 있는 인수)
    "body": ("paragraph_index", {"paragraph_index"}),
    "cell": ("table_index", {"table_index", "row", "col", "cell_paragraph_index"}),
    "endnote": ("endnote_number", {"endnote_number", "endnote_paragraph_index"}),
    "footnote": ("footnote_number", {"footnote_number", "footnote_paragraph_index"}),
    "header": ("header_index", {"header_index", "header_paragraph_index"}),
    "footer": ("footer_index", {"footer_index", "footer_paragraph_index"}),
}
SCOPES = ("body", "table_cells", "endnotes", "footnotes", "headers_footers")

#: 도구 설명(영어) 안의 {ADDRESS} 자리에 들어간다(`addressed`).
ADDRESS_DOC = (
    "Paragraph address - give exactly one group, names as in hwpx_read_layout: body `paragraph_index` (0-based body paragraph; with `section_index` it counts inside that section, without it in the whole document); "
    "table cell `table_index` (document-wide table number as in format_table_ext) + `row` + `col` (cell address, 0-based) + `cell_paragraph_index` (default 0); "
    "endnote `endnote_number` (1-based, document order) + `endnote_paragraph_index` (default 0); footnote `footnote_number` + `footnote_paragraph_index`; "
    "header `header_index` (0-based) + `header_paragraph_index` (default 0); footer `footer_index` + `footer_paragraph_index`. Paragraphs inside text boxes have no address."
)


def addressed(fn):
    """도구 함수 설명의 {ADDRESS}를 ADDRESS_DOC으로 바꾼다(여러 도구가 같은 문장을 쓴다)."""
    fn.__doc__ = fn.__doc__.replace("{ADDRESS}", ADDRESS_DOC)
    return fn


def paragraph_text(paragraph: Any) -> str:
    """문단 자신의 글(run 직속 글만): insert_inline_ext·format_text_ext가 글자 위치를 세는 것과 같은 글."""
    return "".join(run.text or "" for run in paragraph.runs)


def holds_table(paragraph: Any) -> bool:
    return paragraph.element.find(f"{HP}run/{HP}tbl") is not None


def holds_section_definition(paragraph: Any) -> bool:
    return _holds_section_definition(paragraph)


def all_tables(doc: Any) -> list[Any]:
    """Every table of the document, numbered as hwpx_read_layout numbers them: sections in order, and inside a section every hp:tbl in document order
    (a table inside another one's cell comes right after its parent; tables in headers, footers and notes are counted, but not the copy of a header/footer
    that is kept inside the section definition: it is rewritten from the header/footer itself when the file is saved)."""
    tables = []
    for section in doc.sections:
        for element in section.element.iter(f"{HP}tbl"):
            if any(a.tag == f"{HP}secPr" for a in element.iterancestors()):
                continue
            host = next(a for a in element.iterancestors() if a.tag == f"{HP}p")
            tables.append(next(t for t in HwpxOxmlParagraph(host, section).tables if t.element is element))
    return tables


def table_at(doc: Any, table_index: int) -> Any:
    """Table number *table_index* as hwpx_read_layout and format_table_ext count it (see all_tables)."""
    tables = all_tables(doc)
    if isinstance(table_index, bool) or not 0 <= table_index < len(tables):
        raise ToolInputError(f"invalid table_index: {table_index} (the file has {len(tables)} table(s))")
    return tables[table_index]


def table_indexes(doc: Any, elements: list[Any]) -> list[int]:
    """Numbers (as table_at counts them) of the tables whose elements are given."""
    tables = all_tables(doc)
    return [next(index for index, table in enumerate(tables) if table.element is element) for element in elements]


def address_group(**address: Any) -> str:
    """Which group of address arguments is given (exactly one is allowed); anything else is refused with the reason."""
    unknown = sorted(set(address) - set(ADDRESS_ARGS))
    if unknown:
        raise ToolInputError(f"unknown address argument(s) {unknown}; allowed: {list(ADDRESS_ARGS)}")
    given = {key for key, value in address.items() if value is not None}
    leaders = [name for name, (leader, _) in _GROUPS.items() if leader in given]
    if len(leaders) != 1:
        names = [leader for leader, _ in _GROUPS.values()]
        raise ToolInputError(
            f"give exactly one paragraph address group, started by one of {names}"
            + (f"; got {[_GROUPS[name][0] for name in leaders]}" if leaders else "; got none")
        )
    group = leaders[0]
    stray = sorted(given - _GROUPS[group][1])
    if stray:
        raise ToolInputError(f"{stray} do not go with {_GROUPS[group][0]}; allowed in this group: {sorted(_GROUPS[group][1])}")
    if group == "cell" and ("row" not in given or "col" not in given):
        raise ToolInputError("table_index needs row and col")
    return group


def _sections(doc: Any, section_index: int | None) -> list[Any]:
    sections = list(doc.sections)
    if section_index is None:
        return sections
    if isinstance(section_index, bool) or not 0 <= section_index < len(sections):
        raise ToolInputError(f"invalid section_index {section_index!r} (the file has {len(sections)} sections: 0-{len(sections) - 1})")
    return [sections[section_index]]


def _wrap(element: Any, section: Any) -> HwpxOxmlParagraph:
    return HwpxOxmlParagraph(element, section)


def _own_paragraphs(box: Any) -> list[Any]:
    """The paragraphs directly in the subList of a note, header or footer (what hwpx_read_layout numbers)."""
    sub = box.find(f"{HP}subList")
    return sub.findall(f"{HP}p") if sub is not None else []


def _header_footer_boxes(section: Any, tag: str) -> list[Any]:
    """Header/footer controls of the section in document order, without the copy that sits inside the section definition."""
    return [box for box in section.element.iter(f"{HP}{tag}") if not any(a.tag == f"{HP}secPr" for a in box.iterancestors())]


def _boxes(sections: list[Any], tag: str) -> Iterator[tuple[Any, Any]]:
    for section in sections:
        if tag in ("header", "footer"):
            for box in _header_footer_boxes(section, tag):
                yield section, box
        else:
            for box in section.element.iter(f"{HP}{tag}"):
                yield section, box


def _pick(items: list[Any], index: int, what: str, base: int) -> Any:
    if isinstance(index, bool) or not 0 <= index < len(items):
        raise ToolInputError(f"invalid {what} {index + base!r} ({len(items)} found, numbered {base}-{len(items) - 1 + base})" if items else f"invalid {what} {index + base!r} (none found)")
    return items[index]


def resolve_paragraph(doc: Any, section_index: int | None = None, **address: Any) -> HwpxOxmlParagraph:
    """The paragraph named by one address group (see ADDRESS_DOC). Refusals are ToolInputError with the argument name and the valid range."""
    group = address_group(**address)
    sections = _sections(doc, section_index)
    if group == "body":
        paragraphs = [p for section in sections for p in section.paragraphs]
        index = address["paragraph_index"]
        if isinstance(index, bool) or not 0 <= index < len(paragraphs):
            raise ToolInputError(f"invalid paragraph_index {index!r} ({len(paragraphs)} body paragraphs, numbered 0-{len(paragraphs) - 1})")
        return paragraphs[index]
    if group == "cell":
        table = table_at(doc, address["table_index"])
        try:
            cell = table.cell(address["row"], address["col"])
        except (IndexError, KeyError, ValueError) as error:
            raise ToolInputError(f"no cell at row {address['row']}, col {address['col']} in table {address['table_index']}") from error
        index = address.get("cell_paragraph_index") or 0
        if isinstance(index, bool) or not 0 <= index < len(cell.paragraphs):
            raise ToolInputError(f"invalid cell_paragraph_index: {index!r} (the cell has {len(cell.paragraphs)} paragraph(s))")
        return cell.paragraphs[index]
    tag = {"endnote": "endNote", "footnote": "footNote", "header": "header", "footer": "footer"}[group]
    base = 1 if group in ("endnote", "footnote") else 0
    boxes = list(_boxes(sections, tag))
    leader = _GROUPS[group][0]
    section, box = _pick(boxes, address[leader] - base, leader, base)
    inner = address.get(f"{group}_paragraph_index") or 0
    paragraphs = _own_paragraphs(box)
    if isinstance(inner, bool) or not 0 <= inner < len(paragraphs):
        raise ToolInputError(f"invalid {group}_paragraph_index: {inner!r} (the {group} has {len(paragraphs)} paragraph(s))")
    return _wrap(paragraphs[inner], section)


def siblings(paragraph: Any) -> list[Any]:
    """The paragraph elements in the same container (section body, cell, note, header or footer), in order."""
    parent = paragraph.element.getparent()
    return [child for child in parent if child.tag == f"{HP}p"]


def next_paragraph(paragraph: Any) -> Any | None:
    """The next paragraph element in the same container, or None."""
    items = siblings(paragraph)
    position = next(i for i, element in enumerate(items) if element is paragraph.element)
    return items[position + 1] if position + 1 < len(items) else None


def iter_paragraphs(doc: Any, scopes: tuple[str, ...] | list[str] | None = None, section_index: int | None = None) -> Iterator[tuple[dict[str, Any], HwpxOxmlParagraph]]:
    """Every paragraph of the chosen *scopes* (default all of SCOPES) as (address, paragraph), in document order within each scope.
    The address has the argument names of resolve_paragraph, so it can be used to point at the paragraph again."""
    chosen = tuple(scopes) if scopes is not None else SCOPES
    bad = [scope for scope in chosen if scope not in SCOPES]
    if bad:
        raise ToolInputError(f"unknown scope(s) {bad}; allowed: {list(SCOPES)}")
    sections = _sections(doc, section_index)
    if "body" in chosen:
        number = 0
        for section in sections:
            for paragraph in section.paragraphs:
                yield {"paragraph_index": number}, paragraph
                number += 1
    if "table_cells" in chosen:
        tables = all_tables(doc)
        allowed = {section.element for section in sections}
        for table_index, table in enumerate(tables):
            section = table.paragraph.section
            if section.element not in allowed:
                continue
            for tr in table.element.findall(f"{HP}tr"):
                for tc in tr.findall(f"{HP}tc"):
                    where = tc.find(f"{HP}cellAddr")
                    for inner, p in enumerate(_own_paragraphs(tc)):
                        yield {"table_index": table_index, "row": int(where.get("rowAddr")), "col": int(where.get("colAddr")), "cell_paragraph_index": inner}, _wrap(p, section)
    for scope, tag in (("endnotes", "endNote"), ("footnotes", "footNote"), ("headers_footers", "header"), ("headers_footers", "footer")):
        if scope not in chosen:
            continue
        key = {"endNote": "endnote", "footNote": "footnote", "header": "header", "footer": "footer"}[tag]
        base = 1 if key in ("endnote", "footnote") else 0
        for number, (section, box) in enumerate(_boxes(sections, tag), start=base):
            for inner, p in enumerate(_own_paragraphs(box)):
                yield {f"{key}_{'number' if base else 'index'}": number, f"{key}_paragraph_index": inner}, _wrap(p, section)
