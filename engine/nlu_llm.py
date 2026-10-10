"""LLM 驱动的对话 NLU（替代规则式，提升鲁棒性）。

设计：
- 主路径：把对话文本 + 结构化 JSON Schema 交给 LLM，抽取 Signals。
- 失败/不可用：自动回退到规则式 parse_signals，保证系统不崩。
- llm_call 可注入：生产环境由 WorkBuddy / cloudbase 免密钥 LLM 注入；
  测试可用 mock / stub。
- 归一化：把 LLM 输出对齐到与规则式完全一致的 Signals 结构，
  下游 planner / prefs_model / recommender 无需改动。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Callable

from .nlu import Signals, parse_signals

# 口味规范集（与 prefs_model.TASTE_ITEMS 对应）
_CANON_TASTE = {"辣", "甜", "咸", "清淡", "多汁", "香"}
# base_activity 中文/英文归一
_ACTIVITY_MAP = {
    "久坐": "sedentary", "办公": "sedentary", "坐班": "sedentary", " sedentary": "sedentary",
    "轻活动": "light", "偶尔运动": "light",
    "中等": "moderate", "适中": "moderate",
    "活跃": "active", "经常运动": "active", "高频训练": "active",
    "极高": "very_active", "体力活": "very_active",
}

NLU_SYSTEM_PROMPT = (
    "你是一个营养点餐助手的语义解析器。从用户日常对话中提取结构化信号，"
    "只输出 JSON，不要任何解释或 Markdown 代码块标记。\n"
    "字段说明：\n"
    "- height_cm: 身高(cm)整数，无则 null\n"
    "- weight_kg: 当前体重(kg)数字，无则 null\n"
    "- target_weight_kg: 目标体重(kg)数字，无则 null\n"
    "- age: 年龄整数，无则 null\n"
    "- gender: 'male'/'female'，无则 null\n"
    "- base_activity: 职业/日常活动强度，取 sedentary/light/moderate/active/very_active\n"
    "- exercises: 运动列表，每项 {label, met, minutes}；MET 参考：跑步7 游泳6 骑车6 力量训练5 瑜伽2.5 快走4.3 跳绳10；分钟用阿拉伯数字\n"
    "- meal_occasion: breakfast/lunch/dinner/snack\n"
    "- taste_like: 喜欢口味，取值如 辣/甜/咸/清淡/多汁/香\n"
    "- taste_dislike: 不喜欢口味，同上\n"
    "- taboo: 不吃/忌口/过敏 的食材或类别，如 牛肉/辣/海鲜/花生\n"
    "- scene: 用餐场景，如 午餐/健身后/加班/通勤/聚会\n"
    "注意：中文数词(一小时→60分钟)、隐含体重(目标比现在轻→减脂)都要正确换算。"
)


def build_nlu_prompt(text: str) -> str:
    return f"{NLU_SYSTEM_PROMPT}\n\n用户对话：{text}"


def _extract_json(raw: str) -> dict:
    """从 LLM 输出中抽取 JSON 对象（容忍 ```json 代码块 / 前后废话）。"""
    if not raw:
        raise ValueError("空响应")
    s = raw.strip()
    # 去 ```json ... ``` 包裹
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        s = m.group(1)
    else:
        # 取第一个 { 到最后一个 } 之间的内容
        a, b = s.find("{"), s.rfind("}")
        if a != -1 and b != -1 and b > a:
            s = s[a:b + 1]
    return json.loads(s)


def _norm_taste(values) -> list[str]:
    out = []
    for v in (values or []):
        v = str(v).strip()
        if v in _CANON_TASTE:
            out.append(v)
        else:
            hit = next((c for c in _CANON_TASTE if c in v), None)
            if hit:
                out.append(hit)
    return out


def _norm_activity(v):
    if not v:
        return None
    v = str(v).strip().lower()
    if v in ("sedentary", "light", "moderate", "active", "very_active"):
        return v
    return _ACTIVITY_MAP.get(v)


def _normalize(obj: dict) -> Signals:
    ex = []
    for e in obj.get("exercises", []) or []:
        if not isinstance(e, dict):
            continue
        minutes = e.get("minutes") or e.get("duration_minutes") or e.get("duration")
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = 0
        if minutes <= 0:
            continue
        met = e.get("met") or 0
        try:
            met = float(met)
        except (TypeError, ValueError):
            met = 0.0
        ex.append({"label": str(e.get("label", "运动")), "met": met, "minutes": minutes})

    sig: Signals = {
        "exercises": ex,
        "base_activity": _norm_activity(obj.get("base_activity")),
        "meal_occasion": obj.get("meal_occasion"),
        "taste_like": _norm_taste(obj.get("taste_like")),
        "taste_dislike": _norm_taste(obj.get("taste_dislike")),
        "taboo": [str(t).strip() for t in (obj.get("taboo") or []) if t],
        "scene": [str(s).strip() for s in (obj.get("scene") or []) if s],
        "raw": obj.get("raw", ""),
    }
    for k in ("height_cm", "weight_kg", "target_weight_kg", "age"):
        v = obj.get(k)
        if v is None or v == "":
            continue
        try:
            sig[k] = float(v) if k != "height_cm" and k != "age" else int(v)  # type: ignore
        except (TypeError, ValueError):
            pass
    g = obj.get("gender")
    if g in ("male", "female"):
        sig["gender"] = g  # type: ignore
    return sig


def parse_signals_llm(
    text: str,
    llm_call: Callable[[str], str] | None = None,
    return_backend: bool = False,
):
    """LLM 解析；无 llm_call 或失败则回退规则式。

    Args:
        text: 用户对话
        llm_call: 接收 prompt 返回文本的可调用对象（由外部注入 LLM）
        return_backend: 为 True 时返回 (signals, backend_name)
    """
    if llm_call is not None:
        try:
            raw = llm_call(build_nlu_prompt(text))
            sig = _normalize(_extract_json(raw))
            if _is_usable(sig):
                return (sig, "llm") if return_backend else sig
        except Exception:
            pass
    # 回退
    rule = parse_signals(text)
    return (rule, "rule-fallback") if return_backend else rule


def _is_usable(sig: Signals) -> bool:
    """LLM 结果是否至少包含一项有效信号。"""
    return any([
        sig.get("height_cm"), sig.get("weight_kg"), sig.get("target_weight_kg"),
        sig.get("age"), sig.get("gender"), sig.get("exercises"),
        sig.get("meal_occasion"), sig.get("taste_like"), sig.get("taste_dislike"),
        sig.get("taboo"), sig.get("scene"), sig.get("base_activity"),
    ])


# 判断文本是否含「值得再调 LLM」的新信息（否则视为续对话，直接复用上次结果）
_NEW_INFO_KW = [
    "身高", "体重", "目标体重", "年龄", "性别", "男", "女", "跑步", "游泳", "骑车",
    "健身", "瑜伽", "撸铁", "跳绳", "快走", "运动", "辣", "甜", "咸", "清淡", "多汁",
    "不吃", "忌口", "过敏", "别给", "午餐", "早餐", "晚餐", "夜宵", "想吃", "喜欢",
    "爱", "讨厌",
]


def _has_new_info(text: str) -> bool:
    return any(k in text for k in _NEW_INFO_KW)


def parse_signals_llm_cached(
    text: str,
    llm_call: Callable[[str], str] | None,
    state: dict,
    return_backend: bool = False,
    use_cache: bool = True,
):
    """带缓存的 LLM NLU：减少重复 LLM 调用。

    - 相同文本（哈希命中）：直接复用，不调 LLM。
    - 纯续对话（无新信息且已有上次结果）：复用 _last_signals，不调 LLM。
    - 否则调用 LLM（或其回退），并写入 state['_nlu_cache'] / state['_last_signals']。
    state 即持久化的 user_profile，随其一起落盘。
    """
    h = hashlib.md5(text.strip().encode("utf-8")).hexdigest()
    cache = state.setdefault("_nlu_cache", {})
    if use_cache and h in cache:
        sig = cache[h]
        return (sig, "llm-cache") if return_backend else sig
    if use_cache and not _has_new_info(text) and state.get("_last_signals"):
        return (state["_last_signals"], "llm-skip") if return_backend else state["_last_signals"]
    sig, backend = parse_signals_llm(text, llm_call, return_backend=True)
    cache[h] = sig
    state["_last_signals"] = sig
    return (sig, backend) if return_backend else sig


__all__ = ["parse_signals_llm", "parse_signals_llm_cached", "build_nlu_prompt",
           "NLU_SYSTEM_PROMPT", "Signals"]
