#!/usr/bin/env python3
"""麦当劳健身餐推荐 · 命令行入口。

用法:
    python run.py --profile examples/sample_profile.json \
                  --nutrition examples/nutrition_sample.txt \
                  --mode both --top 5

说明:
    --nutrition 传入 mcd_mcp.list-nutrition-foods 返回的 data 原文（含 [N]{...}: 头部也可）。
    --profile   传入用户身体数据 / 训练目标 / 饮食偏好（JSON）。
    --mode      single=只推单品, combo=只推套餐, both=两者都推。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让脚本在任意目录下都能 import engine 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import (  # noqa: E402
    parse_nutrition, build_target, recommend_single,
    recommend_combo, format_output, Preferences,
)


def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    ap = argparse.ArgumentParser(description="麦当劳健身餐推荐引擎")
    ap.add_argument("--profile", required=True, help="用户画像 JSON 路径")
    ap.add_argument("--nutrition", required=True, help="营养数据原文路径")
    ap.add_argument("--mode", choices=["single", "combo", "both"], default="both")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    profile = load_profile(args.profile)
    raw = Path(args.nutrition).read_text(encoding="utf-8")

    items = parse_nutrition(raw)
    if not items:
        print("⚠️ 未能解析到任何餐品营养数据，请检查 --nutrition 内容。", file=sys.stderr)
        sys.exit(1)

    target = build_target(
        gender=profile.get("gender", "male"),
        weight_kg=profile["weight_kg"],
        height_cm=profile["height_cm"],
        age=profile["age"],
        activity=profile.get("activity", "moderate"),
        goal=profile.get("goal", "maintain"),
        meals_per_day=profile.get("meals_per_day", 3),
        protein_per_kg=profile.get("protein_per_kg"),
    )

    prefs: Preferences = profile.get("preferences", {})

    single = recommend_single(items, target, prefs, args.top) if args.mode in ("single", "both") else None
    combos = recommend_combo(items, target, prefs, args.top) if args.mode in ("combo", "both") else None

    result = format_output(single, combos, target, prefs)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    _print_human(result)


def _print_human(result: dict) -> None:
    t = result["target"]
    goal_cn = {"cut": "减脂", "bulk": "增肌", "maintain": "维持"}.get(t["goal"], t["goal"])
    print(f"\n===== 目标概览（{goal_cn}）=====")
    print(f"  TDEE: {t['tdee']:.0f} kcal | 每日目标: {t['target_calories']:.0f} kcal")
    print(f"  每日蛋白/脂肪/碳水: {t['target_protein']:.0f}/{t['target_fat']:.0f}/{t['target_carb']:.0f} g")
    print(f"  每餐(×{t['meals_per_day']})目标: {t['per_meal_calories']:.0f} kcal / 蛋白 {t['per_meal_protein']:.0f} g")

    if result["single"]:
        print("\n----- 单品推荐（Top）-----")
        for i, r in enumerate(result["single"], 1):
            n = r["nutrition"]
            print(f"  {i}. {r['name']}  {n['energy_kcal']:.0f}kcal 蛋{n['protein']:.0f} 脂{n['fat']:.0f} 碳{n['carbohydrate']:.0f} 钠{n['sodium']:.0f}")
            print(f"     └ {r['reason']}")

    if result["combos"]:
        print("\n----- 套餐组合推荐（Top）-----")
        for i, c in enumerate(result["combos"], 1):
            names = " + ".join(x["name"] for x in c["items"])
            tot = c["totals"]
            print(f"  {i}. {names}")
            print(f"     合计 {tot['energy_kcal']:.0f}kcal 蛋{tot['protein']:.0f} 脂{tot['fat']:.0f} 碳{tot['carbohydrate']:.0f} 钠{tot['sodium']:.0f} | 分{c['score']:.3f}")
            print(f"     └ {c['reason']}")


if __name__ == "__main__":
    main()
