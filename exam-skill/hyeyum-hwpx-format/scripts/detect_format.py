"""올린 .hwpx 가 등록된 시험지 형식(assets/formats.json) 중 어느 것과 가장 닮았는지 알려 준다(표준 라이브러리만).
헤더의 문단·글자 모양 모음을 각 형식 템플릿과 자카드 유사도로 견준다.
shortcut: 모양 모음만 보므로 골든에서 많이 고친 파일은 '판별 불가'가 나올 수 있다 — 그때는 사용자에게 형식을 묻는다."""
import importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USAGE = '사용: python3 detect_format.py 파일.hwpx'


def load_verify():  # python3 -I 는 스크립트 폴더를 sys.path 에 넣지 않으므로 경로로 불러온다
    sys.dont_write_bytecode = True  # 스킬 폴더에 __pycache__ 를 남기지 않는다
    spec = importlib.util.spec_from_file_location('verify_exam', Path(__file__).with_name('verify_exam.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def signature(V, path):
    d = V.Doc(path)
    paras = {tuple(sorted(d.para(i).items())) for i in d.pp}
    chars = {(d.cp[i].get('height'), d.bold(i), d.italic(i), d.under(i), d.font(i) if d.cp[i].find(V.H + 'fontRef') is not None else None) for i in d.cp}
    return paras, chars


def jaccard(a, b): return len(a & b) / len(a | b) if a | b else 0.0


def main(argv):
    if len(argv) != 1 or argv[0] in ('-h', '--help'): print(USAGE); return 2
    V = load_verify()
    formats = json.loads((ROOT / 'assets/formats.json').read_text(encoding='utf-8'))
    try:
        fp, fc = signature(V, argv[0])
    except ValueError as e:
        print(f'오류: {argv[0]}: {e}', file=sys.stderr); return 1
    scores = []
    for f in formats:
        tpl = ROOT / f'assets/templates/exam_template_{f["kind"]}.hwpx'
        if not tpl.exists(): continue
        tp, tc = signature(V, tpl)
        scores.append(((jaccard(fp, tp) + jaccard(fc, tc)) / 2, f))
    if not scores: print('오류: 비교할 형식 템플릿이 없습니다', file=sys.stderr); return 1
    scores.sort(key=lambda x: -x[0])
    best, f = scores[0]; gap = best - (scores[1][0] if len(scores) > 1 else 0)
    level = '확실' if best >= .5 and gap >= .15 else '가능성 높음' if best >= .3 and gap >= .1 else '판별 불가'
    detail = ' / '.join(f'{g["kind"]}형 {s:.2f}' for s, g in scores)
    if level == '판별 불가':
        print(f'형식 판별: 판별 불가 (일치도 {detail}) — 사용자에게 어느 형식인지 묻는다'); return 0
    print(f'형식 판별: {f["kind"]}형 {f["title"]} → /hyeyum-hwpx:{f["id"]}  ({level}; 일치도 {detail})'); return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
