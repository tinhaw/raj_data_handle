# ERP 迁移与融合验收矩阵

基线日期：2026-08-18

对照来源：云端 `erp.aiggtj.com` 只读巡检及本地最新 `raj-ads-manage` 源码。
目标系统：`raj_data_handle`，沿用一套登录体系和一套 `SourceConfig + RemoteAccount` 盘口/账号主数据。

状态定义：

- **已完成**：页面、路由、权限、服务、数据模型及自动化测试均已落地。
- **代码就绪/执行禁用**：远端协议和内部执行代码已迁移，但没有可从页面或公开 API 触发的执行入口。
- **待授权执行**：不是代码缺口；必须另行确认生产备份、回退、窗口或具体远端业务操作后才能执行。

## 功能验收

| 云端 ERP 能力 | 融合实现 | 权限与范围 | 自动化验收 | 状态 |
| --- | --- | --- | --- | --- |
| 工作台 | 当日 KPI、7 日趋势、草稿/负结余/锁账/导入错误、最近日结 | `ERP_WORKSPACE_VIEW`；按公司范围汇总 | `test_erp_dashboard_service.py` | 已完成 |
| 投放公司/投放线 | 创建、编辑、停用、搜索、费率/币种；删除影响预检与公司名称二次确认 | `ERP_OPERATOR_VIEW/MANAGE`；按公司范围 | `test_erp_operator_service.py` | 已完成 |
| 连续日台账 | 自动承接、全金额字段、计算/影响预览、批量保存、确认、重开 | 查看、录入、复核、越权覆盖分别授权；按公司范围 | `test_erp_balance_service.py` | 已完成 |
| 月结锁账 | 月度校验、锁定、解锁及锁后写入阻断 | `ERP_PERIOD_LOCK`；按公司范围 | `test_erp_period_lock_service.py` | 已完成 |
| 导入中心 | 粘贴/XLSX、标准模板、预览、冲突策略、提交、历史行、源文件和错误报告 | `ERP_IMPORT_VIEW/EXECUTE`；任务按公司范围过滤 | `test_erp_import_service.py` | 已完成 |
| 汇总报表 | 日/月、公司/投放线/币种/状态筛选，原币种/名义 U、趋势图、Excel | `ERP_REPORT_VIEW/EXPORT`；按公司范围 | `test_erp_report_service.py` | 已完成 |
| 审计日志 | 追加式记录、日期/动作/公司筛选、详情、请求 ID | `ERP_AUDIT_VIEW`；受限用户只见可关联到授权公司的记录 | `test_erp_audit_service.py` | 已完成 |
| 用户与权限 | 一个本地用户多 ERP 角色，角色权限与公司范围分离 | `ERP_ACCESS_MANAGE` | `test_erp_access_service.py` | 已完成 |
| 系统设置 | ERP 时区、精度/舍入、上传上限等基线展示；会话仍复用主系统设置 | 系统管理权限 | 前端类型检查/构建 | 已完成 |
| 盘口与远端账号 | 复用 `SourceConfig` 盘口，新增统一 `RemoteAccount`；账号归属盘口并独立授权分析/ERP 能力 | 管理、查看分离；凭据永不回传 | `test_remote_account_service.py` | 已完成 |
| 标签和兑换档位预设 | 每账号标签快照、预设、快照变化后过期提示；任务按账号预设映射档位 | 本地配置需要账号管理权限 | `test_remote_account_service.py`、任务组测试 | 已完成 |
| 多盘口兑换任务组 | 一次选择多个账号，按顺序拆分子任务；按账号预设原子批量配置 | `ERP_REDEMPTION_GENERATE` | `test_erp_redemption_service.py`、`test_erp_redemption_remote_plan_service.py` | 已完成 |
| 兑换远端状态机 | 单项创建、组发布、下载、取消、失败、恢复、并发占用、执行历史 | 每个操作同时校验账号能力和本次显式授权 | `test_erp_redemption_remote_gate.py`、计划服务测试 | 已完成 |
| 单/多盘口 Excel | 单批次导出和任务组多 Sheet 联合导出 | `ERP_REDEMPTION_EXPORT` | 路由/服务回归与前端构建 | 已完成 |
| 当前远端 HTTP 协议 | 登录、连接检测、标签、创建、列表定位、发布、取消、Excel 下载；ERP 时区为 `Asia/Shanghai` | 适配器要求与账号/盘口/操作完全匹配的 grant | `test_erp_redemption_remote_http_adapter.py` | 代码就绪/执行禁用 |
| 远端执行器 | 只从统一账号解密凭据；令牌仅驻留内存；立即发布失败按 15/30/60 分钟回退 | 内部 runner 要求 `execution_authorized=True`；没有 HTTP/定时入口 | gate、adapter、plan 测试 | 代码就绪/执行禁用 |

## 数据与切换验收

| 项目 | 当前结果 | 状态 |
| --- | --- | --- |
| 数据库迁移链 | 0028–0034 已编写；全新 SQLite 升级到 head、0031 往返降升通过 | 已完成（迁移代码） |
| ERP 历史数据导入 | 尚未读取或迁移云端生产业务数据 | 待授权执行 |
| 生产 RDS schema | 尚未执行；目标只能是 `data_handle` | 待确认备份、回退方案和窗口 |
| 应用发布 | 尚未上传、重启或切流 | 待生产发布授权条件完整 |
| 远端连接检测/标签同步 | 本轮未调用 | 待逐项授权 |
| 远端创建/发布/取消/下载 | 本轮未调用，页面和公开 API 无执行入口 | 待逐项授权及联调 |

## 结论

ERP 的本地业务功能、统一身份/账号模型、远端编排状态机和当前远端协议代码已经迁入同一项目。生产数据库、历史数据和远端业务操作仍保持未执行，这是授权边界，不应被误报为已上线或已完成生产切换。
