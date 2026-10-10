"""推荐引擎核心：偏好过滤 + 单品打分 + 套餐组合搜索。

设计要点：
- 过滤（filter_items）：按饮食偏好剔除不符合的餐品。
- 单品打分（score_single）：针对 cut/bulk/maintain 三目标给出 fitness 分数。
- 套餐组合（recommend_combo）：在「每餐热量预算」内搜索 (主+副+饮) 组合，
  以蛋白质覆盖度 + 热量贴合度 + 低钠为优化目标排序。
"""

from __future__ import annotations

from typing import TypedDict

from .menu_parser import classify
from .profile import Target
from .prefs_model import bias_for_item, hard_excludes


class Preferences(TypedDict, total=False):
    vegetarian: bool        # 素食（剔除禽畜鱼肉类）
    beef_free: bool         # 不吃牛肉
    low_sodium: bool        # 低钠（每餐钠 <= 600mg）
    no_sugar: bool          # 饮料去糖（只选无糖/纯水/茶/黑咖啡）
    exclude_keywords: list[str]   # 名称含这些词则剔除
    min_protein: float      # 每餐蛋白质下限（克）
    max_calorie: float      # 单品热量上限（千卡）
    max_sodium: float       # 单品钠上限（毫克）


# 过滤规则用到的关键词
# 注：「巨无霸」使用「霸」(bà) 而非「堡」(bǎo)，需单独兜底
_MEAT_KW = ["鸡", "牛", "猪", "鱼", "肉", "香肠", "翅", "排", "腿", "堡", "霸", "多肉"]
_BEEF_KW = ["牛", "安格斯", "不素之霸", "霸"]
_SUGAR_DRINK_OK = ["无糖", "纯悦", "茶", "美式", "咖啡", "浓缩", "鲜萃", "锡兰", "川宁"]


def _passes(item: dict, prefs: Preferences) -> bool:
    name = item["name"]
    if prefs.get("exclude_keywords"):
        for kw in prefs["exclude_keywords"]:
            if kw and kw in name:
                return False
    if prefs.get("vegetarian"):
        if any(k in name for k in _MEAT_KW):
            return False
    if prefs.get("beef_free"):
        if any(k in name for k in _BEEF_KW):
            return False
    if prefs.get("max_calorie"):
        if item["energy_kcal"] > prefs["max_calorie"]:
            return False
    if prefs.get("max_sodium"):
        if item["sodium"] > prefs["max_sodium"]:
            return False
    return True


def filter_items(items: list[dict], prefs: Preferences | None = None) -> list[dict]:
    """按偏好过滤餐品。"""
    prefs = prefs or {}
    return [it for it in items if _passes(it, prefs)]


def score_single(item: dict, goal: str, per_meal_calories: float) -> float:
    """单品 fitness 分数（越高越适合该目标）。"""
    p, f, e, s = item["protein"], item["fat"], item["energy_kcal"], item["sodium"]
    if goal == "cut":
        return p * 3 - f * 1.0 - e * 0.05 - s * 0.003
    if goal == "bulk":
        return p * 1.5 + e * 0.15 - s * 0.002
    # maintain：贴近每餐热量、蛋白质与低脂兼顾
    return p * 2 - abs(e - per_meal_calories) * 0.01 - f * 0.3


def _merge_prefs(prefs: Preferences | None, model: dict | None) -> Preferences:
    """合并硬忌口（来自偏好模型）到过滤条件。"""
    prefs = dict(prefs or {})
    if model:
        ex = hard_excludes(model)
        if ex:
            cur = list(prefs.get("exclude_keywords", []))
            for k in ex:
                if k not in cur:
                    cur.append(k)
            prefs["exclude_keywords"] = cur
        if "素" in model.get("taboo", []):
            prefs["vegetarian"] = True
    return prefs


def recommend_single(
    items: list[dict],
    target: Target,
    prefs: Preferences | None = None,
    model: dict | None = None,
    top_n: int = 5,
) -> list[dict]:
    """单品推荐：过滤后按 fitness 分数 + 偏好偏置排序。"""
    prefs = _merge_prefs(prefs, model)
    filtered = filter_items(items, prefs)
    goal = target["goal"]
    scored = []
    for it in filtered:
        s = score_single(it, goal, target["per_meal_calories"])
        if model:
            s += bias_for_item(it, model)
        scored.append((it, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    out = []
    for it, sc in scored[:top_n]:
        row = dict(it)
        row["_score"] = round(sc, 2)
        out.append(row)
    return out


def _combo_score(combo: dict, target: Target, model: dict | None = None) -> float:
    """套餐综合分：热量贴合(50%) + 蛋白质覆盖(50%) - 钠惩罚 + 偏好偏置。"""
    tc = combo["_total_kcal"]
    tp = combo["_total_protein"]
    ts = combo["_total_sodium"]
    cal_fit = 1 - abs(tc - target["per_meal_calories"]) / target["per_meal_calories"]
    cal_fit = max(cal_fit, 0.0)
    pro_fit = min(tp / target["per_meal_protein"], 1.2) / 1.2
    sodium_penalty = ts / 1000 * 0.1
    score = cal_fit * 0.5 + pro_fit * 0.5 - sodium_penalty
    if model:
        score += sum(bias_for_item(c, model) for c in combo["items"]) * 0.03
    return score


def recommend_combo(
    items: list[dict],
    target: Target,
    prefs: Preferences | None = None,
    model: dict | None = None,
    top_n: int = 5,
) -> list[dict]:
    """套餐组合推荐：(主 + 副 + 饮) 在每餐热量预算内搜索。"""
    prefs = _merge_prefs(prefs, model)
    budget = target["per_meal_calories"]
    low_sodium = prefs.get("low_sodium", False)

    # 饮料去糖处理：no_sugar 时只允许无糖/纯水/茶/黑咖啡类
    def drink_ok(d: dict) -> bool:
        if prefs.get("no_sugar"):
            return any(k in d["name"] for k in _SUGAR_DRINK_OK)
        return True

    buckets = classify(items)
    mains = [it for it in buckets["main"] if _passes(it, prefs) and it["energy_kcal"] <= budget * 1.2]
    sides = [it for it in buckets["side"] if _passes(it, prefs) and it["energy_kcal"] <= budget]
    drinks = [it for it in buckets["drink"] if _passes(it, prefs) and drink_ok(it)]

    combos: list[dict] = []
    for m in mains:
        rem = budget - m["energy_kcal"]
        if rem < 0:
            continue
        # 选最优副食：在剩余预算内蛋白质密度最高（减脂时偏好低脂）
        best_side = None
        best_side_score = -1e9
        for s in sides:
            if s["energy_kcal"] > rem * 0.85:
                continue
            sd = s["protein"] / max(s["energy_kcal"], 1)
            sd = sd * 100 - (s["fat"] if target["goal"] == "cut" else 0) * 0.5
            if sd > best_side_score:
                best_side_score = sd
                best_side = s
        if best_side is None:
            continue
        # 选最优饮料：优先近零热量（避免冲爆预算）
        best_drink = None
        best_drink_kcal = 1e9
        for d in drinks:
            if d["energy_kcal"] < best_drink_kcal:
                best_drink_kcal = d["energy_kcal"]
                best_drink = d
        if best_drink is None:
            best_drink = {"name": "（不加饮料）", "energy_kcal": 0, "protein": 0,
                          "fat": 0, "carbohydrate": 0, "sodium": 0, "calcium": 0}

        chosen = [m, best_side, best_drink]
        total_kcal = sum(c["energy_kcal"] for c in chosen)
        total_protein = sum(c["protein"] for c in chosen)
        total_fat = sum(c["fat"] for c in chosen)
        total_carb = sum(c["carbohydrate"] for c in chosen)
        total_sodium = sum(c["sodium"] for c in chosen)

        # 预算窗口：70% ~ 115%
        if not (budget * 0.7 <= total_kcal <= budget * 1.15):
            continue
        if low_sodium and total_sodium > 600:
            continue
        combos.append(
            {
                "items": chosen,
                "_total_kcal": total_kcal,
                "_total_protein": total_protein,
                "_total_fat": total_fat,
                "_total_carb": total_carb,
                "_total_sodium": total_sodium,
                "_score": 0.0,
            }
        )

    for c in combos:
        c["_score"] = round(_combo_score(c, target, model), 4)
    combos.sort(key=lambda x: x["_score"], reverse=True)
    return combos[:top_n]


__all__ = [
    "recommend_single", "recommend_combo", "filter_items",
    "score_single", "Preferences",
]
