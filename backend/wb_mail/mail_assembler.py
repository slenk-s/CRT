"""wb_mail v6 邮件组装模块。

结构：只有「总览区」和「明细区」两块，参数一律跟批次走。
- 总览区：每批次一行，展示机型名/色坐标/RGB上限/Γ±容差/亮度/面板/侧标；
- 明细区：每批次各自一张表，展示该批次完整参数，但总览已合并展示的
  字段不再重复（由 OVERVIEW_COLS 的 covers 声明自动去重）；
- 排除区：MES 工单/条码残留（工单编号、工单号 FA2609040212 等动态键）
  按静态名单 + 正则模式双重排除；无线模组、WiFi6、蓝牙必须保留；
- 防折行：总览单元格与明细「参数」列施加 <nobr> + inline nowrap +
  U+00A0/U+2011 三重防护，明细「值」列允许折行以完整展示长文本；
- 抓取失败批次高亮标注（红色），列出失败原因；
- 响应式 meta 标签，手机端表格可横向滚动而非溢出。
"""
from __future__ import annotations

import re
from typing import Any

from wb_mail import config as C

log = C.log

# 动态键排除：工单号（FA2609040212 / MZ2609040216）等由 MES 子表首列
# 转成的字段名，每天随计划变化，静态清单追不上，只能按正则匹配。
_EXCLUDE_RE = [re.compile(p) for p in C.DETAIL_EXCLUDE_PATTERNS]


def _is_excluded(k: str, excludes: set[str]) -> bool:
    """静态名单 + 正则模式双重排除。"""
    return k in excludes or any(rx.search(k) for rx in _EXCLUDE_RE)

_C = "#2b6cb0"
_FAIL_COLOR = "#c0392b"
_OK_COLOR = "#276749"

# 单元格基础样式。邮件客户端对 <style>/class 支持参差（Outlook 桌面版为 Word
# 引擎），故关键排版一律走 inline style，<style> 仅作兜底。
_BASE = "padding:6px 8px;border:1px solid #cbd5e0;font-size:13px;vertical-align:top"
# 总览表 / 明细表「参数」列：强制单行，禁止折行
_NW = _BASE + ";white-space:nowrap"
# 明细表「值」列：允许折行以完整展示长文本，不截断、不加省略号
_WRAP = (_BASE + ";white-space:normal;word-break:break-word;"
         "overflow-wrap:anywhere;min-width:220px")

_TH = ("th{background:%s;color:#fff;padding:6px 8px;border:1px solid "
       "#cbd5e0;text-align:left;font-weight:600;white-space:nowrap}" % _C)
_TD = "td{" + _BASE + "}"
_TBL = ("table{border-collapse:collapse;font-size:13px;width:auto;"
        "table-layout:auto}")
_STYLE = ("<style>" + _TH + _TD + _TBL +
          "</style>"
          '<meta name="viewport" content="width=device-width,initial-scale=1">')


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _g(d: dict | None, key: str) -> str:
    if d is None:
        return ""
    v = d.get(key)
    return "" if v is None else str(v).strip()


def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


_NBSP = chr(160)          # 不可断行空格
_NBHY = chr(8209)         # 不可断行连字符（渲染为普通连字符，但不断行）


def _nb(s: Any) -> str:
    """按需施加防折行，避免无断行点的内容被白加标签。

    仅当文本含空格或连字符（真实断行机会）时才套三层防护：
      1. <nobr> 元素级约束；2. inline white-space:nowrap；
      3. U+00A0 / U+2011 不可断行字符。
    纯数字/无空格值（如 540、QD、143/128/143）直接输出，
    实测可省掉约 2/3 的标签开销。
    副作用：被处理过的值复制出来是不换行字符，非 ASCII 空格/连字符。
    """
    t = _esc(s)
    if " " not in str(s) and "-" not in str(s):
        return t
    inner = t.replace(" ", _NBSP).replace("-", _NBHY)
    return "<span style='white-space:nowrap'><nobr>" + inner + "</nobr></span>"


def _thead(h: str) -> str:
    return "<thead>%s</thead>" % h


# ---------------------------------------------------------------------------
# 总览表列定义
# ---------------------------------------------------------------------------
def _color_cell(d: dict | None, b: str) -> str:
    groups = []
    for name in ("Normal", "Warm", "Warm2", "Cool"):
        x = _g(d, name + " 色坐标X")
        y = _g(d, name + " 色坐标Y")
        if x or y:
            groups.append("%s/%s" % (x or "-", y or "-"))
    return " ".join(groups) or "-"


def _rgb_cell(d: dict | None, b: str) -> str:
    vals = [_g(d, "白平衡 R 上限"), _g(d, "白平衡 G 上限"), _g(d, "白平衡 B 上限")]
    return "/".join(vals) if any(vals) else "-"


def _gamma_cell(d: dict | None, b: str) -> str:
    gm = _g(d, "目标 Gamma")
    tol = _g(d, "Gamma 容差")
    if not gm:
        return "-"
    return ("%s±%s" % (gm, tol)) if tol else gm


# 总览列：(表头, 取值函数, covers=该列已合并展示的源字段)
# covers 让明细表自动跳过总览已呈现的字段，同一数据不再出现两次；
# 新增/调整总览列时只需改这里，明细去重自动跟随，无需另维护排除清单。
_COLOR_KEYS = [n + " 色坐标" + ax
               for n in ("Normal", "Warm", "Warm2", "Cool") for ax in ("X", "Y")]

OVERVIEW_COLS = [
    # 批次仅作行标识，covers 留空：明细的「批次」值带"（清洗后 X）"标注，
    # 与总览的裸批次号信息量不同，故不被总览覆盖、予以保留。
    ("批次", lambda d, b: b, []),
    ("机型名", lambda d, b: _g(d, "机型名") or "-", ["机型名"]),
    ("目标色坐标 N/W/W2/C(X/Y)", _color_cell, _COLOR_KEYS),
    ("RGB上限", _rgb_cell, ["白平衡 R 上限", "白平衡 G 上限", "白平衡 B 上限"]),
    ("目标Γ±容差", _gamma_cell, ["目标 Gamma", "Gamma 容差"]),
    ("最大亮度", lambda d, b: _g(d, "最大亮度") or "-", ["最大亮度"]),
    ("面板", lambda d, b: _g(d, "面板类型") or "-", ["面板类型"]),
    ("侧标", lambda d, b: _g(d, "侧标样式") or "-", ["侧标样式"]),
]

# ---------------------------------------------------------------------------
# 表格渲染
# ---------------------------------------------------------------------------
def _disp_units(s: Any) -> float:
    """估算显示宽度单位：CJK/全角符号按 2 单位，其余按 1 单位。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(s))


def _col_widths(titles: list[str], grid: list[list[str]]) -> list[int]:
    """按「表头与所有批次取值中最长者」定宽，像素级预留内边距。

    配合 table-layout:fixed 使用：列宽本身足够容纳整串内容，
    因此即便渲染端剥离 white-space:nowrap / <nobr> 并规范化 NBSP，
    也没有触发折行的空间——这是字符级防护之外的第四层、且是唯一
    不依赖客户端支持的根治手段。
    """
    widths = []
    for j, t in enumerate(titles):
        u = _disp_units(t)
        for row in grid:
            if j < len(row):
                u = max(u, _disp_units(row[j]))
        widths.append(int(min(360, max(56, u * 7 + 22))))
    return widths


def _overview_table(pairs: list[tuple[str, dict | None]]) -> str:
    titles = [h for h, _fn, _ks in OVERVIEW_COLS]
    grid: list[list[str] | None] = [
        None if d is None else [fn(d, batch) for _h, fn, _ks in OVERVIEW_COLS]
        for batch, d in pairs]
    widths = _col_widths(titles, [g for g in grid if g])
    # 宽度必须 CSS + HTML 呈现属性双写：Outlook 桌面版为 Word 引擎，
    # 会忽略 table-layout 与 <col style='width'> 这类 CSS，只认 width="N" 属性。
    total = sum(widths)
    colgroup = "<colgroup>%s</colgroup>" % "".join(
        "<col width='%d' style='width:%dpx'>" % (w, w) for w in widths)
    head = "".join("<th width='%d'>%s</th>" % (w, _nb(h))
                   for w, h in zip(widths, titles))
    rows = []
    for (batch, _d), g in zip(pairs, grid):
        if g is None:
            rows.append(
                "<tr><td width='%d' style='%s'>%s</td><td colspan='%d' "
                "style='%s;color:%s;font-weight:bold'>抓取失败</td></tr>"
                % (widths[0], _NW, _esc(batch), len(titles) - 1, _NW, _FAIL_COLOR))
            continue
        rows.append("<tr>%s</tr>" % "".join(
            "<td width='%d' style='%s'>%s</td>" % (w, _NW, _nb(v))
            for w, v in zip(widths, g)))
    # 外层 overflow-x:auto：列宽按内容预留后，若总宽超过邮件阅读区，
    # 不换行而是左右拖动查看（用户明确要求"总览不可换行，可以左右拉动"）。
    # Outlook 桌面版(Word 引擎)不认 overflow，故仍保留 table-layout:fixed +
    # 逐列 width 预留 + <nobr>/nowrap/NBSP 四重防护，两边都不会折行。
    return ("<div style='overflow-x:auto;-webkit-overflow-scrolling:touch;"
            "max-width:100%%'>"
            "<table border='0' cellpadding='0' cellspacing='0' "
            "style='border-collapse:collapse;table-layout:fixed;white-space:nowrap;"
            "width:%dpx;min-width:%dpx'>%s%s%s</table>"
            "<div style='clear:both'></div></div>"
            % (total, total, colgroup, _thead(head), "".join(rows)))


def _overview_covered(d: dict, batch: str) -> set[str]:
    """该批次在总览表中已实际展示（值非空）的源字段集合。

    仅当总览单元格真有值时才算覆盖；总览显示为 "-" 的，明细仍保留原行，
    避免把数据藏成两边都没有。
    """
    out: set[str] = set()
    for _h, fn, ks in OVERVIEW_COLS:
        if not ks:
            continue
        v = fn(d, batch)
        if v and v != "-":
            out.update(ks)
    return out


def _detail_table(batch: str, d: dict,
                  excludes: set[str] | None = None) -> str:
    """明细表：该批次完整参数，逐个批次自行展示，不做跨批次折叠。

    「参数」列强制单行；「值」列允许折行以完整展示长文本。
    仅两类字段不出现在明细中：
      - excludes：非电视参数或 MES 残留表头行（工单号/条码类型/WiFi 等）；
      - covered：总览表已合并展示的源字段（色坐标 8 项、RGB 3 项、Γ±容差 2 项…）。
    """
    excludes = excludes or set()
    covered = _overview_covered(d, batch) - excludes
    rows = ["<tr><th>参数</th><th>值</th></tr>"]
    for k, v in d.items():
        if _is_excluded(k, excludes) or k in covered:
            continue
        rows.append("<tr><td style='%s'>%s</td><td style='%s'>%s</td></tr>"
                    % (_NW, _nb(k), _WRAP, _esc(v)))
    if covered:
        rows.append("<tr><td colspan='2' style='%s;color:#718096;font-style:italic'>"
                    "（另有 %d 个已在上方总览表合并展示，故此处不再重复）</td></tr>"
                    % (_WRAP, len(covered)))
    return ("<h3 style='border-left:4px solid %s;padding-left:8px;"
            "margin:20px 0 6px;font-size:16px'>批次 %s 参数</h3>"
            "<table>%s</table>" % (_C, _esc(batch), "".join(rows)))


def _degraded_note(plan_file_date: str) -> str:
    """降级数据醒目提示条。plan_file_date 由 smb_plan 生成，已是「M月D日」格式。"""
    return ("<p style='margin:0 0 8px;padding:8px 12px;background:#fffbeb;"
            "border:1px solid #f6d38b;border-radius:4px;font-size:13px;"
            "color:#92400e'><b>⚠ 降级数据</b>：本邮件使用 %s 的计划文件生成，"
            "并非目标日期计划，请勿按当天计划解读。</p>"
            % _esc(plan_file_date or "较早日期"))


def _summary_bar(results: list[dict[str, Any]]) -> str:
    """生成顶部摘要信息条。"""
    total = len(results)
    ok = sum(1 for r in results if r.get("fields"))
    fail = total - ok
    elapsed = sum(r.get("duration_s", 0) for r in results)
    parts = [f"<p style='margin:0 0 8px;padding:8px 12px;background:#ebf8ff;"
             f"border-radius:4px;font-size:13px'>"]
    parts.append(f"<b>共 {total} 个批次</b>")
    if ok:
        parts.append(f" | <span style='color:{_OK_COLOR}'>成功 {ok}</span>")
    if fail:
        parts.append(f" | <span style='color:{_FAIL_COLOR}'>失败 {fail}</span>")
    parts.append(f" | 抓取耗时 {elapsed:.0f}s")
    parts.append("</p>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def assemble(车间: str, line: str, date_str: str, degraded: bool,
             plan_file_date: str,
             batches: list[tuple[str, dict | None]],
             fetch_results: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """组装邮件。返回 {"subject", "body"}。

    batches: [(batch_no, fields_dict_or_None), ...]
    fetch_results: 可选，fetch_parallel 的原始返回（含 duration/error），用于摘要。
    degraded: 是否使用了回退的旧计划文件；为真时标题追加 (计划:M月D日)
              并在正文顶部加「降级数据」提示条。
    plan_file_date: 实际使用的计划文件日期（M月D日），仅 degraded 时展示。
    """
    title_suffix = ("(计划:%s)" % plan_file_date
                    if (degraded and plan_file_date) else "")
    subject = (f"【WB参数】{车间}-{line} {date_str} "
               f"批次参数({len(batches)}个){title_suffix}")

    parts: list[str] = [_STYLE,
                        "<div style=\"font-family:Microsoft YaHei,PingFang SC,"
                        "Arial,sans-serif;color:#222;font-size:14px;line-height:1.5\">"
                        ]
    # 标题
    parts.append(f"<h2 style='color:{_C};margin:6px 0 12px'>"
                 f"{_esc(车间)} {_esc(line)} 白平衡参数 {_esc(date_str)}{title_suffix}</h2>")

    # 摘要条
    if fetch_results:
        parts.append(_summary_bar(fetch_results))
    else:
        parts.append(f"<p style='margin:0 0 10px;color:#555'>共 {len(batches)} 个批次</p>")
    if degraded and plan_file_date:
        parts.append(_degraded_note(plan_file_date))

    # 总览表
    parts.append(_overview_table(batches))

    # 明细区：每个批次各自展示完整参数，不做跨批次折叠
    for batch, d in batches:
        if d is None:
            # 失败批次显示失败详情
            err = ""
            if fetch_results:
                for r in fetch_results:
                    if r.get("batch") == batch and r.get("error"):
                        err = r["error"]
                        break
            parts.append(
                f"<h3 style='border-left:4px solid {_FAIL_COLOR};padding-left:8px;"
                f"margin:20px 0 6px;font-size:16px'>批次 {_esc(batch)} "
                f"<span style='color:{_FAIL_COLOR}'>[抓取失败]</span></h3>"
                f"<p style='color:{_FAIL_COLOR};margin:0 0 10px'>原因: {_esc(err or '未知')}</p>")
            continue
        parts.append(_detail_table(batch, d, excludes=C.DETAIL_EXCLUDE_KEYS))

    parts.append("</div>")
    body = "".join(parts)
    return {"subject": subject, "body": body}

# ---------------------------------------------------------------------------
# 与邮件同构的 Markdown 渲染（供对话/命令行输出复用）
# 对话回复必须与邮件一致：同一份 OVERVIEW_COLS、同一套 covered 去重、
# 同一份 DETAIL_EXCLUDE_KEYS。另写一套必然漂移（历史上就漂过一次）。
# ---------------------------------------------------------------------------
def _md(s: Any) -> str:
    """Markdown 单元格：转义竖线、压掉换行，避免撑破表格。"""
    return str(s).replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def _markdown_overview(pairs: list[tuple[str, dict | None]]) -> list[str]:
    titles = [heading for heading, _fn, _keys in OVERVIEW_COLS]
    grid: list[list[str]] = []
    for batch, fields in pairs:
        if fields is None:
            grid.append([batch, "抓取失败"] + [""] * (len(titles) - 2))
        else:
            grid.append([fn(fields, batch) for _heading, fn, _keys in OVERVIEW_COLS])

    def cell_width(value: str) -> int:
        return int(round(float(_disp_units(value))))

    widths = [
        max([cell_width(titles[index])]
            + [cell_width(row[index]) for row in grid]) + 1
        for index in range(len(titles))
    ]

    def padded(value: str, width: int) -> str:
        return str(value) + " " * max(0, width - cell_width(value))

    block = [
        "|" + "|".join(padded(title, widths[index])
                         for index, title in enumerate(titles)) + "|",
        "|" + "|".join("-" * width for width in widths) + "|",
    ]
    block.extend(
        "|" + "|".join(padded(value, widths[index])
                         for index, value in enumerate(row)) + "|"
        for row in grid
    )
    return ["\n#### 总览\n", "> 等宽视图，不换行；超宽时可左右拖动查看。\n",
            "```text", *block, "```"]


def _markdown_details(pairs: list[tuple[str, dict | None]]) -> list[str]:
    out: list[str] = []
    excludes = set(C.DETAIL_EXCLUDE_KEYS)
    for batch, fields in pairs:
        out.append("\n#### 批次 %s 参数\n" % _md(batch))
        if fields is None:
            out.append("**抓取失败**")
            continue
        covered = _overview_covered(fields, batch) - excludes
        rows = [(key, value) for key, value in fields.items()
                if not _is_excluded(key, excludes) and key not in covered]
        out.extend(["| 参数 | 值 |", "|------|----|"])
        out.extend("| %s | %s |" % (_md(key), _md(value)) for key, value in rows)
        if covered:
            out.extend(["", "（另有 %d 个已在上方总览表合并展示，故此处不再重复）"
                        % len(covered)])
    return out


def to_markdown(pairs: list[tuple[str, "dict | None"]], *,
                title: str = "WB参数", note: str = "") -> str:
    """渲染成「摘要 + 总览表 + 逐批明细表」，结构与 assemble() 完全一致。

    pairs: [(批次号, fields_dict 或 None), ...]，与 assemble() 同形。
    """
    ok = sum(1 for _b, d in pairs if d)
    fail = len(pairs) - ok
    out: list[str] = ["### %s" % title,
                      "共 %d 个批次 | 成功 %d | 失败 %d" % (len(pairs), ok, fail)]
    if note:
        out.append("> %s" % note)

    out.extend(_markdown_overview(pairs))
    out.extend(_markdown_details(pairs))
    return "\n".join(out)
