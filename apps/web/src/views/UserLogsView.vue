<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { fetchUsers, queryUserLogs } from '../api/auth'
import { apiErrorMessage } from '../api/client'
import type { UserLogEventType, UserLogQueryResponse, UserRecord } from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const usersLoading = ref(false)
const users = ref<UserRecord[]>([])
const response = ref<UserLogQueryResponse | null>(null)
const page = ref(1)
const pageSize = ref(50)

const filters = reactive({
  userId: undefined as number | undefined,
  eventTypes: [] as UserLogEventType[],
  occurredRange: recentSevenDayRange() as [Date, Date] | [],
})

const eventOptions: Array<{ value: UserLogEventType; label: string }> = [
  { value: 'login', label: '登录' },
  { value: 'access', label: '访问页面' },
]

function recentSevenDayRange(): [Date, Date] {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - 6)
  start.setHours(0, 0, 0, 0)
  return [start, end]
}

function toIso(value: Date | undefined): string | undefined {
  return value?.toISOString()
}

function eventLabel(value: UserLogEventType): string {
  return eventOptions.find((option) => option.value === value)?.label || value
}

function eventTagType(value: UserLogEventType): 'success' | 'primary' {
  return value === 'login' ? 'success' : 'primary'
}

async function loadUsers(): Promise<void> {
  usersLoading.value = true
  try {
    users.value = await fetchUsers()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '用户列表加载失败。'))
  } finally {
    usersLoading.value = false
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    response.value = await queryUserLogs({
      userId: filters.userId,
      eventTypes: filters.eventTypes.length ? filters.eventTypes : undefined,
      startedAt: toIso(filters.occurredRange[0]),
      endedAt: toIso(filters.occurredRange[1]),
      page: page.value,
      pageSize: pageSize.value,
    })
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '操作审计加载失败。'))
  } finally {
    loading.value = false
  }
}

function search(): void {
  page.value = 1
  void load()
}

function reset(): void {
  filters.userId = undefined
  filters.eventTypes = []
  filters.occurredRange = recentSevenDayRange()
  page.value = 1
  void load()
}

function pageChanged(nextPage: number): void {
  page.value = nextPage
  void load()
}

function pageSizeChanged(nextPageSize: number): void {
  pageSize.value = nextPageSize
  page.value = 1
  void load()
}

onMounted(() => {
  void Promise.all([loadUsers(), load()])
})
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Activity audit</span>
        <h1>操作审计</h1>
        <p>记录成功登录与系统页面访问；仅管理员可查看。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <section class="surface-card user-log-filters">
      <el-form label-position="top" class="user-log-filters__grid" @submit.prevent="search">
        <el-form-item label="用户">
          <el-select
            v-model="filters.userId"
            clearable
            filterable
            :loading="usersLoading"
            placeholder="全部用户"
          >
            <el-option
              v-for="user in users"
              :key="user.id"
              :label="`${user.displayName}（${user.username}）`"
              :value="user.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="日志类型">
          <el-select v-model="filters.eventTypes" multiple clearable placeholder="全部类型">
            <el-option
              v-for="option in eventOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="发生时间（北京时间）" class="user-log-filters__time">
          <el-date-picker
            v-model="filters.occurredRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            :default-time="[new Date(2000, 0, 1, 0, 0, 0), new Date(2000, 0, 1, 23, 59, 59)]"
          />
        </el-form-item>
        <div class="user-log-filters__actions">
          <el-button @click="reset">重置</el-button>
          <el-button type="primary" :icon="Search" :loading="loading" @click="search">查询</el-button>
        </div>
      </el-form>
    </section>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="response?.items || []" empty-text="当前筛选条件下暂无操作记录">
        <el-table-column label="用户" min-width="190">
          <template #default="{ row }">
            <strong>{{ row.displayName || '历史用户' }}</strong>
            <small class="user-log-username">{{ row.username || '—' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="日志类型" width="130">
          <template #default="{ row }">
            <el-tag :type="eventTagType(row.eventType)">{{ eventLabel(row.eventType) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="访问页面" min-width="260">
          <template #default="{ row }">
            <code v-if="row.path" class="user-log-path">{{ row.path }}</code>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="发生时间（北京时间）" min-width="210">
          <template #default="{ row }">{{ formatDateTime(row.occurredAt) }}</template>
        </el-table-column>
      </el-table>
      <div class="user-log-pagination">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="response?.total || 0"
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          @update:current-page="pageChanged"
          @update:page-size="pageSizeChanged"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.user-log-filters {
  padding: 18px 20px 4px;
}

.user-log-filters__grid {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) minmax(280px, 1.4fr) auto;
  gap: 0 14px;
  align-items: end;
}

.user-log-filters :deep(.el-select),
.user-log-filters :deep(.el-date-editor) {
  width: 100%;
}

.user-log-filters__actions {
  display: flex;
  gap: 10px;
  padding-bottom: 18px;
}

.user-log-username {
  display: block;
  margin-top: 3px;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 500;
}

.user-log-path {
  color: var(--ink);
  font-size: 12px;
}

.user-log-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px;
}

@media (max-width: 880px) {
  .user-log-filters__grid {
    grid-template-columns: 1fr 1fr;
  }

  .user-log-filters__time {
    grid-column: span 2;
  }

  .user-log-filters__actions {
    justify-content: flex-end;
  }
}

@media (max-width: 580px) {
  .user-log-filters__grid {
    grid-template-columns: 1fr;
  }

  .user-log-filters__time {
    grid-column: auto;
  }

  .user-log-filters__actions,
  .user-log-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
}
</style>
