"""wb_mail v6 联系人路由模块。

优化点：
- 加载时校验邮箱格式，无效邮箱告警但不阻断
- 支持更多分隔符（中英文分号、逗号、顿号、换行）
- resolve 增加"未匹配线体"日志，快速定位漏配
- 兼容车间列有前后空白的情况
"""
from __future__ import annotations

import re
from typing import Any

from openpyxl import load_workbook

from wb_mail import config as C

log = C.log

_ANY_WK = "__any__"
_EMAIL_VALID = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SPLIT_RE = re.compile("[;,、；，\n\r]")


def _extract_emails(text: Any) -> list[str]:
    """从 '姓名<邮箱>; 姓名2<邮箱2>' 等格式中提取合法邮箱列表。"""
    s = "" if text is None else str(text)
    candidates = re.findall(C.EMAIL_RE, s)
    if not candidates and "@" in s:
        candidates = [tok.strip() for tok in _SPLIT_RE.split(s)]
    # 去重保序
    seen: set[str] = set()
    valid: list[str] = []
    for e in candidates:
        e = e.strip()
        if not _EMAIL_VALID.fullmatch(e):
            continue
        e_lower = e.lower()
        if e_lower not in seen:
            seen.add(e_lower)
            valid.append(e)
    return valid


def _find_header(ws):
    """取 sheet 第一行作为表头。"""
    for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
        return [("" if v is None else str(v).strip()) for v in row]
    return []


def _find_contact_sheet(workbook):
    for sheet in workbook.worksheets:
        header = _find_header(sheet)
        if "线体" in header:
            return sheet, header
    return None, []


def _row_cell(row: tuple, index: int | None):
    if index is None or index >= len(row):
        return None
    return row[index]


def _contact_record(row: tuple, indexes: dict[str, int | None]) -> dict | None:
    line_value = _row_cell(row, indexes["line"])
    if line_value is None or not str(line_value).strip():
        return None
    line = str(line_value).strip()
    workshop = str(_row_cell(row, indexes["workshop"]) or "").strip()
    owner_raw = _row_cell(row, indexes["owner"])
    cc_raw = _row_cell(row, indexes["cc"])
    owners = _extract_emails(owner_raw)
    copied = _extract_emails(cc_raw)
    if owner_raw and "@" in str(owner_raw) and not owners:
        log.warning("名单行[%s/%s] 负责人邮箱解析失败: %s",
                    workshop, line, str(owner_raw)[:60])
    return {
        "line": line,
        "workshop": workshop,
        "owner": owners,
        "cc": copied,
    }


def load_contacts(path: str) -> dict[tuple[str, str], dict]:
    """读取名单 xlsx，返回 {(车间,线体):{owner,cc,line,workshop}}。

    仅当名单行未填写车间时，建立 {(__any__,线体):...} 通用索引。
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws, hdr = _find_contact_sheet(wb)
        if ws is None:
            raise ValueError(f"未找到含『线体』表头的 sheet: {path}")

        idx_line = hdr.index("线体")
        idx_wk = hdr.index("车间") if "车间" in hdr else None
        idx_owner = next((i for i, v in enumerate(hdr) if v.startswith("负责人")), None)
        idx_cc = next((i for i, v in enumerate(hdr) if v.startswith("抄送")), None)
        if idx_owner is None:
            raise ValueError(f"名单缺少负责人列: {path}")

        indexes = {
            "line": idx_line,
            "workshop": idx_wk,
            "owner": idx_owner,
            "cc": idx_cc,
        }
        routing: dict[tuple[str, str], dict] = {}

        for row in ws.iter_rows(min_row=2, values_only=True):
            rec = _contact_record(row, indexes)
            if rec is None:
                continue
            key = ((rec["workshop"], rec["line"]) if rec["workshop"]
                   else (_ANY_WK, rec["line"]))
            if key in routing:
                raise ValueError(f"名单存在重复路由: {key[0]}/{key[1]}")
            routing[key] = rec

        log.info("名单加载完成: %d 条", len(routing))
        return routing

    finally:
        wb.close()


def resolve(contacts: dict, workshop: str, line: str) -> tuple[list[str], list[str]]:
    """返回 (owner_emails, cc_emails)；未命中返回 ([], [])。

    匹配策略：精确(车间+线体) → 回退(__any__+线体)。
    """
    rec = contacts.get((workshop, line))
    if not rec:
        rec = contacts.get((_ANY_WK, line))
    if not rec:
        log.debug("未匹配线体: (%s, %s)", workshop, line)
        return ([], [])
    return (list(rec["owner"]), list(rec["cc"]))
