# WorkBuddy 开发上下文（workbuddy.md）

> 本文件用于核验本 Skill 是否符合「麦当劳程序员节创意开发大赛」WorkBuddy 联动奖励条件。
> 本 Skill 全程使用 **WorkBuddy** 作为开发环境完成构思、编码、调试与打包。

## 开发环境

- **工具**：WorkBuddy（官方合作伙伴）
- **连接器**：自定义连接器 `mcd-mcp`（streamablehttp，接入 `https://mcp.mcd.cn`，Bearer Token 鉴权）
- **开发方式**：在 WorkBuddy 对话框中描述需求，由 AI 助手迭代生成并运行 Python 引擎代码，逐步验证

## 开发流程（对话式迭代）

1. **需求构思**：明确"健身人群在麦当劳点餐的个性化推荐"场景，定义目标宏量计算、推荐、偏好学习等能力。
2. **MCP 联调**：通过 WorkBuddy 调用真实 `mcp__mcd-mcp__list-nutrition-foods`（160 条营养数据）与 `mcp__mcd-mcp__order-list`（5 单历史，含套餐子项与取消单），发现并修复了真实订单结构解析 bug（跳过已取消订单、展开套餐子项）。
3. **能力实现**：实现 `engine/` 下的 NLU、planner、prefs_model（持续学习）、recommender、mcp_adapter、activity_source 等模块。
4. **两步触发**：实现"先按常点智能推荐 → 主动询问身体要求 → 个性化重算"的工作流。
5. **测试验证**：落地三套测试（test_history / test_real_data / test_nlu_llm），全部通过。
6. **打包安装**：通过 WorkBuddy 将 Skill 同步安装到 `~/.workbuddy/skills/`，并打包到本地目录用于提交。

## 关键产物

- 可运行 Skill：`SKILL.md` + `engine/`（11 个模块）+ `examples/` + `tests/`
- 真实数据验证：菜单取数、订单历史聚合、偏好偏置注入均经真实 MCP 返回结构验证
- 三套测试全绿，确认功能与取数链路稳定

## 联动奖励符合性

- ✅ 使用 WorkBuddy 官方工具开发
- ✅ 接入并实际调用麦当劳 MCP（mcd-mcp）能力
- ✅ 产出可运行的 Skill 项目，含 README / CONTEST_DECLARATION / MCP_INTEGRATION 等赛事要求文件
