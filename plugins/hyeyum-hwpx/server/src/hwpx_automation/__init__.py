# SPDX-License-Identifier: Apache-2.0
"""Stable Python facade for HWPX task automation.

The base distribution deliberately does not import the optional MCP SDK.  MCP
transport users install ``python-hwpx-automation[mcp]`` and start
``hwpx-automation-mcp``; Python callers can use the curated task facade below.
"""

from importlib import import_module
from typing import Any

_CANONICAL_DISTRIBUTION = "python-hwpx-automation"
# hyeyum(수정): 이 패키지는 hyeyum-hwpx-toolkit에 소스로 들어 있어 설치 메타데이터가 없다.
# 버전을 여기 한 곳에 적고 quality·workflow도 이 값을 쓴다(못 읽으면 쓰기 게이트가 막힌다). 업스트림 태그를 바꾸면 함께 바꾼다.
VENDORED_VERSION = "7.3.4"


def _resolve_version() -> str:
    return VENDORED_VERSION


__version__ = _resolve_version()

_API_EXPORTS = {
    "CanonicalFormFillInput",
    "ComposeResult",
    "DocumentPlan",
    "DocumentStylePreset",
    "EvalPlanContent",
    "FormFillAnalyzeOptions",
    "FormFillPlanInput",
    "Rubric",
    "analyze_form_fill",
    "apply_form_fill",
    "compose_exam",
    "create_document_from_plan",
    "fill_evalplan",
    "finalize_evalplan",
    "normalize_document_plan",
    "parse_evalplan_review",
    "parse_exam_markdown",
    "validate_document_plan",
}


def __getattr__(name: str) -> Any:
    """Load the task facade on first use without creating package cycles."""

    if name not in _API_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.api"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _API_EXPORTS)


__all__ = ["__version__", *sorted(_API_EXPORTS)]
