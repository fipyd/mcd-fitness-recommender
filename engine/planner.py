"""目标计划：身体数据 + 运动消耗 + 减重目标 → 该餐热量/蛋白预算。

计算链：
1. BMR (Mifflin-St Jeor，缺性别/年龄时给保守默认并标注)
2. TDEE = BMR × 基础活动系数(职业) + Σ(运动 MET × 3.5 × 体重 / 200 × 分钟)
3. 减重缺口：目标体重 < 当前体重时，按 0.5kg/周 安全速率换算每日缺口（封顶 TDEE 的 25%）
4. 该餐预算 = (TDEE − 每日缺口) × 用餐场景占比
"""

from __future__ import annotations

from typing import TypedDict

from .nlu import Signals

# 用餐场景热量占比（一日三餐 + 可选加餐，默认三餐）
_MEAL_FRACTION = {"breakfast": 0.25, "lunch": 0.38, "dinner": 0.37, "snack": 0.15}
_KCAL_PER_KG_FAT = 7700
_SAFE_WEEKLY_LOSS_KG = 0.5


class Plan(TypedDict):
    gender: str
    age: int
    weight_kg: float
    target_weight_kg: float | None
    bmr: float
    base_tdee: float
    exercise_burn: float
    tdee: float
    daily_deficit: float
    target_calories: float
    daily_protein: float
    meal_occasion: str
    per_meal_calories: float
    per_meal_protein: float
    est_weeks: float | None
    assumptions: list[str]


def _kcal_per_min(met: float, weight_kg: float) -> float:
    return met * 3.5 * weight_kg / 200.0


def build_plan(sig: Signals, exercise_burn_override: float | None = None) -> Plan:
    assumptions: list[str] = []

    gender = sig.get("gender", "male")
    if "gender" not in sig:
        assumptions.append("未提供性别，默认按男性估算")
    age = sig.get("age", 30)
    if "age" not in sig:
        assumptions.append("未提供年龄，默认按 30 岁估算")

    weight = sig.get("weight_kg")
    if not weight:
        raise ValueError("缺少体重数据，无法制定计划")
    height = sig.get("height_cm")
    if not height:
        raise ValueError("缺少身高数据，无法制定计划")

    # 1) BMR
    base_bmr = 10 * weight + 6.25 * height - 5 * age + (5 if gender == "male" else -161)

    # 2) 运动消耗（接入真实数据：可穿戴实测优先覆盖 MET 估算）
    ex_burn = 0.0
    if exercise_burn_override is not None:
        ex_burn = float(exercise_burn_override)
        assumptions.append("运动消耗采用可穿戴/健康App实测值（覆盖 MET 估算）")
    else:
        for ex in sig.get("exercises", []):
            ex_burn += _kcal_per_min(ex["met"], weight) * ex["minutes"]

    # 基础活动系数（职业久坐 → 低）
    from .profile import ACTIVITY_FACTOR
    base_activity = sig.get("base_activity", "moderate")
    base_tdee = base_bmr * ACTIVITY_FACTOR.get(base_activity, 1.55)
    tdee = base_tdee + ex_burn

    # 3) 减重缺口
    target_w = sig.get("target_weight_kg")
    daily_deficit = 0.0
    est_weeks = None
    if target_w and target_w < weight:
        deficit_kg = weight - target_w
        weekly_loss = min(deficit_kg, _SAFE_WEEKLY_LOSS_KG)  # 安全速率
        daily_deficit = weekly_loss * _KCAL_PER_KG_FAT / 7.0
        cap = tdee * 0.25
        if daily_deficit > cap:
            daily_deficit = cap
            assumptions.append("减重缺口超过 TDEE 25%，已封顶以保证安全")
        est_weeks = deficit_kg / weekly_loss if weekly_loss else None
    elif target_w and target_w > weight:
        assumptions.append("目标体重高于当前，按维持/增肌处理")
        daily_deficit = -tdee * 0.10  # 轻微盈余

    target_calories = max(tdee - daily_deficit, base_bmr * 1.05)

    # 4) 蛋白与餐次预算（减重期高蛋白保肌 2.0 g/kg）
    ppkg = 2.0 if (target_w and target_w < weight) else 1.6
    daily_protein = ppkg * weight

    occasion = sig.get("meal_occasion", "lunch")
    frac = _MEAL_FRACTION.get(occasion, 0.38)
    per_meal_calories = target_calories * frac
    per_meal_protein = daily_protein * frac

    if target_w and target_w < weight:
        goal = "cut"
    elif target_w and target_w > weight:
        goal = "bulk"
    else:
        goal = "maintain"

    return {
        "goal": goal,
        "gender": gender,
        "age": age,
        "weight_kg": weight,
        "target_weight_kg": target_w,
        "bmr": round(base_bmr, 1),
        "base_tdee": round(base_tdee, 1),
        "exercise_burn": round(ex_burn, 1),
        "tdee": round(tdee, 1),
        "daily_deficit": round(daily_deficit, 1),
        "target_calories": round(target_calories, 1),
        "daily_protein": round(daily_protein, 1),
        "meal_occasion": occasion,
        "per_meal_calories": round(per_meal_calories, 1),
        "per_meal_protein": round(per_meal_protein, 1),
        "est_weeks": round(est_weeks, 1) if est_weeks else None,
        "assumptions": assumptions,
    }


__all__ = ["build_plan", "Plan"]
