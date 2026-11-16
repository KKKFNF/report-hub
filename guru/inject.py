"""
블록 주입(멱등).

규칙
 - 기존 <!-- hub:guru:begin:CODE … --> … <!-- hub:guru:end:CODE --> 가 있으면 통째로 교체.
 - 없으면 해당 종목의 첫 '📋 결정카드' 바로 앞에 삽입(코드 있는 헤더 우선, 없으면 첫 결정카드).
   결정카드가 없으면 파일 끝에 추가.
 - 리포트 본문은 한 글자도 바꾸지 않는다(삽입/교체만).
 - 원자적 쓰기(임시파일 → rename), 변경 전 원본은 .bak 로 1회 보관(옵션).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Optional

from .parse_report import RE_CARD_HDR, RE_CODE_IN_PAREN


def _block_re(code: str) -> re.Pattern:
    return re.compile(r"<!--\s*hub:guru:begin:" + code + r"[^>]*-->.*?<!--\s*hub:guru:end:" + code + r"\s*-->\n?", re.S)


def has_block(text: str, code: str) -> bool:
    return _block_re(code).search(text) is not None


def _insert_pos(text: str, code: str) -> int:
    hdrs = list(RE_CARD_HDR.finditer(text))
    for m in hdrs:
        mm = RE_CODE_IN_PAREN.search(m.group("rest"))
        if mm and mm.group(2) == code:
            return m.start()
    for m in hdrs:
        if not RE_CODE_IN_PAREN.search(m.group("rest")):
            return m.start()
    if hdrs:
        return hdrs[0].start()
    return len(text)


def inject_text(text: str, code: str, block: str) -> str:
    rx = _block_re(code)
    if rx.search(text):
        return rx.sub(lambda _m: block, text, count=1)
    pos = _insert_pos(text, code)
    # 결정카드 앞에 빈 줄 하나 확보
    before = text[:pos]
    after = text[pos:]
    if before and not before.endswith("\n\n"):
        before = before.rstrip("\n") + "\n\n"
    if after and not after.startswith("\n"):
        block = block + "\n"
    return before + block + after


def write_atomic(path: str, content: str, backup: bool = False) -> None:
    if backup and os.path.exists(path) and not os.path.exists(path + ".bak"):
        shutil.copy2(path, path + ".bak")
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".guru-", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, path)


def inject_file(path: str, code: str, block: str, backup: bool = False, dry_run: bool = False) -> bool:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new = inject_text(text, code, block)
    if new == text:
        return False
    if not dry_run:
        write_atomic(path, new, backup=backup)
    return True


def remove_block(path: str, code: Optional[str] = None, dry_run: bool = False) -> bool:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if code:
        new = _block_re(code).sub("", text)
    else:
        new = re.sub(r"<!--\s*hub:guru:begin:(\d{6})[^>]*-->.*?<!--\s*hub:guru:end:\1\s*-->\n?", "", text, flags=re.S)
    if new == text:
        return False
    if not dry_run:
        write_atomic(path, new)
    return True
