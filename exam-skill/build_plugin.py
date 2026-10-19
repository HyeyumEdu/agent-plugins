#!/usr/bin/env python3
"""원본 exam-skill/hyeyum-hwpx-format 에서 플러그인 스킬을 만들어 plugins/hyeyum-hwpx/skills/ 에 쓴다.
  skills/format/       형식을 아직 안 정한 요청을 받는 라우터(모든 형식·detect_format.py 포함, 형식이 둘 이상일 때만)
  skills/<형식 id>/    형식을 고정한 전용 명령 /hyeyum-hwpx:<형식 id> (그 형식의 템플릿·예시·조각만)
Claude Desktop 에서 스킬 폴더가 따로 올라갈 수 있어 각 스킬은 scripts 를 복사해 스스로 완결된다.
SKILL.md 의 절 제목·문구("## 먼저 정할 것: B형 / C형", "## 새 시험지를 만드는 순서", "두 형 모두", "C형이면 ")에 기대므로 바꾸면 여기도 고친다.
사용: python3 build_plugin.py [--all] [출력_폴더(기본: plugins/hyeyum-hwpx/skills)]
  --all  "plugin": false 형식까지 넣고 라우터도 만든다(미리 보기·시험용)"""
import json, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / 'hyeyum-hwpx-format'
PLUGIN = 'hyeyum-hwpx'
COMMON = ['scripts/build_exam.py', 'scripts/verify_exam.py', 'scripts/extract_hwpx_text.py', 'references/exam-json.md', 'references/format-spec.md']
EXCLUDE = '서술형·다른 과목, 파일 없이 채팅으로만 출제, 공문 등 일반 문서, 워드 변환은 제외.'


def table_column(body, kind):  # `## 먼저 정할 것` 표(열: 항목 | B형 | C형)에서 이 형식 칸을 "- 항목: 값" 줄로 뽑는다
    col = {'B': 1, 'C': 2}.get(kind)
    if col is None: return []
    rows = [[x.strip() for x in r.strip('|').split('|')] for r in body.splitlines() if r.startswith('|') and not r.startswith(('|---', '| |'))]
    return [f'- {c[0]}: {c[col]}' for c in rows if len(c) > col]


def router_body(body, formats):
    dflt = next(f for f in formats if f.get('default'))
    rows = '\n'.join(f'| `/{PLUGIN}:{f["id"]}` | {f["title"]}{" (기본)" if f.get("default") else ""} | {f["kind"]} | {f["when"]} |' for f in formats)
    sec = (f'## 형식 고르기 (이 명령은 `/{PLUGIN}:format`)\n'
           '형식마다 전용 명령이 있다. 사용자가 전용 명령(아래 표)으로 불렀다면 그 명령이 처리하고, 이 스킬은 **형식을 아직 정하지 않은 요청**을 받는다. 다음 순서로 형식을 정한다.\n'
           '1. 말에서 단서를 찾는다: 학교·학년·과목, "정답만 필요" 또는 "배점·해설까지" 같은 말을 표의 "이럴 때"와 맞춰 본다.\n'
           '2. 사용자가 `.hwpx`를 올렸거나 "이 파일처럼"이라고 하면 `python3 ${CLAUDE_SKILL_DIR}/scripts/detect_format.py 파일.hwpx`로 가장 닮은 형식을 확인한다. `확실`이면 따르고, `가능성 높음`이면 사용자에게 한 번 확인하고, `판별 불가`이면 3번으로 간다.\n'
           f'3. 단서가 없으면 기본 형식(`/{PLUGIN}:{dflt["id"]}`, {dflt["title"]})으로 만들고 그렇게 했다고 알린다. 형식 이름(B/C)이나 명령 이름은 교사에게 쓰지 말고, 필요하면 "정답 번호만 필요하신가요, 문항별 배점·해설까지 넣을까요?" 처럼 묻는다. 정답 번호만 필요하다는 말이 있으면 그에 맞는 형식을 쓴다.\n'
           f'형식을 정했으면 아래 절차를 따르되 JSON의 `kind`를 그 형식의 kind로 쓴다. 사용자에게는 앞으로 같은 형식을 바로 쓰려면 해당 명령(`/{PLUGIN}:<id>`)을 쓰면 된다고 한 번 알린다.\n\n'
           '| 명령 | 형식 | kind | 이럴 때 |\n|---|---|---|---|\n' + rows + '\n\n')
    return body.replace('## 먼저 정할 것: B형 / C형', sec + '## 형식별 차이', 1)


def pinned_body(body, f, router):
    i, j = body.index('## 먼저 정할 것: B형 / C형'), body.index('## 새 시험지를 만드는 순서')
    common = next(p for p in body[i:j].split('\n\n') if p.startswith('두 형 모두'))
    sec = (f'## 이 명령의 형식: {f["title"]} ({f["kind"]}형)\n'
           f'이 명령(`/{PLUGIN}:{f["id"]}`)은 형식을 **{f["kind"]}형으로 고정**한다. 형식을 묻지 말고 JSON의 `kind`를 `"{f["kind"]}"`로 쓴다. 이 형식의 특징:\n'
           + '\n'.join(table_column(body[i:j], f['kind'])) + '\n\n' + common +
           f'\n\n제목(학교·학년·과목·차수)은 사용자에게 받는다. 없으면 `고1 국어`처럼 학년과 과목만 쓴다.' + (f' 다른 형식이 필요하면 `/{PLUGIN}:format`이나 해당 형식 명령을 쓰게 안내한다.' if router else '') + ' '
           f'(이 명령에는 {f["kind"]}형 템플릿·예시만 들어 있으므로 문서의 다른 형식 예시 파일은 없다.)\n\n')
    out = body[:i] + sec + body[j:]
    out = out.replace('두 형 모두 맨 끝에', '이 형식은 맨 끝에', 1)
    out = out.replace('예시는 `assets/examples/example_B.json`, `example_C.json`', f'예시는 `assets/examples/example_{f["kind"]}.json`', 1)
    return out.replace('C형이면 ', '', 1) if f['kind'] == 'C' else out.replace(', C형이면 문항별 배점과 해설(출제 포인트, 정답 해설, 정답을 뺀 선택지 4개의 오답 분석)', '', 1)


def copy(rel, d):
    (d / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(SRC / rel, d / rel)


def build(out, include_all=False):
    formats = json.loads((SRC / 'assets/formats.json').read_text(encoding='utf-8'))
    if not include_all: formats = [f for f in formats if f.get('plugin', True)]
    router = len(formats) > 1  # 형식이 하나면 고를 것이 없다
    body = re.match(r'---\n.*?\n---\n(.*)', (SRC / 'SKILL.md').read_text(encoding='utf-8'), re.S).group(1)
    body = body.replace("'*hyeyum-hwpx-format*'", f"'*{PLUGIN}*'")
    if out.exists(): shutil.rmtree(out)
    skills = [dict(id='format', desc=None, body=router_body(body, formats), kinds=[f['kind'] for f in formats], extra=['scripts/detect_format.py', 'assets/formats.json'])] if router else []
    for f in formats:
        desc = (f'{f["title"]} 형식의 고등학교 국어 시험지(5지선다)를 한글(.hwpx)로 만들 때 쓴다. {f["when"]}. 특징: {f["traits"]}. '
                + ((f'다른 형식이 필요하면 /{PLUGIN}:format. ' if f.get('default') else f'형식이 다르거나 정해지지 않았으면 /{PLUGIN}:format. ') if router else '') + EXCLUDE)
        skills.append(dict(id=f['id'], desc=desc, body=pinned_body(body, f, router), kinds=[f['kind']], extra=[]))
    router_desc = ('고등학교 국어 시험지(5지선다 선택형)를 한글(.hwpx) 파일로 만들 때, 어느 형식으로 만들지 정하지 않았거나 올린 시험지 파일에서 형식을 알아내야 할 때 쓴다. '
                   '시험지·문제지·중간·기말고사·모의고사, 보기 상자, 정답·해설 미주, 기존 시험지 서식 정리. 등록된 형식: '
                   + ', '.join(f'{f["title"]}(/{PLUGIN}:{f["id"]})' for f in formats) + f'. {EXCLUDE}')
    for s in skills:
        d = out / s['id']
        for rel in COMMON + s['extra']: copy(rel, d)
        for k in s['kinds']:
            for rel in [f'assets/examples/example_{k}.json', f'assets/templates/exam_template_{k}.hwpx'] + [str(p.relative_to(SRC)) for p in sorted((SRC / 'assets/snippets').glob(f'{k}_*.xml'))]:
                copy(rel, d)
        desc = (s['desc'] or router_desc).replace('\n', ' ')
        assert len(desc) <= 1024, (s['id'], len(desc))  # Agent Skills 표준의 description 상한
        (d / 'SKILL.md').write_text(f'---\nname: {s["id"]}\ndescription: {desc}\n---\n{s["body"]}', encoding='utf-8')
    return [s['id'] for s in skills]


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--all']
    target = Path(args[0]).resolve() if args else HERE.parent / 'plugins' / PLUGIN / 'skills'
    print('만든 스킬:', ', '.join(f'/{PLUGIN}:{i}' for i in build(target, '--all' in sys.argv)), '->', target)
