"""hwpx_page의 쓰기 도구. 실행(패키지된 환경 그대로):
venv/bin/python -m pytest toolkit/tests/test_hwpx_page.py -q -p no:cacheprovider"""
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_page  # noqa: E402



def _new(tmp_path, monkeypatch, sections: int = 1):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("가나다")
    doc.add_paragraph("두 번째 문단")
    for number in range(1, sections):
        doc.add_section()
        doc.add_paragraph(f"구역 {number}", section=doc.sections[number])
    doc.save_to_path(tmp_path / "doc.hwpx")
    return tmp_path


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    return _new(tmp_path, monkeypatch)


@pytest.fixture()
def ws2(tmp_path, monkeypatch):
    return _new(tmp_path, monkeypatch, sections=2)


def sec(ws: Path, index: int = 0) -> str:
    return zipfile.ZipFile(ws / "doc.hwpx").read(f"Contents/section{index}.xml").decode()


def attrs(xml: str, tag: str, nth: int = 0) -> dict[str, str]:
    return dict(re.findall(r'([\w:]+)="([^"]*)"', re.findall(rf"<hp:{tag} ([^>]*?)/?>", xml)[nth]))


def raw(ws: Path) -> bytes:
    return (ws / "doc.hwpx").read_bytes()


# ---- set_page_options_ext ----------------------------------------------------------------------

def test_line_numbers_shape_and_show_flag_stored_as_01(ws):
    out = hwpx_page.set_page_options_ext(
        "doc.hwpx", line_numbers={"restart_type": 1, "count_by": 5, "distance": 850, "start_number": 1, "show": True})
    xml = sec(ws)
    assert attrs(xml, "lineNumberShape") == {"restartType": "1", "countBy": "5", "distance": "850", "startNumber": "1"}
    assert attrs(xml, "visibility")["showLineNumber"] == "1"
    assert out["secPr"]["lineNumberShape"]["countBy"] == "5" and out["secPr"]["visibility"]["showLineNumber"] == "1"
    hwpx_page.set_page_options_ext("doc.hwpx", line_numbers={"show": False})
    assert attrs(sec(ws), "visibility")["showLineNumber"] == "0"
    assert attrs(sec(ws), "lineNumberShape")["countBy"] == "5"  # what is not passed stays


def test_grid_and_wongoji(ws):
    hwpx_page.set_page_options_ext("doc.hwpx", grid={"line": 1000, "char": 500, "wongoji": True})
    assert attrs(sec(ws), "grid") == {"lineGrid": "1000", "charGrid": "500", "wonggojiFormat": "1"}
    hwpx_page.set_page_options_ext("doc.hwpx", grid={"wongoji": False})
    assert attrs(sec(ws), "grid") == {"lineGrid": "1000", "charGrid": "500", "wonggojiFormat": "0"}


def test_text_direction_first_page_hiding_and_start_numbers(ws):
    hwpx_page.set_page_options_ext(
        "doc.hwpx", text_direction="VERTICAL",
        hide_first={"header": True, "footer": True, "master_page": False, "page_num": True, "empty_line": True},
        start_numbering={"page": 3, "picture": 1, "table": 2, "equation": 4, "page_starts_on": "ODD"})
    xml = sec(ws)
    assert attrs(xml, "secPr")["textDirection"] == "VERTICAL"
    visibility = attrs(xml, "visibility")
    assert (visibility["hideFirstHeader"], visibility["hideFirstFooter"], visibility["hideFirstMasterPage"],
            visibility["hideFirstPageNum"], visibility["hideFirstEmptyLine"], visibility["showLineNumber"]) == ("1", "1", "0", "1", "1", "0")
    assert attrs(xml, "startNum") == {"pageStartsOn": "ODD", "page": "3", "pic": "1", "tbl": "2", "equation": "4"}
    head = xml.split("</hp:secPr>")[0]
    assert "true" not in head and "false" not in head


def test_every_boolean_in_touched_elements_is_01_even_when_the_file_had_true_false(ws):
    path = ws / "doc.hwpx"
    doc = HwpxDocument.open(path)
    doc.page.set_visibility(hide_first_header=True)  # the library's own notation: true/false
    doc.page.set_grid(wonggoji_format=True)
    doc.save_to_path(path)
    assert attrs(sec(ws), "visibility")["hideFirstHeader"] == "true"
    hwpx_page.set_page_options_ext("doc.hwpx", hide_first={"footer": True}, grid={"line": 10})
    xml = sec(ws)
    assert set(attrs(xml, "visibility").values()) - {"SHOW_ALL"} <= {"0", "1"} and attrs(xml, "visibility")["hideFirstHeader"] == "1"
    assert attrs(xml, "grid")["wonggojiFormat"] == "1"


def test_only_the_chosen_section_changes(ws2):
    hwpx_page.set_page_options_ext(
        "doc.hwpx", section_index=1, line_numbers={"count_by": 2, "show": True}, text_direction="VERTICALALL",
        grid={"wongoji": True}, hide_first={"header": True}, start_numbering={"page": 7})
    first, second = sec(ws2, 0), sec(ws2, 1)
    assert attrs(second, "lineNumberShape")["countBy"] == "2" and attrs(second, "visibility")["showLineNumber"] == "1"
    assert attrs(second, "secPr")["textDirection"] == "VERTICALALL" and attrs(second, "startNum")["page"] == "7"
    assert attrs(second, "grid")["wonggojiFormat"] == "1" and attrs(second, "visibility")["hideFirstHeader"] == "1"
    assert attrs(first, "lineNumberShape")["countBy"] == "0" and attrs(first, "visibility")["showLineNumber"] == "0"
    assert attrs(first, "secPr")["textDirection"] == "HORIZONTAL" and attrs(first, "startNum")["page"] == "0"
    assert attrs(first, "grid")["wonggojiFormat"] == "0" and attrs(first, "visibility")["hideFirstHeader"] == "0"
    hwpx_page.set_page_options_ext("doc.hwpx", line_numbers={"count_by": 9})  # default: the first section
    assert attrs(sec(ws2, 0), "lineNumberShape")["countBy"] == "9" and attrs(sec(ws2, 1), "lineNumberShape")["countBy"] == "2"


def test_page_options_dry_run_saves_nothing(ws):
    before = raw(ws)
    out = hwpx_page.set_page_options_ext("doc.hwpx", line_numbers={"count_by": 3, "show": True}, dry_run=True)
    assert out["secPr"]["lineNumberShape"]["countBy"] == "3" and raw(ws) == before


@pytest.mark.parametrize("bad", [
    {},  # nothing given
    dict(line_numbers={}), dict(grid={"line": None}), dict(hide_first={}),
    dict(line_numbers={"bogus": 1}), dict(grid={"lines": 1}), dict(hide_first={"first": True}), dict(start_numbering={"pages": 1}),
    dict(line_numbers={"show": 1}), dict(line_numbers={"show": "yes"}), dict(grid={"wongoji": 1}), dict(hide_first={"header": "true"}),
    dict(line_numbers={"restart_type": 2}), dict(line_numbers={"restart_type": 3}), dict(line_numbers={"restart_type": -1}), dict(line_numbers={"restart_type": True}),
    dict(line_numbers={"count_by": 65536}), dict(line_numbers={"start_number": -1}), dict(line_numbers={"distance": 2.5}),
    dict(grid={"line": -1}), dict(grid={"char": 65536}), dict(start_numbering={"page": 65536}), dict(start_numbering={"table": -2}),
    dict(start_numbering={"page_starts_on": "LEFT"}), dict(text_direction="DIAGONAL"),
    dict(section_index=1, text_direction="VERTICAL"), dict(section_index=-1, text_direction="VERTICAL"),
    dict(section_index=True, text_direction="VERTICAL"),
])
def test_page_options_refusals_leave_the_file_alone(ws, bad):
    before = raw(ws)
    with pytest.raises(hwpx_page.ToolInputError) as error:
        hwpx_page.set_page_options_ext("doc.hwpx", **bad)
    assert str(ws) not in str(error.value) and raw(ws) == before


def test_page_options_error_names_the_argument_and_range(ws2):
    with pytest.raises(hwpx_page.ToolInputError, match=r"line_numbers\.count_by.*0 to 65535.*70000"):
        hwpx_page.set_page_options_ext("doc.hwpx", line_numbers={"count_by": 70000})
    with pytest.raises(hwpx_page.ToolInputError, match=r"section_index 2.*2 sections: 0-1"):
        hwpx_page.set_page_options_ext("doc.hwpx", section_index=2, grid={"line": 1})
    with pytest.raises(hwpx_page.ToolInputError, match="expected_revision"):
        hwpx_page.set_page_options_ext("doc.hwpx", grid={"line": 1}, expected_revision="nope")


# ---- add_page_control_ext ----------------------------------------------------------------------

def test_hide_page_elements_on_one_paragraph_as_01(ws):
    out = hwpx_page.add_page_control_ext("doc.hwpx", 1, hide={"header": True, "page_num": True, "footer": False})
    xml = sec(ws)
    assert attrs(xml, "pageHiding") == {
        "hideHeader": "1", "hideFooter": "0", "hideMasterPage": "0", "hideBorder": "0", "hideFill": "0", "hidePageNum": "1"}
    assert re.search(r"<hp:t>두 번째 문단</hp:t></hp:run><hp:run [^>]*><hp:ctrl><hp:pageHiding ", xml)  # after the paragraph's text
    assert out["hide"] == ["header", "page_num"] and len(re.findall(r"<hp:pageHiding ", xml)) == 1


def test_restart_page_number_defaults_and_kinds(ws):
    hwpx_page.add_page_control_ext("doc.hwpx", 0, restart_page_number={"number": 5})
    hwpx_page.add_page_control_ext("doc.hwpx", 1, restart_page_number={})
    hwpx_page.add_page_control_ext("doc.hwpx", 1, restart_page_number={"number": 2, "kind": "table"})
    xml = sec(ws)
    assert [attrs(xml, "newNum", index) for index in range(3)] == [
        {"num": "5", "numType": "PAGE"}, {"num": "1", "numType": "PAGE"}, {"num": "2", "numType": "TABLE"}]


def test_hide_and_restart_together_in_the_second_section(ws2):
    out = hwpx_page.add_page_control_ext(
        "doc.hwpx", 3, hide={"master_page": True, "border": True, "fill": True}, restart_page_number={"number": 10})
    assert "<hp:pageHiding " not in sec(ws2, 0) and "<hp:newNum " not in sec(ws2, 0)
    xml = sec(ws2, 1)
    assert attrs(xml, "pageHiding")["hideMasterPage"] == "1" and attrs(xml, "pageHiding")["hideHeader"] == "0"
    assert attrs(xml, "newNum") == {"num": "10", "numType": "PAGE"} and out["restart_page_number"] == {"number": 10, "kind": "PAGE"}
    assert xml.index("구역 1") < xml.index("<hp:pageHiding")  # the paragraph of section 1


def test_page_control_dry_run_saves_nothing(ws):
    before = raw(ws)
    out = hwpx_page.add_page_control_ext("doc.hwpx", 0, hide={"footer": True}, dry_run=True)
    assert out["hide"] == ["footer"] and raw(ws) == before


@pytest.mark.parametrize("bad", [
    dict(paragraph_index=0),  # nothing given
    dict(paragraph_index=0, hide={}), dict(paragraph_index=0, hide={"header": False, "footer": False}),
    dict(paragraph_index=0, hide={"header": False}, restart_page_number={"number": 2}),
    dict(paragraph_index=0, hide={"header": 1}), dict(paragraph_index=0, hide={"top": True}),
    dict(paragraph_index=0, restart_page_number={"num": 2}), dict(paragraph_index=0, restart_page_number={"number": 65536}),
    dict(paragraph_index=0, restart_page_number={"number": -1}), dict(paragraph_index=0, restart_page_number={"number": True}),
    dict(paragraph_index=0, restart_page_number={"kind": "CHAPTER"}),
    dict(paragraph_index=2, hide={"header": True}), dict(paragraph_index=-1, hide={"header": True}),
    dict(paragraph_index=True, hide={"header": True}),
])
def test_page_control_refusals_leave_the_file_alone(ws, bad):
    before = raw(ws)
    with pytest.raises(hwpx_page.ToolInputError) as error:
        hwpx_page.add_page_control_ext("doc.hwpx", **bad)
    assert str(ws) not in str(error.value) and raw(ws) == before


def test_second_control_failing_saves_neither(ws):
    before = raw(ws)
    with pytest.raises(hwpx_page.ToolInputError):
        hwpx_page.add_page_control_ext("doc.hwpx", 0, hide={"header": True}, restart_page_number={"kind": "CHAPTER"})
    assert raw(ws) == before


def test_page_control_error_names_the_argument(ws):
    with pytest.raises(hwpx_page.ToolInputError, match=r"paragraph_index 9.*2 body paragraphs"):
        hwpx_page.add_page_control_ext("doc.hwpx", 9, hide={"header": True})
    with pytest.raises(hwpx_page.ToolInputError, match=r"restart_page_number\.number.*65535"):
        hwpx_page.add_page_control_ext("doc.hwpx", 0, restart_page_number={"number": 99999})
    with pytest.raises(hwpx_page.ToolInputError, match="hide must set at least one"):
        hwpx_page.add_page_control_ext("doc.hwpx", 0, hide={"header": False})
