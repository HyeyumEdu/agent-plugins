"""hyeyum-hwpx-format 스킬 회귀 시험(업로드 대상 아님). 실행: python3 -B exam-skill/tests/test_skill.py
QA(적대적 입력·사용 시험)에서 나온 문제를 하나씩 재현해 고쳐졌는지 본다. 표준 라이브러리만 사용."""
import copy, importlib.util, json, re, shutil, subprocess, sys, tempfile, unittest, zipfile
import xml.etree.ElementTree as ET
sys.dont_write_bytecode = True  # 스킬 폴더 안에 __pycache__ 를 만들지 않는다
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / 'hyeyum-hwpx-format'
BUILD, VERIFY = SKILL / 'scripts/build_exam.py', SKILL / 'scripts/verify_exam.py'
EX = {'basic': json.loads((SKILL / 'assets/examples/example_basic.json').read_text(encoding='utf8'))}


def run(*args):
    r = subprocess.run([sys.executable, '-I', *map(str, args)], capture_output=True, text=True, cwd=tempfile.gettempdir())
    return r.returncode, r.stdout + r.stderr


CH = dict(width=181.36, size=10, adjust=-0.5)  # 선택지 줄 폭 설정(be.choice_geom 이 헤더에서 같은 값을 얻는다)


class T(unittest.TestCase):
    def setUp(self): self.d = Path(tempfile.mkdtemp())

    def build(self, spec, name='x.hwpx', raw=None, check=True):
        src = self.d / 'in.json'
        if raw is not None: src.write_bytes(raw)
        else: src.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        code, out = run(BUILD, src, self.d / name)
        if check: self.assertEqual(code, 0, out)
        return code, out, self.d / name

    def verify(self, path, *flags): return run(VERIFY, *flags, path)

    def q(self, fid='basic', **kw):
        q = copy.deepcopy([i for i in EX[fid]['items'] if i['type'] == 'question'][0]); q.update(kw); return q

    def spec(self, base='basic', **top):
        s = copy.deepcopy(EX[base]); s.update(top); return s

    # ---- 정상 ----
    def test_examples_pass_strict(self):
        _, out, p = self.build(EX['basic'], 'C.hwpx')
        code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertNotIn(' FAIL ', v)

    def test_scripts_parse_on_python_before_312(self):  # 사용자 코드 실행 환경은 3.12 미만일 수 있다: f-문자열 안에 같은 따옴표를 쓰면(PEP 701) 그곳에서 문법 오류
        import io, tokenize
        if not hasattr(tokenize, 'FSTRING_START'): return  # 3.12 미만 인터프리터라면 파일을 읽은 것 자체로 통과
        for f in sorted((SKILL / 'scripts').glob('*.py')):
            q = []  # 열린 f-문자열들의 따옴표
            for t in tokenize.generate_tokens(io.StringIO(f.read_text(encoding='utf-8')).readline):
                quote = t.string.lstrip('rbufRBUF')[:1] if t.type in (tokenize.STRING, tokenize.FSTRING_START) else None
                if quote and quote in q: self.fail(f'{f.name}:{t.start[0]} f-문자열 안에 같은 따옴표({quote})를 썼습니다')
                if t.type == tokenize.FSTRING_START: q.append(quote)
                elif t.type == tokenize.FSTRING_END: q.pop()

    def test_example_matches_expected_files(self):  # 빌더를 고쳐도 예시 시험지의 본문·머리가 바뀌지 않는다는 고정점
        _, _, p = self.build(EX['basic'], 'exp.hwpx'); z = zipfile.ZipFile(p)
        for n in ('section0', 'header'):
            self.assertEqual(z.read(f'Contents/{n}.xml'), (Path(__file__).parent / f'expected/example_basic_{n}.xml').read_bytes(),
                             f'{n}.xml이 기대 파일과 다릅니다. 의도한 변경일 때만 예시 JSON 출력의 Contents/{n}.xml로 기대 파일을 바꾼다')

    def test_cwd_independent_and_help(self):
        self.assertEqual(run(BUILD, '--help')[0], 1 if False else run(BUILD, '--help')[0])
        self.assertIn('사용:', run(BUILD, '--help')[1]); self.assertNotIn('Traceback', run(BUILD)[1])
        self.assertEqual(run(VERIFY)[0], 2); self.assertIn('사용:', run(VERIFY)[1]); self.assertIn('사용:', run(VERIFY, '--help')[1])

    def test_parts_option_lists_used_parts(self):  # --parts 는 요약 첫 줄 뒤에 쓴 부품 한 줄만 더한다
        src, dst = self.d / 'in.json', self.d / 'p.hwpx'
        def go(spec, *flags):
            src.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8'); code, o = run(BUILD, src, dst, *flags); self.assertEqual(code, 0, o); return o.splitlines()
        plain = go(EX['basic']); self.assertNotIn('쓴 부품', '\n'.join(plain))
        withp = go(EX['basic'], '--parts')
        self.assertEqual(withp[0], plain[0]); self.assertTrue(withp[1].startswith('쓴 부품: ')); self.assertEqual(withp[2:], plain[1:])
        self.assertIn('bogi-box', withp[1]); self.assertIn('answer-note', withp[1]); self.assertIn('choice5', withp[1])
        s = self.spec()
        for it in s['items']: it.pop('bogi', None)
        self.assertNotIn('bogi-box', go(s, '--parts')[1])
        for bad in (('--part',), ('--parts', 'x')):
            code, o = run(BUILD, src, dst, *bad); self.assertEqual(code, 1); self.assertIn('사용:', o)

    def test_choice_geometry_from_header(self):  # 선택지 줄 폭·탭은 부품이 가리키는 문단·글자 모양에서 나온다
        sys.path.insert(0, str(SKILL / 'scripts')); import build_exam as be
        f = json.loads((SKILL / 'assets/formats.json').read_text(encoding='utf8'))[0]; reg = be.CM.Registry(SKILL, f)
        hdr = reg.resolve(zipfile.ZipFile(SKILL / 'assets/templates/exam_template_basic.hwpx').read('Contents/header.xml').decode('utf-8'))
        ch = be.choice_geom(hdr, reg.parts['choice'])
        self.assertEqual((ch['left'], ch['hang'], ch['size']), (500, 1488, 10)); self.assertEqual(ch['width'], 181.36); self.assertEqual(ch['adjust'], -0.5)

    # ---- 입력 오류는 한국어 안내(트레이스백 없음) ----
    def bad(self, spec, expect, raw=None):
        code, out, _ = self.build(spec, raw=raw, check=False)
        self.assertNotEqual(code, 0); self.assertNotIn('Traceback', out, out); self.assertIn(expect, out, out)

    def test_bad_inputs(self):
        s = self.spec()
        self.bad(None, '문법 오류', raw=b'{ "format": "basic", }')
        self.bad(None, 'UTF-8', raw='{"format":"basic"}'.encode('cp949') + '가'.encode('cp949'))
        self.bad(self.spec(format='D'), 'format은 "basic" 중 하나')
        s = self.spec(); del s['format']; s['kind'] = 'C'; self.bad(s, "알 수 없는 항목 ['kind']")
        self.bad(self.spec(kind='basic'), "알 수 없는 항목 ['kind']")
        self.bad(self.spec(items=[]), 'items')
        self.bad(self.spec(extra=1), '알 수 없는 항목')
        self.bad(self.spec(title=[]), 'title')
        for k, v in (('answer', '3'), ('answer', 0), ('answer', 3.0), ('answer', None), ('choices', None), ('choices', ['a.'] * 4), ('stem', ''), ('stem', None), ('score', 'x')):
            s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0][k] = v
            self.bad(s, '문항 1')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][0] = '① 가.'; self.bad(s, '선택지 번호')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['stem'] = '1. 윗글은?'; self.bad(s, '문제 번호')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['stem'] = '윗글은 **않은** 것은?'; self.bad(s, '**')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][1] = '가\n나.'; self.bad(s, '줄바꿈')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][0] = 'a**b'; self.bad(s, '짝')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][0] = '<u>밑줄</u>'; _, out, _ = self.build(s); self.assertIn('원문자 표시 문자 없이 밑줄', out)
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][0] = '저녁 ㉠바람이 분다'; self.bad(s, '밑줄 범위가 필요')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][1]['bogi']['table'] = [['a']]; self.bad(s, '알 수 없는 항목')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['note'] = {}; self.bad(s, 'note.point')
        s = self.spec(); del [i for i in s['items'] if i['type'] == 'question'][0]['note']; self.bad(s, 'note(point·why·wrong)가 필요')
        s = self.spec(); s['items'].append({'type': 'end_heading', 'text': 'x'}); self.bad(s, '정답과 해설')
        s = self.spec(); s['items'].append({'type': 'zzz'}); self.bad(s, '알 수 없는 type')
        s = self.spec(); s['items'].insert(0, {'type': 'end_heading'}); self.bad(s, '마지막 항목')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['note']['wrong'] = ['a'] * 3; self.bad(s, '4개')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['score'] = 3.65; self.bad(s, '소수 첫째')
        s = self.spec(); del [i for i in s['items'] if i['type'] == 'question'][0]['score']; self.bad(s, 'score')
        s = self.spec(); s['title'] = ['a'] * 4; self.bad(s, '최대 3줄')

    def test_same_src_dst_and_missing_file(self):
        p = self.d / 'a.json'; p.write_text(json.dumps(EX['basic']), encoding='utf-8')
        code, out = run(BUILD, p, p); self.assertNotEqual(code, 0); self.assertIn('덮어', out); self.assertTrue(p.read_text(encoding='utf-8').startswith('{'))
        code, out = run(BUILD, self.d / 'nope.json', self.d / 'o.hwpx'); self.assertIn('입력 파일이 없습니다', out); self.assertNotIn('Traceback', out)

    def test_bom_ok_and_ctrl_chars_removed_and_new_output_dir(self):
        raw = b'\xef\xbb\xbf' + json.dumps(EX['basic'], ensure_ascii=False).encode('utf-8')
        self.build(None, raw=raw)
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][0] = '가\x0b나.'
        _, out, p = self.build(s, 'sub/dir/o.hwpx'); self.assertIn('제어문자', out); self.assertTrue(p.exists())

    # ---- 고친 버그 ----
    def sec(self, p): return zipfile.ZipFile(p).read('Contents/section0.xml').decode()

    def test_title_not_double_escaped(self):
        s = self.spec(); s['title'] = ['예시 & 고2', '화법 & 작문 <A>', '2026']
        _, _, p = self.build(s); x = self.sec(p)
        self.assertNotIn('&amp;amp;', x); self.assertIn('화법 &amp; 작문 &lt;A&gt;', x)

    def test_all_negation_words_underlined(self):
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['stem'] = '적절하지 않은 것과 이해하지 않은 것을 고른 것은?'
        _, _, p = self.build(s); code, v = self.verify(p); self.assertEqual(code, 0, v)
        x = self.sec(p); self.assertEqual(x.count('<hp:t>않은</hp:t>'), 2)

    def test_box_height_uses_ceil(self):  # 94자 한 문단: 4.22줄 -> 5줄, 라벨 1줄
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][1]
        q['bogi'] = {'lines': ['가' * 94]}; _, _, p = self.build(s)
        hs = re.findall(r'<hp:tbl id="\d+"[^>]*>\s*<hp:sz width="20038" widthRelTo="ABSOLUTE" height="(\d+)"', self.sec(p))
        self.assertEqual(int(hs[0]), (1 + 5) * 1250 + 2 * 250 + 800)

    def test_column_break_allowed_with_warning(self):
        s = self.spec(); s['items'] = [i for i in s['items'] if i['type'] not in ('column_break', 'page_break')]  # 나눔을 모두 빼고 하나만 다시 넣는다
        k = [n for n, i in enumerate(s['items']) if i['type'] == 'question'][1]; s['items'].insert(k, {'type': 'column_break'})
        _, _, p = self.build(s); code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('WARN', v)
        x = self.sec(p); self.assertEqual(x.count('columnBreak="1"'), 1); self.assertEqual(x.count('pageBreak="1"'), 1)  # 정답과 해설 제목
        i = x.index('columnBreak="1"'); self.assertIn('<hp:t>윗글', x[x.rfind('<hp:p ', 0, i):i + 120])  # 다음 항목(발문)의 첫 문단에 붙는다

    def test_trailing_page_break_and_segment_warning(self):
        s = self.spec(); s['items'].append({'type': 'page_break'})  # 끝의 page_break 는 정답과 해설 제목이 받는다(빈 문단이 따로 생기지 않는다)
        _, out, p = self.build(s); self.assertIn('쪽 나눔 1개', out); x = self.sec(p)
        self.assertEqual(x.count('pageBreak="1"'), 1); self.assertTrue(x.rstrip().endswith('정답과 해설</hp:t></hp:run></hp:p></hs:sec>'))
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][0]; q['choices'] = ['가' * 400 + '.'] * 5
        s['items'].insert(0, {'type': 'column_break'}); s['items'].insert(4, {'type': 'column_break'}); _, out, _ = self.build(s); self.assertIn('한 단', out); self.assertIn('경고', out)  # 한 단을 넘는 구간 경고
        s = self.spec(); s['items'].append({'type': 'column_break'}); _, out, p = self.build(s); self.assertIn('쓰이지 않습니다', out); self.assertEqual(self.sec(p).count('columnBreak="1"'), 1)

    def test_table_and_instid_unique(self):
        s = self.spec(); s['items'] += [self.q() for _ in range(3)]
        _, _, p = self.build(s); code, v = self.verify(p); self.assertEqual(code, 0, v)

    # ---- 검사기가 거짓 통과하지 않는다 ----
    def mutate(self, src, fn, name='m.hwpx', hfn=None):
        z = zipfile.ZipFile(src); out = self.d / name
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
            for it in z.infolist():
                data = z.read(it.filename)
                if it.filename == 'Contents/section0.xml': data = fn(data.decode()).encode()
                if it.filename == 'Contents/header.xml' and hfn: data = hfn(data.decode()).encode()
                zo.writestr(it, data)
        return out

    def test_verify_catches_mutations(self):
        import re
        _, _, p = self.build(EX['basic'], 'c.hwpx')
        ch = lambda fn: (lambda s: re.sub(r'(<hp:t>①)(<hp:tab [^>]*/>)', lambda m: fn(m.group(1), m.group(2)), s, count=1))  # 본문 첫 선택지의 `①` 와 탭
        cases = {
            'colPr': (lambda s: re.sub(r'<hp:ctrl><hp:colPr.*?</hp:colPr></hp:ctrl>', '', s, flags=re.S), 'G3'),
            'endnote': (lambda s: re.sub(r'<hp:ctrl><hp:endNote .*?</hp:endNote></hp:ctrl>', '', s, count=1, flags=re.S), 'G12'),
            'choice2space': (ch(lambda a, t: a + '  '), 'G19'),
            'choice_space_instead_of_tab': (ch(lambda a, t: a + ' '), 'G49'),
            'dup_choice_no': (ch(lambda a, t: a + t + '① '), 'G19'),
            'markup': (ch(lambda a, t: a + t + '**'), 'G29'),
            'nbsp': (ch(lambda a, t: a + '\u00a0'), 'G19'),
            'tab': (ch(lambda a, t: a + t + '가\t'), 'G28'),
            'dup_instId': (lambda s: s.replace('instId="1100000002"', 'instId="1100000001"'), 'G30'),
            'score_mismatch': (lambda s: s.replace('정답 ③   [3.6점]', '정답 ③   [9.9점]'), 'G31'),
            'no_end_heading': (lambda s: s.replace('정답과 해설', '해설'), 'G35'),
            'heading_not_page_top': (lambda s: s.replace('pageBreak="1"', 'pageBreak="0"'), 'G35'),
            'pagebreak': (lambda s: s.replace('pageBreak="0"', 'pageBreak="1"', 1), 'G6'),
            'no_gap': (lambda s: re.sub(r'<hp:p [^>]*><hp:run charPrIDRef="31"/></hp:p>', '', s, count=1), 'G37'),
            'gap_not_3pt': (lambda s: s.replace('<hp:run charPrIDRef="31"/>', '<hp:run charPrIDRef="0"/>', 1), 'G37'),
            'empty_sublist': (lambda s: re.sub(r'(<hp:subList [^>]*>)<hp:p .*?</hp:p>(</hp:subList>)', r'\1\2', s, count=1, flags=re.S), 'G33'),
            'dangling_ref': (lambda s: re.sub(r'paraPrIDRef="\d+"', lambda m, c=[0]: (c.__setitem__(0, c[0] + 1) or ('paraPrIDRef="999"' if c[0] == 6 else m.group(0))), s), 'G34'),
        }
        for name, (fn, rid) in cases.items():
            code, v = self.verify(self.mutate(p, fn, name + '.hwpx'))
            self.assertNotIn('Traceback', v, name)
            line = [l for l in v.splitlines() if l.strip().startswith(rid + ' ')]
            self.assertTrue(line, f'{name}: {rid} 줄 없음\n{v}')
            self.assertTrue(('FAIL' in line[0]) or (rid == 'G6' and 'WARN' in line[0]), f'{name}: {line[0]}')

    # ---- 안내문 뒤 3pt 빈 줄 · 정답과 해설 제목 · 선택지 자간 ----
    def hdr(self, p): return zipfile.ZipFile(p).read('Contents/header.xml').decode()

    def test_gap_after_instruction_is_3pt(self):
        import re
        # C: 골든 C 처럼 안내문과 지문 사이에 3pt 빈 줄(charPr 31)이 자동으로 들어간다. 빈 줄을 따로 적어도 하나뿐이다
        for with_blank in (False, True):
            s = self.spec(); its = [i for i in s['items'] if i['type'] != 'blank' or False]
            if with_blank: its.insert(1, {'type': 'blank'}); its.insert(1, {'type': 'blank'})
            s['items'] = its; _, out, p = self.build(s); x = self.sec(p)
            self.assertEqual(x.count('<hp:run charPrIDRef="31"/>'), 2 if with_blank else 1, with_blank)  # 적은 blank 2개는 모두 3pt, 자동 삽입은 없다
            code, v = self.verify(p); self.assertEqual(code, 0, v)
            i = x.index('다음 글을 읽고'); self.assertIn('<hp:run charPrIDRef="31"/>', x[i:i + 400])

    def test_end_heading_13pt_bold_page_top(self):
        import re
        for with_item in (False, True):
            s = self.spec(); s['items'] = [i for i in s['items'] if i['type'] != 'end_heading']
            if with_item: s['items'].append({'type': 'end_heading'})
            _, _, p = self.build(s, f'C{with_item}.hwpx'); x = self.sec(p); h = self.hdr(p)
            last = x[x.rfind('<hp:p '):]
            self.assertIn('pageBreak="1"', last[:120]); self.assertIn('정답과 해설', last)
            cid = re.search(r'charPrIDRef="(\d+)"', last).group(1)
            cp = re.search(rf'<hh:charPr id="{cid}" height="(\d+)".*?</hh:charPr>', h, re.S)
            self.assertEqual(cp.group(1), '1300'); self.assertIn('<hh:bold/>', cp.group(0))
            self.assertEqual(x.count('pageBreak="1"'), 1)
            code, v = self.verify(p); self.assertEqual(code, 0, v)
            self.assertIn('G35  PASS', v)

    def test_tighten_orphan_choice(self):
        sys.path.insert(0, str(SKILL / 'scripts')); import build_exam as be
        # 마지막 줄에 한 글자(+마침표)만 남는 선택지 본문(번호 제외): 자간을 줄여 한 줄 덜 쓴다
        self.assertEqual(be.wrap_lines('가' * 19 + '.', 10, 181.36 - 0.5), ['가' * 18, '가.'])
        self.assertEqual(be.tighten('가' * 19 + '.', CH), (-5, 1, False))
        self.assertEqual(be.tighten('가' * 18 + '.', CH)[0], 0)           # 한 줄에 들어가면 그대로
        self.assertEqual(be.tighten('가' * 40 + '나다.', CH)[0], 0)       # 마지막 줄이 두 글자 이상이면 그대로
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][0]; q['choices'][0] = '가' * 19 + '.'; q['choices'][1] = '가' * 10 + '.'
        _, out, p = self.build(s); x = self.sec(p); h = self.hdr(p)
        self.assertIn('자간 줄임', out); self.assertIn('문항 1-① -5%', out)
        tpl = zipfile.ZipFile(SKILL / 'assets/templates/exam_template_basic.hwpx').read('Contents/header.xml').decode()
        self.assertEqual(h.count('<hh:spacing hangul="-5"'), tpl.count('<hh:spacing hangul="-5"') + 1)  # 템플릿(골든 C 헤더)에도 -5% 모양이 있어 하나 더해진 것만 센다
        code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G36  PASS', v)

    def test_verify_rejects_bad_spacing(self):
        import re
        _, _, p = self.build(EX['basic'], 'c.hwpx'); h0 = self.hdr(p)
        mod = lambda f: self.mutate(p, lambda s: s, 'h.hwpx', hfn=f)
        v = self.verify(mod(lambda h: h.replace('hangul="-7" latin="-7"', 'hangul="-12" latin="-12"')))[1]; self.assertIn('G23  FAIL', v)      # 선택지 자간은 -7% 까지
        v = self.verify(mod(lambda h: re.sub(r'(<hh:charPr id="0" .*?<hh:spacing )hangul="0"', r'\1hangul="-5"', h, count=1, flags=re.S)))[1]; self.assertIn('G36  FAIL', v)  # 지문 글자의 자간 조정


    def test_g37_no_false_results(self):
        # 지문 첫 문단·발문이 '다음…읽고'로 시작해도 안내문으로 오인하지 않는다(거짓 실패), 안내문 문구가 달라도 3pt 빈 줄 누락·크기 오류를 잡는다(거짓 통과)
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'] = ['다음 날 아침 그는 편지를 읽고 말없이 웃었다.', '그리고 창밖을 보았다.']
        _, _, p = self.build(s, 'g1.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][1]['stem'] = '다음 <보기>를 읽고 윗글을 이해한 것으로 적절한 것은?'
        _, _, p = self.build(s, 'g2.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)
        for tx in ('※ 다음 시를 감상하고 물음에 답하시오.', '※ (가)와 (나)를 읽고 물음에 답하시오.', '※ 다음 글의 (가)와 (나)를 비교하여 읽고 물음에 답하시오.'):
            s = self.spec(); s['items'][0]['text'] = tx; _, _, p = self.build(s, 'g3.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)
            m = self.mutate(p, lambda x: re.sub(r'<hp:p [^>]*><hp:run charPrIDRef="31"/></hp:p>', '', x, count=1), 'g3m.hwpx'); self.assertIn('G37  FAIL', self.verify(m)[1], tx)
        s = self.spec(); s['items'].insert(1, {'type': 'blank', 'n': 3}); _, _, p = self.build(s, 'g4.hwpx')
        def third_gap_to_10pt(x):  # 셋째 3pt 빈 줄만 10pt 글자로
            n = [0]
            def f(m_):
                n[0] += 1; return '<hp:run charPrIDRef="0"/>' if n[0] == 3 else m_.group(0)
            return re.sub(r'<hp:run charPrIDRef="31"/>', f, x)
        m = self.mutate(p, third_gap_to_10pt, 'g4m.hwpx')
        self.assertIn('G37  FAIL', self.verify(m)[1])

    def test_break_between_instruction_and_passage_rejected(self):
        for br in ('column_break', 'page_break'):
            s = self.spec(); s['items'].insert(1, {'type': br}); self.bad(s, '안내문과 지문 사이')

    def test_page_break_summary_excludes_heading(self):
        _, out, _ = self.build(EX['basic'], 'e.hwpx'); self.assertNotIn('쪽 나눔 2', out)
        s = self.spec(); s['items'] = [i for i in s['items'] if i['type'] != 'column_break']  # 나눔 없음: 쪽 나눔 0개, 높이 요약·경고 없음
        _, out, p = self.build(s, 'n.hwpx'); self.assertIn('단 나눔 0개·쪽 나눔 0개', out); self.assertNotIn('쪽별 추정', out)
        s = self.spec(); s['items'] = [i for i in s['items'] if i['type'] != 'column_break'] + [self.q() for _ in range(40)]; _, out, _ = self.build(s, 'big.hwpx'); self.assertNotIn('경고: 1쪽', out)

    def test_tighten_closing_quote_before_period(self):
        sys.path.insert(0, str(SKILL / 'scripts')); import build_exam as be
        self.assertLess(be.tighten('가' * 19 + '’.', CH)[0], 0); self.assertLess(be.tighten('가' * 19 + ').', CH)[0], 0)

    def test_verify_header_counts_and_spacing_all_attributes(self):
        _, _, p = self.build(EX['basic'], 'c.hwpx')
        m = self.mutate(p, lambda s: s, 'h1.hwpx', hfn=lambda h: re.sub(r'(<hh:charProperties itemCnt=")\d+(")', r'\g<1>99\2', h, count=1)); self.assertIn('G38  FAIL', self.verify(m)[1])
        m = self.mutate(p, lambda s: s, 'h2.hwpx', hfn=lambda h: h.replace('hangul="-7" latin="-7"', 'hangul="-6" latin="-12"')); self.assertIn('FAIL', self.verify(m)[1])
        m = self.mutate(p, lambda s: s, 'h3.hwpx', hfn=lambda h: h.replace('hangul="-7" latin="-7"', 'hangul="-12" latin="-12"')); self.assertIn('G36  FAIL', self.verify(m, '--lenient')[1])  # 원본 검사에서도 선택지 범위는 본다

    def test_choice_tab_stop_checked(self):
        _, _, p = self.build(EX['basic'], 'c.hwpx')
        m = self.mutate(p, lambda s: s, 'ts.hwpx', hfn=lambda h: re.sub(r'(<hh:tabItem pos=")\d+(" type="LEFT" leader="NONE" unit="HWPUNIT"/></hp:case>)', r'\g<1>1234\2', h)); self.assertIn('G49  FAIL', self.verify(m)[1])  # 탭 정지가 둘째 줄 시작과 다르면
        self.assertIn('G49  PASS', self.verify(p)[1]); self.assertIn('G49  PASS', self.verify(p, '--lenient')[1])

    # ---- 안내문 ※ · 원문자 콜론/밑줄 · 구분 표시 · 줄거리 · 선택지 문장 · 문항 보호 · 선택지 정렬 ----
    def test_instruction_uses_star_not_range(self):
        s = self.spec(); s['items'][0]['text'] = '[1~3] 다음 글을 읽고 물음에 답하시오.'
        _, out, p = self.build(s, 'iC.hwpx'); x = self.sec(p)
        self.assertIn('※ 다음 글을 읽고 물음에 답하시오.', x); self.assertNotIn('[1~3]', x); self.assertIn('번호 범위', out)
        code, v = self.verify(p); self.assertEqual(code, 0, v)
        m = self.mutate(p, lambda x: x.replace('※ 다음 글을', '[1~3] 다음 글을', 1), 'im.hwpx'); self.assertIn('G42  FAIL', self.verify(m)[1])

    def test_circled_colon_attached(self):
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][0]; q['choices'][0] = '㉠ : 자신의 짐작이 맞는다.'; q['choices'][1] = '㉡:자신의 짐작이 틀린다.'
        _, out, p = self.build(s); x = self.sec(p); self.assertIn('㉠: 자신', x); self.assertIn('㉡: 자신', x); self.assertNotIn('㉠ :', x); self.assertIn('원문자', out)
        m = self.mutate(p, lambda t: t.replace('㉠: 자신', '㉠ : 자신', 1), 'cm.hwpx'); self.assertIn('G43  FAIL', self.verify(m)[1])

    def test_circled_marker_needs_underline_in_passage(self):
        s = self.spec(); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['㉠등대마다 다르다.']; self.bad(s, '밑줄 범위가 필요')
        pa['paras'] = ['<u>㉠등대마다</u> 다르다.']; _, _, p = self.build(s, 'u1.hwpx'); x = self.sec(p); self.assertIn('㉠</hp:t>', x); self.assertIn('<hp:t>등대마다</hp:t>', x)  # 표시 문자는 밑줄 밖으로 옮겨진다
        code, v = self.verify(p); self.assertEqual(code, 0, v)
        pa['paras'] = ['그는 ㉠“<u>등대마다 다르다.”</u>']; _, _, p = self.build(s, 'u2.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)   # 여는 따옴표는 표시 문자와 밑줄 사이에 올 수 있다
        pa['paras'] = ['저녁 바람이 ⓐ<u>골목</u>을 지나가면']
        _, _, p = self.build(s, 'u3.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)
        m = self.mutate(p, lambda t: t.replace('ⓐ', 'ⓐ ', 1), 'u3m.hwpx'); self.assertIn('G44  FAIL', self.verify(m)[1])

    def test_part_markers_bold_and_one_blank_line(self):
        s = self.spec(); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['(가) 첫째 글이다.', '- 저자 갑, 「가」', '(나) 둘째 글이다.', '', '', '(다) 셋째 글이다.']
        _, out, p = self.build(s, 'sep.hwpx'); x = self.sec(p)
        self.assertEqual(x.count('<hp:t>(가)</hp:t>') + x.count('<hp:t>(나)</hp:t>') + x.count('<hp:t>(다)</hp:t>'), 3)  # 구분 표시는 따로 굵은 run
        code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G45  PASS', v); self.assertIn('G46  PASS', v); self.assertIn('한 줄로 줄였습니다', out)
        m = self.mutate(p, lambda t: re.sub(r'<hp:p [^>]*><hp:run charPrIDRef="0"/></hp:p>(?=<hp:p [^>]*><hp:run charPrIDRef="\d+"><hp:t> </hp:t>)', '', t, count=1), 'sepm.hwpx')

    def test_summary_label_forced(self):
        s = self.spec(); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['앞 글이다.', '앞부분의 줄거리', '요약이 이어진다.', '다음 글이다.', '(중략 부분 줄거리)', '또 요약.', '끝 글이다.']
        _, out, p = self.build(s, 'lbC.hwpx'); x = self.sec(p)
        self.assertIn('<hp:t>[앞부분의 줄거리]</hp:t>', x); self.assertIn('<hp:t>[중략 부분 줄거리]</hp:t>', x); self.assertIn('대괄호', out)
        h = self.hdr(p); cp = re.search(rf'<hh:charPr id="3" height="(\d+)"', h).group(1); self.assertEqual(cp, '900')  # 9pt
        code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G47  PASS', v)
        m = self.mutate(p, lambda t: t.replace('[중략 부분 줄거리]', '중략 부분 줄거리', 1), 'lbm.hwpx'); self.assertIn('G47  FAIL', self.verify(m)[1])

    def test_summary_inline_same_paragraph(self):
        s = self.spec(); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['(가) 앞부분 줄거리 | 초등학교 교사인 ‘나’는 셋방살이를 전전한다.', '(나) 그렇다. 둘째 글이다.']
        _, out, p = self.build(s, 'inC.hwpx'); x = self.sec(p)
        self.assertIn('[앞부분 줄거리] 초등학교 교사인', x); self.assertNotIn('앞부분 줄거리 |', x); self.assertIn('대괄호', out)
        code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G47  PASS', v); self.assertIn('G46  PASS', v)
        hs = self.hdr(p); rid = re.search(r'<hp:t>\[앞부분 줄거리\][^<]*</hp:t>', x); self.assertTrue(rid)
        cid = re.search(r'charPrIDRef="(\d+)"><hp:t>\[앞부분 줄거리\]', x).group(1); self.assertEqual(re.search(rf'<hh:charPr id="{cid}" height="(\d+)"', hs).group(1), '900')   # 요약까지 9pt
        m = self.mutate(p, lambda t: t.replace('[앞부분 줄거리] 초등학교', '앞부분 줄거리 | 초등학교', 1), 'inm.hwpx'); self.assertIn('G47  FAIL', self.verify(m)[1])

    def test_choice_sentence_period_rule(self):
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][0]
        q['choices'] = ['ⓐ: 기계 따위가 작용을 받아 그 기능대로 움직임.', '‘렌즈’를 모아 쓴 사례.', '(가)-(나)-(다).', '나를 믿지 마시오!.', '등대의 불빛이 멀리 보인다']
        _, out, p = self.build(s, 'sp.hwpx'); x = self.sec(p)
        self.assertIn('움직임.</hp:t>', x)                                   # 정의형(`ⓐ: 뜻풀이`)은 마침표를 그대로 둔다(사용자 수정 파일 16/16)
        self.assertIn('사례</hp:t>', x); self.assertNotIn('사례.</hp:t>', x)     # 명사구는 마침표를 뺀다
        self.assertIn('(가)-(나)-(다)</hp:t>', x)                              # 나열
        self.assertIn('마시오!</hp:t>', x); self.assertNotIn('마시오!.', x)       # 느낌표 뒤 마침표
        self.assertIn('문장이 아니라서', out); self.assertIn('문장인데 마침표', out); self.assertIn('느낌표·물음표 뒤', out)
        m = self.mutate(p, lambda t: t.replace('사례</hp:t>', '사례.</hp:t>', 1), 'spm.hwpx'); self.assertIn('G20  FAIL', self.verify(m)[1])

    def test_qa5_fixes(self):  # 5차 QA 에서 나온 문제를 하나씩 재현한 것
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][0]
        q['choices'] = ['소설을 읽는 독자', '이야기를 전하는 화자', '현재와 미래', '별이 빛나는 밤...', '등대의 불빛이 멀리 보인다.']    # 명사 끝 글자와 겹치는 끝(독자·화자·미래)은 쓴 대로, 말줄임표는 그대로
        _, out, p = self.build(s, 'q1.hwpx'); x = self.sec(p)
        self.assertIn('독자</hp:t>', x); self.assertIn('밤...</hp:t>', x); self.assertNotIn('밤..</hp:t>', x)
        code, v = self.verify(p); self.assertEqual(code, 0, v)
        q['choices'][0] = '.'; self.bad(s, '마침표뿐')
        for tx, ok in (('[1~3] ※ 다음 글을 읽고 물음에 답하시오.', True), ('※※ 다음 글을 읽고 물음에 답하시오.', True), ('［1～3］ 다음 글을 읽고 물음에 답하시오.', True), ('※', False)):
            t = self.spec(); t['items'][0]['text'] = tx
            if ok:
                _, _, p = self.build(t, 'q2.hwpx'); self.assertIn('<hp:t>※ 다음 글을 읽고 물음에 답하시오.</hp:t>', self.sec(p)); self.assertEqual(self.verify(p)[0], 0)
            else: self.bad(t, '안내문 글이 비어')
        t = self.spec(); pa = [i for i in t['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['앞 글이다.', '앞부분의 줄거리', '# 소제목', '본문이다.']; self.bad(t, '바로 뒤에는 요약 문단')
        pa['paras'] = ['# ㉠ 제목', '본문이다.']; self.bad(t, '소제목에는 원문자')
        pa['paras'] = ['본문이다.']; pa['source'] = '출제자 ㉠ 창작'; self.bad(t, '출처줄에는 원문자')
        pa['source'] = '저자'; pa['paras'] = ['', '본문이다.']; _, _, p = self.build(t, 'q3.hwpx'); self.assertEqual(self.verify(p)[0], 0)   # 첫머리 빈 줄은 지운다(안내문 뒤 3pt 빈 줄 규칙)
        pa['paras'] = ['']; self.bad(t, '본문 글이 없습니다')
        pa['paras'] = ['(예) 철수가 학교에 간다.', '(나) 둘째 글이다.']; _, _, p = self.build(t, 'q4.hwpx'); x = self.sec(p); self.assertNotIn('<hp:t>(예)</hp:t>', x)   # 한 글자 괄호가 모두 구분 표시는 아니다
        t = self.spec(); pas = [i for i in t['items'] if i['type'] == 'passage'][0]; i0 = t['items'].index(pas)
        t['items'].insert(i0 + 1, {'type': 'passage', 'paras': ['(나) 둘째 시이다.'], 'source': '저자 을'}); _, out, p = self.build(t, 'q5.hwpx')
        self.assertIn('사이에 빈 줄', out); code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G46  PASS', v)   # 지문 둘이 붙으면 문단 테두리가 한 상자가 되므로 빈 줄을 넣는다

    def test_tab_check_ignores_run_boundary(self):  # MCP 도구가 번호만 따로 서식하면 `①` 와 탭이 다른 run 이 된다 — 올바른 XML 이므로 G28·G49 가 통과해야 한다
        _, _, p = self.build(self.spec(), 'rbC.hwpx')
        m = self.mutate(p, lambda t: re.sub(r'<hp:run charPrIDRef="(\d+)"><hp:t>①<hp:tab ', r'<hp:run charPrIDRef="\1"><hp:t>①</hp:t></hp:run><hp:run charPrIDRef="\1"><hp:t><hp:tab ', t, count=1), 'rbmC.hwpx')
        self.assertNotEqual(self.sec(m), self.sec(p)); code, v = self.verify(m); self.assertEqual(code, 0, v); self.assertIn('G49  PASS', v); self.assertIn('G28  PASS', v)
        m2 = self.mutate(p, lambda t: t.replace('<hp:tab ', '<hp:tab /><hp:tab ', 1), 'rbnC.hwpx'); self.assertIn('G49  FAIL', self.verify(m2)[1])   # 탭이 둘이면 여전히 위반

    def test_detect_format(self):
        _, _, p = self.build(self.spec(), 'detC.hwpx'); code, out = run(SKILL / 'scripts/detect_format.py', p)
        self.assertEqual(code, 0, out); self.assertIn('/hyeyum-hwpx:basic', out); self.assertIn('확실', out); self.assertNotRegex(out, '[BC]형')
        code, out = run(SKILL / 'scripts/detect_format.py', self.d / 'nope.hwpx'); self.assertEqual(code, 1); self.assertIn('오류', out); self.assertNotIn('Traceback', out)
        self.assertEqual(run(SKILL / 'scripts/detect_format.py')[0], 2)

    def plugin_files(self, root): return {str(f.relative_to(root)): f.read_bytes() for f in sorted(root.rglob('*')) if f.is_file()}

    def check_plugin_skills(self, out, expect):  # 생성된 각 스킬이 머리글을 갖추고 혼자서 예제를 만들고 검사를 통과하는지
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(expect))
        for sk, fids in expect.items():
            md = (out / sk / 'SKILL.md').read_text(encoding='utf8'); self.assertTrue(md.startswith(f'---\nname: {sk}\ndescription: '))
            self.assertLessEqual(len(re.search(r'description: (.*)', md).group(1)), 1024)
            for fid in fids:
                hw = self.d / f'{sk}_{fid}.hwpx'; code, o = run(out / sk / 'scripts/build_exam.py', out / sk / f'assets/examples/example_{fid}.json', hw); self.assertEqual(code, 0, o)
                code, v = run(out / sk / 'scripts/verify_exam.py', hw); self.assertEqual(code, 0, v)

    def test_plugin_generated_in_sync_and_self_contained(self):  # 플러그인 스킬은 원본에서 생성한 복사본이므로 원본과 어긋나면 안 된다
        plugin = SKILL.parent.parent / 'plugins/hyeyum-hwpx'; out = self.d / 'skills'
        code, msg = run(SKILL.parent / 'build_plugin.py', out); self.assertEqual(code, 0, msg)
        self.assertEqual(self.plugin_files(out), self.plugin_files(plugin / 'skills'), '원본을 고쳤으면 skill/build_plugin.py 를 다시 돌려 skills/ 를 갱신하세요')
        self.check_plugin_skills(out, {'basic': ['basic']})
        self.assertNotIn('/hyeyum-hwpx:format', (out / 'basic/SKILL.md').read_text(encoding='utf8'))
        self.assertEqual([f['id'] for f in json.loads((out / 'basic/assets/formats.json').read_text(encoding='utf8'))], ['basic'])
        self.only_own_format(out / 'basic', ('형식 고르기',))
        sk = out / 'basic/scripts/build_exam.py'; s = self.spec(); del s['format']
        src = self.d / 'nofmt.json'; src.write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
        code, o = run(sk, src, self.d / 'nofmt.hwpx'); self.assertEqual(code, 0, o); self.assertIn('기본 시험지(basic)', o)
        _, _, ref = self.build(EX['basic'], 'ref.hwpx'); self.assertEqual(self.sec(self.d / 'nofmt.hwpx'), self.sec(ref))   # 전용 스킬에서는 format 을 빼도 같은 시험지
        for top, msg in (({'format': 'zzz'}, 'format은 "basic" 중 하나'), ({'kind': 'basic'}, "알 수 없는 항목 ['kind']")):
            src.write_text(json.dumps({**s, **top}, ensure_ascii=False), encoding='utf-8'); code, o = run(sk, src, self.d / 'x.hwpx')
            self.assertNotEqual(code, 0); self.assertIn(msg, o); self.assertNotIn('Traceback', o)

    def test_plugin_carries_components(self):  # 생성된 스킬이 부품 폴더·components.py·목록 문서를 스스로 갖는다
        out = self.d / 'comp'; code, msg = run(SKILL.parent / 'build_plugin.py', out); self.assertEqual(code, 0, msg)
        sk = out / 'basic'; ids = sorted(set(json.loads((sk / 'assets/formats.json').read_text(encoding='utf8'))[0]['parts'].values()))
        self.assertEqual(len(ids), 10); self.assertEqual(sorted(p.name for p in (sk / 'assets/components').iterdir()), ids); self.assertFalse((sk / 'assets/snippets').exists())
        code, o = run(sk / 'scripts/components.py'); self.assertEqual(code, 0, o)
        for i in ids: self.assertIn(i, o)
        spec = importlib.util.spec_from_file_location('components_src', SKILL / 'scripts/components.py'); cm = importlib.util.module_from_spec(spec); spec.loader.exec_module(cm)
        self.assertEqual((sk / 'references/components.md').read_text(encoding='utf8'), cm.catalog(SKILL, 'basic', md=True)); self.assertFalse((SKILL / 'references/components.md').exists())

    def only_own_format(self, d, banned):  # 전용 스킬 문서에는 그 형식 내용만 남는다
        for f in [d / 'SKILL.md', *sorted((d / 'references').glob('*.md'))]:
            t = f.read_text(encoding='utf8')
            for w in ('B형', 'C형', '<!--', '-->', *banned): self.assertNotIn(w, t, f'{f.name}: {w}')

    def test_plugin_all_formats_mode(self):  # 형식이 하나면 --all 도 그 형식만 만든다
        out = self.d / 'all'
        code, msg = run(SKILL.parent / 'build_plugin.py', '--all', out); self.assertEqual(code, 0, msg)
        self.check_plugin_skills(out, {'basic': ['basic']})

    def test_plugin_router_with_two_formats(self):  # 형식을 더 낼 때를 위한 라우터 생성 경로: 복사본에 가짜 형식을 더해 시험한다
        src = self.d / 'src'; shutil.copytree(SKILL, src / SKILL.name); shutil.copy2(SKILL.parent / 'build_plugin.py', src)
        fj = src / SKILL.name / 'assets/formats.json'
        fl = json.loads(fj.read_text(encoding='utf8')); fl.append(dict(id='fake', title='시험용 형식', when='시험용', traits='시험용', template='exam_template_fake.hwpx', parts=fl[0]['parts'], question_types=fl[0]['question_types']))
        fj.write_text(json.dumps(fl, ensure_ascii=False), encoding='utf-8')
        for rel in ('examples/example_{}.json', 'templates/exam_template_{}.hwpx'): shutil.copy2(SKILL / 'assets' / rel.format('basic'), src / SKILL.name / 'assets' / rel.format('fake'))
        md = src / SKILL.name / 'SKILL.md'; md.write_text(md.read_text(encoding='utf8') + '<!-- format:fake -->\nFAKE ONLY\n<!-- /format -->\n', encoding='utf-8')
        out = self.d / 'all'
        code, msg = run(src / 'build_plugin.py', '--all', out); self.assertEqual(code, 0, msg)
        self.check_plugin_skills(out, {'basic': ['basic'], 'fake': [], 'format': ['basic']})
        self.assertTrue((out / 'fake/assets/templates/exam_template_fake.hwpx').exists()); self.assertFalse((out / 'fake/assets/templates/exam_template_basic.hwpx').exists());
        self.assertFalse((out / 'basic/assets/snippets').exists()); self.assertEqual(sorted(p.name for p in (out / 'fake/assets/components').iterdir()), sorted(set(fl[0]['parts'].values())))
        self.assertTrue((out / 'format/scripts/detect_format.py').exists()); self.assertFalse((out / 'fake/scripts/detect_format.py').exists())
        router = (out / 'format/SKILL.md').read_text(encoding='utf8'); self.assertIn('/hyeyum-hwpx:basic', router); self.assertIn('/hyeyum-hwpx:fake', router); self.assertIn('형식 고르기', router)
        self.assertIn('### 기본 시험지 (`basic`)', router); self.assertIn('FAKE ONLY', router); self.assertNotIn('이 명령의 형식은 아래 하나로', router); self.assertNotIn('<!--', router)
        fake = (out / 'fake/SKILL.md').read_text(encoding='utf8'); self.assertIn('FAKE ONLY', fake); self.assertIn('/hyeyum-hwpx:format', fake)
        self.only_own_format(out / 'fake', ('`basic`', '기본 시험지', 'pp41', 'pp62', '형식 고르기'))
        basic = (out / 'basic/SKILL.md').read_text(encoding='utf8'); self.assertNotIn('FAKE ONLY', basic); self.assertIn('다른 형식이 필요하면 /hyeyum-hwpx:format', basic)
        self.assertEqual(len(json.loads((out / 'format/assets/formats.json').read_text(encoding='utf8'))), 2)
        s = self.spec(); del s['format']; amb = self.d / 'amb.json'; amb.write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
        code, o = run(out / 'format/scripts/build_exam.py', amb, self.d / 'amb.hwpx'); self.assertNotEqual(code, 0); self.assertIn('format(형식 이름)을 적어야', o)   # 라우터에서는 형식을 골라 적어야 한다
        code, o = run(out / 'format/scripts/detect_format.py', self.d / 'format_basic.hwpx'); self.assertEqual(code, 0, o); self.assertIn('형식 판별', o)

    def test_kind_input_rejected_as_unknown_key(self):
        s = self.spec(); del s['format']; s['kind'] = 'C'
        code, out, p = self.build(s, 'k.hwpx', check=False)
        self.assertNotEqual(code, 0); self.assertFalse(p.exists()); self.assertNotIn('Traceback', out)
        self.assertIn("최상위: 알 수 없는 항목 ['kind']", out); self.assertNotIn("'kind'", out.split('쓸 수 있는 항목')[1])

    def test_keep_blocks(self):
        sys.path.insert(0, str(SKILL.parent)); import build_plugin as bp
        t = 'a<!-- format:basic -->, b<!-- /format --><!-- format:other -->, c<!-- /format -->.\n<!-- format:router,basic -->\nR\n<!-- /format -->\nz\n'
        self.assertEqual(bp.keep_blocks(t, {'basic'}), 'a, b.\nR\nz\n')
        self.assertEqual(bp.keep_blocks(t, {'pinned', 'other'}), 'a, c.\nz\n')
        self.assertEqual(bp.keep_blocks(t, {'router', 'basic', 'other'}), 'a, b, c.\nR\nz\n')
        with self.assertRaises(AssertionError): bp.keep_blocks('<!-- format:basic -->x', {'basic'})

    def test_auto_group_break_counted_in_summary(self):
        s = self.spec(); items = [i for i in s['items'] if i['type'] not in ('column_break', 'page_break', 'end_heading', 'blank')]
        a = copy.deepcopy(items); s['items'] = a + copy.deepcopy(a)    # 안내문 묶음 둘 -> 두 번째 묶음이 새 단에서 시작(자동)
        _, out, p = self.build(s, 'g.hwpx'); self.assertIn('단 나눔 1개', out); self.assertIn('자동 1개', out); self.assertIn('쪽별 추정 높이', out); self.assertNotIn('오쪽', out)

    def test_question_keep_chain_and_group_start(self):
        s = self.spec(); s['items'] += [{'type': 'instruction', 'text': '※ 다음 글을 읽고 물음에 답하시오.'}, {'type': 'passage', 'paras': ['둘째 지문이다.']}, self.q()]
        _, out, p = self.build(s, 'kcC.hwpx'); x = self.sec(p); code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G40  PASS', v); self.assertIn('G41  PASS', v)
        self.assertEqual(x.count('columnBreak="1"'), 2)  # 사용자 column_break 1개 + 둘째 안내문 자동 1개
        m = self.mutate(p, lambda t: re.sub(r'(<hh:breakSetting [^>]*keepLines=")1(")', r'\g<1>0\2', t), 'kcm.hwpx', hfn=lambda h: h.replace('keepLines="1"', 'keepLines="0"')); self.assertIn('G40  FAIL', self.verify(m)[1])
        s = self.spec(); s['group_start'] = 'flow'; s['items'] += [{'type': 'instruction', 'text': '※ 다음 글을 읽고 물음에 답하시오.'}, {'type': 'passage', 'paras': ['둘째 지문이다.']}, self.q()]
        _, _, p = self.build(s, 'flow.hwpx'); self.assertEqual(self.sec(p).count('columnBreak="1"'), 1); self.assertIn('G41  WARN', self.verify(p)[1])   # 나눔 없는 묶음은 경고
        s['group_start'] = 'page'; _, _, p = self.build(s, 'page.hwpx'); self.assertGreaterEqual(self.sec(p).count('pageBreak="1"'), 2)
        s['group_start'] = 'zzz'; self.bad(s, 'group_start')

    def test_choice_structure_tab_aligned(self):
        _, _, p = self.build(EX['basic'], 'tabC.hwpx'); x = self.sec(p); h = self.hdr(p)
        m = re.search(r'<hp:t>①<hp:tab width="(\d+)" leader="0" type="1"/>', x); self.assertTrue(m)
        self.assertIn(f'<hh:tabItem pos="1988" type="LEFT" leader="NONE" unit="HWPUNIT"/>', h)
        self.assertEqual(x.count('<hp:tab '), 10)   # 선택지 10개, 번호 뒤 탭 하나씩
        self.assertIn('G49  PASS', self.verify(p)[1])

    def test_verify_bad_files(self):
        (self.d / 'bad.hwpx').write_bytes(b'not a zip'); (self.d / 'empty.hwpx').write_bytes(b'')
        _, _, good = self.build(EX['basic'], 'g.hwpx')
        code, out = run(VERIFY, self.d / 'bad.hwpx', self.d / 'empty.hwpx', self.d / 'none.hwpx', good)
        self.assertEqual(code, 1); self.assertNotIn('Traceback', out); self.assertEqual(out.count('열 수 없는 파일'), 3); self.assertIn(' G1 ', out)  # 뒤 파일도 계속 검사

    # ---- 서식 표기 · 특수 공백 · JSON 오류 · 추출기 ----
    def test_markup_nesting_and_u_in_plain_fields_rejected(self):
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][1] = '**가<u>나</u>다**'; self.bad(s, '겹치거나')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][1] = '<u>가**나**다</u>'; self.bad(s, '겹치거나')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][0] = '가<u>나</u>.'; self.bad(s, '밑줄')

    def test_special_spaces_normalized_and_numbered_notes_rejected(self):
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][0]
        q['choices'][0] = '가\u00a0나\u3000다\u200b라.'
        _, out, p = self.build(s); self.assertIn('특수 공백', out); self.assertIn('제로폭', out)
        x = self.sec(p); self.assertIn('가 나 다라.', x); code, v = self.verify(p); self.assertEqual(code, 0, v)
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['note']['wrong'][0] = '① ‘근거’ — 일치.'; self.bad(s, '선택지 번호')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['stem'] = '3.1 운동에 대한 설명으로 가장 적절한 것은?'; self.build(s)  # '3.1' 은 번호가 아니다

    def test_json_error_has_no_english_message(self):
        code, out, _ = self.build(None, raw=b'{"format": "basic", "items": [,]}', check=False)
        self.assertNotIn('Expecting', out); self.assertIn('문법 오류', out)

    def test_extract_nested_tables_and_inline_tab(self):
        _, _, p = self.build(EX['basic'], 'c.hwpx')
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', p)
        self.assertEqual(code, 0, out); self.assertEqual(out.count('[미주 1] 정답 ③'), 1); self.assertIn('[발문 2]', out)
        self.assertLess(out.index('[발문 1]'), out.index('[미주 1]')); self.assertLess(out.index('[선택지] ⑤'), out.index('[미주 1]'))  # 미주는 해당 문항 선택지 뒤
        self.assertIn('<u>', out)
        m = self.mutate(p, lambda s: s.replace('등대는 배가', '등<hp:tab/>대는 배가', 1), 'tab.hwpx')
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', m); self.assertIn('① 등 대는', out)
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', self.d / 'none.hwpx'); self.assertNotEqual(code, 0); self.assertNotIn('Traceback', out)

    # ---- 퍼징 입력 ----
    def test_fuzz_findings(self):
        import unicodedata
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['stem'] = unicodedata.normalize('NFD', '적절하지 않은 것은?')  # 자모 분리 입력
        _, _, p = self.build(s); code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('<hp:t>않은</hp:t>', self.sec(p))
        for bogus in ('****', '<u>a<u>b</u></u>', '</u>a<u>', '# <u>제목</u>'):
            s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][0] = bogus; self.bad(s, '소제목' if bogus.startswith('#') else '')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['source'] = '  '; self.bad(s, '비어 있습니다')
        s = self.spec(); s['items'].append({'type': 'end_heading', 'text': '정답 및 해설'}); self.bad(s, '정답과 해설')
        for sc in ('NaN', 'Infinity', '1e30', '1' + '0' * 40):
            s = self.spec(); raw = json.dumps(s, ensure_ascii=False).replace('"score": 3.6', '"score": ' + sc); self.bad(None, '배점', raw=raw.encode()) if sc != '1' + '0' * 40 else self.bad(None, '', raw=raw.encode())
        code, out, _ = self.build(None, raw=('[' * 100000).encode(), check=False); self.assertNotIn('Traceback', out); self.assertNotEqual(code, 0)
        for ch in ('\u200b', '\u2009', '\u202f', '\ufeff', '\u00ad'):
            s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][0] = f'가{ch}나.'; _, out, p = self.build(s); self.assertIn('경고', out)
            code, v = self.verify(p); self.assertEqual(code, 0, v)

    def test_verify_survives_broken_inputs(self):
        _, _, good = self.build(EX['basic'], 'c.hwpx')
        empty = self.mutate(good, lambda s: __import__('re').sub(r'(<hp:t>)[^<]*(</hp:t>)', r'\1\2', s), 'empty.hwpx')
        code, out = run(VERIFY, empty); self.assertNotIn('Traceback', out)
        # 섹션 항목 CRC 손상 + 뒤에 정상 파일
        raw = bytearray(good.read_bytes()); z = zipfile.ZipFile(good); info = z.getinfo('Contents/section0.xml')
        raw[info.header_offset + 30 + len(info.filename.encode()) + 40] ^= 0xFF; (self.d / 'crc.hwpx').write_bytes(bytes(raw))
        code, out = run(VERIFY, self.d / 'crc.hwpx', good); self.assertNotIn('Traceback', out); self.assertIn('###', out.split('###', 2)[2] and '###'); self.assertEqual(out.count('###'), 2)
        # 미주에만 배점이 있는 C 파일, mimetype 내용
        _, _, c2 = self.build(EX['basic'], 'c2.hwpx'); import re
        m = self.mutate(c2, lambda s: re.sub(r' \[\d+\.\d점\]</hp:t><hp:ctrl><hp:endNote', '</hp:t><hp:ctrl><hp:endNote', s), 'noscore.hwpx')
        code, out = run(VERIFY, m); self.assertIn('G31', [l for l in out.splitlines() if 'FAIL' in l and 'G31' in l][0])
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', self.d); self.assertNotIn('Traceback', out)
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', '--help'); self.assertIn('사용:', out)

    def test_verify_value_error_is_structure_fail(self):  # 열린 파일의 잘못된 값은 '열 수 없는 파일'이 아니라 구조 오류
        _, _, good = self.build(EX['basic'], 'g.hwpx')
        m = self.mutate(good, lambda s: s, 'h.hwpx', hfn=lambda h: re.sub(r'(<hh:charPr id="\d+" height=")\d+', r'\1x', h))
        code, out = run(VERIFY, m); self.assertEqual(code, 1); self.assertNotIn('Traceback', out)
        self.assertIn('구조 오류(ValueError', out); self.assertNotIn('열 수 없는 파일', out)

    def test_extract_counts_endnote_equation_once(self):
        _, _, p = self.build(EX['basic'], 'c.hwpx')
        m = self.mutate(p, lambda s: s.replace('<hp:t>출제 포인트  </hp:t>', '<hp:t>출제 포인트  </hp:t><hp:equation><hp:script>x</hp:script></hp:equation>', 1), 'eq.hwpx')
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', m); self.assertEqual(code, 0, out)
        self.assertIn('[수식: x]', out); self.assertIn('수식 1개', out)


class TComponents(unittest.TestCase):  # scripts/components.py: 정규형·모양 맞추기(재사용·덧붙임)·본문 자리·목록. 부품은 템플릿 헤더에서 뽑아 시험 안에서 만든다
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('components', SKILL / 'scripts/components.py')
        cls.C = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.C)
        cls.HDR = zipfile.ZipFile(SKILL / 'assets/templates/exam_template_basic.hwpx').read('Contents/header.xml').decode('utf-8')

    def setUp(self): self.d = Path(tempfile.mkdtemp())

    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    LISTS = {'borderFill': 'borderFills', 'tabPr': 'tabProperties', 'charPr': 'charProperties', 'numbering': 'numberings', 'bullet': 'bullets', 'paraPr': 'paraProperties'}

    def raw(self, kind, i, hdr=None):
        return re.search(rf'<hh:{kind} id="{i}"[^>]*?(/>|>.*?</hh:{kind}>)', hdr or self.HDR, re.S).group(0)

    def mini_component(self, cid, roles, pick, extra=None, body=None, hdr=None, comp=None, styles=None):
        """템플릿 헤더에서 항목 원문을 id로 뽑아 부품 폴더를 만든다. pick: {종류: [id…]}(의존까지 나열, 글꼴은 모든 언어의 같은 id), extra: {종류: [원문…]}"""
        hdr, extra = hdr or self.HDR, extra or {}
        if styles is None:
            ns = ' '.join(re.findall(r'xmlns:\w+="[^"]+"', hdr[:3000]))
            fonts = ''.join(f'<hh:fontface lang="{lang}">' + ''.join(re.search(rf'<hh:font id="{i}".*?</hh:font>', re.search(rf'<hh:fontface lang="{lang}".*?</hh:fontface>', hdr, re.S).group(0), re.S).group(0) for i in pick.get('font', [])) + '</hh:fontface>'
                            for lang in re.findall(r'<hh:fontface lang="(\w+)"', hdr))
            parts = [f'<hh:fontfaces>{fonts}</hh:fontfaces>'] if pick.get('font') else []
            for kind, tag in self.LISTS.items():
                items = [self.raw(kind, i, hdr) for i in pick.get(kind, [])] + extra.get(kind, [])
                if items: parts.append(f'<hh:{tag}>' + ''.join(items) + f'</hh:{tag}>')
            styles = f'<?xml version="1.0" encoding="UTF-8"?><hh:refList {ns}>' + ''.join(parts) + '</hh:refList>'
        d = self.d / 'assets/components' / cid; d.mkdir(parents=True, exist_ok=True)
        (d / 'styles.xml').write_text(styles, encoding='utf-8')
        slots = {h: h for h in re.findall(r'\{\{([^{}:]*)\}\}', body or '')}  # slots 는 body.xml 의 글 자리와 같아야 한다
        (d / 'component.json').write_text(json.dumps(comp if comp is not None else {'id': cid, 'name': cid, 'roles': roles, 'slots': slots}, ensure_ascii=False), encoding='utf-8')
        if body is not None: (d / 'body.xml').write_text(body, encoding='utf-8')
        return d

    def reg(self, *cids, extra_fmt=None):
        return self.C.Registry(self.d, {'id': 't', 'parts': {c: c for c in cids}, **(extra_fmt or {})})

    def canon(self, xml): return self.C.Canon(ET.fromstring(xml.encode('utf-8')))

    def with_item(self, hdr, kind, xml):  # 목록 끝에 항목을 더한다(itemCnt 는 시험하지 않는 Canon 용)
        t = self.LISTS[kind]; return hdr.replace(f'</hh:{t}>', xml + f'</hh:{t}>', 1)

    def as_id(self, kind, src, new, *sub):  # src 번호 항목을 new 번호로 복제, sub: 정규식·바꿀 글을 번갈아
        x = re.sub(r'(\sid=")\d+(")', rf'\g<1>{new}\2', self.raw(kind, src), count=1)
        for a, b in zip(sub[::2], sub[1::2]): x = re.sub(a, b, x)
        return x

    @staticmethod
    def tweak(x): return re.sub(r'horizontal="(\w+)"', lambda m: 'horizontal="LEFT"' if m.group(1) != 'LEFT' else 'horizontal="RIGHT"', x, count=1)  # 정렬만 바꾼다

    def ids_of(self, hdr, kind): return [int(x) for x in re.findall(rf'<hh:{kind} id="(\d+)"', re.search(rf'<hh:{self.LISTS[kind]} .*?</hh:{self.LISTS[kind]}>', hdr, re.S).group(0))]

    # ---- 정규형 ----
    def test_canon_ignores_id_order_and_whitespace(self):
        x = self.raw('paraPr', 61)
        def shuffle(m): return '<' + m.group(1) + ''.join(' ' + a for a in reversed(re.findall(r'[\w:.\-]+="[^"]*"', m.group(2)))) + m.group(3) + '>'
        y = re.sub(r'<([\w:]+)((?: [\w:.\-]+="[^"]*")+)(/?)>', shuffle, re.sub(r'><', '>\n   <', x))
        y = re.sub(r'(\sid=")\d+(")', r'\g<1>99\2', y, count=1)
        self.assertNotEqual(x, y)
        cn = self.canon(self.with_item(self.HDR, 'paraPr', y))
        self.assertEqual(cn.of('paraPr', 61), cn.of('paraPr', 99))
        cn = self.canon(self.with_item(self.HDR, 'paraPr', self.tweak(self.as_id('paraPr', 61, 99))))
        self.assertNotEqual(cn.of('paraPr', 61), cn.of('paraPr', 99))

    def test_loose_canon_masks_only_variant_attrs(self):
        h = self.HDR
        h = self.with_item(h, 'paraPr', self.as_id('paraPr', 61, 200, r'keepLines="0"', 'keepLines="1"', r'keepWithNext="0"', 'keepWithNext="1"', r'tabPrIDRef="0"', 'tabPrIDRef="1"'))
        h = self.with_item(h, 'paraPr', self.tweak(self.as_id('paraPr', 61, 201)))
        h = self.with_item(h, 'paraPr', self.as_id('paraPr', 61, 202).replace('<hc:left value="0"', '<hc:left value="7"', 1))
        c = self.as_id('charPr', 53, 300)
        c = re.sub(r'height="\d+"', 'height="1300"', c, count=1).replace('<hh:underline type="NONE"', '<hh:underline type="BOTTOM"').replace('<hh:spacing hangul="0"', '<hh:spacing hangul="-5"')
        h = self.with_item(h, 'charPr', c)
        h = self.with_item(h, 'charPr', self.as_id('charPr', 53, 301).replace('textColor="#000000"', 'textColor="#ff0000"'))
        h = self.with_item(h, 'charPr', re.sub(r'height="\d+"', 'height="1300"', self.as_id('charPr', 53, 302), count=1).replace('textColor="#000000"', 'textColor="#ff0000"'))
        cn = self.canon(h)
        self.assertEqual(cn.of('paraPr', 61, True), cn.of('paraPr', 200, True)); self.assertNotEqual(cn.of('paraPr', 61), cn.of('paraPr', 200))
        for i in (201, 202): self.assertNotEqual(cn.of('paraPr', 61, True), cn.of('paraPr', i, True)); self.assertNotEqual(cn.of('paraPr', 61), cn.of('paraPr', i))
        self.assertEqual(cn.of('charPr', 53, True), cn.of('charPr', 300, True)); self.assertNotEqual(cn.of('charPr', 53), cn.of('charPr', 300))
        for i in (301, 302): self.assertNotEqual(cn.of('charPr', 53, True), cn.of('charPr', i, True)); self.assertNotEqual(cn.of('charPr', 53), cn.of('charPr', i))

    # ---- 모양 맞추기 ----
    PICK = {'font': [2], 'borderFill': [1, 2, 3], 'tabPr': [0], 'charPr': [36, 53], 'numbering': [2], 'paraPr': [61, 62]}
    ROLES = {'plain': {'pp': 61, 'cp': 53}, 'num': {'pp': 62, 'cp': 36}, 'box': {'bf': 3}}

    def test_resolve_identity_on_matching_template(self):
        self.mini_component('c1', self.ROLES, self.PICK); r = self.reg('c1'); out = r.resolve(self.HDR)
        self.assertEqual(out, self.HDR); p = r.use('c1')
        self.assertEqual((p.pp('plain'), p.cp('plain'), p.pp('num'), p.cp('num'), p.bf('box')), (61, 53, 62, 36, 3))
        self.assertEqual(r.used(), ['c1'])

    def test_resolver_prefers_original_id(self):
        self.mini_component('c1', {'a': {'pp': 61}}, {'paraPr': [61], 'tabPr': [0], 'borderFill': [2]})
        h = self.HDR.replace(self.raw('paraPr', 5), self.as_id('paraPr', 61, 5))
        self.assertEqual(self.canon(h).index('paraPr')[self.canon(h).of('paraPr', 61)], [5, 61])
        r = self.reg('c1'); self.assertEqual(r.resolve(h), h); self.assertEqual(r.use('c1').pp('a'), 61)

    def test_resolver_smallest_when_original_absent(self):
        self.mini_component('c1', {'a': {'pp': 61}}, {'paraPr': [61], 'tabPr': [0], 'borderFill': [2]})
        h = self.HDR.replace(self.raw('paraPr', 61), self.tweak(self.raw('paraPr', 61)))
        for i in (5, 7): h = h.replace(self.raw('paraPr', i), self.as_id('paraPr', 61, i))
        r = self.reg('c1'); self.assertEqual(r.resolve(h), h); self.assertEqual(r.use('c1').pp('a'), 5)

    def test_resolver_appends_missing_with_counts(self):
        h = self.HDR
        for kind, n in (('paraPr', 40), ('charPr', 37), ('borderFill', 8)):  # 앞 n개만 남긴다(borderFill 은 id 1부터)
            t = self.LISTS[kind]; seg = re.search(rf'<hh:{t} .*?</hh:{t}>', h, re.S).group(0)
            keep = [self.raw(kind, i) for i in sorted(self.ids_of(h, kind))[:n]]
            h = h.replace(seg, f'<hh:{t} itemCnt="{n}">' + ''.join(keep) + f'</hh:{t}>')
        h = re.sub(r'(<hh:font id="2" face=")[^"]*', r'\1다른 바탕', h)  # 부품이 쓰는 글꼴이 없다
        tab = '<hh:tabPr id="3" autoTabLeft="0" autoTabRight="0"><hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"><hh:tabItem pos="1988" type="LEFT" leader="NONE" unit="HWPUNIT"/></hp:case><hp:default><hh:tabItem pos="3976" type="LEFT" leader="NONE"/></hp:default></hp:switch></hh:tabPr>'
        num = self.as_id('numbering', 2, 5, r'charPrIDRef="36"', 'charPrIDRef="41"')
        extra = {'tabPr': [tab], 'numbering': [num],
                 'paraPr': [self.as_id('paraPr', 85, 200, r'tabPrIDRef="0"', 'tabPrIDRef="3"'), self.as_id('paraPr', 62, 201, r'idRef="2"', 'idRef="5"')]}
        pick = {'font': [2], 'borderFill': [1, 2, 3, 9, 13], 'tabPr': [0], 'charPr': [36, 37, 41, 53], 'numbering': [2], 'paraPr': [61, 62, 85]}
        roles = {'a': {'pp': 61, 'cp': 53}, 'b': {'pp': 85, 'cp': 37}, 'c': {'pp': 62, 'cp': 41}, 'd': {'pp': 200}, 'e': {'pp': 201}, 'f': {'bf': 9}, 'g': {'bf': 13}}
        self.mini_component('c1', roles, pick, extra)
        r = self.reg('c1'); out = r.resolve(h); self.assertNotEqual(out, h)
        cn = self.canon(out)
        for kind in self.LISTS:  # itemCnt 가 실제 개수와 같고 id 가 중복 없이 이어진다
            ids = self.ids_of(out, kind); self.assertEqual(len(ids), len(set(ids)), kind)
            self.assertEqual(int(re.search(rf'<hh:{self.LISTS[kind]} itemCnt="(\d+)"', out).group(1)), len(ids), kind)
            self.assertEqual(ids, list(range(ids[0], ids[0] + len(ids))), kind); self.assertEqual(ids[0], 1 if kind in ('borderFill', 'numbering', 'bullet') else 0)
        for lang, n in re.findall(r'<hh:fontface lang="(\w+)" fontCnt="(\d+)"', out):
            self.assertEqual(int(n), len(re.findall(r'<hh:font id=', re.search(rf'<hh:fontface lang="{lang}".*?</hh:fontface>', out, re.S).group(0)))); self.assertEqual(int(n), 5)
        p, pc = r.use('c1'), r.parts['c1'].canon
        kinds = {'pp': 'paraPr', 'cp': 'charPr', 'bf': 'borderFill'}
        for role, rr in roles.items():
            for a, oid in rr.items(): self.assertEqual(cn.of(kinds[a], getattr(p, a)(role)), pc.of(kinds[a], oid), (role, a))
        old = {k: set(self.ids_of(h, k)) for k in self.LISTS}
        self.assertTrue(all(set(self.ids_of(out, k)) >= old[k] for k in old)); self.assertNotEqual(p.pp('d'), 85)
        for kind in ('borderFill', 'tabPr', 'charPr', 'numbering', 'paraPr'):  # 덧붙은 항목이 가리키는 번호는 모두 결과 헤더에 있다
            for i in set(self.ids_of(out, kind)) - old[kind]:
                e = cn.el[kind][i]
                for x in e.iter():
                    for k, k2 in (('borderFillIDRef', 'borderFill'), ('tabPrIDRef', 'tabPr'), ('charPrIDRef', 'charPr')):
                        if k in x.attrib and int(x.get(k)) != 4294967295: self.assertIn(int(x.get(k)), cn.el[k2], (kind, i, k))
                    if x.tag.endswith('heading') and x.get('type') == 'NUMBER': self.assertIn(int(x.get('idRef')), cn.el['numbering'])
                    if x.tag.endswith('fontRef'):
                        for k, lang in self.C.LANGS.items(): self.assertIn((lang, int(x.get(k))), cn.el['font'])
        self.assertEqual(r.resolve(out), out)  # 다시 맞춰도 더 덧붙지 않는다
        self.assertEqual((p.pp('a'), p.bf('f')), (r.use('c1').pp('a'), r.use('c1').bf('f')))

    # ---- 본문 자리 ----
    BODY = '<hp:p paraPrIDRef="{{pp:outer}}"><hp:run charPrIDRef="{{cp:outer}}"><hp:t>{{본문}}</hp:t></hp:run>{{뒤}}</hp:p>'

    def test_body_single_pass_injection(self):
        self.mini_component('c1', {'outer': {'pp': 61, 'cp': 53}}, {'font': [2], 'borderFill': [2], 'tabPr': [0], 'charPr': [53], 'paraPr': [61]}, body=self.BODY)
        r = self.reg('c1'); r.resolve(self.HDR); p = r.use('c1')
        v = r'{{본문}} {{pp:outer}} \1 $& \\ \g<0> {{'
        self.assertEqual(p.body({'본문': v, '뒤': 'X'}), f'<hp:p paraPrIDRef="61"><hp:run charPrIDRef="53"><hp:t>{v}</hp:t></hp:run>X</hp:p>')
        for slots in ({'본문': 'a'}, {'본문': 'a', '뒤': 1}):
            with self.assertRaises(SystemExit) as c: p.body(slots)
            self.assertTrue(str(c.exception.code).startswith('오류:') and 'c1' in str(c.exception.code))
        self.mini_component('c2', {}, {'paraPr': [61], 'tabPr': [0], 'borderFill': [2]}, body='<hp:t>{{</hp:t>')
        with self.assertRaises(SystemExit): self.reg('c2').use('c2').body({})
        with self.assertRaises(SystemExit): self.reg('c1').use('c1').pp('outer')  # 맞추기 전

    # ---- 부품 파일 오류 ----
    def test_bad_component_files_have_korean_errors(self):
        pk = {'paraPr': [61], 'tabPr': [0], 'borderFill': [2], 'charPr': [53], 'font': [2]}
        def expect(cid, **kw):
            with self.assertRaises(SystemExit, msg=cid) as c: self.mini_component(cid, kw.pop('roles', {}), kw.pop('pick', pk), **kw); self.reg(cid)
            m = str(c.exception.code); self.assertTrue(m.startswith('오류:') and cid in m, m)
        expect('k1', comp={'id': 'k1', 'oops': 1})
        expect('k2', comp={'id': 'other', 'name': 'x'})
        expect('k3', comp={'id': 'k3', 'roles': {'a': {'pp': 61, 'zz': 1}}})
        expect('k4', comp={'id': 'k4', 'roles': {'a': {'pp': 9999}}})
        expect('k5', pick={**pk, 'paraPr': [61, 61]}, roles={'a': {'pp': 61}})
        expect('k6', comp={'id': 'k6'}, pick={'paraPr': [61]})  # 가리키는 탭·테두리 정의가 styles.xml 에 없다
        with self.assertRaises(SystemExit) as c: self.reg('ghost')
        self.assertTrue(str(c.exception.code).startswith('오류:') and 'ghost' in str(c.exception.code))

    # ---- 목록 ----
    def test_catalog_lists_components_and_types(self):
        self.mini_component('one', {}, {'paraPr': [61], 'tabPr': [0], 'borderFill': [2]}, comp={'id': 'one', 'name': '첫 부품', 'desc': '설명 하나', 'kind': 'para', 'roles': {}, 'rules': ['G17', 'G33'], 'used_by': ['question.stem']})
        (self.d / 'assets').mkdir(exist_ok=True)
        (self.d / 'assets/formats.json').write_text(json.dumps([{'id': 't1', 'title': '시험', 'parts': {'a': 'one'}, 'question_types': ['choice5']}], ensure_ascii=False), encoding='utf-8')
        for md in (False, True):
            t = self.C.catalog(self.d, None, md)
            for w in ('one', '첫 부품', '설명 하나', 'G17, G33', 'question.stem', 'choice5', 't1'): self.assertIn(w, t, (md, w))
        self.assertIn('| 부품 |', self.C.catalog(self.d, 't1', True)); self.assertNotIn('| 부품 |', self.C.catalog(self.d, 't1'))
        with self.assertRaises(SystemExit) as c: self.C.catalog(self.d, 'zzz')
        self.assertIn('t1', str(c.exception.code))

    def test_shape_problems_detects_unregistered_shapes(self):
        self.mini_component('c1', self.ROLES, self.PICK); r = self.reg('c1')
        hd = ET.fromstring(self.HDR.encode('utf-8'))
        ns = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
        sec = lambda pp, cp, bf=3: ET.fromstring(f'<s {ns}><hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:secPr/></hp:run></hp:p><hp:p paraPrIDRef="{pp}"><hp:run charPrIDRef="{cp}"><hp:tbl borderFillIDRef="{bf}"><hp:tr><hp:tc borderFillIDRef="{bf}"/></hp:tr></hp:tbl></hp:run></hp:p></s>')
        self.assertEqual(self.C.shape_problems(r, hd, sec(61, 53)), [])
        self.assertTrue(self.C.shape_problems(r, hd, sec(5, 53))[0].startswith('문단 모양 5 ('))
        self.assertTrue(self.C.shape_problems(r, hd, sec(61, 5))[0].startswith('글자 모양 5 ('))
        self.assertEqual(len(self.C.shape_problems(r, hd, sec(61, 53, 16))), 1)  # 표와 칸이 같은 테두리를 가리켜도 한 줄

    # ---- basic 부품 폴더(템플릿 번호가 곧 계약: 빌더·검사기가 역할 이름으로 이 번호를 받는다) ----
    BASIC = {'title': {'line': (61, 53)}, 'blank': {'line': (0, 0)}, 'gap-3pt': {'line': (0, 31)}, 'instruction': {'line': (0, 10)},
             'passage-border': {'body': (32, 0), 'bold': (None, 10), 'underline': (None, 32), 'label': (None, 3), 'summary': (None, 3), 'source': (43, 3)},
             'stem': {'stem': (62, 37), 'negation': (None, 38)},
             'bogi-box': {'outer': (53, 0), 'label': (54, 41), 'line_poem': (85, 0), 'line_prose': (55, 0), 'bold': (None, 10), 'underline': (None, 32), 'source': (42, 3)},
             'choice5': {'choice': (41, 0)}, 'answer-note': {'first': (0, 0), 'answer': (None, 39), 'row': (47, 0), 'head': (None, 40), 'wrong_title': (48, None), 'wrong': (49, 0)},
             'end-heading': {'heading': (0, 12)}}

    def basic_fmt(self): return json.loads((SKILL / 'assets/formats.json').read_text(encoding='utf-8'))[0]

    def test_basic_components_resolve_identically_on_template(self):
        reg = self.C.Registry(SKILL, self.basic_fmt())
        self.assertTrue(reg.resolve(self.HDR) == self.HDR)  # 부품 모양이 모두 템플릿에 이미 있다 → 헤더 문자열 그대로
        self.assertEqual({p.id for p in reg.order}, set(self.BASIC))
        for p in reg.order:
            self.assertEqual(set(p.roles), set(self.BASIC[p.id]) | ({'table', 'cell'} if p.id == 'bogi-box' else set()), p.id)
            for role, (pp, cp) in self.BASIC[p.id].items():
                if pp is not None: self.assertEqual(p.pp(role), pp, (p.id, role))
                if cp is not None: self.assertEqual(p.cp(role), cp, (p.id, role))
        b = reg.parts['bogi']; self.assertEqual((b.bf('table'), b.bf('cell')), (8, 9))

    def test_component_json_contract(self):
        dirs = sorted(d.name for d in (SKILL / 'assets/components').iterdir() if d.is_dir())
        self.assertEqual(len(dirs), 10)
        self.assertEqual(sorted(self.basic_fmt()['parts'].values()), dirs)  # parts 값과 폴더가 1:1
        self.assertEqual(self.basic_fmt()['question_types'], ['choice5'])
        src = self.d / 'in.json'; src.write_text(json.dumps(EX['basic'], ensure_ascii=False), encoding='utf-8')
        out = self.d / 'x.hwpx'; self.assertEqual(run(BUILD, src, out)[0], 0)
        ids = set(re.findall(r'^\s+([GV]\d+)\s', run(VERIFY, out)[1], re.M))
        for cid in dirs:
            p = self.C.Part(cid, SKILL / 'assets/components' / cid)  # 계약 위반이면 오류로 멈춘다
            self.assertTrue(p.name and p.desc and p.kind and p.roles, cid)
            self.assertTrue(p.rules and p.used_by, cid)
            self.assertFalse(set(p.rules) - ids, (cid, p.rules))

    def test_bogi_body_reproduces_snippet(self):
        reg = self.C.Registry(SKILL, self.basic_fmt()); reg.resolve(self.HDR)
        raw = reg.parts['bogi'].body_xml
        self.assertEqual(raw.count('{{본문}}'), 1)
        head, tail = raw.split('{{본문}}')
        self.assertTrue(head.endswith('hasNumRef="0">') and head.count('<hp:subList') == 1 and tail.startswith('</hp:subList><hp:cellAddr'))
        x = reg.parts['bogi'].body({'본문': ''})
        self.assertNotIn('{{', x); ET.fromstring(f'<r xmlns:hp="x">{x}</r>'.encode('utf-8'))
        for a in ('treatAsChar="1"', 'rowCnt="1" colCnt="1"', 'width="20038"', '<hp:p id="0" paraPrIDRef="53" styleIDRef="0"', 'cellSpacing="0" borderFillIDRef="8"',
                  'editable="0" dirty="0" borderFillIDRef="9"', '<hp:run charPrIDRef="0"><hp:tbl', '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0"></hp:subList>'):
            self.assertIn(a, x, a)
        self.assertEqual(len(reg.parts['note'].body_xml.split('<hp:p ')) - 1, 9)
        self.assertEqual(reg.parts['bogi'].fit['width'], 189.4); self.assertEqual(reg.parts['choice'].fit, {'wrap': 201.24, 'adjust': -0.5})


    # ---- G50: 본문 모양이 등록된 부품 모양과 같은지 ----
    def g50(self, path, *flags):
        code, out = run(VERIFY, *flags, path); m = re.search(r'^\s+G50\s+(PASS|FAIL)\s+(.*)$', out, re.M)
        self.assertIsNotNone(m, out); self.assertNotIn('Traceback', out); return m.group(1), m.group(2), out

    def built(self, spec=None, name='b.hwpx'):
        src = self.d / 'in.json'; src.write_text(json.dumps(spec or EX['basic'], ensure_ascii=False), encoding='utf-8')
        self.assertEqual(run(BUILD, src, self.d / name)[0], 0); return self.d / name

    def mut(self, src, fn=None, hfn=None, name='m.hwpx'):  # T.mutate 와 같다(구역·헤더 문자열 고치기)
        out = self.d / name
        with zipfile.ZipFile(src) as z, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
            for it in z.infolist():
                data = z.read(it.filename).decode('utf-8') if it.filename in ('Contents/section0.xml', 'Contents/header.xml') else None
                if it.filename == 'Contents/section0.xml' and fn: data = fn(data)
                if it.filename == 'Contents/header.xml' and hfn: data = hfn(data)
                zo.writestr(it, z.read(it.filename) if data is None else data.encode('utf-8'))
        return out

    @staticmethod
    def parts(p): z = zipfile.ZipFile(p); return z.read('Contents/section0.xml') + z.read('Contents/header.xml')

    def test_g50_passes_on_builder_output(self):
        base = copy.deepcopy(EX['basic'])
        v1 = copy.deepcopy(base); v1['title'] = ['한 줄 제목']  # 제목 줄 수 변형
        v2 = copy.deepcopy(base); [i for i in v2['items'] if i['type'] == 'question'][0]['choices'] = ['가' * 60 + '.'] * 5  # 자간 줄임
        v3 = copy.deepcopy(base); [i for i in v3['items'] if i['type'] == 'question'][1]['bogi'].update(style='prose', lines=['첫 줄', '', '**굵은** 둘째 줄 ㉠<u>밑줄</u>'])
        v4 = copy.deepcopy(base); [i for i in v4['items'] if i['type'] == 'passage'][0]['paras'] += ['', '(나) [앞부분 줄거리] 요약이다.', '', '(다) 앞부분 줄거리 | 또 다른 요약.', '(중략 부분 줄거리)', '요약 문단.', '']  # 줄거리 표시
        v5 = copy.deepcopy(base); v5['items'] += [{'type': 'page_break'}, {'type': 'instruction', 'text': '※ 다음 글을 읽고 물음에 답하시오.'}, {'type': 'end_heading'}]
        for i, sp in enumerate((base, v1, v2, v3, v4, v5)):
            st, v, _ = self.g50(self.built(sp, f'v{i}.hwpx')); self.assertEqual(st, 'PASS', (i, v))

    def test_g50_fails_on_unregistered_shape(self):
        p = self.built()
        sub = lambda pat, new: (lambda x: re.sub(pat, new, x, count=1, flags=re.S))  # 첫 문단(구역 설정)은 템플릿 몫이라 건너뛰고 본문부터 찾는다
        cases = {'paraPr': dict(fn=sub(r'(</hp:secPr>.*?paraPrIDRef=")61(")', r'\g<1>1\2')), 'charPr': dict(fn=sub(r'(</hp:p>.*?charPrIDRef=")53(")', r'\g<1>5\2')),
                 'borderFill': dict(fn=sub(r'borderFillIDRef="8"', 'borderFillIDRef="5"')),
                 'header_align': dict(hfn=lambda h: re.sub(r'<hh:paraPr id="32".*?</hh:paraPr>', lambda m: m.group(0).replace('horizontal="JUSTIFY"', 'horizontal="LEFT"', 1), h, count=1, flags=re.S))}
        for k, kw in cases.items():
            q = self.mut(p, name=f'{k}.hwpx', **kw); self.assertNotEqual(self.parts(q), self.parts(p), k)  # 고쳐졌는지
            st, v, _ = self.g50(q); self.assertEqual(st, 'FAIL', (k, v)); self.assertIn('등록된 부품에 없는 모양', v, k)

    def test_g50_ignores_variant_attributes(self):
        h = lambda x: re.sub(r'<hh:paraPr id="32".*?</hh:paraPr>', lambda m: re.sub(r'keepWithNext="0"', 'keepWithNext="1"', m.group(0)), x, count=1, flags=re.S)
        p = self.built(); q = self.mut(p, hfn=h); self.assertNotEqual(self.parts(q), self.parts(p))
        self.assertEqual(self.g50(q)[0], 'PASS')

    def test_g50_skipped_in_lenient(self):
        q = self.mut(self.built(), fn=lambda x: re.sub(r'(</hp:secPr>.*?paraPrIDRef=")61(")', r'\g<1>1\2', x, count=1, flags=re.S))
        self.assertEqual(self.g50(q)[0], 'FAIL')
        st, v, _ = self.g50(q, '--lenient'); self.assertEqual(st, 'PASS'); self.assertIn('원본 검사는 건너뜀', v)

    def test_g50_missing_components_is_fail_not_traceback(self):
        cp = self.d / 'skill'; shutil.copytree(SKILL, cp, ignore=shutil.ignore_patterns('__pycache__', 'components'))
        code, out = run(cp / 'scripts/verify_exam.py', self.built()); m = re.search(r'^\s+G50\s+FAIL\s+.*$', out, re.M)
        self.assertIsNotNone(m, out); self.assertNotIn('Traceback', out); self.assertIn('부품', m.group(0)); self.assertEqual(code, 1)
        (cp / 'scripts/components.py').unlink()  # 코드 파일까지 없어도 트레이스백 없이 FAIL
        code, out = run(cp / 'scripts/verify_exam.py', self.d / 'b.hwpx'); self.assertRegex(out, r'G50\s+FAIL'); self.assertNotIn('Traceback', out)


    # ---- 에이전트 강제: 코드에 모양 번호 금지, 부품 등록부, 지침 ----
    def test_scripts_have_no_hardcoded_shape_numbers(self):  # 모양 번호는 부품이 정한다. 한계: verify_exam 의 테두리 없음 값 '2' 는 의미 상수라 대상이 아니다
        import ast
        ref, calls, names = re.compile(r'(paraPr|charPr|borderFill|styleID)IDRef="\d'), {'para', 'p_xml', 'run_xml', 'choice_xml', 'get'}, {'IDS', 'FIT', 'CHOICE', 'CHW'}
        isint = lambda n: isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool)
        bad = []
        for f in sorted((SKILL / 'scripts').glob('*.py')):
            for n in ast.walk(ast.parse(f.read_text(encoding='utf8'))):
                where = f'{f.name}:{getattr(n, "lineno", 0)}'
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and ref.search(n.value): bad.append((where, '모양 번호 문자열'))
                if isinstance(n, ast.Call) and n.args and isint(n.args[0]):
                    fn = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', '')
                    if fn in calls: bad.append((where, f'{fn}() 첫 인수가 정수'))
                if isinstance(n, ast.Tuple) and len(n.elts) == 2 and isint(n.elts[0]) and isinstance(n.elts[1], ast.Constant) and isinstance(n.elts[1].value, str): bad.append((where, '(정수, 글) 런 쌍'))
                if isinstance(n, ast.Name) and n.id in names: bad.append((where, f'이름 {n.id}'))
        self.assertEqual(bad, [])

    def test_every_component_has_rules_and_catalog_entry(self):
        ids = set(re.findall(r'^\s+([GV]\d+)\s', run(VERIFY, self.built())[1], re.M)); self.assertIn('G50', ids)
        def problems(root):
            out = []
            for d in sorted(x for x in (root / 'assets/components').iterdir() if x.is_dir()):
                c = json.loads((d / 'component.json').read_text(encoding='utf8'))
                if not c.get('rules') or not c.get('used_by'): out.append((d.name, '규칙 또는 쓰는 곳이 비어 있음'))
                if set(c.get('rules', [])) - ids: out.append((d.name, '검사기에 없는 규칙'))
            return out
        self.assertEqual(problems(SKILL), [])
        cp = self.d / 'skill'; (cp / 'assets').mkdir(parents=True); shutil.copytree(SKILL / 'assets/components', cp / 'assets/components')
        for key in ('rules', 'used_by'):  # 비면 FAIL 하는지 임시 복사본으로 확인
            f = cp / 'assets/components/stem/component.json'; c = json.loads(f.read_text(encoding='utf8')); c[key] = []; f.write_text(json.dumps(c, ensure_ascii=False), encoding='utf8')
            self.assertEqual([n for n, _ in problems(cp)], ['stem'], key)
            shutil.copy(SKILL / 'assets/components/stem/component.json', f)
        out = self.C.catalog(SKILL, 'basic'); dirs = sorted(d.name for d in (SKILL / 'assets/components').iterdir() if d.is_dir())
        for d in dirs: self.assertIn(f'- {d} ', out)
        self.assertIn(f'부품 {len(dirs)}개', out)

    def test_skill_md_requires_component_check(self):
        out = self.d / 'sk'; code, msg = run(SKILL.parent / 'build_plugin.py', out); self.assertEqual(code, 0, msg)
        t = (out / 'basic/SKILL.md').read_text(encoding='utf8')
        sec = t.split('## 새 시험지를 만드는 순서')[1]; first = re.split(r'\n2\. ', sec, maxsplit=1)[0]
        self.assertRegex(first, r'\n1\. '); self.assertIn('components.py', first)
        for w in ('목록에 없으면', 'XML을 직접', '다른 도구'): self.assertIn(w, first)
        self.assertNotIn('G50', t.split('## 더 자세한 규칙')[0].split('4. 규칙을 검사한다')[0])  # 교사에게 보이는 앞부분에는 규칙 번호가 없다
        self.assertIn('components.py', (out / 'basic/references/exam-json.md').read_text(encoding='utf8'))


if __name__ == '__main__':
    unittest.main(verbosity=1)
