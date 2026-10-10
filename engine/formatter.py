"""输出格式化：把推荐结果整理成「结构化 JSON + 人话适配理由」。"""

from __future__ import annotations

from .profile import Target
from .recommender import Preferences


_GOAL_CN = {"cut": "减脂", "bulk": "增肌", "maintain": "维持"}


def _reason_for_combo(combo: dict, target: Target) -> str:
    goal_cn = _GOAL_CN.get(target["goal"], target["goal"])
    kc = combo["_total_kcal"]
    kp = combo["_total_protein"]
    ks = combo["_total_sodium"]
    cal_pct = kc / target["per_meal_calories"] * 100
    pro_pct = kp / target["per_meal_protein"] * 100

    parts = []
    # 热量贴合
    if 90 <= cal_pct <= 110:
        parts.append(f"总热量 {kc:.0f} kcal，正好贴合你每餐 {target['per_meal_calories']:.0f} kcal 的目标（{cal_pct:.0f}%）")
    elif cal_pct < 90:
        parts.append(f"总热量 {kc:.0f} kcal，略低于每餐目标（{cal_pct:.0f}%），适合控制总摄入")
    else:
        parts.append(f"总热量 {kc:.0f} kcal，占每餐目标的 {cal_pct:.0f}%，作为训练前后加餐较合适")
    # 蛋白质
    if pro_pct >= 80:
        parts.append(f"蛋白质 {kp:.0f} g（覆盖每餐目标的 {pro_pct:.0f}%），满足{goal_cn}期保肌/增肌需求")
    else:
        parts.append(f"蛋白质 {kp:.0f} g（覆盖 {pro_pct:.0f}%），可再补一份高蛋白小食")
    # 钠
    if ks > 800:
        parts.append(f"钠 {ks:.0f} mg 偏高，建议多喝水、当日少盐")
    else:
        parts.append(f"钠 {ks:.0f} mg 较合理")
    return "；".join(parts) + "。"


def _reason_for_single(item: dict, target: Target) -> str:
    goal_cn = _GOAL_CN.get(target["goal"], target["goal"])
    p, f, e = item["protein"], item["fat"], item["energy_kcal"]
    pd = p / max(e, 1) * 100
    if target["goal"] == "cut":
        return f"蛋白质密度 {pd:.1f} g/100kcal，脂肪 {f:.0f} g，是{goal_cn}期较低脂的高蛋白选择。"
    if target["goal"] == "bulk":
        return f"热量 {e:.0f} kcal、蛋白质 {p:.0f} g，能提供{goal_cn}所需的能量与蛋白。"
    return f"热量 {e:.0f} kcal、蛋白质 {p:.0f} g，营养较均衡，适合{goal_cn}期。"


def format_output(
    single: list[dict] | None,
    combos: list[dict] | None,
    target: Target,
    prefs: Preferences | None = None,
) -> dict:
    """汇总成最终输出结构。"""
    prefs = prefs or {}
    out: dict = {"target": target, "preferences": prefs, "single": [], "combos": []}

    if single is not None:
        for it in single:
            out["single"].append(
                {
                    "name": it["name"],
                    "nutrition": {
                        "energy_kcal": it["energy_kcal"],
                        "protein": it["protein"],
                        "fat": it["fat"],
                        "carbohydrate": it["carbohydrate"],
                        "sodium": it["sodium"],
                        "calcium": it["calcium"],
                    },
                    "score": it.get("_score"),
                    "reason": _reason_for_single(it, target),
                }
            )

    if combos is not None:
        for c in combos:
            out["combos"].append(
                {
                    "items": [
                        {
                            "name": i["name"],
                            "energy_kcal": i["energy_kcal"],
                            "protein": i["protein"],
                            "fat": i["fat"],
                            "carbohydrate": i["carbohydrate"],
                            "sodium": i["sodium"],
                        }
                        for i in c["items"]
                    ],
                    "totals": {
                        "energy_kcal": round(c["_total_kcal"], 1),
                        "protein": round(c["_total_protein"], 1),
                        "fat": round(c["_total_fat"], 1),
                        "carbohydrate": round(c["_total_carb"], 1),
                        "sodium": round(c["_total_sodium"], 1),
                    },
                    "score": c["_score"],
                    "reason": _reason_for_combo(c, target),
                }
            )
    return out


__all__ = ["format_output", "_reason_for_combo", "_reason_for_single"]
