#!/usr/bin/env python3
"""출제 지침에서 지금 필요한 절만 골라 보여 준다.

사용: python3 guide.py 영역[,영역…] [단계[,단계…]]
      python3 guide.py --list
  영역: 공통 문학 독서 화법작문 문법 서술형 학교 분석 오답코드
  단계: 설계 작성 해설 검수 (적지 않으면 모든 단계)
  출제 영역(문학·독서·화법작문·문법·서술형·학교)을 부르면 공통 지침이, 분석을 부르면 오답코드가 함께 나온다.
  --only  함께 나오는 공통·오답코드를 빼고 적은 영역만(이미 읽은 대화에서 다른 영역으로 넘어갈 때).
지침 파일(references/*.md)의 각 `## 절` 바로 아래 `<!-- 단계: … -->` 표지로 절을 고른다. `전체`는 모든 단계에 나온다.
표준 라이브러리만 쓴다."""
import re, sys
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / 'references'
AREAS = {'공통': 'common.md', '문학': 'literature.md', '독서': 'reading.md', '화법작문': 'speech-writing.md',
         '문법': 'grammar.md', '서술형': 'written-answer.md', '학교': 'school.md', '분석': 'analysis.md', '오답코드': 'codes.md'}
ALIASES = {'화작': '화법작문', '화법': '화법작문', '작문': '화법작문', '매체': '화법작문', '언어': '문법', '언매': '문법',
           '논술형': '서술형', '서답형': '서술형', '내신': '학교', '코드': '오답코드', '비문학': '독서'}
WITH = {**{a: '공통' for a in ('문학', '독서', '화법작문', '문법', '서술형', '학교')}, '분석': '오답코드'}
STAGES = ('설계', '작성', '해설', '검수')
TAG = re.compile(r'<!-- 단계: (.+?) -->')


def fail(msg):
    print(f'오류: {msg}', file=sys.stderr); sys.exit(1)


def sections(area):
    """(머리말, [(제목, 단계 집합, 본문)]) — 표지가 없거나 모르는 단계면 오류."""
    parts, fence = [[]], False
    for line in (REF / AREAS[area]).read_text(encoding='utf-8').splitlines(keepends=True):
        if line.startswith('```'): fence = not fence
        if line.startswith('## ') and not fence: parts.append([])  # 코드 블록(양식) 안의 ## 는 절 제목이 아니다
        parts[-1].append(line)
    head, *parts = [''.join(p) for p in parts]
    out = []
    for p in parts:
        title, _, body = p.partition('\n')
        m = TAG.match(body.lstrip('\n'))
        if not m: fail(f'{AREAS[area]}의 "{title}" 절 바로 아래에 <!-- 단계: … --> 표지가 없습니다')
        stages = {s.strip() for s in m.group(1).split(',')}
        if stages - set(STAGES) - {'전체'}: fail(f'{AREAS[area]}의 "{title}" 절에 모르는 단계 {sorted(stages - set(STAGES) - {"전체"})}')
        out.append((title, stages, TAG.sub('', body, count=1).strip('\n')))
    return head.strip(), out


def pick(args, only=False):
    areas, stages = [], []
    for tok in (t for a in args for t in a.split(',') if t):
        tok = ALIASES.get(tok, tok)
        if tok in AREAS: areas.append(tok)
        elif tok in STAGES: stages.append(tok)
        else: fail(f'"{tok}"은(는) 모르는 영역·단계입니다. 영역: {" ".join(AREAS)} / 단계: {" ".join(STAGES)}')
    if not areas: fail(f'영역을 하나 이상 적으세요. 영역: {" ".join(AREAS)}')
    order = []
    for a in areas:  # 공통은 맨 앞, 오답코드는 분석 뒤
        extra = None if only else WITH.get(a)
        for x in ([extra, a] if extra == '공통' else [a, extra] if extra else [a]):
            if x not in order: order.append(x)
    if '공통' in order: order.remove('공통'); order.insert(0, '공통')
    return order, stages or list(STAGES)


def main(argv):
    if not argv or argv[0] in ('-h', '--help'): print(__doc__); return
    if argv[0] == '--list':
        for a, f in AREAS.items():
            print(f'### {a} (references/{f})')
            for title, st, _ in sections(a)[1]: print(f'{title}  [{", ".join(sorted(st))}]')
        return
    areas, stages = pick([a for a in argv if a != '--only'], '--only' in argv)
    for a in areas:
        head, secs = sections(a)
        chosen = [(t, b) for t, st, b in secs if '전체' in st or st & set(stages)]
        print(f'\n########## {a} (references/{AREAS[a]}) — 단계: {", ".join(stages)}\n')
        print(head + '\n')
        for t, b in chosen: print(f'{t}\n{b}\n')
        if not chosen: print('(이 영역에는 이 단계의 절이 따로 없다. 공통 지침의 같은 단계를 따른다.)\n')


if __name__ == '__main__':
    main(sys.argv[1:])
