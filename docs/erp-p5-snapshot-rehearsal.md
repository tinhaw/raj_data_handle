# P5 ERP 历史数据快照迁移演练

状态：演练工具、稳定业务键目录解析器与合成全链路样例已完成。2026-08-27 已取得旧 ERP
与 `data_handle` 两个生产一致性备份；真实历史先后在全新 0037 PostgreSQL 和由生产 0034
恢复的隔离克隆上完成全量演练。生产 schema、数据导入、应用发布与切换均未执行。

## 1. 固定边界

`deploy/rehearse_erp_snapshot.py` 只接受数据库名或 SQLite 文件名中明确包含
`snapshot` / `rehearsal` 的源和目标，且硬拒绝生产 `data_handle`。默认只预检；写入还
必须同时传入 `--apply --confirm-isolated-rehearsal P5-ISOLATED-REHEARSAL`。

`deploy/prepare_erp_p5_directory_mapping.py` 使用旧用户名、盘口代码、远端登录名和当前
`source_id` 等稳定业务键生成上述工具需要的数字 ID / UUID 映射。它同样硬拒绝生产库；
只有传入 `--apply --confirm-isolated-directory P5-ISOLATED-DIRECTORY` 时，才会在隔离目标
创建缺失的统一远端账号占位记录。这类记录固定为禁用、无凭据、无能力授权，不会调用远端。

源连接会在 PostgreSQL 事务中设置为只读，在 SQLite 中开启 `query_only`。工具不会迁移：

- 旧 ERP 的密码哈希、角色表或 Session；
- 旧远端账号的密码、TOTP、Bearer Token、Access Token 或远端 Session；
- `review_recheck` 的任何数据库、Redis、容器、卷、配置或密钥。

当前 V19 的 22 张表已全部显式分类：12 张业务历史表逐行复制，7 张身份/盘口目录表转换，
`permissions`、`role_permissions` 和 `flyway_schema_history` 3 张定义/迁移元数据表明确排除。
真实预检若发现第 23 张未分类表会直接失败，禁止以“未知表忽略”方式继续。

旧用户只作为历史操作人和授权来源，通过显式清单一对一映射到当前 `app_users`。旧盘口
和远端账号分别显式映射到当前 `SourceConfig` 与 `RemoteAccount`。任何缺项、重复映射、
账号归属盘口不一致或目标已有待覆盖数据，都会在写入前失败。

## 2. 数据归属与转换

| 旧 ERP 数据 | 演练目标 | 规则 |
| --- | --- | --- |
| 投放公司、投放线 | `erp_compat_*` 业务表 + `erp_operators/erp_operator_lines` 影子主数据 | 原 Long ID 保留；当前 UUID 使用确定性 UUID，写入 0035 crosswalk |
| 台账、锁账、导入行、审计 | 0036 `erp_compat_*` 表 | 金额、状态、时间和 Long ID 原样保留；操作人改为当前用户 ID |
| 活动、档位、任务、批次、兑换码 | 0037 `erp_compat_redemption_*` 表 | 原 Long ID 和状态机原样保留 |
| 批次远端账号 | 当前 `RemoteAccount` 的 0035 数字兼容 ID | 不保存旧账号凭据副本 |
| 标签与兑换档位预设 | `remote_account_tag_snapshots`、`remote_account_reward_tier_presets` | 显式绑定统一账号；已有快照时拒绝覆盖 |
| ERP 角色与公司范围 | `erp_user_*` | 清单指定当前 ERP 角色；旧公司范围转换到确定性 UUID |
| Excel 原始文件 | 隔离演练文件根目录 `imports/import-{id}.xlsx` | 仅 XLSX 任务需要；复制前后都核对数据库中的 SHA-256 |

真实目录规则以
[erp-p5-directory.example.json](../deploy/erp-p5-directory.example.json) 为模板，解析后的
数字 ID 清单格式见 [erp-p5-mapping.example.json](../deploy/erp-p5-mapping.example.json)。
每个旧用户必须明确“映射”或“忽略”；被历史业务记录引用的操作人不得忽略。每个旧盘口
和旧远端账号必须全部映射，且不同旧账号不能合并为同一个统一账号。生产专用目录规则及
解析结果只能放在 Git 忽略的受控路径，不提交用户名目录或内部 ID 清单。

线上只读目录核对确认：旧 ERP 使用三个盘口和三个分别归属盘口的兑换账号；合并系统当前
只有每盘口一个历史分析默认账号。由于登录身份和用途不同，兑换账号不得绑定到分析默认
账号，必须在同一 `remote_accounts` 主数据中保留为各盘口独立账号。旧密码、TOTP 和会话
不复制，切换后由管理员重新录入，并逐项授予 ERP 能力。

## 3. 演练顺序

数据库 URL 只能通过环境变量传入，避免出现在命令行参数和报告中。以下变量仅在当前
执行终端设置，不写入仓库：

```bash
export ERP_P5_SOURCE_SNAPSHOT_URL='postgresql+psycopg://.../erp_snapshot'
export ERP_P5_TARGET_REHEARSAL_URL='postgresql+psycopg://.../data_handle_rehearsal'
```

先用稳定业务键生成目录映射。首次命令只读源、目标数据库，不会创建账号：

```bash
.venv/bin/python -m deploy.prepare_erp_p5_directory_mapping \
  --spec /secure/path/erp-p5-directory.json \
  --output-mapping /secure/path/erp-p5-mapping.json \
  --report /secure/path/erp-p5-directory-preflight.json
```

确认预检只包含预期的缺失账号后，在隔离目标创建禁用且无凭据的占位账号，并重新输出最终
映射：

```bash
.venv/bin/python -m deploy.prepare_erp_p5_directory_mapping \
  --spec /secure/path/erp-p5-directory.json \
  --output-mapping /secure/path/erp-p5-mapping.json \
  --report /secure/path/erp-p5-directory-result.json \
  --apply \
  --confirm-isolated-directory P5-ISOLATED-DIRECTORY
```

然后做历史数据无写入预检：

```bash
.venv/bin/python -m deploy.rehearse_erp_snapshot \
  --mapping /secure/path/erp-p5-mapping.json \
  --source-files-root /read-only/erp-storage-snapshot \
  --report /secure/path/erp-p5-preflight.json
```

预检通过后，对隔离目标执行演练：

```bash
.venv/bin/python -m deploy.rehearse_erp_snapshot \
  --mapping /secure/path/erp-p5-mapping.json \
  --source-files-root /read-only/erp-storage-snapshot \
  --target-files-root /isolated/data-handle-rehearsal/erp-compat \
  --report /secure/path/erp-p5-result.json \
  --apply \
  --confirm-isolated-rehearsal P5-ISOLATED-REHEARSAL
```

报告不包含数据库 URL、用户名、密码、密文或令牌。它记录 Flyway/Alembic 版本、逐表行数、
金额汇总、逐行 SHA-256 摘要、孤立关系、用户/盘口/账号映射数量、文件 SHA-256 和明确排除项。

真实演练使用的旧 ERP 备份点为 `2026-08-27T11:58:24Z`。标准三件套（PostgreSQL custom
dump、文件卷归档和 SHA-256 manifest）已在服务恢复后于服务端、本地各校验一次。文件归档
为空，因此本次没有 XLSX 可复制或核对。该备份只是演练基线；如果旧 ERP 在生产切换前继续
写入，必须在最终停写窗口重新生成增量基线或完整一致性备份。

真实结果报告保存在 Git 忽略目录
`runtime/erp-p5/reports/erp-20260827T115824Z-98524/p5-history.result.json`。主要结果如下：

- 源 Flyway V19，目标 Alembic `20260827_0037`，12 张业务表全部完成复制；
- 2,512 条审计、1,187 条兑换码、27 个批次、27 个活动、19 个任务等逐表数量一致；
- 所有金额汇总和 12 张表的逐行规范化 SHA-256 摘要一致；
- 盘口 3 个、统一远端账号占位 3 个，均为禁用、无凭据、无能力、无 Session；
- 13 类硬关联孤儿均为 0，12 张兼容表的 PostgreSQL identity 序列均已同步。

旧 V19 数据还包含有意保留的历史软引用：32 条审计引用已删除操作人，16 条导入行引用已
清理的投放线及目标台账。这些字段在旧表与 0036 兼容表中本来就没有外键，属于清理业务对象
后仍需保存的证据，不作为硬关联错误；迁移报告会单独计数。公司/投放线、活动/档位、
任务/批次/兑换码等实时关系仍按硬关联检查，任何孤儿都会阻断迁移。

迁移器保留旧 Long ID，因此写入 PostgreSQL 后会对 12 张兼容表执行显式 sequence 同步。
演练已确认所有非空表的下一 ID 均大于当前最大 ID，避免切换后首笔新增记录主键冲突。

第二次演练使用 `data_handle` 备份点 `2026-08-27T12:30:23Z`。生产起点为 Alembic
`20260818_0034`、48 张表、数据库约 3.11 GB；PostgreSQL 18 custom dump 为 280,520,929
字节，ECS 与本机的结构、SHA-256 均已校验。备份恢复到无端口暴露的内部网络隔离容器后：

- `0035→0037` 一次升级成功，表数由 48 增至 61，原 48 张表的精确行数全部不变；
- 真实 ERP 目录解析和历史导入再次通过，金额、逐行摘要、关系和 sequence 结果与第一次一致；
- 原 48 张表中只有 7 张发生预期变化：公司/投放线影子主数据、ERP 用户授权、标签/档位
  快照和统一远端账号；订单、对账、TOTP、用户、Session 等其余 41 张表行数不变；
- 3 个新增 ERP 账号均禁用、无密文凭据、无启用能力；原 12 个 Session 和 5 个 TOTP
  账号未改变；
- 修复了 Alembic autogenerate 把 12 张 Spring 兼容表误判为待删除对象的风险，并把 ORM
  索引名校准到真实 0037 schema；隔离克隆最终 `alembic check` 为
  `No new upgrade operations detected`。

克隆演练报告保存在 Git 忽略目录
`runtime/erp-p5/reports/data-handle-20260827T123023Z/`，其中
`p5-history.result.json` 是历史导入结果，三份 `data-handle-counts.*.tsv` 是迁移前、
schema 后和历史导入后的精确行数基线，`alembic-check.final.txt` 是最终 schema 漂移结果。

## 4. 验收和生产前置条件

真实快照演练只有在以下项目全部为零差异时才算通过：

1. 十二张兼容业务表的源/目标行数一致；
2. 台账、活动档位和兑换码的金额字段汇总一致；
3. 公司/投放线、任务/批次/兑换码等硬关系无孤儿；历史软引用单列并可解释；
4. 每个批次远端账号均解析到唯一 `RemoteAccount` 兼容 ID；
5. XLSX 文件数量与 SHA-256 一致；
6. 每行规范化摘要一致，审计记录的操作人和时间线可追溯；
7. 目标中不存在旧密码、TOTP、Token 或 Session 表/字段副本。

真实快照演练通过仍不等于获准生产迁移。生产执行前必须依次完成：

1. 重新核对生产 revision、`data_handle` 可恢复备份、回退负责人和执行窗口；
2. 旧 ERP 停写后生成最终一致性备份，并与本次基线比较新增/变更范围；
3. 只通过本项目发布脚本先执行 0035–0037 schema，再导入历史数据并复核报告；
4. 发布应用、验证页面/API/导出后再切换路由。失败时只回切旧 ERP 路由，不降级或清理 RDS；
5. 切换后由管理员重新录入远端凭据，并分别授权所需能力。远端连接检测、标签同步、兑换码
   创建/发布/取消/下载仍须逐项授权，不能作为数据迁移的一部分自动执行。
