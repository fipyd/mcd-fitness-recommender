"""根据健身人士身体数据与训练目标，计算每日目标热量与宏量营养。

方法：
- BMR 采用 Mifflin-St Jeor 方程（健身领域常用、比 Harris-Benedict 更准）。
- TDEE = BMR × 活动系数。
- 训练目标对 TDEE 做增减（减脂 -20% / 增肌 +10% / 维持 0%）。
- 蛋白质目标按体重 g/kg 计算（减脂期更高以保肌）。
"""

from __future__ import annotations

from typing import TypedDict


class Target(TypedDict):
    tdee: float
    target_calories: float
    target_protein: float
    target_fat: float
    target_carb: float
    per_meal_calories: float
    per_meal_protein: float
    per_meal_fat: float
    per_meal_carb: float
    meals_per_day: int
    goal: str


# 活动系数（对应不同训练/日常强度）
ACTIVITY_FACTOR = {
    "sedentary": 1.2,      # 久坐少动
    "light": 1.375,        # 每周 1-3 次轻运动
    "moderate": 1.55,      # 每周 3-5 次中等运动
    "active": 1.725,       # 每周 6-7 次高强度
    "very_active": 1.9,    # 体力工作 + 高强度训练
}

# 目标对 TDEE 的乘数，以及蛋白质目标 g/kg 体重
GOAL_FACTOR = {
    "cut": (0.80, 2.0),    # 减脂：热量缺口 20%，高蛋白保肌
    "bulk": (1.10, 1.8),   # 增肌：热量盈余 10%
    "maintain": (1.0, 1.6),# 维持
}


def calc_bmr(weight_kg: float, height_cm: float, age: int, gender: str) -> float:
    """Mifflin-St Jeor 基础代谢率。"""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if gender == "male" else base - 161


def build_target(
    *,
    gender: str,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity: str = "moderate",
    goal: str = "maintain",
    meals_per_day: int = 3,
    protein_per_kg: float | None = None,
) -> Target:
    """计算目标宏量营养。

    Args:
        gender: "male" / "female"
        weight_kg / height_cm / age: 身体数据
        activity: 活动等级键（见 ACTIVITY_FACTOR）
        goal: "cut" / "bulk" / "maintain"
        meals_per_day: 一天进餐次数（用于拆分每餐目标）
        protein_per_kg: 覆盖默认蛋白质目标
    """
    if activity not in ACTIVITY_FACTOR:
        activity = "moderate"
    if goal not in GOAL_FACTOR:
        goal = "maintain"

    factor, default_ppkg = GOAL_FACTOR[goal]
    ppkg = protein_per_kg if protein_per_kg else default_ppkg

    bmr = calc_bmr(weight_kg, height_cm, age, gender)
    tdee = bmr * ACTIVITY_FACTOR[activity]
    calories = tdee * factor

    protein_g = ppkg * weight_kg
    fat_g = calories * 0.25 / 9          # 脂肪占 25% 热量
    carb_g = (calories - protein_g * 4 - fat_g * 9) / 4
    carb_g = max(carb_g, 0.0)

    meals = max(int(meals_per_day), 1)
    return {
        "tdee": round(tdee, 1),
        "target_calories": round(calories, 1),
        "target_protein": round(protein_g, 1),
        "target_fat": round(fat_g, 1),
        "target_carb": round(carb_g, 1),
        "per_meal_calories": round(calories / meals, 1),
        "per_meal_protein": round(protein_g / meals, 1),
        "per_meal_fat": round(fat_g / meals, 1),
        "per_meal_carb": round(carb_g / meals, 1),
        "meals_per_day": meals,
        "goal": goal,
    }


__all__ = ["build_target", "calc_bmr", "ACTIVITY_FACTOR", "GOAL_FACTOR", "Target"]
