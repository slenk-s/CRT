"""字典与种子管理员初始化（幂等）。

运行：python -m app.seed
种子内容为「已确认稿」定稿：线体 29、工位 11、各工位检查项。
"""
from __future__ import annotations

from . import config, db
from .models import DictCheckItem, DictLine, DictStation, User
from .security import hash_password

# ---- 线体：29 条（车间, 线体）----
LINES: list[tuple[str, str]] = (
    [("一车间", "1F0%d" % i) for i in range(1, 8)] +
    [("二车间", "2F0%d" % i) for i in range(1, 9)] +
    [("三车间", "3F0%d" % i) for i in range(1, 6)] +
    [("四车间", "4F0%d" % i) for i in range(1, 6)] +
    [("七车间", "7F0%d" % i) for i in range(1, 5)]
)

# ---- 工位：11 个（顺序即展示顺序）----
STATIONS: list[str] = [
    "DeMura工位", "耐压工位", "画检工位", "白平衡工位", "检P1工位",
    "AV工位", "侧标工位", "复位工位", "开机工位", "检P2工位", "纸箱下线工位",
]

# ---- 工位 → 检查项（定稿；检P1/检P2 待管理员后补）----
CHECK_ITEMS: dict[str, list[str]] = {
    "耐压工位": ["2500V&3S（4MΩ&2S）", "3500V&3S（4MΩ&2S）"],
    "DeMura工位": ["TCON", "TCONLESS", "调试次数", "是否写入屏端", "屏端Demura调试状态检查"],
    "白平衡工位": [
        "光感", "蓝牙", "2.4GWiFi>0", "5GWiFi>0", "PID与PDM是否一致", "SN写入",
        "cusMAC抄写", "GammaSaveToFlash", "RMS数据读取", "UptoIPTV（亚马逊上传）",
        "双热点WIFI-AP检测", "WIFI6模块状态检测", "wirelessDongle状态检测",
        "画质芯片SPI升级接口检测", "机型写入或检查（与后牌、条码是否一致）",
    ],
    "侧标工位": ["Premium QLED", "Premium QMInILED", "Premium RGEMInILED",
                 "Premium SQIMInILED", "无"],
    "AV工位": [
        "网口检测", "USB2.0", "USB3.0", "AV人脸肤色", "是否未内置AV（无AV端口）",
        "左右声道是否正常", "HDCP1.4&2.2", "HDCP1.4", "ARC", "EDID",
        "TV模拟信号", "TV数字信号", "卫星信号", "RS232检测（网口||耳机孔||9针串口）",
        "HDMI图像灰阶偏色", "地波", "BS", "CS", "4K",
    ],
    "复位工位": ["待机指示灯"],
    "开机工位": ["开机LOGO", "开机语言", "开机指示灯"],
    "画检工位": ["九宫格检测", "白场检测", "LogoDiming检测"],
    "检P1工位": [],
    "检P2工位": [],
    "纸箱下线工位": ["校验AB面", "正反面校验", "前后SN校验", "扫前面", "扫后面"],
}


def seed_dict_lines(session) -> int:
    existing = {row.line for row in session.query(DictLine.line).all()}
    added = 0
    for idx, (workshop, line) in enumerate(LINES, start=1):
        if line in existing:
            continue
        session.add(DictLine(workshop=workshop, line=line, sort=idx * 10, active=1))
        added += 1
    return added


def seed_dict_stations(session) -> int:
    existing = {row.station for row in session.query(DictStation.station).all()}
    added = 0
    for idx, station in enumerate(STATIONS, start=1):
        if station in existing:
            continue
        session.add(DictStation(station=station, sort=idx * 10, active=1))
        added += 1
    return added


def seed_dict_check_items(session) -> int:
    existing = {(r.station, r.item) for r in session.query(DictCheckItem.station, DictCheckItem.item).all()}
    added = 0
    for station in STATIONS:
        for idx, item in enumerate(CHECK_ITEMS.get(station, []), start=1):
            if (station, item) in existing:
                continue
            session.add(DictCheckItem(station=station, item=item, sort=idx * 10, active=1))
            added += 1
    return added


def seed_admin(session) -> int:
    emp_id = config.SEED_ADMIN_EMP_ID
    if not emp_id:
        return 0
    if session.get(User, emp_id):
        return 0
    if not config.SEED_ADMIN_PASSWORD:
        raise RuntimeError("已设置 SEED_ADMIN_EMP_ID 但缺少 SEED_ADMIN_PASSWORD，无法创建种子管理员")
    session.add(User(
        emp_id=emp_id,
        name=config.SEED_ADMIN_NAME or emp_id,
        password_hash=hash_password(config.SEED_ADMIN_PASSWORD),
        role="admin",
        active=1,
        must_change_password=1,     # 首次登录强制改密
    ))
    return 1


def run() -> None:
    db.init_db()
    session = db.SessionLocal()
    try:
        n_lines = seed_dict_lines(session)
        n_stations = seed_dict_stations(session)
        n_items = seed_dict_check_items(session)
        n_admin = seed_admin(session)
        session.commit()
        total_lines = session.query(DictLine).count()
        total_stations = session.query(DictStation).count()
        total_items = session.query(DictCheckItem).count()
        print("种子完成：")
        print("  线体 +%d（共 %d）" % (n_lines, total_lines))
        print("  工位 +%d（共 %d）" % (n_stations, total_stations))
        print("  检查项 +%d（共 %d）" % (n_items, total_items))
        print("  管理员 +%d" % n_admin)
    finally:
        session.close()


if __name__ == "__main__":
    run()