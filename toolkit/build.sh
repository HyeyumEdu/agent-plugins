#!/bin/bash
# 플러그인의 서버(plugins/hyeyum-hwpx/server)를 Claude Desktop 확장(.mcpb)으로 포장한다. 사용법: bash toolkit/build.sh
# PYTHON_HWPX_FORK=<포크 경로>를 주면 포크에서 wheel을 다시 만들어 넣고 uv.lock을 갱신한다(포크가 바뀌었을 때만).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); SRV=$ROOT/plugins/hyeyum-hwpx/server
VER=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$ROOT/toolkit/manifest.json")
# 에이전트별 매니페스트와 서버 버전이 하나라도 다르면 멈춘다(설치처마다 다른 판이 나가지 않게)
python3 - "$ROOT" "$VER" <<'PY'
import json, re, sys
root, ver = sys.argv[1:]
p = f"{root}/plugins/hyeyum-hwpx"
found = {f: json.load(open(f"{p}/{f}"))["version"] for f in ["plugin.json", ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json", "gemini-extension.json"]}
found["server/pyproject.toml"] = re.search(r'^version = "(.*)"', open(f"{p}/server/pyproject.toml").read(), re.M)[1]
bad = {f: v for f, v in found.items() if v != ver}
sys.exit(f"버전 불일치(toolkit/manifest.json = {ver}): {bad}" if bad else 0)
PY
if [ -n "${PYTHON_HWPX_FORK:-}" ]; then
  rm -f "$SRV"/wheels/*.whl; (cd "$PYTHON_HWPX_FORK" && uv build --wheel -o "$SRV/wheels" >/dev/null)
  WHEEL=$(basename "$SRV"/wheels/*.whl); sed -i "s|path = \"wheels/.*\"|path = \"wheels/$WHEEL\"|" "$SRV/pyproject.toml"
  (cd "$SRV" && uv lock -q)
fi
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
cp -r "$SRV"/{src,wheels,pyproject.toml,uv.lock,LICENSE,NOTICE} "$ROOT"/toolkit/{manifest.json,icon.png} "$STAGE"/
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$ROOT/dist"; rm -f "$ROOT"/dist/hyeyum-hwpx-toolkit-*.mcpb
(cd "$STAGE" && npx -y @anthropic-ai/mcpb validate manifest.json | tail -1 && npx -y @anthropic-ai/mcpb pack . "$ROOT/dist/hyeyum-hwpx-toolkit-$VER.mcpb" | grep -E "package size|Output")
