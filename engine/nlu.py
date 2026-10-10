"""对话式 NLU：从自由文本抽取结构化信号。

MVP 采用规则式解析（中文关键词 + 正则），无第三方依赖。
生产环境可用 LLM 替换本模块，只要保持输出 Signals 结构一致即可。
"""

from __future__ import annotations

import re
from typing import TypedDict


class Signals(TypedDict, total=False):
    height_cm: int
    weight_kg: float
    target_weight_kg: float
    age: int
    gender: str
    base_activity: str        # sedentary/light/moderate/active/very_active
    exercises: list[dict]     # [{label, met, minutes}]
    meal_occasion: str        # lunch/breakfast/dinner/snack
    taste_like: list[str]
    taste_dislike: list[str]
    taboo: list[str]
    scene: list[str]
    raw: str


# 运动 MET 表（保守中速估算）
_EXERCISE_MET = {
    "跑步": 7.0, "慢跑": 7.0, "快跑": 9.8,
    "健身": 5.0, "力量": 5.0, "撸铁": 5.0,
    "游泳": 6.0, "骑车": 6.0, "骑行": 6.0, "自行车": 6.0,
    "瑜伽": 2.5, "快走": 4.3, "走路": 3.3, "散步": 2.5,
    "跳绳": 10.0, "打球": 6.0, "篮球": 6.5, "足球": 7.0,
}
# 久坐职业关键词
_SEDENTARY_KW = ["剪辑", "程序", "办公", "坐班", "文员", "设计", "码农", "久坐"]
# 用餐场景
_MEAL_MAP = {
    "午餐": "lunch", "午饭": "lunch", "中饭": "lunch", "中午": "lunch",
    "早餐": "breakfast", "早饭": "breakfast", "早": "breakfast",
    "晚餐": "dinner", "晚饭": "dinner", "夜宵": "dinner",
}
# 口味词
_TASTE_KW = ["辣", "甜", "咸", "清淡", "多汁", "香"]


def _first(pattern: str, text: str):
    m = re.search(pattern, text)
    return m.group(1) if m else None


def parse_body(text: str) -> dict:
    out: dict = {}
    h = _first(r"身高[是为]?\s*(\d+)\s*(?:cm|厘米)?", text)
    w = _first(r"体重[是为]?\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤)?", text)
    tw = _first(r"目标体重[是为]?\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤)?", text)
    if not tw:  # 兜底：口语常只说"目标65"
        tw = _first(r"目标\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤)?", text)
    age = _first(r"年龄[是为]?\s*(\d+)", text)
    if h:
        out["height_cm"] = int(h)
    if w:
        out["weight_kg"] = float(w)
    if tw:
        out["target_weight_kg"] = float(tw)
    if age:
        out["age"] = int(age)
    if "女" in text and "男" not in text:
        out["gender"] = "female"
    elif "男" in text:
        out["gender"] = "male"
    return out


_CN_NUM = {"半": 0.5, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
          "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _num(val: str) -> float:
    return float(val) if val.isdigit() else _CN_NUM.get(val, 1.0)


def parse_exercise(text: str) -> tuple[list[dict], str]:
    """返回 (运动列表, 基础活动等级)。"""
    exercises: list[dict] = []
    base = "moderate"
    if any(k in text for k in _SEDENTARY_KW):
        base = "sedentary"

    for label, met in _EXERCISE_MET.items():
        # 匹配 “跑步一小时” / “跑步30分钟” / “跑步1小时” / “跑步”
        m = re.search(rf"{label}\s*(\d+|[一二两三四五六七八九十半])\s*小时", text)
        if m:
            minutes = int(_num(m.group(1)) * 60)
        else:
            m = re.search(rf"{label}\s*(\d+)\s*分钟", text)
            minutes = int(m.group(1)) if m else (60 if label in text else 0)
        if minutes > 0:
            exercises.append({"label": label, "met": met, "minutes": minutes})
    return exercises, base


def parse_meal(text: str) -> str:
    for kw, occ in _MEAL_MAP.items():
        if kw in text:
            return occ
    return "lunch"


def parse_taste(text: str) -> tuple[list[str], list[str]]:
    like, dislike = [], []
    for t in _TASTE_KW:
        neg = re.search(rf"(?:不(?:吃|爱|喜欢)|讨厌|别吃|不爱|不想吃|忌|少(?:吃)?).{{0,2}}{t}", text)
        pos = re.search(rf"(?:爱|喜欢|爱吃|好|想吃点?|点).{{0,2}}{t}", text)
        if neg and not pos:
            dislike.append(t)
        elif pos and not neg:
            like.append(t)
    return like, dislike


def parse_taboo(text: str) -> list[str]:
    taboo: list[str] = []
    pat = (r"不(?:吃|碰)\s*([\u4e00-\u9fa5]{1,4})"
           r"|别\s*(?:给)?\s*我?\s*([\u4e00-\u9fa5]{1,4})"
           r"|忌口\s*([\u4e00-\u9fa5]{1,4})"
           r"|过敏\s*([\u4e00-\u9fa5]{1,4})"
           r"|不要\s*([\u4e00-\u9fa5]{1,4})")
    for m in re.finditer(pat, text):
        word = next((g for g in m.groups() if g), None)
        if word:
            taboo.append(word)
    # 素食大类
    if "素食" in text or "吃素" in text:
        taboo.append("素")
    return taboo


def parse_signals(text: str) -> Signals:
    """端到端：把对话文本解析为 Signals。"""
    body = parse_body(text)
    exercises, base = parse_exercise(text)
    occasion = parse_meal(text)
    like, dislike = parse_taste(text)
    taboo = parse_taboo(text)
    scene = []
    for kw in ["加班", "健身后", "训练后", "通勤", "聚会", "出差"]:
        if kw in text:
            scene.append(kw)
    sig: Signals = {
        "exercises": exercises,
        "base_activity": base,
        "meal_occasion": occasion,
        "taste_like": like,
        "taste_dislike": dislike,
        "taboo": taboo,
        "scene": scene,
        "raw": text,
    }
    sig.update(body)  # type: ignore
    return sig


__all__ = ["parse_signals", "parse_body", "parse_exercise", "parse_meal", "Signals"]
