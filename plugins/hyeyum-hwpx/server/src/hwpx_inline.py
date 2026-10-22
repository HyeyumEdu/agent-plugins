"""인라인 항목: 문단 안에 글·수식·그림·각주·하이퍼링크·책갈피·체크박스·덧말·글자 겹치기를 준 순서대로 이어 붙이고(build_items),
이미 있는 문단의 글자 위치에 끼운다(insert_inline_ext).

라이브러리의 add_* 호출은 모두 문단 맨 끝에 run을 붙이므로, insert_inline_ext는 끝에 만든 run들을 hwpx_runs.split_at가 정한 자리로 옮긴다.
hwpx_edit가 이 모듈을 쓰므로 여기서는 hwpx_edit를 가져오지 않는다(순환 방지).
"""
import base64
import binascii
import re
import struct
from functools import partial
from typing import Any

from hwpx.equation.authoring import latex_to_eqedit
from hwpx.errors import HwpxLookupError
from hwpx.hwp5.section_xml import COMPOSE_CIRCLE, DUTMAL_POS
from hwpx.oxml._document_primitives import _clear_paragraph_layout_cache, _sanitize_text
from hwpx.oxml.namespaces import HP
from hwpx_automation.workspace import WorkspaceResolver

from hwpx_common import (
    _HWPUNIT_PER_MM, _RUN_KEYS, ToolInputError, _char_ref, _check_keys, _commit, _refuse_dangling_ids, _renumber_footnotes,
)
from hwpx_locate import address_group, addressed, resolve_paragraph, table_at, table_indexes  # noqa: F401  (table_at, table_indexes: hwpx_edit takes them from here)
from hwpx_runs import split_at

_KINDS = ("text", "equation", "latex", "picture", "footnote", "hyperlink", "bookmark", "check_box", "ruby", "composed")
_CHAR_KEYS = _RUN_KEYS | {"char_pr_id"}
#: an item names its kind with one key; the rest are character options (flat, or in "char") and the options of single kinds
_ITEM_KEYS = frozenset(_KINDS) | _CHAR_KEYS | {"char", "special", "base_unit"}
_PICTURE_KEYS = frozenset({"path", "image_base64", "width_mm", "height_mm"})
_TABLE_KEYS = frozenset({"rows", "cols", "width", "height", "border_fill_id"})
#: characters that Hancom stores as elements inside hp:t (the same ones hwpx_runs counts as one character)
_ATOMS = {"\t": "tab", "\n": "lineBreak", "\u00a0": "nbSpace", "\u3000": "fwSpace", "\u00ad": "hyphen"}
_ATOM_SPLIT = re.compile("([" + "".join(_ATOMS) + "])")
_IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"), (b"BM", "bmp"))


# ---------------------------------------------------------------- checks that need no file

def _string(value: Any, label: str, blank_ok: bool = False) -> None:
    if not isinstance(value, str) or not (blank_ok or value.strip()):
        raise ToolInputError(f"{label} must be a {'' if blank_ok else 'non-empty '}string")


def _number(value: Any, label: str, whole: bool = False) -> None:
    ok = isinstance(value, int) if whole else isinstance(value, (int, float))
    if isinstance(value, bool) or not ok or not value > 0 or value == float("inf"):
        raise ToolInputError(f"{label} must be a positive {'whole ' if whole else ''}number, got {value!r}")


def _mapping(value: Any, allowed: frozenset[str], required: tuple[str, ...], label: str) -> None:
    if not isinstance(value, dict):
        raise ToolInputError(f"{label} must be an object with {sorted(allowed)}")
    _check_keys(value, allowed, label)
    missing = [key for key in required if key not in value]
    if missing:
        raise ToolInputError(f"{label} needs {missing}")


def _check_picture(value: Any, label: str) -> None:
    _mapping(value, _PICTURE_KEYS, (), label)
    if ("path" in value) == ("image_base64" in value):
        raise ToolInputError(f"{label}: give exactly one of path or image_base64")
    _string(value.get("path", value.get("image_base64")), f"{label}.{'path' if 'path' in value else 'image_base64'}")
    if "width_mm" not in value and "height_mm" not in value:
        raise ToolInputError(f"{label}: give width_mm and/or height_mm (the other follows the image's proportions)")
    for key in ("width_mm", "height_mm"):
        if key in value:
            _number(value[key], f"{label}.{key}")


def _check_hyperlink(value: Any, label: str) -> None:
    _mapping(value, frozenset({"url", "text"}), ("url", "text"), label)
    _string(value["url"], f"{label}.url")
    _string(value["text"], f"{label}.text")


def _check_check_box(value: Any, label: str) -> None:
    _mapping(value, frozenset({"caption", "checked"}), ("caption",), label)
    _string(value["caption"], f"{label}.caption", blank_ok=True)
    if not isinstance(value.get("checked", False), bool):
        raise ToolInputError(f"{label}.checked must be true or false")


def _choice(value: dict[str, Any], key: str, allowed: tuple[str, ...], label: str) -> None:
    if key in value:
        _string(value[key], f"{label}.{key}")
        if value[key].upper() not in allowed:
            raise ToolInputError(f"{label}.{key} {value[key]!r} is not one of {list(allowed)}")


def _check_ruby(value: Any, label: str) -> None:
    _mapping(value, frozenset({"base", "text", "pos_type"}), ("base", "text"), label)
    _string(value["base"], f"{label}.base")
    _string(value["text"], f"{label}.text")
    _choice(value, "pos_type", DUTMAL_POS, label)


def _check_composed(value: Any, label: str) -> None:
    _mapping(value, frozenset({"text", "circle_type"}), ("text",), label)
    _string(value["text"], f"{label}.text")
    _choice(value, "circle_type", COMPOSE_CIRCLE, label)


_VALUE_CHECKS = {
    "text": partial(_string, blank_ok=True), "footnote": partial(_string, blank_ok=True),
    "equation": _string, "latex": _string, "bookmark": _string,
    "picture": _check_picture, "hyperlink": _check_hyperlink, "check_box": _check_check_box, "ruby": _check_ruby, "composed": _check_composed,
}


def check_items(items: list[dict[str, Any]], where: str) -> None:
    """Refuse a malformed item list (kind keys, option names, value types) before the file is opened."""
    if not isinstance(items, list):
        raise ToolInputError(f"{where} must be a list")
    for number, item in enumerate(items):
        label = f"{where}[{number}]"
        if not isinstance(item, dict):
            raise ToolInputError(f"{label} must be an object")
        _check_keys(item, _ITEM_KEYS, label)
        kinds = [key for key in _KINDS if key in item]
        if len(kinds) != 1:
            raise ToolInputError(f"{label}: give exactly one of {list(_KINDS)}, got {kinds}")
        kind = kinds[0]
        if "special" in item and (kind != "text" or not isinstance(item["special"], bool)):
            raise ToolInputError(f"{label}: special is true/false and belongs to a text item")
        if "base_unit" in item and (kind not in ("equation", "latex") or isinstance(item["base_unit"], bool) or not isinstance(item["base_unit"], int) or item["base_unit"] < 1):
            raise ToolInputError(f"{label}: base_unit is a whole number >= 1 (1/100 pt) and belongs to an equation or latex item")
        if not isinstance(item.get("char", {}), dict):
            raise ToolInputError(f"{label}.char must be an object")
        _check_keys(item.get("char", {}), _CHAR_KEYS, f"{label} char")
        _VALUE_CHECKS[kind](item[kind], f"{label}.{kind}")


def check_table(spec: Any, label: str) -> None:
    _mapping(spec, _TABLE_KEYS, ("rows", "cols"), label)
    for key in ("rows", "cols", "width", "height"):
        if key in spec:
            _number(spec[key], f"{label}.{key}", whole=True)
    if "border_fill_id" in spec and (isinstance(spec["border_fill_id"], bool) or not isinstance(spec["border_fill_id"], (str, int))):
        raise ToolInputError(f"{label}.border_fill_id must be a borderFill id")


# ---------------------------------------------------------------- styles

def paragraph_style(doc: Any, ref: Any, label: str) -> Any:
    """The paragraph style named *ref* (name, English name or id); refusals list what the file has."""
    if isinstance(ref, bool) or not isinstance(ref, (str, int)) or ref == "":
        raise ToolInputError(f"{label} must be a style name or id")
    try:
        style = doc.styles.resolve(ref)
    except HwpxLookupError as error:
        if error.code == "style-ambiguous":
            ids = [candidate["id"] for candidate in error.context["candidates"]]
            raise ToolInputError(f"{label} {ref!r} names several styles; give one of the ids {ids}") from error
        raise ToolInputError(f"{label} {ref!r} is not a style of this file; styles: {doc.styles.names()}") from error
    if style.type == "CHAR":
        raise ToolInputError(f"{label} {ref!r} is a character style; a paragraph takes a paragraph style")
    return style


# ---------------------------------------------------------------- pictures

def _image_size(data: bytes, fmt: str) -> tuple[int, int] | None:
    """Pixel size from the image header, or None when the header is not readable."""
    try:
        if fmt == "png":
            size = struct.unpack(">II", data[16:24])
        elif fmt == "gif":
            size = struct.unpack("<HH", data[6:10])
        elif fmt == "bmp":
            width, height = struct.unpack("<ii", data[18:26])
            size = (width, abs(height))
        else:  # jpeg: walk the segments to the first start-of-frame
            size, at = None, 2
            while size is None and at + 9 < len(data):
                marker = data[at + 1] if data[at] == 0xFF else 0
                if marker in (0, 0x01, 0xFF) or 0xD0 <= marker <= 0xD8:
                    at += 1 if marker in (0, 0xFF) else 2
                elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    height, width = struct.unpack(">HH", data[at + 5:at + 9])
                    size = (width, height)
                else:
                    at += 2 + struct.unpack(">H", data[at + 2:at + 4])[0]
    except struct.error:
        return None
    return size if size and size[0] > 0 and size[1] > 0 else None


def _add_picture(doc: Any, paragraph: Any, spec: dict[str, Any], char: str | None, label: str) -> None:
    if "path" in spec:
        try:
            path = WorkspaceResolver.from_environment().resolve(spec["path"], must_exist=True)
            data = path.read_bytes()
        except OSError:  # a missing file, a directory, a path outside the workspace: none of them may echo the path
            raise ToolInputError(f"{label}.path is not a readable file inside the workspace folder") from None
    else:
        try:
            data = base64.b64decode(spec["image_base64"], validate=True)
        except (binascii.Error, ValueError):
            raise ToolInputError(f"{label}.image_base64 is not valid base64") from None
    fmt = next((name for magic, name in _IMAGE_MAGIC if data.startswith(magic)), None)
    if fmt is None:
        raise ToolInputError(f"{label}: the image must be PNG, JPEG, BMP or GIF")
    width, height = spec.get("width_mm"), spec.get("height_mm")
    if width is None or height is None:
        pixels = _image_size(data, fmt)
        if pixels is None:
            raise ToolInputError(f"{label}: the image size cannot be read from the file header; give both width_mm and height_mm")
        if width is None:
            width = height * pixels[0] / pixels[1]
        else:
            height = width * pixels[1] / pixels[0]
    width, height = round(width * _HWPUNIT_PER_MM), round(height * _HWPUNIT_PER_MM)
    if width < 1 or height < 1:
        raise ToolInputError(f"{label}: the picture size rounds to 0 HWPUNIT; give larger width_mm / height_mm")
    # add_picture refuses pos_overrides on an inline picture, so the Hancom value (anchored to the paragraph, not the column) is set on the element
    picture = paragraph.add_picture(
        str(doc.media.add_image(data, fmt)), width=width, height=height, treat_as_char=True, text_wrap="TOP_AND_BOTTOM", char_pr_id_ref=char)
    picture.element.find(f"{HP}pos").set("horzRelTo", "PARA")


# ---------------------------------------------------------------- text

def _write_special(run: Any, text: str) -> None:
    """Write *text* as the run's hp:t, tab / line break / no-break space / full-width space / soft hyphen as the elements Hancom stores."""
    t = run.element.find(f"{HP}t")
    if t is None:
        t = run.element.makeelement(f"{HP}t", {})
        run.element.append(t)
    for child in list(t):
        t.remove(child)
    t.text = None
    last = None
    for part in _ATOM_SPLIT.split(text):
        if part in _ATOMS:
            last = t.makeelement(f"{HP}{_ATOMS[part]}", {})
            t.append(last)
        elif last is None:
            t.text = _sanitize_text(part) or None
        else:
            last.tail = _sanitize_text(part) or None


def _add_text(paragraph: Any, item: dict[str, Any], char: str | None, first_run: Any | None) -> None:
    text, special = item["text"], item.get("special", False)
    if first_run is None:
        run = paragraph.add_run("" if special else text, char_pr_id_ref=char)
    else:  # the paragraph's blank first run (a new paragraph's, a cell's, a note's number run) takes the first text
        run = first_run
        if char is not None:
            run.char_pr_id_ref = char
        if text and not special:
            run.text = text
    if special:
        _write_special(run, text)


# ---------------------------------------------------------------- build

def _char_options(item: dict[str, Any]) -> dict[str, Any]:
    return {**{key: value for key, value in item.items() if key in _CHAR_KEYS}, **item.get("char", {})}


def _in_note(paragraph: Any) -> bool:
    return any(a.tag in (f"{HP}endNote", f"{HP}footNote") for a in paragraph.element.iterancestors())


def _blank(run: Any) -> bool:
    return all(child.tag == f"{HP}t" and not child.text and not len(child) for child in run.element)


def build_items(doc: Any, paragraph: Any, items: list[dict[str, Any]], base_char: str | None = None, first_run: Any | None = None, where: str = "items") -> None:
    """Append *items* (see check_items) to *paragraph* in the order given, each as new run(s) at the paragraph's end.

    base_char: the character shape id that character options are put on top of (a style's charPrIDRef; an item without options gets it as is).
    first_run: the paragraph's blank first run; a first item of kind text writes into it, otherwise it is dropped when it stays blank.
    """
    for number, item in enumerate(items):
        kind = next(key for key in _KINDS if key in item)
        label = f"{where}[{number}].{kind}"
        options = _char_options(item)
        char = _char_ref(doc, options, base_char)
        own = char if options else None  # a shape the item itself names: for kinds whose look is not the paragraph's
        value = item[kind]
        if kind == "text":
            _add_text(paragraph, item, char, first_run if number == 0 else None)
        elif kind in ("equation", "latex"):
            try:
                script = latex_to_eqedit(value) if kind == "latex" else value
            except ValueError as error:
                raise ToolInputError(f"{label}: the LaTeX cannot be converted to an equation ({error})") from error
            paragraph.add_equation(script, base_unit=item.get("base_unit", 1000), char_pr_id_ref=char)
        elif kind == "picture":
            _add_picture(doc, paragraph, value, char, label)
        elif kind == "footnote":
            if _in_note(paragraph):
                raise ToolInputError(f"{label}: a footnote cannot be placed inside an endnote or footnote")
            # run_attributes={} makes a run of its own (otherwise the note goes into the paragraph's last run)
            paragraph.add_footnote(value, run_attributes={} if own or base_char is None else {"charPrIDRef": base_char}, char_pr_id_ref=own)
        elif kind == "hyperlink":
            paragraph.add_hyperlink(value["url"], value["text"], char_pr_id_ref=own)
        elif kind == "bookmark":
            paragraph.add_bookmark(value, char_pr_id_ref=char)
        elif kind == "check_box":
            paragraph.add_check_box(value["caption"], checked=value.get("checked", False), char_pr_id_ref=char)
        elif kind == "ruby":
            paragraph.add_dutmal(value["base"], value["text"], pos_type=value.get("pos_type", "TOP").upper(), char_pr_id_ref=char)
        else:
            paragraph.add_composed_character(value["text"], circle_type=value["circle_type"].upper() if "circle_type" in value else None, char_pr_id_ref=char)
    if first_run is not None and items and "text" not in items[0] and _blank(first_run) and len(paragraph.runs) > 1:
        paragraph.element.remove(first_run.element)
    _clear_paragraph_layout_cache(paragraph.element)
    paragraph.section.mark_dirty()


def build_table(paragraph: Any, spec: dict[str, Any]) -> Any:
    """Put a table in *paragraph* (after what it holds) and return its element; find its number with table_indexes."""
    return paragraph.add_table(
        spec["rows"], spec["cols"], width=spec.get("width"), height=spec.get("height"), border_fill_id_ref=spec.get("border_fill_id")).element


# ---------------------------------------------------------------- insert_inline_ext

def _neighbor_char(paragraph: Any, position: int) -> str | None:
    """Character shape of the run holding the character just before *position* (the first character at 0; the first run of an empty paragraph)."""
    runs = paragraph.runs
    seen = 0
    for run in runs:
        seen += len(run.text or "")
        if seen > max(position - 1, 0):
            return run.char_pr_id_ref
    return runs[0].char_pr_id_ref if runs else None


@addressed
def insert_inline_ext(
    filename: str,
    items: list[dict[str, Any]],
    position: int | None = None,
    anchor_text: str | None = None,
    occurrence: int = 1,
    before: bool = False,
    replace_anchor: bool = False,
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
    """Insert inline items (equation, picture, footnote, hyperlink, bookmark, check box, ruby, composed character, text) into the middle of an existing paragraph, in the order given.
    Target paragraph (also inside an endnote, footnote, header or footer): {ADDRESS}
    Place: `position` (characters from the start of the paragraph text, 0..length; a tab, line break, no-break/full-width space, soft hyphen and hyperlink display text count as one character each; equations, pictures, footnotes, bookmarks and other objects count 0),
    or `anchor_text` (the items go right after its `occurrence`-th match, 1 = first; `before`=true puts them right before the match). An object already standing at the place stays in front of the new items (the new items come after it).
    replace_anchor=true (with anchor_text) REMOVES the matched text and puts the items in its place: link existing words (hyperlink item with the same text), or turn a marker like "(수식1)" into an equation; the items take the character shape of the removed text.
    A position outside the text or an anchor_text that is not found is refused. Character shape of new items without options: that of the text just before the place.
    items: a non-empty list; each item has exactly one kind key: {"text": "...", "special": false} (special=true turns \\t, \\n, U+00A0, U+3000, U+00AD into tab, line break, no-break space, full-width space, soft hyphen elements),
    {"equation": "EqEdit script"} or {"latex": "\\\\frac{a}{b}"} (+ "base_unit": 1/100 pt, default 1000), {"picture": {"path" | "image_base64", "width_mm", "height_mm"}} (PNG/JPEG/BMP/GIF, treated as a character; give one size and the other follows the image),
    {"footnote": "text"} (not inside an endnote/footnote), {"hyperlink": {"url", "text"}}, {"bookmark": "name"}, {"check_box": {"caption", "checked"}} (a clickable form check-box object - for a plain square character type "□" as text), {"ruby": {"base", "text", "pos_type": TOP|BOTTOM}}, {"composed": {"text", "circle_type"}}.
    Any item may also carry character options: "char": {bold, italic, underline, color, font_name, font_size (pt), ... as in add_endnote_ext} or "char_pr_id" (a character shape already in the file), or the options directly in the item.
    Footnotes are renumbered in document order. dry_run=true saves nothing."""
    if not items:
        raise ToolInputError("items must not be empty")
    check_items(items, "items")
    if (position is None) == (anchor_text is None):
        raise ToolInputError("give exactly one of position or anchor_text")
    if replace_anchor and anchor_text is None:
        raise ToolInputError("replace_anchor needs anchor_text")
    if anchor_text is not None and (not isinstance(anchor_text, str) or not anchor_text or occurrence < 1):
        raise ToolInputError("anchor_text must be a non-empty string and occurrence 1 or more")
    address = dict(
        paragraph_index=paragraph_index, table_index=table_index, row=row, col=col, cell_paragraph_index=cell_paragraph_index,
        endnote_number=endnote_number, endnote_paragraph_index=endnote_paragraph_index, footnote_number=footnote_number,
        footnote_paragraph_index=footnote_paragraph_index, header_index=header_index, header_paragraph_index=header_paragraph_index,
        footer_index=footer_index, footer_paragraph_index=footer_paragraph_index,
    )
    address_group(**address)

    def apply(doc: Any) -> dict[str, Any]:
        paragraph = resolve_paragraph(doc, section_index, **address)
        text = "".join(run.text or "" for run in paragraph.runs)  # counted as format_text_ext counts
        if anchor_text is None:
            place = position
        else:
            start = -1
            for _ in range(occurrence):
                start = text.find(anchor_text, start + len(anchor_text) if start >= 0 else 0)
                if start < 0:
                    raise ToolInputError(f"anchor_text {anchor_text!r} occurrence {occurrence} not found: it occurs {text.count(anchor_text)} time(s) in the paragraph")
            place = start if before or replace_anchor else start + len(anchor_text)
        if not 0 <= place <= len(text):
            raise ToolInputError(f"position {place} is out of range 0..{len(text)}: the paragraph has {len(text)} characters")
        if replace_anchor:
            base = _neighbor_char(paragraph, place + 1)  # the shape of the first removed character
            root = paragraph.element
            end_gap = split_at(paragraph, place + len(anchor_text))
            size = len(root)
            gap = split_at(paragraph, place)
            end_gap += len(root) - size
            for run in [child for child in list(root)[gap:end_gap] if child.tag == f"{HP}run"]:
                for t in [child for child in run if child.tag == f"{HP}t"]:
                    run.remove(t)  # the text goes; objects inside the range (if any) stay
                if len(run) == 0:
                    root.remove(run)
        else:
            base = _neighbor_char(paragraph, place)
            gap = split_at(paragraph, place)
        old = list(paragraph.element)
        build_items(doc, paragraph, items, base_char=base, where="items")
        for offset, run in enumerate([child for child in paragraph.element if child not in old]):
            paragraph.element.insert(gap + offset, run)
        paragraph.section.mark_dirty()
        if any("footnote" in item for item in items):
            _renumber_footnotes(doc)
        _refuse_dangling_ids(doc)
        return {"inserted": len(items), "position": place, "replacedText": anchor_text if replace_anchor else None, "paragraphLength": sum(len(run.text or "") for run in paragraph.runs)}

    return _commit(filename, expected_revision, dry_run, apply)
