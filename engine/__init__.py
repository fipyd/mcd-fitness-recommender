"""麦当劳健身餐推荐引擎包。"""

from .menu_parser import parse_nutrition, classify
from .profile import build_target, calc_bmr
from .recommender import recommend_single, recommend_combo, filter_items, Preferences
from .formatter import format_output
from .nlu import parse_signals, Signals
from .nlu_llm import parse_signals_llm, parse_signals_llm_cached, build_nlu_prompt
from .planner import build_plan, Plan
from .prefs_model import init_model, load, save, update_from_signals, hard_excludes, bias_for_item, apply_order_history
from .mcp_adapter import (fetch_nutrition_data, make_stub_call_mcp,
                          aggregate_favorites, fetch_order_history, make_stub_order_history)
from .activity_source import (ManualActivitySource, WearableActivitySource,
                              merge_activity, ActivitySession)

__all__ = [
    "parse_nutrition", "classify", "build_target", "calc_bmr",
    "recommend_single", "recommend_combo", "filter_items",
    "format_output", "Preferences",
    "parse_signals", "parse_signals_llm", "parse_signals_llm_cached", "build_nlu_prompt", "build_plan", "Plan", "Signals",
    "init_model", "load", "save", "update_from_signals",
    "hard_excludes", "bias_for_item", "apply_order_history",
    "fetch_nutrition_data", "make_stub_call_mcp",
    "aggregate_favorites", "fetch_order_history", "make_stub_order_history",
    "ManualActivitySource", "WearableActivitySource", "merge_activity", "ActivitySession",
]
