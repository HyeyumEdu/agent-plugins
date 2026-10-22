"""hwpx_parts: remove_header_footer_ext, sanitize_document_ext. 실행: venv/bin/python -m pytest toolkit/tests/test_hwpx_parts.py"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.tools.id_integrity import check_id_integrity
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_locate  # noqa: E402
import hwpx_parts  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00\xfd\xd4\x9a\x73\x00\x00\x00\x0cIDATx\x9cc`\x00\x02\x00\x00\x05\x00\x01\x0d\x0a\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("본문 첫 문단")
    doc.add_paragraph("둘째 문단")
    doc.page.set_header(text="전체 머리말")
    doc.page.set_header(text="짝수쪽 머리말", page_type="EVEN")
    doc.page.set_footer(text="꼬리말")
    doc.parts.set_document_metadata(title="비밀 제목", creator="홍길동", subject="주제어", keyword="열쇠")
    doc.package.write("Preview/PrvText.txt", "본문 첫 문단 미리보기")
    doc.package.write("Preview/PrvImage.png", PNG)
    doc.save_to_path(tmp_path / "doc.hwpx")
    return tmp_path


def sha(ws: Path) -> str:
    return hashlib.sha256((ws / "doc.hwpx").read_bytes()).hexdigest()


def reopened(ws: Path) -> HwpxDocument:
    doc = HwpxDocument.open(ws / "doc.hwpx")
    assert check_id_integrity(doc).ok
    return doc


def kinds(ws: Path) -> dict[str, int]:
    doc = reopened(ws)
    section = doc.sections[0]
    return {part: len(hwpx_locate._header_footer_boxes(section, part)) for part in ("header", "footer")}


def test_remove_both_everywhere(ws):
    assert kinds(ws) == {"header": 2, "footer": 1}
    result = hwpx_parts.remove_header_footer_ext("doc.hwpx")
    assert (result["removedHeaders"], result["removedFooters"]) == (2, 1)
    assert kinds(ws) == {"header": 0, "footer": 0}
    assert [p.text for p in reopened(ws).paragraphs if p.text] == ["본문 첫 문단", "둘째 문단"]  # the body is untouched


def test_remove_only_one_kind_or_page_type(ws):
    result = hwpx_parts.remove_header_footer_ext("doc.hwpx", kind="header", page_type="EVEN")
    assert (result["removedHeaders"], result["removedFooters"]) == (1, 0)
    assert kinds(ws) == {"header": 1, "footer": 1}
    hwpx_parts.remove_header_footer_ext("doc.hwpx", kind="footer", page_type="BOTH")
    assert kinds(ws) == {"header": 1, "footer": 0}


def test_nothing_to_remove_is_not_an_error(ws):
    hwpx_parts.remove_header_footer_ext("doc.hwpx")
    again = hwpx_parts.remove_header_footer_ext("doc.hwpx")
    assert (again["removedHeaders"], again["removedFooters"]) == (0, 0)


def test_remove_by_section_and_refusals(ws):
    assert hwpx_parts.remove_header_footer_ext("doc.hwpx", section_index=0)["bySection"][0]["removedHeaders"] == 2
    for arguments, message in (({"kind": "top"}, "kind must be"), ({"page_type": "LEFT"}, "page_type must be"), ({"section_index": 3}, "invalid section_index")):
        with pytest.raises(ToolInputError, match=message):
            hwpx_parts.remove_header_footer_ext("doc.hwpx", **arguments)


def test_remove_dry_run_and_revision_guard_leave_the_file_alone(ws):
    before = sha(ws)
    assert hwpx_parts.remove_header_footer_ext("doc.hwpx", dry_run=True)["removedHeaders"] == 2
    assert sha(ws) == before
    with pytest.raises(ToolInputError, match="revision mismatch"):
        hwpx_parts.remove_header_footer_ext("doc.hwpx", expected_revision="sha256:" + "0" * 64)
    assert sha(ws) == before


def test_sanitize_clears_properties_and_preview_but_not_the_body(ws):
    result = hwpx_parts.sanitize_document_ext("doc.hwpx")
    assert {"title", "creator", "subject", "keyword"} <= set(result["removedMetadata"])
    assert "Preview/PrvText.txt" in result["removedPreview"] and "Preview/PrvImage.png" in result["removedPreview"]
    assert "홍길동" not in json.dumps(result, ensure_ascii=False) and "비밀 제목" not in json.dumps(result, ensure_ascii=False)  # names only, never values
    doc = reopened(ws)
    meta = doc.parts.metadata
    assert not meta.title and not meta.creator and not meta.subject and not meta.keyword and meta.language
    package = zipfile.ZipFile(ws / "doc.hwpx")
    assert package.read("Preview/PrvText.txt") == b"" and package.read("Preview/PrvImage.png") != PNG
    assert [p.text for p in doc.paragraphs if p.text] == ["본문 첫 문단", "둘째 문단"]


def test_sanitize_twice_reports_nothing_the_second_time(ws):
    hwpx_parts.sanitize_document_ext("doc.hwpx")
    again = hwpx_parts.sanitize_document_ext("doc.hwpx")
    assert again["removedMetadata"] == [] and again["removedPreview"] == []


def test_sanitize_keep_preview_leaves_the_picture(ws):
    result = hwpx_parts.sanitize_document_ext("doc.hwpx", keep_preview=True)
    assert result["removedPreview"] == ["Preview/PrvText.txt"] and result["keptPreviewPicture"] is True
    package = zipfile.ZipFile(ws / "doc.hwpx")
    assert package.read("Preview/PrvImage.png") == PNG and package.read("Preview/PrvText.txt") == b""


def test_sanitize_dry_run_saves_nothing(ws):
    before = sha(ws)
    assert hwpx_parts.sanitize_document_ext("doc.hwpx", dry_run=True)["removedMetadata"]
    assert sha(ws) == before
