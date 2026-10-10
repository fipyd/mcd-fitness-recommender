#!/usr/bin/env python3
"""nlu_llm 管线测试：用 mock LLM 验证 LLM 路径正确，并验证回退与鲁棒性。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import parse_signals_llm, parse_signals


def _mock_llm(prompt: str) -> str:
    """模拟真实 LLM 返回的 JSON（按文本返回不同场景）。

    注：真实 LLM 收到的是整段 prompt；这里提取「用户对话：」之后的内容再分支，
    避免系统提示中的示例词（如『跑步7』）误命中。
    """
    text = prompt.split("用户对话：", 1)[1] if "用户对话：" in prompt else prompt
    if "跑步" in text or "剪辑" in text:
        return """{
          "height_cm": 175, "weight_kg": 70, "target_weight_kg": 65,
          "age": null, "gender": null, "base_activity": "sedentary",
          "exercises": [{"label": "跑步", "met": 7.0, "minutes": 60}],
          "meal_occasion": "lunch", "taste_like": [], "taste_dislike": [],
          "taboo": [], "scene": ["午餐"]
        }"""
    if "巨无霸" in text:
        return """{
          "height_cm": null, "weight_kg": null, "target_weight_kg": null,
          "age": null, "gender": null, "base_activity": null, "exercises": [],
          "meal_occasion": "lunch", "taste_like": ["清淡"], "taste_dislike": ["辣"],
          "taboo": ["牛肉"], "scene": ["午餐"]
        }"""
    # messy 中文：男 28 一米八 九十公斤→八十五 写代码不动 撸铁40分 早饭麦记
    return """{
      "height_cm": 180, "weight_kg": 90, "target_weight_kg": 85, "age": 28,
      "gender": "male", "base_activity": "sedentary",
      "exercises": [{"label": "力量训练", "met": 5.0, "minutes": 40}],
      "meal_occasion": "breakfast", "taste_like": [], "taste_dislike": [],
      "taboo": [], "scene": ["早餐"]
    }"""


def _check(name, cond):
    print(("✅" if cond else "❌") + " " + name)
    assert cond, name


def main():
    # 1) 正常场景：LLM 主路径
    t1 = "身高175cm、体重70kg、目标体重65kg、职业剪辑师、久坐时间长、下班后跑步一小时、午餐吃麦当劳"
    sig, backend = parse_signals_llm(t1, _mock_llm, return_backend=True)
    _check("backend=llm", backend == "llm")
    _check("height=175", sig.get("height_cm") == 175)
    _check("weight=70", sig.get("weight_kg") == 70)
    _check("target=65", sig.get("target_weight_kg") == 65)
    _check("base=sedentary", sig.get("base_activity") == "sedentary")
    _check("exercise 跑步60min MET7", sig["exercises"] == [{"label": "跑步", "met": 7.0, "minutes": 60}])
    _check("occasion=lunch", sig.get("meal_occasion") == "lunch")

    # 2) 第二轮：忌辣/清淡/不吃牛
    t2 = "昨天巨无霸不错，但我讨厌吃辣，今天午餐还吃麦当劳，想吃点清淡的，别给我牛肉"
    sig2, _ = parse_signals_llm(t2, _mock_llm, return_backend=True)
    _check("taste_dislike 辣", "辣" in sig2["taste_dislike"])
    _check("taste_like 清淡", "清淡" in sig2["taste_like"])
    _check("taboo 牛肉", "牛肉" in sig2["taboo"])
    _check("occasion lunch", sig2["meal_occasion"] == "lunch")

    # 3) messy 中文鲁棒性
    t3 = "我男的28岁一米八九十公斤想瘦到八十五平时写代码不动晚上撸铁四十分钟早饭吃麦记"
    sig3, _ = parse_signals_llm(t3, _mock_llm, return_backend=True)
    _check("messy gender=male", sig3.get("gender") == "male")
    _check("messy age=28", sig3.get("age") == 28)
    _check("messy height=180", sig3.get("height_cm") == 180)
    _check("messy weight=90 target=85", sig3.get("weight_kg") == 90 and sig3.get("target_weight_kg") == 85)
    _check("messy exercise 力量40", sig3["exercises"] == [{"label": "力量训练", "met": 5.0, "minutes": 40}])
    _check("messy occasion breakfast", sig3.get("meal_occasion") == "breakfast")

    # 4) 无 llm_call → 回退规则
    sig4, backend4 = parse_signals_llm(t1, None, return_backend=True)
    _check("fallback backend=rule-fallback", backend4 == "rule-fallback")
    _check("fallback still parses weight", sig4.get("weight_kg") == 70)

    print("\n全部断言通过 ✅")


if __name__ == "__main__":
    main()
