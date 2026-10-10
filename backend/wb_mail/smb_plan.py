#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SMB 生产计划自动取数（wb_mail 自持版，由 aging-matching 固化链路内联而来）。

只读连接惠州 TV 工厂计划共享盘（Windows/SMB），按“显式计划日期”取 5 车间当天的干净版
生产计划 xlsx，供 `daily_job.py` 筛选目标日期批次。

边界：
- 日期不猜：必须显式传入计划文件名里的日期 plan_date=YYYY-MM-DD（计划发布日），老化目标日
  由调用方的 date 决定；默认不做 D/D-1/回退最近版等推断，仅在显式 allow_recent=True 时
    向过去回退最近 lookback_days 日内的干净版计划，并逐文件标记 degraded。
- 只取干净版：先按文件名模板精确匹配；精确缺失时仅当“无干扰后缀”候选唯一才采用，否则报错。
- 凭据安全：口令仅从环境变量（默认 SMB_PASSWORD）或 getpass 交互读取，绝不写代码/配置/日志。
  共享与车间模板放 `assets/smb_config.json`，服务器只从 `WB_SMB_HOST` 注入。函数签名不使用疑似密钥命名的参数，
  可选覆盖统一走 opts 字典（如 opts={"user":..,"cred":..}）。
- 只读：仅列目录 + 下载，不写/删/改共享盘；遇权限错误直接报错，不换身份绕过。

用法：
    export SMB_PASSWORD=<共享盘口令>
    python3 -m wb_mail.smb_plan --plan-date 2026-09-16 --out ./plan_files
退出码：0 成功；2 取数失败（缺凭据/连接失败/车间未命中/多候选）。
"""
import argparse
import getpass
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'assets', 'smb_config.json')

# 干扰版本命名：普通子串 + 正则变体（序号/括号/(1)/V\d 等），命中即视为非权威。
JUNK_SUBSTR = ["待核对", "待会签", "待审核", "待签", "副本", "最新", "草稿",
               "ok版", "OK版", "~$"]
JUNK_RE = re.compile(
    "|".join([
        r"OK\s*[版（(]", r"ok\s*[版（(]", r"[（(]\s*OK",
        r"第\s*[2-9]\s*[份版]", r"[（(]\s*[2-9]\s*[)）]",
        r"-\s*\(\d", r"\(\d\)", r"（\d）", r"V\d",
    ]),
    re.IGNORECASE,
)


class SMBError(RuntimeError):
    pass


class PlanNotFound(SMBError):
    """指定计划日期（及其回退窗口）内没有干净的整机计划。

    与连接失败/多候选区分开：调用方（见 aging_bridge）据此决定是否降级回退，
    而不是把"当天没发计划"误当成"SMB 连不上"。
    """


def _load_smb_cfg(path=CONFIG_PATH):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)['smb']


class SMBConfig:
    def __init__(self, server, share, base_subpath, user, cred, workshops):
        self.server = server
        self.share = share
        self.base_subpath = base_subpath
        self.user = user
        self._cred = cred                       # 仅内存，勿写日志/落盘
        self.workshops = workshops

    @classmethod
    def from_env(cls, cfg_path=CONFIG_PATH, opts=None, interactive=True):
        cfg = _load_smb_cfg(cfg_path)
        opts = opts or {}
        user = opts.get('user') or os.environ.get('SMB_USER') or cfg.get('user_default') or ''
        env_name = cfg.get('password_env', 'SMB_PASSWORD')
        cred = opts.get('cred') or os.environ.get(env_name)
        if not cred and interactive:
            cred = getpass.getpass('SMB 口令（%s，仅内存不落盘）: ' % env_name)
        if not user or not cred:
            raise SMBError('缺少 SMB 凭据：需设 SMB_USER（默认 %s）与 %s，或交互输入；勿把口令写入代码/配置/日志。'
                           % (cfg.get('user_default'), env_name))
        server = (os.environ.get('WB_SMB_HOST') or '').strip()
        if not server:
            raise SMBError('缺少 SMB 主机：请设 WB_SMB_HOST（由 T盘 wb_endpoints.env 注入）')
        return cls(server, cfg['share'], cfg['base_subpath'], user, cred, cfg['workshops'])

    def share_path(self, *parts):
        B = chr(92)                             # 单反斜杠，避免转义歧义
        head = B + B + self.server + B + self.share       # \\server\share
        segs = [self.base_subpath] + [p for p in parts if p]
        joined = B.join(s.strip(B) for s in segs)
        return head + B + joined


def _to_dt(plan_date):
    if isinstance(plan_date, datetime):
        return plan_date
    return datetime.strptime(str(plan_date), '%Y-%m-%d')


def expected_filename(template, plan_date):
    d = _to_dt(plan_date)
    return template.replace('{M}', str(d.month)).replace('{D}', str(d.day))


def date_token(template, plan_date):
    name = expected_filename(template, plan_date)
    m = re.search(r"\d+月\d+[日号]", name)
    return m.group(0) if m else None


def _is_clean(name):
    if name.lower().endswith('.xlsx') is False:
        return False
    for s in JUNK_SUBSTR:
        if s in name:
            return False
    return not JUNK_RE.search(name)


def _client(cfg):
    try:
        import smbclient
    except ImportError as e:
        raise SMBError('未安装 smbclient/smbprotocol：请先 pip install smbprotocol。') from e
    smbclient.ClientConfig(**{'username': cfg.user, 'password': cfg._cred})
    return smbclient


def _list_dirs(smbclient, path, missing_ok=False):
    """列目录；missing_ok=True 时，目录不存在视为"本路径无内容"返回空。

    年份归档子目录（如 ...\\2026）并非每个车间都存在：一/二/三/四车间当日计划
    直接放在车间根目录，只有七车间走 2026 子目录。若把缺失年份目录当致命错误，
    这些车间会在"扫归档目录"这一步整体失败——历史上 9/21 就是这么全批未发的。
    """
    out = []
    try:
        for e in smbclient.scandir(path):
            out.append((e.name, bool(e.is_dir())))
    except Exception as e:
        msg = str(e)
        if missing_ok and ("No such file" in msg or "0xc0000034" in msg):
            return out
        raise SMBError("SMB 目录读取失败(%s): %s" %
                       (type(e).__name__, msg[:160])) from e
    return out


# SMB 共享冲突：文件被 Excel 等进程占用时返回 STATUS_SHARING_VIOLATION。
_LOCK_MARKERS = ("0xc0000043", "being used by another process",
                 "Sharing violation", "共享冲突")


def _read_bytes(smbclient, path, attempts=3):
    """读取远端文件字节，容忍"文件被占用"。

    计划员常把当天计划用 Excel 打开，此时默认 share_access(None) 会被 smbclient
    按"不与他人共享"处理，触发 0xc0000043 共享冲突，导致整批任务中止。
    这里按 share_access 由紧到松逐个降级尝试，并对持续占用做短暂重试。
    """
    last = None
    for attempt in range(attempts):
        for sa in ("r", "rwd", None):
            kw = {} if sa is None else {"share_access": sa}
            try:
                with smbclient.open_file(path, mode='rb', **kw) as f:
                    return f.read()
            except Exception as e:  # noqa: BLE001 - 逐个方案试探，最终统一报错
                last = e
                continue
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
    raise SMBError("SMB 文件被占用无法读取(%s): %s" %
                   (type(last).__name__, str(last)[:160])) from last


def _scan(smbclient, cfg, workshop, spec, plan_date):
    """扫描单个计划日期：返回 (exact, cands, dtok, want)。

    exact: 模板精确命中的远端路径（权威版），无则 None。
    cands: {文件名: 远端路径}——同一天命中多个干净版时的候选集合。
    """
    template = spec['template']
    want = expected_filename(template, plan_date)
    dtok = date_token(template, plan_date)
    year = _to_dt(plan_date).year
    wroot = cfg.share_path(spec['subdir'])
    # (路径, 目录缺失是否可容忍)：根目录必须存在；年份归档目录可缺失。
    search_paths = [(wroot, False)]
    if spec.get('scan_year_subdir', True):
        search_paths.append((cfg.share_path(spec['subdir'], str(year)), True))

    exact = None
    cands = {}
    B = chr(92)
    for sp, miss_ok in search_paths:
        for name, is_dir in _list_dirs(smbclient, sp, missing_ok=miss_ok):
            if is_dir or not name.lower().endswith('.xlsx'):
                continue
            full = sp + B + name
            if name == want and exact is None:
                exact = full
            if dtok and dtok in name and _is_clean(name):
                cands[name] = full
    return exact, cands, dtok, want


def _pick(exact, cands, workshop, dtok):
    """从扫描结果挑出唯一权威文件：精确命中优先，否则仅当干净候选唯一。"""
    if exact:
        return exact
    if len(cands) == 1:
        return list(cands.values())[0]
    if len(cands) > 1:
        raise SMBError('[%s] 计划日期 %s 命中多个干净候选，需人工确认，不自动择一：%s'
                       % (workshop, dtok, sorted(cands.keys())))
    return None


def _load(smbclient, remote):
    data = _read_bytes(smbclient, remote)
    fname = remote.rsplit(chr(92), 1)[-1]  # Linux 不按反斜杠切，手工取末段
    return {'filename': fname, 'remote': remote, 'size': len(data), 'bytes': data}


def _find_one(smbclient, cfg, workshop, spec, plan_date):
    exact, cands, dtok, want = _scan(smbclient, cfg, workshop, spec, plan_date)
    chosen = _pick(exact, cands, workshop, dtok)
    if not chosen:
        raise PlanNotFound(
            '[%s] 未找到计划日期 %s 的干净版计划（模板：%s）。共享盘可能尚未发布当天计划。'
            % (workshop, dtok, want))
    return _load(smbclient, chosen)


def _find_recent(smbclient, cfg, workshop, spec, plan_date, lookback_days=5):
    """目标日期无干净版计划时，向过去逐日回退，取最近一个可用的干净版计划。

    只回退、不猜未来；命中即返回 (远端路径, 回退日期)。窗口内都没有则返回 None。
    这是显式开启的降级：假期/漏发时宁可发旧计划也要有可核对的产出，因此调用方必须
    把 degraded 标记透传到邮件标题与汇总，绝不能静默冒充当天计划。
    """
    base = _to_dt(plan_date).date()
    for back in range(1, lookback_days + 1):
        day = base - timedelta(days=back)
        exact, cands, dtok, _want = _scan(smbclient, cfg, workshop, spec, day)
        chosen = _pick(exact, cands, workshop, dtok)
        if chosen:
            return chosen, day
    return None


def fetch_plans(plan_date, out_dir, config=None, opts=None, interactive=True, only=None,
                allow_recent=False, lookback_days=5):
    pd = _to_dt(plan_date)
    cfg = config or SMBConfig.from_env(opts=opts, interactive=interactive)
    smbclient = _client(cfg)
    os.makedirs(out_dir, exist_ok=True)
    items = list(cfg.workshops.items())
    if only:
        want = set(only)
        items = [(k, v) for k, v in items if k in want]
        missing = want - {k for k, _ in items}
        if missing:
            raise SMBError('未在配置中找到车间：%s' % sorted(missing))
    files = []
    for workshop, spec in items:
        degraded = False
        actual = pd
        try:
            r = _find_one(smbclient, cfg, workshop, spec, pd)
        except PlanNotFound:
            # 默认直接把 PlanNotFound 抛给调用方（禁止回退）；只有显式 allow_recent
            # 才向过去逐日回退，且回退命中必须记录 degraded 供邮件/汇总标注。
            if not allow_recent:
                raise
            hit = _find_recent(smbclient, cfg, workshop, spec, pd, lookback_days)
            if hit is None:
                raise PlanNotFound(
                    '[%s] 计划日期 %s 无干净版计划，且近 %d 日内没有可回退的计划。'
                    % (workshop, pd.strftime('%Y-%m-%d'), lookback_days))
            chosen, actual = hit
            r = _load(smbclient, chosen)
            degraded = True
        dest = os.path.join(out_dir, r['filename'])
        with open(dest, 'wb') as fw:
            fw.write(r['bytes'])
        files.append({'workshop': workshop, 'filename': r['filename'], 'path': dest,
                      'remote': r['remote'], 'size': r['size'],
                      'matched_date': '%d月%d日' % (actual.month, actual.day),
                      'degraded': degraded})
    return {'plan_date': pd.strftime('%Y-%m-%d'), 'out_dir': out_dir, 'files': files,
            'degraded': any(f['degraded'] for f in files)}


def main():
    ap = argparse.ArgumentParser(description='SMB 生产计划自动取数（只读、日期不猜）')
    ap.add_argument('--plan-date', required=True, help='计划文件名里的日期 YYYY-MM-DD（必填，不推断）')
    ap.add_argument('--out', default='./plan_files', help='下载目录（默认 ./plan_files）')
    ap.add_argument('--only', nargs='*', help='仅取指定车间（如 一车间 二车间）')
    ap.add_argument('--allow-recent', action='store_true',
                    help='目标日期无计划时允许回退最近 lookback-days 日内的干净版计划（结果标记 degraded）')
    ap.add_argument('--lookback-days', type=int, default=5,
                    help='allow-recent 的向往回退天数（默认 7）')
    ap.add_argument('--json', action='store_true', help='输出机器可读 JSON')
    ap.add_argument('--paths-only', action='store_true', help='仅打印本地文件绝对路径（每行一个）')
    a = ap.parse_args()
    try:
        res = fetch_plans(a.plan_date, a.out, only=a.only,
                          allow_recent=a.allow_recent, lookback_days=a.lookback_days)
    except SMBError as e:
        sys.stderr.write('✗ %s%s' % (e, chr(10)))
        sys.exit(2)
    if a.paths_only:
        for f in res['files']:
            print(f['path'])
    elif a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print('计划日期 %s → 取到 %d 个车间干净版计划：%s' % (res['plan_date'], len(res['files']), res['out_dir']))
        for f in res['files']:
            mark = ' (降级)' if f.get('degraded') else ''
            print('  %-4s %8.1f KB  %s%s' % (f['workshop'], f['size'] / 1024, f['filename'], mark))
    sys.exit(0)


if __name__ == '__main__':
    main()
