"""hwpx_runs.split_run: 탭·미주·개체가 든 run의 일부에만 서식을 줘도 그것들이 복제되지 않고 범위가 어긋나지 않는다.
실행: venv/bin/python -m pytest toolkit/tests"""
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
import hwpx_runs  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.add_paragraph("②\t등대의 불빛은 멀리서")
    doc.add_paragraph("발문 문장이 이어진다 끝")
    doc.save_to_path(tmp_path / "doc.hwpx")
    hwpx_edit.add_endnote_ext("doc.hwpx", 2, [{"text": " 정답"}])
    return tmp_path


def section(ws: Path) -> str:
    return zipfile.ZipFile(ws / "doc.hwpx").read("Contents/section0.xml").decode()


def runs_of(ws: Path, index: int) -> list[tuple[str, str]]:
    doc = HwpxDocument.open(ws / "doc.hwpx")
    return [(run.char_pr_id_ref, run.text) for run in doc.paragraphs[index].runs]


@pytest.mark.parametrize("span", [(0, 4), (1, 5), (2, 6), (4, 8), (0, 2), (10, 15)])
def test_tab_stays_single_and_range_counts_the_tab(ws, span):
    before = "".join(text for _, text in runs_of(ws, 1))
    hwpx_edit.format_text_ext("doc.hwpx", 1, *span, bold=True)
    after = runs_of(ws, 1)
    assert "".join(text for _, text in after) == before
    assert section(ws).count("<hp:tab") == 1
    bold = [text for ref, text in after if ref != "0"]
    assert "".join(bold) == before[span[0]:span[1]]


@pytest.mark.parametrize("span", [(0, 3), (3, 6), (5, 12), (8, 12), (0, 12)])
def test_endnote_is_not_duplicated_and_stays_after_its_text(ws, span):
    hwpx_edit.format_text_ext("doc.hwpx", 2, *span, italic=True)
    xml = section(ws)
    assert xml.count("<hp:endNote ") == 1 and xml.count("<hp:autoNum ") == 1
    assert re.search(r"끝</hp:t><hp:ctrl><hp:endNote ", xml)
    assert "".join(text for _, text in runs_of(ws, 2)) == "발문 문장이 이어진다 끝"


def test_upstream_format_text_gets_the_same_repair(ws):
    from hwpx_automation.core.document import open_doc
    from hwpx_automation.core.formatting import format_text_range
    hwpx_runs.patch_upstream()
    doc = open_doc(str(ws / "doc.hwpx"))
    format_text_range(doc, 1, 0, 4, bold=True)
    format_text_range(doc, 2, 3, 6, italic=True)
    doc.save_to_path(ws / "out.hwpx")
    xml = zipfile.ZipFile(ws / "out.hwpx").read("Contents/section0.xml").decode()
    assert xml.count("<hp:tab") == 1 and xml.count("<hp:endNote ") == 1
