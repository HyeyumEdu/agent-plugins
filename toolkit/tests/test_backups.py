"""백업 정책(직전 쓰기 직전 상태 하나만 남김)과 delete_backups_ext. 실행: venv/bin/python -m pytest toolkit/tests/test_backups.py"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx_automation.hwpx_ops import HwpxOps
from hwpx_automation.runtime_services import RUNTIME_SERVICES
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import hwpx_docops  # noqa: E402
import hwpx_edit  # noqa: E402
import hwpx_runs  # noqa: E402
from hwpx_common import ToolInputError  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(root)]))
    hwpx_runs.patch_upstream()
    previous = RUNTIME_SERVICES.ops
    RUNTIME_SERVICES.replace_ops(HwpxOps(auto_backup=False))  # upstream's service graph fixes its workspace roots at import time
    doc = HwpxDocument.new()
    doc.add_paragraph("처음")
    doc.save_to_path(root / "doc.hwpx")
    yield root
    RUNTIME_SERVICES.replace_ops(previous)


def texts(path: Path) -> list[str]:
    return [p.text for p in HwpxDocument.open(path).paragraphs]


def call_upstream(name: str, args: dict) -> None:
    import server
    asyncio.run(server.upstream.mcp.call_tool(name, args))


def baks(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if ".bak" in p.name)


def test_our_tools_keep_one_backup_with_the_state_before_the_latest_write(ws):
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "하나"}])
    after_first = (ws / "doc.hwpx").read_bytes()
    assert baks(ws) == ["doc.hwpx.bak"]
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "둘"}])
    assert baks(ws) == ["doc.hwpx.bak"]  # no .bak.1
    assert (ws / "doc.hwpx.bak").read_bytes() == after_first
    call_upstream("undo_last_edit", {"filename": "doc.hwpx"})
    assert "둘" not in texts(ws / "doc.hwpx") and "하나" in texts(ws / "doc.hwpx")
    assert baks(ws) == ["doc.hwpx.bak"]


@pytest.mark.parametrize("name, args", [
    ("add_paragraph", {"filename": "doc.hwpx", "text": "업스트림"}),
    ("apply_edits", {"filename": "doc.hwpx", "operations": [{"type": "add_paragraph", "text": "업스트림"}]}),  # the transaction path (exact sidecar guards)
])
def test_upstream_edit_tools_keep_one_backup_too(ws, name, args):
    hwpx_edit.add_paragraphs_ext("doc.hwpx", [{"text": "하나"}])
    after_first = (ws / "doc.hwpx").read_bytes()
    call_upstream(name, args)
    assert "업스트림" in texts(ws / "doc.hwpx")
    assert baks(ws) == ["doc.hwpx.bak"]
    assert (ws / "doc.hwpx.bak").read_bytes() == after_first
    call_upstream(name, {**args, **({"text": "또"} if "text" in args else {"operations": [{"type": "add_paragraph", "text": "또"}]})})
    assert baks(ws) == ["doc.hwpx.bak"]


# ---- delete_backups_ext ----
@pytest.fixture()
def folder(ws, tmp_path):
    for name in ("x.hwpx.bak", "x.hwpx.bak.3", "Y.HWPX.BAK", "x.hwpx", "x.bak", "notes.txt.bak", "x.hwpx.bak.old", "x.hwpx.bak.1.txt"):
        (ws / name).write_bytes(b"data")
    (ws / "sub").mkdir()
    (ws / "sub" / "z.hwpx.bak").write_bytes(b"data")
    outside = tmp_path / "outside.hwpx.bak"
    outside.write_bytes(b"keep")
    (ws / "link.hwpx.bak").symlink_to(outside)
    (ws / "dir.hwpx.bak").mkdir()
    return ws


GONE = ["Y.HWPX.BAK", "x.hwpx.bak", "x.hwpx.bak.3"]


def test_dry_run_deletes_nothing(folder):
    before = sorted(p.name for p in folder.iterdir())
    result = hwpx_docops.delete_backups_ext(dry_run=True)
    assert result["deleted"] == GONE and result["count"] == 3 and result["dry_run"] is True and result["folder"] == str(folder.resolve())
    assert sorted(p.name for p in folder.iterdir()) == before


def test_deletes_only_backup_files_of_that_folder(folder, tmp_path):
    result = hwpx_docops.delete_backups_ext()  # empty folder = the first allowed folder
    assert result["deleted"] == GONE and result["count"] == 3 and result["dry_run"] is False
    assert sorted(p.name for p in folder.iterdir()) == sorted(["doc.hwpx", "x.hwpx", "x.bak", "notes.txt.bak", "x.hwpx.bak.old", "x.hwpx.bak.1.txt", "sub", "link.hwpx.bak", "dir.hwpx.bak"])
    assert (folder / "sub" / "z.hwpx.bak").exists()
    assert (folder / "link.hwpx.bak").is_symlink() and (tmp_path / "outside.hwpx.bak").read_bytes() == b"keep"  # links are neither followed nor removed


def test_a_subfolder_can_be_named_and_the_folder_is_checked_like_files(folder, tmp_path):
    assert hwpx_docops.delete_backups_ext("sub")["deleted"] == ["z.hwpx.bak"]
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "o.hwpx.bak").write_bytes(b"keep")
    (folder / "escape").symlink_to(tmp_path / "other")
    for bad in (str(tmp_path / "other"), "../other", "escape", "nope", "x.hwpx"):
        with pytest.raises(ToolInputError) as raised:
            hwpx_docops.delete_backups_ext(bad)
        assert str(tmp_path) not in str(raised.value)
    assert (tmp_path / "other" / "o.hwpx.bak").exists()


def test_empty_folder_means_the_first_root(tmp_path, monkeypatch):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(), second.mkdir()
    (first / "a.hwpx.bak").write_bytes(b"1")
    (second / "b.hwpx.bak").write_bytes(b"2")
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(first), str(second)]))
    assert hwpx_docops.delete_backups_ext()["deleted"] == ["a.hwpx.bak"]
    assert hwpx_docops.delete_backups_ext(str(second))["deleted"] == ["b.hwpx.bak"]
