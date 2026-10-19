"""문서 단위 쓰기 도구: 같은 구역 안 문단 복제(copy_paragraphs_ext)와 다른 hwpx 끼워 넣기(insert_document_ext).

쓰기 절차는 hwpx_common._commit. hwpx_edit는 가져오지 않는다(순환 import 방지).
"""
from collections import Counter
from typing import Any

from hwpx.oxml.namespaces import HH, HP
from hwpx.tools import document_merge
from hwpx_automation.core.document import open_doc
from hwpx_automation.workspace import WorkspaceResolver

from hwpx_common import (
    ToolInputError, _commit, _holds_section_definition, _refuse_dangling_ids, _renumber_endnotes, _renumber_footnotes, _section,
)


def _renumber_and_check(doc: Any) -> None:
    """옮겨 온 미주·각주의 번호를 문서 순서로 다시 매기고, 헤더에 없는 id를 가리키면 거절한다."""
    _renumber_endnotes(doc)
    _renumber_footnotes(doc)
    _refuse_dangling_ids(doc)


def copy_paragraphs_ext(
    filename: str,
    start_index: int,
    end_index: int,
    before_index: int | None = None,
    section_index: int = 0,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Duplicate a range of body paragraphs of one section (tables, endnotes, footnotes, pictures and equations come along) and insert the copies in the same section: repeat a question template.
    start_index..end_index: the closed range to copy (both ends included), 0-based body paragraph numbers inside the section (the `i` of hwpx_read_layout part="body" with the same section).
    before_index: insert the copies in front of this paragraph (0..paragraph count; may lie inside the copied range); omit to append at the end of the section. section_index: which section (default the first).
    The range may not contain, and before_index may not name, the first paragraph of a section: it holds the section definition (page setup, columns) that has to stay first.
    Endnote and footnote numbers are renumbered in document order afterwards. Bookmark names and field ids are copied unchanged, so a copied bookmark or hyperlink repeats them (see `warnings` in the result).
    Returns the number of copies, the index of the first new paragraph and `warnings`. dry_run=true saves nothing."""

    def apply(doc: Any) -> dict[str, Any]:
        section = _section(doc, section_index)
        paragraphs = section.paragraphs
        total = len(paragraphs)
        if not 0 <= start_index <= end_index < total:
            raise ToolInputError(f"start_index {start_index} / end_index {end_index} must satisfy 0 <= start_index <= end_index < {total} (section {section_index} has {total} body paragraphs)")
        target = total if before_index is None else before_index
        if not 0 <= target <= total:
            raise ToolInputError(f"before_index {before_index} is out of range (0..{total})")
        held = next((i for i in range(start_index, end_index + 1) if _holds_section_definition(paragraphs[i])), None)
        if held is not None:
            raise ToolInputError(f"paragraph {held} holds the section definition (page setup, columns) and cannot be copied; start_index must be {held + 1} or later")
        if target < total and _holds_section_definition(paragraphs[target]):
            raise ToolInputError(f"before_index {before_index} is the paragraph that holds the section definition (page setup, columns); "
                                 "a copy in front of it would push that definition out of first place - use before_index 1 or later")
        copies = section.copy_paragraph_range(start_index, end_index)
        section.insert_paragraphs(target, copies)
        _renumber_and_check(doc)
        warnings = []
        bookmarks = sorted({e.get("name") for c in copies for e in c.iter(f"{HP}bookmark") if e.get("name")})
        if bookmarks:
            warnings.append(f"bookmark name(s) {bookmarks[:10]} now exist twice (copies keep the original names); rename one of each pair")
        fields = sum(1 for c in copies for _ in c.iter(f"{HP}fieldBegin"))
        if fields:
            warnings.append(f"{fields} field(s) (hyperlink, click-here ...) were copied with the same field ids as the originals")
        return {"copied": len(copies), "sectionIndex": section_index, "range": [start_index, end_index], "firstNewParagraphIndex": target, "warnings": warnings}

    return _commit(filename, expected_revision, dry_run, apply)


def _resolve_source(name: str) -> str:
    """작업 영역 안의 경로. 거절 사유에는 경로를 싣지 않는다."""
    try:
        path = WorkspaceResolver.from_environment().resolve(name, must_exist=True)
    except FileNotFoundError:
        raise ToolInputError("source_filename does not exist in the workspace") from None
    except PermissionError as error:  # WorkspacePathError: 작업 폴더 밖, 심볼릭 링크 탈출, 잘못된 경로
        raise ToolInputError(f"source_filename is not allowed: {getattr(error, 'reason', 'permission denied')}") from None
    if not path.is_file():
        raise ToolInputError("source_filename is not a file")
    return str(path)


def _style_names(doc: Any) -> Counter:
    return Counter(e.get("name") for e in doc.oxml.headers[0].element.iter(f"{HH}style"))


def insert_document_ext(
    filename: str,
    source_filename: str,
    after_paragraph_index: int | None = None,
    source_section_index: int | None = None,
    target_section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Insert the body of another .hwpx file of the workspace into this one (Hancom's 문서 끼워 넣기): paragraphs, tables, pictures, notes, with their paragraph/character shapes, styles, borders and numberings copied over.
    source_filename: the document to take the content from (read only; it must be inside the workspace). The target's page setup stays; the source's page setup is dropped, but a header/footer set in the source's first paragraph comes along as a control.
    after_paragraph_index: insert after this 0-based body paragraph of the target section; -1 inserts before the first paragraph (the section definition stays first). Omit to append at the end of the section.
    source_section_index: take only this section of the source (default: all its sections, in order). target_section_index: the section of this file to insert into (default the first when after_paragraph_index is given, else the last).
    Source styles are copied under new ids, never merged with same-named ones of this file (names then exist twice; see `warnings`). Endnote and footnote numbers are renumbered in document order afterwards.
    Refused for sources with connector lines, linked text boxes or charts. Returns paragraphsInserted, the index of the first new paragraph, what was copied (`remapped`) and `warnings`. dry_run=true saves nothing."""
    source_path = _resolve_source(source_filename)

    def apply(doc: Any) -> dict[str, Any]:
        at_front = after_paragraph_index is not None
        target_index = target_section_index if target_section_index is not None else (0 if at_front else len(doc.sections) - 1)
        section = _section(doc, target_index, "target_section_index")
        total = len(section.paragraphs)
        if at_front and not -1 <= after_paragraph_index < total:
            raise ToolInputError(f"after_paragraph_index {after_paragraph_index} is out of range (-1..{total - 1}; section {target_index} has {total} body paragraphs)")
        try:
            source = open_doc(source_path)
        except Exception:  # 열기 오류 문구에 경로가 들어 있을 수 있어 버린다
            raise ToolInputError("source_filename could not be opened as an HWPX document") from None
        try:
            if source_section_index is not None:
                _section(source, source_section_index, "source_section_index")
            before = _style_names(doc)
            options = {"target_section_index": target_index, "source_section_index": source_section_index}
            if at_front:
                report = document_merge.insert_document(doc, source, after_paragraph_index=after_paragraph_index, **options)
            else:
                report = document_merge.append_document(doc, source, **options)
        finally:
            source.close()
        _renumber_and_check(doc)
        after = _style_names(doc)
        twice = sorted(name for name, count in after.items() if count > 1 and count > before.get(name, 0))
        warnings = [f"style name(s) {twice[:10]} now exist twice (inserted styles are copied under new ids); delete or reuse one of each pair"] if twice else []
        return {**report, "firstParagraphIndex": after_paragraph_index + 1 if at_front else total, "targetSectionIndex": target_index, "warnings": warnings}

    return _commit(filename, expected_revision, dry_run, apply)
