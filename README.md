# HyeyumEdu agent-plugins

혜윰 교사용 Claude 플러그인 마켓플레이스(`hyeyum`).

| 플러그인 | 버전 | 내용 |
|---|---|---|
| `hyeyum-hwpx` | 1.0.0 | 고등학교 국어 시험지를 한글(.hwpx)로 만드는 스킬 `/hyeyum-hwpx:basic` + 한글 문서 편집 도구(MCP `hyeyum-hwpx-toolkit`) |

## 설치
편집 도구는 [`uv`](https://docs.astral.sh/uv/)로 실행되므로 `uv`가 설치되어 있어야 합니다. 플러그인 하나를 여러 에이전트가 함께 씁니다(스킬은 Agent Skills 표준, 도구는 MCP).

| 에이전트 | 설치 |
|---|---|
| Claude Code | `/plugin install hyeyum-hwpx --marketplace HyeyumEdu/agent-plugins` |
| Claude 앱(Cowork) | Customize → Plugins에서 이 저장소를 마켓플레이스로 추가하고 `hyeyum-hwpx` 설치 |
| Claude 일반 채팅 | 위 플러그인(스킬) + 편집 도구 확장 `hyeyum-hwpx-toolkit-<버전>.mcpb`를 따로 설치. 플러그인 안의 로컬 MCP 서버는 일반 채팅에서 실행되지 않습니다([공식 문서](https://claude.com/docs/plugins/platform-support)) |
| Codex | `codex plugin marketplace add HyeyumEdu/agent-plugins` → `codex plugin add hyeyum-hwpx@hyeyum` |
| Cursor | 설정의 Plugins에 `https://github.com/HyeyumEdu/agent-plugins`를 붙여 넣어 추가 |
| Gemini CLI | 저장소를 받은 뒤 `gemini extensions install <저장소>/plugins/hyeyum-hwpx` |
| 그 밖의 에이전트 | `plugins/hyeyum-hwpx/skills/basic/`을 그 에이전트의 스킬 폴더에 복사하고, `uv run --frozen --directory <저장소>/plugins/hyeyum-hwpx/server src/server.py <다룰 폴더>`를 stdio MCP 서버로 등록 |

다루는 폴더: Claude 플러그인은 작업 폴더 + 문서·바탕화면·다운로드, `.mcpb`는 문서·바탕화면·다운로드 + 설정에서 더한 폴더, Gemini는 작업 폴더, Codex·Cursor는 문서·바탕화면·다운로드. 파일 이름만 쓰면 첫 폴더 기준입니다. 플러그인과 `.mcpb`를 둘 다 켜면 같은 도구가 두 번 보이니 한쪽만 씁니다.

## 저장소 구조
```
.claude-plugin/, .agents/plugins/, .cursor-plugin/   마켓플레이스 목록(Claude, Codex, Cursor)
plugins/hyeyum-hwpx/                배포되는 플러그인
  .claude-plugin/plugin.json        Claude용 매니페스트(MCP 서버 실행 설정 포함)
  plugin.json, mcp.json             표준(Agent Plugins) 매니페스트·MCP 설정: Codex 등
  .cursor-plugin/, gemini-extension.json   Cursor, Gemini CLI용 매니페스트
  skills/basic/                     생성물 (직접 고치지 않는다)
  server/                           편집 도구 서버 소스 + python-hwpx 포크 wheel
exam-skill/                         시험지 스킬 원본과 생성기
  hyeyum-hwpx-format/               원본 (여기를 고친다). 형식 목록 assets/formats.json
  build_plugin.py                   원본 → plugins/hyeyum-hwpx/skills/
  tests/test_skill.py               회귀 시험
toolkit/                            .mcpb 포장(manifest.json, icon.png, build.sh)과 서버 시험(tests/)
```
개발용 작업 파일(골든 시험지, 분석 도구, 포크, 개발 문서, 가상환경)은 이 저장소에 올리지 않는다(`.gitignore`).

## 개발
```
python3 -B exam-skill/build_plugin.py                # 스킬 원본을 고친 뒤 생성물 갱신
python3 -B exam-skill/tests/test_skill.py            # 스킬 시험 (원본과 생성물이 어긋나면 실패)
claude plugin validate plugins/hyeyum-hwpx && claude plugin validate .

# 서버 시험 (골든 대조 시험은 HWPX_GOLDEN 폴더가 없으면 건너뜀)
uv venv --python 3.12 venv && VIRTUAL_ENV=$PWD/venv uv pip install "python-hwpx-automation[mcp]==7.3.4" plugins/hyeyum-hwpx/server/wheels/*.whl pytest
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest toolkit/tests -q -p no:cacheprovider

bash toolkit/build.sh                                # dist/hyeyum-hwpx-toolkit-<버전>.mcpb
PYTHON_HWPX_FORK=<포크 경로> bash toolkit/build.sh    # 포크가 바뀌었을 때: wheel·uv.lock도 갱신
```

### 버전
1.0.0에서 시작하는 유의적 버전. 모든 매니페스트를 같은 번호로 함께 올린다: `plugins/hyeyum-hwpx/`의 `plugin.json`·`.claude-plugin/plugin.json`·`.cursor-plugin/plugin.json`·`gemini-extension.json`, `toolkit/manifest.json`, `plugins/hyeyum-hwpx/server/pyproject.toml`(+ `uv lock`). `bash toolkit/build.sh`가 번호가 다르면 멈춘다. 사용자는 `plugin.json`의 `version`이 바뀌어야 새 판을 받는다.

### 시험지 형식 추가
`exam-skill/hyeyum-hwpx-format/assets/formats.json`에 형식을 더하거나 `"plugin": false`를 지운 뒤 생성 → 시험 → 검증. 형식이 둘 이상이면 형식 고르기 스킬 `/hyeyum-hwpx:format`이 함께 만들어진다. 지금은 `basic`(C형)만 넣고, 고1 공통국어(B형)는 원본에만 있다.

## 라이선스
Apache-2.0. 서버는 [python-hwpx](https://github.com/airmang/python-hwpx)(포크 wheel)와 python-hwpx-automation을 포함한다(`plugins/hyeyum-hwpx/server/NOTICE`).
