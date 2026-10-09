"""模块② · WB 参数查询数据源封装（阶段 6）。

目标：复用 `wb_mail.mes_api`（同机部署，后端直接 import），把「按批次 / 按 BOM」
查询到的**有序字段字典**原样透传给前端（键名即邮件契约的中文字段名，不增删、不改序）。

数据源可插拔（`WB_SOURCE`）：
- `auto`（默认）：优先真实 `wb_mail.mes_api`；不可用则回退 HTTP；都没有则不可用。
- `mes`  ：强制真实 `wb_mail.mes_api`。
- `http` ：走 `WB_BY_BATCH_URL` / `WB_BY_BOM_URL`。
- `mock` ：确定性假数据（仅用于开发自测，不连内网）。
- `off`  ：关闭（一律 503）。

降级：端点缺失 / 包未安装 → `WbUnavailable`，路由层返回 503「数据源未配置，请联系管理员」。
单批次失败：抛 `WbQueryError`，由路由层**逐条**标注，不遮蔽其他批次。
"""
from __future__ import annotations

import sys
from typing import Callable

from .. import config


class WbUnavailable(RuntimeError):
    """数据源不可用（路由层 → 503）。"""


class WbQueryError(RuntimeError):
    """单个批次/BOM 查询失败（路由层 → 该条 ok=false）。"""


# ---------------------------------------------------------------- 真实 mes_api
class MesApiSource:
    """直接调用 wb_mail.mes_api（端点由环境变量预置，不覆盖）。"""

    def __init__(self, mes_api) -> None:  # noqa: ANN001
        self._api = mes_api

    @classmethod
    def try_create(cls) -> "MesApiSource | None":
        path = (config.WB_MAIL_PATH or "").strip()
        if path and path not in sys.path:
            sys.path.insert(0, path)
        try:
            from wb_mail import mes_api  # type: ignore
        except Exception:  # noqa: BLE001  包未安装 / 导入失败 → 不可用
            return None
        # 端点已由环境变量预置；若存在 mes_env.load() 则调用（不覆盖已有端点）。
        try:
            from wb_mail import mes_env  # type: ignore

            if hasattr(mes_env, "load"):
                mes_env.load()
        except Exception:  # noqa: BLE001
            pass
        return cls(mes_api)

    def query_by_batch(self, batch: str) -> dict[str, str]:
        try:
            fields = self._api.fetch_fields(batch, with_side_label=True)
        except Exception as exc:  # noqa: BLE001
            raise WbQueryError(f"批次查询失败：{type(exc).__name__}: {exc}") from exc
        return _normalize(fields)

    def query_by_bom(self, bom: str) -> dict[str, str]:
        try:
            fields = self._api.fetch_fields_by_bom(bom)
        except Exception as exc:  # noqa: BLE001
            raise WbQueryError(f"BOM 查询失败：{type(exc).__name__}: {exc}") from exc
        return _normalize(fields)


# ---------------------------------------------------------------- HTTP
class HttpSource:
    """通过预置的 HTTP 端点查询（无 wb_mail 时的降级通道）。"""

    def __init__(self) -> None:
        import httpx  # 延迟导入：非 http 模式不依赖

        self._httpx = httpx

    def _get(self, url: str, key: str, label: str) -> dict[str, str]:
        params = {"bom" if label == "bom" else "batch": key}
        try:
            resp = self._httpx.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise WbQueryError(f"{label} 查询失败：{type(exc).__name__}: {exc}") from exc
        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            data = data["fields"]
        return _normalize(data)

    def query_by_batch(self, batch: str) -> dict[str, str]:
        return self._get(config.WB_BY_BATCH_URL, batch, "batch")

    def query_by_bom(self, bom: str) -> dict[str, str]:
        return self._get(config.WB_BY_BOM_URL, bom, "bom")


# ---------------------------------------------------------------- Mock（开发自测）
class MockSource:
    """确定性假数据：不访问内网，仅用于开发/测试。"""

    def query_by_batch(self, batch: str) -> dict[str, str]:
        if "ERR" in batch.upper():
            raise WbQueryError("模拟失败：批次不存在")
        return {
            "批次": batch,
            "BOM": f"BM-{batch}",
            "产品平台": "MOCK",
            "机型": "MOCK-55",
            "色坐标": "0.280,0.290",
            "Gamma": "2.2",
            "KEY": "100/100/100",
            "ODF": "ODF-MOCK",
            "侧标": "Premium QLED",
            "无线": "WiFi6",
        }

    def query_by_bom(self, bom: str) -> dict[str, str]:
        if "ERR" in bom.upper():
            raise WbQueryError("模拟失败：BOM 不存在")
        return {
            "BOM": bom,
            "产品平台": "MOCK",
            "色坐标": "0.280,0.290",
            "Gamma": "2.2",
        }


# ---------------------------------------------------------------- helpers
def _normalize(fields: object) -> dict[str, str]:
    """统一成有序 str->str 字典；保持原顺序。"""
    if isinstance(fields, dict):
        return {str(k): ("" if v is None else str(v)) for k, v in fields.items()}
    raise WbQueryError(f"数据源返回格式异常：{type(fields).__name__}")


def resolve_source() -> Callable[[], object]:
    """按 WB_SOURCE 选择数据源实例；不可用返回 None。"""
    mode = (config.WB_SOURCE or "auto").strip().lower()

    if mode == "off":
        return None
    if mode == "mock":
        return MockSource()
    if mode == "http":
        return HttpSource() if config.WB_BY_BATCH_URL else None
    if mode == "mes":
        src = MesApiSource.try_create()
        if src is None:
            raise WbUnavailable("wb_mail.mes_api 不可用（未安装或端点未配置）")
        return src

    # auto
    src = MesApiSource.try_create()
    if src is not None:
        return src
    if config.WB_BY_BATCH_URL:
        return HttpSource()
    return None