# Raj Data Handle 部署方案

## 1. 结论与边界

可以在已配置 ECS 上部署本项目，前提是它作为**完全独立的 Docker Compose 应用**运行。
同主机的既有系统仍位于 `/opt/withdrawal_recheck_review`，本项目固定使用：

| 项目 | 约定 |
|---|---|
| 项目目录 | `/opt/raj_data_handle` |
| Compose 项目名 | `raj-data-handle` |
| 数据库 | 配套 RDS 的 `data_handle` |
| 数据库来源 | RDS 地址、端口和库名来自本机 `configs/deployments.local.yml`；账号和密码只来自本机私有 `deploy/secrets/raj-data-handle.env` |
| Redis / 文件卷 | 本项目 Compose 专属命名卷 |
| Web 监听 | 数据分析容器仅为本机 `127.0.0.1:18080` 提供诊断入口 |
| 外部访问 | `https://analysis.ailuckdg.com`，经 Cloudflare 橙云代理和本项目的 443 边缘 Nginx 容器 |

该方案不修改复审系统的目录、Compose 项目、容器、网络、Redis、卷、`review_recheck`
数据库或其数据库账号。ECS 信息文件中的密码不被部署脚本使用；脚本只允许 SSH 公钥登录。
主机公网 80 仍由复审 Nginx 容器占用。Raj Data Handle 新增独立的 host-network 边缘
Nginx 容器监听 443：它按域名转发 `analysis.ailuckdg.com` 到本机 18080，并将
`recheck.ailuckdg.com` 的 HTTPS 请求转发给既有 80 端口；不修改复审应用的目录、Compose
项目、容器或配置。安全组只需向 Cloudflare 开放 TCP 443；`18080` 不得对公网开放。

## 2. 文件与职责

| 文件 | 作用 |
|---|---|
| `deploy/compose.rajluck.yml` | 生产 Compose；不声明 PostgreSQL 服务，只接受外部 RDS 连接，并包含只监听 443 的边缘 Nginx。 |
| `deploy/nginx.edge.conf` | 独立 TLS 反代；使用 Cloudflare Origin CA 证书按域名分流到数据分析和既有复审 HTTP 服务。 |
| `configs/deployments.local.yml` | 本机唯一的 `raj-data-handle` 目标来源；保存 ECS 公网 IP、SSH 公钥认证策略、分析域名、本机诊断端口及 RDS 的内网地址、端口、数据库名，不保存密码或私钥。RajWin/RajLuck 是应用内配置的远端数据源。 |
| `deploy/deployment_config.py` | 校验本机唯一的数据分析部署目标，拒绝非 ECS 内网 RDS 目标。 |
| `deploy/init_rajluck_secrets.py` | 可选地生成应用密钥；不会填入 RDS 账号或密码，默认拒绝覆盖。 |
| `deploy/render_rajluck_env.py` | 校验目标配置和数据库名必须为 `data_handle`，从私有 env 读取 RDS 账号密码，并依据 YAML 的分析域名生成 HTTPS CORS、Secure Cookie 与本机监听配置；过程不输出密钥。 |
| `deploy/secrets/raj-data-handle.env.example` | 私有 env 模板；实际 `raj-data-handle.env` 文件被 Git 忽略，所有敏感值由部署人员在本机填写。 |
| `deploy/push-rajluck.sh` | macOS/Linux 本机入口；SSH 严格主机指纹、仅公钥登录，默认演练。 |
| `deploy/deploy-rajluck.sh` | 主机端入口；应用发布与 Alembic 迁移分离。 |

根目录 `compose.yaml` 包含本地开发 PostgreSQL，并会在启动 API 时自动运行迁移，**不得**
用于生产环境。

## 3. 一次性准备

1. 确认本项目已经推送到其 Git 远端的目标分支（默认 `main`）。
2. 确认本机存在 `configs/deployments.local.yml`。若是新环境，可先从
   `configs/deployments.local.yml.example` 复制；该文件只登记本系统唯一 ECS 目标，不能
   填入 RDS 密码或应用密钥。
3. 在本机创建并填写仅本机可读的私有 env 文件。当前工作区已生成
   `deploy/secrets/raj-data-handle.env`；新环境可从模板复制：

   ```bash
   cd /Users/dinghao/Documents/code/raj_data_handle
   cp deploy/secrets/raj-data-handle.env.example deploy/secrets/raj-data-handle.env
   chmod 600 deploy/secrets/raj-data-handle.env
   ```

   由部署人员在该文件中填写以下值，不能提交、复制到聊天或写进 YAML：

   | 变量 | 填写内容 |
   |---|---|
   | `RAJ_RDS_USERNAME` / `RAJ_RDS_PASSWORD` | `data_handle` RDS 账号与密码。 |
   | `RAJ_SECRET_KEY` | 至少 32 个字符的随机应用密钥。 |
   | `RAJ_CREDENTIAL_ENCRYPTION_KEY` | 32 字节 URL-safe Base64 密钥；模板内给出了本机生成命令。 |
   外部访问参数不放在私有 env。它们从 YAML 的以下配置统一生成：

   ```yaml
   web:
     access_mode: cloudflare_reverse_proxy
     hostname: analysis.ailuckdg.com
     port: 18080
   ```

   渲染后固定使用 `WEB_BIND_ADDRESS=127.0.0.1`、`RAJ_SESSION_COOKIE_SECURE=true`，并自动生成
   `RAJ_CORS_ORIGINS=["https://analysis.ailuckdg.com"]`。域名与诊断端口只改 YAML，不放入私有 env。
   `deploy/init_rajluck_secrets.py` 仅是可选的本机随机密钥生成辅助工具，使用时仍需手动填写
   RDS 账号和密码。
4. 确认 `configs/deployments.local.yml` 中 `raj-data-handle` 是正确的 ECS 目标。脚本默认
   使用该项的 `ssh_user`、`ecs_host` 和 `ssh_port`；如本机使用 SSH
   别名，可通过 `--ssh-target <ssh-别名>` 覆盖。`ssh_authentication: public_key` 与
   `ssh_host_key_checking: strict` 是强制校验项：私钥仅由本机 SSH Agent、系统 SSH 配置或
   `--identity-file` 提供；发布脚本禁用 SSH 密码和键盘交互认证，并强制严格主机指纹校验。
5. Cloudflare DNS 为 `analysis.ailuckdg.com` 配置同一 ECS 的 A 记录并保持橙云代理；在 ECS
   `/etc/nginx/tls/` 安装 Cloudflare Origin CA 证书和仅 root 可读私钥。安全组只开放 TCP 443
   给 Cloudflare 回源地址；不要开放 RDS 端口或 TCP 18080。

## 4. 应用发布（不含数据库迁移）

先执行默认演练；它只校验本地输入与数据库目标，不会推送、不上传、不连接主机：

```bash
cd /Users/dinghao/Documents/code/raj_data_handle
bash deploy/push-rajluck.sh \
  --deployment-config configs/deployments.local.yml
```

首次发布需要把仓库克隆到 `/opt/raj_data_handle`，随后上传渲染出的临时 `.env` 并启动
独立容器：

```bash
bash deploy/push-rajluck.sh \
  --deployment-config configs/deployments.local.yml \
  --init --remote-deploy
```

后续纯应用发布去掉 `--init`。若需要先将当前分支推送到 Git 远端，再额外传入
`--git-push`。正常发布执行 `docker compose up -d --build --remove-orphans`，但仅作用于
`raj-data-handle` 项目，且**不会执行** Alembic。

如果当前源码尚未形成可由 ECS 拉取的 Git 提交，可以显式上传本地源码快照：

```bash
bash deploy/push-rajluck.sh \
  --deployment-config configs/deployments.local.yml \
  --upload-source --init --remote-deploy
```

该模式只打包运行所需源码，并排除私有 env、原始业务数据、接口抓包、Git 元数据、
`node_modules`、缓存和本机构建产物；远端使用 `--skip-git` 发布。私有 env 仍按
YAML + 本机私有输入单独渲染和上传，不进入源码压缩包。

发布后在主机验证（只读）：

```bash
DATA_HANDLE_SSH_TARGET='root@<ECS-host>'
ssh "$DATA_HANDLE_SSH_TARGET" 'docker compose --project-name raj-data-handle \
  -f /opt/raj_data_handle/deploy/compose.rajluck.yml --env-file /opt/raj_data_handle/.env ps'
ssh "$DATA_HANDLE_SSH_TARGET" 'curl --fail http://127.0.0.1:18080/health'
ssh "$DATA_HANDLE_SSH_TARGET" 'curl --resolve analysis.ailuckdg.com:443:127.0.0.1 \
  --cacert /etc/nginx/tls/ailuckdg.com-origin.crt https://analysis.ailuckdg.com/health'
```

初始建表完成后，再在 API 容器内创建首个管理员；该命令使用项目自己的 `data_handle`
库：

```bash
DATA_HANDLE_SSH_TARGET='root@<ECS-host>'
ssh "$DATA_HANDLE_SSH_TARGET" 'cd /opt/raj_data_handle && docker compose \
  --project-name raj-data-handle -f deploy/compose.rajluck.yml --env-file .env \
  exec api python -m scripts.create_admin_user --username admin'
```

管理员密码不得作为命令行参数、聊天内容或日志保存；按 CLI 的交互提示输入即可。

## 5. 数据库变更门禁

首个 Alembic 版本会在 **`data_handle`** 新库中创建 `app_users`、`auth_sessions`、
`security_audit_logs`、`system_retention_settings`、`source_configs`、支付平台/模板、
支付渠道绑定、文件对象/引用、比对批次/结果/活动日志和用户通知等表及索引。它不会触及
`review_recheck` 的任何表。

| 风险项 | 评估与控制 |
|---|---|
| 兼容性 | 初始迁移仅新建 `data_handle` 对象，对复审代码和复审表向后兼容。 |
| 锁与停机 | 新表和索引 DDL 会锁定本项目的新对象；不会锁定复审表。共享 RDS 仍可能产生短暂 CPU、I/O、连接数竞争，因此应在低峰执行并观察 RDS。 |
| 数据丢失 | 初始 `upgrade` 本身不删除数据；但错误地连接到错误数据库风险极高，脚本已强制拒绝非 `data_handle`。 |
| 备份与回退 | 执行前确认 RDS 快照/备份可恢复，并记录当前 Alembic revision。应用故障时停止或回退 `raj-data-handle` 容器即可，不影响复审。删除或降级 `data_handle` 表只能在单独确认后进行。 |

只有在以下事项已明确确认后，才可以单独运行建表/升级：

1. 已核对目标 RDS 端点、数据库名为 `data_handle`、账号权限范围正确；该连通性需从
   ECS/API 容器验证，不从本机直连 VPC RDS。
2. 已完成或确认可用的 RDS 备份/快照和回退负责人。
3. 已确认本次迁移的表、字段、锁风险和执行窗口。

满足门禁后，仅执行一次：

```bash
bash deploy/push-rajluck.sh \
  --deployment-config configs/deployments.local.yml \
  --remote-deploy --schema-only
```

禁止把 `--schema-only` 与 `--init` 组合，也不要用根目录 `compose.yaml` 在生产环境做
自动迁移。

## 6. 运维与回退

- **纯应用故障**：停止或将 `/opt/raj_data_handle` 回到已知提交后重新运行普通发布；不要
  执行 `docker compose down`、`volume prune` 或修改复审栈。
- **数据库迁移故障**：保留容器与日志，停止数据分析写入；依据确认过的 RDS 备份或专门
  设计的向后兼容迁移处理。不要对共享 RDS 做无计划的 `downgrade` 或删表。
- **资源监控**：持续观察 RDS 连接数、CPU、I/O、磁盘及 ECS 的内存/磁盘；数据文件和
  比对结果按系统默认保留策略清理。
- **密钥轮换**：应用密钥和远端来源凭据只保存在本机密钥文件或系统加密字段中；更新后用
  正常应用发布使容器读取新值，勿提交 `.env`。

## 7. 发布验收

1. `docker compose ... ps` 显示 `api`、`worker`、`web`、`redis`、`edge-proxy` 正常；复审容器状态无变化。
2. `curl http://127.0.0.1:18080/health` 返回 HTTP 200。
3. API/Worker 日志无数据库认证、迁移或 Redis 连接错误。
4. 首次迁移后，管理员可登录、可保存来源配置，且来源凭据不在日志或接口响应中出现。
5. `https://analysis.ailuckdg.com` 经 Cloudflare 可登录并保存 Secure 会话 Cookie；公网不能
   连接 TCP 18080。Cloudflare SSL/TLS 使用 **Full (strict)**，且为分析域名配置缓存绕过规则。
