"""Claude 플러그인 매니페스트의 허용 폴더 설정(userConfig.extra_folder).

Code 탭·Claude Code는 플러그인을 켤 때와 /config에서 이 값을 묻는다. Cowork는 묻지 않고, 기본값이 없는 값을 참조하는
MCP 서버는 아예 띄우지 않으므로(claude.com/docs/plugins/platform-support) 기본값 ""가 꼭 있어야 한다.
빈 인수는 서버가 건너뛴다(server.workspace_roots).
"""
import json
from pathlib import Path

import server

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / ".claude-plugin" / "plugin.json"


def test_extra_folder_option_is_optional_and_reaches_the_server():
    manifest = json.loads(PLUGIN.read_text(encoding="utf-8"))
    option = manifest["userConfig"]["extra_folder"]
    assert option["type"] == "directory" and option["default"] == "" and not option.get("required")
    args = manifest["mcpServers"]["hyeyum-hwpx-toolkit"]["args"]
    assert args.index("${user_config.extra_folder}") == args.index("${CLAUDE_PROJECT_DIR}") + 1  # 작업 폴더 다음(파일 이름만 쓰면 작업 폴더 기준)


def test_empty_or_missing_extra_folder_is_skipped(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    assert server.workspace_roots([str(project), "", str(tmp_path / "없음")], {}) == [str(project.resolve())]
