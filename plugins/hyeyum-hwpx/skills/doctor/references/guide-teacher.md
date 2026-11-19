# 단계 안내 (명령을 실행할 수 없을 때)

Claude 채팅(웹·데스크톱 앱의 Chat 탭)과 클라우드에서 도는 작업은 선생님 컴퓨터에 설치할 수 없다. 플러그인의 편집 도구도 채팅에서는 켜지지 않는다. 그래서 선생님이 직접 하도록 안내한다.

안내 방법: **한 번에 한 단계만** 말하고, "됐어요?"를 확인한 뒤 다음으로 간다. 누를 메뉴 이름과 붙여 넣을 글은 그대로 보여 준다. 먼저 Windows인지 Mac인지 묻는다.

길은 둘이다. 처음 한 번 선생님에게 고르게 한다.

## 가. Claude 데스크톱 앱의 Code 탭 (권장: 설치를 에이전트가 대신 한다)
유료 요금제(Pro 이상)에서 쓸 수 있다. Code 탭은 선생님 컴퓨터에서 명령을 실행할 수 있어서 doctor 스킬이 설치까지 해 준다.
1. Claude 데스크톱 앱을 설치하고 로그인한다(claude.ai/download).
2. 사이드바 위쪽의 Code 탭을 연다. 프롬프트 아래 환경 선택에서 Local을 고르고, 폴더는 문서 폴더처럼 한글 파일이 있는 곳을 고른다.
3. Customize → Plugins → Add → Add marketplace에 `HyeyumEdu/agent-plugins`를 넣고 `hyeyum-hwpx`를 추가한다.
4. Code 탭에서 "한글 도구 쓸 수 있게 준비해 줘"라고 말한다.

## 나. Claude 채팅에서 확장(.mcpb)으로 쓰기 (데스크톱 앱 필요, 웹에서는 안 됨)
1. `uv` 설치: Windows는 시작 메뉴에서 "PowerShell"을 열고, Mac은 "터미널"을 열어 아래 한 줄을 붙여 넣고 Enter를 누른다.
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - Mac: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. https://github.com/HyeyumEdu/agent-plugins/releases/latest 에서 `hyeyum-hwpx-toolkit-<버전>.mcpb` 파일을 받는다.
3. 받은 파일을 더블클릭하거나 Claude 창에 끌어다 놓는다(또는 설정 → 확장(Extensions) → 고급 설정 → Install Extension…). 설치 화면에서 설치를 누른다.
4. Claude 앱을 **완전히 종료했다가** 다시 연다(창만 닫으면 안 된다).
5. 새 채팅에서 "문서 폴더의 한글 파일 목록 보여 줘"라고 해서 목록이 나오면 끝이다.

선생님이 막혔다고 하면 `references/troubleshooting.md`를 읽고 맞는 줄을 쉬운 말로 안내한다.
