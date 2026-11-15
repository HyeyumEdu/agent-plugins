#!/usr/bin/env python3
"""시험 내용 JSON(exam-basic 스킬의 build_exam.py 입력과 같은 형식)의 객관식 문항을 세어 출제 합격선과 견준다.

사용: python3 check_items.py 내용.json [--school] [--area 문학|독서|기타]
  --school  내신 대비: 수능형 기준(긍정 발문 비율, '라는 점에서', 선지 길이)은 '참고'로만 낸다(학교 기준을 따른다).
  --area    선지 길이 기준의 영역(기본 문학). 독서는 기출 중앙값을 참고로, 기타(화법·작문·문법·섞인 시험지)는 길이 판정 없이 값만 낸다.
판정은 안내용이라 종료 코드는 입력 오류일 때만 1이다. 표준 라이브러리만 쓴다."""
import json, re, statistics, sys

NEG = re.compile(r'않은|않는|아닌|없는|틀린')
LENGTH = {'문학': ((58, 81), (32, 47)), '독서': ((53, 53), (33, 33)), '기타': None}  # (〈보기〉 문항, 그 외) 중앙값 기준. 독서는 기출 중앙값 한 점


def fail(msg):
    print(f'오류: {msg}', file=sys.stderr); sys.exit(1)


def load(path):
    try: data = json.loads(open(path, encoding='utf-8-sig').read())
    except (OSError, ValueError) as e: fail(f'{path}을(를) JSON으로 읽지 못했습니다 ({e})')
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list): fail('최상위에 "items" 목록이 있어야 합니다(exam-basic 스킬의 JSON 형식)')
    qs = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict) or it.get('type') != 'question': continue
        n = len(qs) + 1; ch = it.get('choices'); a = it.get('answer')
        if not (isinstance(ch, list) and len(ch) == 5 and all(isinstance(c, str) for c in ch)): fail(f'{n}번 문항(items {i}번째): choices는 글 5개여야 합니다')
        if not (isinstance(a, int) and 1 <= a <= 5): fail(f'{n}번 문항(items {i}번째): answer는 1~5 숫자여야 합니다')
        if not isinstance(it.get('stem'), str): fail(f'{n}번 문항(items {i}번째): stem(발문)이 없습니다')
        qs.append(dict(stem=it['stem'], choices=ch, answer=a, bogi='bogi' in it or '〈보기〉' in it['stem']))
    if not qs: fail('객관식 문항(type "question")이 없습니다')
    return qs


def runs(answers):  # 같은 정답 번호가 3번 이상 이어지는 구간(1부터 센 문항 번호)
    out, start = [], 0
    for i in range(1, len(answers) + 1):
        if i == len(answers) or answers[i] != answers[start]:
            if i - start >= 3: out.append((start + 1, i, answers[start]))
            start = i
    return out


def judge(value, lo, hi, ref=False):
    return '참고' if ref else ('통과' if lo <= value <= hi else '주의')


def report(qs, school=False, area='문학'):
    n = len(qs); few = n < 10; lines = []
    ans = [q['answer'] for q in qs]
    dist = [ans.count(k) for k in range(1, 6)]
    longest = shortest = 0; rows = []
    for k, q in enumerate(qs, 1):
        L = [len(c) for c in q['choices']]; a = L[q['answer'] - 1]
        rank = 1 + sum(x > a for x in L)
        longest += a == max(L); shortest += a == min(L)
        rows.append((k, q['answer'], rank, max(L) - min(L), a == min(L)))
    choices = [c for q in qs for c in q['choices']]
    commas = sum(c.count(',') for c in choices) / len(choices)
    jeom = sum(c.count('라는 점에서') for c in choices)
    pos = sum(not NEG.search(q['stem']) for q in qs) / n
    lines.append(f'문항 {n}개' + (' (10개 미만이라 비율 판정은 참고만)' if few else '') + (' · 내신 기준(--school)' if school else ' · 수능형 기준'))
    over = ['①②③④⑤'[k] for k, c in enumerate(dist) if n >= 5 and c / n > 0.4]  # 5문항 미만은 쏠림을 따지지 않는다
    rr = runs(ans)
    lines.append('정답 분포: ' + ' '.join(f'{"①②③④⑤"[k]}{c}' for k, c in enumerate(dist))
                 + ('  [주의] 40% 넘는 번호: ' + ', '.join(over) if over else '')
                 + ('  [주의] 3번 이상 연속: ' + ', '.join(f'{s}~{e}번 {"①②③④⑤"[v - 1]}' for s, e, v in rr) if rr else ''))
    lines.append(f'정답이 가장 긴 문항: {longest}/{n} ({longest / n:.0%}) 기준 15~30% → {judge(longest / n, .15, .30, few)}')
    lines.append(f'정답이 가장 짧은 문항: {shortest}/{n} ({shortest / n:.0%}) 기준 10~20% → {judge(shortest / n, .10, .20, few)}')
    lines.append(f'선지 쉼표 평균: {commas:.2f}개 기준 0.4~0.7 → {judge(commas, .4, .7)}')
    lines.append(f"'라는 점에서': {jeom}회 기준 0회(수능형) → {judge(jeom, 0, 0, school)}")
    lines.append(f'긍정 발문: {pos:.0%} 기준 35~45%(수능형) → {judge(pos, .35, .45, school or few)}')
    for k, (name, flag) in enumerate((('〈보기〉 문항', True), ('그 외 문항', False))):
        ls = [len(c) for q in qs if q['bogi'] == flag for c in q['choices']]
        if not ls: continue
        med = statistics.median(ls); rng = LENGTH[area] and LENGTH[area][k]
        if not rng: lines.append(f'선지 길이 중앙값({name}): {med:g}자 → 참고(영역 기준 없음)')
        elif rng[0] == rng[1]: lines.append(f'선지 길이 중앙값({name}): {med:g}자 {area} 기출 중앙값 {rng[0]}자 → 참고')
        else: lines.append(f'선지 길이 중앙값({name}): {med:g}자 {area} 기준 {rng[0]}~{rng[1]}자 → {judge(med, *rng, school)}')
    lines.append('문항별: 번호 정답 정답길이순위(1=가장 김) 최장−최단')
    for k, a, rank, gap, short in rows:
        note = []
        if rank == 1: note.append('정답이 가장 김')
        elif short: note.append('정답이 가장 짧음')
        if gap > 20: note.append('길이 차 20자 넘음')
        lines.append(f'  {k:>2}번 {"①②③④⑤"[a - 1]} {rank}위 {gap:>2}자' + (f'  ← {", ".join(note)}' if note else ''))
    return lines


def main(argv):
    area = '문학'
    if '--area' in argv:
        i = argv.index('--area'); area = argv[i + 1] if i + 1 < len(argv) else ''
        if area not in LENGTH: fail(f'--area는 {"·".join(LENGTH)} 중 하나입니다')
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if a != '--school']
    if len(args) != 1 or args[0] in ('-h', '--help'): print(__doc__); sys.exit(0 if args[:1] in (['-h'], ['--help']) else 1)
    print('\n'.join(report(load(args[0]), '--school' in argv, area)))


if __name__ == '__main__':
    main(sys.argv[1:])
