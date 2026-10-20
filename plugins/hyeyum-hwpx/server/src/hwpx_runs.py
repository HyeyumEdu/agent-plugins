"""run 분할: 글 일부에만 글자 서식을 줄 때 run을 쪼갠다.

업스트림의 쪼개기(core.formatting._split_run)는 run 전체를 복제해서 hp:t 안의 탭(hp:tab)과 run 안의 미주·개체(hp:ctrl 등)가
조각마다 복제되고 글자 수도 탭을 빼고 세어 범위가 어긋난다. 여기서는 글자를 한컴 라이브러리와 같은 방식(탭·줄바꿈 등은 1글자)으로
세어 hp:t를 조각에 나누고, hp:t가 아닌 자식(ctrl, tbl ...)은 원래 자리의 글자 위치가 속한 조각에 하나씩만 둔다.
"""
from copy import deepcopy
from typing import Any

from hwpx.oxml._document_primitives import _TEXT_INLINE_ATOMS, _clear_paragraph_layout_cache, _element_local_name
from hwpx.oxml.namespaces import HP

_T = f"{HP}t"


def _tokens(t: Any) -> list[tuple[str, Any, int]]:
    """hp:t 내용을 ("text", 글, 길이) / ("unit", 요소, 길이) 순서로. 탭 등 원자는 1글자, 다른 자식은 쪼개지 않는 한 덩어리."""
    out: list[tuple[str, Any, int]] = []
    if t.text:
        out.append(("text", t.text, len(t.text)))
    for child in t:
        name = _element_local_name(child)
        length = len(_TEXT_INLINE_ATOMS[name]) if name in _TEXT_INLINE_ATOMS else len("".join(child.itertext()))
        out.append(("unit", child, length))
        if child.tail:
            out.append(("text", child.tail, len(child.tail)))
    return out


def _piece(t: Any, tokens: list[tuple[str, Any, int]], start: int, lo: int, hi: int) -> Any | None:
    """원래 위치 start에서 시작하는 tokens 중 글자 위치 [lo, hi)에 드는 부분만 담은 새 hp:t (없으면 None)."""
    piece = t.makeelement(_T, dict(t.attrib))
    last = None
    position = start
    for kind, value, length in tokens:
        if kind == "text":
            chunk = value[max(lo - position, 0):max(min(hi - position, length), 0)]
            if chunk:
                if last is None:
                    piece.text = (piece.text or "") + chunk
                else:
                    last.tail = (last.tail or "") + chunk
        elif lo <= position < hi:
            last = deepcopy(value)
            last.tail = None
            piece.append(last)
        position += length
    return piece if (piece.text or len(piece)) else None


def split_run(run_obj: Any, local_start: int, local_end: int, char_pr_id_ref: str) -> None:
    """run의 글자 위치 [local_start, local_end)에 char_pr_id_ref를 주고, 앞뒤 나머지는 원래 글자 모양을 유지한다."""
    run = run_obj.element
    total = len(run_obj.text or "")
    start, end = max(0, min(local_start, total)), max(0, min(local_end, total))
    if total == 0 or start >= end:
        return
    if start == 0 and end == total:
        run_obj.char_pr_id_ref = char_pr_id_ref
        return
    original = run.get("charPrIDRef")
    segments = [(lo, hi, ref) for lo, hi, ref in ((0, start, original), (start, end, char_pr_id_ref), (end, total, original)) if lo < hi]
    runs = [run.makeelement(run.tag, {**run.attrib, **({"charPrIDRef": ref} if ref is not None else {})}) for _, _, ref in segments]

    position = 0
    for child in run:
        if child.tag == _T:
            tokens = _tokens(child)
            for (lo, hi, _), target in zip(segments, runs):
                piece = _piece(child, tokens, position, lo, hi)
                if piece is not None:
                    target.append(piece)
            position += sum(length for _, _, length in tokens)
        else:  # ctrl, tbl, ... 한 개만: 자기 앞까지의 글을 담은 조각에(맨 앞 개체는 첫 조각에)
            index = next((i for i, (lo, hi, _) in enumerate(segments) if lo < position <= hi), 0)
            runs[index].append(deepcopy(child))
    parent = run.getparent()
    where = parent.index(run)
    for offset, piece in enumerate(runs):
        parent.insert(where + offset, piece)
    parent.remove(run)
    paragraph = run_obj.paragraph
    _clear_paragraph_layout_cache(paragraph.element)
    paragraph.section.mark_dirty()


def _divide(tokens: list[tuple[str, Any, int]], cut: int) -> tuple[list[tuple[str, Any, int]], list[tuple[str, Any, int]]]:
    """tokens를 글자 위치 cut에서 앞뒤로 나눈다. cut에 걸친 글은 쪼개고, 쪼갤 수 없는 덩어리는 통째로 뒤로 보낸다. 폭 0인 덩어리는 cut에서도 앞에 남는다."""
    left: list[tuple[str, Any, int]] = []
    right: list[tuple[str, Any, int]] = []
    position = 0
    for kind, value, length in tokens:
        if right:
            right.append((kind, value, length))
        elif position + length <= cut:
            left.append((kind, value, length))
        elif kind == "text" and position < cut:
            left.append((kind, value[:cut - position], cut - position))
            right.append((kind, value[cut - position:], position + length - cut))
        else:
            right.append((kind, value, length))
        position += length
    return left, right


def _fill_t(t: Any, tokens: list[tuple[str, Any, int]]) -> None:
    """hp:t의 내용을 tokens로 다시 채운다(요소는 옮겨 오고 꼬리 글은 토큰 쪽 것만 남긴다)."""
    for child in list(t):
        t.remove(child)
    t.text = None
    last = None
    for kind, value, _ in tokens:
        if kind == "text":
            if last is None:
                t.text = (t.text or "") + value
            else:
                last.tail = (last.tail or "") + value
        else:
            value.tail = None
            t.append(value)
            last = value


def split_at(paragraph: Any, position: int) -> int:
    """문단 글자 위치 position(0..글자 수, 세는 법은 split_run과 같다)에서 run을 둘로 쪼개고 새 run을 넣을 문단 자식 번호를 돌려준다.

    그 자리에 이미 있는 개체(ctrl, tbl, 수식 ...)는 앞에 남는다: 돌려준 번호는 position번째 글자를 담은 hp:t 바로 앞이다.
    position이 글자 수와 같으면 마지막 run 뒤, 범위 밖이면 ValueError. 쪼갤 수 없는 덩어리(글이 든 표시 요소) 한가운데면 그 앞에서 끊는다.
    """
    root = paragraph.element
    seen = 0
    last_run = -1
    for index, run in enumerate(root):
        if run.tag != f"{HP}run":
            continue
        last_run = index
        for t in run:
            if t.tag != _T:
                continue
            tokens = _tokens(t)
            length = sum(size for _, _, size in tokens)
            if seen + length > position:
                where = _cut(root, run, t, tokens, position - seen)
                paragraph.section.mark_dirty()
                return where
            seen += length
    if position != seen:
        raise ValueError(f"position {position} is outside the paragraph text (0..{seen})")
    return last_run + 1 if last_run >= 0 else len(root)


def _cut(root: Any, run: Any, t: Any, tokens: list[tuple[str, Any, int]], offset: int) -> int:
    """run 안의 hp:t `t`를 글자 위치 offset 앞에서 끊어 run을 둘로 나누고(앞에 끊을 것이 없으면 그대로) 뒤쪽 run의 번호를 돌려준다."""
    children = list(run)
    at = children.index(t)
    if offset == 0 and at == 0:
        return root.index(run)
    tail = run.makeelement(run.tag, dict(run.attrib))
    if offset:
        left, right = _divide(tokens, offset)
        piece = t.makeelement(_T, dict(t.attrib))
        _fill_t(t, left)
        _fill_t(piece, right)
        tail.append(piece)
    else:
        tail.append(t)
    for child in children[at + 1:]:
        tail.append(child)
    where = root.index(run) + 1
    root.insert(where, tail)
    _clear_paragraph_layout_cache(root)
    return where


def patch_upstream() -> None:
    """업스트림 format_text 도구도 같은 쪼개기를 쓰게 한다(업스트림 7.3.4의 core.formatting._split_run 교체)."""
    from hwpx_automation.core import formatting

    formatting._split_run = split_run
    _keep_single_backup()


def _keep_single_backup() -> None:
    """백업은 `<이름>.hwpx.bak` 하나(직전 쓰기 직전 상태)만 남긴다: 업스트림의 `.bak.1`~`.bak.5` 회전을 끈다(사용자 결정 2026-10-20)."""
    from hwpx_automation.core import transactions
    from hwpx_automation.ops_services.save_policy import SavePolicy

    # 함수 기본값 하나를 바꾸면 이름으로 가져다 쓴 호출처(handlers._shared·save_policy·ops_services.transactions)가 모두 따른다.
    transactions.rotate_and_backup.__kwdefaults__["max_backups"] = 0
    rotate = SavePolicy._rotate_and_backup_exact
    if not getattr(rotate, "single_backup", False):  # 이 경로는 max_backups를 인수로 받으므로(hwpx_ops가 5를 넘김) 값을 덮어쓴다
        def single(self: Any, target: Any, **kwargs: Any) -> Any:
            return rotate(self, target, **{**kwargs, "max_backups": 0})

        single.single_backup = True  # type: ignore[attr-defined]
        SavePolicy._rotate_and_backup_exact = single  # type: ignore[method-assign]
