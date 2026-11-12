# 任务明细独立页面与删除恢复：生产发布记录

2026-11-13 已完成 production 发布，目标 analysis.ailuckdg.com / ECS 8.217.194.158 / /opt/raj_data_handle / Compose raj-data-handle / RDS data_handle。

代码提交：9d185f9 记录此前已上线的生产源码基线；db37b29 提交独立明细页、所选配置删除范围、删除恢复及任务级同码一次确认。本机其他未发布修改保留，未作为此次发布内容。

从新鲜生产源码限定合并；保留已上线的列表摘要接口、显式历史所有者选择、库存代际隔离及未知请求保护。17 个发布源文件与提交及生产源文件摘要核对一致。官方 push-rajluck.sh --upload-source --stage-only 暂存，deploy-rajluck.sh --skip-git --build-only 预构建，最终由 deploy-rajluck.sh --skip-git 发布。未执行迁移，结构保持 20261113_0061。

维护窗口（UTC+08）：05:22:08 至 05:23:50，共 102 秒。旧源码、运行环境、六个回退镜像及 12 张 ERP 表加密备份位于 /opt/raj_data_handle/release-backups/20261113-redemption-task-detail；备份解密和摘要验证通过，停写后补最终快照。发布时及浏览器验收后，95,303 条历史记录、9 个保护函数、原约束及账号能力完全一致。未触发回退，数据库未降级或覆盖。

最终 Java 报告 270 项、失败 0，前端行为 49 项通过；主前端、ERP 前端和生产镜像构建通过。全量运行发现两条库存测试仍使用 0061 以前的跨所有者唯一性假设，修正为按代际区分、同所有者仍禁止重复后，31 项身份测试重跑通过；初次失败及复测日志均保留。

发布后六个容器运行，四个配置健康检查全部 healthy，公网 /health 为 ok。Chrome 实际打开任务 202611130005，独立路径 /erp/redemption/83 可访问；四盘口标签、配置列表、完整行展开及两条勾选入口正常。选择 RajLuck 后刷新，仍停留 batch=139。只读打开删除进度显示没有记录，未建立新的删除计划。验收后清空选择，未提交创建、重试、发布、奖励修改或删除；任务 202611130004 未重建。

本次未进行真实删除或实际中断删除的生产演练；该执行路径由 HTTP/数据库与前端行为回归覆盖。保留执行器独立权限、共享范围确认、未知结果只读核对及防重放限制。

审计材料：output/releases/redemption-task-detail-20261113/，包含 manifest.json、validation.json、备份/预构建/发布/核验日志及 production-detail.jpg。
