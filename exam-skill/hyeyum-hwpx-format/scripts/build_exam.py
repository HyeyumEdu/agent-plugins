"""시험 내용 JSON -> HWPX 시험지(형식은 assets/formats.json). 서식 규칙은 references/format-spec.md.
템플릿·조각은 이 파일 기준 ../assets 에서 읽으므로 어느 폴더에서 실행해도 된다(표준 라이브러리만).
shortcut: 표준 XML 파서는 우리가 만든 XML만 읽는다(외부 파일 입력 없음)."""
import datetime, html, importlib.util, json, math, re, sys, unicodedata, zipfile
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET


def load_verify():  # python3 -I 는 스크립트 폴더를 sys.path 에 넣지 않으므로 경로로 불러온다(detect_format.py 와 같은 방식)
    sys.dont_write_bytecode = True  # 스킬 폴더에 __pycache__ 를 남기지 않는다
    spec = importlib.util.spec_from_file_location('verify_exam', Path(__file__).with_name('verify_exam.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


V = load_verify()  # 선택지 끝·원문자·줄거리 판정은 검사기와 같은 정의를 쓴다
NEG, MARK, LABEL, DEF, sentence_kind = V.NEG, V.MARK, V.LABEL, V.DEF, V.sentence_kind

ROOT = Path(__file__).resolve().parent.parent
USAGE = '사용: python3 build_exam.py 내용.json 출력.hwpx      (JSON 형식: references/exam-json.md, 예시: assets/examples/)'
CIRC = '①②③④⑤'
GA = '[가나다라마바사아자차카타파하]'  # 구분 표시 (가)~(하)
NA = '[나다라마바사아자차카타파하]'  # 첫 구분이 아닌 (나)~(하)
INLINE = re.compile(r'^(\s*\(' + GA + r'\))?\s*(?:\[\s*([가-힣 ]{1,15}줄거리)\s*\]|([가-힣 ]{1,15}줄거리)\s*\|)\s*(\S.*)$', re.S)  # `(가) [앞부분 줄거리] 요약…` · `앞부분 줄거리 | 요약…`
CTRL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffe\uffff\ud800-\udfff]')  # 줄바꿈·탭을 뺀 제어문자
RANGE = r'[\[［]\s*\d+\s*[~∼～〜\-–]\s*\d+\s*[\]］]'  # 문제 번호 범위 [1~3]
INSTR_HEAD = re.compile(r'^(?:\s*(?:' + RANGE + r'|[※＊*]|\d+\s*[.)])\s*)+')  # 안내문 앞머리의 [1~3]·※·1. (여러 개)

# 템플릿 헤더의 문단 모양(pp)·글자 모양(cp) ID. 근거는 references/format-spec.md 3절.
IDS = {
    'basic': dict(head=12, instr=(0, 10), stem=(62, 37, 38), choice=(41, 0), box=dict(norm=0, bold=10, pp=32, src=(43, 3), ul=32, lbl=3, sum=3),
              bogi=dict(norm=0, bold=10, pp=85, label=(54, 41), src=(42, 3), ul=32), title=(61, 53), snippet='basic_bogi_box_1x1.xml'),
}
# 표 높이 어림: (칸 안쪽 폭 pt, 글자 크기 pt, 줄간격 배수, 고정 높이, 문단마다 더할 높이, 최소 높이), 높이는 hwpunit.
FIT = {'basic_bogi_box_1x1.xml': (189.4, 10, 1.25, 800, 250, 0)}
KEYS = {
    'top': {'format', 'title', 'items', 'group_start'}, 'blank': {'type', 'n'}, 'instruction': {'type', 'text'}, 'passage': {'type', 'paras', 'source'},
    'question': {'type', 'stem', 'answer', 'choices', 'score', 'bogi', 'note'}, 'end_heading': {'type', 'text'}, 'column_break': {'type'}, 'page_break': {'type'},
    'bogi': {'lines', 'source', 'style'}, 'note': {'point', 'why', 'wrong'},
}
ITEM_TYPES = ('blank', 'instruction', 'passage', 'question', 'end_heading', 'column_break', 'page_break')
WARNINGS = []
COLW, BODY = 201.26, 657.61  # 한 단의 폭·본문 높이(pt) (format-spec 7절)

# 선택지 줄바꿈 예측(자간 줄이기용). 번호 뒤 탭 덕에 모든 줄이 탭 정지(left+|intent|)에서 시작해 줄 폭이 같다.
# CHW = (본문 줄 폭 pt = 201.24 − left − |intent|, 글자 크기 pt, 보정 pt). 보정은 골든 선택지 줄바꿈에 맞춘 값(117/117 일치).
# shortcut: 한컴 글꼴 폭표 없이 글자 종류별 폭(em)으로 어림한다 — 영문·기호가 많으면 틀릴 수 있고, 그때는 한글에서 자간을 직접 고친다.
CHW = {'basic': (181.36, 10, -0.5)}
CHOICE = {'basic': (500, 1488, 10)}  # 선택지 문단의 (left, |intent|, 글자 크기 pt)
SAFE = 2.0  # 자간을 줄인 뒤 들어가는지는 이만큼(pt) 좁은 폭으로 확인한다
NOLS = '.,?!)]’”」』》〉'  # 줄머리 금칙: 앞 글자와 함께 내려간다
HANGUL_EM = .9689  # 함초롬바탕 한글·원문자 폭(em)

# 함초롬바탕 글자별 폭(em). python-hwpx(form_fit/_glyph_table.py, 글꼴 hmtx)에서 옮겼다.
_ADV = {}
for _v, _cs in ((.287, 'il'), (.288, 'j'), (.305, 'I'), (.315, 'J'), (.32, '!"\'(),.:;[]`{|}‘’·'), (.356, 'ft'), (.478, 'r'), (.48, '“”'), (.486, 'z'), (.496, 's'),
                (.5, '「」『』〈〉《》〔〕【】'), (.536, 'e'), (.542, 'x'), (.543, 'y'), (.55, '*+-/0123456789<=>?\\^_~'), (.552, 'c'), (.562, 'g'), (.563, 'v'), (.569, 'a'),
                (.579, 'q'), (.582, 'k'), (.588, 'o'), (.597, 'bdp'), (.603, 'P'), (.605, 'BL'), (.61, '#$'), (.617, 'F×'), (.625, '–'), (.626, 'Z'), (.627, 'ES'),
                (.635, 'hnu'), (.66, 'KR'), (.664, 'T'), (.678, '÷'), (.683, 'G'), (.685, 'C'), (.705, 'QXY'), (.706, 'AV'), (.719, 'D'), (.72, 'w'), (.724, '&'),
                (.731, 'U'), (.732, 'O'), (.734, 'HN'), (.77, '※'), (.798, '±'), (.83, '%@'), (.839, 'M'), (.875, '—'), (.907, 'm'), (.91, 'W'), (.96, '…'),
                (.97, '≠≤≥≒→←↑↓○●◎◇◆□■△▲▽▼')):
    for _c in _cs: _ADV[_c] = _v


def fail(msg): raise SystemExit('오류: ' + msg)


def nlines(t, size, width):  # 줄 수 어림(한글·공백 섞인 글의 평균 글자 폭 0.85em)
    return max(1, math.ceil(len(t) * 0.85 * size / width - 1e-9))


def ptext(x):  # 문단 XML 의 글
    return html.unescape(''.join(re.findall(r'<hp:t>(.*?)</hp:t>', x)))


def cwidth(c):
    o = ord(c)
    if c == ' ': return .5
    if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F or 0x4E00 <= o <= 0x9FFF or 0x2460 <= o <= 0x24FF or 0x3200 <= o <= 0x32FF: return HANGUL_EM
    return _ADV.get(c, .6)


def wrap_lines(t, size, w, sp=0):
    """글자 단위로 나눈 줄 목록(줄 폭 w pt, 자간 sp%). 공백은 줄 끝에 걸치고, 금칙 글자는 앞 글자와 함께 내려간다."""
    ws = [(cwidth(c) + sp / 100) * size for c in t]
    cuts, x, i = [0], 0.0, 0
    while i < len(t):
        if t[i] != ' ' and x > 0 and x + ws[i] > w + 1e-6:
            j = i
            if t[i] in NOLS:
                j = i - 1
                while j > cuts[-1] + 1 and t[j] == ' ': j -= 1
            if j <= cuts[-1]: j = i  # 한 글자도 못 넣는 줄이면 그대로 둔다
            cuts.append(j); i = j; x = 0.0
            while i < len(t) and t[i] == ' ': i += 1
            continue
        x += ws[i]; i += 1
    return [t[a:b] for a, b in zip(cuts, cuts[1:] + [len(t)])]


def tighten(t, fid):
    """선택지 본문의 마지막 줄에 한 글자(+문장부호)만 남으면 한 줄을 덜 쓰는 가장 작은 자간(-1~-7%)을 찾는다.
    반환 (자간 %, 줄 수, -7%로도 안 되는지)."""
    w, size, dl = CHW[fid]
    nom = wrap_lines(t, size, w + dl)  # 넘침 판정은 보정 폭으로(좁게 잡으면 골든에서 헛판정이 늘었다)
    if not (len(nom) > 1 and len(nom[-1].strip(' .?!,’”)]」』》〉')) <= 1): return 0, len(nom), False
    for k in range(1, 8):
        ls = wrap_lines(t, size, w + dl - SAFE, -k)
        if len(ls) < len(nom): return -k, len(ls), False
    return 0, len(nom), True


def p_xml(pp, body, style=0):
    return f'<hp:p id="0" paraPrIDRef="{pp}" styleIDRef="{style}" pageBreak="0" columnBreak="0" merged="0">{body}</hp:p>'


def run_xml(cp, t): return f'<hp:run charPrIDRef="{cp}"><hp:t>{escape(t)}</hp:t></hp:run>' if t else f'<hp:run charPrIDRef="{cp}"/>'


def para(pp, runs, style=0):  # runs: [(글자 모양, 글)]
    return p_xml(pp, ''.join(run_xml(c, t) for c, t in runs) or '<hp:run charPrIDRef="0"/>', style)


def choice_xml(pp, cp, n, body, fid):  # 원문자 + 탭 + 본문. 탭이 끝나는 곳(탭 정지)이 둘째 줄 시작과 같다
    _, hang, size = CHOICE[fid]
    return p_xml(pp, f'<hp:run charPrIDRef="{cp}"><hp:t>{CIRC[n]}<hp:tab width="{hang - round(HANGUL_EM * size * 100)}" leader="0" type="1"/>{escape(body)}</hp:t></hp:run>')


# ---------- 헤더: 기존 모양을 복제해 목록 끝에 더한다(같은 설정은 한 번만) ----------
def item_count(xml, tag): return int(re.search(rf'<hh:{tag} itemCnt="(\d+)"', xml).group(1))


def clone(xml, tag, base, new_id):
    return re.search(rf'<hh:{tag} id="{base}" .*?</hh:{tag}>', xml, re.S).group(0).replace(f'id="{base}"', f'id="{new_id}"', 1)


def add_items(xml, tag, n, new):  # 새 항목을 목록 끝에 붙이고 itemCnt 를 맞춘다(G38)
    if not new: return xml
    return xml.replace(f'</hh:{tag}>', ''.join(x for _, x in new.values()) + f'</hh:{tag}>', 1).replace(f'<hh:{tag} itemCnt="{n}">', f'<hh:{tag} itemCnt="{n + len(new)}">', 1)


class CharPrs:  # 글자 모양: 높이·자간·밑줄만 바꾼 복제본
    def __init__(self, hdr): self.hdr, self.n, self.new = hdr, item_count(hdr, 'charProperties'), {}

    def get(self, base, height=None, spacing=0, underline=False):
        key = (base, height, spacing, underline)
        if key not in self.new:
            i = self.n + len(self.new); x = clone(self.hdr, 'charPr', base, i)
            if height: x = re.sub(r'(<hh:charPr [^>]*?height=")\d+(")', rf'\g<1>{height}\2', x, count=1)
            if underline: x = x.replace('<hh:underline type="NONE"', '<hh:underline type="BOTTOM"', 1)
            if spacing: x = re.sub(r'<hh:spacing [^>]*/>', '<hh:spacing ' + ' '.join(f'{a}="{spacing}"' for a in ('hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user')) + '/>', x, count=1)
            self.new[key] = (i, x)
        return self.new[key][0]

    def apply(self, xml): return add_items(xml, 'charProperties', self.n, self.new)


class ParaPrs:  # 문단 모양: keepWithNext·keepLines·탭 정의만 바꾼 복제본, 그리고 탭 정의(tabPr)
    def __init__(self, hdr):
        self.hdr, self.n, self.new = hdr, item_count(hdr, 'paraProperties'), {}
        self.tn, self.tabs = item_count(hdr, 'tabProperties'), {}

    def tab(self, pos):  # 왼쪽 탭 정지 하나(pos: hwpunit). default 값은 case 의 2배여야 한컴에서 맞는다
        if pos not in self.tabs:
            i = self.tn + len(self.tabs)
            self.tabs[pos] = (i, f'<hh:tabPr id="{i}" autoTabLeft="0" autoTabRight="0"><hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
                                 f'<hh:tabItem pos="{pos}" type="LEFT" leader="NONE" unit="HWPUNIT"/></hp:case><hp:default><hh:tabItem pos="{2 * pos}" type="LEFT" leader="NONE"/></hp:default></hp:switch></hh:tabPr>')
        return self.tabs[pos][0]

    def get(self, base, kwn=None, kl=None, tab=None):
        if (kwn, kl, tab) == (None, None, None): return base
        key = (base, kwn, kl, tab)
        if key not in self.new:
            i = self.n + len(self.new); x = clone(self.hdr, 'paraPr', base, i)
            if kwn is not None: x = re.sub(r'keepWithNext="\d"', f'keepWithNext="{kwn}"', x, count=1)
            if kl is not None: x = re.sub(r'keepLines="\d"', f'keepLines="{kl}"', x, count=1)
            if tab is not None: x = re.sub(r'(<hh:paraPr id="\d+" )tabPrIDRef="\d+"', rf'\g<1>tabPrIDRef="{tab}"', x, count=1)
            self.new[key] = (i, x)
        return self.new[key][0]

    def apply(self, xml): return add_items(add_items(xml, 'paraProperties', self.n, self.new), 'tabProperties', self.tn, self.tabs)


# ---------- 입력 검사 ----------
def check_keys(obj, part, where):  # 모르는 키를 조용히 버리지 않는다(지원하지 않는 기능을 쓴 것일 수 있다)
    extra = set(obj) - KEYS[part]
    if extra: fail(f'{where}: 알 수 없는 항목 {sorted(extra)} — 쓸 수 있는 항목: {sorted(KEYS[part])}')


def text(v, where, *, markup=False, optional=False):
    """문자열을 검사·정리한다. 보이지 않는 글자는 지우고 특수 공백은 일반 공백으로(경고), 줄바꿈·짝 없는 서식 표기는 오류."""
    if v is None and optional: return None
    if not isinstance(v, str): fail(f'{where}: 글(문자열)이어야 합니다')
    if CTRL.search(v):
        WARNINGS.append(f'{where}: 보이지 않는 제어문자를 지웠습니다'); v = CTRL.sub('', v)
    v = unicodedata.normalize('NFC', v)  # 자모 분리(NFD) 입력이면 '않은' 같은 낱말을 못 찾는다
    if re.search('[\u2028\u2029\n\r\t]', v): fail(f'{where}: 줄바꿈·탭은 쓸 수 없습니다 — 문단은 항목을 나눠 적습니다')
    hidden = [c for c in v if unicodedata.category(c) == 'Cf']
    if hidden: WARNINGS.append(f'{where}: 보이지 않는 글자 {len(hidden)}개(제로폭 공백·소프트 하이픈 등)를 지웠습니다'); v = ''.join(c for c in v if unicodedata.category(c) != 'Cf')
    if any(c.isspace() and c != ' ' for c in v): WARNINGS.append(f'{where}: 특수 공백(NBSP·전각 공백 등)을 일반 공백으로 바꿨습니다'); v = ''.join(' ' if c.isspace() else c for c in v)
    v2 = re.sub(r'(' + MARK + r')\s*[:：]\s*', r'\1: ', v); v2 = re.sub(r'(' + MARK + r'): $', r'\1:', v2)  # G43
    if v2 != v: WARNINGS.append(f'{where}: 원문자 뒤 `:`를 붙여 썼습니다(㉠ : → ㉠:)'); v = v2
    if not markup and ('**' in v or '<u>' in v or '</u>' in v): fail(f'{where}: ** 굵게·<u> 밑줄은 지문·보기 줄에서만 씁니다(발문·선택지·해설 서식은 스크립트가 넣습니다)')
    if markup:
        if v.count('**') % 2: fail(f'{where}: **가 짝이 맞지 않습니다: {v[:30]}')
        if v.count('<u>') != v.count('</u>'): fail(f'{where}: <u>와 </u>가 짝이 맞지 않습니다: {v[:30]}')
    return v


def marked(t, norm, bold, ul, where):
    """**굵게**·<u>밑줄</u> 표기를 [(글자 모양, 글)]로 나눈다. ul 은 글자 모양 번호, 또는 쓸 때 모양을 만드는 함수."""
    if '<u>' in t and ul is None: fail(f'{where}: 여기서는 <u>밑줄</u>을 쓸 수 없습니다(이 형식에서 밑줄은 지문에만 씁니다)')
    out = []
    for tok in re.split(r'(\*\*.+?\*\*|<u>.+?</u>)', t):
        if not tok: continue
        if tok.startswith('**') and tok.endswith('**') and len(tok) > 4: style, inner = bold, tok[2:-2]
        elif tok.startswith('<u>') and tok.endswith('</u>'): style, inner = (ul() if callable(ul) else ul), tok[3:-4]
        else: style, inner = norm, tok
        if '**' in inner or '<u>' in inner or '</u>' in inner: fail(f'{where}: **와 <u>가 겹치거나 짝이 어긋납니다: {t[:30]}')
        out.append((style, inner))
    return out or [(norm, '')]


def source_text(v, where):  # 출처줄: 없으면 None, 있으면 비어 있지 않아야 한다
    s = text(v, where, optional=True)
    if s is not None and not s.strip(): fail(f'{where}: 비어 있습니다 — 출처줄이 없으면 source 항목을 빼세요')
    return s


def drop_bullet(x, where):  # 글머리표가 "- "를 붙이는 출처줄
    if x.startswith('- '): WARNINGS.append(f'{where}: 앞의 "- "는 글머리표가 붙이므로 지웠습니다'); x = x[2:]
    return x


def as_int(v, where, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi: fail(f'{where}: {lo}~{hi} 사이의 정수여야 합니다(받은 값: {v!r})')
    return v


def as_score(v, where):  # NaN·무한대는 범위 비교에서 걸러진다
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 100 or Decimal(str(v)) % Decimal('0.1'):
        fail(f'{where}: score(배점)는 0보다 크고 100 이하, 소수 첫째 자리까지인 수여야 합니다(받은 값: {v!r})')
    return Decimal(str(v))


# ---------- XML 조립 ----------
def auto_num(n):
    return f'<hp:ctrl><hp:autoNum num="{n}" numType="ENDNOTE"><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/></hp:autoNum></hp:ctrl>'


def endnote(n, paras):
    return (f'<hp:ctrl><hp:endNote number="{n}" suffixChar="41" instId="{1100000000 + n}"><hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP" '
            'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">' + ''.join(paras) + '</hp:subList></hp:endNote></hp:ctrl>')


def note_xml(n, q):
    ans = CIRC[q['answer'] - 1]
    nt = q['note']
    others = [c for i, c in enumerate(CIRC) if i != q['answer'] - 1]
    first = p_xml(0, f'<hp:run charPrIDRef="0">{auto_num(n)}<hp:t> </hp:t></hp:run><hp:run charPrIDRef="39"><hp:t>정답 {ans}   [{q["score"]:.1f}점]</hp:t></hp:run>')
    return endnote(n, [first, para(47, [(40, '출제 포인트  '), (0, nt['point'])]), para(47, [(40, '정답 해설  '), (0, nt['why'])]), para(48, [(40, '오답 분석')])]
                   + [para(49, [(0, f'{c} {w}')]) for c, w in zip(others, nt['wrong'])] + [para(49, [(0, '')])])


def fill_cell(snippet, paras, counter):
    """조각 표의 첫 칸을 새 문단으로 채우고 표 id·zOrder·높이를 새로 매긴다.
    조각의 높이는 원본 내용 기준이라 그대로 두면 빈 공간이 생기므로 줄 수로 어림한다.
    shortcut: 글자 수로 어림한 줄 수라 한컴이 다시 계산한 높이와 조금 다를 수 있다."""
    xml = (ROOT / 'assets/snippets' / snippet).read_text(encoding='utf8')
    m = list(re.finditer(r'(<hp:subList\b[^>]*>)(.*?)(</hp:subList>)', xml, re.S))[0]
    assert '{{본문}}' not in xml[:m.start(2)] + xml[m.end(2):], f'{snippet}: 채우지 않은 자리표시자가 남았습니다'
    xml = xml[:m.start(2)] + ''.join(paras) + xml[m.end(2):]
    xml = re.sub(r'(<hp:tbl id=")\d+(")', rf'\g<1>{1000000000 + counter}\2', xml)
    xml = re.sub(r'(<hp:tbl id="\d+" zOrder=")\d+(")', rf'\g<1>{counter - 1}\2', xml, count=1)
    width, size, mult, fixed, extra, floor = FIT[snippet]
    height = max(floor, round(sum(nlines(ptext(q), size, width) * size * mult * 100 + extra for q in paras)) + fixed)
    if height > 62000:
        WARNINGS.append(f'보기 상자 하나가 추정 {height / 100:.0f}pt로 한 단(658pt)에 거의 차거나 넘습니다 — 보기 줄을 줄이세요(보기 상자는 나눌 수 없습니다)')
    return re.sub(r'(<hp:sz width="\d+" widthRelTo="ABSOLUTE" height=")\d+(")', rf'\g<1>{height}\2', xml, count=1), height


def fix_marks(x, w_):
    """G44: 원문자는 밑줄 밖에 두고, 바로 뒤(여는 따옴표 한 글자는 건너뜀)에 `<u>…</u>`가 와야 한다."""
    x = re.sub(r'<u>(' + MARK + ')', r'\1<u>', x)
    if '<u></u>' in x: fail(f'{w_}: 밑줄 범위가 비어 있습니다')
    marks = list(re.finditer(MARK, x))
    for mm in marks:
        rest = x[mm.end():]
        if not (rest.startswith('<u>') or (rest[:1] in ('“', '‘', '"', "'") and rest[1:].startswith('<u>'))):
            fail(f'{w_}: 원문자 뒤에는 밑줄 범위가 필요합니다 — `{x[max(0, mm.start() - 3):mm.end() + 8]}…`를 `{mm.group()}<u>가리키는 말</u>` 꼴로 적으세요')
    if len({mm.group() for mm in marks}) != len(marks): WARNINGS.append(f'{w_}: 같은 원문자가 한 문단에 두 번 나옵니다(골든에 없는 꼴)')
    if '<u>' in x and not marks: WARNINGS.append(f'{w_}: 원문자 표시 문자 없이 밑줄을 썼습니다(골든의 밑줄은 모두 원문자 뒤)')
    return x


def prep_passage(paras, source, where, st):
    """지문 문단을 [(종류, 글, 위치)]로 정리한다. 종류: p 본문 · sub 소제목 · label 줄거리 표시 · sum 줄거리 요약
    · sumline 같은 문단 안 `[…줄거리] 요약` · src 출처줄 · blank 빈 줄.
    (가) 머리 표시는 굵게(G45), 첫 문단이 아닌 구분 문단 앞에는 빈 줄 정확히 1개(G46), 줄거리는 `[…줄거리]` 9pt(G47)."""
    nobold = '줄거리 요약(9pt 보통)에는 굵게를 쓸 수 없어 **를 뺐습니다'
    raw = []
    for j, x in enumerate(paras, 1):
        w_ = f'{where}.paras[{j}]'; x = text(x, w_, markup=True)
        if x.startswith('# '):
            if not x[2:].strip() or '**' in x or '<u>' in x: fail(f'{w_}: 소제목(# )이 비었거나 **·<u>가 섞였습니다')
            if re.search(MARK, x): fail(f'{w_}: 소제목에는 원문자(㉠ⓐ…)를 쓸 수 없습니다 — 원문자는 본문 문단에만 씁니다')
            st['sub'] += 1; raw.append(['sub', '**' + x[2:].strip() + '**', w_]); continue
        mi = INLINE.match(x)
        if mi:  # (가) 머리는 굵게 10pt, `[…줄거리] 요약`은 9pt(사용자 수정 파일 방식)
            name = (mi.group(2) or mi.group(3)).strip()
            if '|' in x[:len(x) - len(mi.group(4))]: WARNINGS.append(f'{w_}: `{name} |`를 대괄호 `[{name}]`(9pt)로 고쳤습니다')
            if '**' in mi.group(4): WARNINGS.append(f'{w_}: {nobold}')
            raw.append(['sumline', ((mi.group(1) or '').strip(), '[' + name + '] ' + fix_marks(mi.group(4).replace('**', '').strip(), w_)), w_]); continue
        m = LABEL.match(x) if '**' not in x and '<u>' not in x else None
        if m and len(x.strip()) <= 30 and not x.strip().endswith(('.', '?', '!')):
            name = m.group(1).strip()
            if x.strip() != '[' + name + ']': WARNINGS.append(f'{w_}: 줄거리 표시를 대괄호 `[{name}]`(9pt)로 고쳤습니다')
            raw.append(['label', '[' + name + ']', w_]); continue
        if x.startswith('- '):
            if re.search(MARK, x): fail(f'{w_}: 출처줄에는 원문자(㉠ⓐ…)를 쓸 수 없습니다')
            raw.append(['src', x, w_]); continue
        if x == '': raw.append(['blank', '', w_]); continue
        x = fix_marks(x, w_)
        hm = re.match(r'^(\s*)(\(' + GA + r'\))(.*)$', x, re.S)
        if hm and not x.lstrip().startswith('**('): x = hm.group(1) + '**' + hm.group(2) + '**' + hm.group(3)
        raw.append(['p', x, w_])
    while raw and raw[0][0] == 'blank': raw.pop(0)  # 첫머리 빈 줄은 안내문 뒤 3pt 빈 줄 규칙(G37)을 깬다
    if not [e for e in raw if e[0] not in ('blank', 'src')]: fail(f'{where}: 지문에 본문 글이 없습니다(빈 문단이나 출처줄뿐)')
    if source is not None:
        if re.search(MARK, source): fail(f'{where}.source: 출처줄에는 원문자(㉠ⓐ…)를 쓸 수 없습니다')
        raw.append(['src', source, f'{where}.source'])
    for n, e in enumerate(raw):  # 줄거리 요약 = 표시 바로 뒤 본문 문단
        if e[0] != 'label': continue
        if n + 1 < len(raw) and raw[n + 1][0] == 'p' and not re.match(r'^\s*\*\*\(', raw[n + 1][1]):
            raw[n + 1][0] = 'sum'
            if '**' in raw[n + 1][1]: WARNINGS.append(f'{raw[n + 1][2]}: {nobold}'); raw[n + 1][1] = raw[n + 1][1].replace('**', '')
        else: fail(f'{e[2]}: 줄거리 표시 `{e[1]}` 바로 뒤에는 요약 문단(9pt)이 와야 합니다 — 다음 문단에 요약을 적거나 `{e[1]} 요약…`처럼 한 문단에 쓰세요')
    out = []
    for n, e in enumerate(raw):
        if e[0] == 'label' or (e[0] == 'p' and re.match(r'^\s*\*\*\(' + NA + r'\)\*\*', e[1])) or (e[0] == 'sumline' and re.match(r'^\(' + NA + r'\)', e[1][0])):
            k = 0
            while out and out[-1][0] == 'blank': out.pop(); k += 1
            if k > 1: WARNINGS.append(f'{where}: 구분 문단 앞 빈 줄은 한 줄로 줄였습니다')
            if out: out.append(['blank', '', where])
        out.append(e)
        if e[0] == 'sum' and n + 1 < len(raw) and raw[n + 1][0] not in ('blank', 'label', 'sumline') and not (raw[n + 1][0] == 'p' and re.match(r'^\s*\*\*\(' + NA + r'\)', raw[n + 1][1])):
            out.append(['blank', '', where])  # 요약 뒤 한 줄
    if out and out[-1][0] == 'blank': out.pop()
    return [tuple(e) for e in out]


def passage_paras(parts, b, CP, after_passage, where):
    """prep_passage 결과를 지문 문단 XML 목록으로 만든다(b: IDS[fid]['box'])."""
    sum_ul = lambda: CP.get(b['sum'], underline=True)
    blank = para(b['pp'], [(b['norm'], '')])
    ps = []
    if after_passage:  # 문단 테두리는 이어지는 문단을 한 상자로 묶는다
        ps.append(blank); WARNINGS.append(f'{where}: 앞 지문과 한 상자로 이어지지 않게 사이에 빈 줄 하나를 넣었습니다')
    for kd, x, w_ in parts:
        if kd == 'blank': ps.append(blank)
        elif kd == 'sub': ps.append(para(b['pp'], marked(x, b['norm'], b['bold'], None, w_)))
        elif kd == 'label': ps.append(para(b['pp'], [(b['lbl'], x)]))
        elif kd == 'sumline':
            head, body = x
            ps.append(para(b['pp'], [(b['norm'], ' ')] + ([(b['bold'], head), (b['norm'], ' ')] if head else []) + marked(body, b['sum'], b['sum'], sum_ul, w_)))
        elif kd == 'sum': ps.append(para(b['pp'], marked(x, b['sum'], b['sum'], sum_ul, w_)))
        elif kd == 'src': ps.append(para(b['src'][0], [(b['src'][1], x if x.startswith('- ') else '- ' + x)]))
        else:
            if x: x = ' ' + x.lstrip(' ')  # 첫머리 한 칸 들여쓰기(공백 문자)
            ps.append(para(b['pp'], marked(x, b['norm'], b['bold'], b['ul'], w_)))
    return ps


def check_question(it, qw):
    """문항 항목을 검사·정리한다. 반환 (발문, 선택지 5개, 미주용 dict(answer, score, note))."""
    stem = text(it.get('stem'), f'{qw}.stem').strip()
    if not stem.endswith('?'): fail(f'{qw}.stem: 발문은 물음표(?)로 끝나야 합니다: {stem[:30]}')
    if re.match(r'\d+[.)]\s|[①-⑤]', stem) or re.search(r'\[\d+(\.\d+)?점\]', stem): fail(f'{qw}.stem: 문제 번호·배점은 스크립트가 넣습니다 — 글에서 빼세요: {stem[:30]}')
    ans = as_int(it.get('answer'), f'{qw}.answer', 1, 5)
    ch = it.get('choices')
    if not isinstance(ch, list) or len(ch) != 5: fail(f'{qw}.choices: 선택지는 5개의 목록이어야 합니다(받은 개수: {len(ch) if isinstance(ch, list) else "목록 아님"})')
    ch = [text(c, f'{qw}.choices[{i}]').strip() for i, c in enumerate(ch, 1)]
    for i, c in enumerate(ch, 1):
        cw = f'{qw}.choices[{i}]'
        if not c: fail(f'{cw}: 비어 있습니다')
        if re.match(r'[①-⑤]|\d+[.)]\s', c): fail(f'{cw}: 선택지 번호(①)는 스크립트가 붙입니다 — 글에서 빼세요: {c[:20]}')
        if not c.strip('. '): fail(f'{cw}: 마침표뿐이라 내용이 없습니다')
        if re.search(r'[!?]\.$', c):
            WARNINGS.append(f'{cw}: 느낌표·물음표 뒤의 마침표를 뺐습니다: …{c[-10:]}'); ch[i - 1] = c[:-1]
        elif c.endswith('.') and not c.endswith('..') and sentence_kind(c) == 'no' and not DEF.match(c):  # 말줄임표·maybe·정의형(`ⓐ: …`)은 쓴 대로 둔다(G20)
            WARNINGS.append(f'{cw}: 문장이 아니라서(명사구·표시 문자 나열) 끝의 마침표를 뺐습니다: …{c[-10:]}'); ch[i - 1] = c[:-1].rstrip()
        elif sentence_kind(c) == 'yes' and not c.endswith(('.', '?', '!')): WARNINGS.append(f'{cw}: 문장인데 마침표(.)로 끝나지 않습니다: …{c[-10:]}')
    sc = as_score(it['score'], f'{qw}.score') if 'score' in it else None
    if sc is None or 'note' not in it: fail(f'{qw}: 이 형식은 문항마다 score(배점)와 note(point·why·wrong)가 필요합니다')
    q = dict(answer=ans, score=sc)
    nt = it['note']
    if not isinstance(nt, dict): fail(f'{qw}.note: point·why·wrong을 가진 객체여야 합니다')
    check_keys(nt, 'note', f'{qw}.note')
    for f in ('point', 'why', 'wrong'):
        if f not in nt: fail(f'{qw}.note.{f}: 빠졌습니다')
    wrong = nt['wrong']
    if not isinstance(wrong, list) or len(wrong) != 4: fail(f'{qw}.note.wrong: 정답을 뺀 선택지 4개의 해설 목록이어야 합니다(받은 개수: {len(wrong) if isinstance(wrong, list) else "목록 아님"})')
    q['note'] = dict(point=text(nt['point'], f'{qw}.note.point'), why=text(nt['why'], f'{qw}.note.why'),
                     wrong=[text(w, f'{qw}.note.wrong[{i}]') for i, w in enumerate(wrong, 1)])
    for i, w in enumerate(q['note']['wrong'], 1):
        if re.match(r'\s*([①-⑤]|\d+[.)]\s)', w): fail(f'{qw}.note.wrong[{i}]: 선택지 번호(①)는 스크립트가 붙입니다 — 글에서 빼세요: {w[:20]}')
    return stem, ch, q


def bogi_paras(bg, qw, g):
    """〈보기〉 항목을 검사해 상자 안 문단 XML 목록을 만든다(g: IDS[fid]['bogi'])."""
    if not isinstance(bg, dict) or not isinstance(bg.get('lines'), list) or not bg['lines']:
        fail(f'{qw}.bogi: {{"lines": ["…", …]}} 꼴이어야 합니다(칸이 있는 표는 지원하지 않으니 줄글로 적습니다)')
    check_keys(bg, 'bogi', f'{qw}.bogi')
    bstyle = bg.get('style', 'poem')
    if bstyle not in ('poem', 'prose'): fail(f'{qw}.bogi.style: "poem"(시, 기본) 또는 "prose"(산문) 중 하나입니다')
    ls = []
    for j, x in enumerate(bg['lines'], 1):
        lw = f'{qw}.bogi.lines[{j}]'; x = text(x, lw, markup=True)
        ls.append(marked(' ' + x.lstrip(' ') if bstyle == 'prose' and x else x, g['norm'], g['bold'], g['ul'], lw))
    lpp = 55 if bstyle == 'prose' else g['pp']  # 골든 C: 시 보기는 첫 줄 들여쓰기(pp85), 산문 보기는 들여쓰기 없는 문단(pp55)+첫머리 공백
    ps = [para(g['label'][0], [(g['label'][1], '〈 보 기 〉')])] + [para(lpp, r) for r in ls]
    src = source_text(bg.get('source'), f'{qw}.bogi.source')
    if src is not None: ps.append(para(g['src'][0], [(g['src'][1], drop_bullet(src, f'{qw}.bogi.source'))]))
    return ps


def page_heights(segs, starts):
    """나눔으로 갈린 구간 높이(pt)를 쪽별로 묶고, 단에 넘치거나 꽉 찬 곳을 경고한다.
    단 나눔 없는 쪽은 두 단에 걸쳐 흐르고, 단 나눔이 하나면 각 단이 한 단 높이에 들어가야 한다."""
    pages = []
    for h, start in zip(segs, starts):
        if start == 'page' or not pages: pages.append([])
        pages[-1].append(h)
    for n, hs in enumerate(pages, 1):
        if len(hs) > 2: WARNINGS.append(f'{n}쪽: 단 나눔이 {len(hs) - 1}개라 단이 3개 이상 필요합니다(한 쪽은 두 단)')
        elif len(hs) == 1 and hs[0] > 2 * BODY: WARNINGS.append(f'{n}쪽: 추정 {hs[0]:.0f}pt가 두 단({2 * BODY:.0f}pt)을 넘어 다음 쪽으로 이어집니다(어림 ±10%)')
        elif len(hs) == 2:
            for side, h in zip(('왼쪽', '오른쪽'), hs):
                if h > BODY: WARNINGS.append(f'{n}쪽 {side} 단: 추정 {h:.0f}pt가 한 단({BODY:.0f}pt)을 넘습니다 — 나눔이 제자리에 오지 않을 수 있으니 내용을 줄이거나 나눔을 더하세요(어림 ±10%)')
                elif h > 0.9 * BODY: WARNINGS.append(f'{n}쪽 {side} 단: 추정 {h:.0f}pt로 한 단({BODY:.0f}pt)에 여유가 거의 없습니다(어림 ±10%)')
    return pages


def pick_format(spec):
    fs = json.loads((ROOT / 'assets/formats.json').read_text(encoding='utf-8'))
    ids = ', '.join(f'"{f["id"]}"' for f in fs)
    if 'format' in spec: f = next((f for f in fs if f['id'] == spec['format']), None)
    elif len(fs) == 1: return fs[0]
    else: fail(f'format(형식 이름)을 적어야 합니다 — 쓸 수 있는 값: {ids}')
    if f is None: fail(f'format은 {ids} 중 하나여야 합니다(받은 값: {spec["format"]!r})')
    return f


def build(spec):
    check_keys(spec, 'top', '최상위')
    f = pick_format(spec); fid = f['id']
    I = IDS[fid]; items = spec.get('items')
    if not isinstance(items, list) or not items: fail('items에 항목이 하나 이상 있어야 합니다')
    hdr = zipfile.ZipFile(ROOT / f'assets/templates/exam_template_{fid}.hwpx').read('Contents/header.xml').decode('utf-8')
    CP, PP = CharPrs(hdr), ParaPrs(hdr)
    gs = spec.get('group_start', 'column')
    if gs not in ('column', 'page', 'flow'): fail('group_start는 "column"(기본, 지문 묶음을 새 단 맨 위에서)·"page"(새 쪽 맨 위에서)·"flow"(나눔 없음) 중 하나입니다')
    fs = 10  # 본문 글자 크기(pt)
    blank = para(0, [(0, '')]); out = [blank]  # 제목 다음 빈 문단
    gap = lambda: para(PP.get(0, kwn=1), [(31, '')])  # 안내문 뒤 빈 줄은 글자 3pt(골든 charPr 31)
    tl = spec.get('title'); ntitle = len(tl) if isinstance(tl, list) and tl else 1
    # segs/starts: 나눔으로 갈린 구간마다의 어림 높이(pt)와 그 구간이 새 쪽·단 어느 쪽에서 시작하는지
    st = dict(q=0, scores=[], tbl=0, blanks=1, cbrk=0, pbrk=0, bogi=0, passage=0, sub=0, src=0, answers=[], tight=[], gbrk=0, gs=gs, ninstr=0, pp=PP, cp=CP,
              segs=[24.0 * ntitle + 16.0], starts=['page'], brk=None)
    after_instr = gap_done = False  # 안내문 바로 다음 자리인가 / 그 자리에 3pt 빈 줄을 이미 넣었는가
    last_t = None

    def emit(x, h=0.0):  # h: 어림 높이(pt). 걸린 나눔(st['brk'])은 다음 문단이 받는다
        if st['brk']:
            x = x.replace(f'{st["brk"]}="0"', f'{st["brk"]}="1"', 1); st['starts'].append('page' if st['brk'] == 'pageBreak' else 'column'); st['brk'] = None; st['segs'].append(0.0)
        st['segs'][-1] += h; out.append(x)

    for k, it in enumerate(items, 1):
        if not isinstance(it, dict) or not isinstance(it.get('type'), str): fail(f'{k}번째 항목: {{"type": "..."}} 꼴이어야 합니다')
        t = it['type']; where = f'{k}번째 항목({t})'
        if t not in ITEM_TYPES: fail(f'{where}: 알 수 없는 type입니다 — 쓸 수 있는 값: {", ".join(ITEM_TYPES)}')
        check_keys(it, t, where)
        prev_t, last_t = last_t, t
        if t == 'blank':
            n = as_int(it.get('n', 1), f'{where}.n', 1, 200)
            for _ in range(n): emit(gap(), 4.8) if after_instr else emit(blank, 16.0)
            if after_instr: gap_done = True
            st['blanks'] += n
            continue
        if t in ('column_break', 'page_break'):
            if st['brk']: fail(f'{where}: 나눔 항목이 연달아 있습니다')
            if after_instr: fail(f'{where}: 안내문과 지문 사이에는 나눔을 둘 수 없습니다 — 새 단(쪽)에서 시작하려면 나눔을 안내문 앞에 두세요')
            st['brk'] = 'columnBreak' if t == 'column_break' else 'pageBreak'; st['cbrk' if t == 'column_break' else 'pbrk'] += 1
            continue
        if t == 'passage' and after_instr and not gap_done: emit(gap(), 4.8)  # 골든: 문단 테두리 지문 앞 3pt 빈 줄(자동)
        after_instr = gap_done = False
        if t == 'instruction':
            tx0 = text(it.get('text'), f'{where}.text')
            core = INSTR_HEAD.sub('', tx0)  # 안내문은 번호 범위 대신 `※`로 시작한다(G42)
            if not core.strip(): fail(f'{where}.text: 안내문 글이 비어 있습니다(예: 다음 글을 읽고 물음에 답하시오.)')
            tx = '※ ' + core.strip()
            if not tx.endswith('물음에 답하시오.'): WARNINGS.append(f'{where}: 안내문이 `…물음에 답하시오.`로 끝나지 않습니다(골든: ※ 다음 글을 읽고 물음에 답하시오.)')
            if re.match(r'\s*' + RANGE, tx0): WARNINGS.append(f'{where}: 안내문 앞 문제 번호 범위를 지우고 `※`를 붙였습니다')
            ix = para(PP.get(I['instr'][0], kwn=1), [(I['instr'][1], tx)])
            if st['ninstr'] and gs != 'flow' and not st['brk']:  # 첫 묶음 말고는 지문 묶음이 단(쪽) 맨 위에서 시작한다(G41)
                st['brk'] = 'columnBreak' if gs == 'column' else 'pageBreak'; st['gbrk'] += 1
            st['ninstr'] += 1
            emit(ix, nlines(tx, fs, COLW) * fs * 1.6); after_instr = True
        elif t == 'end_heading':  # 제목 문단은 맨 끝에서 늘 자동으로 넣는다(이 항목은 검사만)
            if k != len(items): fail(f'{where}: end_heading은 마지막 항목이어야 합니다(그 뒤에 미주가 모입니다)')
            if text(it.get('text', '정답과 해설'), f'{where}.text').strip() != '정답과 해설': fail(f'{where}.text: 제목은 "정답과 해설"이어야 합니다(G35) — text를 빼도 됩니다')
        elif t == 'passage':
            paras = it.get('paras')
            if not isinstance(paras, list) or not paras: fail(f'{where}.paras: 문단 문자열의 목록이어야 합니다')
            parts = prep_passage(paras, source_text(it.get('source'), f'{where}.source'), where, st)
            ps = passage_paras(parts, I['box'], CP, prev_t == 'passage', where)
            st['passage'] += 1; st['src'] += sum(kd == 'src' for kd, _, _ in parts)
            for x in ps: emit(x, nlines(re.sub(r'<[^>]+>', '', ptext(x)), 10, COLW - 11.3) * 16.0)  # 문단 테두리 지문: 문단마다 10pt×160%, 테두리 안쪽 여백 위아래 11.3pt
            st['segs'][-1] += 11.3
        elif t == 'question':
            st['q'] += 1; n = st['q']; qw = f'문항 {n}'
            stem, ch, q = check_question(it, qw); sc = q['score']
            st['scores'].append(sc)
            st['answers'].append(q['answer'])
            spid, stcp, negcp = I['stem']; spid = PP.get(spid, kwn=1, kl=1)  # G40: 발문~④는 다음 문단과 함께, 모든 문단은 줄 단위로 쪼개지지 않게
            tag = f' [{sc:.1f}점]'
            pieces, pos = [], 0
            for m in NEG.finditer(stem):  # 부정 낱말은 모두 굵게+밑줄(G15)
                pieces += [(stcp, stem[pos:m.start()]), (negcp, m.group())]; pos = m.end()
            pieces = [p for p in pieces if p[1]] + [(stcp, stem[pos:] + tag)]
            c, x = pieces[-1]
            sh = nlines(stem + tag, fs, COLW - 16) * 12.5 + 12.0
            emit(p_xml(spid, ''.join(run_xml(c_, x_) for c_, x_ in pieces[:-1]) + f'<hp:run charPrIDRef="{c}"><hp:t>{escape(x)}</hp:t>{note_xml(n, q)}<hp:t/></hp:run>'), sh)
            if 'bogi' in it:
                ps = bogi_paras(it['bogi'], qw, I['bogi'])
                st['tbl'] += 1; st['bogi'] += 1; bx, bh = fill_cell(I['snippet'], ps, st['tbl'])
                bx = re.sub(r'paraPrIDRef="(\d+)"', lambda m_: f'paraPrIDRef="{PP.get(int(m_.group(1)), kwn=1)}"', bx, count=1)  # 보기 상자도 다음 문단과 함께
                emit(bx, bh / 100 + 2.8)
            pp, cp = I['choice']; left_, hang_, _ = CHOICE[fid]; tabid = PP.tab(left_ + hang_)
            lh, aft = 12.5, 1.5
            for i, c_ in enumerate(ch):
                sp, nl, stuck = tighten(c_, fid)
                if sp: st['tight'].append((n, i + 1, sp))
                elif stuck: WARNINGS.append(f'{qw}.choices[{i + 1}]: 마지막 줄에 한 글자만 남는데 자간을 -7%까지 줄여도 안 됩니다 — 문구를 줄이세요')
                cpp = PP.get(pp, kwn=1 if i < 4 else 0, kl=1, tab=tabid)  # ⑤에서 문항 사슬을 끊는다
                emit(choice_xml(cpp, CP.get(cp, spacing=sp) if sp else cp, i, c_, fid), nl * lh + aft)
    # 정답과 해설 제목(G35): 미주가 시작하는 쪽 맨 위에 13pt 굵게. 제목 문단이 스스로 새 쪽을 연다
    pb, st['brk'] = st['brk'], None
    if pb == 'columnBreak': WARNINGS.append('맨 끝 column_break는 쓰이지 않습니다 — 정답과 해설 제목이 새 쪽을 엽니다'); st['cbrk'] -= 1
    st['starts'].append('page'); st['segs'].append(22.4)
    out.append(para(0, [(CP.get(I['head'], height=1300), '정답과 해설')]).replace('pageBreak="0"', 'pageBreak="1"', 1))
    if st['q'] == 0: fail('question(문항)이 하나도 없습니다')
    if st['q'] >= 5 and max(st['answers'].count(a) for a in set(st['answers'])) > 0.4 * st['q']:
        WARNINGS.append('정답 번호가 한쪽으로 쏠려 있습니다(한 번호가 40% 초과) — 의도한 것인지 확인하세요')
    if st['cbrk'] + st['pbrk'] + st['gbrk']: st['pages'] = page_heights(st['segs'], st['starts'])
    return f, ''.join(out), st


def stamp(hpf, title):  # 제목과 만든 날짜를 content.hpf 에 적는다(한컴 저장본에는 늘 날짜가 있다)
    now = datetime.datetime.now(datetime.timezone.utc); ko = now.astimezone(); iso = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    kdate = f'{ko.year}년 {ko.month}월 {ko.day}일 {"월화수목금토일"[ko.weekday()]}요일 {"오전" if ko.hour < 12 else "오후"} {ko.hour % 12 or 12}:{ko:%M:%S}'
    hpf = hpf.replace('<opf:title/>', f'<opf:title>{escape(" ".join(title))}</opf:title>')
    for name, val in (('CreatedDate', iso), ('ModifiedDate', iso), ('date', kdate)):
        hpf = re.sub(rf'(<opf:meta name="{name}" content="text">)(</opf:meta>)', rf'\g<1>{val}\g<2>', hpf)
    return hpf


def main(src, dst):
    try:
        spec = json.loads(Path(src).read_text(encoding='utf-8-sig'))
    except FileNotFoundError: fail(f'입력 파일이 없습니다: {src}')
    except UnicodeDecodeError: fail(f'{src}: UTF-8로 저장한 JSON이어야 합니다(메모장: 다른 이름으로 저장 → 인코딩 UTF-8)')
    except RecursionError: fail(f'{src}: JSON이 너무 깊게 겹쳐 있습니다')
    except json.JSONDecodeError as e: fail(f'{src}: JSON 문법 오류 — {e.lineno}번째 줄 {e.colno}번째 글자 근처. 쉼표·따옴표·괄호를 확인하세요(글 안의 큰따옴표는 \\")')
    except ValueError: fail(f'{src}: JSON의 숫자가 너무 큽니다')
    except OSError as e: fail(f'{src}: 읽을 수 없습니다({e.strerror})')
    if not isinstance(spec, dict): fail('JSON 최상위는 {"format": …, "title": …, "items": […]} 꼴이어야 합니다')
    if Path(src).resolve() == Path(dst).resolve(): fail('출력 파일이 입력 JSON과 같은 경로입니다(입력이 덮어써집니다)')
    if not str(dst).lower().endswith('.hwpx'): WARNINGS.append('출력 파일 확장자가 .hwpx가 아닙니다 — 한글에서 열리지 않을 수 있습니다')
    f, body, st = build(spec); fid = f['id']
    title = spec.get('title')
    if isinstance(title, str): title = [title]
    if not isinstance(title, list) or not title or not all(isinstance(x, str) and x.strip() for x in title): fail('title은 한 줄 이상의 글(문자열) 목록이어야 합니다')
    title = [text(x, f'title[{i}]').strip() for i, x in enumerate(title, 1)]
    if len(title) > 3: fail('제목은 최대 3줄입니다')
    tpl = zipfile.ZipFile(ROOT / f'assets/templates/exam_template_{fid}.hwpx')
    sec = tpl.read('Contents/section0.xml').decode().replace('시험 제목', escape(title[0]))
    sec = re.sub(r'^<\?xml[^>]*\?>\s*', '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', sec)  # 한컴이 저장하는 선언 형식
    extra = ''.join(para(IDS[fid]['title'][0], [(IDS[fid]['title'][1], x)]) for x in title[1:])  # 둘째 줄부터
    sec = sec.replace('</hs:sec>', extra + body + '</hs:sec>')
    ET.fromstring(sec.encode())  # well-formed 확인
    try:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
            for it in tpl.infolist():
                data = tpl.read(it.filename)
                if it.filename == 'Contents/section0.xml': data = sec.encode()
                elif it.filename == 'Contents/content.hpf': data = stamp(data.decode(), title).encode()
                elif it.filename == 'Contents/header.xml': data = st['pp'].apply(st['cp'].apply(data.decode('utf-8'))).encode('utf-8')
                zo.writestr(it.filename, data, compress_type=zipfile.ZIP_STORED if it.filename == 'mimetype' else zipfile.ZIP_DEFLATED)
    except OSError as e: fail(f'{dst}: 저장할 수 없습니다({e.strerror})')
    print(f'{dst}: {f["title"]}({f["id"]}) | 지문 {st["passage"]}개(소제목 {st["sub"]}, 출처줄 {st["src"]}) | 문항 {st["q"]}개 | 보기 {st["bogi"]}개 | 배점 합 {sum(st["scores"]):.1f}점 | 빈 문단 {st["blanks"]}개 | 단 나눔 {st["cbrk"] + (st["gbrk"] if st["gs"] == "column" else 0)}개·쪽 나눔 {st["pbrk"] + (st["gbrk"] if st["gs"] == "page" else 0)}개(묶음 시작 자동 {st["gbrk"]}개 포함)')
    if st.get('pages'): print(f'쪽별 추정 높이(pt, 어림 ±10%; 한 단 {BODY:.0f}, 단 나눔 없는 쪽은 두 단에 걸쳐 흐름): ' + ' | '.join(f'{n_}쪽 ' + ' / '.join(f'{h_:.0f}' for h_ in hs_) for n_, hs_ in enumerate(st['pages'], 1)))
    if st['tight']: print('자간 줄임(선택지 마지막 줄에 한 글자만 남는 것을 막음): ' + ', '.join(f'문항 {q}-{CIRC[c - 1]} {sp}%' for q, c, sp in st['tight']))
    for w in WARNINGS: print('경고:', w)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] in ('-h', '--help'): raise SystemExit(USAGE)
    main(*sys.argv[1:])
