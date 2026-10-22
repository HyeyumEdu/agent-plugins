"""hwpx_inline: 문단 안 인라인 항목(글·수식·그림·각주·링크·책갈피·체크박스·덧말·글자 겹치기)과 insert_inline_ext, hwpx_runs.split_at. 실행(패키지된 환경 그대로):
venv/bin/python -m pytest toolkit/tests/test_hwpx_inline.py"""
import base64
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.equation.authoring import latex_to_eqedit
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_edit  # noqa: E402
import hwpx_inline  # noqa: E402
import hwpx_layout  # noqa: E402
import hwpx_runs  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
ATOMS = {"tab": "\t", "lineBreak": "\n", "nbSpace": "\u00a0", "fwSpace": "\u3000", "hyphen": "\u00ad"}
UNIT = 7200 / 25.4


def png(width: int, height: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def jpeg(width: int, height: int) -> bytes:  # headers only: the size is all the tool reads
    return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width)
            + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01" + b"\xff\xd9")


def gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00;"


def bmp(width: int, height: int) -> bytes:  # a top-down bitmap: the height is stored negative
    return b"BM" + struct.pack("<IHHI", 54, 0, 0, 54) + struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 24, 0, 0, 0, 0, 0, 0)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("가나다라마바사")
    doc.add_paragraph("두 번째 문단 문단")
    doc.save_to_path(tmp_path / "doc.hwpx")
    return tmp_path


@pytest.fixture()
def tbl(ws):
    """doc.hwpx with a 2x2 table in its third body paragraph; cell (0,1) holds the text '앞 뒤'."""
    doc = HwpxDocument.open(ws / "doc.hwpx")
    doc.add_paragraph("").add_table(2, 2, width=20000, height=2000)
    doc.save_to_path(ws / "doc.hwpx")
    hwpx_edit.format_table_ext("doc.hwpx", 0, cells=[{"row": 0, "col": 1, "paragraphs": [{"text": "앞 뒤"}]}])
    return ws


@pytest.fixture()
def styled(ws):
    """doc.hwpx with the paragraph style 보기 (its own paragraph shape and a bold 9 pt character shape) and the character style 강조."""
    doc = HwpxDocument.open(ws / "doc.hwpx")
    scratch = doc.add_paragraph("스타일 견본")
    doc.styles.apply_paragraph_format(paragraphs=[scratch], alignment="CENTER", indent_left_mm=4)
    char = doc.styles.ensure_run(bold=True, size=9)
    header = doc.oxml.headers[0]
    header.ensure_style("보기", para_pr_id_ref=scratch.para_pr_id_ref, char_pr_id_ref=char)
    header.ensure_style("강조", style_type="CHAR", char_pr_id_ref=char)
    doc.save_to_path(ws / "doc.hwpx")
    doc = HwpxDocument.open(ws / "doc.hwpx")
    style = doc.styles.resolve("보기")
    return ws, str(style.id), str(style.para_pr_id_ref), str(style.char_pr_id_ref)


def part(ws: Path, name: str = "Contents/section0.xml") -> etree._Element:
    return etree.fromstring(zipfile.ZipFile(ws / "doc.hwpx").read(name))


def body(ws: Path, index: int) -> etree._Element:
    return part(ws).findall(HP + "p")[index]


def cell_paragraphs(ws: Path, table: int, row: int, col: int) -> list[etree._Element]:
    cell = next(tc for tc in list(part(ws).iter(HP + "tbl"))[table].iter(HP + "tc")
                if tc.find(HP + "cellAddr").get("rowAddr") == str(row) and tc.find(HP + "cellAddr").get("colAddr") == str(col))
    return cell.find(HP + "subList").findall(HP + "p")


def flat(paragraph: etree._Element) -> list[tuple]:
    """What a paragraph holds with the run boundaries ignored: ('t', text with the special characters back), ('equation', script), ('ctrl', kind), ('pic',) ..."""
    out: list[tuple] = []
    for run in paragraph.findall(HP + "run"):
        for child in run:
            name = etree.QName(child).localname
            if name == "t":
                text = (child.text or "") + "".join(ATOMS[etree.QName(c).localname] + (c.tail or "") for c in child)
                if text:
                    out.append(("t", text))
            elif name == "equation":
                out.append(("equation", child.find(HP + "script").text))
            elif name == "ctrl":
                kind = etree.QName(child[0]).localname
                if kind != "colPr":
                    out.append(("ctrl", kind))
            elif name != "secPr":
                out.append((name,))
    return out


def collapsed(paragraph: etree._Element) -> list[tuple]:
    """flat() with neighbouring texts joined: a position cut splits a text into runs, which says nothing about the paragraph."""
    out: list[tuple] = []
    for item in flat(paragraph):
        if item[0] == "t" and out and out[-1][0] == "t":
            out[-1] = ("t", out[-1][1] + item[1])
        else:
            out.append(item)
    return out


def sha(ws: Path) -> str:
    return hashlib.sha256((ws / "doc.hwpx").read_bytes()).hexdigest()


def char_pr(ws: Path, char_id: str) -> etree._Element:
    return next(c for c in part(ws, "Contents/header.xml").iter(HH + "charPr") if c.get("id") == char_id)


# ---------------------------------------------------------------- hwpx_runs.split_at

@pytest.mark.parametrize("place, left", [(0, ""), (1, "①"), (2, "①\t"), (3, "①\t본"), (4, "①\t본문")])
def test_split_at_cuts_between_characters_and_keeps_tab_and_object_once(ws, place, left):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    paragraph = doc.paragraphs[1]
    paragraph.text = "①\t본문"
    paragraph.add_bookmark("끝표")  # a zero-width object after the text
    gap = hwpx_runs.split_at(paragraph, place)
    front = list(paragraph.element)[:gap]
    assert "".join(run.text for run in paragraph.runs) == "①\t본문"
    assert "".join(run.text for run in paragraph.runs if run.element in front) == left
    assert len(paragraph.element.findall(f".//{HP}tab")) == 1 and len(paragraph.element.findall(f".//{HP}bookmark")) == 1
    # an object standing at the place stays in front of it: the bookmark is behind the last character only
    assert (paragraph.element.find(f".//{HP}bookmark").getparent().getparent() in front) == (place == 4)
    with pytest.raises(ValueError, match="outside"):
        hwpx_runs.split_at(paragraph, 5)


def test_divide_leaves_zero_width_marks_at_the_cut_in_front_and_never_splits_a_unit():
    mark = etree.Element(HP + "markpenEnd")
    tab = etree.Element(HP + "tab")
    tokens = [("text", "ab", 2), ("unit", mark, 0), ("text", "cd", 2), ("unit", tab, 1), ("text", "ef", 2)]
    shown = lambda parts: [value if kind == "text" else etree.QName(value).localname for kind, value, _ in parts]
    assert tuple(map(shown, hwpx_runs._divide(tokens, 2))) == (["ab", "markpenEnd"], ["cd", "tab", "ef"])
    assert tuple(map(shown, hwpx_runs._divide(tokens, 1))) == (["a"], ["b", "markpenEnd", "cd", "tab", "ef"])
    assert tuple(map(shown, hwpx_runs._divide(tokens, 4))) == (["ab", "markpenEnd", "cd"], ["tab", "ef"])
    assert tuple(map(shown, hwpx_runs._divide(tokens, 5))) == (["ab", "markpenEnd", "cd", "tab"], ["ef"])
    unit = [("text", "a", 1), ("unit", mark, 3), ("text", "z", 1)]  # a unit with text of its own cannot be cut inside
    assert tuple(map(shown, hwpx_runs._divide(unit, 2))) == (["a"], ["markpenEnd", "z"])


# ---------------------------------------------------------------- inline items in new paragraphs

def test_text_and_equation_items_keep_the_given_order_and_options(ws):
    result = hwpx_edit.add_paragraphs_ext("doc.hwpx", [
        {"runs": [{"text": "앞 "}, {"equation": "a over b"}, {"text": " 뒤 ", "bold": True}, {"latex": r"\frac{x}{y}", "base_unit": 1200}, {"text": "끝", "char": {"italic": True}}]},
        {"text": "한 줄", "char": {"bold": True}},  # the old shorthand
    ])
    assert result["added"] == 2 and "tableIndex" not in result
    paragraph = body(ws, -2)
    assert flat(paragraph) == [("t", "앞 "), ("equation", "a over b"), ("t", " 뒤 "), ("equation", latex_to_eqedit(r"\frac{x}{y}")), ("t", "끝")]
    equations = list(paragraph.iter(HP + "equation"))
    assert [e.get("baseUnit") for e in equations] == ["1000", "1200"]  # 1000 is Hancom's own
    assert (equations[0].get("version"), equations[0].get("font"), equations[0].get("lineMode")) == ("Equation Version 60", "HYhwpEQ", "CHAR")
    assert equations[0].find(HP + "pos").get("treatAsChar") == "1"
    ids = [run.get("charPrIDRef") for run in paragraph.findall(HP + "run")]
    assert ids[2] != ids[0] and ids[4] != ids[0] and ids[2] != ids[4]  # bold, italic and plain are three shapes
    assert hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)["items"][-1]["text"] == "한 줄"


ALL_KINDS = [
    {"text": "A"}, {"equation": "a over b"}, {"picture": {"image_base64": b64(png(20, 10)), "width_mm": 20}}, {"footnote": "각주 글"},
    {"hyperlink": {"url": "https://example.com", "text": "링크"}}, {"bookmark": "북마크"}, {"check_box": {"caption": "보기", "checked": True}},
    {"ruby": {"base": "漢", "text": "한", "pos_type": "bottom"}}, {"composed": {"text": "가", "circle_type": "shape_circle"}}, {"text": "Z"},
]
ALL_KINDS_FLAT = [
    ("t", "A"), ("equation", "a over b"), ("pic",), ("ctrl", "footNote"), ("ctrl", "fieldBegin"), ("t", "링크"), ("ctrl", "fieldEnd"), ("ctrl", "bookmark"),
    ("checkBtn",), ("dutmal",), ("compose",), ("t", "Z"),
]


def check_all_kinds(ws, paragraph):
    assert flat(paragraph) == ALL_KINDS_FLAT
    pic = paragraph.find(f".//{HP}pic")
    assert (pic.find(HP + "sz").get("width"), pic.find(HP + "sz").get("height")) == (str(round(20 * UNIT)), str(round(10 * UNIT)))
    assert paragraph.find(f".//{HP}footNote/{HP}subList").xpath("string()").endswith("각주 글")
    assert paragraph.find(f".//{HP}checkBtn").get("value") == "CHECKED" and paragraph.find(f".//{HP}dutmal").get("posType") == "BOTTOM"
    assert paragraph.find(f".//{HP}compose").get("circleType") == "SHAPE_CIRCLE" and paragraph.find(f".//{HP}bookmark").get("name") == "북마크"
    assert any(name.startswith("BinData/") and name.endswith(".png") for name in zipfile.ZipFile(ws / "doc.hwpx").namelist())


def test_every_inline_kind_in_new_paragraph_and_in_insert(ws):
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": ALL_KINDS}])
    check_all_kinds(ws, body(ws, -1))
    # the same items put into an empty paragraph by insert_inline_ext come out the same
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": ""}])
    index = len(part(ws).findall(HP + "p")) - 1
    result = hwpx_inline.insert_inline_ext("doc.hwpx", ALL_KINDS, position=0, paragraph_index=index)
    assert result["inserted"] == len(ALL_KINDS) and result["paragraphLength"] == len("A링크Z")  # a hyperlink's display text counts, objects do not
    check_all_kinds(ws, body(ws, -1))


def test_special_true_writes_tab_break_and_special_space_elements(ws):
    text = "a\tb\nc\u00a0d\u3000e\u00adf"
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": [{"text": text, "special": True}, {"text": "x\ty\nz\u00a0w"}]}, {"text": "q\tr", "tab": {"width": 100}}])
    first = body(ws, -2).find(HP + "run").find(HP + "t")
    assert [etree.QName(c).localname for c in first] == ["tab", "lineBreak", "nbSpace", "fwSpace", "hyphen"]
    assert flat(body(ws, -2))[0] == ("t", text)
    plain = body(ws, -2).findall(HP + "run")[1].find(HP + "t")  # special=false (the default) is what it was: only the library's own tab handling
    assert [etree.QName(c).localname for c in plain] == ["tab"] and plain.text == "x"
    assert body(ws, -1).find(f".//{HP}tab").get("width") == "100"
    # every one of those characters is one position for insert_inline_ext
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": [{"text": text, "special": True}]}])
    index = len(part(ws).findall(HP + "p")) - 1
    assert hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "|"}], position=2, paragraph_index=index)["paragraphLength"] == 12
    assert collapsed(body(ws, -1)) == [("t", "a\t|b\nc\u00a0d\u3000e\u00adf")] and len(list(body(ws, -1).iter(HP + "tab"))) == 1


def test_footnotes_are_renumbered_in_document_order_and_refused_inside_notes(ws):
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": [{"text": "셋째 "}, {"footnote": "c"}]}])
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"footnote": "b"}], anchor_text="문단", occurrence=2, paragraph_index=1)
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"footnote": "a"}], position=0, paragraph_index=0)
    section = part(ws)
    notes = list(section.iter(HP + "footNote"))
    assert [n.get("number") for n in notes] == ["1", "2", "3"] and [n.xpath("string()")[-1] for n in notes] == ["a", "b", "c"]
    assert [a.get("num") for a in section.iter(HP + "autoNum") if a.get("numType") == "FOOTNOTE"] == ["1", "2", "3"]
    before = sha(ws)
    with pytest.raises(hwpx_inline.ToolInputError, match="footnote cannot be placed inside an endnote"):
        hwpx_edit.add_endnote_ext("doc.hwpx", 0, [{"text": "정답"}, {"runs": [{"text": "x"}, {"footnote": "no"}]}])
    assert sha(ws) == before


def test_endnote_paragraphs_take_inline_items_and_keep_the_number_in_front(ws):
    hwpx_edit.add_endnote_ext("doc.hwpx", 0, [
        {"runs": [{"text": " 정답 "}, {"equation": "x"}, {"text": "로 푼다", "bold": True}]},
        {"runs": [{"equation": "y"}, {"hyperlink": {"url": "https://a.b", "text": "링크"}}]},
        {"runs": [{"bookmark": "끝"}]},
    ])
    first, second, third = part(ws).find(f".//{HP}endNote/{HP}subList").findall(HP + "p")
    assert flat(first) == [("ctrl", "autoNum"), ("t", " 정답 "), ("equation", "x"), ("t", "로 푼다")]
    assert first.find(HP + "run").find(HP + "t").text == " 정답 "  # the first text sits in the run that holds the number, as it did before
    assert flat(second) == [("equation", "y"), ("ctrl", "fieldBegin"), ("t", "링크"), ("ctrl", "fieldEnd")]
    assert flat(third) == [("ctrl", "bookmark")]
    notes = hwpx_layout.read_layout(ws / "doc.hwpx", "notes", max_chars=10**9)["items"]
    assert len(notes) == 1 and len(notes[0]["paragraphs"]) == 3


def test_hyperlink_keeps_its_own_look_and_other_items_take_the_style_char(styled):
    ws, style_id, _, style_char = styled
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"style": "보기", "runs": [{"hyperlink": {"url": "https://a.b", "text": "L"}}, {"bookmark": "m"}, {"equation": "x"}]}])
    runs = body(ws, -1).findall(HP + "run")
    link = next(run for run in runs if run.find(HP + "t") is not None and run.find(HP + "t").text == "L")
    assert link.get("charPrIDRef") != style_char  # blue underlined link look
    assert next(run for run in runs if run.find(f"{HP}ctrl/{HP}bookmark") is not None).get("charPrIDRef") == style_char
    assert next(run for run in runs if run.find(HP + "equation") is not None).get("charPrIDRef") == style_char


# ---------------------------------------------------------------- picture checks

def test_picture_sizes_follow_the_image_header_and_formats_are_checked(ws):
    cases = [(png(40, 20), "width_mm", 20, ".png"), (jpeg(30, 60), "height_mm", 20, ".jpg"), (gif(10, 40), "width_mm", 5, ".gif"), (bmp(8, 4), "height_mm", 3, ".bmp")]
    for data, key, mm, _ in cases:
        hwpx_inline.insert_inline_ext("doc.hwpx", [{"picture": {"image_base64": b64(data), key: mm}}], position=0, paragraph_index=1)
    pics = list(body(ws, 1).iter(HP + "pic"))
    assert len(pics) == 4
    expected = [(20, 10), (10, 20), (5, 20), (6, 3)]  # mm: the other side follows the pixel proportions (40x20, 30x60, 10x40, 8x4)
    for pic, (width, height) in zip(pics, expected):  # an object already at position 0 stays in front, so they stand in the order inserted
        assert (int(pic.find(HP + "sz").get("width")), int(pic.find(HP + "sz").get("height"))) == (round(width * UNIT), round(height * UNIT))
        pos = pic.find(HP + "pos")
        assert (pic.get("textWrap"), pos.get("treatAsChar"), pos.get("horzRelTo"), pos.get("vertRelTo")) == ("TOP_AND_BOTTOM", "1", "PARA", "PARA")
    names = zipfile.ZipFile(ws / "doc.hwpx").namelist()
    assert {Path(n).suffix for n in names if n.startswith("BinData/")} == {suffix for *_, suffix in cases}


def test_picture_from_a_workspace_file_and_refusals_that_do_not_name_paths(ws):
    (ws / "fig.png").write_bytes(png(10, 10))
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"picture": {"path": "fig.png", "width_mm": 10, "height_mm": 5}}], position=0, paragraph_index=1)
    assert len(list(body(ws, 1).iter(HP + "pic"))) == 1
    before = sha(ws)
    outside = ws.parent / "outside.png"
    outside.write_bytes(png(2, 2))
    bad_pictures = [
        ({"path": str(outside), "width_mm": 5}, "inside the workspace"), ({"path": "nope.png", "width_mm": 5}, "inside the workspace"),
        ({"path": ".", "width_mm": 5}, "inside the workspace"), ({"image_base64": "@@@", "width_mm": 5}, "base64"),
        ({"image_base64": b64(b"plain text, not an image"), "width_mm": 5}, "PNG, JPEG, BMP or GIF"),
        ({"image_base64": b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4), "width_mm": 5}, "cannot be read"),
        ({"image_base64": b64(png(4, 4))}, "width_mm and/or height_mm"), ({"image_base64": b64(png(4, 4)), "width_mm": 0}, "positive"),
        ({"image_base64": b64(png(4, 4)), "width_mm": True}, "positive"), ({"path": "fig.png", "image_base64": b64(png(4, 4)), "width_mm": 5}, "exactly one of path or image_base64"),
        ({"width_mm": 5}, "exactly one of path or image_base64"), ({"image_base64": b64(png(4, 4)), "width_mm": 5, "align": "LEFT"}, "unknown"),
        ({"image_base64": b64(png(1, 100000)), "width_mm": 0.001}, "rounds to 0"),
    ]
    for spec, message in bad_pictures:
        with pytest.raises(hwpx_inline.ToolInputError, match=message) as error:
            hwpx_inline.insert_inline_ext("doc.hwpx", [{"picture": spec}], position=0, paragraph_index=1)
        assert "nope" not in str(error.value) and str(ws) not in str(error.value)
    assert sha(ws) == before
    # a header that cannot be read is fine when both sizes are given
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"picture": {"image_base64": b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4), "width_mm": 5, "height_mm": 5}}], position=0, paragraph_index=1)


# ---------------------------------------------------------------- insert_inline_ext

def test_insert_by_position_and_by_anchor_text(ws):
    result = hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "[1]"}], position=3, paragraph_index=0)
    assert (result["position"], result["paragraphLength"]) == (3, 10)
    assert hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)["items"][0]["text"] == "가나다[1]라마바사"
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "x"}], anchor_text="문단", paragraph_index=1)  # after the first match
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "y"}], anchor_text="문단", occurrence=2, paragraph_index=1, before=True)
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "z"}], anchor_text="문단", occurrence=2, paragraph_index=1)
    assert flat(body(ws, 1)) == [("t", "두 번째 문단"), ("equation", "x"), ("t", " "), ("equation", "y"), ("t", "문단"), ("equation", "z")]
    assert hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "#"}], position=0, paragraph_index=1)["paragraphLength"] == 11


def test_object_at_the_place_stays_in_front_of_the_new_items(ws):
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"bookmark": "첫"}], position=3, paragraph_index=0)
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "x"}, {"bookmark": "둘"}], position=3, paragraph_index=0)
    assert flat(body(ws, 0)) == [("t", "가나다"), ("ctrl", "bookmark"), ("equation", "x"), ("ctrl", "bookmark"), ("t", "라마바사")]
    names = [b.get("name") for b in body(ws, 0).iter(HP + "bookmark")]
    assert names == ["첫", "둘"]
    # position 0 of the first paragraph: the section definition stays in front
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "머리"}], position=0, paragraph_index=0)
    first = body(ws, 0)
    assert first.find(HP + "run").find(HP + "secPr") is not None and len(list(first.iter(HP + "secPr"))) == 1
    assert flat(first)[0] == ("t", "머리")


def test_run_holding_an_endnote_and_a_tab_is_cut_without_copying_them(ws):
    hwpx_edit.add_endnote_ext("doc.hwpx", 1, [{"text": "정답"}])
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "[탭]", "special": True}], position=3, paragraph_index=1)
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "\t", "special": True}], position=0, paragraph_index=1)
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "x"}], position=len("\t두 번[탭]째 문단 문단"), paragraph_index=1)
    paragraph = body(ws, 1)
    assert collapsed(paragraph) == [("t", "\t두 번[탭]째 문단 문단"), ("ctrl", "endNote"), ("equation", "x")]  # the endnote is once, and behind the text; the new object after it
    assert len(list(paragraph.iter(HP + "tab"))) == 1
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "중"}], position=5, paragraph_index=1)
    assert len(list(body(ws, 1).iter(HP + "endNote"))) == 1


def test_insert_into_a_table_cell_paragraph(tbl):
    result = hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "a over b"}, {"text": "·"}], position=1, table_index=0, row=0, col=1)
    assert result["position"] == 1
    assert flat(cell_paragraphs(tbl, 0, 0, 1)[0]) == [("t", "앞"), ("equation", "a over b"), ("t", "·"), ("t", " 뒤")]
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "끝"}], anchor_text="뒤", table_index=0, row=0, col=1, cell_paragraph_index=0)
    assert flat(cell_paragraphs(tbl, 0, 0, 1)[0])[-1] == ("t", "끝")
    # the cell character shape of the neighbouring text is inherited by what has no options
    runs = cell_paragraphs(tbl, 0, 0, 1)[0].findall(HP + "run")
    assert len({run.get("charPrIDRef") for run in runs}) == 1
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "빈칸"}], position=0, table_index=0, row=1, col=1)
    assert flat(cell_paragraphs(tbl, 0, 1, 1)[0]) == [("t", "빈칸")]


def test_insert_inline_refusals_and_dry_run_leave_the_file_alone(ws, tbl):
    before = sha(ws)
    one = {"text": "x"}
    bad = [
        (dict(position=99, paragraph_index=0), "out of range"), (dict(position=-1, paragraph_index=0), "out of range"),
        (dict(anchor_text="없는글", paragraph_index=0), "not found"), (dict(anchor_text="문단", occurrence=3, paragraph_index=1), "occurs 2 time"),
        (dict(anchor_text="문단", occurrence=0, paragraph_index=1), "occurrence"), (dict(anchor_text="", paragraph_index=1), "anchor_text"),
        (dict(position=1, anchor_text="문", paragraph_index=1), "exactly one of position or anchor_text"), (dict(paragraph_index=1), "exactly one of position or anchor_text"),
        (dict(position=1), "give exactly one paragraph address group"), (dict(position=1, paragraph_index=1, table_index=0, row=0, col=0), "give exactly one paragraph address group"),
        (dict(position=1, paragraph_index=1, row=0), "do not go with paragraph_index"), (dict(position=1, table_index=0, row=0), "needs row and col"),
        (dict(position=1, paragraph_index=99), "invalid paragraph_index"), (dict(position=1, table_index=5, row=0, col=0), "invalid table_index"),
        (dict(position=1, table_index=0, row=9, col=9), "no cell"), (dict(position=1, table_index=0, row=0, col=1, cell_paragraph_index=3), "invalid cell_paragraph_index"),
        (dict(position=1, paragraph_index=1, items=[]), "must not be empty"),
    ]
    for arguments, message in bad:
        with pytest.raises(hwpx_inline.ToolInputError, match=message):
            hwpx_inline.insert_inline_ext("doc.hwpx", **{"items": [one], **arguments})
    with pytest.raises(hwpx_inline.ToolInputError, match="revision mismatch"):
        hwpx_inline.insert_inline_ext("doc.hwpx", [one], position=1, paragraph_index=1, expected_revision="sha256:" + "0" * 64)
    result = hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "x"}, {"picture": {"image_base64": b64(png(4, 4)), "width_mm": 5}}, {"footnote": "n"}], position=1, paragraph_index=1, dry_run=True)
    assert result["dryRun"] is True and sha(ws) == before
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": [{"text": "a"}, {"equation": "x"}]}], dry_run=True)
    hwpx_edit.format_table_ext("doc.hwpx", 0, cells=[{"row": 0, "col": 0, "paragraphs": [{"runs": [{"equation": "x"}]}]}], dry_run=True)
    assert sha(ws) == before


BAD_ITEMS = [
    [{}], [{"text": "a", "equation": "b"}], [{"equation": "  "}], [{"text": "a", "special": 1}], [{"equation": "a", "special": True}], [{"text": "a", "base_unit": 5}],
    [{"equation": "a", "base_unit": 0}], [{"hyperlink": {"url": "u"}}], [{"hyperlink": {"url": "", "text": "t"}}], [{"ruby": {"base": "a", "text": "b", "pos_type": "MIDDLE"}}],
    [{"ruby": {"base": "", "text": "b"}}], [{"composed": {"text": "a", "circle_type": "NOPE"}}], [{"composed": {"text": ""}}], [{"check_box": {"caption": "c", "checked": "yes"}}],
    [{"bookmark": ""}], [{"text": "a", "bogus": 1}], [{"text": "a", "char": {"bogus": 1}}], [{"text": "a", "char": "bold"}], ["text"], [{"footnote": 5}], [{"picture": "x.png"}],
]


@pytest.mark.parametrize("bad", BAD_ITEMS)
def test_malformed_items_are_refused_in_every_place_they_are_used(tbl, bad):
    before = sha(tbl)
    with pytest.raises(hwpx_inline.ToolInputError):
        hwpx_inline.insert_inline_ext("doc.hwpx", bad, position=0, paragraph_index=1)
    with pytest.raises(hwpx_inline.ToolInputError):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": bad}])
    with pytest.raises(hwpx_inline.ToolInputError):
        hwpx_edit.add_endnote_ext("doc.hwpx", 0, [{"runs": bad}])
    with pytest.raises(hwpx_inline.ToolInputError):
        hwpx_edit.format_table_ext("doc.hwpx", 0, cells=[{"row": 0, "col": 0, "paragraphs": [{"runs": bad}]}])
    assert sha(tbl) == before


def test_latex_that_cannot_be_converted_is_refused(ws):
    before = sha(ws)
    with pytest.raises(hwpx_inline.ToolInputError, match="LaTeX cannot be converted"):
        hwpx_inline.insert_inline_ext("doc.hwpx", [{"latex": r"\nosuchcommand{x}"}], position=0, paragraph_index=1)
    with pytest.raises(hwpx_inline.ToolInputError, match="runs\\[0\\].latex"):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": [{"latex": r"\nosuchcommand{x}"}]}])
    assert sha(ws) == before


# ---------------------------------------------------------------- style and table keys of paragraph items

def test_style_item_takes_the_styles_shapes_and_layers_char_options_on_its_char(styled):
    ws, style_id, style_para, style_char = styled
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [
        {"style": "보기", "runs": [{"text": "a"}, {"text": "b", "italic": True}]},
        {"style": style_id, "para_pr_id": "0", "text": "c"},  # the id works as well; an explicit paragraph shape wins over the style's
        {"style": "Normal", "text": "d", "format": {"alignment": "RIGHT"}},
    ])
    first, second, third = part(ws).findall(HP + "p")[-3:]
    assert (first.get("styleIDRef"), first.get("paraPrIDRef")) == (style_id, style_para)
    plain, layered = first.findall(HP + "run")
    assert plain.get("charPrIDRef") == style_char and layered.get("charPrIDRef") not in (style_char, "0")
    shape = char_pr(ws, layered.get("charPrIDRef"))
    assert shape.find(HH + "italic") is not None and shape.find(HH + "bold") is not None  # italic added to the style's bold
    assert (second.get("styleIDRef"), second.get("paraPrIDRef")) == (style_id, "0")
    assert third.get("styleIDRef") == "0" and third.get("paraPrIDRef") not in ("0", style_para)  # format makes a copy of the style's shape
    # the same keys in an endnote paragraph and in a table cell
    hwpx_edit.add_endnote_ext("doc.hwpx", 0, [{"style": "보기", "text": "정답"}])
    note = part(ws).find(f".//{HP}endNote/{HP}subList/{HP}p")
    assert (note.get("styleIDRef"), note.get("paraPrIDRef")) == (style_id, style_para)


def test_style_item_refusals(styled):
    ws, style_id, *_ = styled
    before = sha(ws)
    for spec, message in (({"style": "보기", "style_id": "0"}, "style or style_id"), ({"style": "없는 스타일"}, "not a style of this file"),
                          ({"style": "강조"}, "character style"), ({"style": True}, "style name or id"), ({"style": ""}, "style name or id"), ({"style": 999}, "not a style")):
        with pytest.raises(hwpx_inline.ToolInputError, match=message) as error:
            hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "x", **spec}])
        if "not a style" in message:
            assert "보기" in str(error.value)  # the styles the file has are listed
    assert sha(ws) == before


def test_table_item_gives_table_index_in_document_order_and_continues_in_format_table_ext(tbl):
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "표 앞 글", "table": {"rows": 1, "cols": 2, "width": 10000, "height": 1000}}], before_index=1)
    result = hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"table": {"rows": 3, "cols": 1}}, {"text": "끝"}], before_index=1)
    assert result["tableIndex"] == [0] and result["firstParagraphIndex"] == 1  # in front of the earlier new table and of the file's own
    tables = list(part(tbl).iter(HP + "tbl"))
    assert [(t.get("rowCnt"), t.get("colCnt")) for t in tables] == [("3", "1"), ("1", "2"), ("2", "2")]
    assert flat(body(tbl, 3)) == [("t", "표 앞 글"), ("tbl",)] and flat(body(tbl, 1)) == [("tbl",)] and flat(body(tbl, 2)) == [("t", "끝")]
    hwpx_edit.format_table_ext("doc.hwpx", result["tableIndex"][0], cells=[{"row": 2, "col": 0, "paragraphs": [{"text": "셋째 줄"}]}])
    assert flat(cell_paragraphs(tbl, 0, 2, 0)[0]) == [("t", "셋째 줄")]
    for bad, message in (({"rows": 0, "cols": 1}, "positive"), ({"cols": 1}, "needs"), ({"rows": 1, "cols": 1, "bogus": 1}, "unknown"), ("2x2", "object"),
                         ({"rows": 1, "cols": 1, "border_fill_id": True}, "borderFill"), ({"rows": 1, "cols": 1, "width": 2.5}, "whole")):
        with pytest.raises(hwpx_inline.ToolInputError, match=message):
            hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"table": bad}])
    with pytest.raises(hwpx_inline.ToolInputError, match="give exactly one of text or runs"):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "a", "runs": [{"text": "b"}]}])
    with pytest.raises(hwpx_inline.ToolInputError, match="give exactly one of text or runs"):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"style_id": "0"}])
    with pytest.raises(hwpx_inline.ToolInputError, match="border"):
        hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"table": {"rows": 1, "cols": 1, "border_fill_id": "999"}}])


def test_table_item_inside_a_cell_and_not_inside_an_endnote(tbl):
    result = hwpx_edit.format_table_ext("doc.hwpx", 0, cells=[{"row": 1, "col": 0, "paragraphs": [{"table": {"rows": 2, "cols": 2, "width": 4000}}]}])
    assert result["tableIndex"] == [1]  # a nested table counts right after its parent
    hwpx_edit.format_table_ext("doc.hwpx", result["tableIndex"][0], cells=[{"row": 1, "col": 1, "paragraphs": [{"runs": [{"text": "안"}, {"equation": "x"}]}]}])
    nested = cell_paragraphs(tbl, 1, 1, 1)[0]
    assert flat(nested) == [("t", "안"), ("equation", "x")]
    with pytest.raises(hwpx_inline.ToolInputError, match="endnote paragraph"):
        hwpx_edit.add_endnote_ext("doc.hwpx", 0, [{"text": "a", "table": {"rows": 1, "cols": 1}}])


def test_cell_paragraphs_take_the_same_items_and_keep_old_forms(tbl):
    hwpx_edit.format_table_ext("doc.hwpx", 0, cells=[{"row": 1, "col": 0, "paragraphs": [
        {"runs": [{"equation": "x"}, {"text": "탭\t뒤", "special": True}, {"footnote": "칸 각주"}]},
        {"runs": [{"text": "정답 ", "bold": True}, {"text": "③"}], "format": {"alignment": "CENTER"}},
        {"text": "", "char": {"font_size": 3}},
    ]}])
    first, second, third = cell_paragraphs(tbl, 0, 1, 0)
    assert flat(first) == [("equation", "x"), ("t", "탭\t뒤"), ("ctrl", "footNote")] and len(first.findall(HP + "run")) == 3  # no blank run left in front
    assert flat(second) == [("t", "정답 "), ("t", "③")] and len(third.findall(HP + "run")) == 1
    assert [n.get("number") for n in part(tbl).iter(HP + "footNote")] == ["1"]
    tables = hwpx_layout.read_layout(tbl / "doc.hwpx", "tables", max_chars=10**9)["items"][0]["cells"]
    cell = next(c for c in tables if (c["r"], c["c"]) == (1, 0))
    assert [shape["align"] for shape in (hwpx_layout.read_layout(tbl / "doc.hwpx", "tables", max_chars=10**9)["shapes"][p["shape"]] for p in cell["paragraphs"])][1] == "CENTER"


def test_replace_anchor_links_existing_text_and_turns_markers_into_objects(ws):
    from hwpx_inline import insert_inline_ext
    base = hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)
    index = next(i for i, item in enumerate(base["items"]) if item["text"])
    text = base["items"][index]["text"]
    word = text[2:5]
    insert_inline_ext("doc.hwpx", [{"hyperlink": {"url": "https://example.com", "text": word}}], anchor_text=word, replace_anchor=True, paragraph_index=index)
    after = hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)["items"][index]
    assert after["text"] == text  # same words, now a link
    objects = hwpx_layout.read_layout(ws / "doc.hwpx", "objects", max_chars=10**9)["items"]
    assert [(o["kind"], o.get("url")) for o in objects if o["kind"] == "hyperlink"] == [("hyperlink", "https://example.com")]
    # a marker becomes an equation and disappears from the text
    insert_inline_ext("doc.hwpx", [{"text": "(수식)"}], position=0, paragraph_index=index)
    insert_inline_ext("doc.hwpx", [{"equation": "x^{2}"}], anchor_text="(수식)", replace_anchor=True, paragraph_index=index)
    final = hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)["items"][index]
    assert "(수식)" not in final["text"] and final["text"] == text
    assert any(o["kind"] == "equation" and o["at"] == 0 for o in hwpx_layout.read_layout(ws / "doc.hwpx", "objects", max_chars=10**9)["items"])
    with pytest.raises(hwpx_edit.ToolInputError, match="replace_anchor needs anchor_text"):
        insert_inline_ext("doc.hwpx", [{"text": "x"}], position=0, replace_anchor=True, paragraph_index=index)


def test_insert_inline_reaches_notes_headers_and_footers(ws):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    doc.notes.add_endnote("해설 글", paragraph=doc.paragraphs[1])
    doc.page.set_header(text="머리말 글")
    doc.save_to_path(ws / "doc.hwpx")
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"equation": "x^{2}"}], anchor_text="해설", endnote_number=1)
    hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "[끼움]"}], position=0, header_index=0)
    objects = hwpx_layout.read_layout(ws / "doc.hwpx", "objects", max_chars=10**9)["items"]
    assert any(o["kind"] == "equation" and o.get("endnote_number") == 1 and o["at"] == 2 for o in objects)
    notes = hwpx_layout.read_layout(ws / "doc.hwpx", "notes", max_chars=10**9)["items"][0]
    assert notes["kind"] == "endnote" and "해설" in "".join(p["text"] for p in notes["paragraphs"])
    import hwpx_locate
    assert hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(HwpxDocument.open(ws / "doc.hwpx"), header_index=0)) == "[끼움]머리말 글"
    with pytest.raises(hwpx_inline.ToolInputError, match="a footnote cannot be placed inside"):
        hwpx_inline.insert_inline_ext("doc.hwpx", [{"footnote": "n"}], position=0, endnote_number=1)
    with pytest.raises(hwpx_inline.ToolInputError, match="invalid endnote_number"):
        hwpx_inline.insert_inline_ext("doc.hwpx", [{"text": "x"}], position=0, endnote_number=5)
