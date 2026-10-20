"""도구 지연 노출 층: 숨겨진 도구가 하나도 빠지지 않고 찾아지고 실행되는지(완전성), 읽기/수정 구분, 오류 안내."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from hwpx import HwpxDocument
from hwpx_automation.workspace import WORKSPACE_ROOTS_ENV
from mcp import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"))


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    root = tmp_path_factory.mktemp("lazy")
    patch = pytest.MonkeyPatch()
    patch.setenv(WORKSPACE_ROOTS_ENV, json.dumps([str(root)]))
    patch.delenv("HWPX_SHOW_ALL_TOOLS", raising=False)
    doc = HwpxDocument.new()
    doc.add_paragraph("가나다라 마바사")
    doc.save_to_path(root / "doc.hwpx")
    import hwpx_lazy
    import server
    server.install()
    yield server, hwpx_lazy, root
    patch.undo()


def run(coro):
    return asyncio.run(coro)


def all_tools(srv):
    server, lazy, _ = srv
    return {name: tool for name, tool in lazy._tools(server.upstream.mcp).items() if name not in lazy.META}


def test_listing_is_only_core_plus_meta(srv):
    server, lazy, _ = srv
    handler = server.upstream.mcp._mcp_server.request_handlers[types.ListToolsRequest]
    listed = {tool.name for tool in run(handler(types.ListToolsRequest(method="tools/list"))).root.tools}
    assert listed == set(lazy.CORE) | set(lazy.META)
    assert set(lazy.CORE) <= set(all_tools(srv))  # a renamed or removed core tool must not go unnoticed


def test_every_tool_is_in_the_map_exactly_once_and_in_the_finder_description(srv):
    server, lazy, _ = srv
    mapped = [name for names in lazy.capability_map(server.upstream.mcp).values() for name in names]
    assert sorted(mapped) == sorted(all_tools(srv))  # no tool missing, none twice
    assert lazy._OTHER not in lazy.capability_map(server.upstream.mcp)  # every tool has a real group; a new tool must get a rule
    description = lazy._tools(server.upstream.mcp)["hwpx_find_tools"].description
    assert all(name in description for name in all_tools(srv))


def test_empty_query_lists_every_tool(srv):
    server, lazy, _ = srv
    rows = lazy.search(server.upstream.mcp, "", 15)
    assert sorted(row["name"] for row in rows) == sorted(all_tools(srv))
    assert {row["runWith"] for row in rows} == {"hwpx_run_read", "hwpx_run_edit"}  # the finder already says which runner each tool needs


def test_schema_of_every_tool_is_retrievable_and_matches_the_registry(srv):
    server, lazy, _ = srv
    find = lazy._tools(server.upstream.mcp)["hwpx_tool_schema"].fn
    for name, tool in all_tools(srv).items():
        got = run(find(name))
        assert got["arguments"] == tool.parameters and got["name"] == name
        assert got["runWith"] == ("hwpx_run_edit" if lazy._edits(tool) else "hwpx_run_read")


def test_every_tool_can_be_found_by_its_own_name_and_by_its_first_description_line(srv):
    server, lazy, _ = srv
    misses = []
    for name, tool in all_tools(srv).items():
        if lazy.search(server.upstream.mcp, name, 3)[0]["name"] != name:
            misses.append(("name", name))
        summary = lazy._summary(tool)
        if summary and name not in [row["name"] for row in lazy.search(server.upstream.mcp, summary, 12)]:
            misses.append(("summary", name))
    assert not misses, misses


@pytest.mark.parametrize("query, expected", [
    ("각주 달기", "insert_inline_ext"), ("미주 달기", "add_endnote_ext"), ("줄 번호", "set_page_options_ext"), ("표 칸 병합", "merge_table_cells"),
    ("스타일 적용", "apply_style_ext"), ("번호 글자 크기", "set_list_format_ext"), ("문항 복제", "copy_paragraphs_ext"), ("수식 넣기", "add_equation"),
    ("머리말", "set_header_footer"), ("쪽 번호", "set_page_number"), ("그림 넣기", "insert_picture"), ("탭 정지", "set_paragraph_format_ext"),
    ("자간", "format_text_ext"), ("문서 끼워 넣기", "insert_document_ext"), ("되돌리기", "undo_last_edit"), ("표 읽기", "get_table_text"),
    ("서식 읽기", "hwpx_read_layout"), ("찾아 바꾸기", "search_and_replace"), ("시험지 조판", "compose_exam"), ("2단 구분선", "set_columns_ext"),
    ("들여쓰기 내어쓰기", "set_paragraph_format_ext"), ("하이퍼링크", "insert_inline_ext"), ("바탕쪽", "set_page_options_ext"), ("스타일 만들기", "define_style_ext"),
    ("표 테두리", "format_table_ext"), ("문단 삭제", "delete_paragraph"), ("쪽 감추기", "add_page_control_ext"), ("개인정보", "scan_personal_info"),
    ("백업 지우기", "delete_backups_ext"), ("백업 파일 삭제", "delete_backups_ext"), ("백업 정리", "delete_backups_ext"), (".bak 지우기", "delete_backups_ext"),
])
def test_korean_task_words_lead_to_the_right_tool(srv, query, expected):
    server, lazy, _ = srv
    assert expected in [row["name"] for row in lazy.search(server.upstream.mcp, query, 8)]


def test_read_and_edit_gates_cover_every_tool(srv):
    server, lazy, root = srv
    read, edit = lazy._tools(server.upstream.mcp)["hwpx_run_read"].fn, lazy._tools(server.upstream.mcp)["hwpx_run_edit"].fn
    for name, tool in all_tools(srv).items():
        wrong = read if lazy._edits(tool) else edit
        with pytest.raises(Exception, match="run it with"):
            run(wrong(name, {}))
    kinds = [lazy._edits(tool) for tool in all_tools(srv).values()]
    assert any(kinds) and not all(kinds)


def test_dispatch_gives_the_same_result_as_the_direct_call(srv):
    server, lazy, root = srv
    read = lazy._tools(server.upstream.mcp)["hwpx_run_read"].fn
    via = run(read("get_document_info", {"filename": "doc.hwpx"}))
    direct = run(server.upstream.mcp.call_tool("get_document_info", {"filename": "doc.hwpx"}))[1]
    assert via == direct and via["paragraphs"] >= 1
    edit = lazy._tools(server.upstream.mcp)["hwpx_run_edit"].fn
    before = (root / "doc.hwpx").read_bytes()
    out = run(edit("set_paragraph_format_ext", {"filename": "doc.hwpx", "paragraph_index": 1, "alignment": "CENTER", "dry_run": True}))
    assert out["dryRun"] is True and (root / "doc.hwpx").read_bytes() == before
    run(edit("set_paragraph_format_ext", json.dumps({"filename": "doc.hwpx", "paragraph_index": 1, "alignment": "CENTER"})))  # arguments given as JSON text
    assert (root / "doc.hwpx").read_bytes() != before


def test_error_messages_tell_the_agent_what_to_do(srv):
    server, lazy, _ = srv
    read, edit = lazy._tools(server.upstream.mcp)["hwpx_run_read"].fn, lazy._tools(server.upstream.mcp)["hwpx_run_edit"].fn
    with pytest.raises(Exception, match=r"unknown tool 'nope'.*hwpx_find_tools"):
        run(read("nope", {}))
    with pytest.raises(Exception, match=r"hwpx_find_tools"):
        run(read("hwpx_run_read", {}))  # the runners cannot call themselves
    with pytest.raises(Exception, match=r"Required: \['filename'.*hwpx_tool_schema"):
        run(edit("set_paragraph_format_ext", {}))
    with pytest.raises(Exception, match=r"not JSON"):
        run(read("get_document_info", "{not json"))
    with pytest.raises(Exception, match=r"object of argument names"):
        run(read("get_document_info", ["doc.hwpx"]))


def test_show_all_leaves_everything_visible():
    from mcp.server.fastmcp import FastMCP
    import hwpx_lazy
    mcp = FastMCP("probe")
    mcp.tool(name="solo")(lambda: "x")
    handler = mcp._mcp_server.request_handlers[types.ListToolsRequest]
    registered = {}
    hwpx_lazy.install(mcp, registered, show_all=True)
    assert registered == {} and mcp._mcp_server.request_handlers[types.ListToolsRequest] is handler


def test_every_tool_has_a_hint_and_the_hints_name_no_other_tools(srv):
    server, lazy, _ = srv
    assert set(lazy._HINTS) == set(all_tools(srv))  # a new tool must get a one-line hint
    assert all(0 < len(hint) <= 60 for hint in lazy._HINTS.values())
    description = lazy._tools(server.upstream.mcp)["hwpx_find_tools"].description
    assert all(f"{name} ({hint})" in description for name, hint in lazy._HINTS.items())


@pytest.mark.parametrize("name, group_start", [
    ("format_text", "서식"), ("format_text_ext", "서식"), ("set_paragraph_format", "서식"), ("set_paragraph_format_ext", "서식"), ("set_list_format_ext", "서식"),
    ("apply_style_ext", "서식"), ("define_style_ext", "서식"), ("format_table", "표"), ("format_table_ext", "표"), ("merge_table_cells", "표"),
    ("insert_inline_ext", "글 중간"), ("add_endnote_ext", "글 중간"), ("add_paragraphs_ext", "문단·문서"), ("copy_paragraphs_ext", "문단·문서"),
    ("set_page_options_ext", "쪽·구역"), ("set_columns_ext", "쪽·구역"), ("search_and_replace", "글 바꾸기"), ("hwpx_read_layout", "읽기"),
    ("get_document_info", "읽기"), ("undo_last_edit", "문서 열기"), ("delete_backups_ext", "문서 열기"), ("fill_form_field", "양식"), ("scan_personal_info", "양식"), ("compose_exam", "시험지"),
    ("render_preview", "한컴 렌더"), ("start_workflow", "작업 흐름"),
])
def test_tools_are_in_the_group_a_person_would_look_in(srv, name, group_start):
    _, lazy, _ = srv
    assert lazy._group_of(name).startswith(group_start)  # "format" must not be mistaken for "form fill"


def test_group_map_is_ordered_most_used_first(srv):
    server, lazy, _ = srv
    titles = list(lazy.capability_map(server.upstream.mcp))
    assert titles[0].startswith("읽기") and titles[-1].startswith(("작업 흐름", "한컴"))


def test_edit_replies_are_compact_but_keep_what_matters(srv):
    server, lazy, root = srv
    edit = lazy._tools(server.upstream.mcp)["hwpx_run_edit"].fn
    compact = run(edit("add_endnote_ext", {"filename": "doc.hwpx", "paragraph_index": 1, "paragraphs": [{"text": " 정답 ③ [3.6점]"}]}))
    assert "verificationReport" not in compact and "semanticDiff" not in compact
    check = compact["check"]
    assert check["opensSafely"] is True and check["backupCreated"] is True and check["errors"] == []
    assert check["changes"] and any("placeholder" in w for w in check["warnings"])  # the [3.6점] heuristic is still shown, as a warning
    assert len(json.dumps(compact, ensure_ascii=False)) < 1500
    full = run(edit("add_endnote_ext", {"filename": "doc.hwpx", "paragraph_index": 1, "paragraphs": [{"text": " 해설"}]}, verbose=True))
    assert "verificationReport" in full and "check" not in full


def test_compact_reports_real_problems():
    import hwpx_lazy
    bad = {"x": 1, "verificationReport": {"ok": False, "warnings": ["w"]}, "openSafety": {"ok": False, "validateDocument": {"errors": ["broken ref"]}, "reopen": {"ok": False, "error": "cannot reopen"}}}
    out = hwpx_lazy.compact(bad)
    assert out["x"] == 1 and out["check"]["opensSafely"] is False and out["check"]["errors"] == ["broken ref", "cannot reopen"] and out["check"]["warnings"] == ["w"]
    assert hwpx_lazy.compact({"plain": 1}) == {"plain": 1}


def test_real_failure_reasons_reach_the_agent(srv):
    server, lazy, root = srv
    edit = lazy._tools(server.upstream.mcp)["hwpx_run_edit"].fn
    with pytest.raises(Exception, match=r"add_toc did not succeed.*(add_heading|개요)"):
        run(edit("add_toc", {"filename": "doc.hwpx"}))  # no heading yet: upstream's own hint is passed on
    with pytest.raises(Exception, match=r"add_tracked_edit did not succeed.*must differ"):
        run(edit("add_tracked_edit", {"source_filename": "doc.hwpx", "destination_filename": "doc.hwpx", "edits": []}))
    try:
        run(edit("add_tracked_edit", {"source_filename": "doc.hwpx", "destination_filename": "redline.hwpx", "edits": [{"foo": "bar"}]}))
    except Exception as error:
        assert "errors" in str(error).lower() or "edit" in str(error).lower()
        assert str(root) not in str(error)  # file paths never appear in the message
    else:
        raise AssertionError("an edit item without a type must be refused")


def test_failure_text_and_path_scrubbing():
    import hwpx_lazy
    reply = {"ok": False, "error": "no headings", "hint": "use add_heading", "errors": [{"code": "x", "message": "boom"}], "source": {"path": "/home/user/secret/doc.hwpx", "c": "C:\\Users\\a\\b.hwpx"}}
    assert hwpx_lazy.failed(reply) and not hwpx_lazy.failed({"ok": True}) and not hwpx_lazy.failed({"x": 1})
    text = hwpx_lazy.failure_text("tool_x", reply)
    assert "no headings" in text and "use add_heading" in text and "boom" in text
    assert "/home/user/secret" not in text and "C:\\Users" not in text and "<path>" in text


def test_notes_explain_the_tricky_tools_and_health_has_a_verdict(srv):
    server, lazy, _ = srv
    schema = lazy._tools(server.upstream.mcp)["hwpx_tool_schema"].fn
    assert any("add_heading" in note for note in run(schema("add_toc"))["notes"])
    assert any("destination_filename" in note for note in run(schema("add_tracked_edit"))["notes"])
    assert "notes" not in run(schema("get_document_info"))
    assert set(lazy._NOTES) <= set(all_tools(srv))  # a note for a renamed or removed tool must not linger
    read = lazy._tools(server.upstream.mcp)["hwpx_run_read"].fn
    health = run(read("mcp_server_health", {}))
    assert list(health)[0] == "verdict" and health["verdict"] == "ok"


# ---- 호출 예시 (Anthropic의 tool use examples): 낡은 예시는 여기서 걸린다 ----
@pytest.fixture(scope="module")
def exam_root(srv):
    import struct
    import zlib
    _, _, root = srv
    doc = HwpxDocument.new()
    doc.add_paragraph("")                                             # 1 빈 줄
    doc.add_paragraph("2026학년도 1학기 국어 중간고사")                   # 2 제목
    doc.add_paragraph("1. 다음 글을 읽고 물음에 답하시오. 등대의 불빛은 멀리서 반짝였다.")  # 3 문제
    doc.add_paragraph("①\t첫째 선택지입니다 ②\t둘째 선택지입니다")            # 4 선택지(탭)
    doc.add_paragraph("세포 주기는 G기 → S기 → M기 이다.")                 # 5
    doc.add_paragraph("마지막 문단입니다.")                               # 6
    doc.add_paragraph("").add_table(3, 3, width=30000, height=3000)     # 7 표 0번
    doc.save_to_path(root / "exam.hwpx")
    other = HwpxDocument.new()
    other.add_paragraph("끼울 문서의 글")
    other.save_to_path(root / "other.hwpx")
    raw = b"".join(b"\x00" + bytes([200, 60, 60]) * 8 for _ in range(8))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return root


def test_every_example_fits_its_tools_argument_model(srv):
    from hwpx_examples import EXAMPLES
    tools = all_tools(srv)
    assert set(EXAMPLES) <= set(tools)  # an example for a renamed or removed tool must not linger
    for name, examples in EXAMPLES.items():
        assert 1 <= len(examples) <= 5
        for example in examples:
            assert example["does"] and isinstance(example["arguments"], dict)
            tools[name].fn_metadata.arg_model.model_validate(example["arguments"])


def test_every_example_really_runs_on_the_sample_exam(srv, exam_root):
    from hwpx_examples import EXAMPLES
    server, lazy, _ = srv
    ran = 0
    for name, examples in EXAMPLES.items():
        tool = all_tools(srv)[name]
        for example in examples:
            args = dict(example["arguments"])
            if "dry_run" in tool.parameters["properties"]:
                args["dry_run"] = True
            elif lazy._edits(tool):
                continue  # edits without a dry run (copy_document, undo_last_edit) are only checked against the argument model
            run(server.upstream.mcp.call_tool(name, args))
            ran += 1
    assert ran >= 25


def test_every_tool_of_ours_that_is_not_always_listed_has_example_calls(srv):
    from hwpx_examples import EXAMPLES
    _, lazy, _ = srv
    ours = {name for name in all_tools(srv) if name.endswith("_ext") or name == "set_tab_attributes"}
    assert not [name for name in ours - set(lazy.CORE) if name not in EXAMPLES]


def test_schema_reply_carries_examples_and_the_core_stays_small(srv):
    server, lazy, _ = srv
    schema = lazy._tools(server.upstream.mcp)["hwpx_tool_schema"].fn
    reply = run(schema("insert_inline_ext"))
    assert len(reply["examples"]) >= 3 and all({"does", "arguments"} <= set(item) for item in reply["examples"])
    assert "examples" not in run(schema("mcp_server_health"))
    assert 3 <= len(lazy.CORE) <= 5  # Anthropic: keep the three to five most used tools loaded, defer the rest
    handler = server.upstream.mcp._mcp_server.request_handlers[types.ListToolsRequest]
    tools = run(handler(types.ListToolsRequest(method="tools/list"))).root.tools
    assert sum(len(json.dumps({"n": t.name, "d": t.description, "s": t.inputSchema}, ensure_ascii=False)) for t in tools) < 20000
    instructions = server.upstream.mcp._mcp_server.instructions
    assert "Capability areas" in instructions and "서식" in instructions and "표" in instructions
    assert instructions.startswith("Use this server for ANY reading, creating or editing of")  # routing comes first, then the lazy-loading guidance
