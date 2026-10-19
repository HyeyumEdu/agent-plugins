"""hwpx_layout 읽기 확장: 글자 세기와 같은 미리보기, 문단 스타일·개체 요약, part="objects", overview의 구역 정의.
실행: venv/bin/python -m pytest toolkit/tests/test_hwpx_layout_objects.py"""
import sys
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.oxml.paragraph import HwpxOxmlParagraph
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_layout  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
BIG = 10**9
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


@pytest.fixture()
def objects_doc(tmp_path):
    doc = HwpxDocument.new()
    first = doc.paragraphs[0]
    first.add_run("앞글\t탭")
    first.add_equation("x^2 + y^2", base_unit=1000)
    first.add_run("뒤글")
    first.add_footnote("각주 글", run_attributes={})
    first.add_hyperlink("https://example.com", "링크")
    first.add_bookmark("북마크1")
    first.add_check_box(caption="체크", checked=True)
    second = doc.add_paragraph("두번째")
    doc.shapes.add_dutmal("본문", "위", paragraph=second)
    second.add_picture(doc.media.add_image(PNG, "png"), width=3000, height=3000)
    doc.notes.add_endnote("미주 글", paragraph=second)
    cell = doc.add_paragraph("").add_table(2, 2, width=20000, height=4000).cell(1, 0).paragraphs[0]
    cell.add_run("칸 ")
    cell.add_equation("a+b", base_unit=1000)
    path = tmp_path / "objects.hwpx"
    doc.save_to_path(path)
    return path


def objects(path, **kwargs):
    return hwpx_layout.read_layout(path, "objects", max_chars=BIG, **kwargs)["items"]


def test_objects_lists_body_and_cell_paragraph_objects_with_positions(objects_doc):
    items = objects(objects_doc)
    by_kind = {}
    for item in items:
        by_kind.setdefault(item["kind"], item)  # the first of each kind
    assert [item["kind"] for item in items if item.get("paragraph_index") == 0] == ["equation", "footnote", "hyperlink", "bookmark", "check_box"]
    assert by_kind["equation"]["at"] == 4 and by_kind["equation"]["script"] == "x^2 + y^2" and by_kind["equation"]["base_unit"] == 1000  # "앞글", tab, "탭" = 4 characters
    assert by_kind["equation"]["treat_as_char"] is True and by_kind["equation"]["width"] > 0
    assert by_kind["hyperlink"]["url"] == "https://example.com" and by_kind["hyperlink"]["text"] == "링크" and by_kind["hyperlink"]["at"] == 6
    assert by_kind["bookmark"]["name"] == "북마크1" and by_kind["footnote"]["text"] == "각주 글" and by_kind["footnote"]["number"] == 1
    assert by_kind["check_box"]["caption"] == "체크" and by_kind["check_box"]["checked"] is True
    assert by_kind["ruby"]["base"] == "본문" and by_kind["picture"]["binary_id"] == "BIN0001" and by_kind["picture"]["paragraph_index"] == 1
    assert by_kind["endnote"]["text"] == "미주 글" and by_kind["table"] == {"kind": "table", "paragraph_index": 2, "at": 0, "table_index": 0, "rows": 2, "cols": 2}
    in_cell = [item for item in items if item["kind"] == "equation" and "table_index" in item]
    assert in_cell == [{**in_cell[0], "table_index": 0, "row": 1, "col": 0, "cell_paragraph_index": 0, "at": 2, "script": "a+b"}]
    assert not any(item["kind"] == "auto_number" and item.get("number_type") == "ENDNOTE" for item in items)  # a note's own number mark is not listed


def test_objects_inside_notes_are_listed_with_the_note_number(objects_doc):
    doc = HwpxDocument.open(objects_doc)
    note = doc.notes.add_endnote("그림이 든 미주", paragraph=doc.paragraphs[2])
    note.body_paragraph.add_equation("n+1", base_unit=1000)
    doc.save_to_path(objects_doc)
    inner = [item for item in objects(objects_doc) if item["kind"] == "equation" and "endnote_number" in item]
    assert len(inner) == 1 and inner[0]["endnote_number"] == 2 and inner[0]["endnote_paragraph_index"] == 0 and inner[0]["script"] == "n+1"


def test_text_box_objects_borrow_the_host_paragraph(tmp_path):
    doc = HwpxDocument.new()
    host = doc.add_paragraph("상자 있는 문단")
    doc.shapes.add_rectangle(paragraph=host).set_draw_text("상자 글")
    section = doc.sections[0]
    inner = next(section.element.iter(f"{HP}drawText")).find(f"{HP}subList").find(f"{HP}p")
    HwpxOxmlParagraph(inner, section).add_equation("k+1", base_unit=1000)
    path = tmp_path / "box.hwpx"
    doc.save_to_path(path)
    shape, equation = objects(path)
    assert shape["kind"] == "shape" and shape["name"] == "rect" and shape["text"] == "상자 글" and shape["paragraph_index"] == 1 and shape["at"] == 8
    assert equation["kind"] == "equation" and equation["in_shape"] is True and equation["paragraph_index"] == 1 and equation["at"] == 4  # at counts inside the box paragraph


def test_hyperlink_url_falls_back_to_the_command_parameter(objects_doc):
    doc = HwpxDocument.open(objects_doc)
    for param in doc.sections[0].element.iter(f"{HP}stringParam"):
        if param.get("name") == "Path":
            param.getparent().remove(param)
    doc.sections[0].mark_dirty()
    doc.save_to_path(objects_doc)
    assert next(item for item in objects(objects_doc) if item["kind"] == "hyperlink")["url"] == "https://example.com"


def test_objects_pages_by_offset_and_limit(objects_doc):
    everything = objects(objects_doc)
    first = hwpx_layout.read_layout(objects_doc, "objects", limit=3)
    assert first["part"] == "objects" and first["returned"] == 3 and first["nextOffset"] == 3 and first["total"] == len(everything)
    rest = hwpx_layout.read_layout(objects_doc, "objects", offset=3, max_chars=BIG)
    assert first["items"] + rest["items"] == everything and rest["nextOffset"] is None
    assert hwpx_layout.read_layout(objects_doc)["counts"]["objects"] == len(everything)


def test_body_items_carry_style_name_and_object_summary(objects_doc):
    body = hwpx_layout.read_layout(objects_doc, "body", max_chars=BIG)["items"]
    assert [item["kind"] for item in body[0]["objects"]] == ["equation", "footnote", "hyperlink", "bookmark", "check_box"]
    assert body[0]["objects"][0]["at"] == 4 and "paragraph_index" not in body[0]["objects"][0]
    assert body[2]["objects"][0]["kind"] == "table" and body[2]["tables"] == 1
    styles = {item["id"]: item["name"] for item in hwpx_layout.read_layout(objects_doc, "header", kind="style", max_chars=BIG)["items"]}
    assert body[0]["style"] == styles["0"]


def test_preview_text_counts_characters_like_the_edit_tools(tmp_path):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("가나다")
    t = paragraph.element.find(f"{HP}run/{HP}t")
    t.text = "가"
    for name, tail in (("tab", "나"), ("lineBreak", "다"), ("nbSpace", "라"), ("fwSpace", "마"), ("hyphen", "바")):
        etree.SubElement(t, f"{HP}{name}").tail = tail
    paragraph.section.mark_dirty()
    path = tmp_path / "special.hwpx"
    doc.save_to_path(path)
    reopened = HwpxDocument.open(path).paragraphs[1]
    item = hwpx_layout.read_layout(path, "body", max_chars=BIG)["items"][1]
    assert item["text"] == "가⇥나↵다 라　마­バ".replace("バ", "바")
    assert len(item["text"]) == sum(len(run.text or "") for run in reopened.runs)  # the length the edit tools count
    assert hwpx_layout.read_layout(path, "body", text_chars=3, max_chars=BIG)["items"][1]["text"] == "가⇥나"
    assert hwpx_layout.read_layout(path)["special_chars"] == {"tab": 1, "lineBreak": 1, "nbSpace": 1, "fwSpace": 1, "hyphen": 1}


def test_preview_keeps_spaces_and_leaves_out_text_of_notes_and_cells(objects_doc):
    body = hwpx_layout.read_layout(objects_doc, "body", max_chars=BIG)["items"]
    assert body[1]["text"] == "두번째" and body[2]["text"] == ""  # the endnote's and the table cell's text belong to their own parts


def test_overview_reports_section_definition(tmp_path):
    doc = HwpxDocument.new()
    doc.page.set_visibility(hide_first_header=True, show_line_number=True)
    doc.page.set_line_numbers(restart_type=1, count_by=5, distance=300, start_number=1)
    doc.page.set_grid(line_grid=1, char_grid=2, wonggoji_format=True)
    doc.sections[0].properties.set_start_numbering(page=3, picture=1, table=2, equation=4, page_starts_on="ODD")
    doc.parts.add_master_page(text="바탕쪽 글", page_type="BOTH", section=0)
    path = tmp_path / "overview.hwpx"
    doc.save_to_path(path)
    out = hwpx_layout.read_layout(path)
    assert out["line_numbers"] == {"restart_type": 1, "count_by": 5, "distance": 300, "start_number": 1, "show": 1}
    assert out["grid"] == {"line": 1, "char": 2, "wongoji": 1}  # the file says wonggojiFormat="true"; read as 1
    assert out["visibility"]["hide_first_header"] == 1 and out["visibility"]["hide_first_footer"] == 0 and out["visibility"]["border"] == "SHOW_ALL"
    assert out["start_numbering"] == {"page_starts_on": "ODD", "page": 3, "picture": 1, "table": 2, "equation": 4}
    assert out["master_pages"] == [{"id": "masterpage0", "type": "BOTH", "paragraphs": 1, "text": "바탕쪽 글"}]
    assert out["sections"] == [{"index": 0, "xml": "Contents/section0.xml", "body_paragraphs": 1, "tables": 0, "objects": 0, "endnotes": 0, "footnotes": 0, "landscape": "WIDELY", "columns": "1"}]


def test_second_section_numbers_tables_across_the_document(tmp_path):
    doc = HwpxDocument.new()
    doc.add_paragraph("").add_table(1, 1, width=10000, height=1000)
    doc.add_section()
    doc.add_paragraph("둘째 구역", section_index=1).add_table(1, 1, width=10000, height=1000)
    path = tmp_path / "two.hwpx"
    doc.save_to_path(path)
    second = hwpx_layout.read_layout(path, "tables", section=1)["items"]
    assert [table["index"] for table in second] == [1]  # numbered over the whole document, as format_table_ext does
    assert [item["table_index"] for item in objects(path, section=1) if item["kind"] == "table"] == [1]
    assert [s["index"] for s in hwpx_layout.read_layout(path)["sections"]] == [0, 1]


# eval/extract_spec.py 등 다른 스크립트가 읽는 기존 키: 확장은 키를 더하기만 한다
REQUIRED_KEYS = {
    "top": {"file", "header", "sections"},
    "header": {"borderFill", "charPr", "numbering", "paraPr", "style", "tabPr"},
    "section": {"body_paragraph_count", "body_paragraphs", "columns", "endNotePr", "endnotes", "footNotePr", "footer", "footnotes", "header", "page", "pageNum", "pictures", "tables"},
    "table": {"cells", "cols", "depth", "horzOffset", "horzRelTo", "inMargin", "outMargin", "pageBreak", "repeatHeader", "rows", "size", "tableBorders", "treatAsChar", "vertOffset"},
    "cell": {"borders", "c", "cs", "fill", "h", "hasMargin", "margin", "paragraphs", "r", "rs", "text", "vAlign", "w"},
    "paragraph": {"shape", "special_runs", "text"},
    "body": {"chars", "columnBreak", "endnotes", "i", "pageBreak", "paraPr", "pics", "special_runs", "tables", "text"},
    "page": {"bottom", "footer", "gutter", "header", "height", "landscape", "left", "right", "top", "width"},
}


def check_extract_keys(spec):
    assert REQUIRED_KEYS["top"] <= set(spec) and REQUIRED_KEYS["header"] <= set(spec["header"])
    for section in spec["sections"]:
        assert REQUIRED_KEYS["section"] <= set(section) and REQUIRED_KEYS["page"] <= set(section["page"])
        for table in section["tables"]:
            assert REQUIRED_KEYS["table"] <= set(table)
            for cell in table["cells"]:
                assert REQUIRED_KEYS["cell"] <= set(cell)
                assert all(REQUIRED_KEYS["paragraph"] <= set(p) for p in cell["paragraphs"])
        assert all(REQUIRED_KEYS["body"] <= set(p) for p in section["body_paragraphs"])
        assert all(REQUIRED_KEYS["paragraph"] <= set(p) for note in section["endnotes"] for p in note["paragraphs"])


def test_extract_keeps_every_existing_key(objects_doc):
    check_extract_keys(hwpx_layout.extract(objects_doc))
