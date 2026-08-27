<script setup lang="ts">
import { ElMessage } from 'element-plus'

function saveHint() {
  ElMessage.info('系统参数接口将在后端设置模块接入后启用；修改默认值不会重算已确认历史台账。')
}
</script>

<template>
  <section>
    <div class="page-title-row"><div><h2>系统设置</h2><p class="page-subtitle">设置业务时区、默认费率、计算精度和上传限制。默认值只应用于新建记录。</p></div><div class="page-actions"><el-button type="primary" @click="saveHint">保存设置</el-button></div></div>
    <article class="panel panel--padded settings-grid">
      <el-form label-position="top"><h3>业务计算</h3><el-form-item label="业务时区"><el-select model-value="Asia/Shanghai" disabled><el-option label="Asia/Shanghai" value="Asia/Shanghai" /></el-select></el-form-item><el-form-item label="默认计算精度"><el-input model-value="2" disabled><template #append>位小数</template></el-input></el-form-item><el-form-item label="舍入方式"><el-input model-value="四舍五入（HALF_UP）" disabled /></el-form-item></el-form>
      <el-form label-position="top"><h3>导入与会话</h3><el-form-item label="单文件最大大小"><el-input model-value="10" disabled><template #append>MB</template></el-input></el-form-item><el-form-item label="允许扩展名"><el-input model-value=".xlsx" disabled /></el-form-item><el-form-item label="会话超时"><el-input model-value="30" disabled><template #append>分钟</template></el-input></el-form-item></el-form>
    </article>
    <el-alert type="info" :closable="false" show-icon>敏感参数（初始管理员、数据库密码、会话 Cookie）通过部署环境变量管理，不在浏览器配置页中展示。</el-alert>
  </section>
</template>

<style scoped>
.settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 42px; max-width: 860px; }.settings-grid h3 { margin: 0 0 20px; color: #344054; font-size: 15px; }.settings-grid :deep(.el-input), .settings-grid :deep(.el-select) { width: 100%; }
</style>
