"""hwpx_edit의 쓰기 도구. 실행(패키지된 환경 그대로):
venv/bin/python -m pytest toolkit/tests"""
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_edit  # noqa: E402
import hwpx_layout  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    first = doc.paragraphs[0]
    first.add_run("가나다라마바사")
    doc.styles.apply_paragraph_format(
        paragraphs=[first], alignment="JUSTIFY", line_spacing_percent=160, break_non_latin_word="KEEP_WORD")
    doc.add_paragraph("두 번째 문단")
    doc.save_to_path(tmp_path / "doc.hwpx")
    return tmp_path


def xml(ws: Path, name: str) -> str:
    return zipfile.ZipFile(ws / "doc.hwpx").read(name).decode()


def shape(ws: Path, index: int = 0) -> dict:
    out = hwpx_layout.read_layout(ws / "doc.hwpx", "body")
    return out["shapes"][out["items"][index]["paraPr"]]


def test_only_passed_options_change(ws):
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, indent_left_mm=3.0)
    got = shape(ws)
    assert got["align"] == "JUSTIFY" and got["breakNonLatin"] == "KEEP_WORD" and got["lineSpacing"] == ["PERCENT", "160"]
    assert got["indent"]["left"] == "850"


def test_break_condense_grid_border(ws):
    border = {"type": "SOLID", "width": "0.12 mm", "color": "#000000", "offset_mm": 2, "connect": True}
    hwpx_edit.set_paragraph_format_ext(
        "doc.hwpx", paragraph_index=0, break_non_latin_word="BREAK_WORD", condense=75, snap_to_grid=False, border=border)
    got = shape(ws)
    assert got["breakNonLatin"] == "BREAK_WORD" and got["condense"] == 75 and got["snap_to_grid"] is False
    assert got["border"]["connect"] is True and got["border"]["sides"] == ["b", "l", "r", "t"]


@pytest.mark.parametrize("pos", [628, 1, 20001, 33333, 59527])
def test_tab_stop_hwpunit_is_exact(ws, pos):
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, tab_stops=[{"pos": pos, "type": "RIGHT"}])
    header = xml(ws, "Contents/header.xml")
    assert re.search(rf'<hh:tabItem[^>]*pos="{pos}"[^>]*type="RIGHT"', header)


def test_page_and_column_break_are_paragraph_attributes(ws):
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_indexes=[1], page_break=True, column_break=True)
    out = hwpx_layout.read_layout(ws / "doc.hwpx", "body")
    assert (out["items"][1]["pageBreak"], out["items"][1]["columnBreak"]) == ("1", "1")
    assert (out["items"][0]["pageBreak"], out["items"][0]["columnBreak"]) == ("0", "0")
    with pytest.raises(ValueError):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", page_break=True)


def test_dry_run_and_stale_revision_leave_file_alone(ws):
    before = hashlib.sha256((ws / "doc.hwpx").read_bytes()).hexdigest()
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, condense=60, dry_run=True)
    with pytest.raises(hwpx_edit.ToolInputError, match="revision mismatch"):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, condense=60, expected_revision="sha256:" + "0" * 64)
    assert hashlib.sha256((ws / "doc.hwpx").read_bytes()).hexdigest() == before


def test_format_text_ext_splits_run_and_sets_char_options(ws):
    hwpx_edit.format_text_ext("doc.hwpx", 0, 2, 4, ratio=90, letter_spacing=-5, underline=True, underline_shape="DOT")
    section = xml(ws, "Contents/section0.xml")
    runs = re.findall(r'<hp:run charPrIDRef="(\d+)"><hp:t>([^<]*)</hp:t>', section)
    texts = [t for _, t in runs if t in ("가나", "다라", "마바사")]
    assert texts == ["가나", "다라", "마바사"]
    ids = {t: i for i, t in runs}
    assert ids["가나"] == ids["마바사"] != ids["다라"]
    header = xml(ws, "Contents/header.xml")
    char = re.search(rf'<hh:charPr [^>]*\bid="{ids["다라"]}".*?</hh:charPr>', header, re.S).group(0)
    assert 'ratio hangul="90"' in char and 'spacing hangul="-5"' in char and 'type="BOTTOM" shape="DOT"' in char


def test_format_text_ext_needs_an_option_and_a_valid_range(ws):
    with pytest.raises(ValueError):
        hwpx_edit.format_text_ext("doc.hwpx", 0, 0, 2)
    with pytest.raises(ValueError):
        hwpx_edit.format_text_ext("doc.hwpx", 0, 3, 3, bold=True)


def test_set_tab_attributes_on_text_tab(ws):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    doc.add_paragraph("①\t본문")
    doc.save_to_path(ws / "doc.hwpx")
    index = len(HwpxDocument.open(ws / "doc.hwpx").paragraphs) - 1
    assert "<hp:tab/>" in xml(ws, "Contents/section0.xml")
    hwpx_edit.set_tab_attributes("doc.hwpx", index, width=628, tab_type=1)
    assert '<hp:tab width="628" leader="0" type="1"/>' in xml(ws, "Contents/section0.xml")
    with pytest.raises(ValueError):
        hwpx_edit.set_tab_attributes("doc.hwpx", index, width=1, tab_index=3)


def test_reader_shows_tab_stops_and_char_options(ws):
    hwpx_edit.set_paragraph_format_ext(
        "doc.hwpx", paragraph_index=0, tab_stops=[{"pos": 628, "type": "LEFT"}, {"pos": 20000, "type": "RIGHT", "leader": "DOT"}])
    assert shape(ws)["tabs"]["stops"] == [
        {"pos": 628, "type": "LEFT", "leader": "NONE"}, {"pos": 20000, "type": "RIGHT", "leader": "DOT"}]
    hwpx_edit.format_text_ext("doc.hwpx", 0, 2, 4, letter_spacing=-5, underline=True, underline_shape="DOT")
    special = hwpx_layout.read_layout(ws / "doc.hwpx", "body")["items"][0]["special_runs"]
    assert [(r["text"], r["spacing"], r["underline_shape"]) for r in special] == [("다라", -5, "DOT")]


def test_endnote_placement_numbering_and_independent_shapes(ws):
    hwpx_edit.add_endnote_ext("doc.hwpx", 0, [
        {"runs": [{"text": " "}, {"text": "정답 ⑤", "bold": True}], "format": {"alignment": "LEFT", "line_spacing_percent": 130}},
        {"text": "출제 포인트", "char": {"bold": True}},
        {"text": ""},
    ])
    section = xml(ws, "Contents/section0.xml")
    assert re.search(r"<hp:t>가나다라마바사</hp:t><hp:ctrl><hp:endNote number=\"1\" suffixChar=\"41\"", section)
    note = section[section.index("<hp:subList", section.index("<hp:endNote")):]
    paras = re.findall(r'<hp:p paraPrIDRef="(\d+)" styleIDRef="(\d+)"', note)
    assert len(paras) == 3 and paras[0][0] != paras[1][0] == paras[2][0]  # only the first paragraph was formatted
    assert '<hp:autoNum num="1" numType="ENDNOTE">' in note
    assert hwpx_layout.read_layout(ws / "doc.hwpx", "notes")["items"][0]["paragraphs"][0]["text"].endswith("정답 ⑤")


def test_endnote_uses_given_ids_and_refuses_missing_ones(ws):
    hwpx_edit.add_endnote_ext("doc.hwpx", 1, [{"runs": [{"text": "정답 ③", "char_pr_id": "0"}], "para_pr_id": "0", "style_id": "0"}])
    note = xml(ws, "Contents/section0.xml")
    note = note[note.index("<hp:subList", note.index("<hp:endNote")):]
    assert re.search(r'<hp:p paraPrIDRef="0" styleIDRef="0"[^>]*><hp:run charPrIDRef="0">', note)
    with pytest.raises(ValueError, match="not found"):
        hwpx_edit.add_endnote_ext("doc.hwpx", 1, [{"text": "x", "para_pr_id": "999"}])


def test_endnote_rejects_bad_specs(ws):
    for bad in ([], [{"text": "a", "runs": [{"text": "b"}]}], [{"text": "a", "bogus": 1}], [{"text": "a", "char": {"nope": 1}}]):
        with pytest.raises(ValueError):
            hwpx_edit.add_endnote_ext("doc.hwpx", 0, bad)


def test_endnotes_are_numbered_in_document_order_even_when_added_out_of_order(ws):
    for index in (1, 0):
        hwpx_edit.add_endnote_ext("doc.hwpx", index, [{"text": f"해설{index}"}])
    section = xml(ws, "Contents/section0.xml")
    found = re.findall(r'<hp:t>([^<]*)</hp:t><hp:ctrl><hp:endNote number="(\d+)".*?<hp:autoNum num="(\d+)"', section, re.S)
    assert [(text, number, num) for text, number, num in found] == [("가나다라마바사", "1", "1"), ("두 번째 문단", "2", "2")]


@pytest.fixture()
def tbl(ws):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    doc.add_paragraph("").add_table(3, 3, width=30000, height=3000)
    doc.save_to_path(ws / "doc.hwpx")
    return ws


def table_xml(ws: Path) -> str:
    section = xml(ws, "Contents/section0.xml")
    return section[section.index("<hp:tbl"):section.index("</hp:tbl>")]


def test_table_geometry_margins_position_flags(tbl):
    hwpx_edit.format_table_ext(
        "doc.hwpx", 0, column_widths=[10000, 20000, 30000], row_heights=[1000, 2000, 3000], treat_as_char=True, page_break="NONE",
        repeat_header=True, out_margin={"left": 141, "top": 283}, in_margin={"left": 510, "right": 510, "top": 141, "bottom": 141},
        position={"horz_rel_to": "COLUMN", "vert_rel_to": "PARA", "horz_offset": 100})
    t = table_xml(tbl)
    assert '<hp:sz width="60000" widthRelTo="ABSOLUTE" height="6000"' in t
    assert re.findall(r'<hp:cellSz width="(\d+)" height="(\d+)"/>', t)[:3] == [("10000", "1000"), ("20000", "1000"), ("30000", "1000")]
    assert 'pageBreak="NONE"' in t and 'repeatHeader="1"' in t and 'treatAsChar="1"' in t
    assert re.search(r'<hp:outMargin left="141" right="\d+" top="283"', t) and re.search(r'<hp:inMargin left="510" right="510" top="141" bottom="141"', t)
    assert 'horzRelTo="COLUMN"' in t and 'vertRelTo="PARA"' in t and 'horzOffset="100"' in t


def test_table_total_width_keeps_column_proportions(tbl):
    hwpx_edit.format_table_ext("doc.hwpx", 0, width=45000)
    assert '<hp:sz width="45000"' in table_xml(tbl)
    assert {int(w) for w, _ in re.findall(r'<hp:cellSz width="(\d+)" height="(\d+)"/>', table_xml(tbl))} == {15000}


def test_table_merge_borders_cell_margin_valign_and_paragraphs(tbl):
    hwpx_edit.format_table_ext(
        "doc.hwpx", 0, merges=[[0, 0, 0, 2]], border={"sides": ["left", "right"], "width": "0.5 mm", "color": "#112233"},
        cells=[
            {"row": 1, "col": 1, "border": {"type": "DASH", "width": "0.2 mm"}, "margin": {"left": 700, "top": 50}, "vertical_align": "CENTER",
             "paragraphs": [{"runs": [{"text": "정답 ", "bold": True}, {"text": "③"}], "format": {"alignment": "CENTER"}}, {"text": "두 번째 줄"}]},
        ])
    t = table_xml(tbl)
    assert 'colSpan="3"' in t
    header = xml(tbl, "Contents/header.xml")
    table_bf = re.search(r"<hp:tbl [^>]*borderFillIDRef=\"(\d+)\"", t).group(1)
    bf = re.search(rf'<hh:borderFill [^>]*id="{table_bf}".*?</hh:borderFill>', header, re.S).group(0)
    assert 'rightBorder type="SOLID" width="0.5 mm" color="#112233"' in bf and 'topBorder type="NONE"' in bf
    cell = re.search(r'<hp:tc [^>]*borderFillIDRef="(\d+)"[^>]*>(?:(?!</hp:tc>).)*?정답 (?:(?!</hp:tc>).)*</hp:tc>', t, re.S)
    assert 'hasMargin="1"' in cell.group(0) and 'vertAlign="CENTER"' in cell.group(0) and "두 번째 줄" in cell.group(0)
    assert re.search(r'<hp:cellMargin left="700" right="\d+" top="50"', cell.group(0))
    assert 'type="DASH" width="0.2 mm"' in re.search(rf'<hh:borderFill [^>]*id="{cell.group(1)}".*?</hh:borderFill>', header, re.S).group(0)
    shapes = hwpx_layout.read_layout(tbl / "doc.hwpx", "tables")
    inner = [c for c in shapes["items"][0]["cells"] if c["r"] == 1 and c["c"] == 1][0]["paragraphs"]
    assert [p["text"] for p in inner] == ["정답 ③", "두 번째 줄"] and shapes["shapes"][inner[0]["shape"]]["align"] == "CENTER"


def test_table_given_ids_checked_and_bad_input_refused(tbl):
    hwpx_edit.format_table_ext("doc.hwpx", 0, cells=[{"row": 0, "col": 0, "border_fill_id": "1", "paragraphs": [{"text": "x", "para_pr_id": "0", "style_id": "0"}]}])
    for bad in (dict(table_index=5), dict(border_fill_id="999"), dict(cells=[{"row": 9, "col": 9, "vertical_align": "TOP"}]),
                dict(cells=[{"row": 0, "col": 0, "bogus": 1}]), dict(cells=[{"row": 0, "col": 0, "paragraphs": [{"text": "x", "para_pr_id": "999"}]}])):
        with pytest.raises(ValueError):
            hwpx_edit.format_table_ext("doc.hwpx", **{"table_index": 0, **bad})


def test_columns_with_separator_line_and_single_definition(ws):
    hwpx_edit.set_columns_ext("doc.hwpx", 2, gap=2268, separator_type="SOLID", separator_width="0.12 mm", separator_color="#000000")
    section = xml(ws, "Contents/section0.xml")
    assert len(re.findall(r"<hp:colPr ", section)) == 1  # replaced, not duplicated
    assert re.search(r'<hp:colPr [^>]*type="NEWSPAPER"[^>]*colCount="2"[^>]*sameGap="2268"', section)
    assert re.search(r'<hp:colLine type="SOLID" width="0.12 mm" color="#000000"/>', section)
    overview = hwpx_layout.read_layout(ws / "doc.hwpx")
    assert overview["columns"]["count"] == "2" and overview["columns"]["line"]["type"] == "SOLID"
    hwpx_edit.set_columns_ext("doc.hwpx", 1)
    assert 'colCount="1"' in xml(ws, "Contents/section0.xml") and len(re.findall(r"<hp:colPr ", xml(ws, "Contents/section0.xml"))) == 1
    with pytest.raises(ValueError):
        hwpx_edit.set_columns_ext("doc.hwpx", 0)


def test_attach_existing_ids_to_paragraphs_and_text_ranges(ws):
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, indent_left_mm=3.0)  # mints a new paragraph shape
    pid = re.findall(r'<hp:p [^>]*paraPrIDRef="(\d+)"', xml(ws, "Contents/section0.xml"))[0]
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=1, para_pr_id=pid, alignment="RIGHT")
    body = hwpx_layout.read_layout(ws / "doc.hwpx", "body")
    one, two = (body["shapes"][item["paraPr"]] for item in body["items"][:2])
    assert two["align"] == "RIGHT" and two["indent"] == one["indent"] and two["breakNonLatin"] == one["breakNonLatin"]
    with pytest.raises(ValueError):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=1, para_pr_id="999")
    with pytest.raises(ValueError):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", para_pr_id="0")


def test_attach_existing_char_shape_to_a_range(ws):
    hwpx_edit.format_text_ext("doc.hwpx", 0, 0, 2, bold=True)  # mints a bold character shape
    bold_id = re.search(r'<hp:run charPrIDRef="(\d+)"><hp:t>가나</hp:t>', xml(ws, "Contents/section0.xml")).group(1)
    assert bold_id != "0"
    hwpx_edit.format_text_ext("doc.hwpx", 1, 0, 2, char_pr_id=bold_id)
    assert f'<hp:run charPrIDRef="{bold_id}"><hp:t>두 </hp:t>' in xml(ws, "Contents/section0.xml")
    with pytest.raises(ValueError):
        hwpx_edit.format_text_ext("doc.hwpx", 1, 0, 2, char_pr_id="999")
    with pytest.raises(ValueError):
        hwpx_edit.format_text_ext("doc.hwpx", 1, 0, 2, char_pr_id="0", bold=True)


def test_header_part_lists_ids_and_kinds(ws):
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, keep_with_next=True, indent_left_mm=3.0)
    everything = hwpx_layout.read_layout(ws / "doc.hwpx", "header", max_chars=10**9)
    kinds = {item["kind"] for item in everything["items"]}
    assert {"paraPr", "charPr", "borderFill", "style"} <= kinds and everything["next" "Offset"] is None
    shapes = hwpx_layout.read_layout(ws / "doc.hwpx", "header", kind="paraPr", max_chars=10**9)["items"]
    assert all(item["kind"] == "paraPr" for item in shapes)
    used = hwpx_layout.read_layout(ws / "doc.hwpx", "body")["items"][0]["paraPr"]
    mine = next(item for item in shapes if item["indent"]["left"] == "850")
    assert mine["keepWithNext"] == "1" and mine["id"].isdigit() and used
    with pytest.raises(ValueError):
        hwpx_layout.read_layout(ws / "doc.hwpx", "body", kind="paraPr")
    with pytest.raises(ValueError):
        hwpx_layout.read_layout(ws / "doc.hwpx", "header", kind="nope")


def test_add_paragraphs_ext_never_inherits_and_inserts_where_asked(ws):
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_indexes=[0, 1], alignment="CENTER")
    hwpx_edit.format_text_ext("doc.hwpx", 1, 0, 3, font_size=20)
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "새 문단"}])
    body = hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)
    assert body["shapes"][body["items"][-1]["paraPr"]]["align"] != "CENTER"  # the paragraph before it is centered
    assert [item["text"] for item in body["items"]][-1] == "새 문단"
    result = hwpx_edit.add_paragraphs_ext(
        "doc.hwpx", [{"text": "", "char": {"font_size": 3}}, {"runs": [{"text": "A"}, {"text": "B", "bold": True}], "format": {"alignment": "RIGHT"}}], before_index=1)
    assert result["firstParagraphIndex"] == 1
    body = hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)
    assert [item["text"] for item in body["items"]][:4] == ["가나다라마바사", "", "AB", "두 번째 문단"]
    spacer = re.search(r'<hp:run charPrIDRef="(\d+)"(?:/>|><hp:t/>)', xml(ws, "Contents/section0.xml").split("가나다라마바사")[1])
    header = xml(ws, "Contents/header.xml")
    assert f'id="{spacer.group(1)}"' in header and re.search(rf'<hh:charPr [^>]*height="300"[^>]*id="{spacer.group(1)}"', header)
    with pytest.raises(hwpx_edit.ToolInputError, match="before_index"):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "x"}], before_index=99)
    with pytest.raises(hwpx_edit.ToolInputError, match="not found"):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "x", "para_pr_id": "999"}])


def test_format_text_ext_empty_paragraph_and_clear_errors(ws):
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": ""}])
    last = len(HwpxDocument.open(ws / "doc.hwpx").paragraphs) - 1
    hwpx_edit.format_text_ext("doc.hwpx", last, 0, 0, font_size=3)
    assert any(r["size"] == 3.0 for r in [c for c in hwpx_layout.read_layout(ws / "doc.hwpx", "header", kind="charPr", max_chars=10**9)["items"]])
    with pytest.raises(hwpx_edit.ToolInputError, match="characters"):
        hwpx_edit.format_text_ext("doc.hwpx", 0, 50, 60, bold=True)
    with pytest.raises(hwpx_edit.ToolInputError, match="empty"):
        hwpx_edit.format_text_ext("doc.hwpx", last, 0, 2, bold=True)


def test_paragraph_border_by_existing_border_fill_id(ws):
    border = {"sides": ["left", "right", "top", "bottom"], "type": "SOLID", "width": "0.1 mm", "color": "#000000"}
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, border=border)
    first = hwpx_layout.read_layout(ws / "doc.hwpx", "header", kind="paraPr", max_chars=10**9)["items"]
    bf_id = next(item["border"]["border_fill"] for item in first if item["border"])
    count = xml(ws, "Contents/header.xml").count("<hh:borderFill ")
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=1, border={"border_fill_id": bf_id, "connect": True})
    header = xml(ws, "Contents/header.xml")
    assert header.count("<hh:borderFill ") == count  # no new borderFill
    assert re.search(rf'<hh:border borderFillIDRef="{bf_id}"[^>]*connect="1"', header)
    with pytest.raises(hwpx_edit.ToolInputError, match="not defined"):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=1, border={"border_fill_id": "999"})
    with pytest.raises(hwpx_edit.ToolInputError, match="no border line"):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=1, border={"border_fill_id": "1"})


def test_table_row_heights_may_be_zero(tbl):
    hwpx_edit.format_table_ext("doc.hwpx", 0, row_heights=[0, 500, 0])
    t = table_xml(tbl)
    assert [h for _, h in re.findall(r'<hp:cellSz width="(\d+)" height="(\d+)"/>', t)][::3] == ["0", "500", "0"]
    with pytest.raises(hwpx_edit.ToolInputError, match="row_heights"):
        hwpx_edit.format_table_ext("doc.hwpx", 0, row_heights=[1, 2])


def test_tool_input_errors_keep_their_message_upstream_errors_do_not():
    from hwpx_automation import runtime
    hwpx_edit.patch_error_messages()
    assert runtime._classified_error_payload(hwpx_edit.ToolInputError("para_pr_id '30' is not defined"))["message"] == "para_pr_id '30' is not defined"
    assert "30" not in runtime._classified_error_payload(ValueError("secret 30"))["message"]


def test_small_refusals_and_item_options(ws):
    # tab stops must ascend; set_tab_attributes needs a tab; nothing goes in front of the section-definition paragraph; refusals give the index count
    with pytest.raises(hwpx_edit.ToolInputError, match="ascending"):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, tab_stops=[{"pos": 900}, {"pos": 500}])
    with pytest.raises(hwpx_edit.ToolInputError, match="no tab"):
        hwpx_edit.set_tab_attributes("doc.hwpx", 1, width=100)
    with pytest.raises(hwpx_edit.ToolInputError, match="section definition"):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "x"}], before_index=0)
    with pytest.raises(hwpx_edit.ToolInputError, match=r"has \d+ body paragraphs"):
        hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=99, alignment="LEFT")
    # page_break and tab attributes inside paragraph items
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "①\t본문", "tab": {"width": 519, "leader": 0, "type": 1}, "page_break": True}])
    last = hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)["items"][-1]
    assert last["pageBreak"] == "1" and '<hp:tab width="519" leader="0" type="1"/>' in xml(ws, "Contents/section0.xml")
    hwpx_edit.add_endnote_ext("doc.hwpx", 1, [{"text": " 정답", "page_break": False}, {"text": "a\tb", "tab": {"width": 100}}])
    assert '<hp:tab width="100" leader="0" type="1"/>' in xml(ws, "Contents/section0.xml")


def test_header_listing_shows_every_tab_set_font_names_and_char_border_fill(ws):
    items = hwpx_layout.read_layout(ws / "doc.hwpx", "header", max_chars=10**9)["items"]
    assert "0" in {item["id"] for item in items if item["kind"] == "tabPr"}
    char = next(item for item in items if item["kind"] == "charPr")
    assert char["font"] and "border_fill" in char


def test_cells_border_changes_every_cell_and_tab_stops_take_mm(tbl):
    reply = hwpx_edit.format_table_ext("doc.hwpx", 0, merges=[[0, 0, 0, 2]], border={"width": "0.5 mm"}, cells_border={"width": "0.5 mm", "color": "#112233"})
    assert reply["cellsBordered"] == 7 and reply["cellsFormatted"] == 0  # 3x3 with the first row merged: 7 cells
    header = xml(tbl, "Contents/header.xml")
    ids = set(re.findall(r'<hp:tc [^>]*borderFillIDRef="(\d+)"', table_xml(tbl)))
    assert len(ids) == 1
    bf = re.search(rf'<hh:borderFill [^>]*id="{ids.pop()}".*?</hh:borderFill>', header, re.S).group(0)
    assert 'width="0.5 mm" color="#112233"' in bf
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, tab_stops=[{"pos_mm": 40, "type": "LEFT"}])
    assert re.search(r'<hh:tabItem pos="113(38|39)"', xml(tbl, "Contents/header.xml"))
