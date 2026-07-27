# Raj Data Handle

RajWin / RajLuck 只读数据分析与订单遗漏比对系统。当前仓库已包含充值遗漏比对模块的
MVP 闭环：支付文件上传与模板识别、用户确认盘口/渠道/时间口径、异步只读拉取、逐单
精确复查、结果聚合、图表展示、共享批次、站内通知和 CSV/Excel 导出。

完整、已确认的业务口径见 [docs/README.md](docs/README.md)。

## 当前已实现

- FastAPI + SQLAlchemy 2 + Alembic 后端；
- Vue 3 + Element Plus + ECharts 管理界面；
- PostgreSQL 生产配置，SQLite 可用于本地测试；
- HttpOnly Cookie 会话、验证码、Redis 登录限流、会话撤销；
- `admin` / `user` 两类账号；业务能力共享，系统设置仅管理员可修改；
- 一次性 CLI 创建首个管理员，后续用户由管理员在页面创建；
- RajWin / RajLuck 独立盘口配置与 AES-256-GCM 凭据密文；
- 默认 3 / 30 / 30 天的文件、结果和远端缓存保留策略，可在系统配置页修改；
- `aelopay` 代收与 `elePay` 代付初始模板，未知表格不会静默套用模板；
- 当前已知 RajWin 多渠道绑定：`948`、`659`、`800`、`991`；
- 内容寻址文件存储、重复批次身份键、重跑版本、取消状态机；
- TOTP 登录、充值渠道字典同步、充值订单只读分页拉取和候选订单精确复查；
- 成功、非成功及未知支付状态统一进入比对，远端非成功、重复冲突和不确定结果单独标识；
- 团队共享批次列表、真实结果图表、订单明细、发起人站内 Alert；
- 最终批次可导出 UTF-8 CSV 和固定六工作表 Excel。

## 当前边界

当前只实现充值 / 代收模块，提现 / 代付执行器尚未接入。未知支付平台模板的自助字段
映射、导出审计和生产远端的联合验收仍待完成。虽然本地测试覆盖了
核心解析、分页和比对规则，在使用真实业务数据发布“确认遗漏”结论前，仍应先对
RajWin、RajLuck 各完成一次小时间窗口的人工对照验收。

## 本地开发

要求 Python 3.12+、Node.js 24+、PostgreSQL 和 Redis。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，至少替换 `RAJ_SECRET_KEY`。生产环境还必须配置独立的
`RAJ_CREDENTIAL_ENCRYPTION_KEY`（URL-safe Base64 编码的 32 字节随机值）。

初始化数据库：

```bash
alembic upgrade head
python -m scripts.create_admin_user --username admin
```

分别启动 API、Worker 和前端：

```bash
uvicorn apps.api.main:app --reload
python -m apps.worker.main
cd apps/web
npm ci
npm run dev
```

浏览器打开 `http://localhost:5173`。API 健康检查为
`http://localhost:8000/health`。

## Compose

在 `.env` 中额外设置：

```dotenv
POSTGRES_PASSWORD=请使用随机强密码
RAJ_SECRET_KEY=至少32字符的随机值
RAJ_CREDENTIAL_ENCRYPTION_KEY=URL-safe-Base64编码的32字节随机值
```

然后执行：

```bash
docker compose up --build -d
docker compose exec api python -m scripts.create_admin_user --username admin
```

页面默认发布在 `http://localhost:8080`。当前生产方案为直接以
`http://ECS公网IP:18080` 访问；该端口和直连 Cookie/CORS 策略由
`configs/deployments.local.yml` 的 `web` 配置统一生成。HTTP 会明文传输登录和来源配置凭据，
只应在受限网络中短期使用。

## 生产部署

Raj Data Handle 是单一、独立的 Compose 栈，目录固定为
`/opt/raj_data_handle`，数据库固定为该主机关联 RDS 中的 **`data_handle`**。
它不会读取、写入或迁移复审库 `review_recheck`，也不会复用复审系统的 Redis、容器、
卷或 80 端口。

生产部署请使用下列文件，而不要使用根目录的 `compose.yaml`（后者仅用于本地开发）：

- `deploy/compose.rajluck.yml`：不创建 PostgreSQL 容器，强制使用外部 RDS；当前直接访问
  时把页面绑定到 `0.0.0.0:18080`，不占用复审系统的 80 端口。
- `deploy/render_rajluck_env.py`：先校验本机 `configs/deployments.local.yml` 的唯一部署
  目标，再从未提交的私有 env 读取 RDS 账号密码，并从 YAML 生成 HTTP 端口与 CORS，渲染远端
  `.env`；拒绝非 `data_handle` 的数据库。
- `deploy/push-rajluck.sh`：本机发布入口，默认仅做配置校验和演练；只有显式传入
  `--remote-deploy` 才会连接主机。
- `deploy/deploy-rajluck.sh`：主机端应用发布入口；默认绝不执行 Alembic。

完整步骤、端口规划、验证和数据库变更门禁见
[docs/deployment-raj-data-handle.md](docs/deployment-raj-data-handle.md)。首次版本包含
数据库结构时，必须先按该文档完成 RDS 备份/回退确认，再单独执行 `--schema-only`；不能
把迁移混入应用发布。

## 验证

```bash
ruff check .
pytest
cd apps/web && npm run build
```

数据库结构变更通过 Alembic 管理；不要在应用启动时调用 `create_all()`。
