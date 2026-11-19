"""소스로 넣은 업스트림(server/src/hwpx_automation, python-hwpx-automation 7.3.4)을 지킨다.

- 고친 파일은 고친 줄에 `hyeyum(수정)` 표시가 있어야 한다(Apache-2.0 4조, NOTICE). 표시 없는 파일은 원본과 바이트가 같아야 한다.
- 시험과 서버가 PyPI판이 아니라 이 사본을 읽어야 한다(예전에 시험이 설치된 PyPI판을 읽고 있었던 일).
"""
import hashlib
from pathlib import Path

import hwpx_automation

SRC = Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server" / "src"
MANIFEST = Path(__file__).with_name("upstream_hwpx_automation_7.3.4.sha256")
MARK = "hyeyum(수정)".encode()


def test_tests_import_the_vendored_copy():
    assert Path(hwpx_automation.__file__).resolve().parent == SRC / "hwpx_automation"
    assert hwpx_automation.VENDORED_VERSION == "7.3.4"


def test_unmarked_files_match_upstream_and_none_are_missing():
    upstream = dict(reversed(line.split(maxsplit=1)) for line in MANIFEST.read_text(encoding="utf-8").splitlines())
    upstream = {path.strip(): digest for path, digest in upstream.items()}
    here = {p.relative_to(SRC).as_posix(): p for p in (SRC / "hwpx_automation").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert sorted(set(upstream) - set(here)) == [], "업스트림 파일이 빠졌다"
    assert sorted(set(here) - set(upstream)) == [], "업스트림 사본에 새 파일을 넣지 않는다(우리 코드는 src/ 바로 아래에 둔다)"
    changed = [path for path, file in here.items() if hashlib.sha256(file.read_bytes()).hexdigest() != upstream[path]]
    unmarked = [path for path in changed if MARK not in here[path].read_bytes()]
    assert unmarked == [], f"고친 줄에 hyeyum(수정) 표시가 없다: {unmarked}"
    assert changed, "고친 파일이 하나도 없으면 이 시험의 표시 목록을 다시 본다"
