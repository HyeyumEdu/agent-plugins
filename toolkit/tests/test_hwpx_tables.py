"""hwpx_tables: edit_table_structure_ext (+ split_table_ext, merge_table_with_next_ext). 실행: venv/bin/python -m pytest toolkit/tests/test_hwpx_tables.py"""
import hashlib
import json
import sys
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.tools.id_integrity import check_id_integrity
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_layout  # noqa: E402
import hwpx_locate  # noqa: E402
import hwpx_tables  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def make(tmp_path, rows=3, cols=3, widths=(9000, 9000, 9000)):
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    holder = doc.add_paragraph("")
    table = holder.add_table(rows, cols, width=sum(widths), height=3000 * rows)
    for r in range(rows):
        for c in range(cols):
            table.set_cell_text(r, c, f"{r}{c}")
    doc.add_paragraph("표 뒤 문단")
    doc.save_to_path(tmp_path / "doc.hwpx")


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    make(tmp_path)
    return tmp_path


def sha(ws: Path) -> str:
    return hashlib.sha256((ws / "doc.hwpx").read_bytes()).hexdigest()


def grid(ws: Path, index: int = 0) -> dict:
    """Rows/cols of the table and its cells as {(row, col): (text, rowSpan, colSpan, width)}; checks the file opens and ids hold."""
    doc = HwpxDocument.open(ws / "doc.hwpx")
    assert check_id_integrity(doc).ok
    table = hwpx_locate.table_at(doc, index).element
    cells = {}
    for tc in table.iter(HP + "tc"):
        addr, span, size = tc.find(HP + "cellAddr"), tc.find(HP + "cellSpan"), tc.find(HP + "cellSz")
        cells[(int(addr.get("rowAddr")), int(addr.get("colAddr")))] = ("".join(t.text or "" for t in tc.iter(HP + "t")), int(span.get("rowSpan")), int(span.get("colSpan")), int(size.get("width")))
    return {"rows": int(table.get("rowCnt")), "cols": int(table.get("colCnt")), "cells": cells, "width": int(table.find(HP + "sz").get("width"))}


def test_insert_columns_clones_the_neighbor(ws):
    before = grid(ws)
    result = hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 1, "count": 1, "side": "right", "blank": False}])
    after = grid(ws)
    assert (result["rows"], result["cols"]) == (3, 4) and (after["rows"], after["cols"]) == (3, 4)
    assert [after["cells"][(0, c)][0] for c in range(4)] == ["00", "01", "01", "02"]  # the new column copies column 1's text
    assert after["cells"][(0, 2)][3] == before["cells"][(0, 1)][3] and after["width"] == before["width"] + before["cells"][(0, 1)][3]


def test_insert_blank_columns_to_the_left(ws):
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 0, "side": "left", "blank": True, "count": 2}])
    after = grid(ws)
    assert after["cols"] == 5 and [after["cells"][(1, c)][0] for c in range(5)] == ["", "", "10", "11", "12"]


def test_insert_and_delete_rows(ws):
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_rows", "row": 0, "side": "above", "blank": True}, {"op": "delete_rows", "rows": [3]}])
    after = grid(ws)
    assert after["rows"] == 3 and [after["cells"][(r, 0)][0] for r in range(3)] == ["", "00", "10"]


def test_delete_columns_keeps_the_width(ws):
    before = grid(ws)
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "delete_columns", "columns": 1}])
    after = grid(ws)
    assert after["cols"] == 2 and after["width"] == before["width"] and [after["cells"][(0, c)][0] for c in range(2)] == ["00", "02"]
    assert sum(after["cells"][(0, c)][3] for c in range(2)) == before["width"]


def test_split_cell_into_rows_and_columns(ws):
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "split_cell", "row": 0, "col": 0, "rows": 1, "cols": 2}])
    after = grid(ws)
    assert after["cols"] == 4 and after["cells"][(0, 0)][0] == "00" and after["cells"][(0, 1)][0] == ""
    assert after["cells"][(0, 0)][3] + after["cells"][(0, 1)][3] == 9000
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "split_cell", "row": 1, "col": 3, "rows": 2, "cols": 1}])
    assert grid(ws)["rows"] == 4


def test_a_merged_cell_grows_over_new_columns_and_splits_back(ws):
    from hwpx_edit import format_table_ext
    format_table_ext("doc.hwpx", 0, merges=[[0, 0, 0, 1]])
    assert grid(ws)["cells"][(0, 0)][2] == 2
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 0, "side": "right", "blank": True}])
    assert grid(ws)["cells"][(0, 0)][2] == 3
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "split_cell", "row": 0, "col": 0, "rows": 1, "cols": 3}])
    assert grid(ws)["cells"][(0, 0)][2] == 1


def test_steps_run_in_order_and_all_or_nothing(ws):
    before = sha(ws)
    with pytest.raises(ToolInputError, match=r"ops\[1\] \(delete_rows\)"):
        hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 0}, {"op": "delete_rows", "rows": [0, 1, 2]}])
    assert sha(ws) == before  # the first step was not saved either


def test_refusals(ws):
    before = sha(ws)
    bad = [
        ([], "non-empty list"), ("x", "non-empty list"), ([{"op": "explode"}], "ops\\[0\\].op must be one of"), ([{"insert_rows": 1}], "ops\\[0\\].op"),
        ([{"op": "insert_rows"}], "needs \\['row'\\]"), ([{"op": "insert_rows", "row": 0, "side": "left"}], "side must be"), ([{"op": "insert_rows", "row": -1}], "whole number"),
        ([{"op": "insert_rows", "row": 0, "count": 0}], "count"), ([{"op": "insert_columns", "column": 0, "wide": 1}], "unknown"),
        ([{"op": "delete_rows", "rows": []}], "non-empty list"), ([{"op": "delete_columns", "columns": ["a"]}], "whole number"),
        ([{"op": "split_cell", "row": 0, "col": 0}], "nothing to split"), ([{"op": "split_cell", "row": 0, "col": 0, "rows": 64}], "1-63"),
        ([{"op": "insert_rows", "row": 9}], "was refused"), ([{"op": "delete_columns", "columns": [0, 1, 2]}], "was refused"),
    ]
    for ops, message in bad:
        with pytest.raises(ToolInputError, match=message):
            hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, ops)
    with pytest.raises(ToolInputError, match="invalid table_index"):
        hwpx_tables.edit_table_structure_ext("doc.hwpx", 4, [{"op": "insert_rows", "row": 0}])
    with pytest.raises(ToolInputError, match="revision mismatch"):
        hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_rows", "row": 0}], expected_revision="sha256:" + "0" * 64)
    assert sha(ws) == before


def test_dry_run_changes_nothing_and_reports(ws):
    before = sha(ws)
    result = hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 2}], dry_run=True)
    assert result["dryRun"] is True and result["cols"] == 4 and sha(ws) == before


def test_text_around_the_table_and_reading_back(ws):
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 2, "blank": True}])
    body = hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)["items"]
    assert body[0]["text"] == "머리" and body[-1]["text"] == "표 뒤 문단"
    tables = hwpx_layout.read_layout(ws / "doc.hwpx", "tables", max_chars=10**9)["items"]
    assert tables[0]["cols"] == 4 and tables[0]["rows"] == 3


def test_new_rows_and_columns_are_blank_unless_copying_is_asked_for(ws):
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_rows", "row": 0}, {"op": "insert_columns", "column": 0}])
    after = grid(ws)
    assert after["rows"] == 4 and after["cols"] == 4
    assert [after["cells"][(0, 0)][0], after["cells"][(1, 0)][0], after["cells"][(0, 1)][0], after["cells"][(2, 0)][0]] == ["00", "", "", "10"]  # new row 1 and new column 1 are empty


def test_keep_width_shrinks_the_columns_instead_of_widening_the_table(ws):
    before = grid(ws)
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 2, "keep_width": True}])
    after = grid(ws)
    assert after["cols"] == 4 and after["width"] == before["width"]
    assert sum(after["cells"][(0, c)][3] for c in range(4)) == before["width"]
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 2}])
    assert grid(ws)["width"] > before["width"]  # without it the table grows by the new column


def test_copying_a_cell_with_an_equation_is_refused_but_blank_works(ws):
    from hwpx_inline import insert_inline_ext
    insert_inline_ext("doc.hwpx", [{"equation": "x^{2}"}], position=0, table_index=0, row=0, col=1)
    with pytest.raises(ToolInputError, match="refused"):
        hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 1, "blank": False}])
    hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "insert_columns", "column": 1}])
    assert grid(ws)["cols"] == 4


def test_deleting_cells_with_notes_renumbers_and_reports(ws):
    doc = HwpxDocument.open(ws / "doc.hwpx")
    host = doc.add_paragraph("앞 문단 해설 있음")
    doc.notes.add_endnote("바깥 해설", paragraph=host)
    inner = hwpx_locate.table_at(doc, 0).cell(1, 1).paragraphs[0]
    doc.notes.add_endnote("칸 안 해설", paragraph=inner)
    doc.save_to_path(ws / "doc.hwpx")
    result = hwpx_tables.edit_table_structure_ext("doc.hwpx", 0, [{"op": "delete_rows", "rows": [1]}])
    assert result["removedNotes"] == 1
    reopened = HwpxDocument.open(ws / "doc.hwpx")
    assert [n.get("number") for n in reopened.sections[0].element.iter(HP + "endNote")] == ["1"]


# ---------------------------------------------------------------- split_table_ext / merge_table_with_next_ext

def body_texts(ws: Path) -> list[str]:
    return [item["text"] for item in hwpx_layout.read_layout(ws / "doc.hwpx", "body", max_chars=10**9)["items"]]


def table_facts(ws: Path) -> list[dict]:
    """rows, cols, declared height, texts by row and the rowAddr values of every table, in document order."""
    doc = HwpxDocument.open(ws / "doc.hwpx")
    assert check_id_integrity(doc).ok
    facts = []
    for table in hwpx_locate.all_tables(doc):
        element = table.element
        rows = [["".join(t.text or "" for t in tc.iter(HP + "t")) for tc in tr.findall(HP + "tc")] for tr in element.findall(HP + "tr")]
        addrs = sorted({int(tc.find(HP + "cellAddr").get("rowAddr")) for tc in element.iter(HP + "tc")})
        facts.append({"rows": int(element.get("rowCnt")), "cols": int(element.get("colCnt")), "height": int(element.find(HP + "sz").get("height")), "text": rows, "addrs": addrs, "id": element.get("id")})
    return facts


@pytest.fixture()
def four(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    make(tmp_path, rows=4)
    return tmp_path


def test_split_table_at_a_row(four):
    original = table_facts(four)[0]
    result = hwpx_tables.split_table_ext("doc.hwpx", 0, 2)
    upper, lower = table_facts(four)
    assert (result["upperTable"], result["lowerTable"], result["upperRows"], result["lowerRows"]) == (0, 1, 2, 2)
    assert upper["text"] == original["text"][:2] and lower["text"] == original["text"][2:]
    assert upper["addrs"] == [0, 1] and lower["addrs"] == [0, 1] and upper["cols"] == lower["cols"] == 3
    assert upper["height"] + lower["height"] == original["height"] and upper["height"] == round(original["height"] / 2)
    assert upper["id"] != lower["id"]
    assert body_texts(four) == ["머리", "", "", "표 뒤 문단"]  # the new paragraph holds only the lower table


def test_split_and_merge_drop_the_stale_line_cache(four):
    def with_cache(host_count: int) -> int:
        import zipfile
        root = etree.fromstring(zipfile.ZipFile(four / "doc.hwpx").read("Contents/section0.xml"))
        return sum(len(p.findall(f"{HP}linesegarray")) for p in root.findall(HP + "p") if p.find(f"{HP}run/{HP}tbl") is not None)

    doc = HwpxDocument.open(four / "doc.hwpx")
    host = hwpx_locate.table_at(doc, 0).paragraph.element
    cache = etree.SubElement(host, HP + "linesegarray")
    etree.SubElement(cache, HP + "lineseg", {"textpos": "0", "vertpos": "0", "vertsize": "1000", "textheight": "1000", "baseline": "850", "spacing": "600", "horzpos": "0", "horzsize": "42000", "flags": "0"})
    hwpx_locate.table_at(doc, 0).paragraph.section.mark_dirty()
    doc.save_to_path(four / "doc.hwpx")
    assert with_cache(0) == 1
    hwpx_tables.split_table_ext("doc.hwpx", 0, 2)
    assert with_cache(0) == 0


def test_split_when_the_paragraph_holds_more_than_the_table(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    host = doc.add_paragraph("표 앞 글")
    host.add_table(3, 2, width=8000, height=3000)
    doc.save_to_path(tmp_path / "doc.hwpx")
    hwpx_tables.split_table_ext("doc.hwpx", 0, 1)
    texts = body_texts(tmp_path)
    assert texts[:2] == ["머리", "표 앞 글"] and len(texts) == 3  # the text stays with the upper table; the lower table has its own paragraph
    assert [f["rows"] for f in table_facts(tmp_path)] == [1, 2]


def test_split_then_merge_gives_the_table_back(four):
    original = table_facts(four)[0]
    hwpx_tables.split_table_ext("doc.hwpx", 0, 1)
    result = hwpx_tables.merge_table_with_next_ext("doc.hwpx", 0)
    (merged,) = table_facts(four)
    assert result["rows"] == 4 and merged["text"] == original["text"] and merged["addrs"] == [0, 1, 2, 3] and merged["height"] == original["height"]
    assert body_texts(four) == ["머리", "", "표 뒤 문단"]


def test_split_refusals(four):
    before = hashlib.sha256((four / "doc.hwpx").read_bytes()).hexdigest()
    for row, message in ((0, "cannot be cut"), (4, "cannot be cut"), (-1, "cannot be cut")):
        with pytest.raises(ToolInputError, match=message):
            hwpx_tables.split_table_ext("doc.hwpx", 0, row)
    with pytest.raises(ToolInputError, match="whole number"):
        hwpx_tables.split_table_ext("doc.hwpx", 0, True)
    with pytest.raises(ToolInputError, match="invalid table_index"):
        hwpx_tables.split_table_ext("doc.hwpx", 3, 1)
    from hwpx_edit import format_table_ext
    format_table_ext("doc.hwpx", 0, merges=[[1, 0, 2, 0]])  # a cell reaching over the cut between rows 1 and 2
    with pytest.raises(ToolInputError, match="merged cell"):
        hwpx_tables.split_table_ext("doc.hwpx", 0, 2)
    format_table_ext("doc.hwpx", 0, treat_as_char=False)
    with pytest.raises(ToolInputError, match="floats"):
        hwpx_tables.split_table_ext("doc.hwpx", 0, 1)
    assert hashlib.sha256((four / "doc.hwpx").read_bytes()).hexdigest() != before  # only format_table_ext changed it


def test_split_refuses_a_table_inside_a_cell(four):
    doc = HwpxDocument.open(four / "doc.hwpx")
    hwpx_locate.table_at(doc, 0).cell(0, 0).paragraphs[0].add_table(2, 1, width=2000, height=800)
    doc.save_to_path(four / "doc.hwpx")
    with pytest.raises(ToolInputError, match="body paragraph"):
        hwpx_tables.split_table_ext("doc.hwpx", 1, 1)


def test_split_dry_run_changes_nothing(four):
    before = hashlib.sha256((four / "doc.hwpx").read_bytes()).hexdigest()
    assert hwpx_tables.split_table_ext("doc.hwpx", 0, 2, dry_run=True)["dryRun"] is True
    assert hashlib.sha256((four / "doc.hwpx").read_bytes()).hexdigest() == before


def two_tables(tmp_path, widths=(9000, 9000, 9000), between=None, rows=(2, 2)):
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    for n, count in enumerate(rows):
        if n == 1 and between:
            doc.add_paragraph(between)
        holder = doc.add_paragraph("")
        table = holder.add_table(count, 3, width=sum(widths if n == 0 else widths), height=2000 * count)
        for r in range(count):
            for c in range(3):
                table.set_cell_text(r, c, f"{n}{r}{c}")
    doc.save_to_path(tmp_path / "doc.hwpx")


def test_merge_two_adjacent_tables(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    two_tables(tmp_path)
    hwpx_tables.merge_table_with_next_ext("doc.hwpx", 0)
    (merged,) = table_facts(tmp_path)
    assert merged["rows"] == 4 and merged["text"][0] == ["000", "001", "002"] and merged["text"][2] == ["100", "101", "102"] and merged["addrs"] == [0, 1, 2, 3]
    assert merged["height"] == 8000


def test_merge_refusals(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    two_tables(tmp_path, between="사이 글")
    with pytest.raises(ToolInputError, match="right after"):
        hwpx_tables.merge_table_with_next_ext("doc.hwpx", 0)
    with pytest.raises(ToolInputError, match="right after"):
        hwpx_tables.merge_table_with_next_ext("doc.hwpx", 1)  # the last table has no table below it
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    doc.add_paragraph("").add_table(1, 3, width=9000, height=1000)
    doc.add_paragraph("").add_table(1, 2, width=9000, height=1000)
    doc.save_to_path(tmp_path / "doc.hwpx")
    with pytest.raises(ToolInputError, match="do not share their columns"):
        hwpx_tables.merge_table_with_next_ext("doc.hwpx", 0)
    doc = HwpxDocument.new()
    doc.paragraphs[0].add_run("머리")
    doc.add_paragraph("").add_table(1, 3, width=9000, height=1000)
    doc.add_paragraph("").add_table(1, 3, width=12000, height=1000)
    doc.save_to_path(tmp_path / "doc.hwpx")
    with pytest.raises(ToolInputError, match="do not share their columns"):
        hwpx_tables.merge_table_with_next_ext("doc.hwpx", 0)
