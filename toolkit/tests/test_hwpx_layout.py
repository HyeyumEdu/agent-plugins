"""hwpx_layout.read_layout: 포크로 만든 작은 문서의 서식이 그대로 읽히는지. 실행: venv/bin/python -m pytest toolkit/tests"""
import sys
from pathlib import Path

import pytest
from hwpx import HwpxDocument

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_layout  # noqa: E402


@pytest.fixture()
def sample(tmp_path):
    doc = HwpxDocument.new()
    first = doc.paragraphs[0]
    first.add_run("발문 가나다라마바사 아자차카타파하")
    doc.styles.apply_paragraph_format(
        paragraphs=[first], alignment="JUSTIFY", line_spacing_percent=170, first_line_indent_mm=-4.0,
        indent_left_mm=3.0, break_non_latin_word="KEEP_WORD")
    holder = doc.add_paragraph("")
    table = holder.add_table(2, 2, width=20000, height=4000)
    table.set_cell_text(0, 0, "표 칸")
    note = doc.notes.add_endnote(" 정답 ③ 해설 문장이 길어도 끝까지 읽혀야 한다 " * 8, paragraph=first)
    assert note is not None
    path = tmp_path / "sample.hwpx"
    doc.save_to_path(path)
    return path


def test_overview_has_page_and_counts(sample):
    out = hwpx_layout.read_layout(sample)
    assert out["part"] == "overview" and out["counts"]["tables"] == 1 and out["counts"]["endnotes"] == 1
    assert out["page"]["width"] and "HWPUNIT" in out["units"]


def test_body_paragraph_shape_is_interned_and_readable(sample):
    out = hwpx_layout.read_layout(sample, "body")
    shape = out["shapes"][out["items"][0]["paraPr"]]
    assert shape["align"] == "JUSTIFY" and shape["lineSpacing"] == ["PERCENT", "170"]
    assert shape["breakNonLatin"] == "KEEP_WORD" and int(shape["indent"]["first"]) < 0


def test_tables_page(sample):
    out = hwpx_layout.read_layout(sample, "tables")
    assert out["total"] == 1 and out["nextOffset"] is None
    assert any(c["text"] == "표 칸" for c in out["items"][0]["cells"])


def test_notes_keep_full_text(sample):
    out = hwpx_layout.read_layout(sample, "notes")
    text = "".join(p["text"] for p in out["items"][0]["paragraphs"])
    assert out["items"][0]["kind"] == "endnote" and text.count("정답 ③") == 8


def test_paging_and_bad_arguments(sample):
    assert hwpx_layout.read_layout(sample, "body", offset=1000)["returned"] == 0
    with pytest.raises(ValueError):
        hwpx_layout.read_layout(sample, "nope")
    with pytest.raises(ValueError):
        hwpx_layout.read_layout(sample, section=5)


def test_budget_shrinks_page_and_resumes(sample):
    first = hwpx_layout.read_layout(sample, "body", max_chars=1)
    assert first["returned"] == 1 and first["nextOffset"] == 1
    rest = hwpx_layout.read_layout(sample, "body", offset=first["nextOffset"])
    assert first["returned"] + rest["returned"] == first["total"]
