# RajWin / RajLuck 远端接口与指标基线

> 文档状态：联调基线 v0.1
>
> 来源：当前复审系统已实现的远端请求代码
>
> 业务确认：RajWin、RajLuck 运行同一套后台系统，接口路径、请求参数、响应结构和
> 页面一致。双源契约探测用于检查部署版本、权限和运行状态，不再为两个来源设计
> 不同接口实现。

## 1. 接入原则

- 内置 `source_id` 为 `rajwin`、`rajluck`，管理员可新增使用相同接口契约的来源；
- 各来源独立 base URL、凭据、Token、刷新锁、限流、游标和字典；
- 仅调用登记的只读接口；
- 不直接复用当前审核系统的全局配置和 Token 文件；
- 远端响应先保存原始层，再按版本化 Normalizer 标准化；
- 两个来源共用接口 Schema；仍保存来源探测结果，以发现部署版本或权限异常；
- 任何登录和业务请求日志都必须脱敏。

## 2. 当前已验证的认证模式

### 2.1 登录

```text
POST /api/system/login
```

请求语义：

```json
{
  "username": "<secret>",
  "password": "<secret>",
  "code": "<current-totp>"
}
```

登录响应中的 JWT 可能位于 `token`、`jwt`、`access_token`、`accessToken`
或嵌套对象中。实现应提取并标准化为裸 Token，发起业务请求时使用：

```text
Authorization: Bearer <token>
```

### 2.2 Token 探测

当前系统使用一个小页提现列表请求验证 Token：

```text
POST /api/operate/withdrawOrder/index
page=1, pageSize=1
```

新系统可保留该模式，也可以在联调时寻找更轻量且权限更低的只读探测接口。
来源或账号角色缺失时必须直接失败，不能回退到默认 RajWin 地址或 primary 账号。

### 2.3 认证失败

至少将以下状态归类为认证失败：

```text
401, 403, 419, 440
```

某些后台可能返回 HTTP 200，但 JSON 中 `success=false`，或跳转到 HTML 登录页。
Connector 需要同时识别 HTTP 状态、JSON 业务失败和登录页响应。

### 2.4 刷新规则

- 先复用未过期 Token；
- JWT 有 `exp` 时提前 60–120 秒视为过期；
- 认证失败后刷新一次并重试原请求一次；
- 同来源同账号使用单飞锁；
- 仍失败则停止该任务并告警；
- 不进行无限登录或无限重试。

## 3. P0 统计接口

这些接口最适合构成分析 MVP。

| endpoint_key | 方法 | 远端路径 | 主要参数 | 目标数据 |
|---|---|---|---|---|
| `daily_summary_channel` | POST | `/api/stat/dailySummaryChannel/index` | `create_time`, `channel`, `page`, `pageSize` | 日期/渠道经营汇总 |
| `daily_summary_channel_options` | GET | `/api/stat/dailySummaryChannel/channel` | 无 | 渠道字典 |
| `payment_channel_daily` | GET | `/api/stat/chargeChannelDailyLog/index` | `date[0/1]`, `channel`, `channel_type`, `tabValue`, 分页 | 支付渠道日报 |
| `first_pay_analysis` | POST | `/api/stat/firstPayAnalysisLog/index` | `date`, `channel`, 分页 | 首充与复充 |
| `first_pay_analysis_options` | GET | `/api/stat/firstPayAnalysisLog/channel` | 无 | 首充渠道字典 |
| `first_pay_ltv` | POST | `/api/stat/userPayLtvLog/index` | `date`, `channel`, 分页 | 首充 Cohort LTV |
| `first_pay_ltv_options` | GET | `/api/stat/userPayLtvLog/channel` | 无 | LTV 渠道字典 |
| `user_retention` | POST | `/api/stat/userRetentionLog/index` | `date`, `channel`, `type`, 分页 | 用户留存 |
| `user_retention_options` | GET | `/api/stat/userPayLtvLog/channel` | 无 | 留存渠道字典 |

待确认：

- 两个运行环境当前部署版本是否一致；
- `date` 与 `create_time` 的时区和边界；
- `channel=["-"]` 是否代表全渠道汇总；
- `type=1`、`type=4` 等留存类型的正式含义；
- 返回数据是否包含特殊合计行；
- 历史最大跨度；
- 页面大小上限和并发限制。

## 4. P0/P1 交易与用户接口

充值/提现订单列表和汇总已提升为首批 P0，用于代收、代付遗漏比对；用户和风控明细
仍为 P1，且不应被遗漏比对模块采集。

| endpoint_key | 方法 | 远端路径 | 用途 |
|---|---|---|---|
| `withdraw_order_list` | POST | `/api/operate/withdrawOrder/index` | 提现订单 |
| `withdraw_order_summary` | POST | `/api/operate/withdrawOrder/summary` | 提现汇总 |
| `charge_order_list` | GET | `/api/operate/chargeOrder/index` | 充值订单 |
| `charge_order_summary` | GET | `/api/operate/chargeOrder/summary` | 充值汇总 |
| `player_info` | GET | `/api/operate/playerInfoList/index` | 用户信息 |
| `player_risk_control` | GET | `/api/operate/playerInfoList/riskControl` | 风控关联信息 |
| `player_labels` | GET | `/api/operate/playerInfoList/getLabel` | 用户标签 |
| `player_value` | GET | `/api/operate/playerInfoList/getUserValue` | 用户价值 |
| `agent_lower_info` | GET | `/api/operate/agentLowerInfo/index` | 代理下级信息 |

提现接口可能返回银行卡、姓名、手机号和 IP 等大量 PII。遗漏比对只允许提取订单号、
金额、状态、渠道和必要时间字段，不保存完整 `info` 对象。其他 P1 用户接口正式接入前
必须逐字段批准采集范围，并验证是否存在可靠的增量时间字段。
参考同步逻辑显示部分充值查询窗口最多约 30 天；联调时应重新测量，并由窗口切片器自动拆分。

## 5. P1/P2 行为与游戏接口

| endpoint_key | 方法 | 远端路径 | 用途 |
|---|---|---|---|
| `asset_log` | GET | `/api/operate/assetLog/index` | 资产变动 |
| `game_circle` | GET | `/api/operate/gameCircle/index` | 牌局/游戏结算 |
| `game_asset_detail` | GET | `/api/stat/gameAssetDetail/index` | 游戏投注聚合 |
| `game_vendor_list` | GET | `/api/game/vendor/list` | 游戏厂商字典 |
| `game_info_list` | GET | `/api/game/info/list` | 游戏字典 |

Excel 导出相关接口不建议作为核心采集通道。优先使用分页 JSON 接口，以便检查、重试和幂等落库。

## 6. 字典接口

| 字典 | 方法与路径 |
|---|---|
| 通用数据字典 | `GET /api/system/dataDict/list?code=...` |
| 充值渠道 | `GET /api/operate/chargeOrder/channel` |
| 充值支付通道 | `GET /api/operate/chargeOrder/payChannel` |
| 提现渠道 | `GET /api/operate/withdrawOrder/channelList` |
| 提现支付通道 | `GET /api/operate/withdrawOrder/payChannel` |
| 用户画像标签 | `POST /api/common/profileTag/remote` |

当前已使用的通用字典 code 包括：

```text
game_access_id
withdraw_status
country_list
pay_channel
channel_type
asset_change
```

字典必须按来源保存。即使显示名相同，也不能默认 RajWin 与 RajLuck 的 code 相同。
比对任务启动前，用户从当前来源和代收/代付业务类型的字典中选择渠道。批次保存代码、
名称和字典版本快照，避免字典后续变化影响历史结果。

## 7. 明确禁止的远端操作

MVP 端点 Allowlist 不得包含：

- 提现订单锁定或解锁；
- 提现审核、审批或状态变更；
- 远端订单刷新；
- 用户标签、备注、余额、资产修改；
- 新增充值或补单；
- 任意导入、删除和配置修改；
- 任意由前端传入的 URL 或 path。

建议在 Connector 注册端点时要求 `read_only=true`，并在代码审查和测试中验证。

## 8. 请求和分页规范

### 8.1 分页

当前参考客户端将远端 `pageSize` 限制为最大 100。新系统在联调确认前沿用此上限：

```text
page >= 1
1 <= pageSize <= 100
```

本地分析 API 的 `page_size` 可以更大，但它查询的是本地数据库，不能直接透传给远端。

### 8.2 日期窗口

远端存在多种日期参数形状：

```text
date: ["YYYY-MM-DD", "YYYY-MM-DD"]
create_time: ["...", "..."]
date[0], date[1]
create_time[0], create_time[1]
update_time
```

端点注册表应声明 `window_encoder`，由 Connector 统一编码，业务层不得自行拼装。

### 8.3 响应包络

常见响应形状为：

```json
{
  "success": true,
  "data": {
    "items": [],
    "pageInfo": {
      "total": 0,
      "currentPage": 1,
      "totalPage": 1
    }
  }
}
```

但字典、汇总和错误响应可能不同。Normalizer 必须按 `endpoint_key + source_id + version`
显式解析，不应对所有接口使用一个宽松的 `.get()` 链后静默返回空列表。
现有接口代码中还出现 `items`、`list`、`rows`、`records` 等不同集合字段，
契约层应把它们显式登记为版本化响应形状，而不是无告警地逐个猜测。

## 9. 错误分类

| error_class | 处理 |
|---|---|
| `auth_failed` | 单次刷新；仍失败则暂停来源任务并告警。 |
| `rate_limited` | 尊重 Retry-After，退避后重试。 |
| `upstream_5xx` | 有限重试；超限进入熔断。 |
| `transport_error` | 重建连接并有限重试。 |
| `invalid_request` | 不重试，标记代码/配置错误。 |
| `business_rejected` | 保存脱敏消息，人工确认。 |
| `schema_changed` | 原始层保留，标准化隔离，立即告警。 |
| `pagination_inconsistent` | 标记部分成功，从安全检查点重跑。 |
| `data_quality_failed` | 数据可进入隔离区，不发布到 Gold。 |

自动重试只适用于端点注册表中明确声明的幂等读取操作。远端业务写操作即使返回
5xx 或发生网络中断也不得自动重放，因为上游可能已经执行成功。

## 10. 初始指标字典

以下字段映射来源于当前系统的整合页面，只能作为联调基线。

| 指标键 | 展示名 | 远端来源/字段 | 初始公式 | 汇总规则 |
|---|---|---|---|---|
| `register_users` | 注册人数 | 日渠道汇总 `register` | 远端值 | 求和 |
| `new_paying_users` | 新增付费人数 | 日渠道汇总 `new_charge_user` | 远端值 | 求和 |
| `new_charge_amount` | 新增充值金额 | 日渠道汇总 `new_charge` | 远端值 | 求和 |
| `new_surplus_rate` | 新增盈余率 | 日渠道汇总 `new_charge_withdraw_diff_rate` | 远端口径，待确认 | 按业务基数加权 |
| `new_arppu` | 新增 ARPPU | 日渠道汇总 `new_arppu` | 远端口径，待确认 | 按新增付费人数加权 |
| `marketing_spend` | 广告消耗 | 本地人工数据 | 人工录入 | 求和 |
| `registration_cost` | 注册成本 | 本地计算 | `spend / register_users` | 先汇总分子分母再相除 |
| `paying_cost` | 付费成本 | 本地计算 | `spend / new_paying_users` | 先汇总分子分母再相除 |
| `ltv_d0` | 当日 LTV | 首充 LTV `ltv1` | 远端口径，待确认 | 以 `user_pay` 加权 |
| `ltv_d7` | 7 日 LTV | 首充 LTV `ltv7` | 远端口径，待确认 | 以 `user_pay` 加权 |
| `repurchase_d1_rate` | 次日复充率 | 首充分析 `day2` | 远端口径，待确认 | 以 `day1` 基数加权 |
| `retention_d1_rate` | 次日留存 | 留存 `day2` | 远端口径，待确认 | 以 `day1` 基数加权 |
| `retention_d3_rate` | 3 日留存 | 留存 `day3` | 远端口径，待确认 | 以 `day1` 基数加权 |
| `retention_d7_rate` | 7 日留存 | 留存 `day7` | 远端口径，待确认 | 以 `day1` 基数加权 |
| `retention_d30_rate` | 30 日留存 | 留存 `day30` | 远端口径，待确认 | 以 `day1` 基数加权 |

### 10.1 指标定义最低要求

每个正式指标必须记录：

```text
metric_key
display_name
business_definition
numerator
denominator
source_dataset
source_fields
status_filter
business_timezone
currency
aggregation_rule
owner
version
effective_from
```

### 10.2 汇总禁忌

- 不对比率直接算术平均；
- 不在币种不同或未知时合计金额；
- 不跨来源合并 UID 或订单号；
- 不把远端汇总值和本地重算值静默覆盖；
- 不根据字段名猜测 GGR、利润、LTV 的正式含义；
- 不把页面标题里的目标值或阈值当作指标公式。

## 11. 双源运行验证矩阵模板

联调完成后维护以下矩阵：

| endpoint_key | RajWin 可用 | RajLuck 可用 | 共用契约版本 | 权限一致 | 最大历史 | 备注 |
|---|---:|---:|---:|---:|---:|---:|---|
| `daily_summary_channel` | 待探测 | 待探测 | 待记录 | 待验证 | 待验证 | |
| `payment_channel_daily` | 待探测 | 待探测 | 待记录 | 待验证 | 待验证 | |
| `first_pay_analysis` | 待探测 | 待探测 | 待记录 | 待验证 | 待验证 | |
| `first_pay_ltv` | 待探测 | 待探测 | 待记录 | 待验证 | 待验证 | |
| `user_retention` | 待探测 | 待探测 | 待记录 | 待验证 | 待验证 | |

接口设计已确认为一致，但“同一套系统”不等于两个当前运行环境的部署版本、账号权限
和历史数据范围已经完成探测，因此仍需分别记录运行验证结果。

## 12. 联调步骤

### 12.1 安全准备

1. 为 RajWin、RajLuck 创建专用只读账号；
2. 由管理员在盘口配置页录入远端凭据，后端写入 Secret Manager 或以数据库外主密钥进行信封加密，不写入文档和 Git；
3. 移除参考代码中的硬编码凭据和 Token 打印；
4. 如硬编码凭据曾被实际使用，完成轮换；
5. 建立远端域名 Allowlist 和请求速率上限。

### 12.2 探测

对每个来源执行：

1. TLS 和登录探测；
2. Token 过期和自动刷新测试；
3. 每个 P0 端点空结果、小结果、多页结果；
4. 日期边界和业务时区测试；
5. 最大分页、最大日期跨度和限流测试；
6. 匿名保存请求形状和响应 Schema；
7. 建立字段、类型、可空性和枚举清单。

### 12.3 对账

至少选择：

- 普通工作日；
- 月末；
- 跨午夜边界；
- 有数据和无数据日期；
- 典型渠道；
- 特殊合计行。

对账内容：

- 页面显示总数；
- 分页累计记录数；
- 金额精度；
- 人数去重规则；
- 比率分子/分母；
- 渠道 code/label；
- 时区归属。

## 13. 契约样例管理

匿名响应样例建议存放：

```text
tests/contract/fixtures/
  rajwin/
    daily_summary_channel/
      success_page_1.json
      empty.json
      auth_failed.json
  rajluck/
    daily_summary_channel/
      success_page_1.json
      empty.json
      auth_failed.json
```

样例进入 Git 前必须：

- 移除用户名、Token、手机号、银行卡、IP、设备码；
- 替换真实 UID 和订单号；
- 保留字段结构、类型和分页形状；
- 记录采样日期、来源、endpoint_key 和 Schema 指纹；
- 通过自动敏感信息扫描。

## 14. 立项联调完成标准

- 两个来源的 P0 端点能力矩阵完整；
- 每个 P0 端点至少有正常、空、认证失败匿名样例；
- 时区、币种和渠道字段得到书面确认；
- 远端分页和限流边界已测量；
- 15–20 个 MVP 指标具备正式定义和负责人；
- 明确哪些数据可汇总、哪些只能对比；
- 远端只读账号和凭据轮换流程可用；
- 不存在任何硬编码凭据、Token 输出或任意远端代理入口。
