"""解析 mcd_mcp.list-nutrition-foods 返回的营养数据字符串。

返回结构示例（data 字段内容）:
    [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
      猪柳麦满分,null,1288,308,16,16,24,781,213
      ...

本模块只负责把这段「头部 + CSV 行」文本解析成结构化字典列表，
不含任何推荐逻辑。
"""

from __future__ import annotations

import re
from typing import Iterable


def _to_float(value: str) -> float:
    value = (value or "").strip()
    if value in ("", "null", "None"):
        return 0.0
    try:
        return float(value)
    except ValueError:
        # 形如 "能量约清水1杯" 这类占位说明，按 0 处理
        return 0.0


def parse_nutrition(raw: str) -> list[dict]:
    """解析 list-nutrition-foods 的 data 字符串。

    Args:
        raw: mcd_mcp 返回的 data 字段原文（可能带 [N]{...}: 头部，也可能只是 CSV 行）。

    Returns:
        每条餐品的营养字典，字段:
        name, nutrition_description, energy_kj, energy_kcal,
        protein, fat, carbohydrate, sodium, calcium
    """
    if not raw:
        return []

    items: list[dict] = []
    started = False
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 头部行形如 [160]{productName,...}:，标记数据开始并跳过
        if not started and line.startswith("[") and "{" in line and line.endswith(":"):
            started = True
            continue
        # 若输入不含头部，则首行有效数据也能被处理
        if not started and ("," not in line):
            continue

        parts = line.split(",")
        if len(parts) < 9:
            continue

        name = parts[0].strip()
        if not name:
            continue

        items.append(
            {
                "name": name,
                "nutrition_description": parts[1].strip(),
                "energy_kj": _to_float(parts[2]),
                "energy_kcal": _to_float(parts[3]),
                "protein": _to_float(parts[4]),
                "fat": _to_float(parts[5]),
                "carbohydrate": _to_float(parts[6]),
                "sodium": _to_float(parts[7]),
                "calcium": _to_float(parts[8]),
            }
        )
    return items


def classify(items: Iterable[dict]) -> dict[str, list[dict]]:
    """按名称将餐品粗略分类为 main / side / drink，供组合套餐使用。"""
    DRINK_KW = [
        "可乐", "雪碧", "牛奶", "咖啡", "茶", "果汁", "纯悦", "怡泉", "美式",
        "奶铁", "玛奇朵", "阿芙佳朵", "雪冰", "豆浆", "朱古力", "燕麦",
        "阳光柠檬", "麦旋酷", "浓缩", "鲜萃", "卡布奇诺", "美汁源", "阳光橙",
    ]
    MAIN_KW = ["堡", "霸", "麦满分", "卷", "粥", "多肉", "鱼排", "安格斯"]

    buckets = {"main": [], "side": [], "drink": []}
    for it in items:
        name = it["name"]
        if any(k in name for k in DRINK_KW):
            buckets["drink"].append(it)
        elif any(k in name for k in MAIN_KW):
            buckets["main"].append(it)
        else:
            buckets["side"].append(it)
    return buckets


# 便于外部直接 import 使用
__all__ = ["parse_nutrition", "classify", "_to_float"]
