<template>
  <section class="page" data-module="archive">
    <header class="page-head">
      <div>
        <h2>档案管理</h2>
        <p class="page-desc">按借阅状态分档管理设备档案：默认只列在库档案，借出中可查借阅人与借出日期，归还后自动移出借阅窗口。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记设备档案</button>
        <button class="btn" type="button" @click="exportRows">导出档案清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article
        v-for="item in stats"
        :key="item.status"
        class="stat-card stat-tab"
        :class="{ active: activeStatus === item.status }"
        role="button"
        tabindex="0"
        @click="switchStatus(item.status)"
        @keydown.enter="switchStatus(item.status)"
      >
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.count }}</strong>
      </article>
    </div>

    <div class="tab-bar" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.status"
        class="tab-item"
        :class="{ active: activeStatus === tab.status }"
        role="tab"
        type="button"
        @click="switchStatus(tab.status)"
      >
        {{ tab.label }}
        <span class="tab-count">{{ statusCount(tab.status) }}</span>
      </button>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>档案类别</span>
        <select v-model="category" :disabled="categoryLoading">
          <option value="">全部类别</option>
          <option v-for="name in categories" :key="name" :value="name">{{ name }}</option>
          <option v-if="category && !categories.includes(category)" :value="category">
            {{ category }}（清单未取到）
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>档案编号</span>
        <input v-model="keyword" placeholder="按档案编号检索" @keydown.enter.prevent="reload" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="lockedHint" class="locked-banner">
      <span>已锁定档案：{{ lockedHint }}</span>
      <button class="link" type="button" @click="focusLocked">回到锁定行</button>
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>缺失项</th>
          <th>可执行动作</th>
          <th>锁定</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in visibleRows"
          :key="String(row.id)"
          :ref="el => setRowRef(el as HTMLElement | null, row.id)"
          :class="{ 'locked-row': isLocked(row), 'flash-row': flashId === row.id, 'abnormal-row': row.has_missing }"
        >
          <td v-for="column in columns" :key="column">{{ formatCell(row, column) }}</td>
          <td :class="{ 'missing-text': row.has_missing }">{{ row['缺失项'] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actionsFor(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
          <td>
            <button class="link" type="button" @click="toggleLock(row)">
              {{ isLocked(row) ? '解锁' : '锁定本行' }}
            </button>
          </td>
        </tr>
        <tr v-if="!visibleRows.length">
          <td :colspan="columns.length + 3" class="empty-state">
            {{ activeStatus === '在库' ? '当前没有在库档案' : `没有符合条件的${activeStatus}档案` }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ activeStatus }}档案记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import { useSessionStore } from '@/stores/session'
import { request } from '@/api/client'

type Row = Record<string, string | number | null | boolean>

const ENDPOINT = '/api/archive'
const STORAGE_KEY = 'archive:pinned:v1'

const tabs = [
  { status: '在库', label: '在库' },
  { status: '借出中', label: '借出中（借阅窗口）' },
  { status: '已归还', label: '已归还' },
] as const
type TabStatus = (typeof tabs)[number]['status']

const baseColumns = ['档案编号', '所属设备', '档案类别', '归档日期']
const borrowColumns = ['借阅人', '借阅日期']
const returnedColumns = ['借阅人', '借阅日期', '归还日期']

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')

// 默认只列在库；分档与选中类别重新打开页面时仍然记住。
const activeStatus = ref<TabStatus>('在库')
const category = ref('')
const keyword = ref('')
const categories = ref<string[]>([])
const categoryLoading = ref(false)
const stats = ref<{ status: TabStatus; label: string; count: number }[]>(
  tabs.map(tab => ({ status: tab.status, label: tab.label, count: 0 })),
)

const lockedId = ref<number | null>(null)
const lockedSnapshot = ref<Row | null>(null)
const flashId = ref<number | null>(null)
const rowRefs = new Map<number, HTMLElement>()
let restored = false

const columns = computed(() => {
  if (activeStatus.value === '借出中') return [...baseColumns, ...borrowColumns]
  if (activeStatus.value === '已归还') return [...baseColumns, ...returnedColumns]
  return baseColumns
})

const visibleRows = computed<Row[]>(() => {
  if (lockedId.value === null) return rows.value
  // 锁定行只要还落在当前筛选结果里，就始终固定在首行，重新打开页面也不会跳走。
  const locked = rows.value.find(row => Number(row.id) === lockedId.value)
  if (!locked) return rows.value
  return [locked, ...rows.value.filter(row => Number(row.id) !== lockedId.value)]
})

const lockedHint = computed(() => {
  if (lockedId.value === null) return ''
  if (rows.value.some(row => Number(row.id) === lockedId.value)) return ''
  const snapshot = lockedSnapshot.value
  return snapshot ? `${String(snapshot['档案编号'] ?? lockedId.value)}（不在当前分档/筛选中）` : `#${lockedId.value}`
})

function statusCount(status: string) {
  return stats.value.find(item => item.status === status)?.count ?? 0
}

function isLocked(row: Row) {
  return Number(row.id) === lockedId.value
}

function formatCell(row: Row, column: string) {
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function actionsFor(row: Row) {
  switch (row.status) {
    case '在库':
      return ['办理借阅', '申请销毁']
    case '借出中':
      return ['登记归还', '申请销毁']
    default:
      return ['申请销毁']
  }
}

function setRowRef(el: HTMLElement | null, id: number | string | null | boolean) {
  const rowId = Number(id)
  if (el) rowRefs.set(rowId, el)
  else rowRefs.delete(rowId)
}

function persistState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      status: activeStatus.value,
      category: category.value,
      lockedId: lockedId.value,
    }))
  } catch {
    // 隐私模式等场景写不进本地存储时不影响正常使用
  }
}

function restoreState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw) as { status?: string; category?: string; lockedId?: number | null }
    if (saved.status && tabs.some(tab => tab.status === saved.status)) {
      activeStatus.value = saved.status as TabStatus
    }
    category.value = typeof saved.category === 'string' ? saved.category : ''
    lockedId.value = saved.lockedId === undefined ? null : Number(saved.lockedId)
  } catch {
    // 本地数据损坏时按默认分档打开
  }
}

function switchStatus(status: TabStatus) {
  activeStatus.value = status
  persistState()
  void reload()
}

function resetFilters() {
  category.value = ''
  keyword.value = ''
  persistState()
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '设备档案登记入口尚未接入审批流'
}

function toggleLock(row: Row) {
  if (isLocked(row)) {
    lockedId.value = null
    lockedSnapshot.value = null
  } else {
    lockedId.value = Number(row.id)
    lockedSnapshot.value = { ...row }
  }
  persistState()
}

async function focusLocked() {
  if (lockedId.value === null) return
  // 切到锁定行所在分档并放开类别筛选，再把行滚动到视口中央。
  const snapshot = lockedSnapshot.value
  if (snapshot && tabs.some(tab => tab.status === String(snapshot.status))) {
    activeStatus.value = String(snapshot.status) as TabStatus
  }
  category.value = ''
  keyword.value = ''
  persistState()
  await reload()
  await nextTick()
  scrollToLocked(true)
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const values: Record<string, string> = { action }
  if (action === '办理借阅') {
    // 借阅窗口必须登记借阅人；默认带出当前值班管理员。
    const borrower = window.prompt('请输入借阅人', session.operator)
    if (borrower === null) return
    const name = borrower.trim()
    if (!name) {
      errorMessage.value = '办理借阅必须登记借阅人'
      return
    }
    values['借阅人'] = name
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(values),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '档案动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '档案操作失败'
  }
}

// 类别清单取不到时再取一次重新定位；两次都失败才放行手工输入。
async function loadCategories(retry = true): Promise<void> {
  categoryLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/categories`)
    if (!response.ok) throw new Error(`接口返回 ${response.status}`)
    const payload = await response.json() as { items?: string[] }
    categories.value = payload.items ?? []
  } catch (error) {
    if (retry) {
      await loadCategories(false)
      return
    }
    errorMessage.value = `类别清单取不到，可手工输入类别检索（${error instanceof Error ? error.message : '请求失败'}）`
    categories.value = []
  } finally {
    categoryLoading.value = false
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const payload = await response.json() as { items?: { status: string; count: number }[] }
    for (const item of payload.items ?? []) {
      const target = stats.value.find(stat => stat.status === item.status)
      if (target) target.count = item.count
    }
  } catch {
    // 卡片数量读不出来不阻断列表使用
  }
}

function scrollToLocked(flash: boolean) {
  if (lockedId.value === null) return
  const el = rowRefs.get(lockedId.value)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  if (flash) {
    flashId.value = lockedId.value
    window.setTimeout(() => {
      if (flashId.value === lockedId.value) flashId.value = null
    }, 1600)
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams({ status: activeStatus.value })
  if (category.value) params.set('category', category.value)
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('设备档案列表读取失败')
    }
    const payload = await response.json() as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length

    // 归还/销毁后状态会变档：锁定行若已不在当前结果里，记下快照，便于回到它所在分档。
    if (lockedId.value !== null) {
      const inCurrent = rows.value.some(row => Number(row.id) === lockedId.value)
      if (!inCurrent) {
        try {
          const detail = await request(`${ENDPOINT}/${lockedId.value}`)
          if (detail.ok) lockedSnapshot.value = await detail.json() as Row
        } catch {
          // 行可能已被销毁，保留原快照即可
        }
      } else {
        const fresh = rows.value.find(row => Number(row.id) === lockedId.value)
        if (fresh) lockedSnapshot.value = { ...fresh }
      }
    }

    await nextTick()
    // 仅在重新打开页面恢复时自动滚动定位；之后的查询/换档只保持置顶，不抢滚动位置。
    if (restored && lockedId.value !== null && rows.value.some(row => Number(row.id) === lockedId.value)) {
      scrollToLocked(true)
    }
    restored = false
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '档案管理列表读取失败'
    restored = false
  }
}

onMounted(async () => {
  restoreState()
  // 重新打开页面且本地记住了锁定行时，首次加载完成自动滚动到该行。
  restored = lockedId.value !== null
  await Promise.all([loadCategories(), loadStats(), reload()])
})
</script>
