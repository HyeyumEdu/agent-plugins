"""hwpx_styles의 쓰기 도구(스타일 적용·정의, 목록 서식)와 resolve_style. 실행(패키지된 환경 그대로):
venv/bin/python -m pytest toolkit/tests/test_hwpx_styles.py"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_layout  # noqa: E402
import hwpx_styles  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """doc.hwpx: 본문 문단 4개, 스타일 '보기'(문단 0의 paraPr = 양쪽 정렬 160 %, charPr = 14pt 굵게)."""
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    first = doc.paragraphs[0]
    first.add_run("가나다라마바사")
    doc.styles.apply_paragraph_format(paragraphs=[first], alignment="JUSTIFY", line_spacing_percent=160, indent_left_mm=3.0)
    for text in ("두 번째 문단", "세 번째 문단", "네 번째 문단"):
        doc.add_paragraph(text)
    big = doc.styles.ensure_run(size=14, bold=True)
    doc.oxml.headers[0].ensure_style("보기", para_pr_id_ref=first.para_pr_id_ref, char_pr_id_ref=big, next_style_id_ref="0", lang_id=1042)
    doc.save_to_path(tmp_path / "doc.hwpx")
    return tmp_path


def parts(ws: Path) -> tuple[etree._Element, etree._Element]:
    z = zipfile.ZipFile(ws / "doc.hwpx")
    return etree.fromstring(z.read("Contents/header.xml")), etree.fromstring(z.read("Contents/section0.xml"))


def style_of(ws: Path, name: str) -> dict:
    header, _ = parts(ws)
    return dict(next(s for s in header.iter(f"{HH}style") if s.get("name") == name).attrib)


def body(ws: Path) -> list[dict]:
    """본문 문단별 styleIDRef, paraPrIDRef와 각 run의 charPrIDRef."""
    _, section = parts(ws)
    return [{"style": p.get("styleIDRef"), "para": p.get("paraPrIDRef"), "chars": [r.get("charPrIDRef") for r in p.findall(f"{HP}run")]}
            for p in section.findall(f"{HP}p")]


def char_pr(ws: Path, char_id: str) -> etree._Element:
    header, _ = parts(ws)
    return next(c for c in header.iter(f"{HH}charPr") if c.get("id") == char_id)


def digest(ws: Path) -> str:
    return hashlib.sha256((ws / "doc.hwpx").read_bytes()).hexdigest()


# --- resolve_style -------------------------------------------------------------------------------------------------

def test_resolve_style_by_name_english_name_and_id(ws):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    assert hwpx_styles.resolve_style(doc, "바탕글") == ("0", "0", "0", "PARA")
    assert hwpx_styles.resolve_style(doc, "normal") == ("0", "0", "0", "PARA")
    assert hwpx_styles.resolve_style(doc, "12") == ("12", "0", "1", "CHAR")
    style_id, para, char, kind = hwpx_styles.resolve_style(doc, "보기")
    assert (kind, style_id) == ("PARA", "23") and para == doc.paragraphs[0].para_pr_id_ref and char != "0"
    assert all(isinstance(value, str) for value in (style_id, para, char, kind))


def test_resolve_style_unknown_lists_the_names(ws):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    with pytest.raises(ToolInputError, match=r"'없는'.*바탕글 \(id 0\).*보기 \(id 23\)"):
        hwpx_styles.resolve_style(doc, "없는")
    with pytest.raises(ToolInputError, match="style must be"):
        hwpx_styles.resolve_style(doc, "  ")


# --- apply_style_ext -----------------------------------------------------------------------------------------------

def test_paragraph_style_sets_style_and_paragraph_shape_keeps_runs(ws):
    before = body(ws)
    out = hwpx_styles.apply_style_ext("doc.hwpx", [1, 2], "보기")
    assert (out["styled"], out["styleIDRef"], out["kind"], out["charPrIDRef"]) == (2, "23", "PARA", None)
    after = body(ws)
    assert [(p["style"], p["para"]) for p in after[1:3]] == [("23", style_of(ws, "보기")["paraPrIDRef"])] * 2
    assert [p["chars"] for p in after] == [p["chars"] for p in before]  # apply_char defaults to keep
    assert after[3] == before[3]
    shape = hwpx_layout.read_layout(ws / "doc.hwpx", "body")
    item = shape["items"][1]
    assert shape["shapes"][item["paraPr"]]["align"] == "JUSTIFY" and shape["shapes"][item["paraPr"]]["lineSpacing"] == ["PERCENT", "160"]


@pytest.mark.parametrize("spec", ["보기", "23"])
def test_style_by_id_matches_style_by_name(ws, spec):
    hwpx_styles.apply_style_ext("doc.hwpx", [3], spec)
    assert body(ws)[3]["style"] == "23"
    hwpx_styles.apply_style_ext("doc.hwpx", [3], "Normal")  # English name
    assert (body(ws)[3]["style"], body(ws)[3]["para"]) == ("0", "0")


def test_keep_leaves_paragraph_shape_and_style_combinations(ws):
    original = body(ws)[1]
    hwpx_styles.apply_style_ext("doc.hwpx", [1], "보기", apply_para="keep")
    keep = body(ws)[1]
    assert (keep["style"], keep["para"], keep["chars"]) == ("23", original["para"], original["chars"])
    big = style_of(ws, "보기")["charPrIDRef"]
    out = hwpx_styles.apply_style_ext("doc.hwpx", [1, 2], "보기", apply_para="keep", apply_char="style")
    assert out["paraPrIDRef"] is None and out["charPrIDRef"] == big
    assert (body(ws)[1]["para"], body(ws)[1]["chars"]) == (original["para"], [big] * len(original["chars"]))
    hwpx_styles.apply_style_ext("doc.hwpx", [2], "보기", apply_char="style")
    both = body(ws)[2]
    assert (both["style"], both["para"], set(both["chars"])) == ("23", style_of(ws, "보기")["paraPrIDRef"], {big})
    assert char_pr(ws, big).get("height") == "1400"


def test_character_style_sets_char_shape_only(ws):
    original = body(ws)[1]
    hwpx_styles.define_style_ext("doc.hwpx", "강조", kind="CHAR", char_pr_id=style_of(ws, "보기")["charPrIDRef"])
    with pytest.raises(ToolInputError, match="apply_char='style'"):
        hwpx_styles.apply_style_ext("doc.hwpx", [1], "강조")
    assert body(ws)[1] == original
    out = hwpx_styles.apply_style_ext("doc.hwpx", [1], "강조", apply_char="style", apply_para="style")  # apply_para is ignored
    assert (out["kind"], out["paraPrIDRef"]) == ("CHAR", None)
    got = body(ws)[1]
    assert got["style"] == original["style"] and got["para"] == original["para"]
    assert set(got["chars"]) == {style_of(ws, "강조")["charPrIDRef"]}


def test_apply_style_refusals(ws):
    with pytest.raises(ToolInputError, match=r"'없는 스타일'.*보기 \(id 23\)"):
        hwpx_styles.apply_style_ext("doc.hwpx", [0], "없는 스타일")
    with pytest.raises(ToolInputError, match=r"invalid paragraph index \[4, -1\] \(the file has 4"):
        hwpx_styles.apply_style_ext("doc.hwpx", [0, 4, -1], "보기")
    with pytest.raises(ToolInputError, match="at least one"):
        hwpx_styles.apply_style_ext("doc.hwpx", [], "보기")
    with pytest.raises(ToolInputError, match="apply_para must be"):
        hwpx_styles.apply_style_ext("doc.hwpx", [0], "보기", apply_para="both")


def test_apply_style_dry_run_and_stale_revision_leave_file_alone(ws):
    before = digest(ws)
    out = hwpx_styles.apply_style_ext("doc.hwpx", [1], "보기", dry_run=True)
    assert out["dryRun"] is True and out["styled"] == 1
    with pytest.raises(ToolInputError, match="revision mismatch"):
        hwpx_styles.apply_style_ext("doc.hwpx", [1], "보기", expected_revision="sha256:" + "0" * 64)
    assert digest(ws) == before


# --- define_style_ext ----------------------------------------------------------------------------------------------

def test_define_style_from_ids_creates_a_style(ws):
    big = style_of(ws, "보기")["charPrIDRef"]
    out = hwpx_styles.define_style_ext("doc.hwpx", "문제", para_pr_id="3", char_pr_id=big, eng_name="Question")
    assert out["styleIDRef"] == "24" and out["created"] is True and isinstance(out["styleIDRef"], str)
    got = style_of(ws, "문제")
    assert (got["type"], got["engName"], got["paraPrIDRef"], got["charPrIDRef"]) == ("PARA", "Question", "3", big)
    assert got["nextStyleIDRef"] == "24" and got["langID"] == "1042"  # a new paragraph style follows itself, as Hancom writes it
    header, _ = parts(ws)
    assert header.find(f".//{HH}styles").get("itemCnt") == "25"
    listed = hwpx_layout.read_layout(ws / "doc.hwpx", "header", kind="style")["items"]
    assert {"kind": "style", "id": "24", "name": "문제", "paraPr": "3", "charPr": big, "next": "24", "type": "PARA"} == listed[-1]
    hwpx_styles.apply_style_ext("doc.hwpx", [2], "Question")
    assert body(ws)[2]["style"] == "24" and body(ws)[2]["para"] == "3"


def test_define_style_from_paragraph_takes_para_pr_and_first_text_run(ws):
    first = body(ws)[0]
    assert len(first["chars"]) > 1  # the secPr run comes first; the style takes the shape of the run that holds text
    out = hwpx_styles.define_style_ext("doc.hwpx", "해설", from_paragraph_index=0)
    got = style_of(ws, "해설")
    assert got["paraPrIDRef"] == first["para"] and got["paraPrIDRef"] != "0"
    assert out["paraPrIDRef"] == got["paraPrIDRef"] and out["charPrIDRef"] == got["charPrIDRef"] == first["chars"][-1]


def test_define_style_updates_only_what_is_given(ws):
    before = style_of(ws, "보기")
    out = hwpx_styles.define_style_ext("doc.hwpx", "보기", para_pr_id="3")
    assert out["created"] is False and out["styleIDRef"] == before["id"]
    after = style_of(ws, "보기")
    assert after["paraPrIDRef"] == "3" and {k: v for k, v in after.items() if k != "paraPrIDRef"} == {k: v for k, v in before.items() if k != "paraPrIDRef"}
    header, _ = parts(ws)
    assert header.find(f".//{HH}styles").get("itemCnt") == "24"
    hwpx_styles.define_style_ext("doc.hwpx", "보기", kind="PARA", eng_name="Boxed")  # same kind is fine
    assert style_of(ws, "보기")["engName"] == "Boxed"


def test_define_character_style(ws):
    big = style_of(ws, "보기")["charPrIDRef"]
    out = hwpx_styles.define_style_ext("doc.hwpx", "밑줄강조", kind="CHAR", char_pr_id=big)
    got = style_of(ws, "밑줄강조")
    assert (out["kind"], got["type"], got["charPrIDRef"], got["paraPrIDRef"], got["nextStyleIDRef"]) == ("CHAR", "CHAR", big, "0", "0")
    hwpx_styles.define_style_ext("doc.hwpx", "밑줄강조", char_pr_id="0")  # kind is kept when it is not given
    assert style_of(ws, "밑줄강조")["type"] == "CHAR" and style_of(ws, "밑줄강조")["charPrIDRef"] == "0"
    with pytest.raises(ToolInputError, match="CHAR style has no paragraph shape or next style"):
        hwpx_styles.define_style_ext("doc.hwpx", "다른 글자", kind="CHAR", para_pr_id="3")
    with pytest.raises(ToolInputError, match="CHAR style has no paragraph shape or next style"):
        hwpx_styles.define_style_ext("doc.hwpx", "다른 글자", kind="CHAR", next_style="보기")


@pytest.mark.parametrize("name", ["바탕글", "개요 3", "미주", "캡션", "쪽 번호", "  본문 "])
def test_define_style_refuses_to_overwrite_builtin_names(ws, name):
    before = digest(ws)
    with pytest.raises(ToolInputError, match="built-in"):
        hwpx_styles.define_style_ext("doc.hwpx", name, para_pr_id="3")
    assert digest(ws) == before


def test_define_style_refuses_name_clashes_and_kind_change(ws):
    with pytest.raises(ToolInputError, match="name 'Normal' is already the name or English name"):
        hwpx_styles.define_style_ext("doc.hwpx", "Normal")
    with pytest.raises(ToolInputError, match="eng_name 'Body' is already"):
        hwpx_styles.define_style_ext("doc.hwpx", "새 스타일", eng_name="Body")
    with pytest.raises(ToolInputError, match="its kind cannot be changed to 'CHAR'"):
        hwpx_styles.define_style_ext("doc.hwpx", "보기", kind="CHAR")
    with pytest.raises(ToolInputError, match="kind must be"):
        hwpx_styles.define_style_ext("doc.hwpx", "새 스타일", kind="TABLE")
    with pytest.raises(ToolInputError, match="name must not be empty"):
        hwpx_styles.define_style_ext("doc.hwpx", " ")
    with pytest.raises(ToolInputError, match="already exists; give"):
        hwpx_styles.define_style_ext("doc.hwpx", "보기")


def test_define_style_paragraph_and_ids_are_exclusive_and_checked(ws):
    before = digest(ws)
    with pytest.raises(ToolInputError, match="exclusive"):
        hwpx_styles.define_style_ext("doc.hwpx", "새 스타일", from_paragraph_index=0, para_pr_id="3")
    with pytest.raises(ToolInputError, match="exclusive"):
        hwpx_styles.define_style_ext("doc.hwpx", "새 스타일", from_paragraph_index=0, char_pr_id="0")
    with pytest.raises(ToolInputError, match=r"paraPrIDRef='999'"):
        hwpx_styles.define_style_ext("doc.hwpx", "새 스타일", para_pr_id="999")
    with pytest.raises(ToolInputError, match=r"charPrIDRef='999'"):
        hwpx_styles.define_style_ext("doc.hwpx", "새 스타일", char_pr_id="999")
    with pytest.raises(ToolInputError, match=r"invalid paragraph index \[9\]"):
        hwpx_styles.define_style_ext("doc.hwpx", "새 스타일", from_paragraph_index=9)
    assert digest(ws) == before


def test_define_style_next_style(ws):
    own_name = hwpx_styles.define_style_ext("doc.hwpx", "문제A", para_pr_id="3", next_style="문제A")
    assert own_name["nextStyleIDRef"] == own_name["styleIDRef"]
    other = hwpx_styles.define_style_ext("doc.hwpx", "문제B", para_pr_id="3", next_style="보기")
    assert other["nextStyleIDRef"] == "23"
    english = hwpx_styles.define_style_ext("doc.hwpx", "문제C", para_pr_id="3", eng_name="Q", next_style="Q")
    assert english["nextStyleIDRef"] == english["styleIDRef"]
    own_id = hwpx_styles.define_style_ext("doc.hwpx", "문제A", next_style=own_name["styleIDRef"])  # update: next by its own id
    assert own_id["nextStyleIDRef"] == own_name["styleIDRef"]
    hwpx_styles.define_style_ext("doc.hwpx", "문제A", next_style="바탕글")
    assert style_of(ws, "문제A")["nextStyleIDRef"] == "0"


def test_define_style_next_style_refusals_leave_no_half_made_style(ws):
    before = digest(ws)
    with pytest.raises(ToolInputError) as error:
        hwpx_styles.define_style_ext("doc.hwpx", "반쪽", para_pr_id="3", next_style="없는 스타일")
    assert "'없는 스타일'" in str(error.value) and "반쪽 (id" not in str(error.value)  # the listing is of the file's own styles
    with pytest.raises(ToolInputError, match="CHAR style; a next style must be a paragraph style"):
        hwpx_styles.define_style_ext("doc.hwpx", "반쪽", para_pr_id="3", next_style="쪽 번호")
    assert digest(ws) == before


def test_define_style_dry_run_reports_without_saving(ws):
    before = digest(ws)
    out = hwpx_styles.define_style_ext("doc.hwpx", "시험", para_pr_id="3", dry_run=True)
    assert out["dryRun"] is True and out["styleIDRef"] == "24" and out["created"] is True
    with pytest.raises(ToolInputError, match="revision mismatch"):
        hwpx_styles.define_style_ext("doc.hwpx", "시험", para_pr_id="3", expected_revision="sha256:" + "0" * 64)
    assert digest(ws) == before


# --- set_list_format_ext -------------------------------------------------------------------------------------------

def numberings(ws: Path) -> dict[str, etree._Element]:
    header, _ = parts(ws)
    return {n.get("id"): n for n in header.iter(f"{HH}numbering")}


def heading_of(ws: Path, index: int) -> etree._Element:
    header, _ = parts(ws)
    pr = next(p for p in header.iter(f"{HH}paraPr") if p.get("id") == body(ws)[index]["para"])
    return pr.find(f"{HH}heading")


def test_number_list_in_one_call_shares_one_numbering(ws):
    out = hwpx_styles.set_list_format_ext("doc.hwpx", [1, 2, 3], number_format="circled_digit", start=3)
    assert (out["formatted"], out["kind"], out["level"], out["paragraphs"]) == (3, "number", 1, [1, 2, 3])
    heads = [heading_of(ws, i) for i in (1, 2, 3)]
    assert {(h.get("type"), h.get("level"), h.get("idRef")) for h in heads} == {("NUMBER", "0", heads[0].get("idRef"))}
    head = numberings(ws)[heads[0].get("idRef")].find(f"{HH}paraHead")
    assert (head.get("numFormat"), head.get("start"), head.get("level")) == ("CIRCLED_DIGIT", "3", "1")
    assert heading_of(ws, 0).get("type") == "NONE"
    shapes = hwpx_layout.read_layout(ws / "doc.hwpx", "body")
    shape = shapes["shapes"][shapes["items"][1]["paraPr"]]
    assert shape["heading"]["type"] == "NUMBER" and shape["heading"]["numbering"]["format"] == "CIRCLED_DIGIT"


def test_bullet_and_outline_kinds(ws):
    hwpx_styles.set_list_format_ext("doc.hwpx", [1], kind="bullet", bullet_char="●")
    head = heading_of(ws, 1)
    assert head.get("type") == "BULLET"
    header, _ = parts(ws)
    bullet = next(b for b in header.iter(f"{HH}bullet") if b.get("id") == head.get("idRef"))
    assert bullet.get("char") == "●"
    hwpx_styles.set_list_format_ext("doc.hwpx", [2], kind="outline", level=2, number_format="roman_capital")
    outline = heading_of(ws, 2)
    assert (outline.get("type"), outline.get("level")) == ("OUTLINE", "1")
    levels = {h.get("level"): h.get("numFormat") for h in numberings(ws)[outline.get("idRef")].findall(f"{HH}paraHead")}
    assert levels["2"] == "ROMAN_CAPITAL"


def test_number_char_reproduces_the_question_number_size(ws):
    """문제 번호 크기는 번호 정의의 paraHead@charPrIDRef가 가리키는 글자 모양이다."""
    text_chars = body(ws)[1]["chars"]
    out = hwpx_styles.set_list_format_ext("doc.hwpx", [1, 2], number_char={"font_size": 13, "bold": True})
    char_id = out["numberCharPrIDRef"]
    head = numberings(ws)[heading_of(ws, 1).get("idRef")].find(f"{HH}paraHead")
    assert head.get("charPrIDRef") == char_id
    shape = char_pr(ws, char_id)
    assert shape.get("height") == "1300" and shape.find(f"{HH}bold") is not None
    assert body(ws)[1]["chars"] == text_chars and char_id not in text_chars  # the text keeps its own size
    listed = hwpx_layout.read_layout(ws / "doc.hwpx", "header", kind="numbering")["items"][-1]
    assert listed["number_char"]["size"] == 13 and listed["number_char"]["bold"] is True


def test_number_char_pr_id_uses_an_existing_shape(ws):
    big = style_of(ws, "보기")["charPrIDRef"]
    hwpx_styles.set_list_format_ext("doc.hwpx", [1], kind="outline", number_char_pr_id=big)
    assert numberings(ws)[heading_of(ws, 1).get("idRef")].find(f"{HH}paraHead").get("charPrIDRef") == big
    with pytest.raises(ToolInputError, match="no such character shape"):
        hwpx_styles.set_list_format_ext("doc.hwpx", [1], number_char_pr_id="999")
    with pytest.raises(ToolInputError, match="exclusive"):
        hwpx_styles.set_list_format_ext("doc.hwpx", [1], number_char={"bold": True}, number_char_pr_id=big)


def test_continue_list_keeps_the_numbering_definition(ws):
    base = len(numberings(ws))
    hwpx_styles.set_list_format_ext("doc.hwpx", [0, 1], number_format="digit", start=5)
    first = heading_of(ws, 1).get("idRef")
    hwpx_styles.set_list_format_ext("doc.hwpx", [2, 3], continue_list=True)
    assert {heading_of(ws, i).get("idRef") for i in (0, 1, 2, 3)} == {first}
    assert len(numberings(ws)) == base + 1
    hwpx_styles.set_list_format_ext("doc.hwpx", [3])  # a separate call without continue_list starts a new numbering definition
    assert heading_of(ws, 3).get("idRef") != first and len(numberings(ws)) == base + 2


@pytest.mark.parametrize("given", [{"number_format": "DIGIT"}, {"start": 2}, {"number_char": {"bold": True}}, {"number_char_pr_id": "0"}])
def test_continue_list_conflicts_are_refused(ws, given):
    before = digest(ws)
    with pytest.raises(ToolInputError, match="continue_list cannot be combined with"):
        hwpx_styles.set_list_format_ext("doc.hwpx", [1], continue_list=True, **given)
    assert digest(ws) == before


def test_list_format_argument_refusals(ws):
    before = digest(ws)
    for kwargs, message in [
        ({"level": 0}, "level must be an int from 1 to 10"),
        ({"level": 11}, "level must be an int from 1 to 10"),
        ({"start": 65536}, "start must be an int from 0 to 65535"),
        ({"start": -1}, "start must be an int from 0 to 65535"),
        ({"number_format": "ROMANESQUE"}, "Use one of"),  # the library's own suggestion comes through
        ({"bullet_char": "●"}, "bullet_char applies to kind='bullet' only"),
        ({"kind": "bullet", "number_format": "DIGIT"}, "number and outline lists only"),
        ({"kind": "bullet", "number_char": {"bold": True}}, "number and outline lists only"),
        ({"kind": "table"}, "kind must be"),
        ({"number_char": {}}, "number_char is empty"),
        ({"number_char": {"bld": True}}, "unknown number_char option"),
    ]:
        with pytest.raises(ToolInputError, match=message):
            hwpx_styles.set_list_format_ext("doc.hwpx", [1], **kwargs)
    with pytest.raises(ToolInputError, match="at least one"):
        hwpx_styles.set_list_format_ext("doc.hwpx", [])
    with pytest.raises(ToolInputError, match=r"invalid paragraph index \[7\]"):
        hwpx_styles.set_list_format_ext("doc.hwpx", [1, 7])
    assert digest(ws) == before


def test_list_format_accepts_the_range_ends(ws):
    hwpx_styles.set_list_format_ext("doc.hwpx", [1], level=10, start=0)
    hwpx_styles.set_list_format_ext("doc.hwpx", [2], level=1, start=65535)
    assert heading_of(ws, 1).get("level") == "9"
    assert numberings(ws)[heading_of(ws, 2).get("idRef")].find(f"{HH}paraHead").get("start") == "65535"


def test_list_format_dry_run_and_stale_revision_leave_file_alone(ws):
    before = digest(ws)
    out = hwpx_styles.set_list_format_ext("doc.hwpx", [1], number_char={"font_size": 13}, dry_run=True)
    assert out["dryRun"] is True and out["formatted"] == 1
    with pytest.raises(ToolInputError, match="revision mismatch"):
        hwpx_styles.set_list_format_ext("doc.hwpx", [1], expected_revision="sha256:" + "0" * 64)
    assert digest(ws) == before


def test_apply_style_says_when_it_replaced_a_paragraph_shape(ws):
    import hwpx_edit
    hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, indent_left_mm=5.0)
    result = hwpx_styles.apply_style_ext("doc.hwpx", [0], "본문")
    assert result["replacedParagraphShape"] == [0] and "format them again" in result["note"]
    again = hwpx_styles.apply_style_ext("doc.hwpx", [0], "본문")
    assert "replacedParagraphShape" not in again
    kept = hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=0, indent_left_mm=5.0)
    assert "replacedParagraphShape" not in hwpx_styles.apply_style_ext("doc.hwpx", [0], "본문", apply_para="keep")
