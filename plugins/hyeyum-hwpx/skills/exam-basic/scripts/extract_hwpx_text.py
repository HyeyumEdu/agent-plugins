"""기존 HWPX 시험지의 글을 위에서 아래 순서로 뽑는다(새 서식으로 다시 짤 때 JSON 으로 옮기는 용도).
사용: python3 extract_hwpx_text.py 시험지.hwpx          (표준 라이브러리만, 구형 .hwp 는 읽지 못한다)
표지: [발문 N] 자동 번호 문단, [선택지] ①~⑤ 문단, [표 번호(행×열) r,c] 표 칸 문단, [미주 N] 미주(그 문항의 선택지 뒤에 나온다).
서식: 밑줄 <u>…</u>, 일부만 굵으면 **…**(문단 전체가 굵으면 표시 안 함). 수식은 [수식: …], 그림은 [그림] 자리표시.
shortcut: 표준 XML 파서라 출처를 모르는 파일은 읽지 않는다(사용자가 올린 자기 시험지만)."""
import re, sys, zipfile, zlib
import xml.etree.ElementTree as ET

H = '{http://www.hancom.co.kr/hwpml/2011/head}'
P = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
ln = lambda e: e.tag.rsplit('}', 1)[-1]


def ttext(t):  # hp:t 의 글. <hp:nbSpace/> 같은 자식 요소 뒤의 글(tail)도 읽는다
    return (t.text or '') + ''.join(({'nbSpace': ' ', 'fwSpace': ' ', 'tab': ' ', 'lineBreak': ' '}.get(ln(c), '')) + (c.tail or '') for c in t)


def main(path):
    try:
        z = zipfile.ZipFile(path)
        hd = ET.fromstring(z.read('Contents/header.xml')); secs = sorted((n for n in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n)), key=lambda n: int(re.findall(r'\d+', n)[0]))
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError, zlib.error, RuntimeError, NotImplementedError):
        raise SystemExit('오류: HWPX(zip) 파일이 아니거나 손상되었습니다 — 구형 .hwp 파일이면 한글에서 .hwpx 로 다시 저장해 달라고 안내하세요.')
    numbered = {p.get('id') for p in hd.iter(H + 'paraPr') if p.find(H + 'heading') is not None and p.find(H + 'heading').get('type') == 'NUMBER'}
    bold = {c.get('id') for c in hd.iter(H + 'charPr') if c.find(H + 'bold') is not None}
    ul = {c.get('id') for c in hd.iter(H + 'charPr') if c.find(H + 'underline') is not None and c.find(H + 'underline').get('type') != 'NONE'}
    lost = {'수식': 0, '그림': 0}

    def para_text(p):  # 서식 표기를 넣은 문단 글
        runs = []
        for r in p.findall(P + 'run'):
            s = ''
            for c in r:
                tag = ln(c)
                if tag == 't': s += ttext(c)
                elif tag == 'equation': s += '[수식: ' + ''.join(x.text or '' for x in c.iter(P + 'script')).strip() + ']'; lost['수식'] += 1
                elif tag == 'pic': s += '[그림]'; lost['그림'] += 1
            runs.append((r.get('charPrIDRef'), s))
        withtxt = [(c, s) for c, s in runs if s.strip()]
        allbold = bool(withtxt) and all(c in bold for c, _ in withtxt)
        out = ''
        for c, s in runs:
            if not s: continue
            if c in ul and s.strip(): s = '<u>' + s + '</u>'
            elif c in bold and not allbold and s.strip(): s = '**' + s + '**'
            out += s
        return out

    q = 0; tbl = 0; notes = []

    def flush():
        for line in notes: print(line)
        notes.clear()

    def walk(parent, tag=''):
        nonlocal q, tbl
        for p in parent.findall(P + 'p'):
            t = para_text(p); plain = re.sub(r'</?u>|\*\*', '', t)
            if p.get('paraPrIDRef') in numbered: flush(); q += 1; mark = f'[발문 {q}]'
            elif re.match(r'\s*[①②③④⑤]', plain): mark = '[선택지]'
            else: mark = tag
            if t.strip(): print(f'{mark} {t.strip()}'.strip())
            for e in (x for r in p.findall(P + 'run') for c in r.findall(P + 'ctrl') for x in c.findall(P + 'endNote')):  # 이 문단 자신의 미주만(표 안 문단은 따로 돈다)
                for ep in e.find(P + 'subList').findall(P + 'p'):
                    et = para_text(ep).strip()  # 한 번만 부른다(수식·그림 개수를 센다)
                    if et: notes.append(f'[미주 {e.get("number")}] {et}')
            for tb in (x for r in p.findall(P + 'run') for x in r.findall(P + 'tbl')):  # 이 문단 직속 표만(중첩 표는 칸 안 문단에서 한 번씩)
                tbl += 1; no = tbl
                for tc in tb.findall(P + 'tr/' + P + 'tc'):
                    a = tc.find(P + 'cellAddr'); sub = tc.find(P + 'subList')
                    if sub is not None: walk(sub, f'[표 {no}({tb.get("rowCnt")}×{tb.get("colCnt")}) {a.get("rowAddr")},{a.get("colAddr")}]')

    other = 0
    for name in secs:
        try: root = ET.fromstring(z.read(name))
        except (ET.ParseError, zlib.error, RuntimeError, NotImplementedError, OSError): raise SystemExit(f'오류: {name} 을 읽을 수 없습니다(손상·암호) — 한글에서 다시 저장해 달라고 안내하세요.')
        walk(root)
        other += sum(1 for el in root.iter() if ln(el) in ('rect', 'ellipse', 'line', 'polygon', 'curve', 'container', 'textart', 'header', 'footer', 'footNote'))
    flush()
    if q == 0 and tbl == 0: print('※ 읽을 수 있는 시험 글(발문·표)이 없습니다 — 빈 문서이거나 글이 도형·그림 안에만 있을 수 있습니다.')
    if other: print(f'※ 도형·글상자·머리말·꼬리말·각주 {other}개가 있으나 이 추출기는 읽지 않습니다 — 사용자에게 알리세요.')
    if lost['수식'] or lost['그림']:
        print(f'※ 수식 {lost["수식"]}개·그림 {lost["그림"]}개: 수식은 [수식: …] 자리표시로만 나오고 그림은 읽지 못합니다 — 이 스킬은 둘 다 지원하지 않으니 사용자에게 알리세요.')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] in ('-h', '--help'): raise SystemExit(__doc__.split('\n')[1])
    main(sys.argv[1])
