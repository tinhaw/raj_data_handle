<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const title = computed(() => String(route.meta.title || 'ERP 业务模块'))
const description = computed(() =>
  String(route.meta.migrationDescription || '该 ERP 页面将迁入当前 Raj Data 项目。'),
)
const isRemoteConnectionPage = computed(() => route.meta.navKey === '/erp/remote-connections')
</script>

<template>
  <div class="page-stack erp-migration-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">ERP module migration</span>
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
    </header>

    <el-alert
      title="页面路由已迁入当前项目"
      description="此阶段只完成菜单、路由和页面归属整理。原 ERP 的接口、权限模型和写入能力尚未启用；当前页面不会执行本地写入、数据库迁移或远端业务操作。"
      type="info"
      show-icon
      :closable="false"
    />

    <section v-if="isRemoteConnectionPage" class="surface-card erp-migration-card">
      <h2>统一远端账号体系</h2>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="管理入口">“远端账号与盘口”是唯一账号管理入口，继承现有数据分析配置。</el-descriptions-item>
        <el-descriptions-item label="账号关系">账号归属一个盘口；同一账号可被明确授予分析读取或 ERP 兑换等能力。</el-descriptions-item>
        <el-descriptions-item label="权限边界">账号共用不代表权限共用；分析链路保持只读，ERP 远端操作仍需单独授权。</el-descriptions-item>
      </el-descriptions>
    </section>

    <section class="surface-card erp-migration-card">
      <h2>后续迁移顺序</h2>
      <ol>
        <li>迁入原 ERP 页面组件与交互，保持当前导航路径不变。</li>
        <li>在当前项目中实现对应 API、权限和审计模型，并把 ERP 能力接入统一远端账号体系。</li>
        <li>单独批准数据库结构与数据迁移后，再启用本地写入；远端业务操作需再次单独授权。</li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.erp-migration-page {
  max-width: 980px;
  margin: 0 auto;
}

.erp-migration-card {
  padding: 24px;
}

.erp-migration-card h2 {
  margin: 0 0 14px;
  color: var(--ink-strong);
  font-size: 18px;
}

.erp-migration-card ol {
  display: grid;
  gap: 10px;
  margin: 0;
  padding-left: 22px;
  color: var(--ink);
  line-height: 1.65;
}
</style>
