"""持续学习偏好模型（Continual Preference Model）。

设计要点：
- 以 JSON 持久化，结构轻量、可解释。
- 计数式偏好 + 指数衰减（旧偏好缓慢遗忘，适应口味变化）。
- 两类作用：
  * 硬忌口(hard taboo)：直接作为过滤条件，命中即剔除。
  * 软偏置(soft bias)：口味/单品反馈转成打分权重，微调排序而非一刀切。
- 增量更新：每轮对话抽取信号后调用 update_from_signals，返回变更说明便于解释。
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TypedDict

# 口味 → 餐品名包含即归类的启发式映射
TASTE_ITEMS = {
    "辣": ["辣", "香辣", "绝代双翅", "蒜啦", "薄皮焦香", "BBQ", "蜜汁", "椒"],
    "甜": ["新地", "派", "雪冰", "麦旋风", "拉明顿", "朱古力", "阿芙佳朵", "糖", "甜", "橙", "果汁", "怡泉", "果源"],
    "咸": ["薯条", "薯饼", "脆薯", "油条", "玉米杯"],
    "清淡": ["沙拉", "玉米杯", "纯牛奶", "苹果片", "粥", "豆浆", "鲜萃", "茶", "美式", "牛奶"],
}
# 软偏置权重
W_TASTE_LIKE = 1.2
W_TASTE_DISLIKE = 1.6
W_ITEM_ACCEPT = 2.0
W_ITEM_REJECT = 2.5
DECAY = 0.97  # 每轮更新前对计数的遗忘系数

_POS_WORDS = ["喜欢", "爱吃", "不错", "好吃", "爱", "点这个", "就吃这个"]
_NEG_WORDS = ["难吃", "不想吃", "腻", "不喜欢", "别吃", "换一个"]


class PrefModel(TypedDict, total=False):
    version: int
    conversation_count: int
    updated_at: str
    taste: dict[str, dict[str, int]]      # {kw: {like, dislike}}
    taboo: list[str]
    scene: dict[str, int]
    item_feedback: dict[str, dict[str, int]]  # {name: {accept, reject}}


def init_model() -> PrefModel:
    return {
        "version": 1,
        "conversation_count": 0,
        "updated_at": "",
        "taste": {},
        "taboo": [],
        "scene": {},
        "item_feedback": {},
    }


def load(path: str) -> PrefModel:
    p = Path(path)
    if not p.exists():
        return init_model()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return init_model()


def save(model: PrefModel, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")


def _decay(model: PrefModel) -> None:
    for kw, d in model.get("taste", {}).items():
        d["like"] = int(d.get("like", 0) * DECAY)
        d["dislike"] = int(d.get("dislike", 0) * DECAY)
    for name, d in model.get("item_feedback", {}).items():
        d["accept"] = int(d.get("accept", 0) * DECAY)
        d["reject"] = int(d.get("reject", 0) * DECAY)


def _item_tastes(name: str) -> list[str]:
    return [t for t, subs in TASTE_ITEMS.items() if any(s in name for s in subs)]


def update_from_signals(model: PrefModel, signals: dict, menu_items: list[dict] | None = None) -> tuple[PrefModel, list[str]]:
    """增量更新模型，返回 (新模型, 变更说明)。"""
    before = copy.deepcopy(model)
    _decay(model)

    changes: list[str] = []
    taste = model.setdefault("taste", {})
    for kw in signals.get("taste_like", []):
        taste.setdefault(kw, {"like": 0, "dislike": 0})
        taste[kw]["like"] += 1
        changes.append(f"口味偏好[喜欢:{kw}] +1")
    for kw in signals.get("taste_dislike", []):
        taste.setdefault(kw, {"like": 0, "dislike": 0})
        taste[kw]["dislike"] += 1
        changes.append(f"口味偏好[不爱:{kw}] +1")

    for taboo in signals.get("taboo", []):
        if taboo not in model.get("taboo", []):
            model.setdefault("taboo", []).append(taboo)
            changes.append(f"硬忌口 +{taboo}")

    for sc in signals.get("scene", []):
        model.setdefault("scene", {}).setdefault(sc, 0)
        model["scene"][sc] += 1
        changes.append(f"场景[{sc}] +1")

    # 单品显式反馈：对话中若提及某餐品名且带正/负向词
    if menu_items:
        names = [it["name"] for it in menu_items]
        text = signals.get("raw", "")
        for nm in names:
            if nm in text:
                if any(w in text for w in _POS_WORDS):
                    model.setdefault("item_feedback", {}).setdefault(nm, {"accept": 0, "reject": 0})
                    model["item_feedback"][nm]["accept"] += 1
                    changes.append(f"单品反馈[{nm}] 接受+1")
                elif any(w in text for w in _NEG_WORDS):
                    model.setdefault("item_feedback", {}).setdefault(nm, {"accept": 0, "reject": 0})
                    model["item_feedback"][nm]["reject"] += 1
                    changes.append(f"单品反馈[{nm}] 拒绝+1")

    model["conversation_count"] = model.get("conversation_count", 0) + 1
    model["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not changes:
        changes.append("本轮无新增偏好信号（仅刷新衰减与计数）")
    return model, changes


def hard_excludes(model: PrefModel) -> list[str]:
    """返回硬忌口关键词（已展开为菜单实际子串），供推荐过滤。"""
    # 忌口词 → 菜单名中实际出现的子串
    _EXPAND = {
        "牛肉": ["牛", "安格斯", "霸"],
        "牛": ["牛", "安格斯", "霸"],
        "猪": ["猪"],
        "鸡": ["鸡"],
        "鱼": ["鱼"],
        "海鲜": ["鱼"],
        "辣": ["辣", "香辣", "绝代双翅", "蒜啦", "薄皮焦香", "BBQ", "蜜汁", "椒"],
    }
    ex: list[str] = []
    for t in model.get("taboo", []):
        ex.append(t)
        ex.extend(_EXPAND.get(t, []))
    seen = set()
    out = []
    for k in ex:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def bias_for_item(item: dict, model: PrefModel) -> float:
    """软偏置：口味偏好 + 单品反馈，叠加到推荐打分。"""
    bias = 0.0
    tastes = _item_tastes(item["name"])
    for t in tastes:
        d = model.get("taste", {}).get(t)
        if d:
            bias += d.get("like", 0) * W_TASTE_LIKE - d.get("dislike", 0) * W_TASTE_DISLIKE
    fb = model.get("item_feedback", {}).get(item["name"])
    if fb:
        bias += fb.get("accept", 0) * W_ITEM_ACCEPT - fb.get("reject", 0) * W_ITEM_REJECT
    return bias


def apply_order_history(model: PrefModel, favorites: dict[str, int]) -> PrefModel:
    """把用户常点餐品作为正向单品反馈注入（软偏置）。

    用于"基于历史常吃的智能推荐"：常点餐品获得 accept 计数，recommender 打分时会优先沿用
    熟悉餐品，而不是每次都从零推荐陌生组合。与对话显式反馈共用 item_feedback 通道，不冲突。
    """
    fb = model.setdefault("item_feedback", {})
    for name, cnt in favorites.items():
        d = fb.setdefault(name, {"accept": 0, "reject": 0})
        d["accept"] += int(cnt)
    return model


__all__ = [
    "init_model", "load", "save", "update_from_signals",
    "hard_excludes", "bias_for_item", "apply_order_history", "PrefModel", "TASTE_ITEMS",
]
