"""서식 부품(assets/components/<부품 id>/) 읽기 · 시험지 헤더에 모양 맞추기 · 본문 자리 채우기 · 목록 출력(표준 라이브러리만).
부품은 모양만 맡는다. 모양 번호는 맞춘 헤더 기준으로 바뀌므로 코드에 번호를 쓰지 않고 역할 이름으로 받는다.
사용: python3 components.py [형식 이름] [--md]   (부품 목록과 쓸 수 있는 문항 형식)
shortcut: 표준 XML 파서는 우리가 배포하는 부품·시험지 헤더만 읽는다(외부 입력 아님), 사용자 파일을 받게 되면 defusedxml 로 바꾼다."""
import json, re, sys
sys.dont_write_bytecode = True  # 스킬 폴더에 __pycache__ 를 남기지 않는다
from pathlib import Path
import xml.etree.ElementTree as ET

KINDS = ('font', 'borderFill', 'tabPr', 'charPr', 'numbering', 'bullet', 'paraPr')  # 의존 순서: numbering·bullet 의 paraHead 가 글자 모양을 가리키므로 글자가 먼저다
LIST = {'borderFill': 'borderFills', 'tabPr': 'tabProperties', 'charPr': 'charProperties', 'numbering': 'numberings', 'bullet': 'bullets', 'paraPr': 'paraProperties'}
BY_LIST = {v: k for k, v in LIST.items()}
LANGS = {'hangul': 'HANGUL', 'latin': 'LATIN', 'hanja': 'HANJA', 'japanese': 'JAPANESE', 'other': 'OTHER', 'symbol': 'SYMBOL', 'user': 'USER'}
REF = {'borderFillIDRef': 'borderFill', 'tabPrIDRef': 'tabPr', 'charPrIDRef': 'charPr'}
NONE_REF = 4294967295
MASK = {'paraPr': {'paraPr': {'tabPrIDRef'}, 'breakSetting': {'keepWithNext', 'keepLines'}}, 'charPr': {'charPr': {'height'}, 'spacing': None, 'underline': {'type'}}}  # 느슨한 정규형이 빼는 변형 속성(None=속성 전부)
CP_KEYS, ROLE_KEYS = {'id', 'name', 'desc', 'kind', 'roles', 'slots', 'fit', 'rules', 'used_by'}, {'pp': 'paraPr', 'cp': 'charPr', 'bf': 'borderFill'}
ROLE_NAME = {'pp': '문단 모양', 'cp': '글자 모양', 'bf': '테두리'}
KIND_NAME = {'paraPr': '문단 모양', 'charPr': '글자 모양', 'borderFill': '테두리·배경'}


def fail(msg): raise SystemExit('오류: ' + msg)


def lt(e): return e.tag.rsplit('}', 1)[-1]


# 헤더 목록 도우미(build_exam.py 의 CharPrs·ParaPrs 도 쓴다)
def item_count(xml, tag): return int(re.search(rf'<hh:{tag} itemCnt="(\d+)"', xml).group(1))


def clone(xml, tag, base, new_id):
    return re.search(rf'<hh:{tag} id="{base}" .*?</hh:{tag}>', xml, re.S).group(0).replace(f'id="{base}"', f'id="{new_id}"', 1)


def add_items(xml, tag, n, new):  # 새 항목을 목록 끝에 붙이고 itemCnt 를 맞춘다(G38)
    if not new: return xml
    return xml.replace(f'</hh:{tag}>', ''.join(x for _, x in new.values()) + f'</hh:{tag}>', 1).replace(f'<hh:{tag} itemCnt="{n}">', f'<hh:{tag} itemCnt="{n + len(new)}">', 1)


class Canon:  # 헤더(또는 styles.xml) 정의의 정규형: id 를 빼고 참조 번호는 대상의 정규형으로 바꾼다. 속성 순서·요소 사이 공백과 무관
    def __init__(s, root):
        s.el, s.dups, s.bad, s.memo = {k: {} for k in KINDS}, [], [], {}
        for ls in root.iter():
            n = lt(ls)
            if n == 'fontfaces': kind, items = 'font', [((ff.get('lang'), int(f.get('id'))), f) for ff in ls for f in ff]
            elif n in BY_LIST: kind, items = BY_LIST[n], [(int(c.get('id')), c) for c in ls]
            else: continue
            for k, e in items:
                if k in s.el[kind]: s.dups.append((kind, k))
                s.el[kind][k] = e

    def of(s, kind, i, loose=False):  # 없는 번호면 KeyError
        k = (kind, i, loose)
        if k not in s.memo:
            e = s.el[kind][i]
            s.memo[k] = ('font', i[0], e.get('face'), e.get('type'), e.get('isEmbedded')) if kind == 'font' else s._c(e, kind, True, loose)
        return s.memo[k]

    def ref(s, kind, v, lang=None):  # 가리키는 번호 → 대상의 정규형. 없는 번호는 기록하고 표시만 남긴다
        try: v = int(v)
        except ValueError: return v
        if v == NONE_REF: return v
        k = (lang, v) if lang else v
        if k in s.el[kind]: return s.of(kind, k)
        s.bad.append((kind, k)); return ('?', kind, k)

    def _c(s, e, kind, top, loose):
        n, a, mk = lt(e), dict(e.attrib), (MASK.get(kind, {}) if loose else {})
        if top: a.pop('id', None)
        if n in mk: a = {} if mk[n] is None else {k: v for k, v in a.items() if k not in mk[n]}
        for k in list(a):
            if k in REF: a[k] = s.ref(REF[k], a[k])
        if n == 'heading' and a.get('type') in ('NUMBER', 'BULLET'): a['idRef'] = s.ref('numbering' if a['type'] == 'NUMBER' else 'bullet', a.get('idRef'))
        if n == 'fontRef':
            for k, lang in LANGS.items():
                if k in a: a[k] = s.ref('font', a[k], lang)
        t = (e.text or '') if not len(e) else ''
        return (e.tag, tuple(sorted(a.items())), tuple(s._c(c, kind, False, loose) for c in e), t if t.strip() else '')

    def index(s, kind):  # 정규형 → 같은 모양인 번호들
        d = {}
        for i in s.el[kind]: d.setdefault(s.of(kind, i), []).append(i)
        return d


def parse(xml):
    try: return ET.fromstring(xml.encode('utf-8'))
    except ET.ParseError as e: fail(f'XML 문법 오류: {e}')


def raw_items(xml):  # styles.xml 원문에서 항목 원문을 그대로 뽑는다(덧붙일 때 원문 그대로 복사하려고). 글꼴은 (언어, id), 나머지는 id
    out = {}
    def eid(x): return int(re.search(r'\sid="(\d+)"', x).group(1))
    for lang, body in re.findall(r'<hh:fontface lang="(\w+)"[^>]*>(.*?)</hh:fontface>', xml, re.S):
        for m in re.finditer(r'<hh:font\b(?:[^>]*/>|[^>]*>.*?</hh:font>)', body, re.S): out[('font', (lang, eid(m.group(0))))] = m.group(0)
    for kind in LIST:
        for m in re.finditer(rf'<hh:{kind}\b(?:[^>]*/>|[^>]*>.*?</hh:{kind}>)', xml, re.S): out[(kind, eid(m.group(0)))] = m.group(0)
    return out


def rewrite(raw, new_id, m):  # 덧붙일 원문의 id 와 참조 번호만 문자열로 바꾼다(m: (종류, 원래 번호) → 맞춘 번호). 값은 건드리지 않는다
    x = re.sub(r'(\sid=")\d+(")', lambda g: f'{g.group(1)}{new_id}{g.group(2)}', raw, count=1)
    x = re.sub(r'\b(borderFillIDRef|tabPrIDRef|charPrIDRef)="(\d+)"', lambda g: f'{g.group(1)}="{m.get((REF[g.group(1)], int(g.group(2))), g.group(2))}"', x)
    def head(g):
        t = re.search(r'type="(\w+)"', g.group(0)); r = re.search(r'idRef="(\d+)"', g.group(0))
        if not (t and r and t.group(1) in ('NUMBER', 'BULLET')): return g.group(0)
        return g.group(0).replace(r.group(0), f'idRef="{m.get(("numbering" if t.group(1) == "NUMBER" else "bullet", int(r.group(1))), r.group(1))}"')
    x = re.sub(r'<hh:heading [^>]*>', head, x)
    return re.sub(r'<hh:fontRef [^>]*>', lambda g: re.sub(r'\b(hangul|latin|hanja|japanese|other|symbol|user)="(\d+)"', lambda h: f'{h.group(1)}="{m.get(("font", (LANGS[h.group(1)], int(h.group(2)))), h.group(2))}"', g.group(0)), x)


class Part:
    def __init__(s, pid, d):
        def bad(msg): fail(f'부품 {pid}: {msg}')
        try: j = json.loads((d / 'component.json').read_text(encoding='utf-8'))
        except FileNotFoundError: bad('component.json 이 없습니다')
        except (ValueError, UnicodeDecodeError) as e: bad(f'component.json 문법 오류({e})')
        if not isinstance(j, dict): bad('component.json 은 {…} 꼴이어야 합니다')
        if set(j) - CP_KEYS: bad(f'component.json 에 알 수 없는 항목 {sorted(set(j) - CP_KEYS)} — 쓸 수 있는 항목: {sorted(CP_KEYS)}')
        if j.get('id') != pid: bad(f'component.json 의 id({j.get("id")!r})가 폴더 이름과 다릅니다')
        s.id, s.name, s.kind, s.desc = pid, j.get('name', ''), j.get('kind', ''), j.get('desc', '')
        s.roles, s.slots, s.fit, s.rules, s.used_by = (j.get(k, v) for k, v in (('roles', {}), ('slots', {}), ('fit', {}), ('rules', []), ('used_by', [])))
        for k, t in (('roles', dict), ('slots', dict), ('fit', dict), ('rules', list), ('used_by', list)):
            if not isinstance(getattr(s, k), t): bad(f'component.json 의 {k} 는 {t.__name__} 이어야 합니다')
        try: xml = (d / 'styles.xml').read_text(encoding='utf-8')
        except FileNotFoundError: bad('styles.xml 이 없습니다')
        try: root = ET.fromstring(xml.encode('utf-8'))
        except ET.ParseError as e: bad(f'styles.xml 문법 오류({e})')
        if lt(root) != 'refList': bad('styles.xml 의 루트는 <hh:refList> 여야 합니다')
        if set(lt(c) for c in root) - set(LIST.values()) - {'fontfaces'}: bad(f'styles.xml 에 알 수 없는 목록 {sorted(set(lt(c) for c in root) - set(LIST.values()) - {"fontfaces"})}')
        try: s.canon = Canon(root)
        except (TypeError, ValueError): bad('styles.xml 항목의 id 가 없거나 숫자가 아닙니다')
        if s.canon.dups: bad(f'styles.xml 에 같은 id 가 두 번 있습니다: {s.canon.dups}')
        s.raw = raw_items(xml)
        if set(s.raw) != {(k, i) for k in KINDS for i in s.canon.el[k]}: bad('styles.xml 항목을 원문으로 읽지 못했습니다(<hh:…> 접두어·id 속성 확인)')
        for k in KINDS:
            for i in s.canon.el[k]: s.canon.of(k, i)
        if s.canon.bad: bad(f'styles.xml 이 정의하지 않은 번호를 가리킵니다: {sorted(set(map(str, s.canon.bad)))}')
        for role, r in s.roles.items():
            if not isinstance(r, dict) or set(r) - set(ROLE_KEYS): bad(f'역할 {role!r} 에 알 수 없는 항목 — 쓸 수 있는 항목: {sorted(ROLE_KEYS)}')
            for a, v in r.items():
                if isinstance(v, bool) or not isinstance(v, int) or v not in s.canon.el[ROLE_KEYS[a]]: bad(f'역할 {role!r} 의 {ROLE_NAME[a]}({a}) 번호 {v!r} 가 styles.xml 에 정의돼 있지 않습니다')
        b = d / 'body.xml'
        s.body_xml = b.read_text(encoding='utf-8') if b.exists() else None
        holes = {h for h in re.findall(r'\{\{([^{}]*)\}\}', s.body_xml or '') if h[:3] not in ('pp:', 'cp:', 'bf:')}
        if holes != set(s.slots): bad(f'slots 는 body.xml 의 글 자리와 같아야 합니다(body.xml: {sorted(holes)}, slots: {sorted(s.slots)})')
        s.map = None  # Registry.resolve 가 채운다: (종류, 원래 번호) → 시험지 헤더의 번호

    def _num(s, abbr, role):
        r = s.roles.get(role)
        if r is None: fail(f'부품 {s.id}: 역할 {role!r} 이 없습니다 — 쓸 수 있는 역할: {sorted(s.roles)}')
        if abbr not in r: fail(f'부품 {s.id}: 역할 {role!r} 에는 {ROLE_NAME[abbr]}({abbr}) 이 없습니다')
        if s.map is None: fail(f'부품 {s.id}: 아직 시험지 헤더에 맞추지 않았습니다(Registry.resolve 먼저)')
        return s.map[(ROLE_KEYS[abbr], r[abbr])]

    def pp(s, role): return s._num('pp', role)
    def cp(s, role): return s._num('cp', role)
    def bf(s, role): return s._num('bf', role)

    def body(s, slots):  # 자리를 한 번의 치환으로 채운다: 채운 글은 다시 훑지 않고, 값 안의 \1·$& 등은 글자 그대로 들어간다
        if s.body_xml is None: fail(f'부품 {s.id}: body.xml 이 없습니다')
        def sub(m):
            k = m.group(1)
            if k is None: fail(f'부품 {s.id}: body.xml 에 짝이 맞지 않는 "{{{{" 가 있습니다')
            if k[:3] in ('pp:', 'cp:', 'bf:'): return str(s._num(k[:2], k[3:]))
            if k not in slots: fail(f'부품 {s.id}: 모르는 자리 {{{{{k}}}}} — 채울 수 있는 자리: {sorted(slots)}')
            if not isinstance(slots[k], str): fail(f'부품 {s.id}: 자리 {k!r} 의 값은 글(문자열)이어야 합니다')
            return slots[k]
        return re.sub(r'\{\{([^{}]*)\}\}|\{\{', sub, s.body_xml)


class Registry:  # 형식(fmt)의 부품들: root 는 스킬 폴더(assets/components/<id>/ 를 읽는다)
    def __init__(s, root, fmt):
        if not isinstance(fmt.get('parts'), dict) or not fmt['parts']: fail(f'형식 {fmt.get("id")!r} 에 parts(형식 안 이름 → 부품 id)가 없습니다')
        cache = {}
        for pid in fmt['parts'].values():
            if pid in cache: continue
            d = Path(root) / 'assets/components' / str(pid)
            if not d.is_dir(): fail(f'부품 {pid}: 폴더가 없습니다(assets/components/{pid})')
            cache[pid] = Part(pid, d)
        s.parts, s.order, s._used, s._allowed = {k: cache[v] for k, v in fmt['parts'].items()}, list(cache.values()), set(), {}

    def use(s, key):
        if key not in s.parts: fail(f'형식에 부품 자리 {key!r} 가 없습니다 — 쓸 수 있는 값: {list(s.parts)}')
        s._used.add(s.parts[key].id); return s.parts[key]

    def used(s): return [p.id for p in s.order if p.id in s._used]

    def allowed(s, kind):  # G50: 부품 styles.xml 의 모든 항목의 느슨한 정규형
        if kind not in KIND_NAME: raise ValueError(kind)
        if kind not in s._allowed: s._allowed[kind] = {p.canon.of(kind, i, True) for p in s.order for i in p.canon.el[kind]}
        return s._allowed[kind]

    def resolve(s, hdr):  # 부품의 모든 모양을 hdr 에 맞춘다: 정규형이 같은 항목은 재사용, 없으면 끝에 덧붙인다. 덧붙임이 없으면 입력을 그대로 돌려준다
        cur, cn = hdr, None
        for p in s.order: p.map = {}
        for kind in KINDS:
            cn = cn or Canon(parse(cur)); idx, add = cn.index(kind), {}
            for p in s.order:
                for oid in p.canon.el[kind]:
                    c = p.canon.of(kind, oid)
                    if c in idx or c in add: continue
                    if kind == 'font':  # 글꼴은 언어 묶음마다 번호가 따로다
                        nid = 1 + max([i for l, i in cn.el[kind] if l == oid[0]] + [v[0] for v in add.values() if v[2] == oid[0]], default=-1)
                        add[c] = (nid, rewrite(p.raw[(kind, oid)], nid, p.map), oid[0])
                    else:  # 테두리·번호·글머리표는 1부터, 나머지는 0부터 센다
                        nid = 1 + max([*cn.el[kind], *(v[0] for v in add.values())], default=0 if kind in ('borderFill', 'numbering', 'bullet') else -1)
                        add[c] = (nid, rewrite(p.raw[(kind, oid)], nid, p.map))
            if add:
                cur = s._append_fonts(cur, add) if kind == 'font' else add_items(cur, LIST[kind], s._count(cur, LIST[kind]), add)
                cn = Canon(parse(cur))
            idx = cn.index(kind)
            for p in s.order:
                for oid in p.canon.el[kind]:
                    cands = idx[p.canon.of(kind, oid)]; v = oid if oid in cands else min(cands); p.map[(kind, oid)] = v[1] if kind == 'font' else v  # 글꼴 번호는 언어 안의 번호
        return cur

    @staticmethod
    def _count(xml, tag):
        if not re.search(rf'<hh:{tag} itemCnt="\d+"', xml): fail(f'시험지 헤더에 <hh:{tag} itemCnt="…"> 목록이 없어 부품의 모양을 덧붙일 수 없습니다')
        return item_count(xml, tag)

    @staticmethod
    def _append_fonts(xml, add):  # add: 정규형 → (새 id, 원문, 언어). 언어 묶음마다 글꼴 목록 끝에 붙이고 fontCnt 를 맞춘다
        for lang in dict.fromkeys(v[2] for v in add.values()):
            new = [v[1] for v in add.values() if v[2] == lang]
            m = re.search(rf'<hh:fontface lang="{lang}" fontCnt="(\d+)"', xml)
            if not m: fail(f'시험지 헤더에 {lang} 글꼴 묶음이 없어 부품의 글꼴을 덧붙일 수 없습니다')
            e = xml.index('</hh:fontface>', m.end())
            xml = xml[:e] + ''.join(new) + xml[e:]
            xml = xml[:m.start(1)] + str(int(m.group(1)) + len(new)) + xml[m.end(1):]
        return xml


def shape_problems(reg, hd, sec):  # G50: 본문의 문단·글자·표 테두리 모양이 부품 모양(느슨한 정규형)과 같은지. 다르면 어디가 다른지 한 줄씩
    cn, bad = Canon(hd), {}
    def chk(kind, v):
        if v is None: return
        v = int(v)
        why = '헤더에 정의 없음' if v not in cn.el[kind] else None if cn.of(kind, v, True) in reg.allowed(kind) else '등록된 부품에 없는 모양'
        if why: bad.setdefault((kind, v, why), 0); bad[(kind, v, why)] += 1
    def walk(e):
        n = lt(e)
        if n == 'p':
            if any(lt(x) == 'secPr' for x in e.iter()): return  # 첫 문단(구역 설정)은 템플릿 몫
            chk('paraPr', e.get('paraPrIDRef'))
        elif n == 'run': chk('charPr', e.get('charPrIDRef'))
        elif n in ('tbl', 'tc'): chk('borderFill', e.get('borderFillIDRef'))
        for c in e: walk(c)
    walk(sec)
    return [f'{KIND_NAME[k]} {v} ({why}, {n}곳)' for (k, v, why), n in bad.items()]


def catalog(root, fmt_id=None, md=False):
    fs = json.loads((Path(root) / 'assets/formats.json').read_text(encoding='utf-8'))
    if fmt_id is not None and fmt_id not in [f['id'] for f in fs]: fail(f'모르는 형식 {fmt_id!r} — 쓸 수 있는 값: {[f["id"] for f in fs]}')
    out = []
    for f in fs:
        if fmt_id not in (None, f['id']): continue
        reg, qt = Registry(root, f), ', '.join(f.get('question_types', [])) or '(없음)'
        cell = lambda x: str(x).replace('|', '\\|')
        if md:
            out += [f'## 형식 {f["id"]} — {f.get("title", "")}', '', f'문항 형식: {qt}', '', '| 부품 | 이름 | 종류 | 설명 | 쓰는 JSON 항목 | 검사 규칙 |', '|---|---|---|---|---|---|']
            out += [f'| {cell(p.id)} | {cell(p.name)} | {cell(p.kind)} | {cell(p.desc)} | {cell(", ".join(p.used_by))} | {cell(", ".join(p.rules))} |' for p in reg.order] + ['']
        else:
            out += [f'형식 {f["id"]} — {f.get("title", "")}', f'  문항 형식: {qt}', f'  부품 {len(reg.order)}개:']
            for p in reg.order: out += [f'  - {p.id}  {p.name} [{p.kind}]', f'      설명: {p.desc}', f'      쓰는 JSON 항목: {", ".join(p.used_by) or "(없음)"}', f'      검사 규칙: {", ".join(p.rules) or "(없음)"}']
            out.append('')
    return '\n'.join(out).rstrip('\n') + '\n'


def main(argv=None):
    a = sys.argv[1:] if argv is None else list(argv)
    md = '--md' in a; a = [x for x in a if x != '--md']
    if len(a) > 1 or (a and a[0] in ('-h', '--help')):
        print('사용: python3 components.py [형식 이름] [--md]  — 부품 목록과 문항 형식을 보여 줍니다'); return 0 if a and a[0] in ('-h', '--help') else 2
    print(catalog(Path(__file__).resolve().parent.parent, a[0] if a else None, md), end=''); return 0


if __name__ == '__main__': sys.exit(main())
