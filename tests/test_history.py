"""历史常点接入测试：mcd_mcp 订单历史 → 聚合 → 偏置 → 影响推荐排序。

覆盖：
1. aggregate_favorites：订单列表聚合为 {name:count} 降序
2. fetch_order_history：回退文件解析
3. apply_order_history：常点餐品注入 item_feedback 正向偏置
4. bias_for_item：熟悉餐品获得正向偏置、陌生餐品为 0
5. 集成：注入历史后，top 组合中出现常点餐品（智能推荐生效）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import (  # noqa: E402
    parse_nutrition, build_plan, init_model,
    fetch_order_history, aggregate_favorites, apply_order_history, bias_for_item,
    recommend_combo,
)

ORDER_HISTORY = str(ROOT / "examples" / "order_history_sample.json")
ORDER_HISTORY_REAL = str(ROOT / "examples" / "order_history_real.json")
NUTRITION = str(ROOT / "examples" / "nutrition_sample.txt")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok  {msg}")


def test_aggregate_favorites():
    print("[T1] aggregate_favorites")
    orders = [
        {"items": [{"name": "巨无霸"}, {"name": "中薯条"}]},
        {"items": [{"name": "巨无霸"}]},
        {"items": [{"name": "中薯条"}, {"name": "无糖可口可乐中杯"}]},
    ]
    fav = aggregate_favorites(orders)
    _assert(fav.get("巨无霸") == 2 and fav.get("中薯条") == 2, "巨无霸/中薯条各 2 次")
    _assert(list(fav.keys())[0] in ("巨无霸", "中薯条"), "结果按次数降序")


def test_fetch_order_history_fallback():
    print("[T2] fetch_order_history · 回退文件")
    fav = fetch_order_history(None, ORDER_HISTORY)
    _assert(fav.get("巨无霸") == 4, "巨无霸聚合为 4 次(来自样例订单)")
    _assert("中薯条" in fav and "无糖可口可乐中杯" in fav, "中薯条/可乐也在常点中")


def test_apply_order_history():
    print("[T3] apply_order_history · 注入软偏置")
    model = init_model()
    apply_order_history(model, {"巨无霸": 4, "中薯条": 4})
    fb = model["item_feedback"]
    _assert(fb.get("巨无霸", {}).get("accept") == 4, "巨无霸 accept=4")
    _assert(fb.get("中薯条", {}).get("accept") == 4, "中薯条 accept=4")


def test_bias_for_item():
    print("[T4] bias_for_item · 熟悉餐品正偏置")
    model = init_model()
    apply_order_history(model, {"巨无霸": 4})
    items = parse_nutrition(Path(NUTRITION).read_text(encoding="utf-8"))
    bigmac = next(i for i in items if i["name"] == "巨无霸")
    other = next(i for i in items if i["name"] == "麦香鱼" or i["name"] == "板烧鸡腿堡")
    _assert(bias_for_item(bigmac, model) > 0, "巨无霸(常点)偏置为正")
    _assert(bias_for_item(other, model) == 0, "陌生餐品偏置为 0")


def test_integration_history_influences_combo():
    print("[T5] 集成 · 注入历史后 top 组合含常点餐品")
    items = parse_nutrition(Path(NUTRITION).read_text(encoding="utf-8"))
    sig = {"height_cm": 175, "weight_kg": 70, "target_weight_kg": 70,
           "gender": "male", "age": 30, "meal_occasion": "lunch"}
    plan = build_plan(sig)
    fav = fetch_order_history(None, ORDER_HISTORY)
    model = init_model()
    apply_order_history(model, fav)
    combos = recommend_combo(items, plan, model=model, top_n=3)
    top_names = [x["name"] for c in combos for x in c["items"]]
    hit = [n for n in top_names if n in fav]
    _assert(bool(hit), f"top 组合中出现常点餐品: {hit[:5]}")


def test_fetch_order_history_real_structure():
    print("[T6] fetch_order_history · 真实 order-list 结构（data.list + 套餐子项 + 排除取消单）")
    fav = fetch_order_history(None, ORDER_HISTORY_REAL)
    # 真实结构：{data:{list:[订单]}} → 适配器外层包装后取 list；本文件直接是 {"list":[...]}
    _assert(fav.get("雪碧中杯") == 7, "雪碧中杯跨套餐展开=7(3+3+1)")
    _assert(fav.get("中薯条") == 3, "中薯条跨订单=3(订单1/2/5)")
    _assert(fav.get("板烧鸡腿堡") == 1, "板烧鸡腿堡仅来自已完成订单2=1（订单3已取消不计）")
    _assert(fav.get("麦辣鸡腿汉堡") == 2, "麦辣鸡腿汉堡=2(订单1/4)")
    # 取消订单(订单3)的全部子项不应计入：验证其独有项未出现
    _assert("Hold不住鸡排堡（椒盐风味）" not in fav, "取消订单独有子项不计入")
    # 两种取数路径一致：用 make_stub 模拟 {success,data:{list}} 包裹
    from engine.mcp_adapter import make_stub_order_history
    fav_live = fetch_order_history(make_stub_order_history(ORDER_HISTORY_REAL))
    _assert(fav_live == fav, "live 包裹结构与回退文件解析结果一致")


def main() -> int:
    print("=== 历史常点接入测试 ===")
    test_aggregate_favorites()
    test_fetch_order_history_fallback()
    test_apply_order_history()
    test_bias_for_item()
    test_integration_history_influences_combo()
    test_fetch_order_history_real_structure()
    print("\nALL PASS ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
