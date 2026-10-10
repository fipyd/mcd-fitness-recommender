# 麦当劳健身餐个性化推荐 Skill（mcd-fitness-recommender）

> 麦当劳程序员节创意开发大赛参赛作品 · 基于麦当劳 MCP（mcd-mcp）能力开发

## 一、项目简介

本 Skill 面向**健身人群**，把「健身控卡」与「麦当劳便利」结合起来：基于麦当劳 MCP 提供的**全量菜单营养数据**与**用户历史订单**，结合用户的身体数据、训练目标（减脂 / 增肌 / 维持）和饮食偏好，输出**可解释的个性化麦当劳餐品推荐**（单品 + 套餐组合），并附热量、蛋白质、脂肪、碳水、钠的构成与适配理由。

核心亮点：
- **两步触发工作流**：用户说"想吃麦当劳"时，先拉历史常点做智能推荐，再主动询问身体要求，拿到后个性化重算——避免一上来因缺数据盲推或卡住。
- **目标宏量计算**：Mifflin-St Jeor 算 BMR + 运动消耗（MET 估算，可接入可穿戴实测覆盖）+ 安全减重缺口（0.5kg/周，封顶 TDEE 25%）。
- **偏好持续学习**：计数式偏好模型 + 指数衰减（每轮 ×0.97 缓慢遗忘），硬忌口强制过滤、软偏置微调排序，跨轮对话增量更新。
- **历史常点智能推荐**：常点餐品作为正向偏置注入，优先沿用熟悉口味，同时不违背健身指标硬约束。

## 二、目标用户

- 有减脂 / 增肌 / 维持体重需求，且常吃麦当劳的用户；
- 关注热量、蛋白质摄入，希望在点麦当劳时也能"吃得明白"的健身人群；
- 想用最少决策成本获得"相对健康"麦当劳搭配的人。

## 三、安装方法

### 前置条件
1. 申请麦当劳中国 MCP Token（见 [麦当劳 MCP Server 使用指南](https://github.com/M-China/mcd-mcp-server)）。
2. 在 WorkBuddy 左侧【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置 MCP】，填入：
   ```json
   {
     "mcpServers": {
       "mcd-mcp": {
         "type": "streamablehttp",
         "url": "https://mcp.mcd.cn",
         "headers": { "Authorization": "Bearer YOUR_MCP_TOKEN" }
       }
     }
   }
   ```
   保存并启用 `mcd-mcp`。

### 安装 Skill
将本仓库整体放入 WorkBuddy 的 skills 目录（文件夹名保持 `mcd-fitness-recommender`）：
```
~/.workbuddy/skills/mcd-fitness-recommender/
```
重启 WorkBuddy 或在技能管理页刷新后，即可通过触发词调用：
**健身麦当劳 / 麦当劳增肌 / 减脂吃什么麦当劳 / 麦当劳蛋白 / 健身餐推荐**

> 未配置 mcd-mcp 时，Skill 自动回退本地样例数据，可离线演示完整流程。

## 四、使用示例

**Phase A（仅说想吃，缺身体数据）：**
```
用户：我中午想吃麦当劳给我推荐一下
→ 基于你常点餐品做智能推荐，并提示补充：身高、体重、目标体重、目标、忌口/口味
```

**Phase B（补充身体要求后个性化）：**
```
用户：身高175 体重82 目标72 减脂 午餐吃麦当劳 忌口不要辣
→ 输出个性化套餐组合 + 营养构成 + 适配理由，并应用硬忌口"不要辣"
```

**命令行演示（需 Python 3.10+）：**
```bash
# 两步触发：Phase A + Phase B
python run_dialogue.py --text "我中午想吃麦当劳给我推荐一下" \
  --nutrition examples/nutrition_sample.txt --history examples/order_history_real.json --llm-stub --top 3
python run_dialogue.py --text "身高175 体重82 目标72 减脂 午餐吃麦当劳 忌口不要辣" \
  --nutrition examples/nutrition_sample.txt --history examples/order_history_real.json --llm-stub --top 3
```

## 五、目录结构

```
mcd-fitness-recommender/
├── README.md                 # 本文件（项目介绍/安装/示例/目标用户）
├── CONTEST_DECLARATION.md    # 参赛声明（官方原文，不可修改）
├── MCP_INTEGRATION.md        # mcd-mcp 接入说明（Server/Tool/调用流程/业务价值）
├── SKILL.md                  # Skill 定义与完整能力说明
├── DIALOGUE_SYSTEM.md        # 对话式系统设计与持续学习算法说明
├── run.py                    # 单轮推荐入口
├── run_dialogue.py           # 对话式编排入口（含两步触发与持续学习）
├── engine/                   # 核心引擎
│   ├── mcp_adapter.py        # mcd_mcp 取数适配器（菜单 + 订单历史）
│   ├── menu_parser.py        # 营养数据解析与餐品分类
│   ├── nlu.py / nlu_llm.py   # 中文 NLU（规则 + LLM 主路径）
│   ├── planner.py            # 目标宏量计算
│   ├── prefs_model.py        # 偏好持续学习模型
│   ├── recommender.py        # 过滤/打分/组合推荐
│   ├── activity_source.py    # 运动消耗（MET + 可穿戴实测）
│   └── ...
├── examples/                 # 样例数据（营养/对话/真实订单结构/可穿戴）
└── tests/                    # 三套测试（历史/真实数据/NLU）
```

## 六、验证

仓库内置三套测试，全部通过即可确认功能正常：
```bash
python tests/test_history.py      # 历史常点聚合/取数/偏置/排序影响（含真实 order-list 结构）
python tests/test_real_data.py    # mcd_mcp 取数来源/可穿戴实测覆盖
python tests/test_nlu_llm.py      # NLU 解析（正常/口语/回退）
```

## 七、免责声明

本项目为大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。推荐结果仅供参考，不构成医疗、营养或专业建议；餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准。

## 八、许可证

本项目以参赛作品形式提交，遵循大赛相关规则与声明（见 CONTEST_DECLARATION.md）。
