# 对话式麦当劳健身餐推荐系统 · 设计与持续学习算法

> 在原有「结构化输入」skill 基础上，扩展为**日常对话驱动 + 持续学习**的系统。
> 代码见 `run_dialogue.py` 与 `engine/{nlu,planner,prefs_model}.py`。

---

## 一、系统架构

```
用户日常对话文本
   │
   ▼ engine/nlu.parse_signals         —— 规则式 NLU：抽身体/运动/目标/场景/口味/忌口
   ▼ engine/planner.build_plan        —— BMR + 运动MET消耗 + 目标体重缺口 → 该餐预算
   ▼ engine/prefs_model(load+update)  —— 持续学习：更新偏好模型(计数+衰减)
   ▼ engine/recommender(+model偏置)   —— 套餐组合搜索，叠加偏好软偏置、硬忌口过滤
   ▼ engine/formatter                 —— 结构化输出
   ▼ run_dialogue 展示                  —— 推荐清单 + 估算热量 + 理由 + 模型更新说明
        │
        └──► state/user_profile.json  身体档案(跨轮记忆)
        └──► state/user_prefs.json    偏好模型(持久化)
```

---

## 二、输入格式（日常对话示例）

```
身高175cm、体重70kg、目标体重65kg、职业剪辑师、久坐时间长、
下班后跑步一小时、午餐吃麦当劳
```
NLU 从自由文本抽取：`height_cm=175, weight_kg=70, target_weight_kg=65,
base_activity=sedentary(剪辑/久坐), exercises=[{跑步,60min,MET7}], meal_occasion=lunch`。

---

## 三、计划层：身体数据 + 运动消耗 + 减重目标

1. **BMR**（Mifflin-St Jeor）：`10·kg + 6.25·cm − 5·age ± 5`。
2. **TDEE** = `BMR × 职业活动系数` + `Σ(运动MET × 3.5 × kg / 200 × 分钟)`。
   - 跑步 1h(70kg, MET7) ≈ **514 kcal**。
   - 职业久坐 → 活动系数 1.2；若对话未重提职业，沿用已记忆值（跨轮）。
3. **减重缺口**：目标体重 < 当前时，按 **0.5 kg/周** 安全速率换算每日缺口
   `= 0.5 × 7700 / 7 ≈ 550 kcal`，并**封顶 TDEE 的 25%** 防过低。
4. **该餐预算** = `(TDEE − 每日缺口) × 用餐场景占比`（午餐 0.38）。
   - 例：TDEE 2493 → 目标 1943 → 午餐 ≈ **738 kcal / 蛋白 53 g**，预计 10 周达标。

> 运动消耗用 **MET 表**（跑步7/游泳6/骑车6/瑜伽2.5…）估算，规则式可替换为可穿戴设备数据。

---

## 四、推荐逻辑（复用 + 偏好偏置）

- 复用 `recommender.recommend_combo`：在每餐预算 70%~115% 内搜 (主+副+饮)，
  综合分 = 热量贴合×0.5 + 蛋白覆盖×0.5 − 钠惩罚。
- **偏好偏置（软）**：`score += bias_for_item(item, model)`，口味/单品反馈净偏好加权。
- **硬忌口（硬）**：模型中的 `taboo` 展开为菜单实际子串（如「牛肉」→ 牛/安格斯/霸），
  命中即剔除；「素」→ 触发素食过滤。

---

## 五、持续学习算法（核心）

### 5.1 模型结构（`state/user_prefs.json`）
```json
{
  "version": 1,
  "conversation_count": 2,
  "updated_at": "2026-10-10 11:22",
  "taste":   { "辣": {"like":0,"dislike":1}, "清淡": {"like":1,"dislike":0} },
  "taboo":   ["牛肉"],
  "scene":   { "午餐": 2 },
  "item_feedback": { "巨无霸": {"accept":1,"reject":0} }
}
```

### 5.2 每轮更新规则（`prefs_model.update_from_signals`）
1. **衰减（遗忘）**：更新前对所有计数 ×**0.97**，使久远偏好缓慢淡出，适应口味变化。
2. **增量累加**：
   - 口味：对话中「喜欢X/想吃清淡」→ `taste[X].like +=1`；「讨厌吃辣/不吃辣」→ `dislike +=1`。
   - 忌口：「别给我牛肉/不吃X/过敏X」→ 加入 `taboo`（硬，不衰减）。
   - 场景：「午餐/健身后」→ `scene` 计数 +1（可据此调场景占比）。
   - 单品反馈：对话提及某餐品且带正向词(喜欢/不错/好吃)或负向词(难吃/不想吃)
     → `item_feedback[名].accept/reject +=1`。
3. **持久化**：写回 `state/user_prefs.json`，下一轮直接载入继续学习。

### 5.3 偏置如何反哺推荐
- **软偏置**：`bias = Σ(口味净偏好 × 权重) + Σ(单品 accept−reject × 权重)`，
  叠加进排序分（仅微调，不一刀切）。
- **硬过滤**：`taboo` 展开子串进入 `exclude_keywords`，强制剔除。
- 效果示例（第二轮对话后）：推荐列表已**不再出现任何牛肉类**（巨无霸/安格斯），
  且向「清淡」类（玉米杯/沙拉）倾斜。

### 5.4 为什么这样设计
- **可解释**：所有偏好是计数，用户/开发者都能看懂「为何这样推」。
- **可遗忘**：指数衰减避免几年前口味永久绑架推荐。
- **冷启动友好**：首轮无偏好时退化为纯营养目标推荐。
- **可替换**：NLU（规则→LLM）、运动数据源（MET→手环）均可独立升级，接口不变。

---

## 六、输出格式

每条回复包含四块：
1. **身体·运动·目标计划**：BMR / 运动消耗 / TDEE / 每日缺口 / 该餐预算 / 预计达标周数 / 假设。
2. **推荐餐品清单**：组合项 + 估算热量(钠/蛋白/脂肪/碳水) + **推荐理由**（热量贴合度、蛋白覆盖、钠提醒）。
3. **偏好模型如何基于本轮对话更新**：本轮提取的信号、计数变更、当前生效的软偏置与硬忌口。
4. （隐含）下一轮将以上述模型为起点继续增量更新。

---

## 七、模块结构与职责（含新增）

| 模块 | 职责 |
|---|---|
| engine/nlu.py | 规则式 NLU（作为 LLM 失败时的兜底） |
| engine/nlu_llm.py | **LLM 主路径 NLU**：结构化 JSON Schema Prompt + 抽取 + 归一化，失败自动回退规则式；`llm_call` 可注入（生产由 WorkBuddy/cloudbase 免密钥 LLM 注入） |
| engine/planner.py | Signals → 该餐热量/蛋白预算（含运动与减重） |
| engine/prefs_model.py | 偏好模型：load/save/update(衰减+累加)/硬忌口展开/软偏置 |
| engine/recommender.py | 套餐搜索，接入 model 偏置与硬忌口（扩展） |
| engine/menu_parser.py / profile.py / formatter.py | 原模块，保持不变 |
| run_dialogue.py | 编排：对话→计划→学模型→推荐→解释更新；持久化身体档案与偏好 |

---

## 八、运行

```bash
# 默认走 LLM NLU（无真实 API 时用 --llm-stub 演示管线）
python run_dialogue.py --conv examples/conversation_sample.txt --nutrition examples/nutrition_sample.txt --reset --llm-stub --top 3
# 第二轮（学习：忌辣/清淡/不吃牛，身体数据自动沿用）
python run_dialogue.py --conv examples/conversation_2.txt --nutrition examples/nutrition_sample.txt --llm-stub --top 3
# 强制规则式兜底
python run_dialogue.py --conv examples/conversation_sample.txt --nutrition examples/nutrition_sample.txt --nlu rule --top 3
# 单测
python tests/test_nlu_llm.py
```
重置模型与档案加 `--reset`。

## 十一、LLM NLU 升级说明（鲁棒性）
- **主路径 LLM**：`engine/nlu_llm.parse_signals_llm(text, llm_call)` 把对话 + 结构化 JSON Schema 交给 LLM，
  `build_nlu_prompt` 内置字段说明与 MET 参考，能正确换算中文数词（一小时→60min）、隐含减脂意图等。
- **归一化**：`_normalize` 把 LLM 输出对齐到与规则式完全一致的 `Signals` 结构（口味归一到规范集、活动等级中英映射、运动 MET/分钟校验），下游零改动。
- **回退策略**：`llm_call=None` 或 LLM 抛错/返回不可用 → 自动回退 `parse_signals` 规则式，系统不崩。
- **生产接入**：在 WorkBuddy 技能中，由 Agent 把自身 LLM 作为 `llm_call` 注入（或调用 cloudbase 免密钥 LLM），
  即可处理自由、口语化、含错别字/反讽的日常对话，显著提升鲁棒性。
- **已验证**：`tests/test_nlu_llm.py` 覆盖正常/第二轮/ messy 中文（一米八、九十公斤、撸铁40分、早饭）/ 无 LLM 回退 四类场景，全部通过。

---

## 十二、接入真实数据（mcd_mcp 取数 + 可穿戴运动消耗）

### 12.1 菜单取数解耦（`engine/mcp_adapter.py`）
真实环境由 Agent 注入 `mcp__mcd-mcp__list-nutrition-foods` 调用（无入参），返回 `{"success":True,"data":"[160]{...}:"}`。
`fetch_nutrition_data(call_mcp, fallback_path)` 把"如何拿 data"抽象成可注入回调：注入即走 MCP，否则回退本地样例。
CLI 用 `--mcp-stub` 读取本地样例并包装成真实返回结构，模拟 MCP 通道；生产把 stub 换成真实 `call_mcp` 即可。

### 12.2 运动实测覆盖 MET（`engine/activity_source.py`）
- `ManualActivitySource`：从对话信号用 MET 估算消耗（复用 `_EXERCISE_MET`）。
- `WearableActivitySource`：读 JSON/CSV 导出，优先采用设备**实测 kcal**。
- `merge_activity`：实测优先覆盖手动同类型、手动补位设备未覆盖类型；无可穿戴则退回手动。
- `build_plan(sig, exercise_burn_override=...)`：传入实测合计即覆盖 MET 估算，并标注"采用可穿戴实测"假设。
- 实测示例（跑步60min 实测620 + 游泳30min 实测350 = 970）相较 MET 估算 514，使午餐预算由 738 → 911 kcal，更贴合真实消耗。

### 12.3 验证
`tests/test_real_data.py`：MCP 取数来源、可穿戴 JSON/CSV、实测合并、planner 覆盖假设，全部通过。

---

## 十三、两步触发工作流（历史常点 → 询问身体 → 个性化）

### 13.1 流程
1. **拉历史**：用户说"想吃麦当劳"时，Agent 调用 `mcp__mcd-mcp__order-list`/`query-order` 取过往订单，
   `fetch_order_history` 聚合成常点榜 `{name:count}`。
2. **Phase A 智能推荐**：`apply_order_history(model, favorites)` 把常点作为正向单品反馈注入（软偏置），
   优先沿用熟悉餐品出推荐；同时**主动询问**身高/体重/目标/忌口等身体要求。
3. **Phase B 个性化**：用户补身体数据后，计划按真实指标重算，历史偏置继续生效 → 精准且保留口味习惯。

### 13.2 软偏置不覆盖健康底线
历史偏置权重（`W_ITEM_ACCEPT`）有限，减脂预算紧时引擎仍优先高蛋白/低热量组合；
但常点餐品（无糖可乐、巨无霸等）会显著上浮排序，做到"智能又健康"。

### 13.3 验证
`tests/test_history.py`：聚合、取数回退、偏置注入、熟悉餐品进入 top 组合，全部通过。

---

## 九、已知限制
- NLU 为规则式，复杂句式/反讽/隐含偏好需 LLM 增强（已提供 `nlu_llm` 主路径与回退）。
- 运动默认按 MET 估算；已支持接入可穿戴/健康App **实测 kcal**（`--activity`）覆盖，但手环实时流推送未做。
- 「蜜汁快乐」等无肉字样禽类可能漏过滤（best-effort 关键词）。
- 偏好仅来自显式对话信号，未利用点击/下单隐式反馈（可扩展）。
- 身体数据默认男性/30 岁（缺失时），建议对话中补全以提精度。
