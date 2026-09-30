<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Bell,
  DataAnalysis,
  DocumentChecked,
  Files,
  Ticket,
  Connection,
  HomeFilled,
  Setting,
  Shop,
  SwitchButton,
  UserFilled,
  User,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const collapsed = ref(false)

const title = computed(() => String(route.meta.title || 'Raj ERP'))
const userInitial = computed(() => (session.user?.displayName || session.user?.username || 'U').slice(0, 1).toUpperCase())

async function logout() {
  await ElMessageBox.confirm('确定退出当前登录吗？', '退出登录', { type: 'warning', confirmButtonText: '退出', cancelButtonText: '取消' })
  await session.logout()
  ElMessage.success('已安全退出')
  await router.replace({ name: 'login' })
}
</script>

<template>
  <el-container class="app-shell">
    <el-aside class="app-aside" :width="collapsed ? '72px' : '236px'">
      <div class="brand">
        <div class="brand-mark">R</div>
        <div v-show="!collapsed" class="brand-copy">
          <strong>Raj ERP</strong>
          <span>企业业务控制台</span>
        </div>
      </div>

      <el-menu class="side-menu" :collapse="collapsed" :collapse-transition="false" :default-active="route.path" :default-openeds="['ads-balance']" router>
        <el-menu-item index="/dashboard"><el-icon><HomeFilled /></el-icon><template #title>工作台</template></el-menu-item>
        <el-sub-menu index="ads-balance" popper-class="side-menu-popper">
          <template #title><el-icon><DataAnalysis /></el-icon><span>业务管理</span></template>
          <el-menu-item index="/operators"><el-icon><Shop /></el-icon><template #title>投放公司与投放线</template></el-menu-item>
          <el-menu-item index="/balances"><el-icon><DocumentChecked /></el-icon><template #title>输入台账</template></el-menu-item>
          <el-menu-item index="/imports"><el-icon><Files /></el-icon><template #title>导入中心</template></el-menu-item>
          <el-menu-item index="/redemption"><el-icon><Ticket /></el-icon><template #title>兑换码管理</template></el-menu-item>
          <el-menu-item index="/reports"><el-icon><DataAnalysis /></el-icon><template #title>汇总报表</template></el-menu-item>
          <el-menu-item index="/audit"><el-icon><Bell /></el-icon><template #title>审计日志</template></el-menu-item>
        </el-sub-menu>
        <div v-show="!collapsed" class="menu-caption">系统管理</div>
        <el-menu-item index="/users"><el-icon><UserFilled /></el-icon><template #title>用户与权限</template></el-menu-item>
        <el-menu-item index="/settings"><el-icon><Setting /></el-icon><template #title>系统设置</template></el-menu-item>
        <el-menu-item index="/remote-connections"><el-icon><Connection /></el-icon><template #title>远端连接</template></el-menu-item>
      </el-menu>

      <button class="collapse-button" :aria-label="collapsed ? '展开导航' : '收起导航'" @click="collapsed = !collapsed">
        <span>{{ collapsed ? '›' : '‹' }}</span>
      </button>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <div>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>Raj ERP</el-breadcrumb-item>
            <el-breadcrumb-item>{{ title }}</el-breadcrumb-item>
          </el-breadcrumb>
          <h1>{{ title }}</h1>
        </div>
        <div class="header-actions">
          <el-tag v-if="session.demoMode" type="warning" effect="light" round>演示数据模式</el-tag>
          <span class="business-time">业务时区：Asia/Shanghai</span>
          <el-dropdown trigger="click">
            <button class="user-menu">
              <el-avatar :size="32" class="user-avatar">{{ userInitial }}</el-avatar>
              <span>{{ session.user?.displayName || session.user?.username }}</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :icon="User">个人资料</el-dropdown-item>
                <el-dropdown-item divided :icon="SwitchButton" @click="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="app-main">
        <el-alert v-if="session.demoMode" class="demo-alert" type="warning" :closable="false" show-icon>
          后端暂不可达，当前页面使用演示数据；录入、导入和保存不会写入正式账本。
        </el-alert>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
