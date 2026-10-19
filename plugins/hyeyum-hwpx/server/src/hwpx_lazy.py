"""도구 지연 노출 층: 도구 설명이 모델 입력을 과하게 차지하지 않게 하되 기능은 하나도 빠뜨리지 않는다.

tools/list에는 코어 도구와 메타 도구 네 개만 싣는다.
  hwpx_find_tools(query)         이름·한 줄 설명 검색(빈 검색어 = 전체 목록). 설명에 모든 도구 이름이 분류별로 들어 있고,
                                 서버 시작 때 등록된 도구에서 만들므로 낡거나 빠질 수 없다.
  hwpx_tool_schema(name)         한 도구의 전체 설명과 인수 스키마.
  hwpx_run_read / hwpx_run_edit  이름과 인수로 실행. Claude Desktop이 도구마다 허용 여부를 물으므로 읽기와 수정을 나눈다.
HWPX_SHOW_ALL_TOOLS=1이면 이 층 없이 모든 도구를 그대로 보인다.
"""
import json
import math
import re
from typing import Any

from mcp import types
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from hwpx_common import ToolInputError
from hwpx_examples import EXAMPLES

#: 항상 tools/list에 있는 코어 도구(가장 자주 쓰는 3~5개). 나머지는 찾기→스키마→실행.
CORE = frozenset({"list_available_documents", "get_document_info", "get_document_text", "hwpx_read_layout", "add_paragraphs_ext"})
META = frozenset({"hwpx_find_tools", "hwpx_tool_schema", "hwpx_run_read", "hwpx_run_edit"})


#: 모든 도구의 한 줄 설명(교사가 쓰는 말 포함). 지도와 검색에 쓰이고, 새 도구는 여기에도 적어야 시험이 통과한다.
_HINTS = {
    "add_boxed_org_chart": "상자형 조직도 추가", "add_chart": "차트 삽입", "add_cross_reference": "제목 쪽번호 상호참조", "add_endnote_ext": "미주 달기(여러 문단·서식)",
    "add_equation": "수식을 문단 맨 끝에 추가", "add_form_field": "입력 양식 칸 추가", "add_heading": "제목(개요) 문단 추가", "add_memo": "메모 달기",
    "add_memo_by_anchor": "글 앵커에 메모 달기", "add_page_break": "쪽 나누기 삽입", "add_page_control_ext": "특정 문단이 있는 쪽만 감추기·거기서 쪽번호 다시 시작", "add_paragraph": "문서 끝에 문단 추가",
    "add_paragraphs_ext": "모양 지정해 문단 추가·삽입(수식·그림 포함)", "add_table": "표 추가", "add_toc": "차례(목차) 삽입", "add_tracked_edit": "변경 추적 편집",
    "analyze_document_plan": "문서 계획 분석", "analyze_form_fill": "양식 채우기 분석", "analyze_template_formfit": "양식 맞춤 분석", "apply_body_ops": "본문 바이트보존 편집",
    "apply_document_commands": "명령 묶음 원자 적용", "apply_edits": "여러 편집 원자 적용", "apply_evalplan_fill": "평가계획 양식 채우기", "apply_form_fill": "양식 채우기 적용",
    "apply_style_ext": "문단에 스타일 적용(문단 모양을 스타일 것으로 바꿈)", "apply_style_profile_to_plan": "스타일 프로필 적용", "apply_table_ops": "표 구조 연산(행·열·폭)",
    "apply_template_formfit": "양식 맞춤 적용", "approve_workflow_decision": "작업 흐름 결정 승인", "batch_replace": "여러 글 한꺼번에 바꾸기", "build_image_grid": "그림 격자 문서",
    "build_meeting_nameplates": "회의 명패", "build_organization_chart": "조직도 문서", "byte_preserving_patch": "문단 글 바이트보존 패치", "cancel_workflow": "작업 흐름 취소",
    "check_seal_compliance": "직인 규칙 검사", "compare_style_profiles": "스타일 프로필 비교", "compose_exam": "출제 글을 학교 양식 시험지로 조판", "compose_official_draft": "공문 초안 조판",
    "compose_section_chip": "섹션 구분 칩", "compose_simple_draft": "간단 초안 조판", "compute_report_value": "보고서 값 계산", "continue_workflow": "작업 흐름 계속",
    "copy_document": "문서 파일 복사", "copy_paragraphs_ext": "문단 범위 복제(문항 틀 복제)", "create_comparison_table_document": "비교표 문서", "create_custom_style": "간단 스타일 만들기",
    "create_document": "새 문서", "create_document_from_plan": "계획으로 문서 생성", "create_government_report_document": "정부 보고서 문서", "create_proposal_document": "제안서 문서",
    "define_style_ext": "스타일 만들기·수정(문단·글자 모양 id)", "delete_paragraph": "문단 삭제", "describe_capabilities": "서버 기능 목록", "describe_template": "템플릿 설명",
    "doc_diff": "두 문서 차이 비교", "document_extract_json": "문서를 JSON으로", "document_to_markdown": "문서를 마크다운으로", "dump_document_blueprint": "문서 설계도 추출",
    "extract_style_profile": "스타일 프로필 추출", "fill_by_path": "경로로 값 채우기", "fill_form_field": "양식 칸 채우기", "find_cell_by_label": "라벨로 표 칸 찾기", "find_text": "글 찾기",
    "format_table": "표 테두리·음영(간단)", "format_table_ext": "표 폭·높이·여백·테두리·병합·칸 내용", "format_text": "글자 범위 굵게·크기·색(간단)", "format_text_ext": "글자 범위 장평·자간·밑줄·첨자·강조점",
    "get_document_info": "문서 정보·문단 수·revision", "get_document_map": "문서 지도", "get_document_node": "노드 상세", "get_document_outline": "개요(제목 구조)",
    "get_document_plan_schema": "문서 계획 스키마", "get_document_text": "문서 전체 글", "get_genre_grammar": "장르 문법", "get_location_text": "위치의 글", "get_paragraph_text": "문단 글",
    "get_paragraphs_text": "여러 문단 글(문단 번호 확인)", "get_table_map": "표 지도", "get_table_text": "표 글", "get_workflow": "작업 흐름 상태", "get_workflow_result": "작업 흐름 결과",
    "hwpx_extract_json": "HWPX를 JSON으로", "hwpx_read_layout": "서식 읽기(문단·표·미주·개체·헤더 id)", "hwpx_to_html": "HTML 변환", "hwpx_to_markdown": "마크다운 변환",
    "insert_document_ext": "다른 문서 끼워 넣기", "insert_inline_ext": "글 중간에 수식·그림·각주·링크 끼우기(글 바꿔치기도)", "insert_paragraph": "위치에 문단 삽입", "insert_picture": "그림 삽입(문서 끝)",
    "inspect_document_authoring_quality": "작성 품질 검사", "inspect_document_quality": "문서 품질 검사", "inspect_fill_residue": "채우기 잔여 검사",
    "inspect_mail_merge_placeholders": "편지병합 자리표시 검사", "inspect_official_document_style": "공문서 서식 검사", "inspect_operating_plan_quality": "운영계획 품질 검사",
    "inspect_reference_consistency": "참조 일관성 검사", "list_available_documents": "문서 목록", "list_form_fields": "양식 칸 목록", "list_styles": "스타일 목록", "list_templates": "템플릿 목록",
    "mail_merge": "명부로 문서 대량 생성", "markdown_to_document_plan": "마크다운을 문서 계획으로", "mcp_server_health": "서버 점검", "merge_table_cells": "표 칸 병합",
    "parse_government_report_text": "보고서 글 파싱", "place_seal": "직인 찍기", "query_document_nodes": "노드 조회(미주 등)", "register_template": "템플릿 등록", "remove_memo": "메모 삭제",
    "render_cancel": "렌더 취소", "render_health": "렌더 점검", "render_preview": "미리보기 그림", "render_status": "렌더 상태", "render_submit": "한컴 렌더 제출", "repair_hwpx": "깨진 파일 복구",
    "replace_by_anchor": "앵커로 바꾸기", "replace_in_paragraph": "문단 글 바꾸기", "replace_picture": "그림 교체", "replay_document_blueprint": "설계도로 재생성", "resume_workflow": "작업 흐름 재개",
    "run_edit_plan": "편집 계획 실행", "scan_form_guidance": "양식 안내문 찾기", "scan_personal_info": "개인정보 검사", "search_and_replace": "문서 전체 찾아 바꾸기", "set_columns_ext": "단 나누기·단 구분선",
    "set_header_footer": "머리말·꼬리말", "set_list_format": "번호·글머리표(간단)", "set_list_format_ext": "번호·글머리표(번호 글자 크기·이어 번호)", "set_page_number": "쪽번호를 머리말·꼬리말에 넣기(위치·모양)",
    "set_page_options_ext": "줄 번호·격자·글자방향·구역의 첫 쪽 감추기·시작 번호", "set_page_setup": "용지·여백·방향", "set_paragraph_format": "문단 정렬·들여쓰기·줄간격(간단)",
    "set_paragraph_format_ext": "문단 줄나눔·공백최소·테두리·탭 정지·내어쓰기·쪽 나눔", "set_tab_attributes": "탭 글자 속성", "set_table_cell_text": "표 칸 글 바꾸기", "split_table_cell": "표 칸 나누기",
    "start_workflow": "작업 흐름 시작", "table_compute": "표 계산", "undo_last_edit": "직전 편집 되돌리기(한 단계)", "validate_document_plan": "문서 계획 검증", "verify_form_fill": "양식 채우기 검증",
    "verify_question_splits": "문항이 쪽·단에서 잘리는지 검사", "verify_toc": "차례 검증",
}

#: 교사 요청 -> 쓰는 법(hwpx_find_tools 설명에 실린다).
_RECIPES = """HOW TO (teacher request -> tools):
- Paragraph numbers count from 0 (0 is often an empty paragraph holding the page setup). See numbers and texts with hwpx_read_layout(part="body") or get_paragraphs_text.
- Read formatting first: hwpx_read_layout (part overview/body/tables/notes/objects/header); header ids are what para_pr_id / char_pr_id / style_id arguments take.
- Equation, picture, footnote, link, ruby in the MIDDLE of text: insert_inline_ext (position or anchor_text; replace_anchor=true swaps the matched words for the object, e.g. to link existing words). New paragraphs with such items: add_paragraphs_ext.
- 내어쓰기(hanging indent) = set_paragraph_format_ext first_line_indent_mm NEGATIVE; 탭 정지 = tab_stops [{pos_mm | pos(HWPUNIT), type}]; units: 1 mm = 283.465 HWPUNIT.
- Order: apply a style (apply_style_ext) BEFORE local formatting - it replaces the paragraph's own shape with the style's.
- Make an EXISTING paragraph a heading (e.g. before add_toc): apply_style_ext with style "개요 1".
- Table: add_table, then merge_table_cells / format_table_ext (border + cells_border for every cell's lines).
- Edit replies are compact; edits keep a backup (undo_last_edit undoes one step). Pass verbose=true to see the full verification report. A warning "placeholder-like tokens remain" only means bracketed text such as [3.6점] exists - normal in exams.
"""


#: 스키마만으로 알기 어려운 업스트림 도구의 사용 메모(hwpx_tool_schema 응답의 notes).
_NOTES = {
    "add_toc": ["Needs heading paragraphs in an outline style (개요 1~10): add them with add_heading, or turn existing paragraphs into headings with apply_style_ext (style \"개요 1\"); otherwise it fails.",
                "at_index = body paragraph position where the table of contents goes (0 = top; pass the paragraph count from get_document_info to append)."],
    "add_tracked_edit": ["Writes a NEW file: source_filename is left untouched and destination_filename must be a different name.",
                         'edits = [{"type": "replace", "paragraph_index": 0, "old": "...", "new": "..."}, {"type": "insert", "paragraph_index": 0, "text": "..."}, '
                         '{"type": "delete", "paragraph_index": 0, "match": "..."}]; author is optional.'],
    "add_memo_by_anchor": ["Needs an anchor object returned by find_text. For a plain note on a paragraph use add_memo(paragraph_index, text)."],
    "add_equation": ["Appends the equation at the END of the paragraph. For an equation inside the text use insert_inline_ext (or an equation item in add_paragraphs_ext)."],
    "insert_picture": ["Appends the picture at the end of the document and needs image_base64. For a picture file in the workspace, or a picture inside a paragraph, use insert_inline_ext with a picture item {\"path\": \"logo.png\", \"width_mm\": 20}."],
    "set_page_setup": ['Portrait is stored as orientation "WIDELY" (landscape as "NARROWLY"). Margins are in mm.'],
    "mcp_server_health": ["The reply is long; the verdict is the first key and toolSurface.status (\"ok\")."],
    "get_document_text": ["Phone numbers and similar personal data are masked by default; pass mask=false for the original text."],
}

#: 분류 규칙: 위에서부터 처음 맞는 것. 안 맞으면 "기타"로 지도에 남는다.
_GROUPS: list[tuple[str, re.Pattern[str]]] = [
    ("시험지 전용 (exam)", re.compile(r"^(compose_exam|verify_question_splits)$")),
    ("작업 흐름 (workflow)", re.compile(r"_workflow($|_)|^approve_workflow_decision$")),
    ("한컴 렌더·미리보기 (render; needs Hancom)", re.compile(r"^render_")),
    ("양식 채우기·명부·개인정보 (form fill, mail merge, templates)",
     re.compile(r"(?:^|_)(?:form|fill|mail|template|templates|formfit|evalplan|personal)(?:_|$)|^scan_form|^scan_personal")),
    ("공문서·보고서·조직도·직인 (official/government documents, seal, org chart)",
     re.compile(r"government|proposal|official|operating_plan|seal|org_chart|organization|nameplate|image_grid|section_chip|simple_draft|genre|"
                r"document_plan|compute_report|comparison_table|create_document_from_plan|authoring_quality")),
    ("품질 검사 (inspect)", re.compile(r"^inspect_")),
    ("쪽·구역·단·머리말 (page, section, columns, header/footer)",
     re.compile(r"^(set_page_setup|set_page_number|set_header_footer|set_columns_ext|set_page_options_ext|add_page_control_ext|add_page_break)$")),
    ("표 (tables)", re.compile(r"(?:^|_)table(?:_|$)|find_cell_by_label")),
    ("서식·스타일·번호 (paragraph/character format, styles, lists)",
     re.compile(r"^(format_text|set_paragraph_format|set_tab_attributes|set_list_format)|style|_profile")),
    ("글 중간 개체·주석 (inline objects, notes, memo, toc, tracked edit)",
     re.compile(r"^(insert_inline_ext|add_equation|insert_picture|replace_picture|add_endnote_ext|add_chart|add_memo|add_memo_by_anchor|remove_memo|"
                r"add_cross_reference|add_toc|verify_toc|add_tracked_edit)$")),
    ("문단·문서 만들기·복제 (create, add/insert/delete/copy paragraphs)",
     re.compile(r"^(create_document|add_paragraph|add_paragraphs_ext|add_heading|insert_paragraph|delete_paragraph|copy_paragraphs_ext|insert_document_ext)$")),
    ("글 바꾸기·편집 묶음 (replace, batch edits)",
     re.compile(r"^(replace_|search_and_replace|batch_replace|apply_edits|apply_body_ops|apply_document_commands|run_edit_plan|byte_preserving_patch|replay_document_blueprint)")),
    ("읽기 (read)", re.compile(r"^(get_|find_text|query_|document_to_markdown|document_extract_json|hwpx_to_|hwpx_extract_json|hwpx_read_layout|dump_document_blueprint)")),
    ("문서 열기·복사·되돌리기·비교·점검 (documents, undo, repair, diff, health)",
     re.compile(r"^(list_available_documents|get_document_info|mcp_server_health|describe_capabilities|copy_document|undo_last_edit|repair_hwpx|doc_diff)$")),
]
_OTHER = "기타 (other)"
#: 지도 순서(자주 쓰는 것부터).
_ORDER = ["읽기", "문서 열기", "서식·스타일", "표", "글 중간", "문단·문서", "글 바꾸기", "쪽·구역", "시험지", "품질", "양식", "공문서", "렌더", "작업 흐름", "기타"]

#: 한국어 검색어 -> 영어 도구 설명에 나오는 말(한국어 검색어로도 찾게).
_SYNONYMS = {
    "각주": "footnote", "미주": "endnote", "표": "table", "수식": "equation", "그림": "picture image", "줄 번호": "line numbers", "줄번호": "line numbers",
    "쪽": "page", "단": "column columns", "스타일": "style", "번호": "list numbering number", "탭": "tab", "장평": "ratio width", "자간": "letter spacing",
    "테두리": "border", "병합": "merge", "복제": "copy duplicate", "머리말": "header", "꼬리말": "footer", "글자": "character text", "문단": "paragraph",
    "하이퍼링크": "hyperlink", "책갈피": "bookmark", "덧말": "ruby", "한자": "ruby", "글자 겹침": "composed", "원문자": "composed", "들여쓰기": "indent",
    "내어쓰기": "indent hanging", "줄간격": "line spacing", "정렬": "alignment", "여백": "margin", "격자": "grid", "바탕쪽": "master page",
    "끼워": "insert", "삽입": "insert", "삭제": "delete remove", "바꾸기": "replace", "치환": "replace", "찾기": "find search", "읽기": "read get",
    "서식": "format layout", "목차": "toc table of contents", "메모": "memo", "차트": "chart", "렌더": "render", "백업": "undo backup", "되돌리기": "undo",
    "문서 끼워": "insert document", "시험지": "exam", "문항": "question exam", "양식": "form template", "명부": "mail merge", "개인정보": "personal info",
    "탭 정지": "tab stops", "정지": "stop stops", "어절": "word", "글꼴": "font", "크기": "size", "굵게": "bold", "밑줄": "underline", "색": "color",
    "구분선": "separator line", "머리글": "header", "바닥글": "footer", "행": "row", "열": "column col", "칸": "cell", "넣기": "insert add", "달기": "add insert",
    "만들기": "create define add", "지우기": "delete remove", "복사": "copy", "붙여": "insert paste", "이어": "append continue", "점검": "health inspect check",
    "직인": "seal", "조직도": "organization chart", "보고서": "report government", "비교": "diff compare", "복구": "repair",
}


def _group_of(name: str) -> str:
    return next((title for title, pattern in _GROUPS if pattern.search(name)), _OTHER)


def _tools(mcp: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def _edits(tool: Any) -> bool:
    """수정 도구인가. 표시가 없으면 수정으로 본다(안전한 쪽)."""
    flag = (tool.meta or {}).get("hwpxMutates")
    if flag is not None:
        return bool(flag)
    annotations = tool.annotations
    return not (annotations is not None and annotations.readOnlyHint)


def register(mcp: Any, registry: dict[str, Any], fn: Any, description: str, mutates: bool) -> None:
    """도구 하나를 등록한다(server.py의 확장 도구와 메타 도구가 같은 표시를 쓰게). hwpxMutates로 _edits가 실행기를 고른다."""
    mcp.tool(name=fn.__name__, description=description, meta={"hwpxMutates": mutates, "hwpxExtension": "hyeyum-hwpx-toolkit"},
             annotations={"readOnlyHint": not mutates, "destructiveHint": False, "idempotentHint": not mutates, "openWorldHint": False})(fn)
    registry[fn.__name__] = fn


def _runner(tool: Any) -> str:
    return "hwpx_run_edit" if _edits(tool) else "hwpx_run_read"


def _summary(tool: Any) -> str:
    hint = _HINTS.get(tool.name)
    if hint:
        return hint
    lines = [line.strip() for line in (tool.description or "").strip().splitlines() if line.strip()]
    return lines[0][:120] if lines else ""


def capability_map(mcp: Any) -> dict[str, list[str]]:
    """분류 -> 도구 이름들(메타 도구 제외). 등록된 모든 도구가 정확히 한 분류에 들어간다."""
    groups: dict[str, list[str]] = {}
    for name in sorted(_tools(mcp)):
        if name not in META:
            groups.setdefault(_group_of(name), []).append(name)
    rank = lambda title: next((i for i, head in enumerate(_ORDER) if title.startswith(head)), len(_ORDER))
    return dict(sorted(groups.items(), key=lambda item: rank(item[0])))


def _map_text(mcp: Any) -> str:
    return "\n".join(f"- {title}: " + ", ".join(f"{name} ({_HINTS[name]})" if name in _HINTS else name for name in names)
                     for title, names in capability_map(mcp).items())


_WORD = re.compile(r"[A-Za-z0-9]+|[가-힣]+")


def _tokens(text: str) -> list[str]:
    """영문은 단어, 한글은 어절과 두 글자 조각(조사·어미가 달라도 맞게)."""
    out: list[str] = []
    for word in _WORD.findall(text.lower()):
        out.append(word[:-1] if len(word) > 3 and word.endswith("s") and word[-2] != "s" else word)  # 복수형: indents -> indent
        if "가" <= word[0] <= "힣" and len(word) > 2:
            out.extend(word[i:i + 2] for i in range(len(word) - 1))
    return out


def _index(mcp: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, float]]:
    tools = {name: tool for name, tool in _tools(mcp).items() if name not in META}
    docs = {}
    for name, tool in tools.items():
        hint = _HINTS.get(name, "")
        description = _tokens(f"{tool.description or ''} {hint} {hint}")  # 한 줄 설명은 두 번 세어 가중
        arguments = _tokens(" ".join(tool.parameters.get("properties", {})))  # 에이전트는 인수 이름(indent_left_mm 등)으로도 찾는다
        docs[name] = {"name": set(_tokens(name)), "group": set(_tokens(_group_of(name))), "args": set(arguments),
                      "tf": {w: description.count(w) for w in set(description)}}
    frequency: dict[str, int] = {}
    for doc in docs.values():
        for word in doc["name"] | doc["group"] | doc["args"] | set(doc["tf"]):
            frequency[word] = frequency.get(word, 0) + 1
    idf = {word: math.log(1 + len(docs) / count) for word, count in frequency.items()}
    return tools, docs, idf


def search(mcp: Any, query: str, limit: int) -> list[dict[str, Any]]:
    """이름·분류·설명에서 질의어를 찾는다(드문 단어일수록 무겁게). 빈 질의는 모든 도구를 돌려준다."""
    tools, docs, idf = _index(mcp)
    text = query.lower().strip()
    expanded = text + " " + " ".join(english for korean, english in _SYNONYMS.items() if korean in text)
    words = set(_tokens(expanded))
    rows = []
    for name, tool in tools.items():
        doc = docs[name]
        if not words:
            score = 1.0
        else:
            score = sum(idf.get(w, 1.0) * (4 * (w in doc["name"]) + 2 * (w in doc["args"]) + 1.5 * (w in doc["group"]) + min(doc["tf"].get(w, 0), 3)) for w in words)
            if text == name:
                score += 1000
            elif name in text:
                score += 50
        if score > 0:
            rows.append((score, name, tool))
    rows.sort(key=lambda row: (-row[0], row[1]))
    if words:
        rows = rows[:limit]
    return [{"name": name, "group": _group_of(name), "runWith": _runner(tool), "always_listed": name in CORE, "summary": _summary(tool)}
            for _, name, tool in rows]


def _arguments(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise ToolInputError(f"arguments must be a JSON object, got text that is not JSON: {error}") from error
    if not isinstance(value, dict):
        raise ToolInputError(f"arguments must be an object of argument names to values, got {type(value).__name__}")
    return value


_HEAVY = ("verificationReport", "openSafety", "visualComplete", "semanticDiff", "backup")


def compact(result: dict[str, Any]) -> dict[str, Any]:
    """저장 검증 보고서(수 KB)를 한 줄 요약으로: 안전하게 열리는지, 무엇이 바뀌었는지, 경고. 전체는 verbose=true."""
    if not any(key in result for key in _HEAVY):
        return result
    report = result.get("verificationReport") or {}
    safety = result.get("openSafety") or report.get("openSafety") or {}
    visual = result.get("visualComplete") or report.get("visualComplete") or {}
    diff = result.get("semanticDiff") or report.get("semanticDiff") or {}
    backup = result.get("backup") or report.get("backup") or {}
    errors = [*(safety.get("validateDocument") or {}).get("errors", []), *(safety.get("validatePackage") or {}).get("errors", []), *(visual.get("errors") or [])]
    reopen = safety.get("reopen") or {}
    if reopen.get("error"):
        errors.append(str(reopen["error"]))
    summary = {key: value for key, value in result.items() if key not in _HEAVY}
    summary["check"] = {
        "opensSafely": bool(safety.get("ok", True)) and not errors,
        "changes": diff.get("summary"),
        "warnings": list(dict.fromkeys(report.get("warnings") or [])),
        "errors": errors,
        "backupCreated": bool(backup.get("created")),
        "fullReport": "run again with verbose=true",
    }
    return summary


_PATHLIKE = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\",;)\]}]*[\\/][^\s'\",;)\]}]+")


def _scrub(text: str) -> str:
    """경로처럼 보이는 글은 지운다(경로 노출이 업스트림이 오류 내용을 숨기는 이유다)."""
    return _PATHLIKE.sub("<path>", text)


def failed(result: dict[str, Any]) -> bool:
    """업스트림이 실패로 보는 응답인가(ok/success가 false, isError가 true)."""
    return result.get("ok") is False or result.get("success") is False or result.get("isError") is True


def failure_text(name: str, result: dict[str, Any]) -> str:
    parts = [value for key in ("error", "reason", "hint", "suggestion", "message") if isinstance((value := result.get(key)), str) and value]
    errors = result.get("errors")
    if isinstance(errors, list):
        parts += [str(item.get("message") or item.get("code")) for item in errors[:5] if isinstance(item, dict) and (item.get("message") or item.get("code"))]
    cause = "; ".join(dict.fromkeys(parts)) or "the tool reported a failure"
    detail = json.dumps(result, ensure_ascii=False)
    return _scrub(f"{name} did not succeed: {cause}. Its reply: {detail[:1200]}{' ...' if len(detail) > 1200 else ''}")


def install(mcp: Any, ext_tools: dict[str, Any], show_all: bool = False) -> None:
    """메타 도구를 등록하고 tools/list를 코어+메타로 줄인다. show_all이면 아무것도 하지 않는다."""
    if show_all:
        return

    def lookup(name: str) -> Any:
        tool = _tools(mcp).get(name)
        if tool is None or name in META:
            raise ToolInputError(f"unknown tool {name!r}; call hwpx_find_tools (empty query lists every tool)")
        return tool

    async def hwpx_tool_schema(name: str) -> dict[str, Any]:
        tool = lookup(name)
        out = {"name": name, "runWith": _runner(tool), "edits": _edits(tool),
               "group": _group_of(name), "description": tool.description, "arguments": tool.parameters}
        if name in _NOTES:
            out["notes"] = _NOTES[name]
        if name in EXAMPLES:
            out["examples"] = EXAMPLES[name]  # "arguments"를 hwpx_run_read / hwpx_run_edit에 그대로 넘기면 된다
            out["examplesNote"] = "Sample calls: file names, paragraph numbers and texts are placeholders - read the real ones first (hwpx_read_layout part=body, get_paragraphs_text)."
        return out

    async def _run(name: str, arguments: Any, want_edit: bool, verbose: bool = False) -> dict[str, Any]:
        tool = lookup(name)
        if _edits(tool) != want_edit:
            raise ToolInputError(f"{name} {'only reads' if want_edit else 'edits documents'}: run it with {_runner(tool)}")
        try:
            result = await mcp.call_tool(name, _arguments(arguments))
        except ToolError as error:
            if isinstance(error.__cause__, ValidationError):
                required = tool.parameters.get("required", [])
                problems = "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.__cause__.errors()[:6])
                raise ToolInputError(f"arguments of {name} are invalid ({problems}). Required: {required}. See hwpx_tool_schema({name!r}).") from error
            raise
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
            reply = result[1]
            if failed(reply):  # 업스트림은 고정 문장으로 바꿔 버리므로 실제 이유(error / hint)를 살려 넘긴다
                raise ToolInputError(failure_text(name, reply))
            if name == "mcp_server_health":
                reply = {"verdict": "ok" if (reply.get("toolSurface") or {}).get("status") == "ok" else "check toolSurface / status", **reply}
            return reply if verbose else compact(reply)
        content = result[0] if isinstance(result, tuple) else result
        return {"text": [getattr(block, "text", str(block)) for block in content]}

    async def hwpx_run_read(name: str, arguments: dict[str, Any] | None = None, verbose: bool = False) -> dict[str, Any]:
        return await _run(name, arguments, False, verbose)

    async def hwpx_run_edit(name: str, arguments: dict[str, Any] | None = None, verbose: bool = False) -> dict[str, Any]:
        return await _run(name, arguments, True, verbose)

    async def hwpx_find_tools(query: str = "", limit: int = 15) -> dict[str, Any]:
        found = search(mcp, query, max(1, limit))
        return {"total": len(found), "tools": found, "next": "hwpx_tool_schema(name) shows the arguments; then hwpx_run_read / hwpx_run_edit(name, arguments)"}

    find_doc = (
        "Find tools of this HWPX server. Only a few tools are listed up front; EVERY tool is available through hwpx_run_read (reads) and hwpx_run_edit (edits a document).\n"
        "Workflow: 1) hwpx_find_tools(query) - Korean or English keywords, EMPTY query lists every tool; 2) hwpx_tool_schema(name) - the arguments; "
        "3) hwpx_run_read / hwpx_run_edit(name, arguments). Tools marked always_listed can be called directly.\n"
        + _RECIPES + "ALL TOOLS BY GROUP (complete list, with a one-line hint each):\n" + _map_text(mcp)
    )
    metas = (
        (hwpx_find_tools, find_doc, True),
        (hwpx_tool_schema, "Full description and argument schema of one tool by name (names from hwpx_find_tools), usage notes and realistic example calls where the schema alone is not obvious. Returns which runner to use: hwpx_run_read or hwpx_run_edit.", True),
        (hwpx_run_read, "Run a READ-ONLY tool by name with an arguments object (see hwpx_tool_schema). Refuses tools that edit. Never changes a file. verbose=true returns the tool's full reply.", True),
        (hwpx_run_edit, "Run a tool that EDITS a document by name with an arguments object (see hwpx_tool_schema). Edits keep a backup (undo_last_edit) and accept dry_run / expected_revision where the tool has them. The reply is compact (check: opensSafely, changes, warnings); verbose=true returns the full verification report.", False),
    )
    for fn, description, read_only in metas:
        register(mcp, ext_tools, fn, description, not read_only)

    low = mcp._mcp_server
    areas = " / ".join(title.split(" (")[0] for title in capability_map(mcp))
    low.instructions = ((low.instructions + " ") if low.instructions else "") + (
        f"Most HWPX tools are not listed up front. Capability areas: {areas}. "
        "Find a tool with hwpx_find_tools (its description lists every tool by group; an empty query lists all), "
        "read its arguments, notes and example calls with hwpx_tool_schema, and run it with hwpx_run_read or hwpx_run_edit.")
    original = low.request_handlers[types.ListToolsRequest]

    async def listed(request: types.ListToolsRequest) -> types.ServerResult:
        response = await original(request)
        keep = [tool for tool in response.root.tools if tool.name in CORE or tool.name in META]
        return types.ServerResult(types.ListToolsResult(tools=keep))

    low.request_handlers[types.ListToolsRequest] = listed
