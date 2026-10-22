"""hwpx_textedit: replace_text_ext, edit_paragraph_text_ext, split_paragraph_ext, merge_paragraphs_ext, redact_text_ext (합성 문서만 쓴다; 주민번호·카드번호는 검증을 통과하게
만든 가짜다). 실행: venv/bin/python -m pytest toolkit/tests/test_hwpx_textedit.py"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.tools.id_integrity import check_id_integrity
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_edit  # noqa: E402
import hwpx_inline  # noqa: E402
import hwpx_layout  # noqa: E402
import hwpx_locate  # noqa: E402
import hwpx_textedit as te  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
FILE = "doc.hwpx"


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """doc.hwpx: 0 section definition + '머리' | 1 '가나다 열거 라마' + bold ' 굵은 열거' + endnote 1 | 2 '①<tab>보기 열거 둘' + equation | 3 '셋째 Hello hello' + footnote 1 |
    4 table holder (2x2, cell (0,1) '칸 열거 글') | 5 '끝 문단'; endnote 2 (two paragraphs) on paragraph 5; header and footer. Paragraphs 1-3 carry a layout cache."""
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    bold = doc.styles.ensure_run(bold=True)
    first = doc.add_paragraph("가나다 열거 라마")
    first.add_run(" 굵은 열거", char_pr_id_ref=bold)
    doc.notes.add_endnote("해설 열거 하나", paragraph=first)
    second = doc.add_paragraph("①\t보기 열거 둘")
    second.add_equation("x^2")
    doc.add_paragraph("셋째 Hello hello").add_footnote("각주 열거")
    holder = doc.add_paragraph("")
    holder.add_table(2, 2, width=20000, height=4000).set_cell_text(0, 1, "칸 열거 글")
    doc.add_paragraph("끝 문단")
    doc.page.set_header(text="머리말 열거")
    doc.page.set_footer(text="꼬리말 열거")
    for index in (1, 2, 3):  # a line layout cache, which every changed paragraph has to lose
        cache = etree.SubElement(doc.sections[0].paragraphs[index].element, HP + "linesegarray")
        etree.SubElement(cache, HP + "lineseg", textpos="0", vertpos="0", vertsize="1000", textheight="1000", baseline="850", spacing="600", horzpos="0", horzsize="40000", flags="393216")
    doc.save_to_path(tmp_path / FILE)
    hwpx_edit.add_endnote_ext(FILE, 5, [{"text": "둘째 해설 열거"}, {"text": "해설 둘째 문단"}])
    (tmp_path / (FILE + ".bak")).unlink()
    return tmp_path


def sha(ws: Path) -> str:
    return hashlib.sha256((ws / FILE).read_bytes()).hexdigest()


def section(ws: Path, number: int = 0) -> etree._Element:
    return etree.fromstring(zipfile.ZipFile(ws / FILE).read(f"Contents/section{number}.xml"))


def body(ws: Path, index: int) -> etree._Element:
    return section(ws).findall(HP + "p")[index]


def reopened(ws: Path) -> HwpxDocument:
    return HwpxDocument.open(ws / FILE)


def text_at(ws: Path, **address) -> str:
    return hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopened(ws), **address))


def all_texts(ws: Path) -> dict[str, str]:
    return {json.dumps(address): hwpx_locate.paragraph_text(paragraph) for address, paragraph in hwpx_locate.iter_paragraphs(reopened(ws))}


def count(element: etree._Element, name: str) -> int:
    return len(list(element.iter(HP + name)))


def char_refs(paragraph: etree._Element) -> list[str]:
    return [run.get("charPrIDRef") for run in paragraph.findall(HP + "run")]


def check_saved(ws: Path) -> None:
    """The file opens, has no dangling ids, and every part of hwpx_read_layout that shows text reads it back."""
    doc = reopened(ws)
    assert check_id_integrity(doc).ok
    for part in ("body", "notes", "objects"):
        assert hwpx_layout.read_layout(ws / FILE, part, max_chars=10**9)["total"] >= 0
    for _, paragraph in hwpx_locate.iter_paragraphs(doc):
        assert len(paragraph.element.findall(HP + "run")) >= 1  # a paragraph never loses its last run


# ---------------------------------------------------------------- replace_text_ext

def test_replace_reaches_body_cells_endnotes_footnotes_headers_and_footers(ws):
    first_refs = char_refs(body(ws, 1))
    result = te.replace_text_ext(FILE, "열거", "나열하기")
    assert result["replaced"] == result["matched"] == 9 and not result["truncated"]
    assert result["byScope"] == {"body": 3, "table_cells": 1, "endnotes": 2, "footnotes": 1, "headers_footers": 2}
    texts = all_texts(ws)
    assert "열거" not in "".join(texts.values()) and sum(text.count("나열하기") for text in texts.values()) == 9
    assert text_at(ws, paragraph_index=1) == "가나다 나열하기 라마 굵은 나열하기"
    assert text_at(ws, table_index=0, row=0, col=1) == "칸 나열하기 글"
    assert text_at(ws, endnote_number=1) == "해설 나열하기 하나" and text_at(ws, endnote_number=2) == "둘째 해설 나열하기"
    assert text_at(ws, footnote_number=1) == "각주 나열하기"
    assert text_at(ws, header_index=0) == "머리말 나열하기" and text_at(ws, footer_index=0) == "꼬리말 나열하기"
    assert char_refs(body(ws, 1)) == first_refs  # the bold second half is still bold, the first half is not
    assert len(set(first_refs)) == 2
    assert count(body(ws, 1), "endNote") == 1 and count(body(ws, 2), "tab") == 1 and count(body(ws, 2), "equation") == 1 and count(body(ws, 3), "footNote") == 1
    assert body(ws, 1).find(HP + "linesegarray") is None and body(ws, 2).find(HP + "linesegarray") is None  # the changed paragraphs lose the layout cache
    assert body(ws, 3).find(HP + "linesegarray") is not None  # an untouched one keeps it ("셋째 Hello hello" has no 열거)
    equation = next(o for o in hwpx_layout.read_layout(ws / FILE, "objects", max_chars=10**9)["items"] if o["kind"] == "equation")
    assert equation["at"] == len("①\t보기 나열하기 둘")  # the object moved with the text
    check_saved(ws)


def test_the_header_copy_in_the_section_definition_follows_the_edit(ws):
    te.replace_text_ext(FILE, "머리말", "위쪽 글", scopes=["headers_footers"])
    xml = zipfile.ZipFile(ws / FILE).read("Contents/section0.xml").decode()
    assert xml.count("위쪽 글") == 2 and "머리말" not in xml  # the story Hancom reads and the one python-hwpx keeps beside it


def test_replace_inside_one_run_changes_only_that_text_and_across_runs_takes_the_first_shape(ws):
    before = char_refs(body(ws, 1))
    te.replace_text_ext(FILE, "다 열거 라마 굵은", "[가로질러]")
    assert text_at(ws, paragraph_index=1) == "가나[가로질러] 열거"
    assert count(body(ws, 1), "endNote") == 1 and count(body(ws, 1), "linesegarray") == 0
    refs = char_refs(body(ws, 1))
    assert before[0] in refs and set(refs) == set(before)  # the new text has the shape of the first replaced character
    middle = next(run for run in body(ws, 1).findall(HP + "run") if "[가로질러]" in "".join(run.itertext()))
    assert middle.get("charPrIDRef") == before[0]
    check_saved(ws)


def test_replace_cutting_a_tab_paragraph_keeps_the_other_tab_and_objects(ws):
    te.replace_text_ext(FILE, "보기", "문제")  # inside the text after the tab
    assert text_at(ws, paragraph_index=2) == "①\t문제 열거 둘" and count(body(ws, 2), "tab") == 1
    te.replace_text_ext(FILE, "①\t문", "(1) 문", scopes=["body"])  # a match that contains the tab removes it
    assert text_at(ws, paragraph_index=2) == "(1) 문제 열거 둘" and count(body(ws, 2), "tab") == 0 and count(body(ws, 2), "equation") == 1
    te.replace_text_ext(FILE, "열거", "\t", special=True, scopes=["body"], occurrence=3)
    assert text_at(ws, paragraph_index=2) == "(1) 문제 \t 둘" and count(body(ws, 2), "tab") == 1
    check_saved(ws)


def test_occurrence_replaces_only_the_nth_match_in_document_order(ws):
    result = te.replace_text_ext(FILE, "열거", "XX", occurrence=2)
    assert result["replaced"] == 1 and result["locations"][0]["address"] == {"paragraph_index": 1} and result["locations"][0]["start"] == 13
    assert text_at(ws, paragraph_index=1) == "가나다 열거 라마 굵은 XX"
    te.replace_text_ext(FILE, "열거", "YY", occurrence=3)  # two are left in the body, the third is in the table cell
    assert text_at(ws, table_index=0, row=0, col=1) == "칸 YY 글"
    assert text_at(ws, paragraph_index=1) == "가나다 열거 라마 굵은 XX" and text_at(ws, endnote_number=1) == "해설 열거 하나"
    assert te.replace_text_ext(FILE, "열거", "ZZ", occurrence=99)["replaced"] == 0


def test_regex_with_groups_and_case_insensitive_search(ws):
    te.replace_text_ext(FILE, r"(가)(나)(?P<third>다)", r"\g<third>\2\1", regex=True)
    assert text_at(ws, paragraph_index=1).startswith("다나가 열거")
    te.replace_text_ext(FILE, "hello", "안녕", match_case=False, scopes=["body"])
    assert text_at(ws, paragraph_index=3) == "셋째 안녕 안녕"
    assert te.replace_text_ext(FILE, "HELLO", "x")["replaced"] == 0  # case matters by default
    te.replace_text_ext(FILE, "[.]", "!", regex=False)  # a literal, not a pattern
    assert te.replace_text_ext(FILE, r"^\d+$", "n", regex=True)["replaced"] == 0
    check_saved(ws)


def test_scopes_and_section_index_limit_the_search(ws):
    result = te.replace_text_ext(FILE, "열거", "한정", scopes=["endnotes", "footnotes"], section_index=0)
    assert result["byScope"] == {"endnotes": 2, "footnotes": 1} and result["replaced"] == 3
    assert all(location["address"]["section_index"] == 0 for location in result["locations"])
    for location in result["locations"]:  # section_index is part of the address, which the paragraph tools take as it is
        assert "한정" in hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopened(ws), **location["address"]))
    assert text_at(ws, paragraph_index=1) == "가나다 열거 라마 굵은 열거" and text_at(ws, header_index=0) == "머리말 열거"
    for bad in (["bogus"], [], "body"):
        with pytest.raises(ToolInputError, match="scopes"):
            te.replace_text_ext(FILE, "열거", "x", scopes=bad)
    with pytest.raises(ToolInputError, match="section_index"):
        te.replace_text_ext(FILE, "열거", "x", section_index=3)


def test_locations_give_addresses_that_resolve_back_and_never_the_text(ws):
    result = te.replace_text_ext(FILE, "열거", "나열", dry_run=True)
    assert result["replaced"] == len(result["locations"]) == 9 and result["dryRun"] is True
    doc = reopened(ws)
    for location in result["locations"]:
        assert set(location) == {"address", "start", "length"} and location["length"] == 2
        text = hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(doc, **location["address"]))
        assert text[location["start"]:location["start"] + location["length"]] == "열거"
    assert_no_text(result)


def assert_no_text(result: dict, *words: str) -> None:
    """Nothing of the document's text is in the answer: upstream's readers mask personal information and the answer must not bring it back."""
    dumped = json.dumps(result, ensure_ascii=False)
    for word in ("열거", "가나다", "라마", "굵은", "보기", "Hello", "hello", "끝 문단", *words):
        assert word not in dumped, word
    assert "semanticDiff" not in dumped


def test_more_than_thirty_places_are_counted_but_listed_thirty(ws):
    te.edit_paragraph_text_ext(FILE, 0, text="쪽" * 100, paragraph_index=5)
    result = te.replace_text_ext(FILE, "쪽", "면", scopes=["body"])
    assert result["replaced"] == 100 and len(result["locations"]) == 30 and result["truncated"] is True
    assert text_at(ws, paragraph_index=5) == "면" * 100 + "끝 문단"


def object_at(ws: Path, kind: str, paragraph_index: int = 3) -> list[int]:
    return [o["at"] for o in hwpx_layout.read_layout(ws / FILE, "objects", max_chars=10**9)["items"] if o["kind"] == kind and o.get("paragraph_index") == paragraph_index]


def test_a_match_with_an_object_inside_is_skipped_and_one_beside_it_is_replaced(ws):
    # "셋째 Hello hello" (H at 3, h at 9): an equation after "셋째 He" (position 5) and a footnote anchor after "셋째 Hello he" (position 11)
    hwpx_inline.insert_inline_ext(FILE, [{"equation": "x"}], position=5, paragraph_index=3)
    hwpx_inline.insert_inline_ext(FILE, [{"footnote": "새 각주"}], position=11, paragraph_index=3)
    before = sha(ws)
    result = te.replace_text_ext(FILE, "ello", "ELLO", scopes=["body"])  # "ello" in Hello holds the equation, the one in hello holds the footnote anchor
    assert (result["replaced"], result["matched"], result["skippedCount"], result["saved"]) == (0, 2, 2, False) and "skipped" in result["note"] and result["byScope"] == {"body": 0}
    assert result["skipped"] == [{"address": {"paragraph_index": 3}, "start": 4, "length": 4}, {"address": {"paragraph_index": 3}, "start": 10, "length": 4}]
    assert_no_text(result, "ELLO", "ello")
    assert sha(ws) == before
    # objects at the edge of a match are fine and stay where they are: the equation (5) ends "셋째 He", the footnote anchor (11) ends "he"
    result = te.replace_text_ext(FILE, "셋째 He", "첫째 HE", scopes=["body"])
    assert result["replaced"] == 1 and result["skippedCount"] == 0 and text_at(ws, paragraph_index=3) == "첫째 HEllo hello" and object_at(ws, "equation") == [5]
    result = te.replace_text_ext(FILE, "he", "HE", scopes=["body"])
    assert result["replaced"] == 1 and text_at(ws, paragraph_index=3) == "첫째 HEllo HEllo" and object_at(ws, "footnote") == [11, 14]  # the fixture's own footnote stands at the end
    assert count(body(ws, 3), "equation") == 1 and count(body(ws, 3), "footNote") == 2 and body(ws, 3).find(HP + "linesegarray") is None
    check_saved(ws)


def test_occurrence_counts_a_skipped_match_and_dry_run_lists_it(ws):
    hwpx_inline.insert_inline_ext(FILE, [{"equation": "x"}], position=6, paragraph_index=3)  # inside the first "ello" (4..8)
    result = te.replace_text_ext(FILE, "ello", "ELLO", scopes=["body"], occurrence=1, dry_run=True)
    assert (result["replaced"], result["skippedCount"], result["dryRun"]) == (0, 1, True) and result["skipped"][0]["start"] == 4
    result = te.replace_text_ext(FILE, "ello", "ELLO", scopes=["body"], occurrence=2)
    assert result["replaced"] == 1 and text_at(ws, paragraph_index=3) == "셋째 Hello hELLO"
    both = te.replace_text_ext(FILE, "ELLO|ello", "x", regex=True, scopes=["body"], dry_run=True)
    assert both["matched"] == 2 and both["replaced"] == 1 and both["skippedCount"] == 1
    assert_no_text(both, "ELLO")


def test_a_hyperlink_inside_a_match_is_skipped(ws):
    hwpx_inline.insert_inline_ext(FILE, [{"hyperlink": {"url": "https://example.com", "text": "링크"}}], position=1, paragraph_index=5)  # 끝[링크] 문단
    result = te.replace_text_ext(FILE, "끝링크", "X", scopes=["body"])
    assert result["replaced"] == 0 and result["skippedCount"] == 1  # the link's start mark stands at 1, inside the match
    assert te.replace_text_ext(FILE, "링크", "X", scopes=["body"])["replaced"] == 1  # only the display text: the marks stand at its edges
    assert count(body(ws, 5), "fieldBegin") == 1 and count(body(ws, 5), "fieldEnd") == 1 and text_at(ws, paragraph_index=5) == "끝X 문단"


def test_no_match_is_reported_and_nothing_is_saved(ws):
    te.replace_text_ext(FILE, "머리", "첫머리")  # a real edit first: its backup must survive the no-match calls
    backup = (ws / (FILE + ".bak")).read_bytes()
    before = sha(ws)
    result = te.replace_text_ext(FILE, "없는글", "x")
    assert result["replaced"] == result["matched"] == 0 and "not found" in result["note"] and "captions, text boxes, memos and field values" in result["note"]
    assert result["saved"] is False and result["locations"] == [] and result["skipped"] == [] and result["skippedCount"] == 0
    assert sha(ws) == before and (ws / (FILE + ".bak")).read_bytes() == backup


def test_replace_refusals_dry_run_and_revision_leave_the_file_alone(ws):
    before = sha(ws)
    bad = [
        (dict(find_text=""), "find_text"), (dict(find_text="(", regex=True), "regular expression"), (dict(find_text="열거", replace_text=r"\1", regex=True), "does not fit"),
        (dict(find_text="열거", occurrence=-1), "occurrence"), (dict(find_text="열거", occurrence=True), "occurrence"), (dict(find_text="열거", scopes=["body", "nowhere"]), "scopes"),
    ]
    for arguments, message in bad:
        with pytest.raises(ToolInputError, match=message):
            te.replace_text_ext(FILE, **{"replace_text": "x", **arguments})
    with pytest.raises(ToolInputError, match="revision mismatch"):
        te.replace_text_ext(FILE, "열거", "x", expected_revision="sha256:" + "0" * 64)
    assert te.replace_text_ext(FILE, "열거", "x", dry_run=True)["dryRun"] is True
    assert sha(ws) == before and not (ws / (FILE + ".bak")).exists()


def test_special_characters_become_elements_only_when_asked(ws):
    te.replace_text_ext(FILE, "Hello", "a\u00a0b\u3000c\u00ade", special=True, scopes=["body"])
    names = [etree.QName(child).localname for child in body(ws, 3).iter() if etree.QName(child).localname in ("nbSpace", "fwSpace", "hyphen")]
    assert names == ["nbSpace", "fwSpace", "hyphen"] and text_at(ws, paragraph_index=3) == "셋째 a\u00a0b\u3000c\u00ade hello"
    te.replace_text_ext(FILE, "hello", "\\t", scopes=["body"])  # without special the backslash text stays text
    assert text_at(ws, paragraph_index=3).endswith(" \\t")
    check_saved(ws)


# ---------------------------------------------------------------- edit_paragraph_text_ext

def test_edit_inserts_deletes_and_replaces_by_character_position(ws):
    result = te.edit_paragraph_text_ext(FILE, 4, text="[끼움]", paragraph_index=1)
    assert text_at(ws, paragraph_index=1) == "가나다 [끼움]열거 라마 굵은 열거" and result["paragraphLength"] == len("가나다 [끼움]열거 라마 굵은 열거") and result["insertedLength"] == 4 and result["removedLength"] == 0
    assert_no_text(result, "끼움")
    result = te.edit_paragraph_text_ext(FILE, 4, 8, paragraph_index=1)  # delete
    assert text_at(ws, paragraph_index=1) == "가나다 열거 라마 굵은 열거" and result["removedLength"] == 4 and result["insertedLength"] == 0
    result = te.edit_paragraph_text_ext(FILE, 0, 3, "하나둘", paragraph_index=1)
    assert text_at(ws, paragraph_index=1) == "하나둘 열거 라마 굵은 열거" and (result["removedLength"], result["insertedLength"], result["end"]) == (3, 3, 3)
    assert count(body(ws, 1), "endNote") == 1 and body(ws, 1).find(HP + "linesegarray") is None
    check_saved(ws)


def test_edit_reports_lengths_only(ws):
    te.edit_paragraph_text_ext(FILE, 0, text="가" * 60, paragraph_index=5)
    result = te.edit_paragraph_text_ext(FILE, 0, 60, "나", paragraph_index=5)
    assert (result["removedLength"], result["insertedLength"], result["paragraphLength"]) == (60, 1, 5) and text_at(ws, paragraph_index=5) == "나끝 문단"
    assert_no_text(result, "가" * 5, "나")


def test_edit_positions_count_a_tab_as_one_character_and_objects_stay(ws):
    te.edit_paragraph_text_ext(FILE, 2, 4, "문제", paragraph_index=2)  # 보기 stands after ① and the tab
    assert text_at(ws, paragraph_index=2) == "①\t문제 열거 둘" and count(body(ws, 2), "tab") == 1
    te.edit_paragraph_text_ext(FILE, 1, text="+", paragraph_index=2)  # between ① and the tab
    assert text_at(ws, paragraph_index=2) == "①+\t문제 열거 둘" and count(body(ws, 2), "tab") == 1
    te.edit_paragraph_text_ext(FILE, 0, 2, paragraph_index=2)  # delete ① and + in front of the tab
    assert text_at(ws, paragraph_index=2) == "\t문제 열거 둘" and count(body(ws, 2), "tab") == 1
    te.edit_paragraph_text_ext(FILE, 0, 1, paragraph_index=2)  # delete the tab itself
    assert text_at(ws, paragraph_index=2) == "문제 열거 둘" and count(body(ws, 2), "tab") == 0 and count(body(ws, 2), "equation") == 1
    end = len(text_at(ws, paragraph_index=2))
    te.edit_paragraph_text_ext(FILE, end, text="끝에", paragraph_index=2)  # the equation stays in front of text added at the very end
    assert text_at(ws, paragraph_index=2) == "문제 열거 둘끝에"
    objects = hwpx_layout.read_layout(ws / FILE, "objects", max_chars=10**9)["items"]
    assert next(o for o in objects if o["kind"] == "equation")["at"] == end
    check_saved(ws)


def test_edit_keeps_an_object_inside_the_replaced_range(ws):
    hwpx_inline.insert_inline_ext(FILE, [{"equation": "x"}], position=5, paragraph_index=3)  # "셋째 He|llo hello"
    result = te.edit_paragraph_text_ext(FILE, 3, 8, "가나다라", paragraph_index=3)  # replaces "Hello", the equation stands inside
    assert text_at(ws, paragraph_index=3) == "셋째 가나다라 hello" and count(body(ws, 3), "equation") == 1 and (result["removedLength"], result["insertedLength"]) == (5, 4)
    assert body(ws, 3).find(HP + "linesegarray") is None and count(body(ws, 3), "footNote") == 1
    check_saved(ws)


def test_edit_new_text_takes_the_shape_of_the_replaced_or_preceding_character(ws):
    refs = char_refs(body(ws, 1))
    bold = next(ref for ref in refs if ref != refs[0])
    te.edit_paragraph_text_ext(FILE, 10, 12, "굵게", paragraph_index=1)  # inside the bold part
    run = next(run for run in body(ws, 1).findall(HP + "run") if "굵게" in "".join(run.itertext()))
    assert run.get("charPrIDRef") == bold and text_at(ws, paragraph_index=1) == "가나다 열거 라마 굵게굵은 열거"[:10] + "굵게" + "가나다 열거 라마 굵은 열거"[12:]
    te.edit_paragraph_text_ext(FILE, 3, text="ㅎ", paragraph_index=1)  # an insertion takes the shape of the character before it
    run = next(run for run in body(ws, 1).findall(HP + "run") if "ㅎ" in "".join(run.itertext()))
    assert run.get("charPrIDRef") == refs[0]


def test_edit_the_whole_text_leaves_a_run_and_the_objects(ws):
    te.edit_paragraph_text_ext(FILE, 0, len("가나다 열거 라마 굵은 열거"), paragraph_index=1)
    paragraph = body(ws, 1)
    assert text_at(ws, paragraph_index=1) == "" and len(paragraph.findall(HP + "run")) >= 1 and count(paragraph, "endNote") == 1
    te.edit_paragraph_text_ext(FILE, 0, len("끝 문단"), paragraph_index=5)
    assert text_at(ws, paragraph_index=5) == "" and len(body(ws, 5).findall(HP + "run")) >= 1
    te.edit_paragraph_text_ext(FILE, 0, text="다시", paragraph_index=5)
    assert text_at(ws, paragraph_index=5) == "다시"
    check_saved(ws)


def test_edit_in_cells_notes_footnotes_headers_and_footers(ws):
    te.edit_paragraph_text_ext(FILE, 0, 1, "ㅋ", table_index=0, row=0, col=1)
    te.edit_paragraph_text_ext(FILE, 3, 5, "정정", endnote_number=1)
    te.edit_paragraph_text_ext(FILE, 0, text="둘째 ", endnote_number=2, endnote_paragraph_index=1)
    te.edit_paragraph_text_ext(FILE, 0, 2, "주", footnote_number=1)
    te.edit_paragraph_text_ext(FILE, 4, 5, "[", header_index=0)
    te.edit_paragraph_text_ext(FILE, 0, 1, "아래", footer_index=0)
    assert text_at(ws, table_index=0, row=0, col=1) == "ㅋ 열거 글" and text_at(ws, endnote_number=1) == "해설 정정 하나"
    assert text_at(ws, endnote_number=2, endnote_paragraph_index=1) == "둘째 해설 둘째 문단" and text_at(ws, footnote_number=1) == "주 열거"
    assert text_at(ws, header_index=0) == "머리말 [거" and text_at(ws, footer_index=0) == "아래리말 열거"
    notes = hwpx_layout.read_layout(ws / FILE, "notes", max_chars=10**9)["items"]
    assert "정정" in "".join(p["text"] for p in notes[0]["paragraphs"]) and count(body(ws, 1), "endNote") == 1
    check_saved(ws)


def test_edit_in_a_note_keeps_its_automatic_number(ws):
    te.edit_paragraph_text_ext(FILE, 0, 6, "새 해설", endnote_number=1)  # "해설 열거 " goes, "하나" stays
    note = body(ws, 1).find(f".//{HP}endNote")
    assert text_at(ws, endnote_number=1) == "새 해설하나" and note.find(f".//{HP}autoNum") is not None and note.get("number") == "1"
    check_saved(ws)


def test_edit_refusals_name_the_range_and_leave_the_file_alone(ws):
    before = sha(ws)
    length = len("가나다 열거 라마 굵은 열거")
    bad = [
        (dict(start=0, end=length + 1, paragraph_index=1), f"the paragraph has {length} characters"), (dict(start=length + 1, paragraph_index=1, text="x"), f"the paragraph has {length} characters"),
        (dict(start=5, end=2, paragraph_index=1), "before start"), (dict(start=-1, paragraph_index=1, text="x"), "start"), (dict(start=0, end=-2, paragraph_index=1), "end"),
        (dict(start=2, paragraph_index=1), "nothing to do"), (dict(start=2, end=2, paragraph_index=1), "nothing to do"), (dict(start=0, text="x"), "give exactly one paragraph address group"),
        (dict(start=0, text="x", paragraph_index=1, row=0), "do not go with"), (dict(start=0, text="x", paragraph_index=99), "invalid paragraph_index"),
        (dict(start=0, text="x", endnote_number=9), "invalid endnote_number"), (dict(start=0, text="x", table_index=0, row=0), "needs row and col"),
        (dict(start=0, text=5, paragraph_index=1), "text must be a string"), (dict(start=0, text="x", paragraph_index=1, section_index=2), "invalid section_index"),
    ]
    for arguments, message in bad:
        with pytest.raises(ToolInputError, match=message):
            te.edit_paragraph_text_ext(FILE, **arguments)
    with pytest.raises(ToolInputError, match="revision mismatch"):
        te.edit_paragraph_text_ext(FILE, 0, text="x", paragraph_index=1, expected_revision="sha256:" + "0" * 64)
    assert te.edit_paragraph_text_ext(FILE, 0, text="x", paragraph_index=1, dry_run=True)["dryRun"] is True
    assert sha(ws) == before


def test_edit_special_text_and_the_text_the_library_would_write_count_alike(ws):
    result = te.edit_paragraph_text_ext(FILE, 1, text="\t|\n", special=True, paragraph_index=5)
    assert result["paragraphLength"] == len("끝 문단") + 3 and text_at(ws, paragraph_index=5) == "끝\t|\n 문단" and count(body(ws, 5), "tab") == 1 and count(body(ws, 5), "lineBreak") == 1
    te.edit_paragraph_text_ext(FILE, 1, 4, "", paragraph_index=5)
    assert text_at(ws, paragraph_index=5) == "끝 문단" and count(body(ws, 5), "tab") == 0
    check_saved(ws)


# ---------------------------------------------------------------- split_paragraph_ext / merge_paragraphs_ext

def body_ids(ws: Path) -> list[str]:
    return [p.get("id") for p in section(ws).findall(HP + "p")]


def test_no_tool_answers_with_the_text_of_the_document(ws):
    results = [
        te.replace_text_ext(FILE, "열거", "교체"), te.edit_paragraph_text_ext(FILE, 0, 3, "새로", paragraph_index=1), te.split_paragraph_ext(FILE, 2, paragraph_index=1),
        te.merge_paragraphs_ext(FILE, paragraph_index=1), te.replace_text_ext(FILE, "교체", "다시", dry_run=True),
    ]
    for result in results:
        assert_no_text(result, "교체", "새로", "다시")
        assert "placeholderExamples" not in json.dumps(result)


def test_split_a_body_paragraph_keeps_text_shapes_and_gives_a_new_id(ws):
    first = body(ws, 1)
    before_text, para, style = text_at(ws, paragraph_index=1), first.get("paraPrIDRef"), first.get("styleIDRef")
    result = te.split_paragraph_ext(FILE, 6, paragraph_index=1)
    assert result["newParagraph"] == {"paragraph_index": 2} and result["firstLength"] == 6 and result["secondLength"] == len(before_text) - 6
    one, two = text_at(ws, paragraph_index=1), text_at(ws, paragraph_index=2)
    assert one + two == before_text and one == "가나다 열거" and two == " 라마 굵은 열거"
    first, second = body(ws, 1), body(ws, 2)
    assert (second.get("paraPrIDRef"), second.get("styleIDRef")) == (para, style) and (first.get("paraPrIDRef"), first.get("styleIDRef")) == (para, style)
    assert first.find(HP + "linesegarray") is None and second.find(HP + "linesegarray") is None
    assert len(body_ids(ws)) == len(set(body_ids(ws))) and len(section(ws).findall(HP + "p")) == 7
    assert count(first, "endNote") + count(second, "endNote") == 1 and count(second, "endNote") == 1  # the endnote sits behind the cut and moves along
    assert text_at(ws, **result["newParagraph"]) == two
    notes = [o for o in hwpx_layout.read_layout(ws / FILE, "objects", max_chars=10**9)["items"] if o["kind"] == "endnote"]
    assert [o["paragraph_index"] for o in notes] == [2, 6]  # the endnote moved to the second half; the other one (on the last paragraph) shifted by one
    check_saved(ws)


def test_split_resets_page_and_column_breaks_on_the_second_half_only(ws):
    doc = reopened(ws)
    element = doc.sections[0].paragraphs[1].element
    element.set("pageBreak", "1")
    element.set("columnBreak", "1")
    doc.sections[0].mark_dirty()
    doc.save_to_path(ws / FILE)
    te.split_paragraph_ext(FILE, 3, paragraph_index=1)
    assert (body(ws, 1).get("pageBreak"), body(ws, 1).get("columnBreak")) == ("1", "1") and (body(ws, 2).get("pageBreak"), body(ws, 2).get("columnBreak")) == ("0", "0")


def test_split_at_the_edges_leaves_an_empty_paragraph_with_a_run(ws):
    te.split_paragraph_ext(FILE, 0, paragraph_index=5)
    assert text_at(ws, paragraph_index=5) == "" and text_at(ws, paragraph_index=6) == "끝 문단" and len(body(ws, 5).findall(HP + "run")) == 1
    result = te.split_paragraph_ext(FILE, len("끝 문단"), paragraph_index=6)
    assert result["secondLength"] == 0 and text_at(ws, paragraph_index=6) == "끝 문단" and text_at(ws, paragraph_index=7) == "" and len(body(ws, 7).findall(HP + "run")) == 1
    assert count(section(ws), "endNote") == 2 and len(body_ids(ws)) == len(set(body_ids(ws)))
    check_saved(ws)


def test_split_around_a_tab_and_an_equation_neither_copies_nor_loses_them(ws):
    for position in (1, 2, 3):
        te.split_paragraph_ext(FILE, position, paragraph_index=2)
        total = body(ws, 2), body(ws, 3)
        assert count(total[0], "tab") + count(total[1], "tab") == 1 and count(total[0], "equation") + count(total[1], "equation") == 1
        assert text_at(ws, paragraph_index=2) + text_at(ws, paragraph_index=3) == "①\t보기 열거 둘"
        te.merge_paragraphs_ext(FILE, paragraph_index=2)
    assert text_at(ws, paragraph_index=2) == "①\t보기 열거 둘"
    # a tab at the cut: it belongs to the second half when the cut stands in front of it
    te.split_paragraph_ext(FILE, 1, paragraph_index=2)
    assert count(body(ws, 2), "tab") == 0 and count(body(ws, 3), "tab") == 1
    # the equation stands behind the text: an object at the cut stays in the first paragraph, so a cut at the very end leaves it there
    te.merge_paragraphs_ext(FILE, paragraph_index=2)
    te.split_paragraph_ext(FILE, len("①\t보기 열거 둘"), paragraph_index=2)
    assert count(body(ws, 2), "equation") == 1 and count(body(ws, 3), "equation") == 0 and text_at(ws, paragraph_index=3) == ""
    check_saved(ws)


def test_split_then_merge_gives_the_text_back(ws):
    original = all_texts(ws)
    for index, position in ((1, 7), (3, 4), (5, 2)):
        result = te.split_paragraph_ext(FILE, position, paragraph_index=index)
        merged = te.merge_paragraphs_ext(FILE, paragraph_index=index)
        assert merged["joinedAt"] == result["firstLength"] and merged["paragraphLength"] == result["firstLength"] + result["secondLength"]
    assert all_texts(ws) == original
    assert count(section(ws), "endNote") == 2 and count(body(ws, 1), "endNote") == 1 and count(section(ws), "footNote") == 1 and len(body_ids(ws)) == 6
    check_saved(ws)


def test_split_and_merge_inside_endnotes_cells_and_headers(ws):
    result = te.split_paragraph_ext(FILE, 3, endnote_number=1)
    assert result["newParagraph"] == {"endnote_number": 1, "endnote_paragraph_index": 1}
    assert text_at(ws, endnote_number=1) == "해설 " and text_at(ws, **result["newParagraph"]) == "열거 하나"
    assert count(body(ws, 1), "autoNum") == 1  # the number stays in the first paragraph
    notes = hwpx_layout.read_layout(ws / FILE, "notes", max_chars=10**9)["items"]
    assert [len(note["paragraphs"]) for note in notes if note["kind"] == "endnote"] == [2, 2]
    te.merge_paragraphs_ext(FILE, endnote_number=1)
    assert text_at(ws, endnote_number=1) == "해설 열거 하나"
    # the second endnote has two paragraphs of its own: join them
    assert te.merge_paragraphs_ext(FILE, endnote_number=2)["joinedAt"] == len("둘째 해설 열거") and text_at(ws, endnote_number=2) == "둘째 해설 열거해설 둘째 문단"
    result = te.split_paragraph_ext(FILE, 1, table_index=0, row=0, col=1)
    assert result["newParagraph"] == {"table_index": 0, "row": 0, "col": 1, "cell_paragraph_index": 1}
    assert text_at(ws, table_index=0, row=0, col=1) == "칸" and text_at(ws, **result["newParagraph"]) == " 열거 글"
    te.merge_paragraphs_ext(FILE, table_index=0, row=0, col=1)
    assert text_at(ws, table_index=0, row=0, col=1) == "칸 열거 글"
    result = te.split_paragraph_ext(FILE, 3, header_index=0)
    assert result["newParagraph"] == {"header_index": 0, "header_paragraph_index": 1}
    assert text_at(ws, header_index=0) == "머리말" and text_at(ws, header_index=0, header_paragraph_index=1) == " 열거"
    assert zipfile.ZipFile(ws / FILE).read("Contents/section0.xml").decode().count(" 열거</hp:t>") >= 2  # both copies of the header story
    result = te.split_paragraph_ext(FILE, 1, footer_index=0)
    assert result["newParagraph"] == {"footer_index": 0, "footer_paragraph_index": 1} and text_at(ws, footer_index=0) == "꼬"
    result = te.split_paragraph_ext(FILE, 2, footnote_number=1)
    assert result["newParagraph"] == {"footnote_number": 1, "footnote_paragraph_index": 1}
    assert text_at(ws, footnote_number=1) == "각주" and text_at(ws, **result["newParagraph"]) == " 열거"
    check_saved(ws)


def test_split_with_section_index_gives_it_back_in_the_new_address(ws):
    result = te.split_paragraph_ext(FILE, 2, paragraph_index=5, section_index=0)
    assert result["newParagraph"] == {"paragraph_index": 6, "section_index": 0}
    assert text_at(ws, **result["newParagraph"]) == "문단" and text_at(ws, paragraph_index=5) == "끝 "


def test_split_refuses_to_cut_a_hyperlink_in_two_and_allows_cuts_beside_it(ws):
    hwpx_inline.insert_inline_ext(FILE, [{"hyperlink": {"url": "https://example.com", "text": "링크"}}], position=1, paragraph_index=5)  # 끝[링크] 문단
    before = sha(ws)
    for position in (1, 2):
        with pytest.raises(ToolInputError, match="hyperlink or field"):
            te.split_paragraph_ext(FILE, position, paragraph_index=5)
    assert sha(ws) == before
    te.split_paragraph_ext(FILE, 3, paragraph_index=5)  # behind the link
    assert text_at(ws, paragraph_index=5) == "끝링크" and text_at(ws, paragraph_index=6) == " 문단" and count(body(ws, 5), "fieldBegin") == count(body(ws, 5), "fieldEnd") == 1
    te.split_paragraph_ext(FILE, 1, paragraph_index=6)  # inside a paragraph without a link
    check_saved(ws)


def test_split_and_merge_refusals(ws):
    before = sha(ws)
    length = len("끝 문단")
    bad = [
        (te.split_paragraph_ext, dict(position=0, paragraph_index=0), "section definition"), (te.split_paragraph_ext, dict(position=length + 1, paragraph_index=5), f"has {length} characters"),
        (te.split_paragraph_ext, dict(position=-1, paragraph_index=5), "position"), (te.split_paragraph_ext, dict(position=1), "give exactly one paragraph address group"),
        (te.split_paragraph_ext, dict(position=1, paragraph_index=99), "invalid paragraph_index"), (te.split_paragraph_ext, dict(position=9, endnote_number=1), "out of range"),
        (te.merge_paragraphs_ext, dict(paragraph_index=5), "no paragraph behind"), (te.merge_paragraphs_ext, dict(paragraph_index=4), "holds a table"),
        (te.merge_paragraphs_ext, dict(paragraph_index=3), "holds a table"), (te.merge_paragraphs_ext, dict(paragraph_index=0), "section definition"),
        (te.merge_paragraphs_ext, dict(endnote_number=1), "no paragraph behind"), (te.merge_paragraphs_ext, dict(header_index=0), "no paragraph behind"),
        (te.merge_paragraphs_ext, dict(table_index=0, row=0, col=1), "no paragraph behind"), (te.merge_paragraphs_ext, dict(), "give exactly one paragraph address group"),
    ]
    for tool, arguments, message in bad:
        with pytest.raises(ToolInputError, match=message):
            tool(FILE, **arguments)
    for tool, arguments in ((te.split_paragraph_ext, dict(position=2, paragraph_index=5)), (te.merge_paragraphs_ext, dict(paragraph_index=1))):
        with pytest.raises(ToolInputError, match="revision mismatch"):
            tool(FILE, **arguments, expected_revision="sha256:" + "0" * 64)
        assert tool(FILE, **arguments, dry_run=True)["dryRun"] is True
    assert sha(ws) == before


def test_splitting_the_section_definition_paragraph_in_the_middle_keeps_the_definition_in_front(ws):
    te.split_paragraph_ext(FILE, 1, paragraph_index=0)
    assert body(ws, 0).find(f".//{HP}secPr") is not None and count(section(ws), "secPr") == 1
    assert text_at(ws, paragraph_index=0) == "머" and text_at(ws, paragraph_index=1) == "리"
    check_saved(ws)


def test_merge_refuses_a_next_paragraph_that_would_lose_a_break_a_column_definition_or_a_reference(ws):
    doc = reopened(ws)
    second = doc.sections[0].paragraphs[2].element
    second.set("pageBreak", "1")
    doc.sections[0].mark_dirty()
    doc.save_to_path(ws / FILE)
    with pytest.raises(ToolInputError, match="set_paragraph_format_ext"):
        te.merge_paragraphs_ext(FILE, paragraph_index=1)
    doc = reopened(ws)
    second = doc.sections[0].paragraphs[2].element
    second.set("pageBreak", "0")
    second.set("columnBreak", "1")
    doc.sections[0].mark_dirty()
    doc.save_to_path(ws / FILE)
    with pytest.raises(ToolInputError, match="set_paragraph_format_ext"):
        te.merge_paragraphs_ext(FILE, paragraph_index=1)
    doc = reopened(ws)
    second = doc.sections[0].paragraphs[2].element
    second.set("columnBreak", "0")
    run = etree.SubElement(second, HP + "run", charPrIDRef="0")
    etree.SubElement(etree.SubElement(run, HP + "ctrl"), HP + "colPr", id="", type="NEWSPAPER", layout="LEFT", colCount="2", sameSz="1", sameGap="0")
    doc.sections[0].mark_dirty()
    doc.save_to_path(ws / FILE)
    with pytest.raises(ToolInputError, match="column definition"):
        te.merge_paragraphs_ext(FILE, paragraph_index=1)
    assert te.merge_paragraphs_ext(FILE, paragraph_index=2, dry_run=True)["dryRun"] is True  # the break and the definition do not matter for the paragraph in front
    # a field that points at the next paragraph with ?#<id> (a table-of-contents entry, a cross-reference)
    doc = reopened(ws)
    element = doc.sections[0].paragraphs[2].element
    element.remove(next(r for r in element.findall(HP + "run") if r.find(f".//{HP}colPr") is not None))
    doc.sections[0].mark_dirty()
    doc.save_to_path(ws / FILE)
    target = body(ws, 2).get("id")
    assert target not in (None, "", "0")
    te.merge_paragraphs_ext(FILE, paragraph_index=1, dry_run=True)  # nothing points at it yet
    hwpx_inline.insert_inline_ext(FILE, [{"hyperlink": {"url": f"?#{target}", "text": "목차"}}], position=0, paragraph_index=5)
    with pytest.raises(ToolInputError, match="points at the next paragraph"):
        te.merge_paragraphs_ext(FILE, paragraph_index=1)
    hwpx_inline.insert_inline_ext(FILE, [{"hyperlink": {"url": "?#12345", "text": "다른"}}], position=0, paragraph_index=3)
    assert te.merge_paragraphs_ext(FILE, paragraph_index=2, dry_run=True)["dryRun"] is True  # paragraph 3 has another id
    assert text_at(ws, paragraph_index=1) == "가나다 열거 라마 굵은 열거"
    check_saved(ws)


def test_merge_keeps_the_first_paragraph_shape_and_each_text_its_own_shape(ws):
    refs_one, refs_two = char_refs(body(ws, 1)), char_refs(body(ws, 2))
    one_para, one_style = body(ws, 1).get("paraPrIDRef"), body(ws, 1).get("styleIDRef")
    result = te.merge_paragraphs_ext(FILE, paragraph_index=1)
    assert result["joinedAt"] == len("가나다 열거 라마 굵은 열거") and text_at(ws, paragraph_index=1) == "가나다 열거 라마 굵은 열거①\t보기 열거 둘"
    merged = body(ws, 1)
    assert (merged.get("paraPrIDRef"), merged.get("styleIDRef")) == (one_para, one_style) and char_refs(merged) == refs_one + refs_two
    assert count(merged, "endNote") == 1 and count(merged, "tab") == 1 and count(merged, "equation") == 1 and merged.find(HP + "linesegarray") is None
    assert len(section(ws).findall(HP + "p")) == 5 and text_at(ws, paragraph_index=2) == "셋째 Hello hello"
    assert hwpx_layout.read_layout(ws / FILE, "body", max_chars=10**9)["total"] == 5
    check_saved(ws)


# ---------------------------------------------------------------- a file with two sections

@pytest.fixture()
def two(tmp_path, monkeypatch):
    """Section 0: '구역 영 열거'. Section 1: an empty first paragraph (it holds the section definition), '구역 일 문항 열거' with endnote 1 '구역 일 해설 열거', and '구역 일 둘째 열거'.
    Every paragraph of section 1 carries a layout cache."""
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("구역 영 열거")
    doc.add_section()
    host = doc.sections[1].add_paragraph("구역 일 문항 열거")
    doc.notes.add_endnote("구역 일 해설 열거", paragraph=host)
    doc.sections[1].add_paragraph("구역 일 둘째 열거")
    for paragraph in doc.sections[1].element.iter(HP + "p"):
        etree.SubElement(paragraph, HP + "linesegarray")
    doc.save_to_path(tmp_path / FILE)
    return tmp_path


def section_bytes(ws: Path, number: int) -> bytes:
    return zipfile.ZipFile(ws / FILE).read(f"Contents/section{number}.xml")


def test_edit_an_endnote_of_the_second_section_is_saved_in_that_section(two):
    zero = section_bytes(two, 0)
    result = te.edit_paragraph_text_ext(FILE, 8, 10, "고침", endnote_number=1)  # the number is the document's: section 0 has no endnote
    assert result["removedLength"] == 2 and text_at(two, endnote_number=1) == "구역 일 해설 고침" and section_bytes(two, 0) == zero
    result = te.edit_paragraph_text_ext(FILE, 0, 1, "후", section_index=1, endnote_number=1)  # the same note, counted inside the section
    assert text_at(two, endnote_number=1) == "후역 일 해설 고침" and section_bytes(two, 0) == zero
    note = section(two, 1).find(f".//{HP}endNote")
    assert all(p.find(HP + "linesegarray") is None for p in note.iter(HP + "p")) and section(two, 1).findall(HP + "p")[1].find(HP + "linesegarray") is not None
    with pytest.raises(ToolInputError, match="invalid endnote_number"):
        te.edit_paragraph_text_ext(FILE, 0, text="x", section_index=0, endnote_number=1)
    check_saved(two)


def test_split_a_body_paragraph_of_the_second_section_is_saved_in_that_section(two):
    zero = section_bytes(two, 0)
    result = te.split_paragraph_ext(FILE, 5, paragraph_index=1, section_index=1)  # section 1's second paragraph
    assert result["newParagraph"] == {"paragraph_index": 2, "section_index": 1} and (result["firstLength"], result["secondLength"]) == (5, 5)
    paragraphs = section(two, 1).findall(HP + "p")
    assert len(paragraphs) == 4 and section_bytes(two, 0) == zero
    assert [hwpx_locate.paragraph_text(hwpx_locate.resolve_paragraph(reopened(two), section_index=1, paragraph_index=i)) for i in range(4)] == ["", "구역 일 ", "문항 열거", "구역 일 둘째 열거"]
    assert paragraphs[1].find(HP + "linesegarray") is None and paragraphs[2].find(HP + "linesegarray") is None and paragraphs[3].find(HP + "linesegarray") is not None
    ids = [p.get("id") for p in paragraphs]
    assert len(ids) == len(set(ids)) and count(paragraphs[2], "endNote") == 1  # the endnote sits at the end of the text and moved with the second half
    assert text_at(two, **result["newParagraph"]) == "문항 열거"
    te.merge_paragraphs_ext(FILE, paragraph_index=1, section_index=1)
    assert len(section(two, 1).findall(HP + "p")) == 3 and text_at(two, section_index=1, paragraph_index=1) == "구역 일 문항 열거" and section_bytes(two, 0) == zero
    # the document-wide number reaches the same paragraph
    assert text_at(two, paragraph_index=2) == "구역 일 문항 열거"
    check_saved(two)


def test_replace_in_both_sections_and_in_one(two):
    result = te.replace_text_ext(FILE, "열거", "나열", section_index=1)
    assert result["replaced"] == 3 and all(location["address"]["section_index"] == 1 for location in result["locations"]) and text_at(two, paragraph_index=0) == "구역 영 열거"
    result = te.replace_text_ext(FILE, "나열|열거", "ㅇ", regex=True)
    assert result["replaced"] == 4 and result["byScope"]["body"] == 3 and result["byScope"]["endnotes"] == 1
    assert all("열거" not in text and "나열" not in text for text in all_texts(two).values())
    assert all(p.find(HP + "linesegarray") is None for p in section(two, 1).findall(HP + "p")[1:])
    check_saved(two)


# ---------------------------------------------------------------- redact_text_ext
# The detector is upstream's (hwpx_automation.office.compliance.pii.detect_pii, the one scan_personal_info uses); the numbers below are made up in the forms it finds.

def luhn_complete(body_digits: str) -> str:
    for last in "0123456789":
        total = sum((lambda n: n - 9 if n > 9 else n)(int(d) * (2 if place % 2 else 1)) for place, d in enumerate(reversed(body_digits + last)))
        if total % 10 == 0:
            return body_digits + last
    raise AssertionError


RRN, RRN_PLAIN = "900101-1234567", "9001011234567"
CARD16 = luhn_complete("411111111111111")
CARD_GROUPS = "-".join(CARD16[i:i + 4] for i in range(0, 16, 4))
CARD_SPACED = " ".join(CARD16[i:i + 4] for i in range(0, 16, 4))
PHONE, PHONE_PLAIN, EMAIL, EMAIL_SHORT = "010-1234-5678", "01698765432", "gil.dong_9@mail.example.co.kr", "a@b.co.kr"
REAL = [RRN, RRN_PLAIN, CARD16, CARD_GROUPS, CARD_SPACED, PHONE, PHONE_PLAIN, EMAIL, EMAIL_SHORT]
PREVIEW = f"미리보기에도 {PHONE} 가 있다".encode()


def add_pii(ws: Path) -> None:
    """Paragraphs 6-8 of the body, a table cell, an endnote and the header hold made-up personal information; the stored preview text quotes one number."""
    doc = reopened(ws)
    for index, text in enumerate((f"주민 {RRN} 전화 {PHONE} 메일 {EMAIL} 카드 {CARD_GROUPS}.", f"민증 {RRN_PLAIN}, 휴대 {PHONE_PLAIN}, 메일 {EMAIL_SHORT}", f"카드 {CARD_SPACED} / {CARD16}")):
        paragraph = doc.add_paragraph(text)
        etree.SubElement(paragraph.element, HP + "linesegarray")
    doc.package.write("Preview/PrvText.txt", PREVIEW)
    doc.save_to_path(ws / FILE)
    hwpx_edit.format_table_ext(FILE, 0, cells=[{"row": 1, "col": 0, "paragraphs": [{"text": f"칸 {PHONE}"}]}])
    te.edit_paragraph_text_ext(FILE, 0, 2, f"문의 {EMAIL}", endnote_number=1)
    te.edit_paragraph_text_ext(FILE, 0, 3, f"전화 {PHONE_PLAIN}", header_index=0)
    (ws / (FILE + ".bak")).unlink()


def masked(text: str, mask: str = "●") -> str:
    return "".join(mask if char.isalnum() else char for char in text)


def preview(ws: Path) -> bytes:
    return zipfile.ZipFile(ws / FILE).read("Preview/PrvText.txt")


def test_redact_masks_digits_and_letters_but_keeps_separators_and_length(ws):
    add_pii(ws)
    lengths = {key: len(text) for key, text in all_texts(ws).items()}
    result = te.redact_text_ext(FILE)
    assert result["found"] == result["redacted"] == 12 and result["byKind"] == {"rrn": 2, "phone": 4, "email": 3, "card": 3}
    assert result["byScope"] == {"body": 9, "table_cells": 1, "endnotes": 1, "footnotes": 0, "headers_footers": 1} and not result["truncated"]
    texts = all_texts(ws)
    assert {key: len(text) for key, text in texts.items()} == lengths  # the same number of characters everywhere
    joined = "\n".join(texts.values())
    assert not any(secret in joined for secret in REAL)
    assert f"주민 {masked(RRN)} 전화 {masked(PHONE)} 메일 {masked(EMAIL)} 카드 {masked(CARD_GROUPS)}." in joined
    assert masked(RRN) == "●●●●●●-●●●●●●●" and masked(EMAIL).count("@") == 1 and masked(EMAIL).count(".") == 4 and "_" in masked(EMAIL)
    assert text_at(ws, table_index=0, row=1, col=0) == f"칸 {masked(PHONE)}" and text_at(ws, header_index=0).startswith("전화 " + masked(PHONE_PLAIN))
    assert text_at(ws, endnote_number=1).startswith("문의 " + masked(EMAIL))
    assert all(set(finding) == {"kind", "address", "start", "end", "masked"} for finding in result["findings"])
    for index in (6, 7, 8):  # a changed paragraph loses its layout cache, which would no longer fit its text
        assert body(ws, index).find(HP + "linesegarray") is None
    check_saved(ws)


def test_redact_clears_the_preview_and_says_where_the_original_still_is(ws):
    add_pii(ws)
    assert preview(ws) == PREVIEW
    dry = te.redact_text_ext(FILE, dry_run=True)
    assert dry["previewCleared"] is False and "backupNote" not in dry and preview(ws) == PREVIEW
    result = te.redact_text_ext(FILE)
    assert result["previewCleared"] is True and ".bak" in result["backupNote"] and "delete_backups_ext" in result["backupNote"] and "undo_last_edit" in result["backupNote"]
    assert preview(ws) == b""
    bak = zipfile.ZipFile(ws / (FILE + ".bak"))
    assert bak.read("Preview/PrvText.txt") == PREVIEW  # the backup is the original, as the note says
    assert PHONE.encode() in bak.read("Contents/section0.xml")
    # nothing found: nothing is cleared or saved
    after = sha(ws)
    again = te.redact_text_ext(FILE)
    assert again["found"] == 0 and again["previewCleared"] is False and sha(ws) == after


def test_redact_response_never_holds_the_original_numbers(ws):
    add_pii(ws)
    dry = te.redact_text_ext(FILE, dry_run=True)
    real = te.redact_text_ext(FILE)
    for response in (dry, real):
        dumped = json.dumps(response, ensure_ascii=False)
        for secret in REAL + ["gil.dong", "mail.example", "1234-5678", "98765432", "900101", "1234567", CARD16[:8]]:
            assert secret not in dumped, secret
        assert "semanticDiff" not in dumped and "value" not in {key for finding in response["findings"] for key in finding} and response["rule"]
    assert dry["dryRun"] is True and dry["redacted"] == 0 and dry["found"] == real["found"] == 12


def test_redact_dry_run_and_nothing_found_leave_the_file_and_its_backup_alone(ws):
    add_pii(ws)
    before = sha(ws)
    result = te.redact_text_ext(FILE, dry_run=True)
    assert result["found"] == 12 and len(result["findings"]) == 12 and sha(ws) == before and not (ws / (FILE + ".bak")).exists()
    te.redact_text_ext(FILE)
    backup, after = (ws / (FILE + ".bak")).read_bytes(), sha(ws)
    empty = te.redact_text_ext(FILE)
    assert empty["found"] == 0 and empty["saved"] is False and "nothing was changed" in empty["note"]
    assert sha(ws) == after and (ws / (FILE + ".bak")).read_bytes() == backup  # the backup of the real redaction survives
    with pytest.raises(ToolInputError, match="revision mismatch"):
        te.redact_text_ext(FILE, expected_revision="sha256:" + "0" * 64)


NOT_FOUND = [  # what upstream's detector does not report: not masked
    "900101-5234567", "90010-1234567", "900101-123456",  # sex digit 5, too few digits
    "9010-1234-5678", "010-1234-56789", "012-123-4567", "02-345-6789",  # a digit glued to the number, a prefix that is not a mobile one, a landline
    CARD16[:-1] + str((int(CARD16[-1]) + 1) % 10),  # fails Luhn
    "4111-1111-1111", "gil@host",  # too short, no dot in the domain
]


def test_what_the_detector_does_not_report_is_not_masked(ws):
    doc = reopened(ws)
    for text in NOT_FOUND:
        doc.add_paragraph(f"값 {text} 끝")
    doc.save_to_path(ws / FILE)
    before = sha(ws)
    assert te.redact_text_ext(FILE)["found"] == 0 and sha(ws) == before


def test_kinds_scopes_and_mask_options(ws):
    add_pii(ws)
    result = te.redact_text_ext(FILE, kinds=["email"], mask="*", scopes=["body"])
    assert result["byKind"] == {"rrn": 0, "phone": 0, "email": 2, "card": 0} and result["byScope"] == {"body": 2}
    assert result["findings"][0]["masked"] == masked(EMAIL, "*") and masked(EMAIL, "*").startswith("***.****_*@")
    in_body = "\n".join(hwpx_locate.paragraph_text(p) for _, p in hwpx_locate.iter_paragraphs(reopened(ws), ["body"]))
    assert masked(EMAIL, "*") in in_body and EMAIL not in in_body and EMAIL_SHORT not in in_body and RRN in in_body and PHONE in in_body
    assert EMAIL in text_at(ws, endnote_number=1)  # outside the chosen scope
    assert preview(ws) == b""  # a real masking clears the preview whatever the kinds
    te.redact_text_ext(FILE, kinds=["rrn", "phone"], scopes=["body", "table_cells"])
    assert RRN not in "\n".join(all_texts(ws).values()) and PHONE_PLAIN in text_at(ws, header_index=0)
    check_saved(ws)


def test_redact_refusals(ws):
    add_pii(ws)
    before = sha(ws)
    bad = [
        (dict(mask="A"), "mask"), (dict(mask="7"), "mask"), (dict(mask="ab"), "mask"), (dict(mask=""), "mask"), (dict(mask=" "), "mask"), (dict(mask="가"), "mask"),
        (dict(kinds=["passport"]), "kinds"), (dict(kinds=["ssn"]), "kinds"), (dict(kinds=[]), "kinds"), (dict(scopes=["nowhere"]), "scopes"),
    ]
    for arguments, message in bad:
        with pytest.raises(ToolInputError, match=message):
            te.redact_text_ext(FILE, **arguments)
    assert sha(ws) == before and preview(ws) == PREVIEW


def test_redact_in_a_paragraph_with_a_tab_and_several_runs_keeps_the_rest(ws):
    doc = reopened(ws)
    paragraph = doc.add_paragraph("연락\t")
    paragraph.add_run(PHONE[:6], char_pr_id_ref=doc.styles.ensure_run(bold=True))  # a number cut over two runs
    paragraph.add_run(PHONE[6:] + " 끝")
    paragraph.add_equation("y")
    etree.SubElement(paragraph.element, HP + "linesegarray")
    doc.save_to_path(ws / FILE)
    last = len(section(ws).findall(HP + "p")) - 1
    result = te.redact_text_ext(FILE)
    assert result["found"] == 1 and text_at(ws, paragraph_index=last) == "연락\t" + masked(PHONE) + " 끝" and count(body(ws, last), "tab") == 1 and count(body(ws, last), "equation") == 1
    assert body(ws, last).find(HP + "linesegarray") is None
    check_saved(ws)


def test_findings_are_listed_up_to_one_hundred_and_counted_in_full(ws):
    doc = reopened(ws)
    for _ in range(60):
        doc.add_paragraph(f"{PHONE} {PHONE}")
    doc.save_to_path(ws / FILE)
    result = te.redact_text_ext(FILE, dry_run=True)
    assert result["found"] == 120 and len(result["findings"]) == 100 and result["truncated"] is True


def test_find_personal_info_is_upstreams_detector_with_our_kind_names():
    assert te.find_personal_info(f"{RRN} {PHONE} {EMAIL_SHORT} {CARD_GROUPS}") == [("rrn", 0, 14), ("phone", 15, 28), ("email", 29, 38), ("card", 39, 58)]
    assert te.find_personal_info(f"{RRN} {PHONE}", ["phone"]) == [("phone", 15, 28)]
    assert te.find_personal_info("계좌번호: 123-456-789012 주소: 서울 강남구 성명: 홍길동") == []  # the label-gated kinds of upstream's detector are off
