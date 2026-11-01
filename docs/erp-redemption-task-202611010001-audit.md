# 兑换码任务 202611010001：远端 HTTP 500 独立排查

取证日期：2026-11-01。时间均为北京时间，另有注明除外。

本次先只读核对生产 `data_handle` 的相关任务、审计、账号会话元数据，并使用统一账号现有会话进行有限的兑换码列表 GET、读取远端公开前端源码。用户随后明确授权仅对 RajWin issue `5208` 诊断创建一次，实测保存接口 HTTP 500，并核对无同名落地。未重试其他配置，未执行远端登录、连接检测、标签同步、发布或下载；未部署或迁移。未读取复审系统。

## 结论与证据边界

此问题与任务列表超时分开处理。任务数据存在，600 条创建执行均收到远端 HTTP 500，并被保存为失败。单项诊断已确认保存接口报 PHP 类型错误：`OperateBonusReviewRuleMapper::setRuleForCodeAndMailInfo()` 的第三个参数 `$money` 要求 `int`，实际收到 `string`。适配器通过 `str(Decimal)` 发送奖励上下限，而当前远端表单使用整数金额，属于金额字段类型契约不匹配。没有证据表明金额区间重叠、门槛重复或数量 50 是本次错误的原因。

创建流程先调用 `POST /api/common/giftCodeConfig/save`，取得 ID 后调用 `GET /api/common/giftCodeConfig/index` 查询 group_key。两个接口原来均使用同一句 HTTP 状态错误。单项诊断捕获的是保存 POST 的 500，未进入后续 group_key 查询。其他 599 条原始响应未留存，不能保证它们内部的异常文本完全相同。

## 任务事实与统计

- 任务 ID `63`，编号 `202611010001`，操作者 richer，创建于 `14:09:11.512567`。
- 本地营销类型均为 `AGENT`；2026-11-01 至 2026-11-30，每日 5 档，共 4 × 30 × 5 = 600 条配置。
- 以下每个 issue 对应 1 条失败的 `erp_compatibility_redemption.remote_create` 审计，共 600 条；尚无成功创建回执。不是 600 个不同根因。

| case 范围 | 盘口 / batch | 执行数 | 成功 | 失败 | 首条至末条完成时间 | 错误 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 5208–5357 | RajWin / 81 | 150 | 0 | 150 | 14:09:28–14:23:50 | HTTP 500 |
| 5358–5507 | RajLuck / 82 | 150 | 0 | 150 | 14:24:05–14:38:58 | HTTP 500 |
| 5508–5657 | RajSpin / 83 | 150 | 0 | 150 | 14:39:13–14:54:04 | HTTP 500 |
| 5658–5807 | RajRace / 84 | 150 | 0 | 150 | 14:54:18–15:09:11 | HTTP 500 |

所有 600 条的 `workflow_status` 均为 `FAILED`，错误均为 `远端管理后台返回 HTTP 500。`；`remote_configuration_id`、`remote_create_receipt_id` 均为空。空回执本身不能证明远端绝无落地。

四个所用统一远端账号均启用，具备本地 `ERP_REDEMPTION_CREATE` 授权；会话缓存元数据未过期、无登录失败或冷却记录。本次直接使用现有会话的列表 GET 获得 HTTP 200 / 业务 code 200，证实查询当时会话可读；不据此推断历史写权限一定正常。

## 参数与生产版本核对

各批次的共同参数：兑换码数量 50，单用户限制 1，单码限制 500，流水倍数 5，生效日偏移 0/0；开启手机号绑定，关闭银行卡绑定；设备、登录 IP、注册 IP 检测均开启且限制为 1；可选活动参数为空。

RajWin 首日的实际配置：

| issue | 人群 | 标签 ID | 充值门槛 | 奖励下限–上限 |
| --- | --- | --- | ---: | --- |
| 5208 | 全部用户 | 空数组 | 0 | 5–7 |
| 5209 | 游戏总局数 0 | 5001 | 0 | 5–17 |
| 5210 | 日充值 100–199 | 901990 | 100 | 13–13 |
| 5211 | 日充值 200–999 | 901991 | 200 | 17–17 |
| 5212 | 日充值 1000+ | 901028 | 1000 | 77–77 |

- 生产适配器 SHA256 为 `17657ff0c2b31f309e59a35d34551b7ca9a92fb6d62b21a7f6e96108fd2ba5b3`，与 10 月 25 日单项创建验收成功时一致。本次门槛、列表修复没有修改该创建适配器。
- 当前公开远端前端的普通兑换码路径仍为 `gift_type=0`，支持 `key_number` 输入；未发现该输入的 50 条禁用限制。`single_key_limit` 表单允许 1–999999999，500 在表单范围内。这不能证明服务端当前的所有限制。
- 当前表单仍默认 `reward_condition_type=0`、`refresh_flag=0`；领取范围初始化包含 `user_type`、`channel_type` 和四组空数组，与现有适配器一致。未发现足以支持直接补参修复的新差异。
- 本地 `AGENT` 为营销分类，与远端 `gift_type=3` 的代理奖励模式不同。不能仅凭名称把现有普通兑换码请求改为类型 3。
- 历史成功配置中存在一次生成多码的记录，但不能以旧记录证明当前远端的数量上限，也不能未经验证把本任务数量改为 1。

源码证据来自当前公开构建 `index-C3XZWIpP.js`、`receiveLimit-CXGiJ0jN.js`、`rewardCondition-Xr0P0yJK.js`、`rewardConfig-CAkM-h4n.js`；本机只读取证副本位于 `/private/tmp/raj-http500-task-202611010001/`，不是生产运行输入。

## 远端只读核对

使用统一账号已有会话，仅在 ECS 内存中解密会话令牌，未解密或导出登录密码；未调用可能触发重新登录的适配器 `_request()`。未输出会话值或原始响应正文。

1. 四盘口分别按完整名称查询 `11-01代理全部`、`11-01代理存款0`：均 HTTP 200 / code 200，返回 0 条。这是 8 个抽样，不能扩大为全部 600 条均不存在。
2. RajWin 用历史成功名称 `NEW-1025到1031存款100` 做正向对照，返回历史记录，证明名称过滤实际有效。
3. 四盘口执行与 `_find_group_key()` 一致的请求：page 1、pageSize 100、group_key/group_desc/valid_type 为空。全部 HTTP 200 / code 200，分别返回 100 条。这只能证明查询时状态，不能排除 14:09–15:09 的暂态故障。
4. 从公开前端确认操作日志只读路径 `/api/system/logs/getOperLogPageList`，限定账号及本次执行时间窗口查询；远端返回 HTTP 403，停止该路径，不尝试绕过权限。
5. 已有 Chrome 会话跳到登录页，未填写凭据或重新登录；浏览器会话过期不能直接解释统一 API 会话的结果。

## 分类、影响与恢复顺序

- status label：`missing_contract`，当前适配器未遵守远端严格整数金额契约；远端何时开始严格检查尚不明确，不能标为本次部署引入的 `new_regression`。
- layer / failure type：`tool_or_backend`；primary shard 为 `agent_tool_contract`，本案无 LLM 节点，node containment 不适用。
- audit depth：full，已核对任务输入、批次参数、账号授权、适配器、一次真实创建响应、远端回读及失败持久化；其他历史创建响应仍缺失。
- primary test topic：`error_boundary`；secondary 为创建契约和 `query_readback`。
- impact scope：本任务 600 条已知失败；是否影响其他新任务尚未核实。
- 放大因素：前端逐条创建失败后继续队列，同一共同异常重复执行了 600 次。
- 另一个恢复风险：保存返回 ID 后若 group_key 查询异常，当前统一适配器会抛异常而不返回已取得的 ID；这不是本案已证实根因，但说明不能在未核对远端时整批重试。
- rollback strategy：本次无运行时修改，无需回退；不回退门槛迁移或任务列表修复。
- 验证：`.venv/bin/python -m pytest -q tests/test_erp_redemption_remote_http_adapter.py`，14 项通过；模拟测试验证现有请求契约和错误边界，不证明真实远端 POST 正常。

## 获批单次诊断与金额契约修复预检

用户明确确认“允许单条诊断创建”。仅对 issue `5208` 执行一次，沿用 50 个码、奖励 5–7 的原参数。执行前再次核对账户/盘口映射、授权、0052、issue 状态和无同名记录；使用生产统一创建服务及一个仅允许一次保存 POST 的临时 transport。先保留本地执行占位，若保存返回 ID 则立即持久化回执，防止后续查询失败丢失 ID；禁止登录、发布及第二次保存请求。

- 请求时间：2026-11-01 18:33:58.107775。
- 路径：`POST /api/common/giftCodeConfig/save`；发送次数 1。
- 响应：HTTP 500、JSON 业务 code 500，363 字节。
- 远端跟踪信息：`cf-ray=a53a3e8a3ba70701-HKG`；本地诊断编号 `a93b7556-8ff4-4058-baa2-f1e56a7d7bf7`。
- 脱敏异常：`App\\Operate\\Mapper\\OperateBonusReviewRuleMapper::setRuleForCodeAndMailInfo(): Argument #3 ($money) must be of type int, string given`，远端调用行号 131。
- 没有成功保存回执；issue 恢复为 `FAILED`，仍为 HTTP 500。创建后按完整名称再次查询，HTTP 200、0 条。
- 诊断归档的父目录缺失导致 `FileNotFoundError`，所以完整响应加密文件未落盘。这是诊断脚本的后续留存错误，不是远端 500 的成因；脱敏 HTTP 响应已在异常前取得并持久化至 `erp_redemption.diagnostic_create_result` 审计。已修正目录创建，但没有再执行 POST。

修复预检：

- main goal：将奖励上下限以远端要求的 JSON 整数发送，消除已证实的金额字符串类型错误。
- acceptance points：`Decimal('5.00')` / `Decimal('7.00')` 发为整数 `5` / `7`；模拟严格整数接口接受；小数金额在任何远端请求前明确拒绝，不截断、不四舍五入；数量 50、标签、日期、领取限制保持原请求值。
- impact scope：统一远端 HTTP 适配器的两个奖励金额字段及对应回归；不改门槛、迁移、列表、营销类型或发布逻辑。
- risk level：范围较小；现有小数金额配置会被明确拒绝，与已观测的整数表单及远端 int 契约一致，避免静默改变金额。
- rollback strategy：可独立回退本次适配器和回归改动；不涉及数据库结构。生产部署另需确认范围、备份/回退和窗口。
- regression plan：严格整数远端模拟、带小数零的整数金额、非整数的请求前拒绝、原有创建/权限/下载邻接回归。已通过的模拟不能替代修复后的真实单项创建验收。
- feature flag / canary：请求参数类型修复不采用双模式开关；修复后的线上验收仍应先单项，必须另获部署和再次创建授权。

## 本地修复与验证结果

- `RajAdminGiftCodeAdapter.create_configuration()` 将 `reward_min` / `reward_max` 发送为 JSON 整数。`Decimal('5.00')` / `Decimal('7.00')` 保持金额值，编码为 `5` / `7`；非整数金额在登录或任何其他远端请求前明确拒绝，不自动取整。
- 创建模拟接口按实际异常严格要求 JSON 整数。新增的 5 个目标回归在修复前均失败；修复后通过。统一账号链路中两项旧断言仍要求金额字符串，分类为 `test_contract`，已更新为实测整数契约，并覆盖数量 50 的创建/下载衔接。
- `.venv/bin/python -m pytest -q -o addopts='' tests/test_erp_redemption_remote_http_adapter.py tests/test_erp_compatibility_redemption_remote_service.py tests/test_remote_account_sessions.py`：56 项通过。
- Ruff 检查本次适配器和两个测试文件通过。未修改部署配置、发布脚本或数据库结构。
- 生产回读：5208 为 `FAILED`，没有配置 ID 或创建回执；其他 599 条均仍为原 HTTP 500 且无回执，最后更新时间仍为 15:09:11；诊断占位、结果审计各 1 条。未触发第二次创建或任何发布。

本地验证结束时，根因已定位、修复已完成，尚未发布。单次诊断授权已用完，后续真实创建需要另行授权。

## 获批部署与生产验收

用户随后明确指令“部署”。沿用本会话已确认的目标 `analysis.ailuckdg.com`、应用备份/回退方案及立即执行的发布安排，预留约 10 分钟；不迁移数据库，不重试或发布兑换码。

- 业务修复提交 `94e2599`，已推送 `codex/payment-channel-dictionary`。
- 发布包以新取得的生产源码快照为基础，509 个文件逐项核对后，仅替换 `packages/domain/services/erp_redemption_remote_http_adapter.py`。未包含本地其他未提交改动，未修改部署配置或脚本。
- 备份：`/opt/raj_data_handle/backups/pre-integer-reward-20261101T103853Z/`，含源码、权限受限的原运行配置、4 个应用镜像回退标签及 manifest。源码归档可读取，回退标签与发布前运行镜像一致。无数据库结构变更，不新增数据库备份或降级操作。
- 按 YAML 和本机私有输入重新渲染配置，确认与生产原配置哈希一致。通过项目 `push-rajluck.sh --upload-source --stage-only --remote-deploy` 暂存，再核对远端仅有预定的一处源码差异，最后用 `deploy-rajluck.sh --skip-git` 构建与重启。未执行 `--schema-only`。
- 新快照隔离环境中运行相同 56 项回归全部通过；相关 Ruff、发布脚本语法检查通过。
- 应用执行窗口：2026-11-01 北京时间 18:40:10–18:42:56，约 2 分 46 秒。准备和备份在此前完成。
- 生产 api、erp-compat、web、redis 健康，worker 与 edge-proxy 正常运行。api/worker 容器内适配器哈希均与发布文件一致，运行配置保持原值。
- 在生产 api 容器中以 `httpx.MockTransport` 核验真实加载的适配器：50 码、奖励 `5.00–7.00` 编码为整数 `5–7`；非整数奖励在任何请求前拒绝。实际远端请求为 0，此项不能替代真实创建验收。
- 本机 Web 健康接口 HTTP 200；公网浏览器显示 `{"status":"ok"}`，本机具名客户端及 ECS 公网检查均 HTTP 200。默认 Python User-Agent 请求返回 403，具名客户端返回 200；未修改任何防护配置。
- RDS 只读验收：版本仍为 `20261101_0052`；本任务 600 条仍全部为失败、配置 ID 和创建回执均为 0，4 个批次均未发布。此次仅部署，没有真实重试创建。
- 生产 manifest 已记录应用和公网验收结果；本机发布日志与验证副本位于 `/private/tmp/raj-reward-integer-release-94e2599/`。

应用部署完成，修复后的真实远端创建仍待单项授权验收。
