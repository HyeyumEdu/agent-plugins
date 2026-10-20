#!/usr/bin/env python3
"""원본 exam-skill/hyeyum-hwpx-format 에서 플러그인 스킬을 만들어 plugins/hyeyum-hwpx/skills/ 에 쓴다.
  skills/format/       형식을 아직 안 정한 요청을 받는 라우터(모든 형식·detect_format.py 포함, 형식이 둘 이상일 때만)
  skills/<형식 id>/    형식을 고정한 전용 명령 /hyeyum-hwpx:<형식 id> (그 형식의 템플릿·예시·조각·문서 내용만)
Claude Desktop 에서 스킬 폴더가 따로 올라갈 수 있어 각 스킬은 scripts 를 복사해 스스로 완결된다.
문서(SKILL.md·references/*.md)의 `<!-- format:<id>[,<id>…] -->`…`<!-- /format -->` 구간은 그 id 를 가진 스킬에만 남는다.
  id 는 형식 id, `router`(라우터에만), `pinned`(전용 명령에만). 라우터는 router 와 들어간 모든 형식의 구간을 남긴다.
  구간 표시가 줄 머리에 혼자 있으면 줄 단위, 아니면 줄 안에서 그 부분만.
사용: python3 build_plugin.py [--all] [출력_폴더(기본: plugins/hyeyum-hwpx/skills)]
  --all  "plugin": false 형식까지 넣는다(미리 보기·시험용)"""
import json, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / 'hyeyum-hwpx-format'
PLUGIN = 'hyeyum-hwpx'
SCRIPTS = ['scripts/build_exam.py', 'scripts/verify_exam.py', 'scripts/extract_hwpx_text.py']
DOCS = ['references/exam-json.md', 'references/format-spec.md']
EXCLUDE = '서술형·다른 과목, 파일 없이 채팅으로만 출제, 공문 등 일반 문서, 워드 변환은 제외.'
BLOCK_LINES = re.compile(r'^<!-- format:([\w,-]+) -->\n(.*?)^<!-- /format -->\n', re.S | re.M)
BLOCK_INLINE = re.compile(r'<!-- format:([\w,-]+) -->(.*?)<!-- /format -->', re.S)


def keep_blocks(text, ids):
    pick = lambda m: m.group(2) if ids & set(m.group(1).split(',')) else ''
    out = BLOCK_INLINE.sub(pick, BLOCK_LINES.sub(pick, text))
    assert '<!-- format:' not in out and '<!-- /format -->' not in out, '닫히지 않았거나 겹친 format 구간'
    return out


def copy(rel, d):
    (d / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(SRC / rel, d / rel)


def build(out, include_all=False):
    formats = json.loads((SRC / 'assets/formats.json').read_text(encoding='utf-8'))
    if not include_all: formats = [f for f in formats if f.get('plugin', True)]
    router = len(formats) > 1  # 형식이 하나면 고를 것이 없다
    body = re.match(r'---\n.*?\n---\n(.*)', (SRC / 'SKILL.md').read_text(encoding='utf-8'), re.S).group(1)
    if out.exists(): shutil.rmtree(out)
    router_desc = ('고등학교 국어 시험지(5지선다 선택형)를 한글(.hwpx) 파일로 만들 때, 어느 형식으로 만들지 정하지 않았거나 올린 시험지 파일에서 형식을 알아내야 할 때 쓴다. '
                   '시험지·문제지·중간·기말고사·모의고사, 보기 상자, 정답·해설 미주, 기존 시험지 서식 정리. 등록된 형식: '
                   + ', '.join(f'{f["title"]}(/{PLUGIN}:{f["id"]})' for f in formats) + f'. {EXCLUDE}')
    skills = [dict(id='format', desc=router_desc, ids={'router'} | {f['id'] for f in formats}, formats=formats, extra=['scripts/detect_format.py'])] if router else []
    for f in formats:
        desc = (f'{f["title"]} 형식의 고등학교 국어 시험지(5지선다)를 한글(.hwpx)로 만들 때 쓴다. {f["when"]}. 특징: {f["traits"]}. '
                + ((f'다른 형식이 필요하면 /{PLUGIN}:format. ' if f.get('default') else f'형식이 다르거나 정해지지 않았으면 /{PLUGIN}:format. ') if router else '') + EXCLUDE)
        skills.append(dict(id=f['id'], desc=desc, ids={'pinned', f['id']}, formats=[f], extra=[]))
    for s in skills:
        d = out / s['id']
        for rel in SCRIPTS + s['extra']: copy(rel, d)
        for rel in DOCS:
            (d / rel).parent.mkdir(parents=True, exist_ok=True); (d / rel).write_text(keep_blocks((SRC / rel).read_text(encoding='utf-8'), s['ids']), encoding='utf-8')
        (d / 'assets').mkdir(exist_ok=True)
        (d / 'assets/formats.json').write_text(json.dumps(s['formats'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for k in [f['kind'] for f in s['formats']]:
            for rel in [f'assets/examples/example_{k}.json', f'assets/templates/exam_template_{k}.hwpx'] + [str(p.relative_to(SRC)) for p in sorted((SRC / 'assets/snippets').glob(f'{k}_*.xml'))]:
                copy(rel, d)
        desc = s['desc'].replace('\n', ' ')
        assert len(desc) <= 1024, (s['id'], len(desc))  # Agent Skills 표준의 description 상한
        (d / 'SKILL.md').write_text(f'---\nname: {s["id"]}\ndescription: {desc}\n---\n{keep_blocks(body, s["ids"])}', encoding='utf-8')
    return [s['id'] for s in skills]


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--all']
    target = Path(args[0]).resolve() if args else HERE.parent / 'plugins' / PLUGIN / 'skills'
    print('만든 스킬:', ', '.join(f'/{PLUGIN}:{i}' for i in build(target, '--all' in sys.argv)), '->', target)
