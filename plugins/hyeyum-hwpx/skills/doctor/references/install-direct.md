# 직접 설치 (선생님 컴퓨터에서 명령을 실행할 수 있을 때)

Claude 데스크톱 앱의 Code 탭, Claude Code, Codex처럼 선생님 컴퓨터(Windows·macOS)에서 명령을 실행할 수 있을 때의 순서다.

## 1. `uv`가 있는지
`uv --version`을 실행한다. 안 되면 기본 설치 위치를 직접 확인한다.
- Windows: `& "$env:USERPROFILE\.local\bin\uv.exe" --version` (winget으로 깔았으면 `where.exe uv`)
- macOS: `~/.local/bin/uv --version` (Homebrew로 깔았으면 `/opt/homebrew/bin/uv` 또는 `/usr/local/bin/uv`)

기본 위치에는 있는데 `uv --version`만 안 되면 이미 설치된 것이다. 다시 설치하지 말고 4(다시 연결)로 간다. 이미 켜져 있던 앱과 창은 설치 전의 PATH를 계속 쓰기 때문이다.

## 2. `uv` 설치 (1에서 못 찾았을 때만)
무엇을 왜 설치하는지 한 문장으로 알리고 허락을 받은 뒤 공식 설치 명령을 그대로 실행한다. Codex는 인터넷을 쓰는 명령에 허락을 묻는다(설치 명령도 그렇다).
- Windows(PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- macOS(터미널): `curl -LsSf https://astral.sh/uv/install.sh | sh`

설치 뒤 1의 기본 위치로 `--version`을 실행해 확인한다. 파이썬은 따로 설치하지 않는다. `uv`가 맞는 파이썬을 알아서 내려받는다.

이 명령이 막히면(보안 프로그램, 실행 정책) 다른 공식 방법을 쓴다: Windows `winget install --id=astral-sh.uv -e`, macOS `brew install uv`(Homebrew가 있을 때만).

## 3. 플러그인 설치 (도구가 목록에 없었을 때)
- Claude 데스크톱 앱의 Code 탭: 플러그인 `hyeyum-hwpx`가 없으면 설치를 안내한다. 먼저 claude.ai 또는 앱의 Customize → Plugins → Add → Add marketplace에 `HyeyumEdu/agent-plugins`를 넣고 `hyeyum-hwpx`를 추가한다(계정에 추가한 플러그인은 Claude Code에서도 쓰인다). 그다음 Code 탭 프롬프트 옆 **+** → **Add plugins**(또는 **Plugins** → **Browse plugins**)에서 `hyeyum-hwpx`가 설치·켜짐인지 확인한다.
- Claude Code(터미널): `claude plugin install hyeyum-hwpx --marketplace HyeyumEdu/agent-plugins`.
- Codex: `codex plugin marketplace add HyeyumEdu/agent-plugins`로 마켓플레이스를 더하고, 플러그인 화면(`/plugins`)에서 `hyeyum-hwpx`를 설치한다.

## 4. 다시 연결
- Claude Code(터미널): `/mcp`에서 `hyeyum-hwpx-toolkit`을 고르고 **Reconnect**. 실패한 서버는 잠시 다시 시도하지 않으므로 기다리지 말고 Reconnect를 누른다. 그래도 안 보이면 Claude Code를 다시 시작한다.
- Claude 데스크톱 앱의 Code 탭: 앱을 완전히 종료했다가 다시 열고 새 세션을 시작한다.
- Codex: 새 세션을 시작한다.

## 5. 확인
`list_available_documents`를 불러 결과로 확인한다. 처음 켤 때는 파이썬과 필요한 부품을 내려받느라 오래 걸릴 수 있다. 1~2분 기다렸다가 다시 연결해 본다. 계속 안 되면 `references/troubleshooting.md`를 읽는다.
