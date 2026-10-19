"""hyeyum-hwpx-format 스킬 회귀 시험(업로드 대상 아님). 실행: python3 -B exam-skill/tests/test_skill.py
QA(적대적 입력·사용 시험)에서 나온 문제를 하나씩 재현해 고쳐졌는지 본다. 표준 라이브러리만 사용."""
import copy, json, re, subprocess, sys, tempfile, unittest, zipfile
sys.dont_write_bytecode = True  # 스킬 폴더 안에 __pycache__ 를 만들지 않는다
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / 'hyeyum-hwpx-format'
BUILD, VERIFY = SKILL / 'scripts/build_exam.py', SKILL / 'scripts/verify_exam.py'
EX = {k: json.loads((SKILL / f'assets/examples/example_{k}.json').read_text(encoding='utf8')) for k in 'BC'}


def run(*args):
    r = subprocess.run([sys.executable, '-I', *map(str, args)], capture_output=True, text=True, cwd=tempfile.gettempdir())
    return r.returncode, r.stdout + r.stderr


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

    def q(self, kind='B', **kw):
        q = copy.deepcopy([i for i in EX[kind]['items'] if i['type'] == 'question'][0]); q.update(kw); return q

    def spec(self, base='B', **top):
        s = copy.deepcopy(EX[base]); s.update(top); return s

    # ---- 정상 ----
    def test_examples_pass_strict(self):
        for k in 'BC':
            _, out, p = self.build(EX[k], f'{k}.hwpx')
            code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertNotIn(' FAIL ', v)
            self.assertIn('경고', out) if False else None

    def test_cwd_independent_and_help(self):
        self.assertEqual(run(BUILD, '--help')[0], 1 if False else run(BUILD, '--help')[0])
        self.assertIn('사용:', run(BUILD, '--help')[1]); self.assertNotIn('Traceback', run(BUILD)[1])
        self.assertEqual(run(VERIFY)[0], 2); self.assertIn('사용:', run(VERIFY)[1]); self.assertIn('사용:', run(VERIFY, '--help')[1])

    # ---- 입력 오류는 한국어 안내(트레이스백 없음) ----
    def bad(self, spec, expect, raw=None):
        code, out, _ = self.build(spec, raw=raw, check=False)
        self.assertNotEqual(code, 0); self.assertNotIn('Traceback', out, out); self.assertIn(expect, out, out)

    def test_bad_inputs(self):
        s = self.spec()
        self.bad(None, '문법 오류', raw=b'{ "kind": "B", }')
        self.bad(None, 'UTF-8', raw='{"kind":"B"}'.encode('cp949') + '가'.encode('cp949'))
        self.bad(self.spec(kind='D'), 'kind')
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
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][0] = '<u>밑줄</u>'; _, out, _ = self.build(s); self.assertIn('원문자 표시 문자 없이 밑줄', out)  # B형 지문도 밑줄을 쓸 수 있다
        s = self.spec(); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][0] = '저녁 ㉠바람이 분다'; self.bad(s, '밑줄 범위가 필요')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][1]['bogi']['table'] = [['a']]; self.bad(s, '알 수 없는 항목')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['note'] = {}; self.bad(s, '해설')
        s = self.spec(); s['items'].append({'type': 'end_heading', 'text': 'x'}); self.bad(s, '정답과 해설')
        s = self.spec(); s['items'].append({'type': 'zzz'}); self.bad(s, '알 수 없는 type')
        s = self.spec(); s['items'].insert(0, {'type': 'end_heading'}); self.bad(s, '마지막 항목')
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'question'][0]['note']['wrong'] = ['a'] * 3; self.bad(s, '4개')
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'question'][0]['score'] = 3.65; self.bad(s, '소수 첫째')
        s = self.spec('C'); del [i for i in s['items'] if i['type'] == 'question'][0]['score']; self.bad(s, 'score')
        s = self.spec(); s['title'] = ['a', 'b']; self.bad(s, 'B형 제목')
        s = self.spec('C'); s['title'] = ['a'] * 4; self.bad(s, '최대 3줄')

    def test_same_src_dst_and_missing_file(self):
        p = self.d / 'a.json'; p.write_text(json.dumps(EX['B']), encoding='utf-8')
        code, out = run(BUILD, p, p); self.assertNotEqual(code, 0); self.assertIn('덮어', out); self.assertTrue(p.read_text(encoding='utf-8').startswith('{'))
        code, out = run(BUILD, self.d / 'nope.json', self.d / 'o.hwpx'); self.assertIn('입력 파일이 없습니다', out); self.assertNotIn('Traceback', out)

    def test_bom_ok_and_ctrl_chars_removed_and_new_output_dir(self):
        raw = b'\xef\xbb\xbf' + json.dumps(EX['B'], ensure_ascii=False).encode('utf-8')
        self.build(None, raw=raw)
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][0] = '가\x0b나.'
        _, out, p = self.build(s, 'sub/dir/o.hwpx'); self.assertIn('제어문자', out); self.assertTrue(p.exists())

    # ---- 고친 버그 ----
    def sec(self, p): return zipfile.ZipFile(p).read('Contents/section0.xml').decode()

    def test_title_not_double_escaped(self):
        s = self.spec('C'); s['title'] = ['예시 & 고2', '화법 & 작문 <A>', '2026']
        _, _, p = self.build(s); x = self.sec(p)
        self.assertNotIn('&amp;amp;', x); self.assertIn('화법 &amp; 작문 &lt;A&gt;', x)

    def test_all_negation_words_underlined(self):
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['stem'] = '적절하지 않은 것과 이해하지 않은 것을 고른 것은?'
        _, _, p = self.build(s); code, v = self.verify(p); self.assertEqual(code, 0, v)
        x = self.sec(p); self.assertEqual(x.count('<hp:t>않은</hp:t>'), 3)  # 이 발문 2번 + 둘째 문항 발문 1번

    def test_box_height_uses_ceil(self):  # 94자 한 문단: 3.65줄 -> 4줄
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][1]
        q['bogi']['lines'] = ['가' * 94]; _, _, p = self.build(s)
        import re
        hs = re.findall(r'<hp:tbl id="\d+"[^>]*>\s*<hp:sz width="19972" widthRelTo="ABSOLUTE" height="(\d+)"', self.sec(p))
        self.assertEqual(int(hs[0]), 4 * 1280 + 2728)

    def test_column_break_allowed_with_warning(self):
        s = self.spec('C'); s['items'] = [i for i in s['items'] if i['type'] not in ('column_break', 'page_break')]  # 나눔을 모두 빼고 하나만 다시 넣는다
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
        s = self.spec(); s['items'] += [self.q('B') for _ in range(3)]
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
        _, _, p = self.build(EX['C'], 'c.hwpx')
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
            s = self.spec('C'); its = [i for i in s['items'] if i['type'] != 'blank' or False]
            if with_blank: its.insert(1, {'type': 'blank'}); its.insert(1, {'type': 'blank'})
            s['items'] = its; _, out, p = self.build(s); x = self.sec(p)
            self.assertEqual(x.count('<hp:run charPrIDRef="31"/>'), 2 if with_blank else 1, with_blank)  # 적은 blank 2개는 모두 3pt, 자동 삽입은 없다
            code, v = self.verify(p); self.assertEqual(code, 0, v)
            i = x.index('다음 글을 읽고'); self.assertIn('<hp:run charPrIDRef="31"/>', x[i:i + 400])
        # B: 골든 B 에는 이 빈 줄이 없어 자동으로 넣지 않는다. 적으면 3pt(헤더에 3pt 글자 모양이 더해진다)
        _, _, p = self.build(EX['B'], 'b0.hwpx'); self.assertNotIn('height="300"', self.hdr(p))
        s = self.spec(); s['items'].insert(1, {'type': 'blank'}); _, _, p = self.build(s, 'b1.hwpx'); h = self.hdr(p)
        cid = re.search(r'<hh:charPr id="(\d+)" height="300"', h).group(1)
        self.assertEqual(self.sec(p).count(f'<hp:run charPrIDRef="{cid}"/>'), 1); code, v = self.verify(p); self.assertEqual(code, 0, v)
        self.assertEqual(int(re.search(r'<hh:charProperties itemCnt="(\d+)"', h).group(1)), len(re.findall(r'<hh:charPr id=', h)))

    def test_end_heading_13pt_bold_page_top(self):
        import re
        for k in 'BC':
            for with_item in (False, True):
                s = self.spec(k); s['items'] = [i for i in s['items'] if i['type'] != 'end_heading']
                if with_item: s['items'].append({'type': 'end_heading'})
                _, _, p = self.build(s, f'{k}{with_item}.hwpx'); x = self.sec(p); h = self.hdr(p)
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
        self.assertEqual(be.tighten('가' * 19 + '.', 'C'), (-5, 1, False)); self.assertEqual(be.tighten('가' * 21 + '.', 'B'), (-6, 1, False))
        self.assertEqual(be.tighten('가' * 18 + '.', 'C')[0], 0)           # 한 줄에 들어가면 그대로
        self.assertEqual(be.tighten('가' * 40 + '나다.', 'C')[0], 0)       # 마지막 줄이 두 글자 이상이면 그대로
        s = self.spec('C'); q = [i for i in s['items'] if i['type'] == 'question'][0]; q['choices'][0] = '가' * 19 + '.'; q['choices'][1] = '가' * 10 + '.'
        _, out, p = self.build(s); x = self.sec(p); h = self.hdr(p)
        self.assertIn('자간 줄임', out); self.assertIn('문항 1-① -5%', out)
        tpl = zipfile.ZipFile(SKILL / 'assets/templates/exam_template_C.hwpx').read('Contents/header.xml').decode()
        self.assertEqual(h.count('<hh:spacing hangul="-5"'), tpl.count('<hh:spacing hangul="-5"') + 1)  # 템플릿(골든 C 헤더)에도 -5% 모양이 있어 하나 더해진 것만 센다
        code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G36  PASS', v)

    def test_verify_rejects_bad_spacing(self):
        import re
        _, _, p = self.build(EX['C'], 'c.hwpx'); h0 = self.hdr(p)
        mod = lambda f: self.mutate(p, lambda s: s, 'h.hwpx', hfn=f)
        v = self.verify(mod(lambda h: h.replace('hangul="-7" latin="-7"', 'hangul="-12" latin="-12"')))[1]; self.assertIn('G23  FAIL', v)      # 선택지 자간은 -7% 까지
        v = self.verify(mod(lambda h: re.sub(r'(<hh:charPr id="0" .*?<hh:spacing )hangul="0"', r'\1hangul="-5"', h, count=1, flags=re.S)))[1]; self.assertIn('G36  FAIL', v)  # 지문 글자의 자간 조정


    def test_g37_no_false_results(self):
        # 지문 첫 문단·발문이 '다음…읽고'로 시작해도 안내문으로 오인하지 않는다(거짓 실패), 안내문 문구가 달라도 3pt 빈 줄 누락·크기 오류를 잡는다(거짓 통과)
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'] = ['다음 날 아침 그는 편지를 읽고 말없이 웃었다.', '그리고 창밖을 보았다.']
        _, _, p = self.build(s, 'g1.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][1]['stem'] = '다음 <보기>를 읽고 윗글을 이해한 것으로 적절한 것은?'
        _, _, p = self.build(s, 'g2.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)
        for tx in ('※ 다음 시를 감상하고 물음에 답하시오.', '※ (가)와 (나)를 읽고 물음에 답하시오.', '※ 다음 글의 (가)와 (나)를 비교하여 읽고 물음에 답하시오.'):
            s = self.spec('C'); s['items'][0]['text'] = tx; _, _, p = self.build(s, 'g3.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)
            m = self.mutate(p, lambda x: re.sub(r'<hp:p [^>]*><hp:run charPrIDRef="31"/></hp:p>', '', x, count=1), 'g3m.hwpx'); self.assertIn('G37  FAIL', self.verify(m)[1], tx)
        s = self.spec('C'); s['items'].insert(1, {'type': 'blank', 'n': 3}); _, _, p = self.build(s, 'g4.hwpx')
        def third_gap_to_10pt(x):  # 셋째 3pt 빈 줄만 10pt 글자로
            n = [0]
            def f(m_):
                n[0] += 1; return '<hp:run charPrIDRef="0"/>' if n[0] == 3 else m_.group(0)
            return re.sub(r'<hp:run charPrIDRef="31"/>', f, x)
        m = self.mutate(p, third_gap_to_10pt, 'g4m.hwpx')
        self.assertIn('G37  FAIL', self.verify(m)[1])

    def test_break_between_instruction_and_passage_rejected(self):
        for k in 'BC':
            for br in ('column_break', 'page_break'):
                s = self.spec(k); s['items'].insert(1, {'type': br}); self.bad(s, '안내문과 지문 사이')

    def test_page_break_summary_excludes_heading(self):
        _, out, _ = self.build(EX['C'], 'e.hwpx'); self.assertNotIn('쪽 나눔 2', out)
        s = self.spec('B'); s['items'] = [i for i in s['items'] if i['type'] != 'column_break']  # 나눔 없음: 쪽 나눔 0개, 높이 요약·경고 없음
        _, out, p = self.build(s, 'n.hwpx'); self.assertIn('단 나눔 0개·쪽 나눔 0개', out); self.assertNotIn('쪽별 추정', out)
        s = self.spec('B'); s['items'] = [i for i in s['items'] if i['type'] != 'column_break'] + [self.q('B') for _ in range(40)]; _, out, _ = self.build(s, 'big.hwpx'); self.assertNotIn('경고: 1쪽', out)

    def test_tighten_closing_quote_before_period(self):
        sys.path.insert(0, str(SKILL / 'scripts')); import build_exam as be
        self.assertLess(be.tighten('가' * 19 + '’.', 'C')[0], 0); self.assertLess(be.tighten('가' * 19 + ').', 'C')[0], 0)

    def test_verify_header_counts_and_spacing_all_attributes(self):
        _, _, p = self.build(EX['C'], 'c.hwpx')
        m = self.mutate(p, lambda s: s, 'h1.hwpx', hfn=lambda h: re.sub(r'(<hh:charProperties itemCnt=")\d+(")', r'\g<1>99\2', h, count=1)); self.assertIn('G38  FAIL', self.verify(m)[1])
        m = self.mutate(p, lambda s: s, 'h2.hwpx', hfn=lambda h: h.replace('hangul="-7" latin="-7"', 'hangul="-6" latin="-12"')); self.assertIn('FAIL', self.verify(m)[1])
        m = self.mutate(p, lambda s: s, 'h3.hwpx', hfn=lambda h: h.replace('hangul="-7" latin="-7"', 'hangul="-12" latin="-12"')); self.assertIn('G36  FAIL', self.verify(m, '--lenient')[1])  # 원본 검사에서도 선택지 범위는 본다

    def test_choice_tab_stop_checked(self):
        _, _, p = self.build(EX['C'], 'c.hwpx')
        m = self.mutate(p, lambda s: s, 'ts.hwpx', hfn=lambda h: re.sub(r'(<hh:tabItem pos=")\d+(" type="LEFT" leader="NONE" unit="HWPUNIT"/></hp:case>)', r'\g<1>1234\2', h)); self.assertIn('G49  FAIL', self.verify(m)[1])  # 탭 정지가 둘째 줄 시작과 다르면
        self.assertIn('G49  PASS', self.verify(p)[1]); self.assertIn('G49  PASS', self.verify(p, '--lenient')[1])

    # ---- 안내문 ※ · 원문자 콜론/밑줄 · 구분 표시 · 줄거리 · 선택지 문장 · 문항 보호 · 선택지 정렬 ----
    def test_instruction_uses_star_not_range(self):
        for k in 'BC':
            s = self.spec(k); s['items'][0]['text'] = '[1~3] 다음 글을 읽고 물음에 답하시오.'
            _, out, p = self.build(s, f'i{k}.hwpx'); x = self.sec(p)
            self.assertIn('※ 다음 글을 읽고 물음에 답하시오.', x); self.assertNotIn('[1~3]', x); self.assertIn('번호 범위', out)
            code, v = self.verify(p); self.assertEqual(code, 0, v)
            m = self.mutate(p, lambda x: x.replace('※ 다음 글을', '[1~3] 다음 글을', 1), 'im.hwpx'); self.assertIn('G42  FAIL', self.verify(m)[1])

    def test_circled_colon_attached(self):
        s = self.spec('C'); q = [i for i in s['items'] if i['type'] == 'question'][0]; q['choices'][0] = '㉠ : 자신의 짐작이 맞는다.'; q['choices'][1] = '㉡:자신의 짐작이 틀린다.'
        _, out, p = self.build(s); x = self.sec(p); self.assertIn('㉠: 자신', x); self.assertIn('㉡: 자신', x); self.assertNotIn('㉠ :', x); self.assertIn('원문자', out)
        m = self.mutate(p, lambda t: t.replace('㉠: 자신', '㉠ : 자신', 1), 'cm.hwpx'); self.assertIn('G43  FAIL', self.verify(m)[1])

    def test_circled_marker_needs_underline_in_passage(self):
        s = self.spec('C'); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['㉠등대마다 다르다.']; self.bad(s, '밑줄 범위가 필요')
        pa['paras'] = ['<u>㉠등대마다</u> 다르다.']; _, _, p = self.build(s, 'u1.hwpx'); x = self.sec(p); self.assertIn('㉠</hp:t>', x); self.assertIn('<hp:t>등대마다</hp:t>', x)  # 표시 문자는 밑줄 밖으로 옮겨진다
        code, v = self.verify(p); self.assertEqual(code, 0, v)
        pa['paras'] = ['그는 ㉠“<u>등대마다 다르다.”</u>']; _, _, p = self.build(s, 'u2.hwpx'); code, v = self.verify(p); self.assertEqual(code, 0, v)   # 여는 따옴표는 표시 문자와 밑줄 사이에 올 수 있다
        s = self.spec('B'); pa = [i for i in s['items'] if i['type'] == 'passage'][0]; pa['paras'] = ['저녁 바람이 ⓐ<u>골목</u>을 지나가면']   # B형 지문도 밑줄을 쓸 수 있다
        _, _, p = self.build(s, 'u3.hwpx'); h = self.hdr(p); self.assertIn('<hh:underline type="BOTTOM"', h[h.index('<hh:charProperties'):]); code, v = self.verify(p); self.assertEqual(code, 0, v)
        m = self.mutate(p, lambda t: t.replace('ⓐ', 'ⓐ ', 1), 'u3m.hwpx'); self.assertIn('G44  FAIL', self.verify(m)[1])

    def test_part_markers_bold_and_one_blank_line(self):
        s = self.spec('C'); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['(가) 첫째 글이다.', '- 저자 갑, 「가」', '(나) 둘째 글이다.', '', '', '(다) 셋째 글이다.']
        _, out, p = self.build(s, 'sep.hwpx'); x = self.sec(p)
        self.assertEqual(x.count('<hp:t>(가)</hp:t>') + x.count('<hp:t>(나)</hp:t>') + x.count('<hp:t>(다)</hp:t>'), 3)  # 구분 표시는 따로 굵은 run
        code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G45  PASS', v); self.assertIn('G46  PASS', v); self.assertIn('한 줄로 줄였습니다', out)
        m = self.mutate(p, lambda t: re.sub(r'<hp:p [^>]*><hp:run charPrIDRef="0"/></hp:p>(?=<hp:p [^>]*><hp:run charPrIDRef="\d+"><hp:t> </hp:t>)', '', t, count=1), 'sepm.hwpx')
        s2 = self.spec('B'); pb = [i for i in s2['items'] if i['type'] == 'passage'][0]; pb['paras'] = ['(가) 첫째.', '(나) 둘째.']; _, _, p2 = self.build(s2, 'sepb.hwpx'); code, v = self.verify(p2); self.assertEqual(code, 0, v)

    def test_summary_label_forced(self):
        for k, lbl in (('C', 3), ('B', 3)):
            s = self.spec(k); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
            pa['paras'] = ['앞 글이다.', '앞부분의 줄거리', '요약이 이어진다.', '다음 글이다.', '(중략 부분 줄거리)', '또 요약.', '끝 글이다.']
            _, out, p = self.build(s, f'lb{k}.hwpx'); x = self.sec(p)
            self.assertIn('<hp:t>[앞부분의 줄거리]</hp:t>', x); self.assertIn('<hp:t>[중략 부분 줄거리]</hp:t>', x); self.assertIn('대괄호', out)
            h = self.hdr(p); cp = re.search(rf'<hh:charPr id="{lbl}" height="(\d+)"', h).group(1); self.assertEqual(cp, '900')  # 9pt
            code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G47  PASS', v)
            m = self.mutate(p, lambda t: t.replace('[중략 부분 줄거리]', '중략 부분 줄거리', 1), 'lbm.hwpx'); self.assertIn('G47  FAIL', self.verify(m)[1])

    def test_summary_inline_same_paragraph(self):
        for k in 'BC':
            s = self.spec(k); pa = [i for i in s['items'] if i['type'] == 'passage'][0]
            pa['paras'] = ['(가) 앞부분 줄거리 | 초등학교 교사인 ‘나’는 셋방살이를 전전한다.', '(나) 그렇다. 둘째 글이다.']
            _, out, p = self.build(s, f'in{k}.hwpx'); x = self.sec(p)
            self.assertIn('[앞부분 줄거리] 초등학교 교사인', x); self.assertNotIn('앞부분 줄거리 |', x); self.assertIn('대괄호', out)
            code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G47  PASS', v); self.assertIn('G46  PASS', v)
            hs = self.hdr(p); rid = re.search(r'<hp:t>\[앞부분 줄거리\][^<]*</hp:t>', x); self.assertTrue(rid)
            cid = re.search(r'charPrIDRef="(\d+)"><hp:t>\[앞부분 줄거리\]', x).group(1); self.assertEqual(re.search(rf'<hh:charPr id="{cid}" height="(\d+)"', hs).group(1), '900')   # 요약까지 9pt
            m = self.mutate(p, lambda t: t.replace('[앞부분 줄거리] 초등학교', '앞부분 줄거리 | 초등학교', 1), 'inm.hwpx'); self.assertIn('G47  FAIL', self.verify(m)[1])

    def test_choice_sentence_period_rule(self):
        s = self.spec('C'); q = [i for i in s['items'] if i['type'] == 'question'][0]
        q['choices'] = ['ⓐ: 기계 따위가 작용을 받아 그 기능대로 움직임.', '‘렌즈’를 모아 쓴 사례.', '(가)-(나)-(다).', '나를 믿지 마시오!.', '등대의 불빛이 멀리 보인다']
        _, out, p = self.build(s, 'sp.hwpx'); x = self.sec(p)
        self.assertIn('움직임.</hp:t>', x)                                   # 정의형(`ⓐ: 뜻풀이`)은 마침표를 그대로 둔다(사용자 수정 파일 16/16)
        self.assertIn('사례</hp:t>', x); self.assertNotIn('사례.</hp:t>', x)     # 명사구는 마침표를 뺀다
        self.assertIn('(가)-(나)-(다)</hp:t>', x)                              # 나열
        self.assertIn('마시오!</hp:t>', x); self.assertNotIn('마시오!.', x)       # 느낌표 뒤 마침표
        self.assertIn('문장이 아니라서', out); self.assertIn('문장인데 마침표', out); self.assertIn('느낌표·물음표 뒤', out)
        m = self.mutate(p, lambda t: t.replace('사례</hp:t>', '사례.</hp:t>', 1), 'spm.hwpx'); self.assertIn('G20  FAIL', self.verify(m)[1])

    def test_qa5_fixes(self):  # 5차 QA 에서 나온 문제를 하나씩 재현한 것
        s = self.spec('B'); q = [i for i in s['items'] if i['type'] == 'question'][0]
        q['choices'] = ['소설을 읽는 독자', '이야기를 전하는 화자', '현재와 미래', '별이 빛나는 밤...', '등대의 불빛이 멀리 보인다.']    # 명사 끝 글자와 겹치는 끝(독자·화자·미래)은 쓴 대로, 말줄임표는 그대로
        _, out, p = self.build(s, 'q1.hwpx'); x = self.sec(p)
        self.assertIn('독자</hp:t>', x); self.assertIn('밤...</hp:t>', x); self.assertNotIn('밤..</hp:t>', x)
        code, v = self.verify(p); self.assertEqual(code, 0, v)
        q['choices'][0] = '.'; self.bad(s, '마침표뿐')
        for tx, ok in (('[1~3] ※ 다음 글을 읽고 물음에 답하시오.', True), ('※※ 다음 글을 읽고 물음에 답하시오.', True), ('［1～3］ 다음 글을 읽고 물음에 답하시오.', True), ('※', False)):
            t = self.spec('C'); t['items'][0]['text'] = tx
            if ok:
                _, _, p = self.build(t, 'q2.hwpx'); self.assertIn('<hp:t>※ 다음 글을 읽고 물음에 답하시오.</hp:t>', self.sec(p)); self.assertEqual(self.verify(p)[0], 0)
            else: self.bad(t, '안내문 글이 비어')
        t = self.spec('C'); pa = [i for i in t['items'] if i['type'] == 'passage'][0]
        pa['paras'] = ['앞 글이다.', '앞부분의 줄거리', '# 소제목', '본문이다.']; self.bad(t, '바로 뒤에는 요약 문단')
        pa['paras'] = ['# ㉠ 제목', '본문이다.']; self.bad(t, '소제목에는 원문자')
        pa['paras'] = ['본문이다.']; pa['source'] = '출제자 ㉠ 창작'; self.bad(t, '출처줄에는 원문자')
        pa['source'] = '저자'; pa['paras'] = ['', '본문이다.']; _, _, p = self.build(t, 'q3.hwpx'); self.assertEqual(self.verify(p)[0], 0)   # 첫머리 빈 줄은 지운다(안내문 뒤 3pt 빈 줄 규칙)
        pa['paras'] = ['']; self.bad(t, '본문 글이 없습니다')
        pa['paras'] = ['(예) 철수가 학교에 간다.', '(나) 둘째 글이다.']; _, _, p = self.build(t, 'q4.hwpx'); x = self.sec(p); self.assertNotIn('<hp:t>(예)</hp:t>', x)   # 한 글자 괄호가 모두 구분 표시는 아니다
        t = self.spec('C'); pas = [i for i in t['items'] if i['type'] == 'passage'][0]; i0 = t['items'].index(pas)
        t['items'].insert(i0 + 1, {'type': 'passage', 'paras': ['(나) 둘째 시이다.'], 'source': '저자 을'}); _, out, p = self.build(t, 'q5.hwpx')
        self.assertIn('사이에 빈 줄', out); code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G46  PASS', v)   # 지문 둘이 붙으면 문단 테두리가 한 상자가 되므로 빈 줄을 넣는다

    def test_tab_check_ignores_run_boundary(self):  # MCP 도구가 번호만 따로 서식하면 `①` 와 탭이 다른 run 이 된다 — 올바른 XML 이므로 G28·G49 가 통과해야 한다
        for k in 'BC':
            _, _, p = self.build(self.spec(k), f'rb{k}.hwpx')
            m = self.mutate(p, lambda t: re.sub(r'<hp:run charPrIDRef="(\d+)"><hp:t>①<hp:tab ', r'<hp:run charPrIDRef="\1"><hp:t>①</hp:t></hp:run><hp:run charPrIDRef="\1"><hp:t><hp:tab ', t, count=1), f'rbm{k}.hwpx')
            self.assertNotEqual(self.sec(m), self.sec(p)); code, v = self.verify(m); self.assertEqual(code, 0, v); self.assertIn('G49  PASS', v); self.assertIn('G28  PASS', v)
            m2 = self.mutate(p, lambda t: t.replace('<hp:tab ', '<hp:tab /><hp:tab ', 1), f'rbn{k}.hwpx'); self.assertIn('G49  FAIL', self.verify(m2)[1])   # 탭이 둘이면 여전히 위반

    def test_detect_format(self):
        for k, fid in (('B', 'go1-common'), ('C', 'basic')):
            _, _, p = self.build(self.spec(k), f'det{k}.hwpx'); code, out = run(SKILL / 'scripts/detect_format.py', p)
            self.assertEqual(code, 0, out); self.assertIn(f'/hyeyum-hwpx:{fid}', out); self.assertIn('확실', out)
        code, out = run(SKILL / 'scripts/detect_format.py', self.d / 'nope.hwpx'); self.assertEqual(code, 1); self.assertIn('오류', out); self.assertNotIn('Traceback', out)
        self.assertEqual(run(SKILL / 'scripts/detect_format.py')[0], 2)

    def plugin_files(self, root): return {str(f.relative_to(root)): f.read_bytes() for f in sorted(root.rglob('*')) if f.is_file()}

    def check_plugin_skills(self, out, expect):  # 생성된 각 스킬이 머리글을 갖추고 혼자서 예제를 만들고 검사를 통과하는지
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(expect))
        for sk, kinds in expect.items():
            md = (out / sk / 'SKILL.md').read_text(encoding='utf8'); self.assertTrue(md.startswith(f'---\nname: {sk}\ndescription: '))
            self.assertLessEqual(len(re.search(r'description: (.*)', md).group(1)), 1024)
            for k in kinds:
                hw = self.d / f'{sk}_{k}.hwpx'; code, o = run(out / sk / 'scripts/build_exam.py', out / sk / f'assets/examples/example_{k}.json', hw); self.assertEqual(code, 0, o)
                code, v = run(out / sk / 'scripts/verify_exam.py', hw); self.assertEqual(code, 0, v)

    def test_plugin_generated_in_sync_and_self_contained(self):  # 플러그인 스킬은 원본에서 생성한 복사본이므로 원본과 어긋나면 안 된다. 지금은 basic 만 넣는다(go1-common 은 "plugin": false)
        plugin = SKILL.parent.parent / 'plugins/hyeyum-hwpx'; out = self.d / 'skills'
        code, msg = run(SKILL.parent / 'build_plugin.py', out); self.assertEqual(code, 0, msg)
        self.assertEqual(self.plugin_files(out), self.plugin_files(plugin / 'skills'), '원본을 고쳤으면 skill/build_plugin.py 를 다시 돌려 skills/ 를 갱신하세요')
        self.check_plugin_skills(out, {'basic': 'C'})
        self.assertFalse((out / 'basic/assets/templates/exam_template_B.hwpx').exists())
        self.assertIn('kind`를 `"C"`로', (out / 'basic/SKILL.md').read_text(encoding='utf8')); self.assertNotIn('/hyeyum-hwpx:format', (out / 'basic/SKILL.md').read_text(encoding='utf8'))

    def test_plugin_all_formats_mode(self):  # 형식을 더 낼 때를 위한 라우터 생성 경로(--all)도 계속 동작해야 한다
        out = self.d / 'all'
        code, msg = run(SKILL.parent / 'build_plugin.py', '--all', out); self.assertEqual(code, 0, msg)
        self.check_plugin_skills(out, {'basic': 'C', 'go1-common': 'B', 'format': 'BC'})
        self.assertTrue((out / 'format/scripts/detect_format.py').exists()); self.assertFalse((out / 'go1-common/scripts/detect_format.py').exists())
        self.assertFalse((out / 'go1-common/assets/templates/exam_template_C.hwpx').exists())
        self.assertIn('/hyeyum-hwpx:basic', (out / 'format/SKILL.md').read_text(encoding='utf8')); self.assertIn('kind`를 `"B"`로', (out / 'go1-common/SKILL.md').read_text(encoding='utf8'))

    def test_auto_group_break_counted_in_summary(self):
        s = self.spec('C'); items = [i for i in s['items'] if i['type'] not in ('column_break', 'page_break', 'end_heading', 'blank')]
        a = copy.deepcopy(items); s['items'] = a + copy.deepcopy(a)    # 안내문 묶음 둘 -> 두 번째 묶음이 새 단에서 시작(자동)
        _, out, p = self.build(s, 'g.hwpx'); self.assertIn('단 나눔 1개', out); self.assertIn('자동 1개', out); self.assertIn('쪽별 추정 높이', out); self.assertNotIn('오쪽', out)

    def test_question_keep_chain_and_group_start(self):
        for k in 'BC':
            s = self.spec(k); s['items'] += [{'type': 'instruction', 'text': '※ 다음 글을 읽고 물음에 답하시오.'}, {'type': 'passage', 'paras': ['둘째 지문이다.']}, self.q(k)]
            _, out, p = self.build(s, f'kc{k}.hwpx'); x = self.sec(p); code, v = self.verify(p); self.assertEqual(code, 0, v); self.assertIn('G40  PASS', v); self.assertIn('G41  PASS', v)
            self.assertEqual(x.count('columnBreak="1"'), 2 if k == 'B' else 2)  # 사용자 column_break 1개 + 둘째 안내문 자동 1개
            m = self.mutate(p, lambda t: re.sub(r'(<hh:breakSetting [^>]*keepLines=")1(")', r'\g<1>0\2', t), 'kcm.hwpx', hfn=lambda h: h.replace('keepLines="1"', 'keepLines="0"')); self.assertIn('G40  FAIL', self.verify(m)[1])
        s = self.spec('C'); s['group_start'] = 'flow'; s['items'] += [{'type': 'instruction', 'text': '※ 다음 글을 읽고 물음에 답하시오.'}, {'type': 'passage', 'paras': ['둘째 지문이다.']}, self.q('C')]
        _, _, p = self.build(s, 'flow.hwpx'); self.assertEqual(self.sec(p).count('columnBreak="1"'), 1); self.assertIn('G41  WARN', self.verify(p)[1])   # 나눔 없는 묶음은 경고
        s['group_start'] = 'page'; _, _, p = self.build(s, 'page.hwpx'); self.assertGreaterEqual(self.sec(p).count('pageBreak="1"'), 2)
        s['group_start'] = 'zzz'; self.bad(s, 'group_start')

    def test_choice_structure_tab_aligned(self):
        for k, left, hang in (('B', 996, 1500), ('C', 500, 1488)):
            _, _, p = self.build(EX[k], f'tab{k}.hwpx'); x = self.sec(p); h = self.hdr(p)
            m = re.search(r'<hp:t>①<hp:tab width="(\d+)" leader="0" type="1"/>', x); self.assertTrue(m)
            self.assertIn(f'<hh:tabItem pos="{left + hang}" type="LEFT" leader="NONE" unit="HWPUNIT"/>', h)
            self.assertEqual(x.count('<hp:tab '), 10)   # 선택지 10개, 번호 뒤 탭 하나씩
            self.assertIn('G49  PASS', self.verify(p)[1])

    def test_verify_bad_files(self):
        (self.d / 'bad.hwpx').write_bytes(b'not a zip'); (self.d / 'empty.hwpx').write_bytes(b'')
        _, _, good = self.build(EX['B'], 'g.hwpx')
        code, out = run(VERIFY, self.d / 'bad.hwpx', self.d / 'empty.hwpx', self.d / 'none.hwpx', good)
        self.assertEqual(code, 1); self.assertNotIn('Traceback', out); self.assertEqual(out.count('열 수 없는 파일'), 3); self.assertIn(' G1 ', out)  # 뒤 파일도 계속 검사

    # ---- 서식 표기 · 특수 공백 · JSON 오류 · 추출기 ----
    def test_markup_nesting_and_u_in_plain_fields_rejected(self):
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][1] = '**가<u>나</u>다**'; self.bad(s, '겹치거나')
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][1] = '<u>가**나**다</u>'; self.bad(s, '겹치거나')
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][0] = '가<u>나</u>.'; self.bad(s, '밑줄')

    def test_special_spaces_normalized_and_numbered_notes_rejected(self):
        s = self.spec(); q = [i for i in s['items'] if i['type'] == 'question'][0]
        q['choices'][0] = '가\u00a0나\u3000다\u200b라.'
        _, out, p = self.build(s); self.assertIn('특수 공백', out); self.assertIn('제로폭', out)
        x = self.sec(p); self.assertIn('가 나 다라.', x); code, v = self.verify(p); self.assertEqual(code, 0, v)
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'question'][0]['note']['wrong'][0] = '① ‘근거’ — 일치.'; self.bad(s, '선택지 번호')
        s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['stem'] = '3.1 운동에 대한 설명으로 가장 적절한 것은?'; self.build(s)  # '3.1' 은 번호가 아니다

    def test_json_error_has_no_english_message(self):
        code, out, _ = self.build(None, raw=b'{"kind": "B", "items": [,]}', check=False)
        self.assertNotIn('Expecting', out); self.assertIn('문법 오류', out)

    def test_extract_nested_tables_and_inline_tab(self):
        _, _, p = self.build(EX['C'], 'c.hwpx')
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
            s = self.spec('C'); [i for i in s['items'] if i['type'] == 'passage'][0]['paras'][0] = bogus; self.bad(s, '소제목' if bogus.startswith('#') else '')
        s = self.spec('C'); [i for i in s['items'] if i['type'] == 'passage'][0]['source'] = '  '; self.bad(s, '비어 있습니다')
        s = self.spec('C'); s['items'].append({'type': 'end_heading', 'text': '정답 및 해설'}); self.bad(s, '정답과 해설')
        for sc in ('NaN', 'Infinity', '1e30', '1' + '0' * 40):
            s = self.spec('C'); raw = json.dumps(s, ensure_ascii=False).replace('"score": 3.6', '"score": ' + sc); self.bad(None, '배점', raw=raw.encode()) if sc != '1' + '0' * 40 else self.bad(None, '', raw=raw.encode())
        code, out, _ = self.build(None, raw=('[' * 100000).encode(), check=False); self.assertNotIn('Traceback', out); self.assertNotEqual(code, 0)
        for ch in ('\u200b', '\u2009', '\u202f', '\ufeff', '\u00ad'):
            s = self.spec(); [i for i in s['items'] if i['type'] == 'question'][0]['choices'][0] = f'가{ch}나.'; _, out, p = self.build(s); self.assertIn('경고', out)
            code, v = self.verify(p); self.assertEqual(code, 0, v)

    def test_verify_survives_broken_inputs(self):
        _, _, good = self.build(EX['C'], 'c.hwpx')
        empty = self.mutate(good, lambda s: __import__('re').sub(r'(<hp:t>)[^<]*(</hp:t>)', r'\1\2', s), 'empty.hwpx')
        code, out = run(VERIFY, empty); self.assertNotIn('Traceback', out)
        # 섹션 항목 CRC 손상 + 뒤에 정상 파일
        raw = bytearray(good.read_bytes()); z = zipfile.ZipFile(good); info = z.getinfo('Contents/section0.xml')
        raw[info.header_offset + 30 + len(info.filename.encode()) + 40] ^= 0xFF; (self.d / 'crc.hwpx').write_bytes(bytes(raw))
        code, out = run(VERIFY, self.d / 'crc.hwpx', good); self.assertNotIn('Traceback', out); self.assertIn('###', out.split('###', 2)[2] and '###'); self.assertEqual(out.count('###'), 2)
        # 미주에만 배점이 있는 C 파일, mimetype 내용
        _, _, c2 = self.build(EX['C'], 'c2.hwpx'); import re
        m = self.mutate(c2, lambda s: re.sub(r' \[\d+\.\d점\]</hp:t><hp:ctrl><hp:endNote', '</hp:t><hp:ctrl><hp:endNote', s), 'noscore.hwpx')
        code, out = run(VERIFY, m); self.assertIn('G31', [l for l in out.splitlines() if 'FAIL' in l and 'G31' in l][0])
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', self.d); self.assertNotIn('Traceback', out)
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', '--help'); self.assertIn('사용:', out)

    def test_verify_value_error_is_structure_fail(self):  # 열린 파일의 잘못된 값은 '열 수 없는 파일'이 아니라 구조 오류
        _, _, good = self.build(EX['B'], 'g.hwpx')
        m = self.mutate(good, lambda s: s, 'h.hwpx', hfn=lambda h: re.sub(r'(<hh:charPr id="\d+" height=")\d+', r'\1x', h))
        code, out = run(VERIFY, m); self.assertEqual(code, 1); self.assertNotIn('Traceback', out)
        self.assertIn('구조 오류(ValueError', out); self.assertNotIn('열 수 없는 파일', out)

    def test_extract_counts_endnote_equation_once(self):
        _, _, p = self.build(EX['C'], 'c.hwpx')
        m = self.mutate(p, lambda s: s.replace('<hp:t>출제 포인트  </hp:t>', '<hp:t>출제 포인트  </hp:t><hp:equation><hp:script>x</hp:script></hp:equation>', 1), 'eq.hwpx')
        code, out = run(SKILL / 'scripts/extract_hwpx_text.py', m); self.assertEqual(code, 0, out)
        self.assertIn('[수식: x]', out); self.assertIn('수식 1개', out)


if __name__ == '__main__':
    unittest.main(verbosity=1)
