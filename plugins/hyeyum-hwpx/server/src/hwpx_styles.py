"""스타일·번호 도구: 이름 붙은 스타일 적용·정의와 글머리표/번호 목록 서식.

쓰기 절차는 hwpx_common._commit. hwpx_edit는 가져오지 않는다(순환 import 방지).
"""
from typing import Any, Literal

from hwpx.errors import HwpxLookupError
from hwpx.oxml.namespaces import HH, HP
from hwpx_common import ToolInputError, _char_ref, _check_keys, _check_paragraph_indexes, _commit, _refuse_dangling_ids, _RUN_KEYS

#: 한컴 기본 스타일 이름(새 문서 헤더에 있는 23종). 헤더에 있으면 덮어쓰지 않는다.
_DEFAULT_STYLE_NAMES = frozenset({
    "바탕글", "본문", *(f"개요 {n}" for n in range(1, 11)), "쪽 번호", "줄 번호", "머리말", "각주", "미주", "메모",
    "차례 제목", "차례 1", "차례 2", "차례 3", "캡션",
})


def _style_elements(doc: Any) -> list[Any]:
    return list(doc.oxml.headers[0].element.iter(f"{HH}style"))


def resolve_style(doc: Any, style: str) -> tuple[str, str, str, str]:
    """이름·영문 이름·id로 고른 스타일의 (style_id, para_pr_id, char_pr_id, kind). kind는 "PARA"/"CHAR".
    paraPrIDRef/charPrIDRef가 없으면 "0". 없는 스타일·모호한 이름은 파일의 스타일 목록과 함께 거절한다."""
    wanted = "" if style is None else str(style).strip()
    if not wanted:
        raise ToolInputError("style must be a style name, English name or id")
    try:
        found = doc.styles.resolve(wanted)
    except HwpxLookupError as error:
        if error.code == "style-ambiguous":
            raise ToolInputError(f"style {wanted!r} is ambiguous: {error.suggestion}") from error
        listed = ", ".join(f"{item.get('name')} (id {item.get('id')})" for item in _style_elements(doc))
        raise ToolInputError(f"style {wanted!r} is not defined in the file; styles it has (name or English name or id works): {listed}") from error
    element = next(item for item in _style_elements(doc) if item.get("id") == found.raw_id)
    return (found.raw_id, element.get("paraPrIDRef", "0"), element.get("charPrIDRef", "0"), (element.get("type") or "PARA").upper())


def _check_indexes(doc: Any, indexes: list[int] | None, what: str = "paragraph_indexes") -> list[int]:
    if not indexes:
        raise ToolInputError(f"{what} must list at least one body paragraph index")
    _check_paragraph_indexes(doc, indexes)
    return list(indexes)


def apply_style_ext(
    filename: str,
    paragraph_indexes: list[int],
    style: str,
    apply_para: Literal["style", "keep"] = "style",
    apply_char: Literal["keep", "style"] = "keep",
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Apply a named style (by Korean name, English name or id; see hwpx_read_layout part="header" kind="style") to body paragraphs. Apply a style BEFORE local formatting: by default it replaces the paragraph's own shape (indents, alignment ...) with the style's.
    A paragraph style sets the paragraph's style reference. apply_para="style" (default) also gives the paragraph the style's paragraph shape
    (indents, spacing, alignment, list numbering - replacing the paragraph's own); "keep" sets only the style reference and leaves the paragraph's shape as it is
    (Hancom itself keeps a paragraph's own shape after a user overrides it inside a styled paragraph).
    apply_char="style" also sets every run of the paragraph to the style's character shape; "keep" (default) leaves the runs' character shapes.
    A character style (type CHAR) has no paragraph reference: it needs apply_char="style" (apply_para is ignored) and only sets the runs' character shape.
    An unknown style is refused with the list of styles the file has. dry_run=true saves nothing."""
    if apply_para not in ("style", "keep") or apply_char not in ("keep", "style"):
        raise ToolInputError(f"apply_para must be 'style' or 'keep' and apply_char 'keep' or 'style'; got {apply_para!r} and {apply_char!r}")

    def apply(doc: Any) -> dict[str, Any]:
        indexes = _check_indexes(doc, paragraph_indexes)
        style_id, para_pr_id, char_pr_id, kind = resolve_style(doc, style)
        if kind == "CHAR" and apply_char != "style":
            raise ToolInputError(f"style {style!r} is a character style: it only sets character shapes, so pass apply_char='style'")
        replaced = []
        for index in indexes:
            paragraph = doc.paragraphs[index]
            if kind == "PARA":
                paragraph.style_id_ref = style_id
                if apply_para == "style":
                    if str(paragraph.para_pr_id_ref) != str(para_pr_id):
                        replaced.append(index)
                    paragraph.para_pr_id_ref = para_pr_id
            if apply_char == "style":
                paragraph.char_pr_id_ref = char_pr_id
        result = {
            "styled": len(indexes), "paragraphs": indexes, "styleIDRef": style_id, "kind": kind,
            "paraPrIDRef": para_pr_id if kind == "PARA" and apply_para == "style" else None,
            "charPrIDRef": char_pr_id if apply_char == "style" else None,
        }
        if replaced:
            result["replacedParagraphShape"] = replaced
            result["note"] = "these paragraphs lost their own paragraph shape (indents, alignment, tabs, border ...) to the style's; format them again after applying the style, or use apply_para='keep'"
        return result

    return _commit(filename, expected_revision, dry_run, apply)


def _shapes_of_paragraph(doc: Any, index: int) -> tuple[str, str]:
    """문단의 paraPr와, 글이 있는 첫 run(없으면 첫 run)의 charPr."""
    paragraph = doc.paragraphs[_check_indexes(doc, [index], "from_paragraph_index")[0]]
    runs = paragraph.element.findall(f"{HP}run")
    run = next((r for r in runs if any("".join(t.itertext()) for t in r.findall(f"{HP}t"))), runs[0] if runs else None)
    if run is None or run.get("charPrIDRef") is None:
        raise ToolInputError(f"paragraph {index} has no run with a character shape; give para_pr_id and char_pr_id instead of from_paragraph_index")
    return paragraph.para_pr_id_ref or "0", run.get("charPrIDRef")


def define_style_ext(
    filename: str,
    name: str,
    from_paragraph_index: int | None = None,
    para_pr_id: str | None = None,
    char_pr_id: str | None = None,
    next_style: str | None = None,
    kind: Literal["PARA", "CHAR"] | None = None,
    eng_name: str | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Create a named style, or update the style of that name (only the arguments you pass change). Returns its id (a string); apply it with apply_style_ext.
    The style's shapes come from from_paragraph_index (that body paragraph's paragraph shape and the character shape of its first text run) or from para_pr_id / char_pr_id
    (ids that already exist in the file, see hwpx_read_layout part="header"); the two ways are exclusive. A new style without them uses shape 0.
    kind: "PARA" (default for a new style) styles paragraphs; "CHAR" styles runs (needs no para_pr_id). An existing style's kind cannot be changed.
    next_style: the paragraph style (name, English name or id) a new paragraph takes after Enter; the style's own name makes it follow itself (a new paragraph style does by default).
    Hancom's 23 built-in style names (바탕글, 본문, 개요 1-10, 쪽 번호, 줄 번호, 머리말, 각주, 미주, 메모, 차례 제목, 차례 1-3, 캡션) cannot be overwritten, and a name or eng_name that is
    already another style's name or English name is refused (it would make that name ambiguous). dry_run=true saves nothing."""
    label = (name or "").strip()
    if not label:
        raise ToolInputError("name must not be empty")
    if from_paragraph_index is not None and (para_pr_id is not None or char_pr_id is not None):
        raise ToolInputError("from_paragraph_index and para_pr_id/char_pr_id are exclusive: give the paragraph or the ids")
    if kind not in (None, "PARA", "CHAR"):
        raise ToolInputError(f"kind must be 'PARA' or 'CHAR'; got {kind!r}")

    def apply(doc: Any) -> dict[str, Any]:
        elements = _style_elements(doc)
        current = next((item for item in elements if item.get("name") == label), None)
        if current is not None and label in _DEFAULT_STYLE_NAMES:
            raise ToolInputError(f"style {label!r} is one of Hancom's built-in styles and cannot be overwritten; define a style with another name")
        if current is not None and kind is not None and (current.get("type") or "PARA") != kind:
            raise ToolInputError(f"style {label!r} is a {current.get('type')} style; its kind cannot be changed to {kind!r}")
        others = {(value or "").strip() for item in elements if item is not current for value in (item.get("name"), item.get("engName"))} - {""}
        for wanted, argument in ((label, "name"), ((eng_name or "").strip(), "eng_name")):
            if wanted in others:
                raise ToolInputError(f"{argument} {wanted!r} is already the name or English name of another style")
        created = current is None
        style_kind = kind or (current.get("type") if not created else None) or "PARA"
        para, char = para_pr_id, char_pr_id
        if from_paragraph_index is not None:
            para, char = _shapes_of_paragraph(doc, from_paragraph_index)
        if style_kind == "CHAR" and (para_pr_id is not None or next_style is not None):
            raise ToolInputError("a CHAR style has no paragraph shape or next style: leave out para_pr_id and next_style")
        if not created and all(value is None for value in (para, char, next_style, eng_name)):
            raise ToolInputError(f"style {label!r} already exists; give from_paragraph_index, para_pr_id, char_pr_id, next_style or eng_name to change it")
        if style_kind == "CHAR":
            para = "0" if created else None  # 한컴은 글자 스타일에도 paraPrIDRef="0"을 쓴다
        elif created:
            para = para or "0"
        own = {label, (eng_name or "").strip(), *((current.get(key) or "").strip() for key in ("engName", "id") if current is not None)} - {""}
        follows_itself = next_style is not None and str(next_style).strip() in own
        wanted_next = None
        if next_style is not None and not follows_itself:  # 아무것도 바꾸기 전에 확인해야 오류가 파일의 스타일 목록을 보여 준다
            wanted_next, next_kind = resolve_style(doc, next_style)[::3]
            if next_kind != "PARA":
                raise ToolInputError(f"next_style {next_style!r} is a {next_kind} style; a next style must be a paragraph style")
        header = doc.oxml.headers[0]
        style_id = header.ensure_style(
            label, style_type=style_kind if created else None, eng_name=eng_name, para_pr_id_ref=para,
            char_pr_id_ref=char or ("0" if created else None), lang_id=1042 if created else None,
        )
        if follows_itself or (next_style is None and created):  # 새 스타일은 한컴처럼 자기 자신을 잇는다(글자 스타일은 0)
            wanted_next = style_id if style_kind == "PARA" else "0"
        if wanted_next is not None:
            header.ensure_style(label, next_style_id_ref=wanted_next)
        _refuse_dangling_ids(doc)
        fresh = next(item for item in _style_elements(doc) if item.get("id") == style_id)
        return {
            "styleIDRef": style_id, "name": label, "kind": fresh.get("type"), "created": created,
            "paraPrIDRef": fresh.get("paraPrIDRef"), "charPrIDRef": fresh.get("charPrIDRef"), "nextStyleIDRef": fresh.get("nextStyleIDRef"),
        }

    return _commit(filename, expected_revision, dry_run, apply)


def set_list_format_ext(
    filename: str,
    paragraph_indexes: list[int],
    kind: Literal["number", "bullet", "outline"] = "number",
    level: int = 1,
    number_format: str | None = None,
    bullet_char: str | None = None,
    start: int | None = None,
    continue_list: bool = False,
    number_char: dict[str, Any] | None = None,
    number_char_pr_id: str | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Number or bullet body paragraphs (list numbering shape, as Hancom's 번호 매기기 / 글머리표 / 개요 번호).
    Paragraphs given in one call form one list (numbered on from start); a separate call makes a new numbering definition and restarts at 1 - to number on from an
    earlier list use continue_list=true (it continues the last list of that kind before the first target paragraph, or starts a new one if there is none).
    kind: "number" (번호), "bullet" (글머리표) or "outline" (개요). level: 1-10. number_format (number/outline, case-insensitive): DIGIT, CIRCLED_DIGIT, ROMAN_CAPITAL, ROMAN_SMALL,
    LATIN_CAPITAL, LATIN_SMALL, CIRCLED_LATIN_CAPITAL, CIRCLED_LATIN_SMALL, HANGUL_SYLLABLE, CIRCLED_HANGUL_SYLLABLE, HANGUL_JAMO, CIRCLED_HANGUL_JAMO, HANGUL_PHONETIC, IDEOGRAPH,
    CIRCLED_IDEOGRAPH (short names NUMBER, ROMAN, ALPHA, HANGUL also work). bullet_char (bullet only): the bullet, e.g. "●". start (number/outline): first number, 0-65535.
    number_char (number/outline): character options of the number itself, e.g. {"font_size": 13, "bold": true} for a question number bigger than the 10 pt text
    (keys: bold, italic, underline, underline_shape, underline_color, strike, strike_shape, color, highlight, font_name, font_size in pt, ratio in %, letter_spacing in %, script, offset, use_font_space, emphasis_mark, use_kerning);
    number_char_pr_id: an existing character shape id instead (exclusive with number_char). continue_list cannot be combined with number_format, start, number_char or number_char_pr_id
    (a continued list keeps the format of the list before it). Replaces the paragraphs' paragraph shape with a copy that has the list heading. dry_run=true saves nothing."""
    if kind not in ("number", "bullet", "outline"):
        raise ToolInputError(f"kind must be 'number', 'bullet' or 'outline'; got {kind!r}")
    if number_char is not None and number_char_pr_id is not None:
        raise ToolInputError("number_char and number_char_pr_id are exclusive: give the options or an existing character shape id")
    if number_char is not None:
        if not number_char:
            raise ToolInputError("number_char is empty: give at least one character option, e.g. {\"font_size\": 13}")
        _check_keys(number_char, _RUN_KEYS, "number_char")
    shaping = {"number_format": number_format, "start": start, "number_char": number_char, "number_char_pr_id": number_char_pr_id}
    given = [key for key, value in shaping.items() if value is not None]
    if continue_list and given:
        raise ToolInputError(f"continue_list cannot be combined with {given}: a continued list keeps the format of the list before it")
    if kind == "bullet" and given:
        raise ToolInputError(f"{given} apply to number and outline lists only, not kind='bullet'")
    if kind != "bullet" and bullet_char is not None:
        raise ToolInputError("bullet_char applies to kind='bullet' only")

    def apply(doc: Any) -> dict[str, Any]:
        indexes = _check_indexes(doc, paragraph_indexes)
        shape_id = _char_ref(doc, number_char) if number_char else number_char_pr_id
        result = doc.styles.apply_list_format(
            paragraph_indexes=indexes, kind=kind, level=level, bullet_char=bullet_char, number_format=number_format, start=start,
            continue_list=continue_list, number_char_pr_id_ref=shape_id,
        ).to_dict()
        result["numberCharPrIDRef"] = None if shape_id is None else str(shape_id)
        return result

    return _commit(filename, expected_revision, dry_run, apply)
