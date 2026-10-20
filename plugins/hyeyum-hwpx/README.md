# 혜윰학원 한글 플러그인

국어 시험지를 한글 문서(HWPX)로 만들고, 이미 있는 한글 문서를 읽고 수정할 수 있어요. Claude, Codex, Cursor, Gemini CLI 등 Agent Skills와 MCP를 지원하는 에이전트에서 쓸 수 있어요.

## 쓰는 법
- **시험지 만들기**: 지문·문항·정답·해설을 주고 "시험지 만들어 줘"라고 하거나 스킬 `basic`을 부릅니다(Claude는 `/hyeyum-hwpx:basic`). 에이전트가 내용을 정리해 스킬의 스크립트로 서식이 맞춰진 `.hwpx`를 만들고 규칙 검사까지 합니다.
- **한글 문서 고치기**: 문단 모양, 표, 미주·각주, 글 중간 수식·그림, 스타일, 쪽 설정을 편집 도구(MCP `hyeyum-hwpx-toolkit`)로 고칩니다. 고치기 전에 백업(.bak)을 만듭니다.

## 설치
편집 도구는 [`uv`](https://docs.astral.sh/uv/)로 실행되므로 `uv`가 설치되어 있어야 합니다.

| 에이전트 | 설치 |
|---|---|
| Claude Code | `/plugin install hyeyum-hwpx --marketplace HyeyumEdu/agent-plugins` |
| Claude 앱(Cowork) | Customize → Plugins에서 `HyeyumEdu/agent-plugins`를 마켓플레이스로 추가하고 `hyeyum-hwpx` 설치. 일반 채팅에서는 편집 도구가 돌지 않으니 `.mcpb` 확장을 따로 설치 |
| Codex | `codex plugin marketplace add HyeyumEdu/agent-plugins` → `codex plugin add hyeyum-hwpx@hyeyum` |
| Cursor | 설정의 Plugins에 저장소 주소 `https://github.com/HyeyumEdu/agent-plugins`를 붙여 넣어 추가 |
| Gemini CLI | 저장소를 받은 뒤 `gemini extensions install <저장소>/plugins/hyeyum-hwpx` |
| 그 밖의 에이전트 | 스킬 폴더 `skills/basic/`을 그 에이전트의 스킬 폴더에 복사하고, MCP 설정에 `uv run --frozen --directory <이 폴더>/server src/server.py <다룰 폴더>`를 stdio 서버로 등록 |

## 데이터
모든 처리는 사용자 컴퓨터(또는 에이전트의 코드 실행 환경)에서 이루어지고, 이 플러그인은 문서를 외부 서버로 보내지 않습니다. 편집 도구는 허용된 폴더(에이전트에 따라 작업 폴더, 문서·바탕화면·다운로드) 안의 파일만 열 수 있습니다. 첫 실행 때 `uv`가 PyPI에서 의존 패키지를 내려받습니다.

## 라이선스
Apache-2.0 (`server/LICENSE`, `server/NOTICE`)
