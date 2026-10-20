"""Claude Desktop 확장 진입점: 업스트림 hwpx-automation MCP 서버에 서식 읽기·확장 도구를 더해 띄운다.

사용자가 설정에서 고른 폴더만 작업 영역이다(그 밖의 경로는 서버가 막는다).
업스트림은 python-hwpx-automation==7.3.4로 고정: 아래 보정은 그 버전의 내부 구조에 기댄다.
"""
import os
import sys
from typing import Any, Literal

from hwpx_automation import fastmcp_adapter as _fa
from hwpx_automation import server as upstream
from hwpx_automation.handlers import quality_render as _qr  # 이 모듈도 snapshot_runtime_tools를 import 시점에 묶어 두므로 함께 보정한다
from hwpx_automation.workspace import WorkspaceResolver  # 업스트림 도구와 같은 경로 검사

import hwpx_layout
import hwpx_lazy
import hwpx_runs
from hwpx_page import add_page_control_ext, set_page_options_ext
from hwpx_styles import apply_style_ext, define_style_ext, set_list_format_ext
from hwpx_docops import copy_paragraphs_ext, delete_backups_ext, insert_document_ext
from hwpx_inline import insert_inline_ext
from hwpx_common import ToolInputError, patch_error_messages
from hwpx_edit import add_endnote_ext, add_paragraphs_ext, format_table_ext, format_text_ext, set_columns_ext, set_paragraph_format_ext, set_tab_attributes

TOOLS: dict[str, Any] = {}


def hwpx_read_layout(filename: str, part: Literal["overview", "body", "tables", "notes", "header", "objects"] = "overview", section: int = 0, offset: int = 0, limit: int = 0,
                     text_chars: int = 0, max_chars: int = 10000,
                     kind: Literal["paraPr", "charPr", "borderFill", "numbering", "tabPr", "style"] | None = None) -> dict[str, Any]:
    """Read the formatting of an HWPX file (read-only): what text tools do not show.
    part="overview": page size/margins, columns, endnote/footnote settings, page number, header/footer, counts.
    part="body": every body paragraph's shape (alignment, line spacing, indent left/right/first-line, space before/after,
    line-break mode KEEP_WORD/BREAK_WORD, condense, paragraph border, list numbering shape), special runs (sup/sub, ratio, offset).
    part="tables": table size/position/margins and every cell (merge, size, borders, margins, vertical align, paragraph shapes).
    part="notes": full text of every endnote/footnote with paragraph shapes.
    part="objects": every inline object (equation, picture, shape, table, hyperlink, bookmark, footnote/endnote, check box, ruby, ...) with its place and attributes; `at` is the character offset in its paragraph.
    part="header": the shapes defined in the file's header, each with its id: paragraph shapes (paraPr), character shapes (charPr), border fills, numberings, tab sets, styles;
    kind=... lists one sort only. These are the ids the *_id arguments of the editing tools take (para_pr_id, char_pr_id, border_fill_id, style_id).
    Paragraph shapes are listed once in `shapes` and items point to them by number (cell borders: `cell_borders`).
    Lists page by offset/limit; use `nextOffset` to continue. Units are in `units` (HWPUNIT: 7200 per inch, 283.465 = 1 mm)."""
    p = WorkspaceResolver.from_environment().resolve(filename, must_exist=True)
    if not p.is_file():
        raise ToolInputError("filename is not a file")
    try:
        return hwpx_layout.read_layout(p, part, section, offset, limit, text_chars, max_chars, kind)
    except ValueError as error:
        raise ToolInputError(str(error)) from error


def install(roots: list[str] | None = None) -> None:
    hwpx_runs.patch_upstream()
    patch_error_messages()
    writes = (set_paragraph_format_ext, format_text_ext, set_tab_attributes, add_endnote_ext, format_table_ext, set_columns_ext, add_paragraphs_ext,
              apply_style_ext, define_style_ext, set_list_format_ext, set_page_options_ext, add_page_control_ext,
              copy_paragraphs_ext, insert_document_ext, insert_inline_ext, delete_backups_ext)
    for fn in (hwpx_read_layout, *writes):
        hwpx_lazy.register(upstream.mcp, TOOLS, fn, fn.__doc__, fn in writes)

    # 업스트림 점검(mcp_server_health·describe_capabilities)은 모르는 도구가 있으면 "skewed"/쓰기 차단으로 보고해 에이전트가 오해한다.
    # 점검용 목록에서만 우리 도구를 뺀다(실제 쓰기 게이트는 영향 없음).
    orig = _fa.snapshot_runtime_tools
    hidden = lambda mcp: {k: v for k, v in orig(mcp).items() if k not in TOOLS}
    _fa.snapshot_runtime_tools = _qr.snapshot_runtime_tools = hidden

    # 코어+메타 도구만 tools/list에 올리고 나머지는 검색해서 쓴다(HWPX_SHOW_ALL_TOOLS=1이면 전부 노출).
    upstream.mcp._mcp_server.instructions = routing_text(roots or [])
    hwpx_lazy.install(upstream.mcp, TOOLS, show_all=os.environ.get("HWPX_SHOW_ALL_TOOLS", "").strip().lower() in ("1", "true", "yes"))

    # 업스트림이 바뀌어 보정이 어긋나면 시작 단계에서 멈춘다.
    if (upstream.mcp_server_health()["toolSurface"]["status"] != "ok"
            or not upstream.describe_capabilities()["coverage"]["ok"]):
        raise SystemExit("hyeyum-hwpx-toolkit: 업스트림 도구 점검이 확장 도구와 맞지 않습니다(업스트림 버전이 달라진 듯합니다).")


ROUTING = ("Use this server for ANY reading, creating or editing of 한글 HWPX (.hwpx) documents - prefer it over any other tool that touches .hwpx files.")


def workspace_roots(argv: list[str], env: dict[str, str]) -> list[str]:
    """허용 폴더: 명령줄 인수(매니페스트가 문서·바탕화면·다운로드와 사용자 추가 폴더를 넘긴다) + 옛 HWPX_WORKSPACE.
    빈 값, 치환 안 된 `${...}`, 없는 폴더는 건너뛰고 같은 폴더는 한 번만 둔다. 첫 폴더가 파일 이름만 쓸 때의 기준이다."""
    roots: list[str] = []
    for raw in [*argv, *env.get("HWPX_WORKSPACE", "").split("|")]:
        value = raw.strip()
        if not value or value.startswith("${"):
            continue
        folder = os.path.realpath(os.path.expanduser(value))
        if os.path.isdir(folder) and folder not in roots:
            roots.append(folder)
    return roots


def default_folders(home: str) -> list[str]:
    """폴더 인수 없이 띄웠을 때(작업 폴더 변수가 없는 표준 플러그인 형식 등) 쓰는 기본 폴더."""
    return [os.path.join(home, name) for name in ("Documents", "Desktop", "Downloads")]


def routing_text(roots: list[str]) -> str:
    where = (" Allowed folders: " + "; ".join(roots) + ". A bare file name means the first folder; give the full path for files in the others.") if roots else ""
    return ROUTING + where


if __name__ == "__main__":
    argv = sys.argv[1:] or ([] if os.environ.get("HWPX_WORKSPACE") else default_folders(os.path.expanduser("~")))
    roots = workspace_roots(argv, dict(os.environ))
    if not roots:
        print("작업할 폴더를 찾지 못했습니다. 다룰 폴더를 서버 인수로 넘기세요(기본: 문서·바탕화면·다운로드).", file=sys.stderr)
        raise SystemExit(2)
    install(roots)
    upstream.main([arg for root in roots for arg in ("--workspace-root", root)])
