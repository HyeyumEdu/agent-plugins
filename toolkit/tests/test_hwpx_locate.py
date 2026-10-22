"""hwpx_locate: 문단 주소(본문·표 칸·미주·각주·머리말/꼬리말)와 전체 순회. 실행: venv/bin/python -m pytest toolkit/tests/test_hwpx_locate.py"""
import sys
from pathlib import Path

import pytest
from hwpx import HwpxDocument

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_locate  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402


@pytest.fixture()
def doc(tmp_path):
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    first = doc.add_paragraph("문항 1")
    doc.notes.add_endnote("해설 1", paragraph=first)
    second = doc.add_paragraph("문항 2")
    doc.notes.add_endnote("해설 2", paragraph=second)
    second.add_footnote("각주 2")
    holder = doc.add_paragraph("")
    table = holder.add_table(2, 2, width=20000, height=4000)
    table.set_cell_text(0, 1, "칸 글")
    doc.page.set_header(text="머리말 글")
    doc.page.set_footer(text="꼬리말 글")
    doc.save_to_path(tmp_path / "doc.hwpx")
    return HwpxDocument.open(tmp_path / "doc.hwpx")


def text_of(paragraph):
    return hwpx_locate.paragraph_text(paragraph)


def test_body(doc):
    assert text_of(hwpx_locate.resolve_paragraph(doc, paragraph_index=1)) == "문항 1"
    assert text_of(hwpx_locate.resolve_paragraph(doc, section_index=0, paragraph_index=2)) == "문항 2"


def test_cell(doc):
    assert text_of(hwpx_locate.resolve_paragraph(doc, table_index=0, row=0, col=1)) == "칸 글"
    assert text_of(hwpx_locate.resolve_paragraph(doc, table_index=0, row=0, col=1, cell_paragraph_index=0)) == "칸 글"


def test_notes_follow_document_order(doc):
    assert text_of(hwpx_locate.resolve_paragraph(doc, endnote_number=1)) == "해설 1"
    assert text_of(hwpx_locate.resolve_paragraph(doc, endnote_number=2)) == "해설 2"
    assert text_of(hwpx_locate.resolve_paragraph(doc, footnote_number=1)) == "각주 2"


def test_header_and_footer(doc):
    assert "머리말 글" in text_of(hwpx_locate.resolve_paragraph(doc, header_index=0))
    assert "꼬리말 글" in text_of(hwpx_locate.resolve_paragraph(doc, footer_index=0))


def test_wrapper_edits_mark_the_section_dirty(doc):
    paragraph = hwpx_locate.resolve_paragraph(doc, endnote_number=2)
    doc.sections[0].reset_dirty()
    paragraph.section.mark_dirty()
    assert doc.sections[0].dirty


@pytest.mark.parametrize("address, message", [
    ({}, "give exactly one"),
    ({"paragraph_index": 0, "table_index": 0, "row": 0, "col": 0}, "give exactly one"),
    ({"paragraph_index": 99}, "invalid paragraph_index"),
    ({"paragraph_index": -1}, "invalid paragraph_index"),
    ({"table_index": 0}, "needs row and col"),
    ({"table_index": 5, "row": 0, "col": 0}, "invalid table_index"),
    ({"table_index": 0, "row": 9, "col": 9}, "no cell at"),
    ({"table_index": 0, "row": 0, "col": 0, "cell_paragraph_index": 3}, "invalid cell_paragraph_index"),
    ({"endnote_number": 0}, "invalid endnote_number"),
    ({"endnote_number": 3}, "invalid endnote_number"),
    ({"endnote_number": 1, "endnote_paragraph_index": 4}, "invalid endnote_paragraph_index"),
    ({"footnote_number": 2}, "invalid footnote_number"),
    ({"header_index": 1}, "invalid header_index"),
    ({"paragraph_index": 0, "row": 1}, "do not go with"),
    ({"paragraph_index": 0, "endnote_paragraph_index": 0}, "do not go with"),
    ({"endnote_paragraph_index": 0}, "give exactly one"),
    ({"bogus": 1}, "unknown address argument"),
])
def test_refusals(doc, address, message):
    with pytest.raises(ToolInputError, match=message):
        hwpx_locate.resolve_paragraph(doc, **address)


def test_section_index_out_of_range(doc):
    with pytest.raises(ToolInputError, match="invalid section_index"):
        hwpx_locate.resolve_paragraph(doc, section_index=4, paragraph_index=0)


def test_iter_paragraphs_gives_addresses_that_resolve_back(doc):
    seen = list(hwpx_locate.iter_paragraphs(doc))
    assert seen
    for address, paragraph in seen:
        assert hwpx_locate.resolve_paragraph(doc, **address).element is paragraph.element
    texts = {text_of(paragraph) for _, paragraph in seen}
    assert {"문항 1", "해설 1", "해설 2", "각주 2", "칸 글"} <= texts
    assert any("머리말 글" in text for text in texts) and any("꼬리말 글" in text for text in texts)


def test_iter_paragraphs_scopes(doc):
    only_notes = [address for address, _ in hwpx_locate.iter_paragraphs(doc, ["endnotes"])]
    assert only_notes == [{"endnote_number": 1, "endnote_paragraph_index": 0}, {"endnote_number": 2, "endnote_paragraph_index": 0}]
    with pytest.raises(ToolInputError, match="unknown scope"):
        list(hwpx_locate.iter_paragraphs(doc, ["bogus"]))


def test_next_paragraph_and_holders(doc):
    first = hwpx_locate.resolve_paragraph(doc, paragraph_index=1)
    following = hwpx_locate.next_paragraph(first)
    assert following is not None and text_of(type(first)(following, first.section)) == "문항 2"
    last = hwpx_locate.resolve_paragraph(doc, paragraph_index=len(doc.paragraphs) - 1)
    assert hwpx_locate.next_paragraph(last) is None
    assert hwpx_locate.holds_section_definition(hwpx_locate.resolve_paragraph(doc, paragraph_index=0))
    assert hwpx_locate.holds_table(hwpx_locate.resolve_paragraph(doc, paragraph_index=3))
    assert not hwpx_locate.holds_table(first)


def test_addressed_fills_the_placeholder():
    @hwpx_locate.addressed
    def tool():
        """Edit a paragraph. {ADDRESS} Done."""

    assert "{ADDRESS}" not in tool.__doc__ and "paragraph_index" in tool.__doc__ and tool.__doc__.endswith("Done.")


def test_table_numbers_match_the_reader_even_when_a_header_holds_a_table(tmp_path):
    import hwpx_layout
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    doc.page.set_header(text="머리말")
    hwpx_locate.resolve_paragraph(doc, header_index=0).add_table(1, 3, width=9000, height=1000)  # a table inside the header
    doc.add_paragraph("").add_table(2, 2, width=9000, height=2000)
    doc.add_paragraph("").add_table(4, 1, width=9000, height=4000)
    doc.save_to_path(tmp_path / "doc.hwpx")
    doc = HwpxDocument.open(tmp_path / "doc.hwpx")
    items = hwpx_layout.read_layout(tmp_path / "doc.hwpx", "tables", max_chars=10**9)["items"]
    assert len(items) == len(hwpx_locate.all_tables(doc)) >= 3
    for item in items:
        table = hwpx_locate.table_at(doc, item["index"])
        assert (table.row_count, table.column_count) == (item["rows"], item["cols"]), item["index"]
    assert [hwpx_locate.table_indexes(doc, [hwpx_locate.table_at(doc, i).element])[0] for i in range(len(items))] == list(range(len(items)))


def test_a_second_section_keeps_its_own_section_for_notes_and_saves(tmp_path):
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("구역 0")
    doc.add_section()
    host = doc.sections[1].add_paragraph("구역 1 문항")
    doc.notes.add_endnote("구역 1 해설", paragraph=host)
    doc.save_to_path(tmp_path / "doc.hwpx")
    doc = HwpxDocument.open(tmp_path / "doc.hwpx")
    assert len(doc.sections) == 2
    paragraph = hwpx_locate.resolve_paragraph(doc, endnote_number=1)
    assert paragraph.section.element is doc.sections[1].element  # the wrapper belongs to the section that holds the note
    assert hwpx_locate.resolve_paragraph(doc, section_index=1, endnote_number=1).element is paragraph.element
    paragraph.runs[-1].text = "고친 해설"
    paragraph.section.mark_dirty()
    doc.save_to_path(tmp_path / "out.hwpx")
    assert hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(HwpxDocument.open(tmp_path / "out.hwpx"), endnote_number=1)).endswith("고친 해설")
    with pytest.raises(ToolInputError, match="invalid endnote_number"):
        hwpx_locate.resolve_paragraph(doc, section_index=0, endnote_number=1)  # section 0 has no endnote
