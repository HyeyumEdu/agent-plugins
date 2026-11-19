"""손상된 파일의 오류 문구: "찾을 수 없음"이나 이유 없는 실패가 아니라 손상이라고 알린다(업스트림 사본 수정, hyeyum(수정)).

예전에는 손상 파일을 열면 TOOL_EXECUTION_FAILED(이유 없음), 복구하면 파일이 있는데도 DOCUMENT_NOT_FOUND가 나와
에이전트가 파일 이름 정규화까지 의심하며 헤맸다.
"""
import asyncio
import json

import pytest
from hwpx import HwpxDocument
from hwpx_automation import runtime
from hwpx_automation.hwpx_ops import HwpxOps
from hwpx_automation.runtime_services import RUNTIME_SERVICES
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(root)]))
    previous = RUNTIME_SERVICES.ops
    RUNTIME_SERVICES.replace_ops(HwpxOps(auto_backup=False))
    (root / "bad.hwpx").write_bytes(b"PK\x03\x04broken")
    doc = HwpxDocument.new()
    doc.add_paragraph("정상")
    doc.save_to_path(root / "good.hwpx")
    yield root
    RUNTIME_SERVICES.replace_ops(previous)


def error_code(name: str, args: dict) -> str | None:
    import server
    try:
        asyncio.run(server.upstream.mcp.call_tool(name, args))
    except Exception as exc:  # FastMCP가 ToolError로 감싼 것을 업스트림 분류기에 그대로 넘긴다
        return runtime._classified_error_payload(exc)["code"]
    return None


def test_damaged_file_reports_damage_not_missing(ws):
    assert error_code("get_document_info", {"filename": "bad.hwpx"}) == "DOCUMENT_DAMAGED"
    assert error_code("repair_hwpx", {"source_filename": "bad.hwpx", "output_filename": "out.hwpx", "recover": True}) == "DOCUMENT_DAMAGED"
    # 다른 경로는 업스트림이 원래 ZIP 아님(HWPX_PACKAGE_REQUIRED)으로 먼저 거를 수 있다. 둘 다 원인을 알린다(찾을 수 없음·이유 없는 실패가 아님)
    clear = ("DOCUMENT_DAMAGED", "HWPX_PACKAGE_REQUIRED")
    assert error_code("get_document_text", {"filename": "bad.hwpx"}) in clear
    assert error_code("repair_hwpx", {"source_filename": "bad.hwpx", "output_filename": "out.hwpx", "recover": False}) in clear
    assert not (ws / "out.hwpx").exists()


def test_missing_and_valid_files_unchanged(ws):
    assert error_code("get_document_info", {"filename": "nothing.hwpx"}) == "DOCUMENT_NOT_FOUND"
    assert error_code("repair_hwpx", {"source_filename": "nothing.hwpx", "output_filename": "out.hwpx"}) == "DOCUMENT_NOT_FOUND"
    assert error_code("get_document_info", {"filename": "good.hwpx"}) is None
    assert error_code("repair_hwpx", {"source_filename": "good.hwpx", "output_filename": "fixed.hwpx"}) is None


def test_damage_message_tells_the_teacher_what_to_do():
    from hwpx_automation.errors import DocumentDamagedError
    payload = runtime._classified_error_payload(DocumentDamagedError("local HWPX open failed open-safety verification"))
    assert payload["code"] == "DOCUMENT_DAMAGED" and "손상" in payload["message"] and "다시 저장" in payload["message"]
    assert "open-safety" not in payload["message"]  # 내부 문구는 내보내지 않는다
