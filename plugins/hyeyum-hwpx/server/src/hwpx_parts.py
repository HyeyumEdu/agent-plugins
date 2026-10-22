"""문서 부분 쓰기 도구: 머리말/꼬리말 지우기(remove_header_footer_ext)와 작성자·제목 같은 메타데이터와 미리보기 지우기(sanitize_document_ext).

쓰기 절차는 hwpx_common._commit. hwpx_edit는 가져오지 않는다(순환 import 방지).
"""
from dataclasses import fields
from typing import Any

from hwpx_common import ToolInputError, _commit, _section
from hwpx_locate import _header_footer_boxes

_PAGE_TYPES = ("BOTH", "EVEN", "ODD")
_PREVIEW_TEXT = "Preview/PrvText.txt"


def remove_header_footer_ext(
    filename: str,
    kind: str = "both",
    page_type: str = "all",
    section_index: int | None = None,
    dry_run: bool = False,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Delete the page header and/or footer of a document (Hancom's 머리말/꼬리말 지우기). To change their text use set_header_footer or edit_paragraph_text_ext.
    kind: "header", "footer" or "both" (default). page_type: which one - "BOTH" (the same on all pages), "EVEN" (even pages), "ODD" (odd pages) or "all" (default: every one of the three).
    section_index: only this 0-based section; omit for every section. Nothing to delete is not an error: `removedHeaders`/`removedFooters` are then 0.
    A picture that only the header/footer used is dropped from the file too. Returns removedHeaders, removedFooters (how many header/footer objects were deleted), removedImages and `bySection`. dry_run=true saves nothing."""
    if kind not in ("header", "footer", "both"):
        raise ToolInputError(f"kind must be 'header', 'footer' or 'both', got {kind!r}")
    if page_type not in (*_PAGE_TYPES, "all"):
        raise ToolInputError(f"page_type must be one of {[*_PAGE_TYPES, 'all']}, got {page_type!r}")

    def apply(doc: Any) -> dict[str, Any]:
        indexes = range(len(doc.sections)) if section_index is None else [section_index]
        if section_index is not None:
            _section(doc, section_index)
        types = _PAGE_TYPES if page_type == "all" else (page_type,)
        removed = {"header": 0, "footer": 0}
        by_section = []
        for index in indexes:
            section = doc.sections[index]
            count = {"header": 0, "footer": 0}
            for part in ("header", "footer"):
                if kind not in (part, "both"):
                    continue
                before = len(_header_footer_boxes(section, part))
                for each in types:
                    (doc.page.remove_header if part == "header" else doc.page.remove_footer)(page_type=each, section_index=index)
                count[part] = before - len(_header_footer_boxes(section, part))
                removed[part] += count[part]
            by_section.append({"section": index, "removedHeaders": count["header"], "removedFooters": count["footer"]})
        images = len(doc.media.remove_unused_images()) if removed["header"] or removed["footer"] else 0  # a picture only the removed header held would stay behind unreferenced
        return {"removedHeaders": removed["header"], "removedFooters": removed["footer"], "removedImages": images, "bySection": by_section}

    return _commit(filename, expected_revision, dry_run, apply)


def sanitize_document_ext(filename: str, keep_preview: bool = False, dry_run: bool = False, expected_revision: str | None = None) -> dict[str, Any]:
    """Remove what a document carries about itself before it is shared, without touching the body text: the author, title, subject, keywords, description, last-saved-by and dates in the document properties, and the stored preview (the preview text, and the preview picture, which can show the first page).
    Names of the properties are kept as empty entries and the dates are set to 1970-01-01, so the file still opens normally; the language is kept.
    keep_preview=true leaves the preview picture (the preview text is always emptied). Running it twice is safe: the second time reports nothing removed.
    Returns `removedMetadata` (names of the properties that had content, never their values) and `removedPreview` (the preview parts that had content). dry_run=true saves nothing."""

    def apply(doc: Any) -> dict[str, Any]:
        def snapshot() -> dict[str, Any]:
            found = doc.parts.metadata
            return {} if found is None else {field.name: getattr(found, field.name) for field in fields(found) if field.name != "language"}

        before = snapshot()
        doc.parts.clear_document_metadata(keep=("language",))
        after = snapshot()
        package = doc.package
        previews = []
        if package.has_part(_PREVIEW_TEXT) and package.read(_PREVIEW_TEXT):
            previews.append(_PREVIEW_TEXT)
        if not keep_preview:
            before_image = {name: package.read(name) for name in package.part_names() if name.startswith("Preview/PrvImage")}
            doc.parts.clear_preview()  # also empties PrvText
            previews += [name for name, data in before_image.items() if package.read(name) != data]
        elif package.has_part(_PREVIEW_TEXT):
            package.write(_PREVIEW_TEXT, b"")
        removed_metadata = [name for name, value in before.items() if value and value != after.get(name)]
        return {"removedMetadata": removed_metadata, "removedPreview": previews, "keptPreviewPicture": keep_preview}

    return _commit(filename, expected_revision, dry_run, apply)
