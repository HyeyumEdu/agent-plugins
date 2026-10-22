"""글 수정: 이미 있는 문서의 글을 바꾸고(replace_text_ext, edit_paragraph_text_ext), 문단을 나누고 합치고(split_paragraph_ext,
merge_paragraphs_ext), 개인정보를 가린다(redact_text_ext). 본문·표 칸·미주·각주·머리말/꼬리말 어디에든 쓴다.

글을 바꾸는 세 도구는 문단 하나의 글자 범위 [start, end)를 새 글로 바꾸는 splice_text를 같이 쓴다. 글자 위치는 insert_inline_ext와 같이
hwpx_locate.paragraph_text의 인덱스다(탭·줄바꿈·특수 공백 1글자, 개체 0글자). hwpx_edit는 가져오지 않는다(순환 방지).
"""
import re
from typing import Any

from hwpx.oxml._document_primitives import _TEXT_INLINE_ATOMS, _clear_paragraph_layout_cache, _element_local_name, _paragraph_id, _sanitize_text
from hwpx.oxml.namespaces import HP
from hwpx.oxml.paragraph import HwpxOxmlParagraph
from hwpx_automation.office.compliance.pii import PIIPolicy, detect_pii

from hwpx_common import ToolInputError, _commit, _refuse_dangling_ids
from hwpx_inline import _neighbor_char, build_items
from hwpx_locate import (
    ADDRESS_ARGS, SCOPES, address_group, addressed, holds_section_definition, holds_table, iter_paragraphs, next_paragraph, paragraph_text,
    resolve_paragraph,
)
from hwpx_runs import split_at

_ATOM_CHARS = frozenset("\t\n\u00a0\u3000\u00ad")  # the characters Hancom stores as elements inside hp:t (special=true writes them so)
_LOCATIONS = 30  # replace_text_ext lists this many places
_FINDINGS = 100  # redact_text_ext lists this many findings
_SCOPE_OF = {"paragraph_index": "body", "table_index": "table_cells", "endnote_number": "endnotes", "footnote_number": "footnotes", "header_index": "headers_footers", "footer_index": "headers_footers"}
_INNER = {"body": "paragraph_index", "cell": "cell_paragraph_index", "endnote": "endnote_paragraph_index", "footnote": "footnote_paragraph_index", "header": "header_paragraph_index", "footer": "footer_paragraph_index"}


class _Unchanged(Exception):
    """Raised by an apply that found nothing to change, with the result to give back."""

    def __init__(self, result: dict[str, Any]):
        super().__init__("unchanged")
        self.result = result


def _commit_changes(filename: str, expected_revision: str | None, dry_run: bool, apply: Any) -> dict[str, Any]:
    """_commit with two differences. An apply that finds nothing to change does not save: the save would replace the .bak (the state before the last real edit) by
    the unchanged file. And the save report's semanticDiff and the text snippets in its section reports are left out: they quote the paragraphs before and
    after the edit, which would bring back the text that upstream's readers mask (and the personal information redact_text_ext has just masked)."""
    try:
        result = _commit(filename, expected_revision, dry_run, apply)
    except _Unchanged as nothing:
        return {**nothing.result, "filename": filename, "dryRun": dry_run, "saved": False}
    result.pop("semanticDiff", None)
    report = result.get("verificationReport")
    if isinstance(report, dict):
        report.pop("semanticDiff", None)
        for section in report.get("sectionReports") or ():  # the per-section check quotes placeholder-like and suspicious snippets of the saved text
            section.pop("placeholderExamples", None)
            section.pop("suspiciousPatterns", None)
    return result


def _address(arguments: dict[str, Any]) -> dict[str, Any]:
    """The paragraph address given to a tool (its locals()), checked for exactly one group."""
    address = {key: value for key, value in arguments.items() if key in ADDRESS_ARGS}
    address_group(**address)
    return address


def _check_scopes(scopes: list[str] | None) -> tuple[str, ...]:
    if scopes is None:
        return SCOPES
    if not isinstance(scopes, list) or not scopes or any(scope not in SCOPES for scope in scopes):
        raise ToolInputError(f"scopes must be a non-empty list of {list(SCOPES)}, got {scopes!r}")
    return tuple(scopes)


def _check_flag(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ToolInputError(f"{name} must be true or false")


# ---------------------------------------------------------------- splice_text

def _slots(paragraph: Any):
    """(owner, "text" | "tail", start) for every piece of plain text in the paragraph's runs: an hp:t's own text and the text after each child
    of an hp:t (tabs and the like), with the character position the piece starts at (counted as paragraph_text counts)."""
    seen = 0
    for run in paragraph.element.findall(f"{HP}run"):
        for t in run.findall(f"{HP}t"):
            if t.text:
                yield t, "text", seen
                seen += len(t.text)
            for child in t:
                seen += 1 if _element_local_name(child) in _TEXT_INLINE_ATOMS else len("".join(child.itertext()))
                if child.tail:
                    yield child, "tail", seen
                    seen += len(child.tail)


def _empty_run(root: Any, char: str | None) -> Any:
    run = root.makeelement(f"{HP}run", {"charPrIDRef": char or "0"})
    run.append(run.makeelement(f"{HP}t", {}))
    return run


def _edit_in_place(paragraph: Any, start: int, end: int, text: str) -> bool:
    """Change [start, end) inside one piece of plain text (the run, its shape and the tabs around stay as they are); False when the range is not inside one piece.
    An insertion has to lie strictly inside a piece: at a piece's edge an object may stand between the pieces, and the general path puts the text behind it."""
    for owner, attribute, at in _slots(paragraph):
        value = getattr(owner, attribute)
        if (at <= start and end <= at + len(value)) if start < end else (at < start < at + len(value)):
            changed = value[:start - at] + _sanitize_text(text) + value[end - at:]
            setattr(owner, attribute, changed or None)
            if not changed and attribute == "text" and not len(owner):  # a deletion emptied the hp:t: drop it, and its run unless it is the paragraph's last
                run = owner.getparent()
                run.remove(owner)
                root = paragraph.element
                if len(run) == 0:
                    if len(root.findall(f"{HP}run")) > 1:
                        root.remove(run)
                    else:
                        run.append(run.makeelement(f"{HP}t", {}))
            return True
    return False


def splice_text(doc: Any, paragraph: Any, start: int, end: int, text: str, special: bool = False) -> None:
    """Replace the characters [start, end) of *paragraph* by *text* (start == end inserts; text "" deletes). The new text takes the character shape of
    the first replaced character (of the one before the place for an insertion). Objects (endnotes, equations, ...) inside the range stay."""
    root = paragraph.element
    if not any(char in _ATOM_CHARS for char in text) and _edit_in_place(paragraph, start, end, text):
        _clear_paragraph_layout_cache(root)
        paragraph.section.mark_dirty()
        return
    _clear_paragraph_layout_cache(root)
    if start < end:
        base = _neighbor_char(paragraph, start + 1)
        end_gap = split_at(paragraph, end)
        size = len(root)
        gap = split_at(paragraph, start)
        end_gap += len(root) - size
        for run in [child for child in list(root)[gap:end_gap] if child.tag == f"{HP}run"]:
            for t in run.findall(f"{HP}t"):
                run.remove(t)  # the text goes; objects inside the range stay
            if len(run) == 0:
                root.remove(run)
    else:
        base = _neighbor_char(paragraph, start)
        gap = split_at(paragraph, start)
    if text:
        old = list(root)
        build_items(doc, paragraph, [{"text": text, "special": special}], base_char=base, where="text")
        for offset, run in enumerate([child for child in root if child not in old]):
            root.insert(gap + offset, run)
    if not root.findall(f"{HP}run"):
        root.insert(gap, _empty_run(root, base))
    _clear_paragraph_layout_cache(root)
    paragraph.section.mark_dirty()


# ---------------------------------------------------------------- replace_text_ext

def _where(address: dict[str, Any], start: int, length: int) -> dict[str, Any]:
    """A place in the answer: address and position only, never the text (upstream's readers mask personal information, so the answer must not bring it back)."""
    return {"address": address, "start": start, "length": length}


def _object_positions(paragraph: Any) -> list[int]:
    """Character position (as paragraph_text counts: an hp:t advances by its length, anything else in a run is 0 wide) of every object in the
    paragraph's runs: equations, pictures, tables, controls (endnote and footnote anchors, bookmarks, field marks ...); not the section definition."""
    at, found = 0, []
    for run in paragraph.element.findall(f"{HP}run"):
        for child in run:
            if not isinstance(child.tag, str):
                continue
            name = _element_local_name(child)
            if name == "t":
                at += len(child.text or "") + sum((1 if _element_local_name(part) in _TEXT_INLINE_ATOMS else len("".join(part.itertext()))) + len(part.tail or "") for part in child)
            elif name not in ("secPr", "tab"):
                found.append(at)
    return found


def replace_text_ext(
    filename: str,
    find_text: str,
    replace_text: str,
    scopes: list[str] | None = None,
    regex: bool = False,
    match_case: bool = True,
    occurrence: int = 0,
    special: bool = False,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Find and replace text everywhere in the file in one call: body paragraphs, table cells, endnotes, footnotes and headers/footers - the upstream search-and-replace tools cannot reach text inside endnotes, footnotes or headers.
    Only those five places are searched: not captions, text boxes, memos or field values, so replaced 0 does not mean the text is nowhere in the document.
    The replaced text keeps its character shape; tabs, line breaks, endnotes, footnotes, equations, pictures and other objects outside the matched text stay untouched (a tab inside it is replaced). A match is searched inside one paragraph (it never crosses a paragraph boundary).
    A match with an object standing INSIDE it (an equation, picture, endnote/footnote anchor, bookmark, hyperlink mark ...) is skipped, because the object would be pushed out of the replaced text; skipped matches are listed in `skipped`. An object at the very start or end of a match is fine and stays where it is. Change such a place with edit_paragraph_text_ext.
    find_text: the text to find (never empty); a literal by default, a Python regular expression with regex=true (empty matches are skipped). replace_text: the new text ("" deletes the match); with regex=true it may use \\1 and \\g<name>. match_case=false ignores case.
    The paragraph text is counted as in insert_inline_ext: a tab, line break, no-break/full-width space and soft hyphen count as one character each, objects 0. special=true turns the tab, line feed, U+00A0, U+3000 and U+00AD characters in replace_text into tab, line break, no-break space, full-width space, soft hyphen elements (a typed backslash-t stays text).
    scopes: a non-empty subset of "body", "table_cells", "endnotes", "footnotes", "headers_footers" (default all five). section_index: only that section (default all sections; with it the addresses in the result count inside that section and carry section_index).
    occurrence: 0 = replace every match (default); n (1 or more) = replace only the n-th match in document order (body paragraphs first, then table cells, endnotes, footnotes, headers/footers); skipped matches are counted.
    Returns replaced (places changed), matched (places found, skipped ones included), byScope (places replaced per scope), locations (the first 30 replaced places: `address` as the other paragraph tools take it, original character `start` and `length`; never the text itself), truncated, skipped (the first 30 skipped places in the same form) and skippedCount.
    Nothing replaced is not an error: replaced 0 and a `note`, and the file is NOT saved. dry_run=true saves nothing (it lists what would change). Check the result with hwpx_read_layout or get_document_text."""
    if not isinstance(find_text, str) or not find_text:
        raise ToolInputError("find_text must be a non-empty string")
    if not isinstance(replace_text, str):
        raise ToolInputError("replace_text must be a string")
    for name, value in (("regex", regex), ("match_case", match_case), ("special", special)):
        _check_flag(value, name)
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise ToolInputError(f"occurrence must be 0 (all matches) or the number of the match, 1 or more, got {occurrence!r}")
    chosen = _check_scopes(scopes)
    try:
        pattern = re.compile(find_text if regex else re.escape(find_text), 0 if match_case else re.IGNORECASE)
    except re.error as error:
        raise ToolInputError(f"find_text is not a valid regular expression: {error}") from error

    def new_text(match: Any) -> str:
        if not regex:
            return replace_text
        try:
            return match.expand(replace_text)
        except (re.error, IndexError) as error:
            raise ToolInputError(f"replace_text does not fit find_text: {error}") from error

    def apply(doc: Any) -> dict[str, Any]:
        hits, skipped, count = [], [], 0  # hits: (address, paragraph, [(start, end, new text)]); skipped: (address, start, length)
        for address, paragraph in list(iter_paragraphs(doc, chosen, section_index)):
            address = {**address, **({"section_index": section_index} if section_index is not None else {})}
            text, found, objects = paragraph_text(paragraph), [], None
            for match in pattern.finditer(text) if text else ():
                if match.end() == match.start():
                    continue
                count += 1
                if occurrence and count != occurrence:
                    continue
                objects = _object_positions(paragraph) if objects is None else objects
                if any(match.start() < at < match.end() for at in objects):
                    skipped.append((address, match.start(), match.end() - match.start()))
                else:
                    found.append((match.start(), match.end(), new_text(match)))
            if found:
                hits.append((address, paragraph, found))
            if occurrence and count >= occurrence:
                break
        replaced = sum(len(found) for _, _, found in hits)
        shown_skipped = [_where(*item) for item in skipped[:_LOCATIONS]]
        if not replaced:
            raise _Unchanged({
                "replaced": 0, "matched": len(skipped), "byScope": dict.fromkeys(chosen, 0), "locations": [], "truncated": False, "skipped": shown_skipped, "skippedCount": len(skipped),
                "note": ("every match has an object inside it and was skipped (see skipped; use edit_paragraph_text_ext there); nothing was changed" if skipped
                         else "find_text was not found in the five searched places (case and paragraph boundaries matter; captions, text boxes, memos and field values are not searched); nothing was changed"),
            })
        by_scope, locations = dict.fromkeys(chosen, 0), []
        for address, _, found in hits:
            by_scope[_SCOPE_OF[next(iter(address))]] += len(found)
            locations += [_where(address, start, end - start) for start, end, _ in found[:_LOCATIONS - len(locations)]]
        for _, paragraph, found in hits:
            for start, end, new in reversed(found):  # from the back, so the positions in front stay right
                splice_text(doc, paragraph, start, end, new, special)
        _refuse_dangling_ids(doc)
        return {"replaced": replaced, "matched": replaced + len(skipped), "byScope": by_scope, "locations": locations, "truncated": replaced > _LOCATIONS, "skipped": shown_skipped, "skippedCount": len(skipped)}

    return _commit_changes(filename, expected_revision, dry_run, apply)


# ---------------------------------------------------------------- edit_paragraph_text_ext

@addressed
def edit_paragraph_text_ext(
    filename: str,
    start: int,
    end: int | None = None,
    text: str = "",
    special: bool = False,
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row: int | None = None,
    col: int | None = None,
    cell_paragraph_index: int | None = None,
    endnote_number: int | None = None,
    endnote_paragraph_index: int | None = None,
    footnote_number: int | None = None,
    footnote_paragraph_index: int | None = None,
    header_index: int | None = None,
    header_paragraph_index: int | None = None,
    footer_index: int | None = None,
    footer_paragraph_index: int | None = None,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Replace the characters [start, end) of one paragraph by `text`: insert (omit `end`, or end = start), delete (text = ""), or replace. Works in body paragraphs, table cells, endnotes, footnotes, headers and footers.
    Target paragraph: {ADDRESS}
    Positions count characters from the start of the paragraph text, 0..length (a tab, line break, no-break/full-width space, soft hyphen and hyperlink display text count as one character each; equations, pictures, endnotes and other objects count 0 and stay where they are, also inside the range). Read the text with hwpx_read_layout first.
    0 <= start <= end <= length is required, otherwise the call is refused and the length is given. The new text takes the character shape of the first replaced character (of the character just before `start` for an insertion). special=true turns the tab, line feed, U+00A0, U+3000 and U+00AD characters in `text` into tab, line break, no-break space, full-width space, soft hyphen elements.
    An empty `text` with an empty range changes nothing and is refused. The cached line layout of the paragraph is dropped (Hancom recomputes it on open). Returns paragraphLength (after the change), removedLength and insertedLength (characters; never the text itself). dry_run=true saves nothing."""
    address = _address(locals())
    for name, value in (("start", start), ("end", end)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ToolInputError(f"{name} must be a whole number >= 0, got {value!r}")
    if not isinstance(text, str):
        raise ToolInputError("text must be a string")
    _check_flag(special, "special")
    stop = start if end is None else end
    if stop < start:
        raise ToolInputError(f"end {stop} is before start {start}")
    if stop == start and not text:
        raise ToolInputError("nothing to do: text is empty and the range [start, end) is empty")

    def apply(doc: Any) -> dict[str, Any]:
        paragraph = resolve_paragraph(doc, section_index, **address)
        old = paragraph_text(paragraph)
        if stop > len(old):
            raise ToolInputError(f"range {start}..{stop} is out of bounds: the paragraph has {len(old)} characters (positions 0..{len(old)})")
        splice_text(doc, paragraph, start, stop, text, special)
        _refuse_dangling_ids(doc)
        return {"paragraphLength": len(paragraph_text(paragraph)), "removedLength": stop - start, "insertedLength": len(text), "start": start, "end": stop}

    return _commit_changes(filename, expected_revision, dry_run, apply)


# ---------------------------------------------------------------- split_paragraph_ext / merge_paragraphs_ext

def _next_address(address: dict[str, Any], group: str) -> dict[str, Any]:
    """Address of the paragraph right behind the one at *address*."""
    key = _INNER[group]
    given = {name: value for name, value in address.items() if value is not None}
    return {**given, key: (given.get(key) or 0) + 1}


@addressed
def split_paragraph_ext(
    filename: str,
    position: int,
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row: int | None = None,
    col: int | None = None,
    cell_paragraph_index: int | None = None,
    endnote_number: int | None = None,
    endnote_paragraph_index: int | None = None,
    footnote_number: int | None = None,
    footnote_paragraph_index: int | None = None,
    header_index: int | None = None,
    header_paragraph_index: int | None = None,
    footer_index: int | None = None,
    footer_paragraph_index: int | None = None,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Split one paragraph in two at a character position (like pressing Enter). Works in body paragraphs, table cells, endnotes, footnotes, headers and footers; the second paragraph is inserted right behind the first, in the same place.
    Paragraph to split: {ADDRESS}
    position: characters from the start of the paragraph text, 0..length (a tab, line break, no-break/full-width space, soft hyphen and hyperlink display text count as one character each; objects count 0). The text behind the position moves to the new paragraph with its character shapes; objects (equations, pictures, endnotes ...) standing at the position stay in the first paragraph, objects behind it move along.
    The new paragraph gets the first one's paragraph shape and style; page break and column break are reset to 0, so the second half never starts a new page. Position 0 is refused for the paragraph that holds the section definition (page and column settings must stay in the section's first paragraph), and so is a position inside a hyperlink or field (its start mark stands in front of the cut, so a cut at the very start of the link text is inside it too).
    The cached line layout of both paragraphs is dropped (Hancom recomputes it on open). Returns newParagraph (the address of the second paragraph, in the same form the paragraph tools take), firstLength and secondLength (characters). dry_run=true saves nothing."""
    address = _address(locals())
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ToolInputError(f"position must be a whole number >= 0, got {position!r}")
    group = address_group(**address)

    def apply(doc: Any) -> dict[str, Any]:
        paragraph = resolve_paragraph(doc, section_index, **address)
        length = len(paragraph_text(paragraph))
        if position > length:
            raise ToolInputError(f"position {position} is out of range 0..{length}: the paragraph has {length} characters")
        if position == 0 and holds_section_definition(paragraph):
            raise ToolInputError("position 0 is refused for the paragraph that holds the section definition (page and column settings); split it at 1 or more")
        root = paragraph.element
        _clear_paragraph_layout_cache(root)
        first_char, last_char = _neighbor_char(paragraph, 0), _neighbor_char(paragraph, position)
        gap = split_at(paragraph, position)
        begun = {mark.get("id") for child in list(root)[:gap] for mark in child.iter(f"{HP}fieldBegin")}
        if any(mark.get("beginIDRef") in begun for child in list(root)[gap:] for mark in child.iter(f"{HP}fieldEnd")):
            raise ToolInputError(f"position {position} cuts a hyperlink or field in two (its start stays in the first paragraph, its end would move to the second); choose a position outside it")
        new = root.makeelement(root.tag, dict(root.attrib))
        for key in ("pageBreak", "columnBreak"):
            if key in new.attrib:
                new.set(key, "0")
        used = {element.get("id") for element in paragraph.section.element.iter(f"{HP}p")}
        new_id = _paragraph_id()
        while new_id in used:
            new_id = _paragraph_id()
        new.set("id", new_id)
        for child in list(root)[gap:]:
            new.append(child)
        if not new.findall(f"{HP}run"):
            new.append(_empty_run(new, last_char))
        if not root.findall(f"{HP}run"):
            root.append(_empty_run(root, first_char))
        root.getparent().insert(root.getparent().index(root) + 1, new)
        paragraph.section.mark_dirty()
        _refuse_dangling_ids(doc)
        return {
            "newParagraph": _next_address({**address, **({"section_index": section_index} if section_index is not None else {})}, group),
            "firstLength": len(paragraph_text(paragraph)), "secondLength": len(paragraph_text(HwpxOxmlParagraph(new, paragraph.section))),
        }

    return _commit_changes(filename, expected_revision, dry_run, apply)


@addressed
def merge_paragraphs_ext(
    filename: str,
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row: int | None = None,
    col: int | None = None,
    cell_paragraph_index: int | None = None,
    endnote_number: int | None = None,
    endnote_paragraph_index: int | None = None,
    footnote_number: int | None = None,
    footnote_paragraph_index: int | None = None,
    header_index: int | None = None,
    header_paragraph_index: int | None = None,
    footer_index: int | None = None,
    footer_paragraph_index: int | None = None,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Join a paragraph with the paragraph right behind it in the same place (like pressing Delete at the end of the paragraph): the next paragraph's text and objects move to the end of this one, keeping their own character shapes, and the next paragraph is removed. Works in body paragraphs, table cells, endnotes, footnotes, headers and footers.
    First paragraph: {ADDRESS}
    The first paragraph keeps its paragraph shape and style. Refused when there is no next paragraph in the same place (cell, note, header ...); when either paragraph holds a table or the section definition (page and column settings); and when the NEXT paragraph would lose something by being merged: it starts a new page or column (pageBreak/columnBreak - clear that first with set_paragraph_format_ext), it holds a column definition, or a field elsewhere in the file points at it (a table-of-contents entry or cross-reference). Endnotes and footnotes standing in the moved text move along and keep their numbering.
    The cached line layout is dropped (Hancom recomputes it on open). Returns paragraphLength (after the merge) and joinedAt (the character position where the second text now begins). dry_run=true saves nothing."""
    address = _address(locals())

    def apply(doc: Any) -> dict[str, Any]:
        paragraph = resolve_paragraph(doc, section_index, **address)
        following = next_paragraph(paragraph)
        if following is None:
            raise ToolInputError("there is no paragraph behind this one in the same place to merge with")
        second = HwpxOxmlParagraph(following, paragraph.section)
        if holds_table(paragraph) or holds_table(second):
            raise ToolInputError("a paragraph that holds a table cannot be merged")
        if holds_section_definition(paragraph) or holds_section_definition(second):
            raise ToolInputError("a paragraph that holds the section definition (page and column settings) cannot be merged")
        if following.get("pageBreak") == "1" or following.get("columnBreak") == "1":
            raise ToolInputError("the next paragraph starts a new page or column (pageBreak/columnBreak); merging would silently drop that break. Clear it first with set_paragraph_format_ext, then merge")
        if following.find(f".//{HP}colPr") is not None:
            raise ToolInputError("the next paragraph holds a column definition (colPr); merging would silently drop it")
        target = following.get("id")
        if target not in (None, "", "0") and any(
            found == target for section in doc.sections for field in section.element.iter(f"{HP}fieldBegin")
            for param in field.iter(f"{HP}stringParam") for found in re.findall(r"\?#(\d+)", param.text or "")
        ):
            raise ToolInputError("a field in the file (a table-of-contents entry or cross-reference) points at the next paragraph; merging would break it")
        root, joined = paragraph.element, len(paragraph_text(paragraph))
        _clear_paragraph_layout_cache(root)
        for run in following.findall(f"{HP}run"):
            root.append(run)
        following.getparent().remove(following)
        paragraph.section.mark_dirty()
        _refuse_dangling_ids(doc)
        return {"paragraphLength": len(paragraph_text(paragraph)), "joinedAt": joined}

    return _commit_changes(filename, expected_revision, dry_run, apply)


# ---------------------------------------------------------------- redact_text_ext

_KINDS = ("rrn", "phone", "email", "card")
_POLICY = PIIPolicy(contextual_enabled=False)  # the machine-checkable kinds only: the same definition as upstream's scan_personal_info
_BACKUP_NOTE = "the .bak file written before the edit still holds the original personal information: delete it with delete_backups_ext, or restore it with undo_last_edit"


def find_personal_info(text: str, kinds: list[str] | tuple[str, ...] = _KINDS) -> list[tuple[str, int, int]]:
    """(kind, start, end) of every personal-information span of the chosen kinds that upstream's detector finds in *text*, in order."""
    return sorted(((span["type"], span["start"], span["end"]) for span in detect_pii(text, _POLICY) if span["type"] in kinds), key=lambda item: item[1])


def redact_text_ext(
    filename: str,
    kinds: list[str] | None = None,
    mask: str = "●",
    scopes: list[str] | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Mask personal information in the whole file - body, table cells, endnotes, footnotes, headers/footers - keeping the length: each digit and letter of a finding becomes `mask`, separators (- space @ . _ % +) stay, so the character count and the layout stay the same. Run it with dry_run=true FIRST and look at `findings` to see what would be masked.
    Detection is upstream's (the same definition as scan_personal_info), by kind: "rrn" (13-digit resident registration number, sex/century digit 1-4, hyphen optional), "phone" (mobile 010/011/016/017/018/019 + 3-4 digits + 4 digits, hyphens optional), "email", "card" (16 digits in groups of four, hyphen or space optional; the Luhn check must pass). Default all four; any other value is refused. It does not detect landline numbers, passport or bank account numbers, or foreigners' registration numbers: read the text yourself afterwards.
    mask: one character, not a letter, a digit or a space (default ●). scopes: a non-empty subset of "body", "table_cells", "endnotes", "footnotes", "headers_footers" (default all five). The masked text takes the character shape of its first character.
    The response NEVER contains the original text: findings list kind, masked shape (e.g. ●●●●●●-●●●●●●●), address (as the paragraph tools take it) and character positions. Returns found, redacted (0 for a dry run), byKind, byScope, findings (first 100), truncated and `rule`. Nothing found: the file is NOT saved.
    After a real masking the stored preview (preview text and picture, which show the first page) is cleared too, and the result says previewCleared: true. The .bak backup written before the edit still holds the ORIGINAL personal information (`backupNote`): delete it with delete_backups_ext, or restore the file with undo_last_edit."""
    if kinds is None:
        kinds = list(_KINDS)
    if not isinstance(kinds, list) or not kinds or any(kind not in _KINDS for kind in kinds):
        raise ToolInputError(f"kinds must be a non-empty list of {list(_KINDS)}, got {kinds!r}")
    if not isinstance(mask, str) or len(mask) != 1 or mask.isalnum() or mask.isspace():
        raise ToolInputError("mask must be one character that is not a letter, a digit or a space")
    chosen = _check_scopes(scopes)

    def masked(text: str) -> str:
        return "".join(mask if char.isalnum() else char for char in text)

    def apply(doc: Any) -> dict[str, Any]:
        hits = []  # (address, paragraph, text, [(kind, start, end)])
        for address, paragraph in list(iter_paragraphs(doc, chosen)):
            text = paragraph_text(paragraph)
            spots = find_personal_info(text, kinds)
            if spots:
                hits.append((address, paragraph, text, spots))
        shown = dict.fromkeys(_KINDS, 0)
        by_scope, findings = dict.fromkeys(chosen, 0), []
        for address, _, text, spots in hits:
            for kind, start, end in spots:
                shown[kind] += 1
                by_scope[_SCOPE_OF[next(iter(address))]] += 1
                if len(findings) < _FINDINGS:
                    findings.append({"kind": kind, "address": address, "start": start, "end": end, "masked": masked(text[start:end])})
        found = sum(shown.values())
        rule = "each digit and letter of a finding became the mask; separators (- space @ . _ % +) stayed; the length is unchanged"
        result = {"found": found, "redacted": 0 if dry_run else found, "byKind": shown, "byScope": by_scope, "findings": findings, "truncated": found > _FINDINGS, "rule": rule, "previewCleared": False}
        if not found:
            raise _Unchanged({**result, "note": "no personal information of the chosen kinds was found; nothing was changed"})
        for _, paragraph, text, spots in hits:
            for _, start, end in reversed(spots):
                splice_text(doc, paragraph, start, end, masked(text[start:end]))
        if not dry_run:
            doc.parts.clear_preview()  # the preview text and picture show the first page, personal information included
            result.update(previewCleared=True, backupNote=_BACKUP_NOTE)
        _refuse_dangling_ids(doc)
        return result

    return _commit_changes(filename, expected_revision, dry_run, apply)
