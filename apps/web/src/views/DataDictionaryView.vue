<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchPaymentChannelNames } from '../api/dataDictionaries'
import { fetchAllSources } from '../api/sources'
import type { DataDictionaryEntry, SourceConfig } from '../types'
import { formatDateTime } from '../ui'

const activeTab = ref('payment-channel-names')
const loading = ref(false)
const entries = ref<DataDictionaryEntry[]>([])
const sources = ref<SourceConfig[]>([])
const page = ref(1)
const pageSize = ref(20)
const filters = reactive({
  keyword: '',
  sourceId: '',
  status: 'active' as 'active' | 'inactive' | 'all',
})

const filteredEntries = computed(() => {
  const keyword = filters.keyword.trim().toLocaleLowerCase()
  return entries.value.filter((entry) => {
    if (filters.sourceId && entry.sourceId !== filters.sourceId) return false
    if (filters.status === 'active' && !entry.active) return false
    if (filters.status === 'inactive' && entry.active) return false
    if (
      keyword &&
      !entry.entryLabel.toLocaleLowerCase().includes(keyword) &&
      !entry.entryCode.toLocaleLowerCase().includes(keyword)
    ) {
      return false
    }
    return true
  })
})

const pagedEntries = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredEntries.value.slice(start, start + pageSize.value)
})

const activeEntryCount = computed(
  () => entries.value.filter((entry) => entry.active).length,
)
const sourceCount = computed(
  () => new Set(entries.value.map((entry) => entry.sourceId)).size,
)
const latestSyncAt = computed(() => {
  const timestamps = entries.value
    .map((entry) => Date.parse(entry.updatedAt))
    .filter(Number.isFinite)
  return timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const [dictionaryEntries, availableSources] = await Promise.all([
      fetchPaymentChannelNames(),
      fetchAllSources(),
    ])
    entries.value = dictionaryEntries
    sources.value = availableSources
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '数据字典加载失败。'))
  } finally {
    loading.value = false
  }
}

watch(
  () => [filters.keyword, filters.sourceId, filters.status],
  () => {
    page.value = 1
  },
)

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Data dictionaries</span>
        <h1>数据字典</h1>
        <p>查看从各盘口远端接口同步并保存在本地数据库中的稳定枚举值。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新本地数据</el-button>
    </header>

    <el-alert
      title="字典由盘口连接测试同步"
      description="连接测试成功后，系统从充值订单模块的“支付渠道名称”接口读取完整 label/value；远端不再返回的条目会保留并标记为停用。"
      type="info"
      show-icon
      :closable="false"
    />

    <section v-loading="loading" class="surface-card dictionary-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="支付渠道名称" name="payment-channel-names">
          <div class="summary-grid">
            <article>
              <span>有效条目</span>
              <strong>{{ activeEntryCount }}</strong>
            </article>
            <article>
              <span>已同步盘口</span>
              <strong>{{ sourceCount }}</strong>
            </article>
            <article>
              <span>最近同步</span>
              <strong>{{ latestSyncAt ? formatDateTime(latestSyncAt) : '尚未同步' }}</strong>
            </article>
          </div>

          <div class="dictionary-toolbar">
            <el-input
              v-model="filters.keyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜索渠道名称或 ID"
            />
            <el-select v-model="filters.sourceId" placeholder="全部盘口">
              <el-option label="全部盘口" value="" />
              <el-option
                v-for="source in sources"
                :key="source.sourceId"
                :label="source.displayName"
                :value="source.sourceId"
              />
            </el-select>
            <el-segmented
              v-model="filters.status"
              :options="[
                { label: '有效', value: 'active' },
                { label: '停用', value: 'inactive' },
                { label: '全部', value: 'all' },
              ]"
            />
          </div>

          <el-table :data="pagedEntries" stripe>
            <el-table-column label="支付渠道名称" min-width="260">
              <template #default="{ row }">
                <strong class="entry-label">{{ row.entryLabel }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="渠道 ID" width="150">
              <template #default="{ row }">
                <el-tag effect="plain">{{ row.entryCode }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="来源盘口" min-width="190">
              <template #default="{ row }">
                <div class="source-cell">
                  <strong>{{ row.sourceDisplayName }}</strong>
                  <span>{{ row.sourceId }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.active ? 'success' : 'info'">
                  {{ row.active ? '有效' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最近同步" min-width="190">
              <template #default="{ row }">
                {{ formatDateTime(row.updatedAt) }}
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无支付渠道名称字典">
                <span class="empty-help">请先到“盘口配置”完成一次连接测试。</span>
              </el-empty>
            </template>
          </el-table>

          <div v-if="filteredEntries.length" class="pagination-row">
            <span>共 {{ filteredEntries.length }} 条</span>
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              :total="filteredEntries.length"
              layout="sizes, prev, pager, next"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<style scoped>
.dictionary-card {
  padding: 8px 24px 24px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin: 14px 0 22px;
}

.summary-grid article {
  display: grid;
  gap: 7px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #f8fbfd;
}

.summary-grid span,
.source-cell span,
.pagination-row,
.empty-help {
  color: var(--ink-muted);
}

.summary-grid span,
.source-cell span,
.empty-help {
  font-size: 12px;
}

.summary-grid strong {
  color: var(--ink-strong);
  font-size: 20px;
}

.dictionary-toolbar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 220px auto;
  gap: 12px;
  margin-bottom: 18px;
}

.entry-label {
  color: var(--ink-strong);
}

.source-cell {
  display: grid;
  gap: 2px;
}

.pagination-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 18px;
}

.empty-help {
  display: block;
}

@media (max-width: 900px) {
  .summary-grid,
  .dictionary-toolbar {
    grid-template-columns: 1fr;
  }

  .pagination-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
