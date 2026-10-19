"""hwpx_docops: copy_paragraphs_ext, insert_document_ext. 실행: venv/bin/python -m pytest toolkit/tests/test_hwpx_docops.py"""
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_docops  # noqa: E402
import hwpx_layout  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(root)]))
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    first = doc.add_paragraph("문항 1")
    doc.notes.add_endnote("해설 1", paragraph=first)
    holder = doc.add_paragraph("")
    holder.add_table(2, 2, width=20000, height=4000).set_cell_text(0, 0, "칸")
    last = doc.add_paragraph("끝")
    doc.notes.add_endnote("해설 끝", paragraph=last)
    doc.save_to_path(root / "doc.hwpx")
    return root


def section_xml(ws: Path, name: str = "doc.hwpx") -> str:
    return zipfile.ZipFile(ws / name).read("Contents/section0.xml").decode()


def texts(ws: Path, name: str = "doc.hwpx") -> list[str]:
    return re.findall(r"<hp:t>([^<]*)</hp:t>", section_xml(ws, name))


def body(ws: Path, name: str = "doc.hwpx") -> list[dict]:
    return hwpx_layout.read_layout(ws / name, "body", max_chars=10**9)["items"]


def note_numbers(xml: str) -> tuple[list[str], list[str]]:
    return re.findall(r'<hp:endNote number="(\d+)"', xml), re.findall(r'<hp:autoNum num="(\d+)" numType="ENDNOTE"', xml)


def test_copy_inserts_a_closed_range_and_renumbers_endnotes_in_document_order(ws):
    result = hwpx_docops.copy_paragraphs_ext("doc.hwpx", 1, 2, before_index=3)
    assert result["copied"] == 2 and result["firstNewParagraphIndex"] == 3 and result["warnings"] == []
    assert texts(ws) == ["머리", "문항 1", "해설 1", "칸", "문항 1", "해설 1", "칸", "끝", "해설 끝"]
    assert note_numbers(section_xml(ws)) == (["1", "2", "3"], ["1", "2", "3"])  # the copy's note is number 2, the last one moved to 3
    assert hwpx_layout.read_layout(ws / "doc.hwpx")["counts"]["tables"] == 2
    ids = re.findall(r'<hp:p id="(\d+)"', section_xml(ws))
    assert len(ids) == len(set(ids)) == 6


def test_copy_without_before_index_appends_to_the_section_end(ws):
    hwpx_docops.copy_paragraphs_ext("doc.hwpx", 3, 3)
    assert texts(ws)[-4:] == ["끝", "해설 끝", "끝", "해설 끝"]
    assert [item["text"] for item in body(ws)] == ["머리", "문항 1", "", "끝", "끝"]
    assert note_numbers(section_xml(ws))[0] == ["1", "2", "3"]


def test_copy_before_a_paragraph_inside_the_range(ws):
    hwpx_docops.copy_paragraphs_ext("doc.hwpx", 1, 3, before_index=2)
    assert [item["text"] for item in body(ws)] == ["머리", "문항 1", "문항 1", "", "끝", "", "끝"]
    assert note_numbers(section_xml(ws))[0] == ["1", "2", "3", "4"] and texts(ws)[:4] == ["머리", "문항 1", "해설 1", "문항 1"]


def test_copy_errors_name_the_argument_and_leave_the_file_alone(ws):
    before = (ws / "doc.hwpx").read_bytes()
    for kwargs, match in (
        (dict(start_index=2, end_index=1), "end_index 1"),
        (dict(start_index=-1, end_index=1), "start_index -1"),
        (dict(start_index=1, end_index=4), "end_index 4"),
        (dict(start_index=1, end_index=2, before_index=5), "before_index 5"),
        (dict(start_index=1, end_index=2, before_index=-1), "before_index -1"),
        (dict(start_index=0, end_index=1), "section definition"),
        (dict(start_index=1, end_index=2, before_index=0), "section definition"),
        (dict(start_index=1, end_index=2, section_index=1), "section_index 1"),
    ):
        with pytest.raises(ToolInputError, match=match):
            hwpx_docops.copy_paragraphs_ext("doc.hwpx", **kwargs)
    assert (ws / "doc.hwpx").read_bytes() == before


def test_copy_dry_run_changes_nothing_and_revision_is_checked(ws):
    before = (ws / "doc.hwpx").read_bytes()
    result = hwpx_docops.copy_paragraphs_ext("doc.hwpx", 1, 2, dry_run=True)
    assert result["dryRun"] is True and result["copied"] == 2
    assert (ws / "doc.hwpx").read_bytes() == before
    with pytest.raises(ToolInputError, match="revision"):
        hwpx_docops.copy_paragraphs_ext("doc.hwpx", 1, 2, expected_revision="sha256:0")
    ok = hwpx_docops.copy_paragraphs_ext("doc.hwpx", 1, 1, expected_revision=result["document_revision"])
    assert ok["copied"] == 1


def test_copy_warns_about_repeated_bookmarks_and_fields(ws):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    doc.paragraphs[1].add_bookmark("문항표시")
    doc.paragraphs[1].add_hyperlink("https://example.com", "링크")
    doc.save_to_path(ws / "doc.hwpx")
    warnings = hwpx_docops.copy_paragraphs_ext("doc.hwpx", 1, 1)["warnings"]
    assert any("문항표시" in w for w in warnings) and any("field" in w for w in warnings)


@pytest.fixture()
def source(ws):
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("원본 머리")
    note_host = doc.add_paragraph("원본 문단")
    doc.notes.add_endnote("원본 해설", paragraph=note_host)
    doc.add_paragraph("원본 끝")
    doc.save_to_path(ws / "src.hwpx")
    return ws / "src.hwpx"


def test_insert_document_after_a_paragraph_and_renumbers_notes(ws, source):
    result = hwpx_docops.insert_document_ext("doc.hwpx", "src.hwpx", after_paragraph_index=1)
    assert result["paragraphsInserted"] == 3 and result["firstParagraphIndex"] == 2 and result["targetSectionIndex"] == 0
    assert [item["text"] for item in body(ws)] == ["머리", "문항 1", "원본 머리", "원본 문단", "원본 끝", "", "끝"]
    assert texts(ws).index("원본 해설") > texts(ws).index("해설 1")  # note text follows document order ...
    assert note_numbers(section_xml(ws)) == (["1", "2", "3"], ["1", "2", "3"])  # ... and so do the numbers
    assert section_xml(ws).count("<hp:secPr") == 1
    assert (ws / "src.hwpx").read_bytes() == source.read_bytes()


def test_insert_document_without_a_position_appends_and_at_minus_one_goes_first(ws, source):
    hwpx_docops.insert_document_ext("doc.hwpx", "src.hwpx")
    assert [item["text"] for item in body(ws)][-3:] == ["원본 머리", "원본 문단", "원본 끝"]
    hwpx_docops.insert_document_ext("doc.hwpx", "src.hwpx", after_paragraph_index=-1, source_section_index=0)
    items = body(ws)
    assert [item["text"] for item in items][:3] == ["원본 머리", "원본 문단", "원본 끝"]
    xml = section_xml(ws)
    assert xml.count("<hp:secPr") == 1 and xml.index("<hp:secPr") < xml.index("원본 머리")  # the section definition stayed in the first paragraph
    assert note_numbers(xml)[0] == ["1", "2", "3", "4"]


def test_insert_document_warns_about_duplicated_style_names(ws, source):
    result = hwpx_docops.insert_document_ext("doc.hwpx", "src.hwpx", after_paragraph_index=0)
    assert result["remapped"]["style"] >= 1 and result["warnings"] and "exist twice" in result["warnings"][0]


def test_insert_document_dry_run_and_index_errors(ws, source):
    before = (ws / "doc.hwpx").read_bytes()
    result = hwpx_docops.insert_document_ext("doc.hwpx", "src.hwpx", after_paragraph_index=1, dry_run=True)
    assert result["dryRun"] is True and result["paragraphsInserted"] == 3
    for kwargs, match in (
        (dict(after_paragraph_index=4), "after_paragraph_index 4"),
        (dict(after_paragraph_index=-2), "after_paragraph_index -2"),
        (dict(after_paragraph_index=0, target_section_index=1), "target_section_index 1"),
        (dict(after_paragraph_index=0, target_section_index=-1), "target_section_index -1"),
        (dict(after_paragraph_index=0, source_section_index=3), "source_section_index 3"),
    ):
        with pytest.raises(ToolInputError, match=match):
            hwpx_docops.insert_document_ext("doc.hwpx", "src.hwpx", **kwargs)
    assert (ws / "doc.hwpx").read_bytes() == before


def test_insert_document_refuses_sources_outside_the_workspace_without_naming_paths(ws, source, tmp_path):
    outside = tmp_path / "outside.hwpx"
    outside.write_bytes(source.read_bytes())
    (ws / "escape.hwpx").symlink_to(outside)
    (ws / "folder").mkdir()
    (ws / "notes.txt").write_text("not a document")
    cases = {str(outside): "not allowed", "../outside.hwpx": "not allowed", "escape.hwpx": "not allowed",
             "missing.hwpx": "does not exist", "folder": "not a file", "notes.txt": "could not be opened"}
    for name, match in cases.items():
        with pytest.raises(ToolInputError, match=match) as raised:
            hwpx_docops.insert_document_ext("doc.hwpx", name)
        assert str(tmp_path) not in str(raised.value) and "outside.hwpx" not in str(raised.value)


def test_insert_document_can_take_a_second_look_at_itself(ws):
    hwpx_docops.insert_document_ext("doc.hwpx", "doc.hwpx", after_paragraph_index=3)
    assert [item["text"] for item in body(ws)][4:8] == ["머리", "문항 1", "", "끝"]
    assert note_numbers(section_xml(ws))[0] == ["1", "2", "3", "4"]
