#!/usr/bin/env python3
"""정답 검증용: 정답·해설을 가린 문항 묶음을 만들고(make), 풀이 결과를 정답표와 맞춰 본다(compare).

사용: python3 blind.py make 입력 작업폴더 [--answers 3,5,1,…]
        입력: 시험 내용 JSON(exam-basic 형식) · 한글 시험지(.hwpx) · extract_hwpx_text.py 출력(.txt)
        작업폴더에 문항.md(전체, 정답 없음), 세트01.md…(지문 묶음별, 정답 없음), 정답표.json(풀이가 끝날 때까지 열지 않는다)을 쓴다.
        --answers  교사가 따로 준 정답(문항 순서대로 쉼표로). 파일 안 정답(미주)과 다르면 compare가 알린다.
        화면에는 개수만 나오고 정답은 나오지 않는다. 해설 글이 묶음에 섞였으면 멈춘다.
      python3 blind.py compare 작업폴더 풀이1.json [풀이2.json …]
        풀이 결과(형식은 guide.py 풀이자)를 정답표와 맞춰 문항마다 확인·정답 불일치·복수 정답 소지·정답 없음 소지·풀이자끼리 갈림·애매·판정 보류를 표시하고,
        정답표 자체의 일관성(미주와 교사 정답, 오답 분석 번호)도 본다. 최종 판정은 사람(모델)이 근거로 한다.
표준 라이브러리만 쓴다. 입력 오류만 종료 코드 1."""
import contextlib, importlib.util, io, json, re, sys, unicodedata
from pathlib import Path

CIRC = '①②③④⑤'
NEG = re.compile(r'않은|않는|아닌|없는|틀린|못한|잘못|어긋나는|거리가 먼|다른 하나|다른 것')  # check_items.py 와 같은 정의
SCORE = re.compile(r'\s*\[(\d+(?:\.\d+)?)점\]\s*$')
NOTE = re.compile(r'\[미주[^\]]*\]\s*(.*)')
ANSWER_AREA = re.compile(r'\W*정답\s*(과|및|·)?\s*(해설|표)\W*')


def fail(msg):
    print(f'오류: {msg}', file=sys.stderr); sys.exit(1)


def plain(s): return re.sub(r'</?u>|\*\*', '', s)


def nfc(s): return unicodedata.normalize('NFC', s)


def negative(stem):  # 부정 발문인가. 괄호 안 단서('(단, …없는 …)')는 보지 않는다
    return bool(NEG.search(re.sub(r'\([^)]*\)', '', nfc(plain(stem)))))


def lab(n): return CIRC[n - 1] if isinstance(n, int) and 1 <= n <= 5 else f'({n})'


def is_int(x): return isinstance(x, int) and not isinstance(x, bool)


def strs(x): return isinstance(x, list) and all(isinstance(v, str) for v in x)


def new_set(sets, head=''):
    sets.append({'head': head, 'passage': [], 'qs': []}); return sets[-1]


def from_json(data):
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list): fail('JSON 최상위에 "items" 목록이 있어야 합니다(exam-basic 시험 내용 형식)')
    sets = []; cur = None
    for i, it in enumerate(items, 1):
        w = f'items {i}번째'
        if not isinstance(it, dict): fail(f'{w}: 항목은 {{"type": …}} 꼴이어야 합니다')
        t = it.get('type')
        if t == 'instruction':
            if not isinstance(it.get('text', ''), str): fail(f'{w}: 안내문 text는 글이어야 합니다')
            if cur is not None and not cur['qs'] and not cur['passage']: cur['head'] = (cur['head'] + ' ' + it.get('text', '')).strip(); continue
            cur = new_set(sets, it.get('text', '')); continue
        if t not in ('passage', 'question'): continue
        if cur is None or t == 'passage' and cur['qs']: cur = new_set(sets)
        if t == 'passage':
            if not strs(it.get('paras')): fail(f'{w}: 지문 paras는 글 목록이어야 합니다')
            if not isinstance(it.get('source', ''), str): fail(f'{w}: 지문 source는 글이어야 합니다')
            cur['passage'] += it['paras'] + ([f"- {it['source']}"] if it.get('source') else []); continue
        ch, a, sc, bogi, note = it.get('choices'), it.get('answer'), it.get('score'), it.get('bogi'), it.get('note')
        if not isinstance(it.get('stem'), str): fail(f'{w}: 발문 stem이 글이어야 합니다')
        if not strs(ch) or len(ch) < 2: fail(f'{w}: choices는 선택지 글 목록이어야 합니다')
        if a is not None and not (is_int(a) and 1 <= a <= len(ch)): fail(f'{w}: answer는 1~{len(ch)} 숫자여야 합니다')
        if sc is not None and (isinstance(sc, bool) or not isinstance(sc, (int, float))): fail(f'{w}: score는 숫자여야 합니다')
        if bogi is not None and not (isinstance(bogi, dict) and strs(bogi.get('lines', [])) and isinstance(bogi.get('source', ''), str)): fail(f'{w}: bogi는 {{"lines": [글…]}} 꼴이어야 합니다')
        if note is not None and not (isinstance(note, dict) and all(isinstance(note.get(k, ''), str) for k in ('point', 'why')) and strs(note.get('wrong', []))):
            fail(f'{w}: note는 {{"point": 글, "why": 글, "wrong": [글…]}} 꼴이어야 합니다')
        note = note or {}; wrong = note.get('wrong', [])
        lines = ([f"출제 포인트: {note['point']}"] if note.get('point') else []) + ([f"정답 해설: {note['why']}"] if note.get('why') else []) + (['오답 분석'] + wrong if wrong else [])
        bl = (bogi or {}).get('lines', []) + ([f"- {bogi['source']}"] if bogi and bogi.get('source') else [])
        cur['qs'].append({'stem': it['stem'], 'score': sc, 'bogi': bl, 'choices': ch, 'answer': a, 'note': lines,
                          'wrong_nums': [k for k in range(1, len(ch) + 1) if k != a][:len(wrong)] if a else []})
    return sets


def note_answer(note):
    """미주에서 정답 번호: '정답 ③', '정답: 3', 또는 '정답'이 든 줄 바로 다음의 '③'·'3' 한 글자."""
    for i, n in enumerate(note):
        m = re.search(r'정답\s*[:：]?\s*([①②③④⑤1-5])(?![\d.])', n)
        if not m and '정답' in n and i + 1 < len(note): m = re.fullmatch(r'\s*([①②③④⑤1-5])\s*', note[i + 1])
        if not m and i == 0: m = re.fullmatch(r'\s*([①②③④⑤])\s*', n)
        if m: c = m.group(1); return CIRC.index(c) + 1 if c in CIRC else int(c)
    return None


def from_text(text):
    """extract_hwpx_text.py 출력을 세트·문항으로 나눈다. 미주 줄은 바로 앞 문항의 것이다(추출기가 다음 발문 직전에 내보낸다).
    '정답과 해설' 제목 뒤의 글은 문항이 아니므로 버린다(미주만 읽는다). 선택지가 시작된 뒤의 글은 다음 지문이다."""
    sets = []; cur = None; q = None; last = None; answer_area = False
    for raw in text.splitlines():
        line = nfc(raw).strip()
        m = NOTE.match(line)
        if m:
            if last is not None: last['note'].append(m.group(1).strip())
            continue
        if not line:  # 지문 안의 빈 줄(시의 연 구분)만 살린다
            if not answer_area and cur is not None and q is None and cur['passage'] and cur['passage'][-1] != '': cur['passage'].append('')
            continue
        if line.startswith(('※ 읽을 수', '※ 도형', '※ 수식')): continue
        if ANSWER_AREA.fullmatch(plain(line)): answer_area = True; q = None; continue
        if answer_area: continue  # 정답과 해설 쪽의 글(번호 문단 해설 등)은 묶음에 넣지 않는다
        m = re.match(r'\[발문 \d+\]\s*(.*)', line)
        if m:
            if cur is None: cur = new_set(sets)
            stem = m.group(1); sc = SCORE.search(stem)
            q = {'stem': SCORE.sub('', stem).strip(), 'score': float(sc.group(1)) if sc else None, 'bogi': [], 'choices': [], 'answer': None, 'note': [], 'wrong_nums': []}
            cur['qs'].append(q); last = q; continue
        m = re.match(r'\[선택지\]\s*[①②③④⑤]\s*(.*)', line)
        if m and q is not None: q['choices'].append(m.group(1).strip()); continue
        m = re.match(r'\[표 \d+\(\d+×\d+\) \d+,\d+\]\s*(.*)', line)
        body = m.group(1) if m else line
        if q is not None and not q['choices']:  # 발문과 선택지 사이의 글(표·단서) = 〈보기〉
            if not re.fullmatch(r'[〈<]\s*보\s*기\s*[〉>]', plain(body)): q['bogi'].append(body)
            continue
        if line.startswith('※'): cur = new_set(sets, line); q = None; continue
        if q is not None: cur = new_set(sets); q = None  # 선택지 뒤에 온 글 = 다음 지문
        if cur is not None: cur['passage'].append(body)  # 첫 안내문 앞의 글(제목)은 버린다
    for s in sets:
        demoted = [x for x in s['qs'] if not x['choices']]  # 선택지가 없는 번호 문단은 문항이 아니다(학습 메모 등) → 지문으로
        s['passage'] += [t for x in demoted for t in [x['stem']] + x['bogi']]
        s['qs'] = [x for x in s['qs'] if x['choices']]
        for x in s['qs']:
            x['answer'] = note_answer(x['note'])
            if '오답 분석' in x['note']:
                x['wrong_nums'] = [CIRC.index(n[0]) + 1 for n in x['note'][x['note'].index('오답 분석') + 1:] if n[:1] in CIRC]
    return sets


def load(path):
    p = Path(path); suf = p.suffix.lower()
    if not p.is_file(): fail(f'{path} 파일이 없습니다')
    if suf == '.hwp': fail('구형 .hwp는 읽지 못합니다. 한글에서 .hwpx로 다시 저장하거나 문항을 시험 내용 JSON으로 옮기세요')
    if suf == '.hwpx':
        spec = importlib.util.spec_from_file_location('extract_hwpx_text', Path(__file__).resolve().parent / 'extract_hwpx_text.py')
        ex = importlib.util.module_from_spec(spec); spec.loader.exec_module(ex); buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf): ex.main(str(p), keep_empty=True)
        except SystemExit as e: fail(str(e).removeprefix('오류: '))
        except Exception as e: fail(f'한글 파일을 읽지 못했습니다({type(e).__name__}). 문항을 시험 내용 JSON으로 옮긴 뒤 다시 돌리세요')
        return from_text(buf.getvalue())
    if suf not in ('.json', '.txt', '.md'): fail('입력은 시험 내용 JSON(.json), 한글 시험지(.hwpx), 추출 글(.txt)이어야 합니다')
    try: text = p.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError: fail(f'{path}은(는) UTF-8 글 파일이 아닙니다. UTF-8로 다시 저장하세요')
    if suf != '.json': return from_text(text)
    try: data = json.loads(text)
    except (ValueError, RecursionError) as e: fail(f'{path}을(를) JSON으로 읽지 못했습니다 ({str(e)[:80]})')
    return from_json(data)


def render(s, start):
    para = list(s['passage'])
    while para and para[-1] == '': para.pop()
    out = ([s['head']] if s['head'] else []) + (['[지문]'] + para if para else [])
    for k, q in enumerate(s['qs'], start):
        out += ['', f"### {k}번" + (f" [{q['score']:g}점]" if q['score'] else ''), q['stem']]
        if q['bogi']: out += ['〈보기〉'] + [f'  {b}' for b in q['bogi']]
        out += [f'{CIRC[i] if i < 5 else "?"} {c}' for i, c in enumerate(q['choices'])]
        if len(q['choices']) != 5: out.append(f"(선택지가 {len(q['choices'])}개로 읽혔다 - 원본 확인 필요, 판정 보류)")
    return '\n'.join(out)


def make(src, outdir, answers=None):
    sets = [s for s in load(src) if s['qs']] or fail('문항을 찾지 못했습니다. 발문에 자동 번호가 없는 한글 파일이면 문항을 시험 내용 JSON(exam-basic 형식)으로 옮긴 뒤 다시 돌리세요')
    pairs = [(i, q) for i, s in enumerate(sets, 1) for q in s['qs']]
    if answers is not None and len(answers) != len(pairs): fail(f'--answers는 {len(pairs)}개여야 합니다(받은 개수 {len(answers)})')
    n = 0; texts = []
    for s in sets: texts.append(render(s, n + 1)); n += len(s['qs'])
    whole = plain('\n'.join(texts))
    leak = [k for k, (_, q) in enumerate(pairs, 1) if any(len(plain(x).strip()) >= 8 and plain(x).strip() in whole for x in q['note'])]
    if leak: fail(f'해설 글이 문항 묶음에 섞였습니다({", ".join(map(str, leak[:10]))}번 해설). 원본의 구성이 추출기와 맞지 않으니 문항을 시험 내용 JSON으로 옮긴 뒤 다시 돌리세요')
    out = Path(outdir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        for f in [*out.glob('세트*.md'), out / '문항.md', out / '정답표.json']:  # 지난번 묶음이 남지 않게
            if f.is_file(): f.unlink()
        for i, txt in enumerate(texts, 1): (out / f'세트{i:02d}.md').write_text(f'# 세트 {i} (정답·해설 없음)\n\n{txt}\n', encoding='utf-8')
        (out / '문항.md').write_text('# 정답을 가린 문항(정답·해설 없음)\n' + ''.join(f'\n## 세트 {i}\n{t}\n' for i, t in enumerate(texts, 1)), encoding='utf-8')
        key = [{'번호': k, '세트': i, '정답': q['answer'], '교사정답': answers[k - 1] if answers else None, '부정발문': negative(q['stem']),
                '배점': q['score'], '선택지수': len(q['choices']), '오답분석번호': q['wrong_nums'], '해설': q['note']} for k, (i, q) in enumerate(pairs, 1)]
        (out / '정답표.json').write_text(json.dumps({'문항': key}, ensure_ascii=False, indent=1), encoding='utf-8')
    except (OSError, UnicodeError) as e: fail(f'작업폴더 {outdir}에 쓰지 못했습니다({type(e).__name__}). 다른 폴더를 고르세요')
    bad = [k for k, (_, q) in enumerate(pairs, 1) if len(q['choices']) != 5]
    print(f'문항 {len(pairs)}개, 세트 {len(sets)}개(세트01.md~세트{len(sets):02d}.md), 정답이 있는 문항 {sum(1 for x in key if x["정답"] or x["교사정답"])}개 -> {out}')
    if bad: print(f'※ 선택지가 5개로 읽히지 않은 문항 {len(bad)}개: {", ".join(map(str, bad[:20]))}{" …" if len(bad) > 20 else ""}번 - 원본을 확인하고 판정 보류로 둔다')
    print('풀이가 끝날 때까지 정답표.json과 원본 파일의 미주·정답과 해설 쪽을 열지 마세요.')


def compare(outdir, results):
    keyf = Path(outdir) / '정답표.json'
    if not keyf.is_file(): fail(f'{keyf}가 없습니다. 먼저 make를 돌리세요')
    try:
        key = {k['번호']: k for k in json.loads(keyf.read_text(encoding='utf-8'))['문항']}
        assert all(is_int(k) for k in key)
    except (ValueError, KeyError, TypeError, AssertionError): fail(f'{keyf}을(를) 읽지 못했습니다(손상). make를 다시 돌리세요')
    solvers = []
    for f in results:
        try: d = json.loads(Path(f).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as e: fail(f'{f}을(를) 읽지 못했습니다 ({str(e)[:80]})')
        rows = d.get('문항') if isinstance(d, dict) else None
        if not isinstance(rows, list): fail(f'{f}: 최상위에 "문항" 목록이 있어야 합니다(guide.py 풀이자의 결과 형식)')
        name = str(d.get('풀이자') or Path(f).stem); got = {}
        for r in rows:
            k = r.get('번호') if isinstance(r, dict) else None
            if not is_int(k) or k not in key: fail(f'{f}: 정답표에 없는 번호 {k!r}')
            if k in got: fail(f'{f}: {k}번이 두 번 있습니다')
            nc = key[k].get('선택지수', 5); j = r.get('선지') or []; a = r.get('답')
            if j and (not isinstance(j, list) or len(j) != nc or any(x not in ('참', '거짓', '애매') for x in j)): fail(f'{f} {k}번: "선지"는 참·거짓·애매 {nc}개여야 합니다')
            if a is not None and not (is_int(a) and 1 <= a <= nc): fail(f'{f} {k}번: "답"은 1~{nc} 숫자이거나 null(정답 없음·판단 못 함)이어야 합니다')
            got[k] = dict(답=a, 선지=j, 확신=r.get('확신', ''))
        solvers.append((name, got))
    order = ['정답 불일치', '복수 정답 소지', '정답 없음 소지', '풀이자끼리 갈림', '애매·확신 낮음', '판정 보류', '해설·정답표 점검', '풀지 않음', '확인']
    counts = dict.fromkeys(order, 0); lines = ['번호  표시정답  풀이  판정']; again = []
    for k, kk in sorted(key.items()):
        mine, teacher, nc = kk.get('정답'), kk.get('교사정답'), kk.get('선택지수', 5); mark = mine or teacher; flags = []
        if nc != 5: flags.append(f'판정 보류(선택지 {nc}개로 읽힘)')
        if mine and teacher and mine != teacher: flags.append(f'해설·정답표 점검(미주 {lab(mine)}와 교사 정답 {lab(teacher)}이 다름)')
        wn = kk.get('오답분석번호') or []
        if mine and wn and sorted(wn) != [x for x in range(1, nc + 1) if x != mine]: flags.append('해설·정답표 점검(오답 분석 번호가 정답을 뺀 번호와 다름)')
        ans, given = [], set()
        for name, got in solvers:
            g = got.get(k)
            if g is None: ans.append(f'{name}-'); continue
            a, j = g['답'], g['선지']
            want = '거짓' if kk.get('부정발문') else '참'; cand = [i + 1 for i, x in enumerate(j) if x == want]
            if j and len(cand) == 1 and a is None: a = cand[0]  # 답을 안 적었으면 선지 판정에서 읽는다
            if j and len(cand) == 1 and a != cand[0]: flags.append(f'애매·확신 낮음({name}: 답 {lab(a)}와 선지 판정 {lab(cand[0])}이 다름)')
            ans.append(f"{name}{lab(a) if a else '(답없음)'}"); given.add(a)
            if mark and a and a != mark: flags.append('정답 불일치')
            if j:
                if len(cand) > 1: flags.append(f"복수 정답 소지({name}: {' '.join(lab(i) for i in cand)})")
                if not cand and '애매' not in j: flags.append(f'정답 없음 소지({name})')
                if '애매' in j: flags.append(f"애매·확신 낮음({name}: {' '.join(lab(i + 1) for i, x in enumerate(j) if x == '애매')} 애매)")
            elif a is None: flags.append(f'정답 없음 소지({name}: 답 없음)')
            if g['확신'] == '낮음': flags.append(f'애매·확신 낮음({name})')
        if len(given) > 1: flags.append('풀이자끼리 갈림')
        if not any(k in got for _, got in solvers): flags.append('풀지 않음')
        flags = list(dict.fromkeys(flags)) or ['확인']
        if flags != ['확인']: again.append(k)
        for o in order:
            if any(x.startswith(o) for x in flags): counts[o] += 1
        lines.append(f"{k:>3}번  {lab(mark) if mark else '(없음)':<6} {' '.join(ans):<10} {' / '.join(flags)}")
    print(f'풀이자 {len(solvers)}명, 문항 {len(key)}개')
    print('요약: ' + ', '.join(f'{o} {c}' for o, c in counts.items() if c))
    print('\n'.join(lines))
    print('다시 볼 문항: ' + (', '.join(f'{k}번' for k in again) if again else '없음'))


def main(argv):
    for s in (sys.stdout, sys.stderr):  # cp949 콘솔(Windows)에서도 찍을 수 없는 글자 때문에 멈추지 않게
        if hasattr(s, 'reconfigure'): s.reconfigure(errors='replace')
    if len(argv) >= 3 and argv[0] == 'make':
        answers = None
        if '--answers' in argv:
            i = argv.index('--answers'); raw = argv[i + 1] if i + 1 < len(argv) else ''; argv = argv[:i] + argv[i + 2:]
            try: answers = [int(x) for x in re.split(r'[,，\s]+', unicodedata.normalize('NFKC', raw).strip()) if x]
            except ValueError: fail('--answers는 1~5 숫자를 쉼표로 이어 적습니다(예: 3,5,1)')
            if not answers or any(not 1 <= a <= 5 for a in answers): fail('--answers는 1~5 숫자를 쉼표로 이어 적습니다(예: 3,5,1)')
        if len(argv) != 3: fail('사용: blind.py make 입력 작업폴더 [--answers 3,5,1,…]')
        make(argv[1], argv[2], answers)
    elif len(argv) >= 3 and argv[0] == 'compare': compare(argv[1], argv[2:])
    else: print(__doc__); sys.exit(0 if argv[:1] in (['-h'], ['--help']) else 1)


if __name__ == '__main__':
    main(sys.argv[1:])
