# MCP 接入说明（MCP_INTEGRATION.md）

本文件说明本 Skill 实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值，供赛事核验。

## 一、使用的麦当劳 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 协议类型 | `streamablehttp` |
| 服务地址 | `https://mcp.mcd.cn` |
| 鉴权方式 | `Authorization: Bearer <TOKEN>`（Token 通过环境变量占位，不硬编码，符合信息安全声明） |
| 配置方式 | WorkBuddy【自定义连接器】→【配置 MCP】手动填入 JSON（见 README 安装方法） |

## 二、实际调用的 Tool

### 1. `mcp__mcd-mcp__list-nutrition-foods`（无入参）
- **作用**：获取麦当劳全量菜单营养数据。
- **返回结构**：`{"success": true, "code": 200, "message": "请求成功", "data": "<字符串>"}`
  - `data` 为字符串，格式为 `[N]{productName,能量,蛋白质,脂肪,碳水化合物,钠,...}:\n` 后接 CSV（实测约 160 条餐品）。
  - 字段含：`productName`（餐品名）、`能量(kcal)`、`蛋白质(g)`、`脂肪(g)`、`碳水化合物(g)`、`钠(mg)` 等。
- **代码位置**：由 `engine/mcp_adapter.fetch_nutrition_data(call_mcp)` 注入真实调用取数；未配置/超时自动回退本地样例（`--nutrition`）。

### 2. `mcp__mcd-mcp__order-list`（无入参）
- **作用**：获取当前用户的历史订单，用于"基于常点餐品的智能推荐"。
- **返回结构**：`{"success": true, "code": 200, "data": {"list": [订单, ...]}}`
  - 订单含 `orderId`、`storeName`、`orderStatus`、`orderProductList[]`。
  - `orderProductList[].comboItemList` 为套餐子项（`{name, quantity}`）；单品直接用 `productName`。
  - `orderStatus` 含 `订单已完成` / `订单已取消` 等状态。
- **代码位置**：由 `engine/mcp_adapter.fetch_order_history(call_mcp)` 注入；适配器自动识别 `{data:{list:[...]}}` 结构、**跳过已取消订单**、**展开套餐子项**后聚合为常点榜 `{name: count}`。

## 三、调用流程

```
用户说"想吃麦当劳"
   │
   ├─[1] 取菜单：Agent 注入 call_mcp → mcp__mcd-mcp__list-nutrition-foods
   │        → fetch_nutrition_data() → parse_nutrition() 解析为结构化餐品
   │
   ├─[2] 拉历史：Agent 注入 call_mcp → mcp__mcd-mcp__order-list
   │        → fetch_order_history() 聚合成常点榜 {name:count}
   │        → apply_order_history() 注入偏好模型（正向软偏置）
   │
   ├─[3] Phase A 智能推荐：基于常点 + 通用/已有身体数据出推荐
   │        → 主动询问身体要求（身高/体重/目标/忌口）
   │
   └─[4] Phase B 个性化：用户补充身体数据
            → build_plan() 按真实指标算每餐预算
            → recommend_combo() 在预算内搜索(主+副+饮)组合
            → format_output() 输出餐品 + 营养构成 + 适配理由
```

> 引擎与取数通道解耦：取数被抽象为可注入的 `call_mcp` 回调，生产环境注入真实 MCP 调用，沙箱/离线时回退本地样例，无需修改推荐逻辑。

详见 `SKILL.md` 第十二、十三节与 `engine/mcp_adapter.py`。

## 四、业务价值

1. **降低决策成本**：健身人群在麦当劳点餐时常陷入"想吃又怕胖"的纠结，本 Skill 用真实菜单营养 + 个人订单习惯，秒级给出贴合热量/蛋白目标的搭配。
2. **可解释而非黑盒**：每条推荐都附"热量贴合度、蛋白覆盖率、钠提示"，用户知道为什么这么推荐。
3. **兼顾习惯与指标**：历史常点作为软偏置，优先沿用熟悉口味；但当健身指标不达标（如减脂预算紧）时，引擎仍优先高蛋白/低糖组合，不盲从常点。
4. **真实数据驱动**：直接消费麦当劳官方 MCP 能力（菜单营养 + 订单历史），输出随官方数据实时更新，无需维护静态菜单表。

## 五、安全与合规

- 所有 MCP 调用通过 WorkBuddy 连接器鉴权，**不存储、不硬编码任何 Token/密钥**，配置文件仅使用环境变量占位符。
- 订单历史仅用于本地偏好偏置计算，不对外发送用户个人信息。
- 推荐结果标注"仅供参考，不构成专业建议"，餐品/价格以官方实时结果为准。
