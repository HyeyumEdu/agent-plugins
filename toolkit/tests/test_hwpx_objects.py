"""hwpx_objects: delete_inline_object_ext, update_inline_object_ext (문단 안 개체 지우기·고치기). 실행(패키지된 환경 그대로):
venv/bin/python -m pytest toolkit/tests/test_hwpx_objects.py"""
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.equation.measure import measure_equation
from hwpx.oxml.hyperlink_form import hyperlink_parameters
from hwpx.tools.id_integrity import check_id_integrity
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_inline  # noqa: E402
import hwpx_layout  # noqa: E402
import hwpx_locate  # noqa: E402
import hwpx_objects  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
UNIT = 7200 / 25.4
DELETE = hwpx_objects.delete_inline_object_ext
UPDATE = hwpx_objects.update_inline_object_ext


def png(width: int, height: int, red: int = 255) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    rows = b"".join(b"\x00" + bytes([red, 0, 0]) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    return tmp_path


def sha(ws: Path) -> str:
    return hashlib.sha256((ws / "doc.hwpx").read_bytes()).hexdigest()


def save(ws: Path, doc) -> None:
    doc.save_to_path(ws / "doc.hwpx")


def reopen(ws: Path):
    return HwpxDocument.open(ws / "doc.hwpx")


def section_xml(ws: Path, index: int = 0) -> etree._Element:
    return etree.fromstring(zipfile.ZipFile(ws / "doc.hwpx").read(f"Contents/section{index}.xml"))


def bin_items(ws: Path) -> list[str]:
    return sorted(n for n in zipfile.ZipFile(ws / "doc.hwpx").namelist() if n.startswith("BinData/"))


def objects(ws: Path, section: int = 0, **where) -> list[dict]:
    """The part="objects" items of hwpx_read_layout whose place has the given values."""
    items = hwpx_layout.read_layout(ws / "doc.hwpx", "objects", section=section, max_chars=10**9)["items"]
    return [item for item in items if all(item.get(key) == value for key, value in where.items())]


def assert_clean(ws: Path) -> None:
    doc = reopen(ws)
    assert check_id_integrity(doc).ok


def new_picture(doc, paragraph, data: bytes | None = None, width: int = 10000, height: int = 4000, item: str | None = None):
    """A picture of its own image, or of the binary item *item* (what another picture already uses)."""
    return paragraph.add_picture(item or str(doc.media.add_image(data or png(8, 4), "png")), width=width, height=height, treat_as_char=True)


#: how each kind is put into a paragraph (doc, paragraph)
ADD = {
    "equation": lambda doc, p: p.add_equation("a over b"),
    "picture": lambda doc, p: new_picture(doc, p),
    "bookmark": lambda doc, p: p.add_bookmark("책갈피"),
    "hyperlink": lambda doc, p: p.add_hyperlink("https://a.example", "링크"),
    "ruby": lambda doc, p: p.add_dutmal("漢", "한"),
    "composed": lambda doc, p: p.add_composed_character("가"),
    "check_box": lambda doc, p: p.add_check_box("보기"),
    "shape": lambda doc, p: p.add_rectangle(3000, 2000),
    "field": lambda doc, p: p.add_date_field("2026년 10월 20일"),
    "footnote": lambda doc, p: p.add_footnote("각주 글"),
    "endnote": lambda doc, p: doc.notes.add_endnote("해설 글", paragraph=p),
}


def in_body(doc):
    paragraph = doc.add_paragraph("앞 뒤")
    return paragraph, {"paragraph_index": len(doc.paragraphs) - 1}


def in_cell(doc):
    table = doc.add_paragraph("").add_table(2, 2, width=20000, height=4000)
    table.set_cell_text(1, 0, "칸 글")
    return table.cell(1, 0).paragraphs[0], {"table_index": 0, "row": 1, "col": 0}


def in_endnote(doc):
    doc.notes.add_endnote("해설", paragraph=doc.add_paragraph("본문"))
    return hwpx_locate.resolve_paragraph(doc, endnote_number=1), {"endnote_number": 1}


def in_header(doc):
    doc.paragraphs[0].add_run("본문")
    doc.page.set_header(text="머리말")
    return hwpx_locate.resolve_paragraph(doc, header_index=0), {"header_index": 0}


PLACES = {"body": in_body, "cell": in_cell, "endnote": in_endnote, "header": in_header}


def build(ws: Path, place, *adders):
    """doc.hwpx with the objects of *adders* in a paragraph of *place*; returns that paragraph's address."""
    doc = HwpxDocument.new()
    paragraph, address = place(doc)
    for adder in adders:
        adder(doc, paragraph)
    save(ws, doc)
    return address


# ---------------------------------------------------------------- delete: every kind, in every place

@pytest.mark.parametrize("place", PLACES)
@pytest.mark.parametrize("kind", ["equation", "picture", "bookmark", "hyperlink", "ruby", "composed", "check_box", "shape", "field", "footnote", "endnote"])
def test_delete_each_kind_in_each_place(ws, kind, place):
    if place == "endnote" and kind in ("footnote", "endnote"):
        pytest.skip("a note cannot hold a note")
    address = build(ws, PLACES[place], ADD[kind], ADD["equation"] if kind != "equation" else ADD["bookmark"])
    before = objects(ws, **address)
    assert [item["kind"] for item in before].count(kind) == 1
    result = DELETE("doc.hwpx", kind, **address)
    assert result["deleted"]["kind"] == kind and result["remaining"] == 0 and result["warnings"] == []
    after = objects(ws, **address)
    assert [item["kind"] for item in after] == [item["kind"] for item in before if item["kind"] != kind]  # the others are still there, in order
    assert_clean(ws)
    assert not [ctrl for ctrl in section_xml(ws).iter(HP + "ctrl") if len(ctrl) == 0]  # the hp:ctrl around a deleted object goes with it
    if kind == "picture":
        assert bin_items(ws) == [] and result["removedImages"] == 1
    if kind == "shape":
        assert section_xml(ws).find(f".//{HP}rect") is None


def test_scan_walks_the_paragraph_as_the_layout_reader_does(ws):
    address = build(ws, in_body, ADD["equation"], ADD["hyperlink"], ADD["footnote"], ADD["equation"], ADD["bookmark"], ADD["check_box"], ADD["ruby"],
                    ADD["picture"], ADD["composed"], ADD["field"], ADD["shape"], ADD["endnote"])
    doc = reopen(ws)
    paragraph = hwpx_locate.resolve_paragraph(doc, **address)
    scanned = [found.summary for found in hwpx_objects._scan(paragraph.element)]
    listed = [{key: value for key, value in item.items() if key not in address and key != "cell_paragraph_index"} for item in objects(ws, **address)]
    assert scanned == listed and len(scanned) == 12
    assert [item["kind"] for item in scanned if item["kind"] == "equation"] == ["equation", "equation"]


# ---------------------------------------------------------------- delete: nth, order, neighbours

def test_nth_counts_per_kind_in_document_order(ws):
    address = build(ws, in_body, lambda d, p: p.add_equation("first"), ADD["bookmark"], lambda d, p: p.add_equation("second"), lambda d, p: p.add_equation("third"))
    result = DELETE("doc.hwpx", "equation", nth=2, **address)
    assert result["deleted"]["script"] == "second" and result["remaining"] == 2
    assert [item["script"] for item in objects(ws, **address) if item["kind"] == "equation"] == ["first", "third"]
    assert len(objects(ws, **address)) == 3
    before = sha(ws)
    for nth, message in [(3, "out of range: the paragraph has 2 equation"), (0, "nth must be"), (True, "nth must be")]:
        with pytest.raises(ToolInputError, match=message):
            DELETE("doc.hwpx", "equation", nth=nth, **address)
    with pytest.raises(ToolInputError, match="has no hyperlink object"):
        DELETE("doc.hwpx", "hyperlink", **address)
    assert sha(ws) == before


def test_text_tab_and_neighbours_stay_and_an_emptied_run_goes(ws):
    doc = HwpxDocument.new()
    doc.add_paragraph("가\t나다")
    save(ws, doc)
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "x"}, {"bookmark": "끝"}], position=2, paragraph_index=1)
    paragraph = section_xml(ws).findall(HP + "p")[1]
    runs_before = len(paragraph.findall(HP + "run"))
    DELETE("doc.hwpx", "equation", paragraph_index=1)
    paragraph = section_xml(ws).findall(HP + "p")[1]
    assert len(paragraph.findall(HP + "run")) == runs_before - 1  # the run that held only the equation is gone
    assert len(list(paragraph.iter(HP + "tab"))) == 1 and paragraph.find(f".//{HP}bookmark") is not None
    assert hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopen(ws), paragraph_index=1)) == "가\t나다"


def test_the_last_run_of_a_paragraph_is_kept_even_when_empty(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("")
    paragraph.add_equation("x")
    for run in paragraph.element.findall(HP + "run")[:-1]:
        paragraph.element.remove(run)
    save(ws, doc)
    assert len(section_xml(ws).findall(HP + "p")[1].findall(HP + "run")) == 1
    DELETE("doc.hwpx", "equation", paragraph_index=1)
    runs = section_xml(ws).findall(HP + "p")[1].findall(HP + "run")
    assert len(runs) == 1 and len(runs[0]) == 0


def test_the_layout_cache_of_a_changed_paragraph_is_dropped(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("가나")
    paragraph.add_equation("x")
    paragraph.element.append(paragraph.element.makeelement(HP + "linesegarray", {}))
    save(ws, doc)
    assert section_xml(ws).findall(HP + "p")[1].find(HP + "linesegarray") is not None
    DELETE("doc.hwpx", "equation", paragraph_index=1)
    assert section_xml(ws).findall(HP + "p")[1].find(HP + "linesegarray") is None


# ---------------------------------------------------------------- delete: notes, pictures

@pytest.mark.parametrize("kind, tag", [("endnote", "endNote"), ("footnote", "footNote")])
def test_deleting_a_note_renumbers_the_rest_in_document_order(ws, kind, tag):
    doc = HwpxDocument.new()
    for number in range(1, 4):
        host = doc.add_paragraph(f"문항 {number}")
        ADD[kind](doc, host)
        hwpx_locate.resolve_paragraph(doc, **{f"{kind}_number": number}).runs[-1].text = f"설명 {number}"
    save(ws, doc)
    result = DELETE("doc.hwpx", kind, paragraph_index=2)
    assert result["deleted"]["kind"] == kind and result["deleted"]["number"] == 2
    notes = list(section_xml(ws).iter(HP + tag))
    assert [n.get("number") for n in notes] == ["1", "2"]
    assert [a.get("num") for a in section_xml(ws).iter(HP + "autoNum") if a.get("numType") == kind.upper()] == ["1", "2"]
    assert [n.xpath("string()").strip()[-4:] for n in notes] == ["설명 1", "설명 3"]
    assert [item["number"] for item in objects(ws) if item["kind"] == kind] == [1, 2]
    assert_clean(ws)


def test_deleting_a_picture_drops_the_image_only_when_nothing_else_uses_it(ws):
    doc = HwpxDocument.new()
    first, second, third = doc.add_paragraph("a"), doc.add_paragraph("b"), doc.add_paragraph("c")
    shared = str(doc.media.add_image(png(8, 4), "png"))
    new_picture(doc, first, item=shared)
    new_picture(doc, second, png(8, 4, red=10))
    new_picture(doc, third, item=shared)  # the same image as the first picture
    save(ws, doc)
    assert len(bin_items(ws)) == 2
    assert DELETE("doc.hwpx", "picture", paragraph_index=1)["removedImages"] == 0
    assert len(bin_items(ws)) == 2  # the third picture still uses it
    assert DELETE("doc.hwpx", "picture", paragraph_index=2)["removedImages"] == 1
    assert len(bin_items(ws)) == 1
    assert DELETE("doc.hwpx", "picture", paragraph_index=3)["removedImages"] == 1
    assert bin_items(ws) == [] and not objects(ws, kind="picture")
    assert_clean(ws)


CHART = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    '<c:chartSpace xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:plotArea><c:layout/><c:pieChart><c:varyColors val="1"/><c:ser><c:idx val="0"/><c:order val="0"/>'
    '<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$3</c:f><c:strCache><c:ptCount val="2"/><c:pt idx="0"><c:v>{0}</c:v></c:pt><c:pt idx="1"><c:v>B</c:v></c:pt></c:strCache></c:strRef></c:cat>'
    '<c:val><c:numRef><c:f>Sheet1!$B$2:$B$3</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="2"/><c:pt idx="0"><c:v>60</c:v></c:pt><c:pt idx="1"><c:v>40</c:v></c:pt>'
    "</c:numCache></c:numRef></c:val></c:ser></c:pieChart></c:plotArea></c:chart></c:chartSpace>"
)


def test_deleting_a_chart_drops_its_part(ws):
    doc = HwpxDocument.new()
    for label in ("A", "C"):
        doc.shapes.add_chart(CHART.format(label), paragraph=doc.add_paragraph(""), size=(12000, 9000))
    save(ws, doc)
    charts = lambda: sorted(n for n in zipfile.ZipFile(ws / "doc.hwpx").namelist() if n.startswith("Chart/"))
    assert len(charts()) == 2 and objects(ws, paragraph_index=1)[0]["name"] == "chart"
    result = DELETE("doc.hwpx", "shape", paragraph_index=1)
    assert result["deleted"]["name"] == "chart" and result["removedCharts"] == 1 and len(charts()) == 1
    assert len(objects(ws, kind="shape")) == 1
    assert_clean(ws)


# ---------------------------------------------------------------- delete: links, fields, ruby

LINK_LOOK = "링크"


def run_texts(paragraph: etree._Element) -> list[tuple]:
    """Per run: (charPrIDRef, the text of its hp:t, the objects in it)."""
    return [(run.get("charPrIDRef"), "".join(t.xpath("string()") for t in run.findall(HP + "t")),
             [etree.QName(c).localname if etree.QName(c).localname != "ctrl" else etree.QName(c[0]).localname for c in run if etree.QName(c).localname not in ("t", "secPr")])
            for run in paragraph.findall(HP + "run")]


def test_unlinking_a_synthetic_hyperlink_keeps_the_text_and_its_look(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("앞 ")
    paragraph.add_hyperlink("https://a.example", LINK_LOOK)
    paragraph.add_run(" 뒤")
    save(ws, doc)
    before = run_texts(section_xml(ws).findall(HP + "p")[1])
    link_look = next(ref for ref, text, _ in before if text == LINK_LOOK)
    result = DELETE("doc.hwpx", "hyperlink", paragraph_index=1)
    assert result["deleted"]["url"] == "https://a.example" and result["deleted"]["text"] == LINK_LOOK and result["fieldEndsRemoved"] == 1
    assert "format_text_ext" in result["note"] and result["remaining"] == 0
    after = run_texts(section_xml(ws).findall(HP + "p")[1])
    assert [text for _, text, _ in after] == ["앞 ", LINK_LOOK, " 뒤"]  # the two marker runs are gone, the text is where it was
    assert (link_look, LINK_LOOK, []) in after and not list(section_xml(ws).iter(HP + "fieldBegin")) and not list(section_xml(ws).iter(HP + "fieldEnd"))
    assert hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopen(ws), paragraph_index=1)) == "앞 링크 뒤"
    assert_clean(ws)


def hancom_style_link(paragraph, end_in=None):
    """Rebuild the paragraph as Hancom saves a link: run[t, ctrl(fieldBegin)] run[display text] run[ctrl(fieldEnd), t]."""
    root = paragraph.element
    for run in root.findall(HP + "run"):
        root.remove(run)

    def run_of(*children, ref="0"):
        run = root.makeelement(HP + "run", {"charPrIDRef": ref})
        for child in children:
            run.append(child)
        return run

    def text(value):
        t = root.makeelement(HP + "t", {})
        t.text = value
        return t

    def ctrl(tag, **attrs):
        wrapper = root.makeelement(HP + "ctrl", {})
        wrapper.append(root.makeelement(HP + tag, attrs))
        return wrapper

    begin = ctrl("fieldBegin", id="777", type="HYPERLINK", name="", fieldid="627600491")
    begin[0].append(begin[0].makeelement(HP + "parameters", {"cnt": "0", "name": ""}))
    runs = [run_of(text("앞"), begin), run_of(text("표시 글"), ref="5"), run_of(ctrl("fieldEnd", beginIDRef="777", fieldid="627600491"), text("뒤"))]
    if end_in is None:
        for run in runs:
            root.append(run)
    return root, runs


def test_unlinking_a_hancom_style_link_keeps_the_text_that_shares_the_marker_runs(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("x")
    root, runs = hancom_style_link(paragraph)
    save(ws, doc)
    assert objects(ws, paragraph_index=1)[0]["text"] == "표시 글"
    DELETE("doc.hwpx", "hyperlink", paragraph_index=1)
    after = run_texts(section_xml(ws).findall(HP + "p")[1])
    assert after == [("0", "앞", []), ("5", "표시 글", []), ("0", "뒤", [])]  # no run was dropped: each still holds text
    assert hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopen(ws), paragraph_index=1)) == "앞표시 글뒤"


def test_unlinking_finds_a_fieldend_in_another_paragraph_of_the_section(ws):
    doc = HwpxDocument.new()
    first, second = doc.add_paragraph("x"), doc.add_paragraph("y")
    root, runs = hancom_style_link(first, end_in=second)
    for run in runs[:2]:
        first.element.append(run)
    second.element.insert(0, runs[2])
    second.element.append(second.element.makeelement(HP + "linesegarray", {}))
    first.element.append(first.element.makeelement(HP + "linesegarray", {}))
    save(ws, doc)
    assert objects(ws, paragraph_index=1)[0]["kind"] == "hyperlink" and "text" not in objects(ws, paragraph_index=1)[0]  # no end in the same paragraph
    result = DELETE("doc.hwpx", "hyperlink", paragraph_index=1)
    assert result["fieldEndsRemoved"] == 1 and result["warnings"] == []
    section = section_xml(ws)
    assert not list(section.iter(HP + "fieldBegin")) and not list(section.iter(HP + "fieldEnd"))
    paragraphs = section.findall(HP + "p")
    assert [hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopen(ws), paragraph_index=i)) for i in (1, 2)] == ["앞표시 글", "뒤y"]
    assert paragraphs[1].find(HP + "linesegarray") is None and paragraphs[2].find(HP + "linesegarray") is None


def test_a_link_without_its_fieldend_is_unlinked_with_a_warning(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("x")
    hancom_style_link(paragraph)
    paragraph.element.remove(paragraph.element.findall(HP + "run")[2])
    save(ws, doc)
    result = DELETE("doc.hwpx", "hyperlink", paragraph_index=1)
    assert result["fieldEndsRemoved"] == 0 and "no matching fieldEnd" in result["warnings"][0]


def test_a_field_that_is_not_a_link_is_unlinked_but_a_memo_field_is_refused(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("앞")
    paragraph.add_date_field("2026년 10월 20일")
    save(ws, doc)
    result = DELETE("doc.hwpx", "field", paragraph_index=1)
    assert result["deleted"]["field_type"] == "DATE" and result["fieldEndsRemoved"] == 1
    assert hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopen(ws), paragraph_index=1)).endswith("2026년 10월 20일")
    doc = HwpxDocument.new()
    host = doc.add_paragraph("메모 달린 글")
    doc.notes.add_memo("메모 내용", anchor=host)
    save(ws, doc)
    before = sha(ws)
    assert objects(ws, paragraph_index=1)[0]["field_type"] == "MEMO"
    with pytest.raises(ToolInputError, match="remove_memo"):
        DELETE("doc.hwpx", "field", paragraph_index=1)
    assert sha(ws) == before


@pytest.mark.parametrize("kind, base, keep", [("ruby", "漢", True), ("ruby", "漢", False), ("composed", "가", True), ("composed", "가", False)])
def test_ruby_and_composed_leave_their_base_text_unless_asked_not_to(ws, kind, base, keep):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("앞")
    ADD[kind](doc, paragraph)
    paragraph.add_run("뒤")
    save(ws, doc)
    holder_ref = next(run.get("charPrIDRef") for run in section_xml(ws).findall(HP + "p")[1].findall(HP + "run") if run.find(HP + ("dutmal" if kind == "ruby" else "compose")) is not None)
    result = DELETE("doc.hwpx", kind, paragraph_index=1, keep_text=keep)
    assert result["deleted"]["kind"] == kind
    text = hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopen(ws), paragraph_index=1))
    assert text == ("앞" + (base if keep else "") + "뒤")
    assert not list(section_xml(ws).iter(HP + ("dutmal" if kind == "ruby" else "compose")))
    if keep:  # the base text sits in the run where the object stood
        assert any(ref == holder_ref and base in run_text for ref, run_text, _ in run_texts(section_xml(ws).findall(HP + "p")[1]))
    assert not objects(ws, paragraph_index=1, kind=kind)


def test_keep_text_false_is_refused_for_other_kinds(ws):
    address = build(ws, in_body, ADD["equation"])
    before = sha(ws)
    with pytest.raises(ToolInputError, match="keep_text=false only applies"):
        DELETE("doc.hwpx", "equation", keep_text=False, **address)
    assert sha(ws) == before


def test_deleting_a_bookmark_counts_the_links_that_lose_their_target(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("목적지")
    paragraph.add_bookmark("표적")
    other = doc.add_paragraph("")
    other.add_hyperlink("#표적", "이동 1")
    other.add_hyperlink("#표적", "이동 2")
    other.add_hyperlink("#다른곳", "이동 3")
    save(ws, doc)
    result = DELETE("doc.hwpx", "bookmark", paragraph_index=1)
    assert len(result["warnings"]) == 1 and result["warnings"][0].startswith("2 hyperlink(s)")
    assert len(objects(ws, kind="hyperlink")) == 3 and not objects(ws, kind="bookmark")


# ---------------------------------------------------------------- update: equation

def one_equation(ws, script="a over b", base_unit=1000, size=None, line=None):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("식:")
    paragraph.add_equation(script, base_unit=base_unit)
    equation = paragraph.element.find(f".//{HP}equation")
    if size:
        equation.find(HP + "sz").set("width", str(size[0]))
        equation.find(HP + "sz").set("height", str(size[1]))
    if line:
        equation.set("baseLine", str(line))
    save(ws, doc)
    return {"paragraph_index": 1}


def equation_of(ws) -> etree._Element:
    return section_xml(ws).find(f".//{HP}equation")


def test_a_new_script_is_measured_and_flagged_as_an_estimate(ws):
    address = one_equation(ws, base_unit=1100)
    result = UPDATE("doc.hwpx", "equation", {"script": "{x+1} over {y-1}"}, **address)
    box = measure_equation("{x+1} over {y-1}", base_unit=1100)
    equation = equation_of(ws)
    assert equation.find(HP + "script").text == "{x+1} over {y-1}" and equation.get("baseUnit") == "1100"
    assert (int(equation.find(HP + "sz").get("width")), int(equation.find(HP + "sz").get("height")), int(equation.get("baseLine"))) == tuple(box)
    assert result["estimated"] is True and "Hancom recalculates the box" in result["note"]
    assert result["changed"]["script"] == {"before": "a over b", "after": "{x+1} over {y-1}"} and "base_unit" not in result["changed"]
    assert objects(ws, paragraph_index=1)[0]["script"] == "{x+1} over {y-1}"
    assert_clean(ws)


def test_the_same_script_with_another_base_unit_scales_the_stored_box(ws):
    address = one_equation(ws, size=(2000, 3000), line=70)  # a box that is not what the estimate would give (Hancom's own differs from it)
    result = UPDATE("doc.hwpx", "equation", {"base_unit": 1500}, **address)
    equation = equation_of(ws)
    assert (equation.find(HP + "sz").get("width"), equation.find(HP + "sz").get("height")) == ("3000", "4500")
    assert equation.get("baseUnit") == "1500" and equation.get("baseLine") == "70"  # baseLine is a share of the height: a uniform scale keeps it
    assert "estimated" not in result and result["changed"]["base_unit"] == {"before": 1000, "after": 1500}
    assert result["changed"]["width_mm"] == {"before": round(2000 / UNIT, 2), "after": round(3000 / UNIT, 2)}


def test_width_or_height_win_over_the_box_and_one_alone_keeps_the_proportion(ws):
    address = one_equation(ws, size=(2000, 1000), line=70)
    UPDATE("doc.hwpx", "equation", {"width_mm": 10}, **address)
    size = equation_of(ws).find(HP + "sz")
    assert (size.get("width"), size.get("height")) == (str(round(10 * UNIT)), str(round(round(10 * UNIT) / 2)))
    UPDATE("doc.hwpx", "equation", {"height_mm": 4}, **address)
    size = equation_of(ws).find(HP + "sz")
    assert size.get("height") == str(round(4 * UNIT)) and int(size.get("width")) == round(round(4 * UNIT) * 2835 / 1418)
    # a new script with a given width: the height follows the proportion of the recalculated box
    result = UPDATE("doc.hwpx", "equation", {"script": "x over y", "width_mm": 12, "height_mm": 5}, **address)
    size = equation_of(ws).find(HP + "sz")
    assert (size.get("width"), size.get("height")) == (str(round(12 * UNIT)), str(round(5 * UNIT))) and result["estimated"]
    UPDATE("doc.hwpx", "equation", {"script": "{a+b} over {c}", "width_mm": 20}, **address)
    box = measure_equation("{a+b} over {c}", base_unit=1000)
    size = equation_of(ws).find(HP + "sz")
    assert size.get("width") == str(round(20 * UNIT)) and size.get("height") == str(round(round(20 * UNIT) * box.height / box.width))


def test_a_long_script_is_cut_in_the_response_and_an_unchanged_one_changes_nothing(ws):
    address = one_equation(ws)
    script = " + ".join(f"x{n}" for n in range(60))
    result = UPDATE("doc.hwpx", "equation", {"script": script}, **address)
    assert len(result["changed"]["script"]["after"]) == 80 and equation_of(ws).find(HP + "script").text == script
    again = UPDATE("doc.hwpx", "equation", {"script": script, "base_unit": 1000}, **address)
    assert again["changed"] == {} and "nothing was changed" in again["warnings"][0] and "estimated" not in again


# ---------------------------------------------------------------- update: picture

def one_picture(ws, size=(10000, 4000), move=("243", "-351")):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("그림:")
    picture = new_picture(doc, paragraph, width=size[0], height=size[1]).element
    scale = picture.find(f"{HP}renderingInfo/{HC}scaMatrix")
    scale.set("e3", move[0])
    scale.set("e6", move[1])
    save(ws, doc)
    return {"paragraph_index": 1}


def picture_of(ws) -> etree._Element:
    return section_xml(ws).find(f".//{HP}pic")


def pic_state(picture: etree._Element) -> dict:
    sca = picture.find(f"{HP}renderingInfo/{HC}scaMatrix")
    return {
        "sz": dict(picture.find(HP + "sz").attrib), "curSz": dict(picture.find(HP + "curSz").attrib), "orgSz": dict(picture.find(HP + "orgSz").attrib),
        "rot": dict(picture.find(HP + "rotationInfo").attrib), "sca": dict(sca.attrib),
        "fixed": [etree.tostring(picture.find(path)) for path in (HP + "imgRect", HP + "imgClip", HP + "imgDim", f"{HP}renderingInfo/{HC}transMatrix", f"{HP}renderingInfo/{HC}rotMatrix")],
    }


def test_picture_size_is_written_the_way_hancom_stores_a_resized_picture(ws):
    address = one_picture(ws)
    original = pic_state(picture_of(ws))
    result = UPDATE("doc.hwpx", "picture", {"width_mm": 10}, **address)  # one side: the proportion 10000:4000 stays
    width = round(10 * UNIT)
    height = round(width * 4000 / 10000)
    state = pic_state(picture_of(ws))
    assert state["sz"]["width"] == str(width) and state["sz"]["height"] == str(height)
    assert (state["curSz"]["width"], state["curSz"]["height"]) == (str(width), str(height))
    assert state["sca"]["e1"] == f"{round(width / 10000, 6):.6f}".rstrip("0") and state["sca"]["e5"] == f"{round(height / 4000, 6):.6f}".rstrip("0")
    assert (state["rot"]["centerX"], state["rot"]["centerY"]) == (str(width // 2), str(height // 2)) and state["rot"]["angle"] == "0"
    assert state["sca"]["e3"] == "243" and state["sca"]["e6"] == "-351" and state["sca"]["e2"] == state["sca"]["e4"] == "0"  # the move part stays
    assert state["orgSz"] == original["orgSz"] and state["fixed"] == original["fixed"]  # original size, crop, image box and the other matrices stay
    assert result["changed"] == {"width_mm": {"before": round(10000 / UNIT, 2), "after": round(width / UNIT, 2)}, "height_mm": {"before": round(4000 / UNIT, 2), "after": round(height / UNIT, 2)}}
    # the layout reader sees the new size, and a second resize works from the new size
    assert (objects(ws, **address)[0]["width"], objects(ws, **address)[0]["height"]) == (width, height)
    UPDATE("doc.hwpx", "picture", {"height_mm": 3}, **address)
    new_height = round(3 * UNIT)
    state = pic_state(picture_of(ws))
    assert state["sz"]["height"] == str(new_height) and state["sz"]["width"] == str(round(new_height * width / height))
    assert state["fixed"] == original["fixed"] and state["orgSz"] == original["orgSz"]
    UPDATE("doc.hwpx", "picture", {"width_mm": 20, "height_mm": 20}, **address)
    assert (picture_of(ws).find(HP + "sz").get("width"), picture_of(ws).find(HP + "sz").get("height")) == (str(round(20 * UNIT)), str(round(20 * UNIT)))
    assert_clean(ws)


def test_brightness_and_contrast_are_set_on_the_image_element(ws):
    address = one_picture(ws)
    result = UPDATE("doc.hwpx", "picture", {"brightness": 30, "contrast": -20}, **address)
    image = picture_of(ws).find(f".//{HC}img")
    assert (image.get("bright"), image.get("contrast")) == ("30", "-20")
    assert result["changed"] == {"brightness": {"before": 0, "after": 30}, "contrast": {"before": 0, "after": -20}}
    assert picture_of(ws).find(HP + "sz").get("width") == "10000"  # the size is not touched


def test_a_rotated_picture_is_not_resized_and_treat_as_char_is_not_supported(ws):
    address = one_picture(ws)
    doc = reopen(ws)
    doc.paragraphs[1].element.find(f".//{HP}rotationInfo").set("angle", "90")
    doc.paragraphs[1].section.mark_dirty()
    save(ws, doc)
    before = sha(ws)
    with pytest.raises(ToolInputError, match="rotated"):
        UPDATE("doc.hwpx", "picture", {"width_mm": 10}, **address)
    assert UPDATE("doc.hwpx", "picture", {"brightness": 5}, **address)["changed"]  # only the size is refused
    with pytest.raises(ToolInputError, match="treat_as_char is not supported yet"):
        UPDATE("doc.hwpx", "picture", {"treat_as_char": False}, **address)
    assert sha(ws) != before


# ---------------------------------------------------------------- update: bookmark, hyperlink, check box

def command_of(begin: etree._Element) -> str:
    return next(p.text for p in begin.iter(HP + "stringParam") if p.get("name") == "Command")


def test_renaming_a_bookmark_follows_the_links_to_it(ws):
    doc = HwpxDocument.new()
    doc.add_paragraph("목적지").add_bookmark("표:적")
    other = doc.add_paragraph("")
    other.add_hyperlink("#표:적", "이동 1")
    other.add_hyperlink("#표:적", "이동 2")
    other.add_hyperlink("#표", "표 링크")  # a name that only starts the same way
    other.add_hyperlink("https://a.example", "웹")
    tip = other.element.findall(f".//{HP}fieldBegin")[1]
    next(p for p in tip.iter(HP + "stringParam") if p.get("name") == "Command").text = "?표\\:적|도움말;0;0;0;"
    save(ws, doc)
    assert [command_of(b) for b in section_xml(ws).iter(HP + "fieldBegin")][:2] == ["?표\\:적;0;0;0;", "?표\\:적|도움말;0;0;0;"]
    result = UPDATE("doc.hwpx", "bookmark", {"name": "새;이름"}, paragraph_index=1)
    assert result["updatedLinks"] == 2 and result["changed"]["name"] == {"before": "표:적", "after": "새;이름"}
    commands = [command_of(b) for b in section_xml(ws).iter(HP + "fieldBegin")]
    assert commands[:2] == ["?새\\;이름;0;0;0;", "?새\\;이름|도움말;0;0;0;"]
    assert commands[2] == "?표;0;0;0;" and commands[3] == "https\\://a.example;1;0;0;"
    assert [item["name"] for item in objects(ws, kind="bookmark")] == ["새;이름"]
    assert_clean(ws)


def test_a_bookmark_name_must_be_new_and_not_empty(ws):
    doc = HwpxDocument.new()
    host = doc.add_paragraph("가")
    host.add_bookmark("하나")
    host.add_bookmark("둘")
    save(ws, doc)
    with pytest.raises(ToolInputError, match="already exists"):
        UPDATE("doc.hwpx", "bookmark", {"name": "둘"}, nth=1, paragraph_index=1)
    for bad in ("", "  ", 3):
        with pytest.raises(ToolInputError, match="properties.name must be a non-empty string"):
            UPDATE("doc.hwpx", "bookmark", {"name": bad}, paragraph_index=1)
    assert UPDATE("doc.hwpx", "bookmark", {"name": "하나"}, paragraph_index=1)["changed"] == {}  # its own name is not a duplicate
    assert [item["name"] for item in objects(ws, kind="bookmark")] == ["하나", "둘"]


def parameters(begin: etree._Element) -> list[tuple[str, str, str]]:
    return [(etree.QName(p).localname, p.get("name"), p.text) for p in begin.find(HP + "parameters")]


@pytest.mark.parametrize("url", ["mailto:teacher@example.com", "#표적", "https://b.example/a?x=1;y=2#top"])
def test_hyperlink_url_rebuilds_the_whole_parameter_block(ws, url):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("앞")
    paragraph.add_bookmark("표적")
    paragraph.add_hyperlink("https://a.example", "표시 글")
    save(ws, doc)
    result = UPDATE("doc.hwpx", "hyperlink", {"url": url}, paragraph_index=1)
    begin = section_xml(ws).find(f".//{HP}fieldBegin")
    assert parameters(begin) == hyperlink_parameters(url)
    assert begin.find(HP + "parameters").get("cnt") == str(len(hyperlink_parameters(url))) and begin.get("name") == url
    assert result["changed"]["url"] == {"before": "https://a.example", "after": url} and result["warnings"] == []
    assert objects(ws, paragraph_index=1, kind="hyperlink")[0]["text"] == "표시 글"  # the display text is untouched
    assert_clean(ws)


def test_hyperlink_to_a_missing_bookmark_warns_and_a_link_without_parameters_is_rebuilt(ws):
    doc = HwpxDocument.new()
    paragraph = doc.add_paragraph("앞")
    paragraph.add_hyperlink("https://a.example", "표시")
    begin = paragraph.element.find(f".//{HP}fieldBegin")
    begin.remove(begin.find(HP + "parameters"))  # as python-hwpx wrote links before: only @name
    save(ws, doc)
    result = UPDATE("doc.hwpx", "hyperlink", {"url": "#없는곳"}, paragraph_index=1)
    assert "no bookmark named '없는곳'" in result["warnings"][0]
    assert parameters(section_xml(ws).find(f".//{HP}fieldBegin")) == hyperlink_parameters("#없는곳")
    same = UPDATE("doc.hwpx", "hyperlink", {"url": "#없는곳"}, paragraph_index=1)
    assert same["changed"] == {}


def test_check_box_state_and_caption(ws):
    doc = HwpxDocument.new()
    host = doc.add_paragraph("")
    host.add_check_box("첫째")
    host.add_check_box("둘째", checked=True)
    save(ws, doc)
    result = UPDATE("doc.hwpx", "check_box", {"checked": True, "caption": "새 보기"}, nth=1, paragraph_index=1)
    boxes = list(section_xml(ws).iter(HP + "checkBtn"))
    assert [(b.get("value"), b.get("caption")) for b in boxes] == [("CHECKED", "새 보기"), ("CHECKED", "둘째")]
    assert result["changed"] == {"checked": {"before": False, "after": True}, "caption": {"before": "첫째", "after": "새 보기"}}
    UPDATE("doc.hwpx", "check_box", {"checked": False}, nth=2, paragraph_index=1)
    assert [(i["caption"], i["checked"]) for i in objects(ws, kind="check_box")] == [("새 보기", True), ("둘째", False)]
    with pytest.raises(ToolInputError, match="properties.checked must be true or false"):
        UPDATE("doc.hwpx", "check_box", {"checked": "yes"}, paragraph_index=1)


# ---------------------------------------------------------------- places, sections and common refusals

@pytest.mark.parametrize("place", PLACES)
def test_update_works_in_every_place(ws, place):
    address = build(ws, PLACES[place], ADD["equation"])
    result = UPDATE("doc.hwpx", "equation", {"script": "x over y"}, **address)
    assert result["estimated"] and objects(ws, **address)[0]["script"] == "x over y"
    assert_clean(ws)


def test_a_second_section_saves_its_note_equation_deletion_and_link_renames(ws):
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("구역 0")
    doc.paragraphs[0].add_bookmark("먼곳")
    doc.add_section()
    host = doc.sections[1].add_paragraph("구역 1 문항")
    doc.notes.add_endnote("구역 1 해설", paragraph=host)
    note = hwpx_locate.resolve_paragraph(doc, section_index=1, endnote_number=1)
    note.add_equation("a over b")
    host.add_hyperlink("#먼곳", "이동")
    save(ws, doc)
    assert section_xml(ws, 1).find(f".//{HP}equation") is not None
    result = DELETE("doc.hwpx", "equation", endnote_number=1, section_index=1)
    assert result["remaining"] == 0 and section_xml(ws, 1).find(f".//{HP}equation") is None
    assert objects(ws, section=1, kind="equation") == []
    result = UPDATE("doc.hwpx", "bookmark", {"name": "가까운곳"}, paragraph_index=0)
    assert result["updatedLinks"] == 1  # the link is in the other section
    assert command_of(section_xml(ws, 1).find(f".//{HP}fieldBegin")) == "?가까운곳;0;0;0;"
    assert section_xml(ws, 0).find(f".//{HP}bookmark").get("name") == "가까운곳"
    assert_clean(ws)


def test_refusals_leave_the_file_alone(ws):
    address = build(ws, in_body, ADD["equation"], ADD["hyperlink"])
    before = sha(ws)
    bad_calls = [
        (lambda: DELETE("doc.hwpx", "table", **address), "kind 'table' is not one of"),
        (lambda: DELETE("doc.hwpx", "bogus", **address), "is not one of"),
        (lambda: DELETE("doc.hwpx", "equation"), "give exactly one paragraph address group"),
        (lambda: DELETE("doc.hwpx", "equation", paragraph_index=1, table_index=0, row=0, col=0), "give exactly one"),
        (lambda: DELETE("doc.hwpx", "equation", paragraph_index=99), "invalid paragraph_index"),
        (lambda: DELETE("doc.hwpx", "equation", paragraph_index=1, section_index=7), "invalid section_index"),
        (lambda: DELETE("doc.hwpx", "equation", paragraph_index=1, expected_revision="sha256:" + "0" * 64), "revision mismatch"),
        (lambda: UPDATE("doc.hwpx", "ruby", {"x": 1}, **address), "kind 'ruby' is not one of"),
        (lambda: UPDATE("doc.hwpx", "equation", {}, **address), "non-empty object"),
        (lambda: UPDATE("doc.hwpx", "equation", {"bright": 1}, **address), "allowed: \\['script', 'base_unit', 'width_mm', 'height_mm'\\]"),
        (lambda: UPDATE("doc.hwpx", "equation", {"script": "  "}, **address), "properties.script must be a non-empty string"),
        (lambda: UPDATE("doc.hwpx", "equation", {"base_unit": 0}, **address), "properties.base_unit"),
        (lambda: UPDATE("doc.hwpx", "equation", {"base_unit": True}, **address), "properties.base_unit"),
        (lambda: UPDATE("doc.hwpx", "equation", {"width_mm": 0}, **address), "positive number of mm"),
        (lambda: UPDATE("doc.hwpx", "equation", {"width_mm": float("inf")}, **address), "positive number of mm"),
        (lambda: UPDATE("doc.hwpx", "picture", {"brightness": 101}, **address), "from -100 to 100"),
        (lambda: UPDATE("doc.hwpx", "hyperlink", {"url": ""}, **address), "properties.url"),
        (lambda: UPDATE("doc.hwpx", "equation", {"script": "x"}, nth=2, **address), "out of range"),
        (lambda: UPDATE("doc.hwpx", "equation", {"script": "x"}, nth=0, **address), "nth must be"),
        (lambda: UPDATE("doc.hwpx", "check_box", {"checked": True}, **address), "has no check_box object"),
        (lambda: UPDATE("doc.hwpx", "equation", "script", **address), "non-empty object"),
    ]
    for call, message in bad_calls:
        with pytest.raises(ToolInputError, match=message) as error:
            call()
        assert str(ws) not in str(error.value) and "doc.hwpx" not in str(error.value)
    assert sha(ws) == before


def test_dry_run_changes_nothing_and_still_reports(ws):
    address = build(ws, in_body, ADD["equation"], ADD["picture"], ADD["bookmark"], ADD["hyperlink"])
    before = sha(ws)
    deleted = DELETE("doc.hwpx", "picture", dry_run=True, **address)
    assert deleted["removedImages"] == 1 and deleted["dryRun"] is True
    assert DELETE("doc.hwpx", "hyperlink", dry_run=True, **address)["fieldEndsRemoved"] == 1
    assert UPDATE("doc.hwpx", "equation", {"script": "z"}, dry_run=True, **address)["changed"]["script"]["after"] == "z"
    assert UPDATE("doc.hwpx", "bookmark", {"name": "다른"}, dry_run=True, **address)["changed"]
    assert UPDATE("doc.hwpx", "picture", {"width_mm": 5}, dry_run=True, **address)["changed"]
    assert sha(ws) == before and len(bin_items(ws)) == 1


def test_a_matching_expected_revision_is_accepted(ws):
    address = build(ws, in_body, ADD["equation"])
    revision = DELETE("doc.hwpx", "equation", dry_run=True, **address)["document_revision"]
    assert DELETE("doc.hwpx", "equation", expected_revision=revision, **address)["remaining"] == 0


def test_the_tools_are_plain_module_functions_with_the_address_in_their_description():
    import inspect
    for tool in (DELETE, UPDATE):
        names = list(inspect.signature(tool).parameters)
        assert set(hwpx_locate.ADDRESS_ARGS) <= set(names) and names[:2] == ["filename", "kind"]
        assert {"nth", "section_index", "dry_run", "expected_revision"} <= set(names)
        assert "{ADDRESS}" not in tool.__doc__ and "paragraph_index" in tool.__doc__
    assert "keep_text" in inspect.signature(DELETE).parameters and "properties" in inspect.signature(UPDATE).parameters
