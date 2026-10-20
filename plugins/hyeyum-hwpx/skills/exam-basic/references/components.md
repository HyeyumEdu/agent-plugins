## 형식 basic — 기본 시험지

문항 형식: choice5

| 부품 | 이름 | 종류 | 설명 | 쓰는 JSON 항목 | 검사 규칙 |
|---|---|---|---|---|---|
| title | 제목 | para | 시험지 제목 줄(가운데, 15pt 굵게) | title | G7, G8, G50 |
| blank | 빈 줄 | para | 본문 글자 크기의 빈 문단 | blank | G37, G50 |
| gap-3pt | 3pt 빈 줄 | para | 안내문과 지문 사이 글자 3pt 빈 문단(자동) | instruction(자동) | G37, G41, G50 |
| instruction | 안내문 | para | ※로 시작하는 안내문(다음 문단과 함께 쪽에 남는다) | instruction | G41, G42, G50 |
| passage-border | 지문(문단 테두리) | para | 문단 테두리로 묶인 지문: 본문·굵게·밑줄·줄거리·출처줄 | passage | G44, G45, G46, G47, G50 |
| stem | 발문 | para | 번호·배점이 붙는 발문과 굵게+밑줄 부정 낱말 | question.stem | G9, G10, G11, G15, G16, G21, G26, G40, G50 |
| bogi-box | 보기 상자 | table | 〈 보 기 〉 1×1 표(글자처럼 취급): 시·산문 줄과 출처줄 | question.bogi | G17, G33, G39, G50 |
| choice5 | 선택지(5지선다) | para | ①+탭+본문 선택지(둘째 줄은 본문 시작에 맞춤) | question.choices | G13, G14, G19, G20, G23, G25, G36, G49, G50 |
| answer-note | 정답·해설 미주 | endnote | 정답·배점, 출제 포인트, 정답 해설, 오답 분석이 든 미주 | question.note | G12, G18, G27, G31, V9, G50 |
| end-heading | 정답과 해설 제목 | para | 맨 끝 새 쪽의 정답과 해설 제목(13pt 굵게, 자동) | end_heading(자동) | G35, G50 |
