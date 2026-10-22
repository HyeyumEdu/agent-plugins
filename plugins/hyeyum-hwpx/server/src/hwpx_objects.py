"""문단 안 개체 지우기·고치기: delete_inline_object_ext, update_inline_object_ext.

개체는 `문단 주소 + kind + nth`로 가리킨다. nth는 그 문단의 같은 종류 개체 중 문서 순서 n번째이고,
`hwpx_read_layout(part="objects")`가 같은 문단에서 같은 kind로 보여 주는 순서와 같다(`_scan`이 hwpx_layout.objects_of와 같은 걸음으로 요소를 쥔다).
hwpx_edit를 가져오지 않는다(순환 방지).
"""
import math
import re
from typing import Any, NamedTuple

from hwpx.equation.measure import measure_equation
from hwpx.errors import HwpxError
from hwpx.oxml._document_primitives import _clear_paragraph_layout_cache, _sanitize_text
from hwpx.oxml.hyperlink_form import hyperlink_parameters, hyperlink_target
from hwpx.oxml.namespaces import HC, HP
from hwpx.oxml.section_story import sync_story_mirrors
from hwpx.oxml.shape_position import validate_equation_base_unit

import hwpx_layout as layout
from hwpx_common import _HWPUNIT_PER_MM, ToolInputError, _commit, _refuse_dangling_ids, _renumber_endnotes, _renumber_footnotes
from hwpx_locate import ADDRESS_ARGS, address_group, addressed, resolve_paragraph

DELETE_KINDS = ("endnote", "footnote", "equation", "picture", "bookmark", "hyperlink", "ruby", "composed", "check_box", "shape", "field")
UPDATE_KINDS = ("equation", "picture", "bookmark", "hyperlink", "check_box")
_PROPERTY_KEYS = {
    "equation": ("script", "base_unit", "width_mm", "height_mm"),
    "picture": ("width_mm", "height_mm", "brightness", "contrast"),
    "bookmark": ("name",),
    "hyperlink": ("url",),
    "check_box": ("checked", "caption"),
}
_RUN, _CTRL, _T = f"{HP}run", f"{HP}ctrl", f"{HP}t"
_FIELD_SCOPES = {f"{HP}{name}" for name in ("header", "footer", "endNote", "footNote", "tc")}
_SHORT, _LONG = 40, 80  # preview length of a text in a response: deleted object / changed property
_ESTIMATE_NOTE = "The box and baseline are estimated from the script; Hancom recalculates the box when the equation is opened for editing."


# ---------------------------------------------------------------- finding the object

class _NoTables(dict):
    """hwpx_layout's table numbers: tables are not objects of these tools, any number will do."""

    def __missing__(self, key: Any) -> int:
        return 0


class _Found(NamedTuple):
    kind: str
    element: Any  # the object itself (for a field: its hp:fieldBegin)
    holder: Any  # its parent: the hp:run, or the hp:ctrl around it
    summary: dict[str, Any]  # the part="objects" item: kind, at and the properties of the kind


def _scan(paragraph: Any) -> list[_Found]:
    """The inline objects of a paragraph element in the order hwpx_read_layout(part="objects") lists them (the same walk as hwpx_layout.objects_of)."""
    found: list[_Found] = []
    text, opened = "", {}
    for run in paragraph.findall(_RUN):
        first = run.find(f"{HP}secPr") is not None
        for child in run:
            if not isinstance(child.tag, str):
                continue
            name = layout.ln(child)
            if name == "t":
                text += layout.t_text(child)
                continue
            if name in ("secPr", "tab"):
                continue
            for item in list(child) if name == "ctrl" else [child]:
                if not isinstance(item.tag, str):
                    continue
                if layout.ln(item) == "fieldEnd":
                    begun = opened.pop(item.get("beginIDRef"), None)
                    if begun is not None:
                        begun["text"] = text[begun["at"]:][:_SHORT]
                    continue
                summary = layout._ctrl_object(item, first, _SHORT) if name == "ctrl" else layout._run_object(item, _NoTables(), _SHORT)
                if summary is None:
                    continue
                summary = {"kind": summary.pop("kind"), "at": len(text), **summary}
                found.append(_Found(summary["kind"], item, child if name == "ctrl" else run, summary))
                if layout.ln(item) == "fieldBegin":
                    opened[item.get("id")] = summary
    return found


def _target(doc: Any, kind: str, nth: int, address: dict[str, Any], section_index: int | None) -> tuple[Any, _Found]:
    paragraph = resolve_paragraph(doc, section_index, **address)
    same = [item for item in _scan(paragraph.element) if item.kind == kind]
    if not 1 <= nth <= len(same):
        raise ToolInputError(f"nth {nth} is out of range: the paragraph has {len(same)} {kind} object(s), numbered 1-{len(same)}" if same else f"nth {nth}: the paragraph has no {kind} object")
    return paragraph, same[nth - 1]


def _check_target(kind: Any, allowed: tuple[str, ...], nth: Any) -> None:
    if not isinstance(kind, str) or kind not in allowed:
        raise ToolInputError(f"kind {kind!r} is not one of {list(allowed)}")
    if isinstance(nth, bool) or not isinstance(nth, int) or nth < 1:
        raise ToolInputError(f"nth must be a whole number >= 1 (1 = the first object of that kind in the paragraph), got {nth!r}")


def _clip(summary: dict[str, Any], limit: int = _SHORT) -> dict[str, Any]:
    return {key: value[:limit] if isinstance(value, str) else value for key, value in summary.items()}


# ---------------------------------------------------------------- removing

def _detach(marker: Any) -> Any:
    """Take *marker* out of its run, with the hp:ctrl around it when nothing else is in that; a run left blank goes unless it is the paragraph's only one.
    Returns the paragraph element (its layout cache is cleared)."""
    holder = marker.getparent()
    holder.remove(marker)
    run = holder
    if holder.tag == _CTRL:
        run = holder.getparent()
        if not len(holder):
            run.remove(holder)
    paragraph = run.getparent()
    if len(paragraph.findall(_RUN)) > 1 and all(child.tag == _T and not child.text and not len(child) for child in run):
        paragraph.remove(run)
    _clear_paragraph_layout_cache(paragraph)
    return paragraph


def _field_end(begin: Any, section_element: Any) -> Any | None:
    """The hp:fieldEnd that closes *begin* (its beginIDRef is the begin's id), the first one after it in document order. It may stand in another paragraph;
    a begin in a header, footer, note or cell is looked for inside that part only (a header is kept twice in the section, other parts may carry copied ids)."""
    scope = next((a for a in begin.iterancestors() if a.tag in _FIELD_SCOPES), section_element)
    seen = False
    for node in scope.iter(f"{HP}fieldBegin", f"{HP}fieldEnd"):
        if node is begin:
            seen = True
        elif seen and node.tag == f"{HP}fieldEnd" and node.get("beginIDRef") == begin.get("id"):
            return node
    return None


def _bookmark_links(doc: Any, name: str) -> list[tuple[Any, Any, Any]]:
    """(section, fieldBegin, Command parameter) of the hyperlinks that point at bookmark *name*: Command `?name;...` (a `|tip` may follow the name),
    or, when there is no Command (an older file), the field's name `#name`. The whole document is searched: a link may sit in another section."""
    escaped = "".join("\\" + ch if ch in ":?;#" else ch for ch in name)
    pattern = re.compile(r"^\?" + re.escape(escaped) + r"(?=[;|]|$)")
    links = []
    for section in doc.sections:
        for begin in section.element.iter(f"{HP}fieldBegin"):
            if begin.get("type") != "HYPERLINK":
                continue
            command = next((p for p in begin.iter(f"{HP}stringParam") if p.get("name") == "Command"), None)
            if (command is not None and pattern.match(command.text or "")) or (command is None and begin.get("name") == "#" + name):
                links.append((section, begin, command))
    return links


def _bookmark_names(doc: Any) -> set[str]:
    return {b.get("name") for section in doc.sections for b in section.element.iter(f"{HP}bookmark")}


def _delete(doc: Any, kind: str, nth: int, keep_text: bool, address: dict[str, Any], section_index: int | None) -> dict[str, Any]:
    paragraph, found = _target(doc, kind, nth, address, section_index)
    element, warnings = found.element, []
    out: dict[str, Any] = {"deleted": _clip(found.summary)}
    if kind in ("hyperlink", "field"):
        if element.get("type") == "MEMO":
            raise ToolInputError("this field anchors a memo (type MEMO); use remove_memo, which also removes the memo text that is kept elsewhere in the section")
        end = _field_end(element, paragraph.section.element)
        ends = [end] if end is not None else []
        if not ends:
            warnings.append("no matching fieldEnd was found; only the start of the field was removed")
        for marker in [element, *ends]:  # the display text between them stays
            _detach(marker)
        out["fieldEndsRemoved"] = len(ends)
        if kind == "hyperlink":
            out["note"] = "the text is kept with the link's blue underlined look; reformat it with format_text_ext"
    elif kind in ("ruby", "composed") and keep_text:
        text = (element.findtext(f"{HP}mainText") if kind == "ruby" else element.get("composeText")) or ""
        if text:
            plain = element.makeelement(_T, {})
            plain.text = _sanitize_text(text) or None
            found.holder.replace(element, plain)  # the text takes the object's place in the same run, so it keeps the run's character shape
            _clear_paragraph_layout_cache(paragraph.element)
        else:
            _detach(element)
    else:
        _detach(element)
    if kind == "endnote":
        _renumber_endnotes(doc)
    elif kind == "footnote":
        _renumber_footnotes(doc)
    elif kind == "bookmark":
        broken = len(_bookmark_links(doc, found.summary.get("name") or ""))
        if broken:
            warnings.append(f"{broken} hyperlink(s) pointed at the deleted bookmark {found.summary.get('name')!r} and now lead nowhere; unlink or retarget them")
    if kind in ("picture", "shape"):
        sync_story_mirrors(paragraph.section)  # a header/footer lives twice in the section; the unused-image check must not see the old copy
        out["removedImages"] = len(doc.media.remove_unused_images())
        if layout.ln(element) == "chart":
            out["removedCharts"] = len(doc.shapes.remove_unused_charts())
    else:
        out["removedImages"] = 0
    out["remaining"] = sum(item.kind == kind for item in _scan(paragraph.element))
    out["warnings"] = warnings
    paragraph.section.mark_dirty()
    _refuse_dangling_ids(doc)
    return out


@addressed
def delete_inline_object_ext(
    filename: str,
    kind: str,
    nth: int = 1,
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
    keep_text: bool = True,
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Delete one object that stands inside a paragraph (also inside a table cell, endnote, footnote, header or footer).
    Paragraph: {ADDRESS}
    Object: `kind` + `nth` (1-based; the n-th object of that kind in the paragraph, in document order - the same numbering as hwpx_read_layout part="objects" gives for the paragraph). kind is one of
    endnote, footnote, equation, picture, bookmark, hyperlink, ruby, composed (overlapped characters), check_box, shape (drawing object, text box, chart ...), field (a field that is not a hyperlink).
    A table is not deleted here (apply_table_ops delete_table), neither is a memo (remove_memo; a MEMO field is refused).
    hyperlink / field: the link or field is removed but its display text stays (unlink); the text keeps the link's blue underlined look, reformat it with format_text_ext.
    ruby / composed: the base text (the ruby's main text, the composed characters) stays as plain text in the same character shape; keep_text=false deletes it too (keep_text=false is refused for the other kinds).
    endnote / footnote: the remaining notes are renumbered in document order. picture / shape: the embedded image (BinData) is dropped when nothing else in the document uses it (`removedImages`; a chart's data too: `removedCharts`).
    bookmark: hyperlinks pointing at it are not blocked but counted in `warnings`.
    Returns `deleted` (the part="objects" item of the object, texts cut to 40 characters), `remaining` (objects of that kind left in the paragraph), `removedImages`, `warnings`. dry_run=true saves nothing."""
    address = {key: value for key, value in locals().items() if key in ADDRESS_ARGS}
    _check_target(kind, DELETE_KINDS, nth)
    if not isinstance(keep_text, bool):
        raise ToolInputError("keep_text must be true or false")
    if not keep_text and kind not in ("ruby", "composed"):
        raise ToolInputError(f"keep_text=false only applies to kind ruby or composed, not {kind!r}")
    address_group(**address)
    return _commit(filename, expected_revision, dry_run, lambda doc: _delete(doc, kind, nth, keep_text, address, section_index))


# ---------------------------------------------------------------- updating

def _record(changed: dict[str, Any], name: str, before: Any, after: Any, show: Any = None) -> None:
    if before != after:
        show = show or (lambda value: value)
        changed[name] = {"before": show(before), "after": show(after)}


def _mm(unit: int) -> float:
    return round(unit / _HWPUNIT_PER_MM, 2)


def _text(value: str) -> str:
    return value[:_LONG]


def _new_size(props: dict[str, Any], width: int, height: int) -> tuple[int, int]:
    """The size (HWPUNIT) after width_mm / height_mm of *props*; one alone keeps the proportion of (width, height)."""
    given = [round(props[key] * _HWPUNIT_PER_MM) if key in props else None for key in ("width_mm", "height_mm")]
    new_w, new_h = given
    if new_w is None and new_h is None:
        return width, height
    if new_w is None:
        new_w = max(1, round(new_h * width / height)) if height else width
    if new_h is None:
        new_h = max(1, round(new_w * height / width)) if width else height
    return new_w, new_h


def _scale(value: int, base: int) -> str:
    """A scaMatrix factor as Hancom writes it: six decimals, trailing zeros dropped."""
    return f"{round(value / base, 6):.6f}".rstrip("0").rstrip(".")


def _update_equation(doc: Any, element: Any, props: dict[str, Any]) -> dict[str, Any]:
    sz, script_element = element.find(f"{HP}sz"), element.find(f"{HP}script")
    if sz is None or script_element is None:
        raise ToolInputError("this equation has no hp:sz or hp:script element and cannot be edited")
    old_script = (script_element.text or "").strip()
    old_unit, old_line = int(element.get("baseUnit") or 0), int(element.get("baseLine") or 0)
    old_size = (int(sz.get("width") or 0), int(sz.get("height") or 0))
    script = _sanitize_text(props["script"]).strip() if "script" in props else old_script
    if not script:
        raise ToolInputError("properties.script must not be empty after removing control characters")
    unit = props.get("base_unit", old_unit or 1000)
    (width, height), line, out = old_size, old_line, {}
    if script != old_script or (unit != old_unit and not old_unit):
        box = measure_equation(script, base_unit=unit)
        width, height, line = box.width, box.height, box.base_line
        out.update(estimated=True, note=_ESTIMATE_NOTE)
    elif unit != old_unit:  # same script, other base size: the box grows with it as it is (a measured box is not Hancom's), the baseline is a share of the height and stays
        width, height = (max(1, round(value * unit / old_unit)) for value in old_size)
    width, height = _new_size(props, width, height)
    changed: dict[str, Any] = {}
    _record(changed, "script", old_script, script, _text)
    _record(changed, "base_unit", old_unit, unit)
    _record(changed, "base_line", old_line, line)
    _record(changed, "width_mm", old_size[0], width, _mm)
    _record(changed, "height_mm", old_size[1], height, _mm)
    if changed:
        script_element.text = script
        element.set("baseUnit", str(unit))
        element.set("baseLine", str(line))
        sz.set("width", str(width))
        sz.set("height", str(height))
    return {"changed": changed, **(out if changed else {})}


def _update_picture(doc: Any, element: Any, props: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    if "width_mm" in props or "height_mm" in props:
        sz, current, original, rotation = (element.find(f"{HP}{name}") for name in ("sz", "curSz", "orgSz", "rotationInfo"))
        scales = element.findall(f"{HP}renderingInfo/{HC}scaMatrix")
        if sz is None or original is None or len(scales) != 1:
            raise ToolInputError(f"this picture cannot be resized: it needs hp:sz, hp:orgSz and exactly one hc:scaMatrix (found {len(scales)})")
        if rotation is not None and float(rotation.get("angle") or 0) != 0:
            raise ToolInputError("this picture is rotated (rotationInfo angle is not 0); resizing a rotated picture is not supported")
        old = (int(sz.get("width")), int(sz.get("height")))
        org = (int(original.get("width")), int(original.get("height")))
        if min(org) < 1 or min(old) < 1:
            raise ToolInputError("this picture has a zero original or current size and cannot be resized")
        width, height = _new_size(props, *old)
        # what Hancom writes for a picture it has resized: sz and curSz are the new size, the scale (scaMatrix e1/e5) is size/orgSz, the rotation centre is half the size;
        # orgSz, imgRect, imgClip, imgDim and the move part of the matrices stay
        for target in (sz, current):
            if target is not None:
                target.set("width", str(width))
                target.set("height", str(height))
        scales[0].set("e1", _scale(width, org[0]))
        scales[0].set("e5", _scale(height, org[1]))
        if rotation is not None:
            rotation.set("centerX", str(width // 2))
            rotation.set("centerY", str(height // 2))
        _record(changed, "width_mm", old[0], width, _mm)
        _record(changed, "height_mm", old[1], height, _mm)
    if "brightness" in props or "contrast" in props:
        image = next(element.iter(f"{HC}img"), None)
        if image is None:
            raise ToolInputError("this picture has no hc:img element")
        for key, name in (("brightness", "bright"), ("contrast", "contrast")):
            if key in props:
                _record(changed, key, int(image.get(name) or 0), props[key])
                image.set(name, str(props[key]))
    return {"changed": changed}


def _update_bookmark(doc: Any, element: Any, props: dict[str, Any]) -> dict[str, Any]:
    old, new = element.get("name") or "", props["name"]
    if new == old:
        return {"changed": {}}
    if new in _bookmark_names(doc):
        raise ToolInputError(f"a bookmark named {new!r} already exists in the document; bookmark names must be unique")
    links = _bookmark_links(doc, old)
    element.set("name", new)
    escaped = "".join("\\" + ch if ch in ":?;#" else ch for ch in new)
    for section, begin, command in links:
        if command is not None:
            command.text = re.sub(r"^\?(?:[^;|\\]|\\.)*", lambda _: "?" + escaped, command.text)
        if begin.get("name") == "#" + old:
            begin.set("name", "#" + new)
        section.mark_dirty()
    return {"changed": {"name": {"before": old, "after": new}}, "updatedLinks": len(links)}


def _update_hyperlink(doc: Any, element: Any, props: dict[str, Any]) -> dict[str, Any]:
    url, old = props["url"], hyperlink_target(element)
    current = element.find(f"{HP}parameters")
    if url == old and current is not None:
        return {"changed": {}}
    params = hyperlink_parameters(url)  # a bookmark, mail and web address differ in Command tail, Path and Category: all of it is rebuilt
    fresh = element.makeelement(f"{HP}parameters", {"cnt": str(len(params)), "name": ""})
    for tag, name, text in params:
        fresh.append(fresh.makeelement(f"{HP}{tag}", {"name": name}))
        fresh[-1].text = text
    if current is None:
        element.insert(0, fresh)
    else:
        element.replace(current, fresh)
    if element.get("name"):  # older files keep the address here too
        element.set("name", url)
    warnings = [f"no bookmark named {url[1:]!r} in the document; the link leads nowhere until one exists"] if url.startswith("#") and url[1:] not in _bookmark_names(doc) else []
    return {"changed": {"url": {"before": _text(old), "after": _text(url)}}, "warnings": warnings}


def _update_check_box(doc: Any, element: Any, props: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    if "checked" in props:
        _record(changed, "checked", element.get("value") == "CHECKED", props["checked"])
        element.set("value", "CHECKED" if props["checked"] else "UNCHECKED")
    if "caption" in props:
        caption = _sanitize_text(props["caption"])
        _record(changed, "caption", element.get("caption") or "", caption, _text)
        element.set("caption", caption)
    return {"changed": changed}


_UPDATERS = {"equation": _update_equation, "picture": _update_picture, "bookmark": _update_bookmark, "hyperlink": _update_hyperlink, "check_box": _update_check_box}


def _positive_mm(props: dict[str, Any], key: str) -> None:
    value = props[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < round(value * _HWPUNIT_PER_MM) < 2**31:
        raise ToolInputError(f"properties.{key} must be a positive number of mm (at most {_mm(2**31 - 1)}), got {value!r}")


def _check_properties(kind: str, props: Any) -> None:
    if not isinstance(props, dict) or not props:
        raise ToolInputError(f"properties must be a non-empty object; for {kind} the keys are {list(_PROPERTY_KEYS[kind])}")
    if kind == "picture" and "treat_as_char" in props:
        raise ToolInputError("properties.treat_as_char is not supported yet")
    unknown = sorted(set(props) - set(_PROPERTY_KEYS[kind]))
    if unknown:
        raise ToolInputError(f"unknown properties {unknown} for {kind}; allowed: {list(_PROPERTY_KEYS[kind])}")
    for key in ("width_mm", "height_mm"):
        if key in props:
            _positive_mm(props, key)
    for key in ("script", "name", "url"):
        if key in props and (not isinstance(props[key], str) or not props[key].strip()):
            raise ToolInputError(f"properties.{key} must be a non-empty string")
    for key in ("brightness", "contrast"):
        if key in props and (isinstance(props[key], bool) or not isinstance(props[key], int) or not -100 <= props[key] <= 100):
            raise ToolInputError(f"properties.{key} must be a whole number from -100 to 100, got {props[key]!r}")
    if "base_unit" in props:
        try:
            validate_equation_base_unit(props["base_unit"])
        except HwpxError as error:
            raise ToolInputError(f"properties.base_unit: {error}") from error
    if "checked" in props and not isinstance(props["checked"], bool):
        raise ToolInputError("properties.checked must be true or false")
    if "caption" in props and not isinstance(props["caption"], str):
        raise ToolInputError("properties.caption must be a string")


def _update(doc: Any, kind: str, nth: int, props: dict[str, Any], address: dict[str, Any], section_index: int | None) -> dict[str, Any]:
    paragraph, found = _target(doc, kind, nth, address, section_index)
    out = _UPDATERS[kind](doc, found.element, props)
    out.setdefault("warnings", [])
    if out["changed"]:
        _clear_paragraph_layout_cache(paragraph.element)
        paragraph.section.mark_dirty()
    else:
        out["warnings"].append("no property differs from the current value; nothing was changed")
    out.update(kind=kind, at=found.summary["at"])
    _refuse_dangling_ids(doc)
    return out


@addressed
def update_inline_object_ext(
    filename: str,
    kind: str,
    properties: dict[str, Any],
    nth: int = 1,
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
    """Change properties of one object that stands inside a paragraph (also inside a table cell, endnote, footnote, header or footer).
    Paragraph: {ADDRESS}
    Object: `kind` + `nth` (1-based; the n-th object of that kind in the paragraph, in document order - the same numbering as hwpx_read_layout part="objects" gives for the paragraph).
    `properties` holds only the keys of the kind (anything else is refused with the allowed list):
    equation: `script` (EqEdit, not empty), `base_unit` (1/100 pt), `width_mm`, `height_mm`. Same script with another base_unit: the box is scaled in proportion. A new script: the box and baseline are re-estimated
    (`estimated: true`; Hancom recalculates the box when the equation is opened for editing). width_mm / height_mm win over the box; one alone keeps the proportion.
    picture: `width_mm`, `height_mm` (one alone keeps the proportion; sets the size the way Hancom stores a resized picture and keeps the image crop; a rotated picture is refused), `brightness`, `contrast` (-100..100). treat_as_char is not supported yet.
    bookmark: `name` (not empty, unique in the document); hyperlinks pointing at the old name follow (`updatedLinks`).
    hyperlink: `url` (web address, `mailto:` address or `#bookmark`); the link target is rebuilt in the form Hancom reads. The display text is not changed (edit_paragraph_text_ext).
    check_box: `checked` (true/false), `caption`.
    Returns `changed` ({property: {before, after}}; sizes in mm, long texts cut to 80 characters), `warnings`, and `estimated` / `updatedLinks` where they apply. dry_run=true saves nothing."""
    address = {key: value for key, value in locals().items() if key in ADDRESS_ARGS}
    _check_target(kind, UPDATE_KINDS, nth)
    _check_properties(kind, properties)
    address_group(**address)
    return _commit(filename, expected_revision, dry_run, lambda doc: _update(doc, kind, nth, properties, address, section_index))
