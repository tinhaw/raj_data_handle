# Raj Data Handle 协作约定

本文件适用于在本仓库工作的所有自动化代理和开发者。若与用户的明确指令冲突，以用户指令为准。

## 系统边界

- 本项目是 RajWin / RajLuck 的只读数据分析与对账系统；RajWin、RajLuck 是应用内远端数据源，不是独立部署节点。
- 生产环境只有一个 Raj Data Handle ECS 与一个 `data_handle` RDS 数据库。
- 不实现远端订单修改、审核操作或其他会改变远端业务数据的功能。
- 不读取、写入、迁移或复用复审系统的 `review_recheck` 数据库、Redis、容器、卷、配置或密钥。

## 配置与密钥

- `configs/deployments.local.yml` 是本机部署参数的唯一来源，保存 ECS 公网 IPv4、SSH 策略、外部端口及 RDS 地址/端口/数据库名；不得保存私钥、密码或应用密钥。
- `deploy/secrets/raj-data-handle.env` 是仅本机保存且 Git 忽略的私有输入文件。只在其中填写 RDS 账号密码、应用密钥和保留期设置。
- 私有 env 不是云主机运行时 env。发布脚本必须用 YAML + 私有 env 渲染完整运行时 `.env`，再上传到 `/opt/raj_data_handle/.env`；不得直接复制复审系统或其他项目的 env。
- 不在命令输出、日志、测试断言、文档、Git 提交或聊天中输出密码、连接串、私钥、会话密钥或加密密钥。

## 生产访问与发布

- 当前外部访问模式固定为 `cloudflare_reverse_proxy`：由 YAML 的 `web.hostname` 和本机 `web.port` 生成 HTTPS CORS、Secure Cookie 与仅本机 Web 监听地址。Cloudflare 橙云代理连接 ECS 上的边缘 Nginx `443`；不得在私有 env 中重复配置这些值，也不得对公网暴露 `18080`。
- ECS SSH 只允许 `public_key` 认证并要求 `strict` 主机指纹校验。禁止回退到 SSH 密码或键盘交互认证。
- 私钥只由本机 SSH Agent、系统 SSH 配置或发布命令的 `--identity-file` 提供；不得写入仓库或 YAML。
- 生产目录固定为 `/opt/raj_data_handle`，Compose 项目名固定为 `raj-data-handle`。发布使用 `deploy/push-rajluck.sh` 与 `deploy/deploy-rajluck.sh`，不要用根目录 `compose.yaml` 部署生产环境。
- 未获用户明确授权时，不连接 ECS、不上传文件、不重启服务、不执行发布，也不执行数据库迁移。

## 数据库

- RDS 仅可从 ECS 内网侧连接；目标数据库必须是 `data_handle`。
- 数据库结构变更与应用发布必须分离。仅在用户明确确认备份、回退方案、风险和执行窗口后才可运行 `--schema-only`。
- 禁止对共享 RDS 执行未计划的降级、删表、清库、`docker compose down`、卷清理或其他破坏性操作。

## 验证

- Python 检查和测试使用仓库 `.venv/bin/python`，项目要求 Python 3.12+；不要使用 macOS 系统 Python 3.9。
- 修改部署配置、渲染器或发布脚本后，至少运行：`pytest -q`、`ruff check deploy tests`、相关 shell 语法检查，并保持任何测试输入不含真实凭据。
