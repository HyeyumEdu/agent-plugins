"""HWPX 시험지가 references/format-spec.md 의 규칙(G1~G50, V1·V5·V9)을 지키는지 XML 로 검사한다(표준 라이브러리만).
기본은 엄격 모드(새로 만든 시험지용). --lenient 는 한컴이 저장한 원본처럼 작은 예외가 있는 파일용.
출력: 규칙 ID, PASS/FAIL/WARN, 설명, 측정값. 종료 코드: FAIL·열 수 없는 파일이 있으면 1, 사용법 오류 2.
shortcut: 표준 XML 파서라 출처를 모르는 파일은 검사하지 않는다(직접 만든·받은 시험지만), 필요하면 defusedxml 로 바꾼다."""
import importlib.util, json, re, sys, unicodedata, zipfile, zlib
from pathlib import Path
import xml.etree.ElementTree as ET
from collections import Counter

H = '{http://www.hancom.co.kr/hwpml/2011/head}'
P = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
C = '{http://www.hancom.co.kr/hwpml/2011/core}'
USAGE = '사용: python3 verify_exam.py [--lenient] 파일.hwpx [파일2.hwpx ...]'
ln = lambda e: e.tag.rsplit('}', 1)[-1]
ROOT = Path(__file__).resolve().parent.parent


def shape_check(d):  # G50: 기본 형식의 부품으로 본문 모양을 견준다. 반환 (부품에 없는 모양들, 부품을 읽지 못한 이유 또는 None)
    # shortcut: 형식이 둘 이상이면 기본 형식의 부품만 본다 — 두 번째 형식을 더할 때 --format 인수를 넣는다
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('components', Path(__file__).with_name('components.py'))
        cm = importlib.util.module_from_spec(spec); spec.loader.exec_module(cm)
        fs = json.loads((ROOT / 'assets/formats.json').read_text(encoding='utf-8'))
        fmt = next((f for f in fs if f.get('default')), fs[0] if len(fs) == 1 else None)
        if fmt is None: return [], '기본 형식(formats.json 의 default)을 정할 수 없습니다'
        return cm.shape_problems(cm.Registry(ROOT, fmt), d.hd, d.sec), None
    except SystemExit as e: return [], f'부품을 읽지 못했습니다({str(e.code).replace("오류: ", "", 1)})'
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e: return [], f'부품을 읽지 못했습니다({type(e).__name__}: {e})'


def ttext(t):  # hp:t 의 글. <hp:nbSpace/> 같은 자식 요소 뒤의 글(tail)도 읽는다
    return (t.text or '') + ''.join(({'nbSpace': ' ', 'fwSpace': ' ', 'tab': ' ', 'lineBreak': ' '}.get(ln(c), '')) + (c.tail or '') for c in t)


NEG = re.compile(r'않은|않는|아닌|없는')
MARK = '[\u3260-\u327b\u24d0-\u24e9\u24b6-\u24cf]'  # 원문자 표시: ㉠~㉻, ⓐ~ⓩ, Ⓐ~Ⓩ
SENT_END = set('다요죠까군네나니라지야어아여가걸데래게세자해와봐줘돼구')  # 문장 종결로도 쓰이는 끝 글자(명사 끝 글자와 겹침: 독자·필요·분야·미래 …)
SENT_STRONG = set('다군까죠')  # 문장일 때만 쓰이는 끝 글자. 골든·사용자 파일 선택지 3,140개 중 이 둘(다·군)이 마침표 문장의 99% 이상
LABEL = re.compile(r'^\s*(?:[\[\(\{<【〔［（]\s*)?([가-힣 ]{1,15}줄거리)\s*(?:[\]\)\}>】〕］）])?\s*$')  # 줄거리 표시 한 줄 문단
ENUM = r'(?:\([가나다라마바사아자차카타파하]\)|' + MARK + r'|[ㄱ-ㅎ])'
DEF = re.compile('^' + MARK + r':\s')  # 정의형 선택지 `ⓐ: 뜻풀이`는 마침표를 둔다(사용자 수정 파일 16/16)


def sentence_kind(t):
    """선택지 본문 분류: 'yes' 문장(다·군·까·죠) / 'no' 명사구·표시 문자 나열 / 'maybe' 명사와 겹치는 끝 글자(독자·필요…)라 모름(쓴 대로 둔다)."""
    core = re.sub(r'[\s.?!…”’」』)\]]+$', '', t)
    if not core or re.fullmatch(ENUM + r'(?:\s*[-,~∼]\s*' + ENUM + ')*', t.rstrip('. ')): return 'no'  # (가)-(나)-(다), ㄱ, ㄴ, ㉠
    return 'yes' if core[-1] in SENT_STRONG else 'maybe' if core[-1] in SENT_END else 'no'


class Doc:
    def __init__(self, path):
        try:
            z = zipfile.ZipFile(path)
        except FileNotFoundError: raise ValueError('파일이 없습니다')
        except IsADirectoryError: raise ValueError('폴더입니다(.hwpx 파일을 지정하세요)')
        except PermissionError: raise ValueError('파일을 읽을 권한이 없습니다')
        except zipfile.BadZipFile: raise ValueError('hwpx(zip) 파일이 아니거나 손상되었습니다')
        self.names = z.namelist(); self.infos = z.infolist()
        for need in ('Contents/header.xml', 'Contents/section0.xml', 'Contents/content.hpf'):
            if need not in self.names: raise ValueError(f'{need}가 없습니다')
        try:
            self.hd = ET.fromstring(z.read('Contents/header.xml')); self.sec = ET.fromstring(z.read('Contents/section0.xml'))
            self.hpf = z.read('Contents/content.hpf').decode('utf-8'); ET.fromstring(self.hpf.encode())
            self.mime = z.read('mimetype') if 'mimetype' in self.names else b''
        except (ET.ParseError, UnicodeDecodeError) as e: raise ValueError(f'XML이 손상되었습니다({e})')
        except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, OSError) as e: raise ValueError(f'zip 안의 파일을 읽을 수 없습니다(손상·암호·지원하지 않는 압축: {type(e).__name__})')
        self.parent = {c: p for p in self.sec.iter() for c in p}
        self.fonts = {f.get('id'): f.get('face') for ff in self.hd.iter(H + 'fontface') if ff.get('lang') == 'HANGUL' for f in ff}
        self.cp = {c.get('id'): c for c in self.hd.iter(H + 'charPr')}
        self.pp = {p.get('id'): p for p in self.hd.iter(H + 'paraPr')}
        self.num = {n.get('id'): n for n in self.hd.iter(H + 'numbering')}
        self.body = [p for p in self.sec if ln(p) == 'p']
        self.sp = next(self.sec.iter(P + 'secPr'), None)
        if self.sp is None: raise ValueError('첫 문단의 쪽 설정(secPr)이 없습니다')

    def anc(self, e):
        while e in self.parent:
            e = self.parent[e]; yield e

    def inside(self, e, name): return any(ln(a) == name for a in self.anc(e))

    def size(self, cid): return int(self.cp[cid].get('height')) / 100
    def bold(self, cid): return self.cp[cid].find(H + 'bold') is not None
    def italic(self, cid): return self.cp[cid].find(H + 'italic') is not None
    def under(self, cid):
        u = self.cp[cid].find(H + 'underline'); return u is not None and u.get('type') != 'NONE'
    def font(self, cid): return self.fonts[self.cp[cid].find(H + 'fontRef').get('hangul')]

    def para(self, pid):
        p = self.pp[pid]; m = p.find('.//' + H + 'margin')
        g = lambda t: int(m.find(C + t).get('value')) if m is not None and m.find(C + t) is not None else 0
        hg = p.find(H + 'heading'); bs = p.find(H + 'breakSetting'); ls = p.find('.//' + H + 'lineSpacing')
        return dict(al=p.find(H + 'align').get('horizontal'), ls=int(ls.get('value')) if ls is not None else 0,
                    L=g('left'), R=g('right'), F=g('intent'), B=g('prev'), A=g('next'),
                    head=(hg.get('type'), hg.get('idRef')) if hg is not None else ('NONE', '0'),
                    brk=bs.get('breakNonLatinWord'))

    def stems(self):
        return [i for i, p in enumerate(self.body) if self.para(p.get('paraPrIDRef'))['head'][0] == 'NUMBER']

    def runs(self, p):
        return [(''.join(ttext(t) for t in r.findall(P + 't')), r.get('charPrIDRef')) for r in p.findall(P + 'run')]

    def txt(self, p): return ''.join(t for t, _ in self.runs(p))

    def choices_after(self, k, stems):
        end = stems[k + 1] if k + 1 < len(stems) else len(self.body)
        return [q for q in self.body[stems[k] + 1:end] if re.match(r'^\s*[①②③④⑤]', self.txt(q))]


def ptok(p_):  # 문단의 글 조각(run 이 갈려도 같은 순서): 글은 그대로, 탭은 '\t', 그 밖의 개체는 '\0이름'
    out = []
    for t in p_.iter(P + 't'):
        if t.text: out.append(t.text)
        for c in t:
            out.append('\t' if ln(c) == 'tab' else '\0' + ln(c))
            if c.tail: out.append(c.tail)
    return out


def rules(d, lenient=False):
    """[(id, 설명, 통과여부(True/False/None=경고), 측정값)]"""
    R = []; add = lambda i, s, ok, v='': R.append((i, s, ok if ok is None else bool(ok), v))
    empty_p = lambda q: not d.txt(q).strip() and not any(True for _ in q.iter(P + 'tbl')) and not any(True for _ in q.iter(P + 'ctrl'))
    kwset = lambda p_: d.pp[p_.get('paraPrIDRef')].find(H + 'breakSetting')

    def boxed(p_):  # 문단 테두리 지문(connect=1)의 문단
        bd = d.pp[p_.get('paraPrIDRef')].find(H + 'border')
        return bd is not None and bd.get('connect') == '1' and bd.get('borderFillIDRef') not in ('', None, '2')

    refs = {'paraPrIDRef': set(d.pp), 'charPrIDRef': set(d.cp), 'styleIDRef': {x.get('id') for x in d.hd.iter(H + 'style')}, 'borderFillIDRef': {x.get('id') for x in d.hd.iter(H + 'borderFill')}}
    dang = sorted({f'{a}={e.get(a)}' for e in d.sec.iter() for a, ok in refs.items() if e.get(a) not in (None, '4294967295') and e.get(a) not in ok})
    add('G34', '본문이 쓰는 문단·글자·스타일·테두리 모양 번호가 모두 헤더에 있음', not dang, dang[:4])
    if dang: return R + [('G1+', '헤더에 없는 모양 번호가 있어 나머지 규칙을 검사할 수 없음', False, '')]
    pg = d.sp.find(P + 'pagePr'); mg = pg.find(P + 'margin') if pg.find(P + 'margin') is not None else pg.find(P + 'pageMar')
    cl = next(d.sec.iter(P + 'colPr'), None); cline = cl.find(P + 'colLine') if cl is not None else None
    en = d.sp.find(P + 'endNotePr')
    w, h = int(pg.get('width')), int(pg.get('height'))
    add('G1', 'A4 세로(59528x84186)', (w, h) == (59528, 84186), f'{w}x{h} {pg.get("landscape")}')
    m = {k: int(mg.get(k)) for k in ('left', 'right', 'top', 'bottom', 'header', 'footer', 'gutter')}
    add('G2', '여백 L=R=8504 T≈5669 B=H=F=4252 gutter0',
        m['left'] == m['right'] == 8504 and abs(m['top'] - 5669) <= 1 and m['bottom'] == m['header'] == m['footer'] == 4252 and m['gutter'] == 0, m)
    add('G3', '2단 NEWSPAPER 간격2268 구분선 SOLID 0.12mm #000000',
        cl is not None and cline is not None and cl.get('colCount') == '2' and cl.get('type') == 'NEWSPAPER' and cl.get('sameGap') == '2268'
        and (cline.get('type'), cline.get('width'), cline.get('color')) == ('SOLID', '0.12 mm', '#000000'),
        (cl.get('colCount'), cl.get('type'), cl.get('sameGap'), cline.get('width')) if cl is not None else 'colPr 없음')
    af = en.find(P + 'autoNumFormat'); nl = en.find(P + 'noteLine'); ns = en.find(P + 'noteSpacing')
    add('G4', '미주: DIGIT ")" CONTINUOUS END_OF_DOCUMENT, 선 14692344 0.12mm, 간격 0/567/850',
        af.get('type') == 'DIGIT' and af.get('suffixChar') == ')' and en.find(P + 'numbering').get('type') == 'CONTINUOUS'
        and en.find(P + 'placement').get('place') == 'END_OF_DOCUMENT' and nl.get('length') == '14692344' and nl.get('width') == '0.12 mm'
        and (ns.get('betweenNotes'), ns.get('belowLine'), ns.get('aboveLine')) == ('0', '567', '850'),
        (en.find(P + 'placement').get('place'), nl.get('length')))
    hf = sum(len(list(d.sec.iter(P + t))) for t in ('header', 'footer', 'pageNum'))
    add('G5', '머리말·꼬리말·쪽번호 없음', hf == 0, hf)
    lastp = next((p for p in reversed(d.body) if d.txt(p).strip()), None)
    endh = lastp is not None and d.txt(lastp).strip() == '정답과 해설'  # 이 제목 문단의 쪽 나눔(G35)은 지침이라 G6 에서 세지 않는다
    ins = [k for k, p_ in enumerate(d.body) if d.para(p_.get('paraPrIDRef'))['head'][0] == 'NONE' and re.search(r'물음에 답하시오\.?$', d.txt(p_).strip()) and len(d.txt(p_)) < 140
           and all(d.bold(c) for t, c in d.runs(p_) if t.strip())]  # 안내문: 굵은 글자의 '…물음에 답하시오.' 한 문단(번호 문단·표 안 문단 제외)
    insp = {id(d.body[k]) for k in ins}  # 안내문 문단의 단·쪽 나눔(G41)도 지침이라 G6 에서 세지 않는다
    cb = sum(1 for p in d.sec.iter(P + 'p') if p.get('columnBreak', '0') != '0' and id(p) not in insp); pb = sum(1 for p in d.sec.iter(P + 'p') if p.get('pageBreak', '0') != '0' and not (endh and p is lastp) and id(p) not in insp)
    add('G6', '강제 쪽/단 나눔 없음(골든은 빈 문단으로 흐름 조절; 나눔을 쓰면 지침 이탈이라 경고)', True if cb + pb == 0 else None, f'단 나눔 {cb}개, 쪽 나눔 {pb}개')

    # 글꼴·색
    fc = Counter()
    for p in d.sec.iter(P + 'p'):
        if d.inside(p, 'endNote'): continue
        for t, c in d.runs(p):
            if t.strip(): fc[(d.font(c), d.cp[c].get('textColor'))] += len(t)
    n = sum(fc.values()); hb = sum(v for (f, _), v in fc.items() if f == '함초롬바탕')
    add('G7', '본문 글자 95% 이상 함초롬바탕', n and hb / n >= .95, f'{hb / max(n, 1):.1%}')
    add('G8', '글자색 검정(#000000) 100%', all(c == '#000000' for (_, c) in fc), sorted({c for (_, c) in fc}))

    # 문항
    st = d.stems(); ps = [d.para(d.body[i].get('paraPrIDRef')) for i in st]
    add('G9', '문제 번호는 자동 번호(NUMBER), 모든 문항이 같은 번호 정의', len(st) > 0 and len({p['head'] for p in ps}) == 1, (len(st), {p['head'] for p in ps}))
    if not st:
        return R + [('G10+', '발문(NUMBER 문단)이 없어 이하 문항 규칙을 검사할 수 없음', False, '')]
    ph = d.num[ps[0]['head'][1]].find(H + 'paraHead'); ncp = ph.get('charPrIDRef')
    add('G10', '번호 서식 "^1." DIGIT, 굵게+기울임, 12~13pt',
        ph.get('numFormat') == 'DIGIT' and (ph.text or '').strip() == '^1.' and d.bold(ncp) and d.italic(ncp) and d.size(ncp) in (12.0, 13.0),
        (ph.text, d.size(ncp), d.font(ncp)))
    add('G11', '발문 글자 전부 굵게', all(d.bold(c) for i in st for t, c in d.runs(d.body[i]) if t.strip()))
    add('G12', '발문마다 미주 정확히 1개', all(len(list(d.body[i].iter(P + 'endNote'))) == 1 for i in st), len(st))
    chq = [d.choices_after(k, st) for k in range(len(st))]  # 문항별 선택지 문단
    chl = [c for cs in chq for c in cs]; chs = {id(c) for c in chl}
    bad = [k + 1 for k, cs in enumerate(chq) if ''.join(d.txt(c)[:1] for c in cs) != '①②③④⑤']
    add('G13', '선택지 ①②③④⑤ 5개', not bad, bad)
    cps = [d.para(c.get('paraPrIDRef')) for c in chl]
    add('G14', '선택지 문단: 내어쓰기(첫줄<0, 왼쪽>0) JUSTIFY KEEP_WORD', cps and all(p['F'] < 0 < p['L'] and p['al'] == 'JUSTIFY' and p['brk'] == 'KEEP_WORD' for p in cps),
        f'{len(cps)}개 L{sorted({p["L"] for p in cps})[:4]} F{min(p["F"] for p in cps)}~{max(p["F"] for p in cps)}' if cps else '')
    miss = []
    for k, i in enumerate(st):
        runs = d.runs(d.body[i]); t_all = ''.join(t for t, _ in runs)
        mask = [d.under(c) and d.bold(c) for t, c in runs for _ in t]
        if any(not all(mask[m_.start():m_.end()]) for m_ in NEG.finditer(t_all)): miss.append(k + 1)
    add('G15', '부정 발문(않은/않는/아닌/없는)은 나오는 곳마다 굵게+밑줄', not miss, miss)
    add('G16', '발문 문단: JUSTIFY KEEP_WORD', all(p['al'] == 'JUSTIFY' and p['brk'] == 'KEEP_WORD' for p in ps), sorted({(p['ls'], p['B'], p['A']) for p in ps}))
    top = [t for t in d.sec.iter(P + 'tbl') if not d.inside(t, 'tbl')]
    boxes = [t for t in top if (t.get('rowCnt'), t.get('colCnt')) in (('1', '1'), ('3', '3'))]
    add('G17', '문서 최상위 표는 모두 상자(1x1, 원본의 [A] 구간 표시는 3x3)', len(boxes) == len(top), f'{len(boxes)}/{len(top)}')
    ens_all = list(d.sec.iter(P + 'endNote')); ens_q = [next(d.body[i].iter(P + 'endNote'), None) for i in st]
    add('G18', '미주 본문 첫 문단 = 자동번호 + 정답', all(e.find('.//' + P + 'p') is not None and 'autoNum' in ET.tostring(e.find('.//' + P + 'p'), encoding='unicode') and re.search(r'[①-⑤]', ''.join(e.itertext())) for e in ens_all), len(ens_all))
    # ---- 띄어쓰기·자간 ----
    ch_txt = [d.txt(c) for c in chl]
    bad = [t[:12] for t in ch_txt if not re.match(r'^[①-⑤] [^\s①-⑤]', t)]
    add('G19', '선택지 첫머리 = 원문자 + 공백 1칸 + 글자(번호 중복 없음)', not bad, bad[:3])
    body_ = lambda t: t[2:] if re.match(r'^[①-⑤] ', t) else t
    end_bad = [t[-8:] for t in ch_txt if (sentence_kind(body_(t)) == 'yes' or t.endswith(('.', '?'))) and not t.endswith(('.', '?', '!'))]  # 문장인데 마침표가 없거나 끝 공백
    nsp = [t[-8:] for t in ch_txt if (t.endswith('.') and not t.endswith('..') and sentence_kind(body_(t)) == 'no' and not DEF.match(body_(t))) or re.search(r'[!?]\.$', t)]  # 비문장 마침표
    add('G20', '선택지: 문장이면 마침표·물음표로 끝(끝 공백 없음), 문장이 아니면(명사구·뜻풀이) 마침표를 찍지 않는다' + (', 문장 위반 2% 이하(원본 검사는 비문장 마침표를 건너뜀)' if lenient else ''), len(end_bad) <= (max(1, .02 * len(ch_txt)) if lenient else 0) and (lenient or not nsp), (len(end_bad), end_bad[:2], '비문장 마침표', len(nsp), nsp[:2]))
    stem_txt = [d.txt(d.body[i]) for i in st]
    sc = [re.search(r' \[\d+(\.\d+)?점\]$', t) for t in stem_txt]
    core = [re.sub(r' \[\d+(\.\d+)?점\]$', '', t) for t in stem_txt]
    add('G21', '발문은 ?로 끝나고 배점은 ` [n.n점]`(앞 공백 1칸)로 그 뒤에 온다(전부 있거나 전부 없음)', all(c.endswith('?') for c in core) and len({bool(x) for x in sc}) == 1, f'배점 {sum(bool(x) for x in sc)}/{len(sc)}')
    dbl = [d.txt(q).lstrip(' ')[:20] for q in d.sec.iter(P + 'p') if not d.inside(q, 'endNote') and re.search(r'[.?!”’)\]] {2,}\S', d.txt(q).lstrip(' '))]
    add('G22', '문장 사이 공백은 1칸' + (f'(문단당 위반 허용 1개 이하)' if lenient else ''), len(dbl) <= (1 if lenient else 0), dbl[:2])
    tot = dflt = 0; tight = []
    sp7 = lambda c: {d.cp[c].find(H + 'spacing').get(a_) for a_ in ('hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user')}
    rat = lambda c: d.cp[c].find(H + 'ratio').get('hangul')
    is_tight = lambda c: rat(c) == '100' and len(sp7(c)) == 1 and -7 <= int(next(iter(sp7(c)))) < 0  # 선택지 자간 줄임(G36)
    for q in d.sec.iter(P + 'p'):
        for t, c in d.runs(q):
            if t.strip():
                tot += len(t)
                if id(q) in chs and is_tight(c): tight.append(int(next(iter(sp7(c))))); dflt += len(t)
                else: dflt += rat(c) == '100' and sp7(c) == {'0'} and len(t)
    add('G23', '글자 장평 100%·자간 0이 ' + ('95% 이상' if lenient else '100%') + '(선택지의 자간 -1~-7%는 예외, G36)', tot and dflt / tot >= (.95 if lenient else 1), f'{dflt / max(tot, 1):.1%}')
    used = {q.get('paraPrIDRef') for q in d.sec.iter(P + 'p')}
    add('G24', '쓰인 모든 문단의 영문·숫자 자동 간격 꺼짐(eAsianEng=eAsianNum=0)', all(d.pp[i].find(H + 'autoSpacing').get('eAsianEng') == d.pp[i].find(H + 'autoSpacing').get('eAsianNum') == '0' for i in used), len(used))
    # ---- 문장 시작 줄 맞춤 ----
    hang = [abs(d.para(c.get('paraPrIDRef'))['F']) / (d.size(d.runs(c)[0][1]) * 100) for c in chl]
    add('G25', '선택지 내어쓰기 폭 = 글자 크기의 1.3~2.0배(원문자+공백 폭; 골든 1.3~1.75, 사용자 수정 파일 1.83)', hang and all(1.3 <= x <= 2.0 for x in hang), f'{min(hang):.2f}~{max(hang):.2f}배' if hang else '')
    add('G26', '발문 문단 left=0·intent=0(둘째 줄은 번호 정의의 자동 맞춤)', all(p['L'] == 0 and p['F'] == 0 for p in ps), sorted({(p['L'], p['F']) for p in ps}))
    # ---- 미주 ----
    ens = []; okpos = True
    for i, e in zip(st, ens_q):
        an = next(e.iter(P + 'autoNum'), None) if e is not None else None
        if e is None or an is None: ens.append(None); continue
        kids = [ln(x) for x in d.body[i].findall(P + 'run')[-1]]
        okpos &= 'ctrl' in kids and 't' in kids and kids.index('ctrl') > kids.index('t')
        ens.append((int(e.get('number')), int(an.get('num')), e.get('suffixChar')))
    add('G27', '미주 번호 = 발문 순번(number·autoNum 일치, 1부터 연속), suffixChar=41, ctrl은 발문 마지막 run의 t 뒤',
        all(x == (k + 1, k + 1, '41') for k, x in enumerate(ens)) and okpos, f'{len(ens)}개')
    # ---- 글 안 문자·서식 표기·중복 id ----
    alltxt = [ttext(t) for t in d.sec.iter(P + 't')]
    badch = Counter(hex(ord(ch)) for t in alltxt for ch in t if (ch.isspace() and ch != ' ') or unicodedata.category(ch) == 'Cf')
    ok_tabs = set()  # 선택지 원문자 바로 뒤의 탭(G49)은 허용한다(run 이 갈려 있어도)
    for p_ in chl:
        tk_, ts_ = ptok(p_), list(p_.iter(P + 'tab'))
        if ts_ and len(tk_) > 1 and re.fullmatch('[①-⑤]', tk_[0]) and tk_[1] == '\t': ok_tabs.add(id(ts_[0]))
    badel = {tag: len([e for e in d.sec.iter(P + tag) if id(e) not in ok_tabs]) for tag in ('tab', 'fwSpace', 'lineBreak')}
    add('G28', '공백은 일반 공백만(탭·NBSP·전각 공백·제로폭 문자·줄바꿈 없음. 용어 풀이 hp:nbSpace 는 허용)', not badch and not any(badel.values()), (dict(badch), {k: v for k, v in badel.items() if v}))
    left = [t[:20] for t in alltxt if '**' in t or '<u>' in t or '</u>' in t]
    add('G29', '굵게·밑줄 표기(**, <u>)가 글에 그대로 남지 않음', not left, left[:2])
    tids = [t.get('id') for t in d.sec.iter(P + 'tbl')]; iids = [e.get('instId') for e in ens_all]
    add('G30', '표 id·미주 instId 중복 없음', len(set(tids)) == len(tids) and len(set(iids)) == len(iids), (len(tids), len(iids)))
    mism = []
    for k, e in enumerate(ens_q):
        if e is None: continue
        s1 = re.search(r'\[(\d+(?:\.\d+)?)점\]$', stem_txt[k])
        s2 = re.search(r'정답\s*[①-⑤]\s+\[(\d+(?:\.\d+)?)점\]', ''.join(e.itertext()))
        if s2 and (not s1 or s2.group(1) != s1.group(1)): mism.append(k + 1)
    add('G31', '발문 끝 배점 = 미주 첫 줄 배점', not mism, mism)
    mt = d.infos[:1]; nofile = [h for h in re.findall(r'href="([^"]+)"', d.hpf) if h not in d.names]
    add('G32', 'zip: mimetype 이 첫 항목·무압축·`application/hwp+zip`이고 content.hpf 가 가리키는 파일이 모두 있음',
        bool(mt) and mt[0].filename == 'mimetype' and mt[0].compress_type == 0 and d.mime.strip() == b'application/hwp+zip' and not nofile, nofile)
    empty = sum(1 for sl in d.sec.iter(P + 'subList') if sl.find(P + 'p') is None)
    add('G33', '모든 표 칸·미주 안에 문단이 1개 이상 있음', empty == 0, empty)
    kinds = Counter()
    for e in ens_q:
        sub = e.find(P + 'subList') if e is not None else None
        ps_ = list(sub.findall(P + 'p')) if sub is not None else []
        if not ps_: kinds['기타'] += 1; continue
        t0 = d.txt(ps_[0])
        if (len(ps_) == 9 and re.match(r'^ 정답 [①-⑤] {3}\[\d+\.\d점\]$', t0) and d.txt(ps_[1]).startswith('출제 포인트  ') and d.txt(ps_[2]).startswith('정답 해설  ')
              and d.txt(ps_[3]) == '오답 분석' and not d.txt(ps_[8]).strip() and all(re.match(r'^[①-⑤] ', d.txt(q)) for q in ps_[4:8])):
            kinds['정답·포인트·해설·오답분석'] += 1
        else: kinds['기타'] += 1
    add('V9', '미주 내용 형식이 모두 "정답·포인트·해설·오답분석"', len(kinds) == 1 and '기타' not in kinds, dict(kinds))
    last = lastp; lr = d.runs(last) if last is not None else []; hok = last is not None and d.txt(last).strip() == '정답과 해설' and all(d.bold(c) for t, c in lr if t.strip())
    if lenient:  # 원본: 제목이 있으면 굵게 13~14pt(골든 14pt), 없어도 된다
        add('G35', '`정답과 해설` 제목이 있으면 본문 맨 끝 문단에 굵게 13~14pt(원본은 없어도 됨)', not any(d.txt(p).strip() == '정답과 해설' for p in d.body) or (hok and all(13.0 <= d.size(c) <= 14.0 for t, c in lr if t.strip())), d.txt(last)[:20] if last is not None else '')
    else:
        add('G35', '본문 맨 끝 문단이 `정답과 해설`: 13pt 굵게, 쪽 맨 위(pageBreak=1) — 미주(정답·해설)가 이 쪽에서 시작', hok and all(d.size(c) == 13.0 for t, c in lr if t.strip()) and last.get('pageBreak') == '1',
            (d.txt(last)[:20], {d.size(c) for t, c in lr if t.strip()}, last.get('pageBreak')) if last is not None else '')
    bad36 = [t[:8] for p_ in chl for t, c in d.runs(p_) if t.strip() and not (rat(c) == '100' and (sp7(c) == {'0'} or is_tight(c)))]
    other = [t[:8] for p_ in d.sec.iter(P + 'p') if id(p_) not in chs for t, c in d.runs(p_) if t.strip() and not (rat(c) == '100' and sp7(c) == {'0'})]
    add('G36', '글자 간격(자간) 조정은 선택지 글자에만, 일곱 속성 모두 같은 -1~-7%, 장평 100%' + ('(원본 검사: 선택지만 본다 — 기준 시험지의 지문 인용 상자는 -5% 예외)' if lenient else ''),
        not bad36 and (lenient or not other), f'선택지 {len(tight)}곳 {sorted(set(tight))}' + (f', 선택지 밖 위반 {len(other)}곳 {other[:2]}' if other and not lenient else '') + (f', 선택지 위반 {bad36[:2]}' if bad36 else ''))
    gbad = []
    for k in ins:  # 안내문 뒤 빈 문단은 모두 3pt·160%, 문단 테두리 지문이 빈 줄 없이 곧바로 오면 위반
        j = k + 1
        while j < len(d.body) and empty_p(d.body[j]):
            q = d.body[j]
            if not (all(d.size(c) == 3.0 for _, c in d.runs(q)) and d.para(q.get('paraPrIDRef'))['ls'] == 160): gbad.append(k + 1)
            j += 1
        if j == k + 1 and j < len(d.body) and boxed(d.body[j]): gbad.append(k + 1)
    add('G37', '안내문(…물음에 답하시오.) 뒤 빈 줄은 글자 3pt·줄간격 160%, 문단 테두리 지문 앞에는 반드시 있음', not gbad, sorted(set(gbad))[:4])
    cnt = {}
    for tag_, lst in (('charPr', 'charProperties'), ('paraPr', 'paraProperties'), ('tabPr', 'tabProperties')):
        box = next(d.hd.iter(H + lst), None); kids = [e for e in box if ln(e) == tag_] if box is not None else []
        ids_ = [e.get('id') for e in kids]; cnt[tag_] = (box.get('itemCnt') if box is not None else None, len(kids))
        if box is None or int(box.get('itemCnt')) != len(kids) or len(set(ids_)) != len(ids_) or ids_ != [str(i) for i in range(len(ids_))]: cnt[tag_] += ('불일치',)
    tabids = {t_.get('id') for t_ in d.hd.iter(H + 'tabPr')}; badtab = [p_.get('id') for p_ in d.hd.iter(H + 'paraPr') if p_.get('tabPrIDRef') not in tabids]
    add('G38', '헤더의 글자·문단 모양·탭 정의 목록: itemCnt = 실제 개수, id 0부터 연속·중복 없음, 문단 모양의 tabPrIDRef 가 존재', not any(len(v) > 2 for v in cnt.values()) and not badtab, (cnt, 'tabPrIDRef 끊김', badtab[:3]))
    notchar = [t.get('rowCnt') + 'x' + t.get('colCnt') for t in d.sec.iter(P + 'tbl') if (t.find(P + 'pos') is None or t.find(P + 'pos').get('treatAsChar') != '1')]
    add('G39', '모든 표(중첩 표 포함)는 "글자처럼 취급"(treatAsChar=1)' + ('(원본 검사: 기준 시험지의 표 지문·일부 보기 표는 예외라 개수만 알린다)' if lenient else ''), lenient or not notchar, f'글자처럼 취급 아님 {len(notchar)}개 {sorted(set(notchar))}')
    # ---- 문항 보호·안내문·선택지 정렬·지문 글 규칙(G40~G49) ----
    bad40 = []
    for k, i in enumerate(st):
        ch_ = chq[k]
        if len(ch_) != 5: continue
        blk = d.body[i: d.body.index(ch_[-1]) + 1]
        for n_, p_ in enumerate(blk):
            bs = kwset(p_); want = '0' if n_ == len(blk) - 1 else '1'
            if bs is None or bs.get('keepWithNext') != want or bs.get('pageBreakBefore', '0') != '0' or (d.txt(p_).strip() and bs.get('keepLines') != '1') or (n_ and (p_.get('pageBreak', '0') != '0' or p_.get('columnBreak', '0') != '0')):  # 발문의 나눔은 문항을 새 단에서 시작할 뿐이라 허용
                bad40.append(k + 1); break
    add('G40', '문항(발문~⑤)은 단·쪽 경계에서 끊기지 않게 묶임: 마지막(⑤)을 뺀 문단 keepWithNext=1, 글 문단 keepLines=1, 문항 안 나눔·pageBreakBefore 없음' + ('(원본 검사: 골든은 빈 문단으로 맞추므로 건너뜀)' if lenient else ''), lenient or not bad40, f'위반 문항 {bad40[:5]}')
    bad41 = []; nob = []
    for n_, k in enumerate(ins):
        p_ = d.body[k]; bs = kwset(p_)
        if bs is None or bs.get('keepWithNext') != '1': bad41.append(k + 1)
        if n_ > 0 and p_.get('columnBreak', '0') == '0' and p_.get('pageBreak', '0') == '0': nob.append(k + 1)
        j = k + 1
        while j < len(d.body) and empty_p(d.body[j]):
            bs2 = kwset(d.body[j])
            if bs2 is None or bs2.get('keepWithNext') != '1': bad41.append(j + 1)
            j += 1
    add('G41', '안내문(과 뒤 빈 줄)은 다음 문단과 함께(keepWithNext=1), 첫 묶음 말고는 지문 묶음이 새 단·쪽 맨 위에서 시작(나눔 속성)' + ('(원본 검사는 건너뜀)' if lenient else ''), True if lenient else (False if bad41 else (None if nob else True)),
        f'keepWithNext 위반 {sorted(set(bad41))[:4]}, 나눔 없는 안내문 {nob[:4]}')
    bad42 = [k + 1 for k in ins if not re.match(r'^※ (?![\[［※])\S.*물음에 답하시오\.$', d.txt(d.body[k]).strip())]
    add('G42', '안내문은 `※ 다음 글을 읽고 물음에 답하시오.` 꼴(문제 번호 범위 `[1~3]` 금지)' + ('(원본 검사: 기준 시험지에는 `[1~3]`이 있어 건너뜀)' if lenient else ''), lenient or not bad42, f'위반 안내문 {bad42[:4]}')
    all_p = [d.txt(p_) for p_ in d.sec.iter(P + 'p')]
    bad43 = [t[:12] for t in all_p if re.search(MARK + r'\s+[:：]|' + MARK + '：', t)]
    warn43 = [t[:12] for t in all_p if re.search(MARK + r':(?=\S)', t)]
    add('G43', '원문자 표시 문자(㉠ⓐ㉮…) 뒤의 `:` 는 공백 없이 바로 붙고, `:` 뒤는 한 칸', False if bad43 else (None if warn43 else True), f'공백이 낀 곳 {bad43[:3]}, `:` 뒤 공백 없음 {warn43[:3]}')
    seqs, run = [], []  # 지문: 문단 테두리로 이어지는 최상위 문단 묶음 + 〈보기〉가 아닌 1×1 표의 칸 문단
    for p_ in d.body:
        if boxed(p_): run.append(p_)
        elif run: seqs.append(run); run = []
    if run: seqs.append(run)
    for p_ in d.body:
        for t_ in p_.findall('.//' + P + 'tbl'):
            if d.inside(t_, 'tbl'): continue
            f_ = t_.find('.//' + P + 'p'); first = d.txt(f_).strip() if f_ is not None else ''
            if first.startswith(('〈 보 기 〉', '<보기>')) or (t_.get('rowCnt'), t_.get('colCnt')) == ('3', '3'): continue
            sl = t_.find('.//' + P + 'subList')
            if sl is not None: seqs.append(list(sl.findall(P + 'p')))
    bad44 = []; bad45 = []; bad46 = []; bad47 = []
    for sq in seqs:
        for n_, p_ in enumerate(sq):
            cs = [(ch, d.under(c), d.bold(c)) for t, c in d.runs(p_) for ch in t]; tx_ = ''.join(c_[0] for c_ in cs); t_ = tx_.strip()
            for i_, (ch, u, b_) in enumerate(cs):
                if re.fullmatch(MARK, ch):
                    j_ = i_ + 1
                    if j_ < len(cs) and cs[j_][0] in '“‘"\'': j_ += 1
                    if u or j_ >= len(cs) or not cs[j_][1]: bad44.append(tx_[max(0, i_ - 2): i_ + 6])
            m_ = re.match(r'^(\s*)(\([가나다라마바사아자차카타파하]\))', tx_)
            if m_ and not all(c_[2] for c_ in cs[m_.start(2): m_.end(2)]): bad45.append(tx_[:10])
            islabel = bool(LABEL.match(t_)) and len(t_) <= 30 and not t_.endswith(('.', '?', '!'))
            if n_ and (re.match(r'^\([나다라마바사아자차카타파하]\)', t_) or islabel):
                prev = d.txt(sq[n_ - 1]).strip(); prev2 = d.txt(sq[n_ - 2]).strip() if n_ >= 2 else ''
                if prev or not prev2: bad46.append(t_[:10])
            if islabel:
                rs = [c for t, c in d.runs(p_) if t.strip()]
                nxt = next((q for q in sq[n_ + 1: n_ + 2] if d.txt(q).strip()), None)
                if not (re.fullmatch(r'\[[^\[\]]*줄거리\]', t_) and all(d.size(c) == 9.0 for c in rs)) or (nxt is not None and not all(d.size(c) == 9.0 for t, c in d.runs(nxt) if t.strip())): bad47.append(t_[:12])
            mi_ = re.search(r'\[[^\[\]]*줄거리\]|줄거리\s*\|', tx_)  # 같은 문단 안 `[…줄거리] 요약`: 대괄호, 그 뒤는 모두 9pt
            if mi_ and not islabel:
                if '|' in mi_.group(): bad47.append(tx_[:12])
                elif any(d.size(c) != 9.0 for t, c in d.runs(p_) if t.strip() and t in tx_[mi_.start():] and tx_.find(t) >= mi_.start()): bad47.append(tx_[:12])
    note_ = '(원본 검사: 골든에 없는 새 규칙이라 건너뜀)'
    add('G44', '지문의 원문자 표시 문자 뒤에는 밑줄 범위가 있고 표시 문자 자체는 밑줄 밖' + (note_ if lenient else ''), lenient or not bad44, f'위반 {bad44[:3]}')
    add('G45', '지문 문단 첫머리의 구분 표시 (가)(나)…는 굵게' + (note_ if lenient else ''), lenient or not bad45, f'위반 {bad45[:3]}')
    add('G46', '지문의 구분 문단((나)~, 줄거리 표시) 앞에는 빈 줄 정확히 1개' + (note_ if lenient else ''), lenient or not bad46, f'위반 {bad46[:3]}')
    add('G47', '지문의 `…줄거리` 표시는 `[…줄거리]` 대괄호, 9pt(요약 문단도 9pt)' + (note_ if lenient else ''), lenient or not bad47, f'위반 {bad47[:3]}')
    tabs_ = {t_.get('id'): t_ for t_ in d.hd.iter(H + 'tabPr')}; bad49 = []
    for p_ in chl:
        ts = list(p_.iter(P + 'tab')); tk = ptok(p_); pr = d.para(p_.get('paraPrIDRef'))
        tp = tabs_.get(d.pp[p_.get('paraPrIDRef')].get('tabPrIDRef')); it_ = tp.find('.//' + H + 'tabItem') if tp is not None else None
        ok_ = (len(ts) == 1 and len(tk) > 1 and re.fullmatch('[①-⑤]', tk[0]) and tk[1] == '\t'
               and it_ is not None and int(it_.get('pos')) == pr['L'] + abs(pr['F']) and pr['F'] < 0)
        if not ok_: bad49.append(d.txt(p_)[:8])
    add('G49', '선택지: 원문자 바로 뒤에 탭 1개, 탭 정지 = left+|intent| (첫 줄 본문 시작 = 둘째 줄 시작, 번호 뒤 간격이 선택지마다 같음)' + ('(원본 검사: 골든은 공백이라 건너뜀)' if lenient else ''), lenient or not bad49, f'위반 {len(bad49)}개 {bad49[:3]}')
    p50, e50 = ([], None) if lenient else shape_check(d)  # 부품 밖 모양은 에이전트가 도구로 덧붙인 서식이라 막지 않고 알린다(WARN). 부품을 못 읽으면 설치 문제라 FAIL
    add('G50', '본문 문단·글자·표 테두리 모양이 모두 등록된 부품의 모양과 같음(다르면 등록되지 않은 서식이 들어간 것)' + ('(원본 검사는 건너뜀)' if lenient else ''), False if e50 else (None if p50 else True), [e50] if e50 else p50[:3])
    sizes = Counter(d.size(c) for p in d.body for t, c in d.runs(p) if t.strip() and not d.inside(p, 'endNote'))
    add('V1', '본문 글자 크기(보고용)', True, dict(sizes.most_common(3)))
    add('V5', '선택지 줄간격(보고용)', True, sorted({p['ls'] for p in cps}))
    return R


def main(argv):
    lenient = '--lenient' in argv; files = [a for a in argv if a != '--lenient']
    if not files or any(a in ('-h', '--help') for a in argv): print(USAGE); return 2
    bad = 0
    for path in files:
        print('###', path)
        try:
            d = Doc(path)
        except ValueError as e: print(f'  열 수 없는 파일: {e}'); bad += 1; continue
        try:
            res = rules(d, lenient)
        except (KeyError, AttributeError, IndexError, StopIteration, TypeError, ValueError, ZeroDivisionError) as e:
            print(f'  FAIL  검사 중 구조 오류({type(e).__name__}: {e}) — 헤더 참조나 필수 요소가 빠진 파일일 수 있습니다'); bad += 1; continue
        for i, s, ok, v in res:
            print(f'  {i:4} {"PASS" if ok else ("WARN" if ok is None else "FAIL")}  {s}  <- {v}')
            bad += ok is False
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
