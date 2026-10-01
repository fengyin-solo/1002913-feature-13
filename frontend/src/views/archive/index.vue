<template>
  <section class="page" data-module="archive">
    <header class="page-head">
      <div>
        <h2>档案管理管理</h2>
        <p class="page-desc">按借阅状态分档维护设备档案：默认只看在库，切到借出中可核对借阅人与借出日期，归还后自动移出借出窗口。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记设备档案</button>
        <button class="btn" type="button" @click="exportRows">导出档案管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article
        v-for="item in tabCards"
        :key="item.key"
        class="stat-card"
        :class="{ active: activeTab === item.key }"
        role="button"
        tabindex="0"
        @click="switchTab(item.key)"
        @keyup.enter="switchTab(item.key)"
      >
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="status-tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        role="tab"
        class="tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </button>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>档案类别</span>
        <select v-if="!categoryFailed" v-model="categoryFilter">
          <option value="">全部类别</option>
          <option v-for="name in categoryOptions" :key="name" :value="name">{{ name }}</option>
        </select>
        <input v-else v-model="categoryFilter" list="archive-category-options" placeholder="清单未取到，直接输入类别" />
        <datalist id="archive-category-options">
          <option v-for="name in categories" :key="name" :value="name"></option>
        </datalist>
      </label>
      <label class="filter-item">
        <span>档案编号</span>
        <input v-model="keyword" placeholder="按档案编号检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="categoryFailed" class="warn-text">{{ categoryError }}</p>
    <p v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in activeColumns" :key="column.key">{{ column.label }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :id="`archive-row-${row.id}`"
          :key="String(row.id)"
          :class="{
            'locked-row': lockedId === row.id,
            'flash-row': flashId === row.id,
          }"
        >
          <td v-for="column in activeColumns" :key="column.key">
            <template v-if="column.key === '缺失项'">
              <span v-if="(row.缺失项 ?? []).length" class="missing-tag">
                缺少：{{ (row.缺失项 ?? []).join('、') }}
              </span>
              <span v-else>—</span>
            </template>
            <template v-else>{{ displayValue(row, column.key) }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actionsFor(activeTab)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link lock-link" type="button" @click="toggleLock(row)">
              {{ lockedId === row.id ? '取消锁定' : '锁定此行' }}
            </button>
            <span v-if="!actionsFor(activeTab).length">仅可锁定定位</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="activeColumns.length + 1" class="empty-state">
            {{ activeTab === '在库' ? '当前没有在库档案' : `没有「${activeTab}」状态的档案` }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ activeTab }}档案<template v-if="lockedId !== null">，已锁定档案「{{ lockedCode }}」</template></span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type StatusKey = '在库' | '借出中' | '已归还' | '已销毁'

interface ArchiveRow {
  id: number
  档案编号: string
  所属设备: string
  档案类别: string
  归档日期: string | null
  借阅人: string | null
  借阅日期: string | null
  归还日期: string | null
  档案状态: StatusKey
  缺失项: string[]
}

interface Column {
  key: keyof ArchiveRow
  label: string
}

const ENDPOINT = '/api/archive'
const TAB_KEY = 'archive:statusTab'
const CATEGORY_KEY = 'archive:category'
const LOCK_KEY = 'archive:lockedId'
const VALID_TABS: StatusKey[] = ['在库', '借出中', '已归还', '已销毁']

const tabs: { key: StatusKey; label: string }[] = [
  { key: '在库', label: '在库' },
  { key: '借出中', label: '借出中' },
  { key: '已归还', label: '已归还' },
  { key: '已销毁', label: '已销毁' },
]

const COLUMNS_BY_TAB: Record<StatusKey, Column[]> = {
  在库: [
    { key: '档案编号', label: '档案编号' },
    { key: '所属设备', label: '所属设备' },
    { key: '档案类别', label: '档案类别' },
    { key: '归档日期', label: '归档日期' },
    { key: '缺失项', label: '缺失项' },
  ],
  借出中: [
    { key: '档案编号', label: '档案编号' },
    { key: '所属设备', label: '所属设备' },
    { key: '档案类别', label: '档案类别' },
    { key: '借阅人', label: '借阅人' },
    { key: '借阅日期', label: '借出日期' },
    { key: '缺失项', label: '缺失项' },
  ],
  已归还: [
    { key: '档案编号', label: '档案编号' },
    { key: '所属设备', label: '所属设备' },
    { key: '档案类别', label: '档案类别' },
    { key: '借阅人', label: '借阅人' },
    { key: '借阅日期', label: '借出日期' },
    { key: '归还日期', label: '归还日期' },
    { key: '缺失项', label: '缺失项' },
  ],
  已销毁: [
    { key: '档案编号', label: '档案编号' },
    { key: '所属设备', label: '所属设备' },
    { key: '档案类别', label: '档案类别' },
    { key: '归档日期', label: '归档日期' },
    { key: '缺失项', label: '缺失项' },
  ],
}

const ACTIONS_BY_TAB: Record<StatusKey, string[]> = {
  在库: ['办理借阅', '申请销毁'],
  借出中: ['登记归还'],
  已归还: ['办理借阅', '申请销毁'],
  已销毁: [],
}

const rows = ref<ArchiveRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const categoryFilter = ref('')
const activeTab = ref<StatusKey>('在库')
const categories = ref<string[]>([])
const categoryFailed = ref(false)
const categoryError = ref('')
const statusCounts = ref<Record<StatusKey, number>>({ 在库: 0, 借出中: 0, 已归还: 0, 已销毁: 0 })
const lockedId = ref<number | null>(null)
const lockedCode = ref('')
const flashId = ref<number | null>(null)

const activeColumns = computed<Column[]>(() => COLUMNS_BY_TAB[activeTab.value])
const actionsFor = (tab: StatusKey) => ACTIONS_BY_TAB[tab]

const tabCards = computed(() => [
  { key: '在库' as StatusKey, label: '在库档案', value: statusCounts.value.在库 },
  { key: '借出中' as StatusKey, label: '借出档案', value: statusCounts.value.借出中 },
  { key: '已归还' as StatusKey, label: '已归还档案', value: statusCounts.value.已归还 },
  { key: '已销毁' as StatusKey, label: '已销毁档案', value: statusCounts.value.已销毁 },
])

// 下拉清单取不到本次值时，仍把已记住的类别顶在选项里，避免筛选被悄悄冲掉。
const categoryOptions = computed(() => {
  const remembered = categoryFilter.value
  if (remembered && !categories.value.includes(remembered)) {
    return [remembered, ...categories.value]
  }
  return categories.value
})

function displayValue(row: ArchiveRow, key: keyof ArchiveRow): string {
  const value = row[key]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function switchTab(tab: StatusKey) {
  if (tab === activeTab.value) return
  activeTab.value = tab
  localStorage.setItem(TAB_KEY, tab)
  noticeMessage.value = ''
  void reload()
}

function resetFilters() {
  keyword.value = ''
  categoryFilter.value = ''
  localStorage.removeItem(CATEGORY_KEY)
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '设备档案登记入口尚未接入审批流'
}

function toggleLock(row: ArchiveRow) {
  if (lockedId.value === row.id) {
    lockedId.value = null
    lockedCode.value = ''
    localStorage.removeItem(LOCK_KEY)
  } else {
    lockedId.value = row.id
    lockedCode.value = row.档案编号
    localStorage.setItem(LOCK_KEY, String(row.id))
    void locateRow(row.id)
  }
}

async function locateRow(id: number) {
  await nextTick()
  const el = document.getElementById(`archive-row-${id}`)
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    flashId.value = id
    window.setTimeout(() => {
      if (flashId.value === id) flashId.value = null
    }, 2000)
  }
}

async function runAction(action: string, row: ArchiveRow) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const values: Record<string, string> = { action }
    if (action === '办理借阅') {
      const borrower = window.prompt(`办理借阅「${row.档案编号}」，请填写借阅人：`)
      if (borrower === null) return
      const name = borrower.trim()
      if (!name) {
        errorMessage.value = '办理借阅必须填写借阅人'
        return
      }
      values.借阅人 = name
    }
    if (action === '申请销毁' && !window.confirm(`确认对「${row.档案编号}」申请销毁？销毁后不可再借阅。`)) {
      return
    }
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, values }),
    })
    const payload = (await response.json().catch(() => null)) as
      | { ok?: boolean; message?: string; entry?: ArchiveRow }
      | null
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '档案动作未生效，请稍后重试')
    }
    // 锁定行发生状态流转时，跟着它的新状态换档，保证锁定的那一行始终在眼前。
    if (lockedId.value === row.id) {
      const moved = payload?.entry
      if (moved?.档案状态 && moved.档案状态 !== activeTab.value) {
        activeTab.value = moved.档案状态
        localStorage.setItem(TAB_KEY, moved.档案状态)
      }
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '档案管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  localStorage.setItem(TAB_KEY, activeTab.value)
  localStorage.setItem(CATEGORY_KEY, categoryFilter.value)
  const params = new URLSearchParams({
    status: activeTab.value,
    size: '200',
  })
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (categoryFilter.value) params.set('category', categoryFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('设备档案列表读取失败')
    }
    const payload = (await response.json()) as { items?: ArchiveRow[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '档案管理列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      statusCounts.value = (await response.json()) as Record<StatusKey, number>
    }
  } catch {
    // 计数取不到不阻塞列表，保留上一次的计数。
  }
}

async function loadCategories() {
  // 清单取不到时只再取一次；两次都失败就退化为手工输入，并保留已记住的类别。
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await request(`${ENDPOINT}/categories`)
      if (!response.ok) throw new Error(`类别清单返回 ${response.status}`)
      const payload = (await response.json()) as { items?: string[] }
      categories.value = payload.items ?? []
      categoryFailed.value = false
      categoryError.value = ''
      return
    } catch (error) {
      if (attempt === 0) continue
      categoryFailed.value = true
      const detail = error instanceof Error ? error.message : '请求未送达'
      categoryError.value = `档案类别清单取不到（${detail}），已重试一次；可直接输入类别检索。`
    }
  }
}

async function restoreLockedRow(): Promise<number | null> {
  const stored = localStorage.getItem(LOCK_KEY)
  if (!stored) return null
  const id = Number(stored)
  if (!Number.isInteger(id) || id <= 0) {
    localStorage.removeItem(LOCK_KEY)
    return null
  }
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (response.status === 404) {
      localStorage.removeItem(LOCK_KEY)
      lockedId.value = null
      lockedCode.value = ''
      return null
    }
    if (!response.ok) throw new Error('锁定档案读取失败')
    const row = (await response.json()) as ArchiveRow
    lockedId.value = row.id
    lockedCode.value = row.档案编号
    // 锁住的行可能已经归还或被销毁：重新打开时按它的真实状态归位，不允许停在错的页签。
    activeTab.value = row.档案状态
    localStorage.setItem(TAB_KEY, row.档案状态)
    // 若记住的类别会把锁住的行过滤掉，先放开类别筛选，保证它一定看得见。
    if (categoryFilter.value && categoryFilter.value !== row.档案类别) {
      categoryFilter.value = ''
      localStorage.removeItem(CATEGORY_KEY)
      noticeMessage.value = `已定位到锁定的档案「${row.档案编号}」，并暂时放开类别筛选。`
    }
    return row.id
  } catch {
    // 暂时读不到（如后端重启中）不要丢掉锁定，下次打开再重新定位。
    return id
  }
}

onMounted(async () => {
  await loadCategories()
  // 先恢复记住的类别/页签；若存在锁定行，restoreLockedRow 会按它的真实状态覆盖页签。
  categoryFilter.value = localStorage.getItem(CATEGORY_KEY) ?? ''
  const rememberedTab = localStorage.getItem(TAB_KEY) as StatusKey | null
  if (rememberedTab && VALID_TABS.includes(rememberedTab)) {
    activeTab.value = rememberedTab
  }
  await restoreLockedRow()
  await Promise.all([reload(), loadStats()])
  if (lockedId.value !== null) {
    await locateRow(lockedId.value)
  }
})
</script>

<style scoped>
.status-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.tab-btn {
  border: none;
  background: none;
  padding: 8px 18px;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.tab-btn.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
  font-weight: 600;
}
.stat-card {
  cursor: pointer;
  outline: none;
}
.stat-card.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 1px var(--brand);
}
.stat-card.active .stat-value {
  color: var(--brand);
}
.filter-item select {
  padding: 5px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  min-width: 150px;
}
.missing-tag {
  display: inline-block;
  color: #b42318;
  background: #fef3f2;
  border: 1px solid #fecdca;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
  white-space: nowrap;
}
.warn-text {
  margin: 0 0 8px;
  color: #b54708;
  font-size: 12px;
}
.notice-text {
  margin: 0 0 8px;
  color: var(--brand);
  font-size: 12px;
}
.lock-link {
  color: var(--muted);
}
.locked-row {
  background: #eff6ff;
}
.locked-row td {
  font-weight: 600;
}
.flash-row {
  animation: archive-flash 2s ease-out;
}
@keyframes archive-flash {
  0% {
    background: #bfdbfe;
  }
  100% {
    background: #eff6ff;
  }
}
</style>
