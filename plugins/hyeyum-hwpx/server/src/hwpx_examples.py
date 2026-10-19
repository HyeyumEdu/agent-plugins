"""호출 예시(tool use examples): 스키마만으로 쓰는 법이 분명치 않은 도구마다 현실적인 예시 1~3개. hwpx_tool_schema 응답의 `examples`로 나간다.

tests/test_hwpx_lazy.py가 모든 예시를 도구의 인수 모델에 대어 보고, dry_run이 있는 도구는 시험 문서에 실제로 돌려 본다(낡은 예시는 여기서 걸린다).
예시의 문서는 `exam.hwpx`, 문단 번호는 그 시험 문서 기준: 0 구역 정의, 1 빈 줄, 2 제목, 3 1번 문제, 4 선택지, 5 세포 주기, 6 마지막 문단, 표 0번.
"""
from typing import Any

F = "exam.hwpx"

EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "set_paragraph_format_ext": [
        {"does": "내어쓰기(첫 줄 -3mm)와 왼쪽 여백 5mm", "arguments": {"filename": F, "paragraph_index": 3, "indent_left_mm": 5, "first_line_indent_mm": -3}},
        {"does": "40mm 위치 왼쪽 탭 정지 + 어절 단위 줄바꿈", "arguments": {"filename": F, "paragraph_index": 4, "tab_stops": [{"pos_mm": 40, "type": "LEFT"}], "break_non_latin_word": "BREAK_WORD"}},
        {"does": "두 문단을 하나의 테두리 상자로 이어 붙이기", "arguments": {"filename": F, "paragraph_indexes": [2, 3], "border": {"type": "SOLID", "width": "0.12 mm", "color": "#000000", "offset_mm": 2, "connect": True}}},
    ],
    "format_text_ext": [
        {"does": "글자 범위(3~6번째)에 굵게 + 자간 -5%", "arguments": {"filename": F, "paragraph_index": 3, "start_pos": 3, "end_pos": 6, "bold": True, "letter_spacing": -5}},
        {"does": "빈 문단(간격 줄)의 글자 크기를 3pt로", "arguments": {"filename": F, "paragraph_index": 1, "start_pos": 0, "end_pos": 0, "font_size": 3}},
        {"does": "노란 형광펜", "arguments": {"filename": F, "paragraph_index": 5, "start_pos": 4, "end_pos": 6, "highlight": "#FFFF00"}},
    ],
    "insert_inline_ext": [
        {"does": "'불빛은' 바로 뒤에 각주", "arguments": {"filename": F, "paragraph_index": 3, "anchor_text": "불빛은", "items": [{"footnote": "등대에서 나오는 빛"}]}},
        {"does": "글 8번째 자리에 아래첨자 수식", "arguments": {"filename": F, "paragraph_index": 5, "position": 8, "items": [{"equation": "{}_{1}"}]}},
        {"does": "기존 글에 하이퍼링크 걸기(같은 글로 바꿔치기)", "arguments": {"filename": F, "paragraph_index": 3, "anchor_text": "등대의 불빛은", "replace_anchor": True, "items": [{"hyperlink": {"url": "https://example.com", "text": "등대의 불빛은"}}]}},
        {"does": "문단 맨 앞에 그림(너비 20mm)", "arguments": {"filename": F, "paragraph_index": 6, "position": 0, "items": [{"picture": {"path": "logo.png", "width_mm": 20}}]}},
        {"does": "표 칸 안 문단에 수식", "arguments": {"filename": F, "table_index": 0, "row": 1, "col": 1, "position": 0, "items": [{"equation": "x^{2}"}]}},
    ],
    "add_paragraphs_ext": [
        {"does": "가운데 제목 + 3pt 간격 줄 + 수식이 든 본문을 2번 문단 앞에", "arguments": {"filename": F, "before_index": 2, "paragraphs": [
            {"text": "제목", "format": {"alignment": "CENTER"}, "char": {"font_size": 15, "bold": True}}, {"text": "", "char": {"font_size": 3}},
            {"runs": [{"text": "세포 주기는 G"}, {"equation": "{}_{1}"}, {"text": "기 이다"}]}]}},
        {"does": "선택지(탭 + 다음 문단과 붙이기), 스타일 지정", "arguments": {"filename": F, "paragraphs": [{"text": "①\t등대의 불빛은", "tab": {"width": 519}, "style": "본문", "format": {"keep_with_next": True}}]}},
    ],
    "add_endnote_ext": [
        {"does": "문제 문단에 정답·해설 미주(여러 문단, 빈 마지막 문단)", "arguments": {"filename": F, "paragraph_index": 3, "paragraphs": [
            {"runs": [{"text": " "}, {"text": "정답 ③ [3.6점]", "bold": True}]}, {"text": "출제 포인트  세부 내용 일치", "char": {"font_size": 9.5}}, {"text": ""}]}},
    ],
    "format_table_ext": [
        {"does": "열 폭·행 높이(HWPUNIT)", "arguments": {"filename": F, "table_index": 0, "column_widths": [10000, 20000, 12000], "row_heights": [1500, 2000, 2000]}},
        {"does": "첫 행 가로 병합 + 모든 칸 선 0.5mm", "arguments": {"filename": F, "table_index": 0, "merges": [[0, 0, 0, 2]], "cells_border": {"type": "SOLID", "width": "0.5 mm"}}},
        {"does": "칸 하나의 세로 가운데 + 글 바꾸기", "arguments": {"filename": F, "table_index": 0, "cells": [{"row": 1, "col": 1, "vertical_align": "CENTER", "paragraphs": [{"text": "정답 ③", "format": {"alignment": "CENTER"}}]}]}},
    ],
    "apply_style_ext": [
        {"does": "문단에 '본문' 스타일(먼저 적용하고 그 뒤에 개별 서식)", "arguments": {"filename": F, "paragraph_indexes": [3, 4], "style": "본문"}},
    ],
    "define_style_ext": [
        {"does": "3번 문단의 모양을 본떠 '시험문제' 스타일 만들기", "arguments": {"filename": F, "name": "시험문제", "from_paragraph_index": 3}},
    ],
    "set_list_format_ext": [
        {"does": "번호 매기기(1. 2. …), 번호 글자만 13pt 굵게", "arguments": {"filename": F, "paragraph_indexes": [3], "kind": "number", "number_format": "DIGIT", "number_char": {"font_size": 13, "bold": True}}},
    ],
    "set_page_options_ext": [
        {"does": "줄 번호를 5줄마다 쪽마다 새로 표시", "arguments": {"filename": F, "line_numbers": {"restart_type": 1, "count_by": 5, "distance": 850, "start_number": 1, "show": True}}},
        {"does": "첫 쪽 머리말 감추기", "arguments": {"filename": F, "hide_first": {"header": True}}},
    ],
    "add_page_control_ext": [
        {"does": "이 문단이 있는 쪽의 머리말·쪽번호 감추기", "arguments": {"filename": F, "paragraph_index": 2, "hide": {"header": True, "page_num": True}}},
        {"does": "이 문단부터 쪽 번호를 1부터 다시", "arguments": {"filename": F, "paragraph_index": 6, "restart_page_number": {"number": 1}}},
    ],
    "set_columns_ext": [
        {"does": "2단 + 실선 구분선(간격 8mm = 2268)", "arguments": {"filename": F, "columns": 2, "gap": 2268, "separator_type": "SOLID", "separator_width": "0.12 mm", "separator_color": "#000000"}},
    ],
    "copy_paragraphs_ext": [
        {"does": "3~4번 문단(한 문항)을 6번 문단 앞에 복제", "arguments": {"filename": F, "start_index": 3, "end_index": 4, "before_index": 6}},
    ],
    "insert_document_ext": [
        {"does": "other.hwpx를 6번 문단 뒤에 끼워 넣기", "arguments": {"filename": F, "source_filename": "other.hwpx", "after_paragraph_index": 6}},
    ],
    "set_tab_attributes": [
        {"does": "문단 안의 탭 글자를 한컴 형태(폭 519)로", "arguments": {"filename": F, "paragraph_index": 4, "width": 519, "tab_type": 1}},
    ],
    "add_table": [
        {"does": "3행 3열 표(첫 행에 제목 글)", "arguments": {"filename": F, "rows": 3, "cols": 3, "data": [["이름", "번호", "점수"], ["", "", ""], ["", "", ""]]}},
    ],
    "merge_table_cells": [
        {"does": "0번 표의 첫 행을 가로로 합치기(0,0 ~ 0,2)", "arguments": {"filename": F, "table_index": 0, "start_row": 0, "start_col": 0, "end_row": 0, "end_col": 2}},
    ],
    "set_table_cell_text": [
        {"does": "0번 표 1행 1열 칸의 글 바꾸기", "arguments": {"filename": F, "table_index": 0, "row": 1, "col": 1, "text": "정답 ③"}},
    ],
    "set_page_setup": [
        {"does": "A4 세로, 여백 위 20 아래 15 좌우 20mm", "arguments": {"filename": F, "paper_size": "A4", "orientation": "portrait", "margin_top_mm": 20, "margin_bottom_mm": 15, "margin_left_mm": 20, "margin_right_mm": 20}},
    ],
    "set_header_footer": [
        {"does": "머리말 글", "arguments": {"filename": F, "kind": "header", "text": "2026학년도 국어 중간고사"}},
    ],
    "set_page_number": [
        {"does": "아래 가운데 쪽번호", "arguments": {"filename": F, "position": "BOTTOM_CENTER"}},
    ],
    "search_and_replace": [
        {"does": "문서 전체에서 글 바꾸기", "arguments": {"filename": F, "find_text": "중간고사", "replace_text": "기말고사"}},
    ],
    "replace_in_paragraph": [
        {"does": "한 문단 안에서만 바꾸기", "arguments": {"filename": F, "paragraph_index": 6, "old_text": "마지막", "new_text": "끝"}},
    ],
    "add_memo": [
        {"does": "문단에 메모 달기", "arguments": {"filename": F, "paragraph_index": 4, "text": "확인 필요"}},
    ],
    "delete_paragraph": [
        {"does": "6번 문단 지우기", "arguments": {"filename": F, "paragraph_index": 6}},
    ],
    "insert_paragraph": [
        {"does": "2번 문단 앞에 문단 넣기(앞 문단의 서식을 이어받음; 모양을 정하려면 add_paragraphs_ext)", "arguments": {"filename": F, "paragraph_index": 2, "text": "새 문단"}},
    ],
    "find_text": [
        {"does": "글이 있는 문단 번호와 위치 찾기", "arguments": {"filename": F, "text_to_find": "선택지"}},
    ],
    "get_paragraphs_text": [
        {"does": "문단 번호와 글 보기(번호는 0부터)", "arguments": {"filename": F, "start_index": 0, "end_index": 7}},
    ],
    "add_tracked_edit": [
        {"does": "변경 추적으로 바꾼 새 파일 만들기(원본은 그대로)", "arguments": {"source_filename": F, "destination_filename": "redline.hwpx", "edits": [{"type": "replace", "paragraph_index": 2, "old": "중간고사", "new": "기말고사"}]}},
    ],
    "copy_document": [
        {"does": "문서 사본 만들기", "arguments": {"source_filename": F, "destination_filename": "backup.hwpx"}},
    ],
    "undo_last_edit": [
        {"does": "직전 편집(한 단계) 되돌리기", "arguments": {"filename": F}},
    ],
}
