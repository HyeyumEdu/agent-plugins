"""잠금 파일(uv.lock)이 선생님 PC 4종에서 소스 빌드 없이 설치되는지: 그 PC가 고를 패키지마다 맞는 wheel이 있어야 한다.

PC에 컴파일러(Rust·C)가 없으니 wheel이 없으면 설치가 실패한다(cryptography 최신판에 Intel Mac·Windows ARM wheel이 없었던 일).
pyproject.toml의 [tool.uv] required-environments·no-build-package가 이를 막고, 이 시험은 잠금 결과를 네트워크 없이 확인한다.
"""
import tomllib
from pathlib import Path

import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

SERVER = Path(__file__).resolve().parents[2] / "plugins" / "hyeyum-hwpx" / "server"
LOCK = tomllib.loads((SERVER / "uv.lock").read_text(encoding="utf-8"))
# (sys_platform, platform_machine, wheel 플랫폼 태그에 들어 있어야 할 조각)
PCS = {
    "mac-arm64": ("darwin", "arm64", ("arm64", "universal2")),
    "mac-x86_64": ("darwin", "x86_64", ("x86_64", "universal2")),
    "win-amd64": ("win32", "AMD64", ("win_amd64",)),
    "win-arm64": ("win32", "ARM64", ("win_arm64",)),
}
PYTHONS = ("3.11", "3.12", "3.13", "3.14")


def env(pc: str, py: str) -> dict[str, str]:
    sys_platform, machine, _ = PCS[pc]
    return {"sys_platform": sys_platform, "platform_machine": machine, "python_version": py, "python_full_version": f"{py}.0",
            "platform_system": {"darwin": "Darwin", "win32": "Windows"}[sys_platform], "os_name": {"darwin": "posix", "win32": "nt"}[sys_platform],
            "implementation_name": "cpython", "platform_python_implementation": "CPython", "extra": ""}


def chosen(e: dict[str, str]) -> list[dict]:
    """프로젝트에서 출발해 의존성(표지 포함)을 따라가며 이 환경이 실제로 설치할 패키지 항목을 모은다."""
    by_name: dict[str, list[dict]] = {}
    for p in LOCK["package"]:
        by_name.setdefault(canonicalize_name(p["name"]), []).append(p)

    def pick(name: str) -> dict:
        cands = by_name[name]
        if len(cands) == 1:
            return cands[0]
        hits = [c for c in cands if any(Marker(m).evaluate(e) for m in c.get("resolution-markers", []))]
        assert len(hits) == 1, f"{name}: 이 환경에 맞는 잠금 항목이 {len(hits)}개"
        return hits[0]

    root = next(p for p in LOCK["package"] if p.get("source", {}).get("virtual") or p.get("source", {}).get("editable"))
    seen, todo, out = set(), [root], []
    while todo:
        p = todo.pop()
        key = (p["name"], p["version"] if "version" in p else "")
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        for dep in p.get("dependencies", []):
            if "marker" in dep and not Marker(dep["marker"]).evaluate(e):
                continue
            cands = by_name[canonicalize_name(dep["name"])]
            if "version" in dep:
                cands = [c for c in cands if c["version"] == dep["version"]]
                todo.append(cands[0])
            else:
                todo.append(pick(canonicalize_name(dep["name"])))
    return out


def wheel_fits(filename: str, pc: str, py: str) -> bool:
    _, _, _, tags = parse_wheel_filename(filename)
    frags = PCS[pc][2]
    cp = "cp3" + py.split(".")[1]
    for t in tags:
        if t.platform == "any":
            return True
        if not any(f in t.platform for f in frags):
            continue
        if t.interpreter == cp or (t.abi == "abi3" and t.interpreter.startswith("cp3") and int(t.interpreter[3:]) <= int(py.split(".")[1])):
            return True
        if t.interpreter in ("py3", "py2.py3"):
            return True
    return False


@pytest.mark.parametrize("pc", sorted(PCS))
@pytest.mark.parametrize("py", PYTHONS)
def test_every_chosen_package_has_a_wheel(pc, py):
    e = env(pc, py)
    missing = []
    for p in chosen(e):
        src = p.get("source", {})
        if src.get("virtual") or src.get("editable") or src.get("path"):
            continue  # 프로젝트 자신과 번들 포크 wheel(py3-none-any)
        wheels = [w["url"].rsplit("/", 1)[1] for w in p.get("wheels", []) if "url" in w]
        if not any(wheel_fits(w, pc, py) for w in wheels):
            missing.append(f"{p['name']} {p['version']}")
    assert not missing, f"{pc} / Python {py}: wheel 없음 → 소스 빌드가 필요해 설치 실패: {missing}"


def test_platform_settings_stay_in_pyproject():
    s = (SERVER / "pyproject.toml").read_text(encoding="utf-8")
    cfg = tomllib.loads(s)["tool"]["uv"]
    assert len(cfg["required-environments"]) == 4 and "cryptography" in cfg["no-build-package"]
    pins = [d for d in tomllib.loads(s)["project"]["dependencies"] if "==" in d]
    assert [Requirement(d).name for d in pins] == ["mcp"], "버전 고정은 mcp만(업스트림이 실행 중에 검사한다)"
