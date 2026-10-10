---
name: mcd-fitness-recommender
description: 面向健身人士的麦当劳餐品个性化推荐。调用 mcd_mcp 获取菜单营养数据，依据身体数据、训练目标（减脂/增肌/维持）与饮食偏好，按热量、蛋白质、碳水、脂肪、钠等指标筛选、打分、排序，输出单品与套餐组合推荐及适配理由。触发词：健身麦当劳、麦当劳增肌、减脂吃什么麦当劳、麦当劳蛋白、健身餐推荐。
---

# 麦当劳健身餐个性化推荐 Skill

## 概述
本技能为健身人群在麦当劳点餐时提供**基于个人数据的个性化匹配**。核心数据流：
`mcd_mcp.list-nutrition-foods`（取全量营养） → `engine/menu_parser` 解析 → `engine/profile` 算目标宏量 → `engine/recommender` 过滤/打分/组合 → `engine/formatter` 输出推荐餐品 + 营养构成 + 适配理由。

---

## 一、功能定义与核心能力

| 能力 | 说明 |
|---|---|
| 目标宏量计算 | 用 Mifflin-St Jeor 算 BMR，结合活动系数得 TDEE，按目标生成每日/每餐热量与蛋白/脂肪/碳水目标 |
| 单品推荐 | 过滤后按 fitness 分数排序，给"该目标下最优的单个高蛋白/低脂餐品" |
| 套餐组合推荐 | 在每餐热量预算内搜索 (主+副+饮) 组合，最大化蛋白覆盖、贴合热量、控钠 |
| 偏好过滤 | 素食 / 不吃牛 / 低钠 / 去糖饮料 / 排除关键词 / 热量·蛋白·钠上限 |
| 适配理由 | 每条推荐附带人话解释（热量贴合度、蛋白覆盖率、钠提示） |

---

## 二、通过 mcd_mcp 的数据调用方式与接口约定

### 2.1 核心取数接口：`list-nutrition-foods`
- **调用方式**：MCP 工具 `mcp__mcd-mcp__list-nutrition-foods`，**无入参**。
- **返回**：JSON `{success, code, message, data, ...}`，其中 `data` 为**字符串**。
- **data 结构**（字符串）：
  ```
  [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  ...
  ```
  首行 `[数量]{字段头}:` 是表头；其后每行一个餐品，逗号分隔。
- **字段约定**（解析后字段名 → 含义 → 单位）：

  | 字段 | 含义 | 单位 |
  |---|---|---|
  | name | 餐品名 | — |
  | nutrition_description | 备注（多为 null，含 "能量约…" 占位说明） | — |
  | energy_kj | 能量(千焦) | kJ |
  | energy_kcal | 能量(千卡) | kcal |
  | protein | 蛋白质 | g |
  | fat | 脂肪 | g |
  | carbohydrate | 碳水化合物 | g |
  | sodium | 钠 | mg |
  | calcium | 钙 | mg |

- **调用约定（Agent 必须遵守）**：
  1. 先调用 `list-nutrition-foods` 取全量数据，把 `data` 原文（含或不含头部均可）传给 `engine/menu_parser.parse_nutrition`。
  2. 解析时对 `null`/空/"能量约…" 占位统一按 `0` 处理（见 `menu_parser._to_float`）。
  3. 本技能**只消费营养数据**，不发起下单；下单类接口 `query_meals` / `query_meal_detail` / `create_order` 仅当用户明确要求"帮我下单"时再按 mcd_mcp 既有规则调用（需 storeCode/beType/orderType）。

### 2.2 解析约定
- 头部行以 `[` 开头且含 `{` 且以 `:` 结尾 → 跳过。
- 任意行逗号不足 9 段或首段为空 → 跳过（健壮性）。
- 名称含「霸」(巨无霸) 与「堡」均视为汉堡主食类，需一并处理（关键词差异已兜底）。

---

## 三、推荐逻辑

### 3.1 目标宏量（`profile.build_target`）
- BMR（男）= `10·kg + 6.25·cm − 5·age + 5`；女 `…− 161`。
- TDEE = BMR × 活动系数（sedentary 1.2 / light 1.375 / moderate 1.55 / active 1.725 / very_active 1.9）。
- 目标乘数：减脂 0.8、增肌 1.1、维持 1.0。
- 蛋白目标 g/kg：减脂 2.0、增肌 1.8、维持 1.6（保肌优先）。
- 脂肪 = 总热量×25%÷9；碳水 = 剩余热量÷4。
- 每餐目标 = 每日目标 ÷ `meals_per_day`。

### 3.2 过滤（`recommender.filter_items`）
依 `preferences` 逐项剔除：排除关键词 / 素食（剔禽畜鱼肉类关键词）/ 不吃牛 / 单品热量或钠上限。

### 3.3 单品打分（`recommender.score_single`）
- 减脂：`蛋白×3 − 脂肪×1.0 − 热量×0.05 − 钠×0.003`（重蛋白密度、轻脂/热量/钠）
- 增肌：`蛋白×1.5 + 热量×0.15 − 钠×0.002`（需能量与蛋白）
- 维持：`蛋白×2 − |热量−每餐目标|×0.01 − 脂肪×0.3`（贴近目标、均衡）

### 3.4 套餐组合（`recommender.recommend_combo`）
- 分类：main / side / drink（`menu_parser.classify` 按名称关键词）。
- 预算窗口：每餐热量 `[0.7×, 1.15×]`；去糖时饮料仅限无糖/纯水/茶/黑咖啡。
- 搜索：遍历主食 → 在剩余预算内选蛋白质密度最高的副食 → 选近零热量饮料。
- 组合分 = `热量贴合度×0.5 + 蛋白覆盖率×0.5 − 钠/1000×0.1`，降序取 Top-N。

---

## 四、输入格式

用户需提供三类数据，由 Agent 收齐后组装为 `profile` JSON 传入引擎：

```json
{
  "gender": "male | female",
  "weight_kg": 75,
  "height_cm": 178,
  "age": 28,
  "activity": "sedentary|light|moderate|active|very_active",
  "goal": "cut | bulk | maintain",
  "meals_per_day": 3,
  "protein_per_kg": 2.0,
  "preferences": {
    "vegetarian": false,
    "beef_free": false,
    "low_sodium": false,
    "no_sugar": false,
    "exclude_keywords": [],
    "min_protein": 0,
    "max_calorie": 0,
    "max_sodium": 0
  }
}
```
- **身体数据**：gender / weight_kg / height_cm / age（必填）。
- **训练目标**：goal + activity + meals_per_day（决定每日/每餐预算）。
- **饮食偏好**：preferences（全可空，缺省不限制）。

---

## 五、输出格式

`format_output` 产出结构化结果，含 `target`、`preferences`、`single[]`、`combos[]`：

```json
{
  "target": { "tdee": 2678, "target_calories": 2142, "per_meal_calories": 714, "per_meal_protein": 50, "...": "..." },
  "single": [
    { "name": "蒜了吧…带骨里脊", "nutrition": {"energy_kcal":126,"protein":19,"fat":2,"carbohydrate":4,"sodium":750,"calcium":59}, "score": 15.1, "reason": "蛋白质密度 15.1 g/100kcal … 减脂期较低脂的高蛋白选择。" }
  ],
  "combos": [
    { "items": [{"name":"果然多肉","energy_kcal":478,"protein":36,"fat":17,"carbohydrate":44,"sodium":1343}, "..."],
      "totals": {"energy_kcal":604,"protein":55,"fat":19,"carbohydrate":49,"sodium":2128},
      "score": 0.668,
      "reason": "总热量 604 kcal，略低于每餐目标（85%）…；蛋白质 55 g（覆盖 110%）…；钠 2128 mg 偏高，建议多喝水。" }
  ]
}
```
- **推荐餐品**：单品名 / 组合内多项名。
- **营养构成**：热量、蛋白、脂肪、碳水、钠、钙（组合另给合计 totals）。
- **适配理由**：人话解释热量贴合度、蛋白覆盖率、钠提示，绑定个人目标。

---

## 六、模块结构及各模块职责

```
mcd-fitness-recommender/
├── SKILL.md                # 技能定义、触发词、本方案全部约定与工作流
├── run.py                  # 命令行入口：读 profile + nutrition → 调引擎 → 输出（JSON/人话）
├── engine/
│   ├── __init__.py         # 包导出
│   ├── menu_parser.py      # 解析 list-nutrition-foods 字符串 → 结构体；classify 分 main/side/drink
│   ├── profile.py          # Mifflin-St Jeor 算 BMR/TDEE，按目标生成每日/每餐宏量 Target
│   ├── recommender.py      # 偏好过滤 + 单品打分 + 套餐组合搜索（核心算法）
│   └── formatter.py        # 结果结构化 + 生成人话适配理由
└── examples/
    ├── sample_profile.json # 减脂示例
    ├── bulk_profile.json   # 增肌示例
    ├── veg_profile.json    # 素食示例
    └── nutrition_sample.txt# 真实营养数据样本（来自 list-nutrition-foods）
```

| 模块 | 职责 | 关键函数 |
|---|---|---|
| menu_parser | 文本解析 + 分类 | `parse_nutrition`, `classify` |
| profile | 目标宏量计算 | `build_target`, `calc_bmr` |
| recommender | 过滤/打分/组合 | `filter_items`, `score_single`, `recommend_single`, `recommend_combo` |
| formatter | 输出格式化 | `format_output` |
| run.py | 编排与 CLI | `main` |

---

## 七、Agent 工作流（调用约定）

1. **收集输入**：向用户确认身体数据、训练目标、饮食偏好（缺省可给合理默认并标注）。
2. **取数**：调用 `mcd__mcd-mcp__list-nutrition-foods`，取得 `data` 原文。
3. **计算**：将 `data` 与用户 `profile` 传入 `run.py`（或 `engine` 包）执行推荐。
   - 命令行：`python run.py --profile <profile.json> --nutrition <data.txt> --mode both --top 5`
   - 或在对话内 `import engine` 直接调用。
4. **呈现**：用 `format_output` 的人话版本，按"目标概览 → 单品 → 套餐 → 适配理由"顺序输出；强调钠偏高的提醒。
5. **可选下单**：用户要求下单时，按 mcd_mcp 规则用 `query_meals`/`query_meal_detail` 取 code 与门店，再 `create_order`。

### 7.1 边界处理：首条消息常缺身体数据
真实用户首条消息常只有"午餐吃麦当劳"而无身高/体重。`run_dialogue.py` 检测到 `height_cm`/`weight_kg` 缺失时进入**通用示例模式**：用保守默认（175cm/70kg/维持）算出参考推荐，并明确标注"⚠️ 非个性化匹配"，同时提示用户补全身高/体重/目标体重。这样 skill 不会因缺数据而崩溃，先给参考再引导个性化。

---

## 八、运行与验证

```bash
# 减脂（默认示例）
python run.py --profile examples/sample_profile.json --nutrition examples/nutrition_sample.txt --mode both --top 5
# 增肌
python run.py --profile examples/bulk_profile.json  --nutrition examples/nutrition_sample.txt --mode combo --top 3
# 仅 JSON
python run.py --profile examples/veg_profile.json   --nutrition examples/nutrition_sample.txt --mode both --top 3 --json
```
验证已覆盖：cut / bulk / maintain 三目标；vegetarian / beef_free / no_sugar 偏好；解析健壮性（null、占位说明、头部行）。

---

## 九、已知限制
- 营养数据来自 mcd_mcp 快照，未含分量/烹饪油波动，实际以门店为准。
- 素食/不吃牛基于名称关键词过滤，"蜜汁快乐"等无肉字样的禽类单品可能漏过滤（best-effort）。
- 套餐组合为 (主+副+饮) 三元结构，未枚举"双主食/多小食"等复杂搭配。
- 麦当劳餐品钠普遍偏高，减脂/控钠人群建议搭配多喝水、当日清淡。

---

## 十、对话式扩展（持续学习）· 见 DIALOGUE_SYSTEM.md

在结构化输入之外，本 skill 支持**日常对话驱动 + 偏好持续学习**：

- 入口：`run_dialogue.py`（对话文本 → 解析 → 计划 → 学模型 → 推荐 → 解释更新）。
- 新增模块：`engine/nlu.py`（对话→信号）、`engine/planner.py`（运动MET消耗+减重缺口→该餐预算）、`engine/prefs_model.py`（计数式偏好模型+指数衰减+硬忌口/软偏置）。
- 身体档案 `state/user_profile.json` 跨轮记忆身高/体重/目标；偏好模型 `state/user_prefs.json` 增量更新。
- 示例：`examples/conversation_sample.txt`（减脂男）、`examples/conversation_2.txt`（忌辣/清淡/不吃牛，演示学习）。
- 完整算法设计与输出格式见同目录 `DIALOGUE_SYSTEM.md`。

---

## 十一、Agent 注入 LLM 的方式（生产使用）

NLU 主路径 `engine/nlu_llm.parse_signals_llm(text, llm_call)` 需要一个 LLM 调用钩子。
在 WorkBuddy 技能内，由 Agent 把自身 LLM（或 cloudbase 免密钥 LLM）注入即可：

```python
from engine.nlu_llm import parse_signals_llm

def llm_call(prompt: str) -> str:
    # 你的 LLM 调用：WorkBuddy Agent 的 LLM，或 cloudbase 免密钥大模型
    return workbuddy_llm_complete(prompt)

signals = parse_signals_llm(user_text, llm_call)   # 返回与规则式一致的 Signals
# 之后照常：build_plan(signals) → recommend_combo(..., model=...) → format_output(...)
```

要点：
- `llm_call(prompt) -> str`：接收完整 prompt（含 `build_nlu_prompt` 的字段说明与 MET 参考），返回 JSON 文本。
- 归一化/回退已在模块内完成：返回结构一定对齐 `Signals`，无 LLM 或解析失败自动回退规则式。
- **缓存**：`parse_signals_llm_cached(text, llm_call, state)` 把抽取结果按文本哈希存入 `state`
  （即 `state/user_profile.json`），相同文本或纯续对话直接复用，不再重复调 LLM。
- CLI `run_dialogue.py` 默认 `--nlu llm`；无真实 API 时用 `--llm-stub` 以规则解析模拟 LLM 输出演示管线，
  生产环境把 stub 替换成上面的 `llm_call` 即可。调试可加 `--no-cache` 强制每次调 LLM。

## 十二、接入真实数据（mcd_mcp 取数 + 可穿戴运动）

### 12.1 菜单取数适配器 `engine/mcp_adapter.py`
真实环境由 Agent 通过 MCP 工具 `mcp__mcd-mcp__list-nutrition-foods`（无入参）取全量菜单。
引擎与"取数通道"解耦：取数被抽象为可注入的 `call_mcp` 回调，未配置 MCP 时回退本地样例。

```python
from engine.mcp_adapter import fetch_nutrition_data, make_stub_call_mcp

# Agent 生产接入：把真实 MCP 调用包成无参函数注入
def call_mcp():
    return mcp__mcd-mcp__list-nutrition-foods()    # 真实返回 {"success":True,"data":"[160]{...}:"}

data, src = fetch_nutrition_data(call_mcp)        # src == "mcp"
items = parse_nutrition(data)
```

- `fetch_nutrition_data(call_mcp=None, fallback_path=None)`：优先用 `call_mcp`，失败/未注入时回退 `fallback_path`。
- `make_stub_call_mcp(path)`：沙箱自测用，读本地样例并按真实返回结构包装；CLI 用 `--mcp-stub` 触发。

### 12.2 运动消耗数据源 `engine/activity_source.py`
默认按 MET 估算（`kcal/min = MET×3.5×体重/200`）。接入可穿戴/健康 App 导出后，
**实测 kcal 优先覆盖 MET 估算**，设备未覆盖的运动类型仍用 MET 补位。

```python
from engine.activity_source import ManualActivitySource, WearableActivitySource, merge_activity

manual = ManualActivitySource(weight_kg).get_session(signals)    # 对话所说运动·MET 估算
wearable = WearableActivitySource("export.json").get_session()  # 手环/App 导出·实测优先
session = merge_activity(manual, wearable)                       # 实测覆盖 + 类型补位
plan = build_plan(signals, exercise_burn_override=session.total_kcal())
```

- `WearableActivitySource` 支持 JSON / CSV 导出，字段兼容 `type/activity/label`、
  `minutes/duration_min`、`kcal/calories/energy`（实测消耗，存在即优先）。
- `merge_activity`：可穿戴有实测 → 采用实测并剔除手动同类型；手动补位未覆盖类型；无可穿戴 → 退回手动。
- 真实数据覆盖时，计划假设自动标注"运动消耗采用可穿戴/健康App实测值（覆盖 MET 估算）"。

### 12.3 CLI 演示
```bash
# 真实取数(模拟) + 可穿戴实测覆盖 MET 估算
python run_dialogue.py --conv examples/conversation_sample.txt \
  --nutrition examples/nutrition_sample.txt --mcp-stub \
  --activity examples/wearable_run.json --llm-stub --top 3
```
效果：午餐预算从 MET 估算 738 kcal → 实测 970 kcal 对应的 911 kcal；计划假设标注"采用可穿戴实测覆盖 MET"。

### 12.4 测试
`tests/test_real_data.py` 覆盖：MCP 取数来源(mcp/fallback)、可穿戴 JSON/CSV 解析、实测覆盖合并、planner 覆盖假设，全部断言通过。

## 十三、两步触发工作流（历史常点 → 询问身体 → 个性化）

用户说"想吃麦当劳"时，skill 按**先熟悉、后精准**的两步走，避免一上来就因缺数据卡住或盲推：

### 13.1 流程
1. **拉历史**：Agent 调用 `mcp__mcd-mcp__order-list` / `query-order` 取该用户过往订单，
   用 `fetch_order_history` 聚合成常点榜 `{name: count}`（见 12.1 的取数解耦模式）。
2. **Phase A · 智能推荐（基于常点）**：把常点榜经 `apply_order_history` 注入偏好模型（正向单品反馈/软偏置），
   在「通用示例计划」或已有身体数据下优先沿用熟悉餐品出推荐；同时**主动询问**身体要求。
3. **Phase B · 个性化推荐**：用户补充身高/体重/目标体重/目标(减脂·增肌·维持)/忌口后，
   计划按真实身体数据重算，历史偏置继续生效 → 既贴合个人指标、又保留口味习惯。

### 13.2 Agent 主动询问模板（Phase A 末尾）
> 你常点的是 X×n、Y×m… 已按此给你做了智能推荐。为了更精准，还差几项：
> **身高、体重、目标体重、目标（减脂/增肌/维持）**，以及忌口/口味偏好？告诉我我重新算。

### 13.3 关键函数与 CLI
- `engine.mcp_adapter.fetch_order_history(call_mcp, fallback_path)` / `aggregate_favorites(orders)`：聚合常点；
  `make_stub_order_history(path)` 沙箱模拟。
- `engine.prefs_model.apply_order_history(model, favorites)`：常点→软偏置（与对话反馈共用 item_feedback，不冲突）。
- CLI：`--history <订单列表JSON>` 模拟 mcp 订单历史；生产把 call_mcp 注入真实 `order-list` 即可。
  ```bash
  # Phase A：仅触发意图 + 历史 → 智能推荐并提示补身体数据
  python run_dialogue.py --text "我中午想吃麦当劳给我推荐一下" \
    --nutrition examples/nutrition_sample.txt --history examples/order_history_sample.json --llm-stub --top 3
  # Phase B：补充身体数据后 → 个性化 + 历史
  python run_dialogue.py --text "身高175 体重70 目标65 减脂 久坐剪辑师 下班跑步一小时 中午吃麦当劳" \
    --nutrition examples/nutrition_sample.txt --history examples/order_history_sample.json --llm-stub --top 3
  ```
- 验证：`tests/test_history.py` 覆盖聚合/取数/偏置注入/排序影响，全部通过。

### 13.4 Agent 生产接入：注入真实 mcd_mcp（取数 + 订单历史）

沙箱用 `--mcp-stub` / `--history` 本地模拟；生产环境由 Agent 把真实 MCP 调用作为 `call_mcp` 闭包注入即可，
引擎与取数通道完全解耦，未配置/超时自动回退本地样例。

```python
from engine import (parse_nutrition, parse_signals_llm, build_plan,
                    init_model, load, save, update_from_signals,
                    recommend_combo, format_output,
                    fetch_nutrition_data, fetch_order_history, apply_order_history,
                    ManualActivitySource, WearableActivitySource, merge_activity)

# —— 真实 mcd_mcp 调用（由 WorkBuddy Agent 注入，无参或按工具约定）——
def call_mcp_nutrition():
    # 全量菜单营养：无入参，返回 {"success":True,"data":"[160]{...}:"}
    return mcp__mcd-mcp__list-nutrition-foods()

def call_mcp_orders():
    # 该用户历史订单：无入参，返回 {"success":True,"data":{"list":[{orderId,orderStatus,orderProductList:[{productName,comboItemList:[{name,quantity}]}]}]}}
    return mcp__mcd-mcp__order-list()

# —— Step1：取菜单 + 拉常点（任一失败都安全回退）——
data, src = fetch_nutrition_data(call_mcp_nutrition)      # src == "mcp"
favorites = fetch_order_history(call_mcp_orders)          # {name: count}，无历史则 {}
items = parse_nutrition(data)

# —— Step2：Phase A 智能推荐（基于常点，先给参考）——
model = init_model()
if favorites:
    apply_order_history(model, favorites)                 # 常点 → 软偏置
signals = parse_signals_llm(user_text, llm_call)          # 或规则 parse_signals
plan = build_plan(signals)                                # 缺身体数据→通用示例(见7.1)
combo = recommend_combo(items, plan, model=model, top_n=3)
print(format_output(None, combo, plan, prefs={})["combos"])
print("你常吃的:", favorites, "；请补充身高/体重/目标体重/目标/忌口")

# —— Step3：用户补充身体数据后 Phase B 个性化重算 ——
signals = parse_signals_llm(user_text_with_body, llm_call)
plan = build_plan(signals)                                # 按真实身体数据算预算/缺口
combo = recommend_combo(items, plan, model=model, top_n=3)  # 历史偏置继续生效
print(format_output(None, combo, plan, prefs={})["combos"])
```

要点：
- `mcp__mcd-mcp__order-list` / `query-order` 返回结构各异，引擎只认"订单列表"；用 `fetch_order_history` 的
  `_extract_orders` 兼容 `orders/data/list/items` 多种键，拿不到时回退本地样例。
- 真实取数通道与降级共用 12.1 的 `fetch_nutrition_data` 模式，Agent 只需替换 `call_mcp` 闭包。
- 若 mcd_mcp 未连接，CLI 直接 `--nutrition` + `--history` 读本地样例即可离线演示整套两步流程。

### 13.5 体验要点
- 历史偏置是**软**的：健身指标不达标时（如减脂预算紧），引擎仍可能优先高蛋白组合而非纯照搬常点，
  但常点餐品（如你常喝的无糖可乐、常吃的巨无霸）会显著上浮排序——既智能又健康。
- 历史随 `state/user_prefs.json` 持久化，配合对话反馈持续学习，越用越懂你。
