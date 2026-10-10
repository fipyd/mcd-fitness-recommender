"""mcd_mcp 取数适配器。

真实运行环境里，菜单营养数据由 Agent 通过 MCP 工具 `mcp__mcd-mcp__list-nutrition-foods`
获取（无入参，返回 {"success":true,"data":"[N]{...}:\\n csv..."}）。

本模块把"如何拿到 data 字符串"抽象成可注入的 `call_mcp` 回调：
- Agent 侧：把真实 MCP 调用包成一个无参函数注入即可；
- 沙箱/降级：不注入 call_mcp，则回退到本地样例文件（--nutrition）。

这样引擎与"取数通道"解耦，既能接真实 MCP，也能在离线/测试时用样例数据跑通。
"""

from __future__ import annotations

import json
import os
from typing import Callable, Tuple


def _extract_data(raw) -> str | None:
    """从 MCP 返回结构里抽出 data 字符串。兼容多种形态。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        d = raw.get("data")
        if isinstance(d, str):
            return d.strip()
        if isinstance(d, dict):
            # 个别实现可能把内容再包一层
            inner = d.get("content") or d.get("text") or d.get("nutrition")
            if isinstance(inner, str):
                return inner.strip()
    return None


def fetch_nutrition_data(call_mcp: Callable[[], object] | None = None,
                         fallback_path: str | None = None) -> Tuple[str, str]:
    """返回 (菜单 data 字符串, 来源标识)。

    来源标识: "mcp" | "fallback-file"
    - call_mcp 注入时优先调用；成功取到非空 data 即返回 ("mcp")
    - 否则回退 fallback_path（本地 .txt/.json）
    - 都没有 → 抛 RuntimeError
    """
    if call_mcp is not None:
        try:
            data = _extract_data(call_mcp())
            if data:
                return data, "mcp"
        except Exception:
            # 真实 MCP 不可用（未配置/超时），静默降级
            pass
    if fallback_path and os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return f.read(), "fallback-file"
    raise RuntimeError(
        "无法获取麦当劳营养数据：未注入可用的 mcd_mcp 调用，且本地回退文件不存在。"
    )


def make_stub_call_mcp(nutrition_path: str) -> Callable[[], dict]:
    """生成一个模拟 mcd_mcp 调用的回调（沙箱自测用）。

    读取本地样例文件，按真实返回结构包装成 {"success":True,"data":...}。
    Agent 接入真实 MCP 后，用真实调用替换本 stub 即可。
    """
    def _call() -> dict:
        with open(nutrition_path, "r", encoding="utf-8") as f:
            return {"success": True, "code": 0, "message": "ok", "data": f.read()}

    return _call


# ---------------------------------------------------------------------------
# 订单历史取数（用于"基于用户常点餐品的智能推荐"）
# 真实环境：Agent 注入 mcp__mcd-mcp__order-list / query-order 调用，返回订单列表。
# ---------------------------------------------------------------------------

def _extract_orders(raw) -> list[dict]:
    """从 MCP 返回结构里抽出订单列表，兼容多种形态：
    - 真实 order-list: {success, data:{list:[...]}}
    - 其它: {orders|list|items:[...]} 或裸列表
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        d = raw.get("data")
        if isinstance(d, dict) and isinstance(d.get("list"), list):
            return d["list"]
        if isinstance(d, list):
            return d
        for k in ("orders", "list", "items", "orderList"):
            v = raw.get(k)
            if isinstance(v, list):
                return v
    return []


def _order_items(order: dict) -> list[tuple[str, int]]:
    """抽出一张订单里的具体餐品(名称, 数量)，兼容真实结构与简单结构。

    - 真实结构：orderProductList[].comboItemList（套餐子项）或 productName（单品）；跳过已取消订单。
    - 简单结构：items[].{name,quantity}。
    """
    if order.get("orderStatus") in ("订单已取消", "CANCELLED", "已取消", "canceled"):
        return []
    out: list[tuple[str, int]] = []
    for p in order.get("orderProductList", []):
        sub = p.get("comboItemList") or []
        if sub:
            for c in sub:
                out.append((c.get("name") or c.get("productName"), int(c.get("quantity", 1) or 1)))
        else:
            out.append((p.get("productName") or p.get("name"), int(p.get("quantity", 1) or 1)))
    for it in order.get("items", []):
        out.append((it.get("name") or it.get("productName"), int(it.get("quantity", 1) or 1)))
    return out


def aggregate_favorites(orders: list[dict]) -> dict[str, int]:
    """从订单列表聚合常点餐品：返回按次数(数量)降序的 {name: count}（套餐子项展开计入）。"""
    fav: dict[str, int] = {}
    for o in orders:
        for nm, qty in _order_items(o):
            if nm:
                fav[nm] = fav.get(nm, 0) + qty
    return dict(sorted(fav.items(), key=lambda kv: kv[1], reverse=True))


def fetch_order_history(call_mcp: Callable[[], object] | None = None,
                        fallback_path: str | None = None) -> dict[str, int]:
    """返回用户常点餐品 {name: count}（降序）。

    - call_mcp：注入真实 mcd_mcp 订单查询（order-list / query-order），返回含订单的结构。
    - 否则回退 fallback_path（本地 JSON，支持真实 data.list 结构与简单结构）。
    - 都没有 → 返回 {}（无历史，走纯个性化）。
    """
    raw = None
    if call_mcp is not None:
        try:
            raw = call_mcp()
        except Exception:
            raw = None
    if raw is None and fallback_path and os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    if raw is None:
        return {}
    orders = _extract_orders(raw)
    return aggregate_favorites(orders) if orders else {}


def make_stub_order_history(path: str) -> Callable[[], object]:
    """模拟 mcd_mcp 订单查询：读取本地订单 JSON（真实 data.list 结构或简单结构）。生产替换为真实 call_mcp。"""
    def _call() -> object:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return _call


__all__ = ["fetch_nutrition_data", "make_stub_call_mcp",
           "aggregate_favorites", "fetch_order_history", "make_stub_order_history"]
