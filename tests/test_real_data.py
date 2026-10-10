"""真实数据接入测试：mcd_mcp 取数适配器 + 可穿戴运动实测覆盖。

覆盖：
1. fetch_nutrition_data：注入 call_mcp → 来源 "mcp"；无注入 → 回退 "fallback-file"
2. WearableActivitySource(JSON/CSV) 解析实测 kcal
3. merge_activity：可穿戴实测优先覆盖手动 MET 估算，并为未覆盖类型补位
4. planner：exercise_burn_override 采用实测消耗并标注假设
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import (  # noqa: E402
    fetch_nutrition_data, make_stub_call_mcp,
    ManualActivitySource, WearableActivitySource, merge_activity,
    parse_signals, build_plan,
)

NUTRITION = str(ROOT / "examples" / "nutrition_sample.txt")
WEARABLE_JSON = str(ROOT / "examples" / "wearable_run.json")
WEARABLE_CSV = str(ROOT / "examples" / "wearable_run.csv")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"FAIL: {msg}")
    print(f"  ok  {msg}")


def test_mcp_adapter_mcp_source():
    print("[T1] fetch_nutrition_data · mcp 来源")
    call_mcp = make_stub_call_mcp(NUTRITION)
    data, src = fetch_nutrition_data(call_mcp)
    _assert(src == "mcp", "注入 call_mcp 时来源应为 mcp")
    _assert(data.lstrip().startswith("[") and "productName" in data, "返回的 data 应为菜单头[...]{...}且含 productName")


def test_mcp_adapter_fallback():
    print("[T2] fetch_nutrition_data · 回退本地文件")
    data, src = fetch_nutrition_data(None, NUTRITION)
    _assert(src == "fallback-file", "无 call_mcp 时来源应为 fallback-file")
    _assert(data.lstrip().startswith("[") and "productName" in data, "回退文件内容应为菜单头[...]{...}")


def test_wearable_json_and_csv():
    print("[T3] 可穿戴解析 JSON / CSV")
    j = WearableActivitySource(WEARABLE_JSON).get_session()
    c = WearableActivitySource(WEARABLE_CSV).get_session()
    _assert(j.has_measured(), "JSON 导出应包含实测 kcal")
    _assert(c.has_measured(), "CSV 导出应包含实测 kcal")
    _assert(abs(j.total_kcal() - c.total_kcal()) < 1e-6, "JSON 与 CSV 解析总消耗应一致")
    _assert(abs(j.total_kcal() - 970) < 1e-6, "JSON 总消耗应为 620+350=970")


def test_merge_prefers_measured():
    print("[T4] merge_activity · 实测覆盖 MET 且补位未覆盖类型")
    sig = parse_signals("身高175cm、体重70kg、目标体重65kg、职业剪辑师、久坐时间长、下班后跑步一小时、午餐吃麦当劳")
    manual = ManualActivitySource(sig["weight_kg"]).get_session(sig)
    wearable = WearableActivitySource(WEARABLE_JSON).get_session(sig)
    merged = merge_activity(manual, wearable)
    # 手动只估算了 跑步(MET=514)；可穿戴实测 跑步=620 且新增 游泳=350
    _assert(abs(merged.total_kcal() - 970) < 1e-6, "合并后总消耗应为可穿戴实测 970（覆盖手动514，新增游泳）")
    _assert("游泳" in merged.labels(), "合并应保留可穿戴新增的 游泳 类型")


def test_planner_override_assumption():
    print("[T5] planner · 实测消耗覆盖 + 假设标注")
    sig = parse_signals("身高175cm、体重70kg、目标体重65kg、职业剪辑师、久坐时间长、下班后跑步一小时、午餐吃麦当劳")
    manual = ManualActivitySource(sig["weight_kg"]).get_session(sig)
    wearable = WearableActivitySource(WEARABLE_JSON).get_session(sig)
    merged = merge_activity(manual, wearable)
    plan = build_plan(sig, exercise_burn_override=merged.total_kcal())
    _assert(plan["exercise_burn"] == 970, "计划运动消耗应等于实测 970")
    _assert(any("可穿戴" in a for a in plan["assumptions"]), "计划假设应标注采用可穿戴实测")


def main() -> int:
    print("=== 真实数据接入测试 ===")
    test_mcp_adapter_mcp_source()
    test_mcp_adapter_fallback()
    test_wearable_json_and_csv()
    test_merge_prefers_measured()
    test_planner_override_assumption()
    print("\nALL PASS ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
