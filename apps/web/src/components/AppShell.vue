<script setup lang="ts">
import {
  Bell,
  Collection,
  DataAnalysis,
  Setting,
  SwitchButton,
  User,
  Wallet,
} from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchUnreadNotifications, markNotificationRead } from '../api/notifications'
import { clearSession, currentUser, isAdmin } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const delivered = new Set<string>()
const currentTime = ref(new Date())
let timer: number | undefined
let clockTimer: number | undefined

const activeMenu = computed(() => String(route.meta.navKey || route.path))
const beijingTime = computed(() => formatTime('Asia/Shanghai'))
const indiaTime = computed(() => formatTime('Asia/Kolkata'))

function formatTime(timeZone: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(currentTime.value)
}

async function signOut(): Promise<void> {
  await clearSession()
  await router.replace('/login')
}

async function pollNotifications(): Promise<void> {
  if (!currentUser.value) return
  try {
    const rows = await fetchUnreadNotifications()
    for (const item of rows.slice().reverse()) {
      if (delivered.has(item.id)) continue
      delivered.add(item.id)
      const instance = ElNotification({
        title: item.title,
        message: `批次 ${item.batchId.slice(0, 8)} · 执行版本 V${item.runVersion}`,
        type: item.eventType === 'batch_completed' ? 'success' : 'warning',
        duration: 0,
        position: 'bottom-right',
        onClick: () => {
          void router.push(`/batches/${item.batchId}`)
          instance.close()
        },
        onClose: () => {
          void markNotificationRead(item.id)
        },
      })
    }
  } catch {
    // Session and network errors are handled by page navigation or the next poll.
  }
}

onMounted(() => {
  currentTime.value = new Date()
  clockTimer = window.setInterval(() => {
    currentTime.value = new Date()
  }, 1_000)
  void pollNotifications()
  timer = window.setInterval(pollNotifications, 15_000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  if (clockTimer) window.clearInterval(clockTimer)
})
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell--collapsed': collapsed }">
    <aside class="side-nav">
      <button class="brand" type="button" @click="collapsed = !collapsed">
        <span class="brand-mark">R</span>
        <span v-if="!collapsed" class="brand-copy">
          <strong>RAJ DATA</strong>
          <small>对账分析中心</small>
        </span>
      </button>

      <section v-if="!collapsed" class="time-panel" aria-label="当前时间">
        <span class="time-panel__eyebrow">CURRENT TIME</span>
        <div class="time-card">
          <span>北京时间</span>
          <strong>{{ beijingTime }}</strong>
        </div>
        <div class="time-card">
          <span>印度时间</span>
          <strong>{{ indiaTime }}</strong>
        </div>
      </section>

      <el-menu :default-active="activeMenu" router :collapse="collapsed">
        <el-menu-item index="/batches">
          <el-icon><DataAnalysis /></el-icon>
          <template #title>充值订单</template>
        </el-menu-item>
        <el-menu-item index="/withdraw-orders">
          <el-icon><Wallet /></el-icon>
          <template #title>提现订单</template>
        </el-menu-item>
        <el-menu-item index="/settings/system">
          <el-icon><Setting /></el-icon>
          <template #title>系统配置</template>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/settings/sources">
          <el-icon><Setting /></el-icon>
          <template #title>盘口配置</template>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/settings/data-dictionaries">
          <el-icon><Collection /></el-icon>
          <template #title>数据字典</template>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/settings/users">
          <el-icon><User /></el-icon>
          <template #title>用户管理</template>
        </el-menu-item>
      </el-menu>

      <div class="side-footer">
        <el-icon><Bell /></el-icon>
        <div v-if="!collapsed">
          <strong>{{ currentUser?.displayName }}</strong>
          <span>{{ isAdmin ? '管理员' : '业务用户' }}</span>
        </div>
        <el-button text circle :icon="SwitchButton" title="退出登录" @click="signOut" />
      </div>
    </aside>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  background: var(--page-bg);
  transition: grid-template-columns 0.2s ease;
}

.app-shell--collapsed {
  grid-template-columns: 76px minmax(0, 1fr);
}

.side-nav {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #f7fbff;
  background:
    radial-gradient(circle at 20% 0%, rgba(42, 157, 143, 0.26), transparent 32%),
    linear-gradient(180deg, #102a43 0%, #0b1f33 100%);
  box-shadow: 8px 0 30px rgba(16, 42, 67, 0.12);
}

.brand {
  height: 86px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.brand-mark {
  flex: 0 0 40px;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 13px;
  color: #102a43;
  background: #e9c46a;
  font-size: 21px;
  font-weight: 900;
}

.brand-copy {
  display: grid;
  gap: 2px;
  white-space: nowrap;
}

.brand-copy strong {
  letter-spacing: 0.08em;
}

.brand-copy small {
  color: rgba(255, 255, 255, 0.62);
}

.time-panel {
  display: grid;
  gap: 8px;
  margin: 0 14px 10px;
  padding: 14px;
  border: 1px solid rgba(233, 196, 106, 0.2);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.06);
}

.time-panel__eyebrow {
  color: rgba(255, 255, 255, 0.58);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.time-card {
  display: grid;
  gap: 2px;
  padding: 10px 11px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  background: rgba(11, 31, 51, 0.32);
}

.time-card span {
  color: rgba(255, 255, 255, 0.65);
  font-size: 12px;
  font-weight: 700;
}

.time-card strong {
  color: #fff;
  font-size: 23px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  line-height: 1.1;
}

.side-nav :deep(.el-menu) {
  flex: 1;
  border-right: 0;
  background: transparent;
}

.side-nav :deep(.el-menu-item) {
  margin: 5px 10px;
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.68);
}

.side-nav :deep(.el-menu-item:hover),
.side-nav :deep(.el-menu-item.is-active) {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}

.side-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.side-footer > div {
  min-width: 0;
  flex: 1;
  display: grid;
}

.side-footer strong,
.side-footer span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-footer span {
  color: rgba(255, 255, 255, 0.58);
  font-size: 12px;
}

.side-footer :deep(.el-button) {
  color: rgba(255, 255, 255, 0.72);
}

.app-main {
  min-width: 0;
  padding: 28px;
}

@media (max-width: 860px) {
  .app-shell,
  .app-shell--collapsed {
    grid-template-columns: 76px minmax(0, 1fr);
  }

  .app-main {
    padding: 18px;
  }

  .brand-copy,
  .side-footer > div,
  .time-panel {
    display: none;
  }
}
</style>
