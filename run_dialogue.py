#!/usr/bin/env python3
"""对话式麦当劳健身餐推荐 · 编排入口（含持续学习）。

流程：
  对话文本 → nlu 解析 → planner 定该餐预算 → 载入/更新偏好模型 →
  推荐引擎(带偏好偏置) → 输出推荐清单 + 估算热量 + 理由 + 模型更新说明

用法:
  python run_dialogue.py --conv examples/conversation_sample.txt \
                         --nutrition examples/nutrition_sample.txt \
                         --state state/user_prefs.json --top 3
  # 重置模型：加 --reset
  # 直接传文本：--text "身高175 ... 午餐吃麦当劳"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import (  # noqa: E402
    parse_nutrition, parse_signals, parse_signals_llm, parse_signals_llm_cached,
    build_plan, load, save,
    update_from_signals, recommend_combo, recommend_single, format_output,
    fetch_nutrition_data, make_stub_call_mcp,
    fetch_order_history, apply_order_history,
    ManualActivitySource, WearableActivitySource, merge_activity,
)


def _print_plan(plan: dict) -> None:
    goal_cn = {"cut": "减脂", "bulk": "增肌", "maintain": "维持"}.get(plan["goal"], plan["goal"])
    occ_cn = {"lunch": "午餐", "breakfast": "早餐", "dinner": "晚餐", "snack": "加餐"}.get(plan["meal_occasion"], plan["meal_occasion"])
    print(f"\n===== 身体·运动·目标计划（{goal_cn} · {occ_cn}）=====")
    print(f"  BMR: {plan['bmr']:.0f} kcal | 基础TDEE(职业): {plan['base_tdee']:.0f} | 运动消耗: {plan['exercise_burn']:.0f} kcal")
    print(f"  TDEE: {plan['tdee']:.0f} kcal | 每日缺口: {plan['daily_deficit']:.0f} | 每日目标: {plan['target_calories']:.0f} kcal")
    if plan.get("target_weight_kg"):
        print(f"  当前 {plan['weight_kg']:.0f}→目标 {plan['target_weight_kg']:.0f} kg"
              + (f" | 预计 {plan['est_weeks']:.0f} 周达标" if plan.get("est_weeks") else ""))
    print(f"  → 本餐({occ_cn})预算: {plan['per_meal_calories']:.0f} kcal / 蛋白 {plan['per_meal_protein']:.0f} g")
    if plan["assumptions"]:
        print("  假设: " + "; ".join(plan["assumptions"]))


def _print_reco(result: dict, plan: dict) -> None:
    occ_cn = {"lunch": "午餐", "breakfast": "早餐", "dinner": "晚餐", "snack": "加餐"}.get(plan["meal_occasion"], plan["meal_occasion"])
    print(f"\n----- {occ_cn}推荐餐品清单 -----")
    if result["combos"]:
        for i, c in enumerate(result["combos"], 1):
            names = " + ".join(x["name"] for x in c["items"])
            t = c["totals"]
            print(f"  {i}. {names}")
            print(f"     估算热量 {t['energy_kcal']:.0f} kcal | 蛋白 {t['protein']:.0f} | 脂肪 {t['fat']:.0f} | 碳水 {t['carbohydrate']:.0f} | 钠 {t['sodium']:.0f} | 评分 {c['score']:.3f}")
            print(f"     └ 推荐理由：{c['reason']}")
    elif result["single"]:
        for i, r in enumerate(result["single"], 1):
            n = r["nutrition"]
            print(f"  {i}. {r['name']}  估算热量 {n['energy_kcal']:.0f} kcal | 蛋白 {n['protein']:.0f} | 脂肪 {n['fat']:.0f} | 碳水 {n['carbohydrate']:.0f} | 钠 {n['sodium']:.0f}")
            print(f"     └ 推荐理由：{r['reason']}")


def _print_model_update(model: dict, changes: list[str]) -> None:
    print("\n----- 偏好模型如何基于本轮对话更新 -----")
    print(f"  累计对话轮次: {model['conversation_count']} | 更新时间: {model['updated_at']}")
    print("  本轮变更: " + ("；".join(changes) if changes else "无"))
    # 当前生效的软偏置 Top（来自口味/单品反馈）
    biases = []
    for kw, d in model.get("taste", {}).items():
        net = d.get("like", 0) - d.get("dislike", 0)
        if net:
            biases.append(f"口味[{kw}]净偏好{net:+d}")
    for nm, d in model.get("item_feedback", {}).items():
        net = d.get("accept", 0) - d.get("reject", 0)
        if net:
            biases.append(f"单品[{nm}]{net:+d}")
    if model.get("taboo"):
        print("  硬忌口(必剔除): " + ", ".join(model["taboo"]))
    if biases:
        print("  当前软偏置: " + "；".join(biases))
    print("  算法说明: 计数式偏好 + 指数衰减(每轮×0.97 缓慢遗忘)；软偏置微调排序，硬忌口强制过滤；下一轮对话继续增量更新。")


def main() -> None:
    ap = argparse.ArgumentParser(description="对话式麦当劳健身餐推荐（持续学习）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="直接传入对话文本")
    src.add_argument("--conv", help="对话文本文件路径")
    ap.add_argument("--nutrition", required=True, help="营养数据原文路径")
    ap.add_argument("--state", default="state/user_prefs.json", help="偏好模型持久化路径")
    ap.add_argument("--profile", default="state/user_profile.json", help="用户身体档案(跨轮记忆)")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--reset", action="store_true", help="重置偏好模型与身体档案")
    ap.add_argument("--mode", choices=["single", "combo", "both"], default="combo")
    ap.add_argument("--nlu", choices=["llm", "rule"], default="llm",
                    help="NLU 后端：llm(默认, 主路径) / rule(规则兜底)")
    ap.add_argument("--llm-stub", action="store_true",
                    help="用规则解析模拟 LLM 输出，演示 LLM 管线(无真实 API 时)")
    ap.add_argument("--no-cache", action="store_true",
                    help="禁用 NLU 缓存，每次都调用 LLM（调试用）")
    ap.add_argument("--mcp-stub", action="store_true",
                    help="用本地样例文件模拟真实 mcd_mcp 调用（演示取数适配器，未配置 MCP 时）")
    ap.add_argument("--activity", default=None,
                    help="可穿戴/健康App导出的运动记录(JSON/CSV)，实测消耗优先覆盖 MET 估算")
    ap.add_argument("--history", default=None,
                    help="用户常点餐品历史(订单列表JSON)，模拟 mcd_mcp order-list；注入后优先沿用熟悉餐品做智能推荐")
    args = ap.parse_args()

    text = Path(args.conv).read_text(encoding="utf-8") if args.conv else args.text
    # 取数：优先用注入的 mcd_mcp 调用(本演示用 --mcp-stub 模拟)，否则回退本地样例
    call_mcp = make_stub_call_mcp(args.nutrition) if args.mcp_stub else None
    raw, menu_src = fetch_nutrition_data(call_mcp, args.nutrition)
    print(f"[菜单来源] {menu_src}")

    # 载入持久化身体档案（含 NLU 缓存）；重置则清空
    if args.reset:
        body_profile: dict = {}
    else:
        body_profile = load_json(args.profile)

    # 1) NLU（LLM 主路径 + 缓存；规则兜底）
    if args.nlu == "rule":
        signals, backend = parse_signals(text), "rule"
    else:
        llm_call = None
        if args.llm_stub:
            def llm_call(prompt):  # noqa: E306
                # 用规则解析模拟 LLM 返回的 JSON（仅演示管线，无真实 API 时）
                return json.dumps(parse_signals(text), ensure_ascii=False)
        signals, backend = parse_signals_llm_cached(
            text, llm_call, body_profile, return_backend=True, use_cache=not args.no_cache)
    print(f"[NLU 后端] {backend}")

    # 2) 身体档案跨轮记忆：身高/体重/目标体重/年龄/性别 持久化
    for k in ("height_cm", "weight_kg", "target_weight_kg", "age", "gender"):
        if k in signals:
            body_profile[k] = signals[k]
    # 职业/久坐活动仅当本轮显式提及时才覆盖（避免静息日把久坐职业抹掉）
    occ_explicit = bool(signals.get("exercises")) or any(k in text for k in ("久坐", "剪辑", "办公", "程序", "坐班"))
    if occ_explicit and "base_activity" in signals:
        body_profile["base_activity"] = signals["base_activity"]
    save_json(args.profile, body_profile)
    plan_signals = dict(body_profile)
    for k in ("exercises", "meal_occasion", "taste_like", "taste_dislike", "taboo", "scene", "raw"):
        if k in signals:
            plan_signals[k] = signals[k]
    if "base_activity" not in plan_signals and "base_activity" in signals:
        plan_signals["base_activity"] = signals["base_activity"]

    # 2.5) 必要身体数据缺失 → 通用示例模式（不崩溃，先给参考并提示补全）
    #      真实用户首条消息常只有"午餐吃麦当劳"，缺身高/体重；此处分流避免 ValueError。
    generic_mode = False
    _ESSENTIAL = ("height_cm", "weight_kg")
    if any(k not in plan_signals for k in _ESSENTIAL):
        generic_mode = True
        _DEFAULTS = {"height_cm": 175, "weight_kg": 70.0,
                     "target_weight_kg": 70.0, "age": 30, "gender": "male"}
        for k, v in _DEFAULTS.items():
            plan_signals.setdefault(k, v)

    # 3) 运动消耗：手动 MET 估算 + 可穿戴实测（真实数据优先）
    #    仅当传入 --activity（真实外部数据）时才覆盖 planner 的 MET 估算；
    #    否则交回 planner 自行按 MET 计算，避免误打"可穿戴实测"假设。
    weight = plan_signals.get("weight_kg", 70.0)
    manual_act = ManualActivitySource(weight).get_session(plan_signals)
    exercise_burn_override = None
    activity_src_note = None
    if args.activity:
        wearable_act = WearableActivitySource(args.activity).get_session(plan_signals)
        activity_session = merge_activity(manual_act, wearable_act)
        if activity_session.items:
            exercise_burn_override = activity_session.total_kcal()
            if wearable_act.has_measured():
                activity_src_note = "可穿戴实测(覆盖MET估算)"
            else:
                activity_src_note = "可穿戴MET估算"
    # 4) 计划
    plan = build_plan(plan_signals, exercise_burn_override=exercise_burn_override)
    if generic_mode:
        plan["assumptions"].append("⚠️ 缺少身高/体重，按通用成人(175cm/70kg/维持)示例，非个性化匹配")
        print("⚠️ 检测到缺少身体数据（身高/体重），以下按【通用成人示例】给出，仅供参考、非个性化匹配。")
        print("   想要个性化推荐，请补充：身高、体重、目标体重（如：身高175 体重70 目标65 减脂）。")

    # 4) 偏好模型载入/重置
    if args.reset:
        from engine import init_model
        model = init_model()
    else:
        model = load(args.state)
    # 5) 更新模型（持续学习）
    items = parse_nutrition(raw)
    model, changes = update_from_signals(model, signals, menu_items=items)
    # 5.5) 历史常点 → 软偏置（智能推荐：优先沿用熟悉餐品，而非每次从零推荐）
    favorites: dict = {}
    if args.history:
        favorites = fetch_order_history(None, args.history)
        if favorites:
            apply_order_history(model, favorites)
    save(model, args.state)
    # 6) 推荐
    single = recommend_single(items, plan, model=model, top_n=args.top) if args.mode in ("single", "both") else None
    combo = recommend_combo(items, plan, model=model, top_n=args.top) if args.mode in ("combo", "both") else None
    result = format_output(single, combo, plan, prefs={})
    # 7) 输出
    _print_plan(plan)
    if activity_src_note:
        print(f"  运动消耗来源: {activity_src_note}（合计 {exercise_burn_override:.0f} kcal）")
    _print_reco(result, plan)
    _print_model_update(model, changes)
    # 历史常点提示 + 两步触发说明
    if favorites:
        top = list(favorites.items())[:5]
        print(f"\n你常吃的(Top{len(top)}): " + ", ".join(f"{n}×{c}" for n, c in top))
        if generic_mode:
            print("👉 以上为基于你常吃的【智能推荐】(尚未结合身体数据)。")
            print("   为了更精准的个性化推荐，请补充：身高、体重、目标体重、目标(减脂/增肌/维持)，"
                  "以及忌口/口味偏好——我来重新算。")
        else:
            print("👉 以上为结合【你常吃的 + 你的身体数据】的个性化推荐。")


def load_json(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_json(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
