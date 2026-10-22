"""여러 쓰기 도구를 무작위로 섞어 써도 문서가 열리고, 서식 도구가 글·탭·미주·수식을 바꾸지 않는지(고정 시드, 작은 반복)."""
import json
import random
import re
import sys
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx.tools.id_integrity import check_id_integrity
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_docops  # noqa: E402
import hwpx_edit  # noqa: E402
import hwpx_layout  # noqa: E402
import hwpx_objects  # noqa: E402
import hwpx_page  # noqa: E402
import hwpx_styles  # noqa: E402
import hwpx_textedit  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    doc = HwpxDocument.new()
    doc.add_paragraph("①\t등대의 불빛은 멀리서 반짝였다")
    doc.add_paragraph("발문 문장이 이어진다 끝")
    doc.add_paragraph("세 번째 문단입니다 가나다라마바사")
    doc.save_to_path(tmp_path / "doc.hwpx")
    hwpx_edit.add_endnote_ext("doc.hwpx", 2, [{"text": " 정답 ③"}])
    hwpx_edit.insert_inline_ext("doc.hwpx", items=[{"equation": "{}_{1}"}], position=3, paragraph_index=3)
    return tmp_path


def counts(ws: Path) -> dict[str, int]:
    xml = zipfile.ZipFile(ws / "doc.hwpx").read("Contents/section0.xml").decode()
    return {tag: len(re.findall(rf"<hp:{tag}[ >/]", xml)) for tag in ("tab", "endNote", "equation", "footNote")}


def body_text(ws: Path) -> list[str]:
    doc = HwpxDocument.open(ws / "doc.hwpx")
    return ["".join(run.text or "" for run in p.runs) for p in doc.paragraphs]


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_random_tool_mix_keeps_the_document_sound(ws, seed):
    rng = random.Random(seed)
    for _ in range(14):
        text = body_text(ws)
        index = rng.randrange(1, len(text))
        length = len(text[index])
        before_counts, before_text = counts(ws), list(text)
        choice = rng.choice(["format_text", "format_para", "style", "insert_eq", "insert_text", "footnote", "add", "copy", "replace", "edit_text", "split_merge", "delete_obj", "update_obj"])
        if choice == "format_text" and length > 1:
            start = rng.randrange(0, length - 1)
            hwpx_edit.format_text_ext("doc.hwpx", index, start, rng.randrange(start + 1, length + 1), **rng.choice([{"bold": True}, {"italic": True}, {"font_size": 12}, {"letter_spacing": -3}]))
            assert counts(ws) == before_counts and body_text(ws) == before_text  # formatting never changes text, tabs, notes, equations
        elif choice == "format_para":
            hwpx_edit.set_paragraph_format_ext("doc.hwpx", paragraph_index=index, **rng.choice([{"alignment": "CENTER"}, {"indent_left_mm": 2.0}, {"condense": 80}, {"keep_with_next": True}]))
            assert counts(ws) == before_counts and body_text(ws) == before_text
        elif choice == "style":
            hwpx_styles.apply_style_ext("doc.hwpx", [index], rng.choice(["본문", "바탕글"]))
            assert counts(ws) == before_counts and body_text(ws) == before_text
        elif choice == "insert_eq":
            hwpx_edit.insert_inline_ext("doc.hwpx", items=[{"equation": "x^{2}"}], position=rng.randrange(0, length + 1), paragraph_index=index)
            assert counts(ws)["equation"] == before_counts["equation"] + 1 and body_text(ws) == before_text
        elif choice == "insert_text":
            position = rng.randrange(0, length + 1)
            hwpx_edit.insert_inline_ext("doc.hwpx", items=[{"text": "[끼움]", "bold": True}], position=position, paragraph_index=index)
            expected = list(before_text)
            expected[index] = before_text[index][:position] + "[끼움]" + before_text[index][position:]
            assert body_text(ws) == expected and counts(ws) == before_counts
        elif choice == "footnote":
            hwpx_edit.insert_inline_ext("doc.hwpx", items=[{"footnote": "각주 글"}], position=rng.randrange(0, length + 1), paragraph_index=index)
            assert counts(ws)["footNote"] == before_counts["footNote"] + 1
        elif choice == "add":
            hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"runs": [{"text": "새 "}, {"equation": "a+b"}, {"text": " 끝"}]}], before_index=rng.randrange(1, len(text) + 1))
            assert counts(ws)["equation"] == before_counts["equation"] + 1
        elif choice == "replace" and length > 1:
            start = rng.randrange(0, length - 1)
            word = before_text[index][start:start + 2]
            result = hwpx_textedit.replace_text_ext("doc.hwpx", word, "ZZ")
            assert counts(ws) == before_counts  # a text replacement never touches tabs, notes, equations
            assert result["replaced"] + len(result.get("skipped", [])) == result["matched"] and (result["replaced"] == 0 or any("ZZ" in line for line in body_text(ws)))
        elif choice == "edit_text":
            position = rng.randrange(0, length + 1)
            hwpx_textedit.edit_paragraph_text_ext("doc.hwpx", start=position, text="[편집]", paragraph_index=index)
            expected = list(before_text)
            expected[index] = before_text[index][:position] + "[편집]" + before_text[index][position:]
            assert body_text(ws) == expected and counts(ws) == before_counts
        elif choice == "split_merge" and length > 1:
            hwpx_textedit.split_paragraph_ext("doc.hwpx", position=rng.randrange(1, length), paragraph_index=index)
            assert len(body_text(ws)) == len(before_text) + 1 and counts(ws) == before_counts
            hwpx_textedit.merge_paragraphs_ext("doc.hwpx", paragraph_index=index)
            assert body_text(ws) == before_text and counts(ws) == before_counts  # split then merge gives the paragraph back
        elif choice in ("delete_obj", "update_obj"):
            here = [item for item in hwpx_layout.read_layout(ws / "doc.hwpx", "objects", max_chars=10**9)["items"]
                    if item.get("paragraph_index") == index and item["kind"] in ("equation", "footnote", "endnote")]
            if here and choice == "delete_obj":
                kind = here[0]["kind"]
                tag = {"endnote": "endNote", "footnote": "footNote", "equation": "equation"}[kind]
                hwpx_objects.delete_inline_object_ext("doc.hwpx", kind=kind, nth=1, paragraph_index=index)
                assert counts(ws)[tag] == before_counts[tag] - 1 and body_text(ws) == before_text  # the object goes, its neighbors' text and tabs stay
            elif here and any(item["kind"] == "equation" for item in here):
                hwpx_objects.update_inline_object_ext("doc.hwpx", kind="equation", properties={"script": "y^{3}"}, paragraph_index=index)
                assert counts(ws) == before_counts and body_text(ws) == before_text
        else:
            hwpx_docops.copy_paragraphs_ext("doc.hwpx", index, index, before_index=index)
            assert len(body_text(ws)) == len(before_text) + 1
        doc = HwpxDocument.open(ws / "doc.hwpx")
        assert check_id_integrity(doc).ok
        nums = [int(n) for n in re.findall(r'<hp:endNote number="(\d+)"', zipfile.ZipFile(ws / "doc.hwpx").read("Contents/section0.xml").decode())]
        assert nums == list(range(1, len(nums) + 1))
    assert hwpx_layout.read_layout(ws / "doc.hwpx", "objects", max_chars=10**9)["total"] >= 1
