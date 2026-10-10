"""运动消耗数据源：手动(MET 估算) / 可穿戴(实测) / 合并。

planner 默认用 MET 公式估算：kcal/min = MET × 3.5 × 体重 / 200。
接入真实数据后，优先采用可穿戴/健康 App 导出的**实测 kcal**（设备已按心率/轨迹算好），
对设备未覆盖的运动类型，仍用 MET 估算补位。
"""

from __future__ import annotations

import csv
import json
from typing import TypedDict


class ActivityItem(TypedDict, total=False):
    label: str
    met: float
    minutes: float
    kcal: float | None          # 实测值（可穿戴）或估算值（MET）
    source: str                 # "met-estimate" | "wearable-measured" | "wearable-met"


class ActivitySession:
    def __init__(self, items: list[ActivityItem]):
        self.items = items

    def total_kcal(self) -> float:
        return sum((i.get("kcal") or 0.0) for i in self.items)

    def has_measured(self) -> bool:
        return any(i.get("kcal") is not None for i in self.items)

    def labels(self) -> set[str]:
        return {i.get("label") for i in self.items if i.get("label")}


class ActivitySource:
    def get_session(self, sig: dict | None = None) -> ActivitySession:
        raise NotImplementedError


# MET 表与 nlu 保持一致（单一事实来源，避免漂移）
_EXERCISE_MET = {
    "跑步": 7.0, "慢跑": 7.0, "快跑": 9.8,
    "健身": 5.0, "力量": 5.0, "撸铁": 5.0,
    "游泳": 6.0, "骑车": 6.0, "骑行": 6.0, "自行车": 6.0,
    "瑜伽": 2.5, "快走": 4.3, "走路": 3.3, "散步": 2.5,
    "跳绳": 10.0, "打球": 6.0, "篮球": 6.5, "足球": 7.0,
}


class ManualActivitySource(ActivitySource):
    """从 NLU 信号(对话里说的运动)用 MET 估算消耗。"""

    def __init__(self, weight_kg: float):
        self.w = weight_kg

    def get_session(self, sig: dict | None = None) -> ActivitySession:
        items: list[ActivityItem] = []
        for ex in (sig or {}).get("exercises", []):
            met = ex.get("met") or _EXERCISE_MET.get(ex.get("label", ""), 5.0)
            minutes = ex.get("minutes", 0) or 0
            kcal = round(met * 3.5 * self.w / 200.0 * minutes, 1) if minutes else None
            items.append({
                "label": ex.get("label", ""),
                "met": met,
                "minutes": minutes,
                "kcal": kcal,
                "source": "met-estimate",
            })
        return ActivitySession(items)


class WearableActivitySource(ActivitySource):
    """读取可穿戴/健康 App 导出的运动记录（JSON 或 CSV）。

    期望字段（兼容中文/英文键）：
      type/activity/label, minutes/duration_min/duration,
      kcal/calories/energy（实测消耗，存在即用实测覆盖 MET）
    """

    def __init__(self, export_path: str):
        self.path = export_path

    def get_session(self, sig: dict | None = None) -> ActivitySession:
        rows = self._load()
        items: list[ActivityItem] = []
        for r in rows:
            minutes = _to_float(r.get("minutes") or r.get("duration_min") or r.get("duration"))
            kcal = _to_float(r.get("kcal") or r.get("calories") or r.get("energy"))
            met = _to_float(r.get("met"))
            label = r.get("type") or r.get("activity") or r.get("label") or ""
            items.append({
                "label": label,
                "met": met,
                "minutes": minutes,
                "kcal": kcal,
                "source": "wearable-measured" if kcal is not None else "wearable-met",
            })
        return ActivitySession(items)

    def _load(self) -> list[dict]:
        if self.path.endswith(".json"):
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, list) else d.get("activities", [])
        # CSV
        with open(self.path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))


def merge_activity(manual: ActivitySession | None,
                  wearable: ActivitySession | None) -> ActivitySession:
    """合并手动与可穿戴：优先用可穿戴**实测**；设备未覆盖的类型用 MET 估算补位。

    原则：
      - 可穿戴有实测 kcal 的项目 → 直接采用（更准），不再叠加手动同类型；
      - 手动里可穿戴没覆盖的类型 → 保留 MET 估算（补全当日总消耗）；
      - 都没有可穿戴 → 退回手动。
    """
    if wearable and wearable.has_measured():
        combined = [dict(i) for i in wearable.items]   # 实测优先
        worn = wearable.labels()
        for i in (manual.items if manual else []):
            if i.get("label") not in worn:
                combined.append(dict(i))              # 手动补位未覆盖类型
        return ActivitySession(combined)
    if wearable and wearable.items:
        # 可穿戴无实测(全是 met 估算)：与手动等价，直接采用可穿戴
        return wearable
    return manual or ActivitySession([])


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


__all__ = ["ActivityItem", "ActivitySession", "ActivitySource",
           "ManualActivitySource", "WearableActivitySource", "merge_activity"]
