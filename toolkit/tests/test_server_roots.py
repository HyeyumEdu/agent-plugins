"""서버 진입점: 허용 폴더를 명령줄 인수에서 고르는 규칙(확장 매니페스트가 문서·바탕화면·다운로드와 선택한 추가 폴더를 넘긴다)과 안내문."""
import json
import os
import sys
from pathlib import Path

import pytest
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))
import server  # noqa: E402


def test_unset_empty_and_missing_folders_are_skipped(tmp_path):
    docs, downloads = tmp_path / "Documents", tmp_path / "Downloads"
    docs.mkdir(), downloads.mkdir()
    argv = [str(docs), str(tmp_path / "Desktop"), str(downloads), "${user_config.extra_folders}", "", "  "]
    assert server.workspace_roots(argv, {}) == [os.path.realpath(docs), os.path.realpath(downloads)]  # order kept; the first is what bare file names mean


def test_same_folder_once_and_extra_folders_after_the_defaults(tmp_path):
    docs, extra = tmp_path / "Documents", tmp_path / "USB 시험지"
    docs.mkdir(), extra.mkdir()
    assert server.workspace_roots([str(docs), str(extra), str(docs) + "/", str(extra)], {}) == [os.path.realpath(docs), os.path.realpath(extra)]


def test_old_environment_setting_still_works_and_nothing_found_is_empty(tmp_path):
    only = tmp_path / "작업"
    only.mkdir()
    assert server.workspace_roots([], {"HWPX_WORKSPACE": f"{only}|{tmp_path / 'nope'}|"}) == [os.path.realpath(only)]
    assert server.workspace_roots(["${DOCUMENTS}", str(tmp_path / "nope")], {}) == []


def test_without_folder_arguments_the_default_folders_are_documents_desktop_downloads(tmp_path):
    (tmp_path / "Documents").mkdir(), (tmp_path / "Downloads").mkdir()
    folders = server.default_folders(str(tmp_path))
    assert [Path(p).name for p in folders] == ["Documents", "Desktop", "Downloads"]
    assert server.workspace_roots(folders, {}) == [os.path.realpath(tmp_path / "Documents"), os.path.realpath(tmp_path / "Downloads")]


def test_routing_text_says_when_to_use_the_server_and_where_it_may_work():
    text = server.routing_text(["/home/a/Documents", "/home/a/Desktop"])
    assert text.startswith("Use this server for ANY reading, creating or editing of")
    assert ".hwpx" in text and "/home/a/Documents; /home/a/Desktop" in text and "bare file name means the first folder" in text
    assert "Allowed folders" not in server.routing_text([])


def test_read_layout_refuses_a_folder_with_a_message_the_caller_sees(tmp_path, monkeypatch):
    """ToolInputError(경로 없는 문구)여야 업스트림이 고정 문장으로 바꾸지 않는다."""
    (tmp_path / "folder").mkdir()
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(tmp_path)]))
    with pytest.raises(server.ToolInputError, match="filename is not a file") as raised:
        server.hwpx_read_layout("folder")
    assert str(tmp_path) not in str(raised.value)
