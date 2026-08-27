# ERP 高保真兼容边界

> 状态：P1–P5 与生产切换已完成；统一远端业务操作仍保持执行禁用
>
> 生产 schema、历史导入、应用发布和入口切换已在获批窗口执行；本文不授权任何远端业务操作。

## 1. 唯一身份来源

Raj Data Handle 的 `app_users`、`auth_sessions` 和 HttpOnly `raj_session`
Cookie 是唯一登录与会话来源。兼容服务不得创建第二个登录页、用户密码、
`JSESSIONID` 或 Bootstrap 管理员。

主 API 提供内部只读契约：

```text
GET /api/v1/erp/access/compatibility-session
Cookie: raj_session=<existing HttpOnly session>
```

响应只包含当前用户 ID、显示信息、会话到期时间、ERP 角色、权限及公司范围。
不包含 Cookie、密码、哈希、JWT、TOTP、远端账号密文或会话密钥。兼容服务随后把
当前权限映射为旧 API 所使用的 authority 名称；旧 Spring 登录和用户管理实现只保留
为上游回归测试夹具，不进入运行时路由。

统一盘口/账号的内部只读契约为：

```text
GET /api/v1/erp/remote-accounts/compatibility-registry
Cookie: raj_session=<existing HttpOnly session>
```

它按旧页面需要的 market/connection 形状返回 `SourceConfig + RemoteAccount`，但只给出
“凭据是否配置”和 capability，不返回密码、TOTP、密文或远端令牌。

## 2. 权限映射

| 当前权限 | 旧 ERP authority |
| --- | --- |
| `ERP_OPERATOR_VIEW` | `OPERATOR_VIEW` |
| `ERP_OPERATOR_MANAGE` | `OPERATOR_MANAGE` |
| `ERP_LEDGER_VIEW` | `BALANCE_VIEW` |
| `ERP_LEDGER_WRITE` | `BALANCE_EDIT` |
| `ERP_LEDGER_OVERRIDE` | `BALANCE_OVERRIDE` |
| `ERP_LEDGER_CONFIRM`、`ERP_LEDGER_REOPEN` | `BALANCE_CONFIRM` |
| `ERP_PERIOD_LOCK` | `PERIOD_LOCK` |
| `ERP_IMPORT` | `IMPORT` |
| `ERP_REPORT_VIEW` | `REPORT_VIEW` |
| `ERP_REPORT_EXPORT` | `REPORT_EXPORT` |
| `ERP_AUDIT_VIEW` | `AUDIT_VIEW` |
| `ERP_REDEMPTION_VIEW` | `REDEMPTION_VIEW` |
| `ERP_REDEMPTION_MANAGE` | `REDEMPTION_MANAGE` |
| `ERP_REDEMPTION_GENERATE` | `REDEMPTION_GENERATE` |
| `ERP_REDEMPTION_EXPORT` | `REDEMPTION_EXPORT` |
| `ERP_REMOTE_ACCOUNT_MANAGE` | `REDEMPTION_REMOTE_MANAGE` |
| `ERP_ACCESS_MANAGE` | `USER_MANAGE` |

## 3. 数据表归属

| 数据 | 唯一目标 | 处理方式 |
| --- | --- | --- |
| 用户与会话 | `app_users`、`auth_sessions` | 保留当前表；不迁移旧用户密码和 Session |
| ERP 角色/公司范围 | `erp_user_*` | 保留当前授权模型；通过兼容身份契约读取 |
| 盘口 | `source_configs` | 旧 `redemption_remote_markets` 转为适配视图/DTO，不建第二份主数据 |
| 远端账号、密码、TOTP | `remote_accounts` | 旧 `redemption_remote_connections` 只做历史 ID 映射，不保存凭据副本 |
| 标签与兑换档位 | `remote_account_tag_snapshots`、`remote_account_reward_tier_presets` | 旧 API 契约适配到当前表 |
| 投放公司/投放线 | `erp_compat_operators`、`erp_compat_operator_accounts` + ID 映射 | 保留线上 Long ID 契约；当前 UUID 记录在创建事务内取得稳定 numeric ID，0035/0036 对既有记录回填 |
| 台账、锁账、导入、报表 | `erp_compat_daily_balances`、锁账及导入兼容表 | 0036 已从旧 Flyway 转为 Alembic并提供当前表数据转换；金额、精度、状态和时间语义不改写 |
| 兑换活动、任务组、子任务、代码 | `erp_compat_redemption_*` + ID 映射 | 0037 保留线上 Long ID、任务组/批次/单项状态机；`remote_connection_id` 只保存统一 `RemoteAccount` 的 numeric crosswalk，不建立旧账号表 |
| 审计 | ERP 兼容审计 + 当前 actor user ID | 不复制旧身份；保留线上实体/动作/请求 ID 语义 |

兼容业务表的最终 DDL 只能进入本项目 Alembic 链。导入快照中的 Flyway 文件不得对
`data_handle` 执行。Long/UUID crosswalk 与兼容业务表已通过 Alembic 0035–0037 在生产落地；兼容
GET 只读取预置映射，缺失时返回 503，不会在读取请求中隐式写库或扩大权限。
线上 ERP 历史 Long ID 在数据导入时原值绑定；当前 UUID/字符串投影统一从
`9_000_000_000_000` 以上的 JavaScript 安全整数保留区分配，避免预迁移数据占用线上 ID。

## 4. 远端操作门

兼容服务具有独立的全局迁移开关和远端操作开关，默认均为关闭。融合模式会进一步
硬阻断导入的 Spring 凭据客户端；实际远端执行只能进入主应用统一账号 runner。即使用户拥有 ERP
功能权限，以下操作仍必须再通过统一账号 capability 与当次执行授权：

- 连接检测；
- 标签读取与同步；
- 远端兑换配置创建；
- 立即/定时发布与取消；
- 兑换码下载。

当前生产运行时的远端操作总开关为关闭；本次迁移和切换没有对任何线上盘口发出这些请求。

## 5. 生产激活结果

兼容服务在以下条件全部满足后，已通过生产 Compose 激活并完成入口切换：

1. 旧登录和用户管理路由已从运行时移除；
2. `compatibility-session` 适配器和权限拒绝测试通过；
3. `SourceConfig + RemoteAccount` 适配器通过契约测试；
4. 所需 Flyway DDL 已转换为 Alembic 0035–0037 迁移链；
5. 页面、API、Excel、权限和状态机差异矩阵通过；
6. 已取得生产发布、schema、数据迁移与切换授权，并保留可恢复备份和明确回退负责人。

P5 的隔离快照导入、安全门、逐表摘要、金额/关系/文件校验和显式主数据映射见
[P5 ERP 历史数据快照迁移演练](./erp-p5-snapshot-rehearsal.md)。该工具硬拒绝生产
`data_handle`，除非显式选择 `production-cutover` 模式并提供生产确认串。真实双快照隔离
演练与生产导入均已完成；远端业务操作仍需逐项另行授权。
