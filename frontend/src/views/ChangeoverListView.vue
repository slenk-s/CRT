<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, fmtDateTime, statusText } from '@/api'
import { downloadFile } from '@/api/http'
import type { ChangeoverOut, DictLine } from '@/api/types'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const user = useUserStore()

const allLines = ref<DictLine[]>([])
// 已设置「所属车间」时只列该车间的线体；车间在用户菜单里改了会自动重算
const lines = computed(() => {
  const ws = user.profile?.workshop || ''
  return allLines.value.filter((x) => !ws || x.workshop === ws).map((x) => x.line)
})
const rows = ref<ChangeoverOut[]>([])
const total = ref(0)
const loading = ref(false)
const exporting = ref(false)

const query = reactive({
  status: '' as '' | 'draft' | 'submitted',
  line: '',
  from: '',
  to: '',
  keyword: '',
  mine: false,
  page: 1,
  size: 20,
})

const params = computed(() => {
  const p: Record<string, unknown> = { page: query.page, size: query.size }
  if (query.status) p.status = query.status
  if (query.line) p.line = query.line
  if (query.from) p.date_from = query.from
  if (query.to) p.date_to = query.to
  if (query.keyword.trim()) p.keyword = query.keyword.trim()
  if (query.mine) p.mine = true
  return p
})

async function load() {
  loading.value = true
  try {
    const r = await api.coList(params.value)
    rows.value = r.items
    total.value = r.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  query.status = ''
  query.line = ''
  query.from = ''
  query.to = ''
  query.keyword = ''
  query.mine = false
  search()
}

async function exportCsv() {
  exporting.value = true
  try {
    await downloadFile('/api/changeover/export.csv', params.value, `转产记录导出.csv`)
    ElMessage.success('导出完成（UTF-8 BOM，可直接用 Excel 打开）')
  } finally {
    exporting.value = false
  }
}

function canEdit(row: ChangeoverOut) {
  return row.status === 'draft' && (user.isAdmin || row.uploader_emp_id === user.profile?.emp_id)
}

function onRowCommand(cmd: string, row: ChangeoverOut) {
  if (cmd === 'edit') router.push(`/changeover/${row.id}/edit`)
  else if (cmd === 'delete') removeDraft(row)
  else if (cmd === 'delete-submitted') removeSubmitted(row)
}

async function removeDraft(row: ChangeoverOut) {
  try {
    await ElMessageBox.confirm(
      `确认删除草稿「${row.shot_date} / ${row.line} / ${row.batch}」？草稿照片将一并清理，且不可恢复。`,
      '删除草稿',
      { type: 'warning', confirmButtonText: '确认删除', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  await api.coDelete(row.id)
  ElMessage.success('已删除')
  load()
}

async function removeSubmitted(row: ChangeoverOut) {
  try {
    await ElMessageBox.confirm(
      `确认删除已提交记录「${row.shot_date} / ${row.line} / ${row.batch}」？正式文件将清理，操作会写入审计日志。`,
      '删除已提交记录',
      { type: 'warning', confirmButtonText: '确认删除', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  await api.coDelete(row.id)
  ElMessage.success('已删除')
  load()
}

// 车间改动后线体选项会变：若当前筛选值已不在范围内，清空并重查，避免筛出空列表
watch(lines, (ls) => {
  if (query.line && !ls.includes(query.line)) {
    query.line = ''
    load()
  }
})

onMounted(async () => {
  try {
    allLines.value = (await api.dictLines()).items
  } catch {
    /* 字典下拉失败不影响列表 */
  }
  load()
})
</script>

<template>
  <div class="page">
    <div class="head-title">
      <h2 class="title">转产记录</h2>
      <p class="hint">按「日期 + 线体 + 批次」管理转产会话；草稿可续录，提交后版本化留存。</p>
    </div>
    <div class="head-actions">
      <el-button class="head-btn export-btn" :loading="exporting" @click="exportCsv">
        <el-icon><Download /></el-icon><span>导出 CSV</span>
      </el-button>
      <el-button class="head-btn create-btn" type="primary" @click="router.push('/changeover/new')">
        <el-icon><Plus /></el-icon><span>新建转产</span>
      </el-button>
    </div>

    <div class="card panel mb">
      <el-form class="list-filter" inline label-width="68px" @submit.prevent>
        <el-form-item label="日期">
          <!-- 两个单日期选择器：每次只弹一个日历；editable=false 让输入框只读，
               手机上点中不会唤起键盘（窄屏下两端各占一半宽度） -->
          <div class="date-range">
            <el-date-picker
              v-model="query.from"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="开始"
              :editable="false"
              style="width: 128px"
            />
            <span class="date-sep">-</span>
            <el-date-picker
              v-model="query.to"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="结束"
              :editable="false"
              style="width: 128px"
            />
          </div>
        </el-form-item>
        <el-form-item label="线体">
          <el-select v-model="query.line" clearable filterable placeholder="全部" style="width: 140px">
            <el-option v-for="l in lines" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" clearable placeholder="全部" style="width: 120px">
            <el-option label="草稿" value="draft" />
            <el-option label="已提交" value="submitted" />
          </el-select>
        </el-form-item>
        <el-form-item label="批次">
          <el-input v-model="query.keyword" clearable placeholder="批次模糊匹配" style="width: 160px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="范围">
          <el-checkbox v-model="query.mine">仅看我的</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search"><el-icon><Search /></el-icon>查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="card">
      <el-table v-loading="loading" :data="rows" stripe class="changeover-table card-enter-active" style="width: 100%">
        <el-table-column prop="shot_date" label="日期" width="110" class-name="col-nowrap" />
        <el-table-column prop="workshop" label="车间" width="82" />
        <el-table-column prop="line" label="线体" width="88" />
        <el-table-column prop="batch" label="批次" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="82">
          <template #default="{ row }">
            <el-tag :type="row.status === 'submitted' ? 'success' : 'info'" effect="light" size="small">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工位/照片" width="94" align="center">
          <template #default="{ row }">
            <span :class="{ warn: row.item_with_photo < row.item_total }">
              {{ row.item_total }}/{{ row.item_with_photo }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="上传人" width="122">
          <template #default="{ row }">{{ row.uploader_name }}<small class="sub"> {{ row.uploader_emp_id }}</small></template>
        </el-table-column>
        <el-table-column label="提交时间" width="176" class-name="col-nowrap">
          <template #default="{ row }">{{ fmtDateTime(row.submitted_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="132" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="router.push(`/changeover/${row.id}`)">查看</el-button>
              <el-dropdown
                v-if="canEdit(row) || user.isAdmin"
                trigger="click"
                placement="bottom-end"
                :hide-on-click="true"
                popper-class="row-more-dropdown"
                @command="(cmd: string) => onRowCommand(cmd, row)"
              >
                <el-button link type="primary" class="action-more">更多</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="canEdit(row)" command="edit">继续录入</el-dropdown-item>
                    <el-dropdown-item v-if="canEdit(row)" command="delete" :divided="user.isAdmin" class="danger-item">删除</el-dropdown-item>
                    <el-dropdown-item v-if="user.isAdmin" command="delete-submitted" divided class="danger-item">删除已提交记录</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无转产记录" /></template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.size"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.head-actions { min-width: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; width: 100%; max-width: 100%; padding: 16px 20px; border-radius: 14px; background: var(--card); border: 1px solid var(--border-l); box-shadow: 0 1px 3px rgba(0,0,0,.04); margin: 0 0 16px; }
.head-btn { width: 100% !important; max-width: 100%; min-width: 0; height: 42px !important; display: inline-flex !important; align-items: center; justify-content: center; gap: 8px; border-radius: 12px !important; font-weight: 600 !important; letter-spacing: .2px; transition: transform .14s ease, box-shadow .16s ease, border-color .16s ease, color .16s ease, background .18s ease, opacity .16s ease; }
.head-btn .el-icon { font-size: 17px; }
.head-btn span { line-height: 1; white-space: nowrap; }
.export-btn { background: linear-gradient(180deg, #ffffff, #f7fbff) !important; color: var(--text2) !important; border: 1px solid #dfe7f3 !important; box-shadow: 0 1px 2px rgba(31,45,61,.04); }
.export-btn:hover { color: var(--primary) !important; border-color: #bfe0ff !important; box-shadow: 0 8px 18px rgba(64,158,255,.10); transform: translateY(-1px); }
.create-btn { background: linear-gradient(135deg, #64a8ff, var(--primary)) !important; border: 1px solid transparent !important; box-shadow: 0 8px 18px rgba(64,158,255,.22); }
.create-btn:hover { transform: translateY(-1px); box-shadow: 0 12px 24px rgba(64,158,255,.28); }
.head-btn:active { transform: scale(.96); }
.head-btn.is-loading { transform: none; }
.title { margin: 0; font-size: 20px; }
.sub { color: var(--text3); }
.warn { color: var(--warning); font-weight: 600; }
.pager { display: flex; justify-content: flex-end; padding: 14px 0 4px; }
.changeover-table .el-table__row { transition: transform .18s cubic-bezier(.34,1.56,.64,1), box-shadow .18s ease, background-color .16s ease; }
.changeover-table .el-table__row:hover { background-color: #f7fbff; }
.changeover-table { width: 100%; }
.changeover-table .el-table__header .cell,
.changeover-table .el-table__body .cell { padding-left: 6px; padding-right: 6px; }
.changeover-table .el-button.is-link { padding: 0 6px; }
/* 日期 / 提交时间强制单行（列宽已含 Element Plus 的 12px 单元格内边距） */
:deep(.col-nowrap .cell) { white-space: nowrap; }
.row-actions { display: flex; align-items: center; justify-content: center; gap: 6px; }
.row-actions .el-dropdown { display: inline-flex; }
.row-more-dropdown { min-width: 118px; max-width: calc(100vw - 28px); border-radius: 10px; box-shadow: 0 12px 28px rgba(31,45,61,.16); }
.danger-item { color: var(--danger); }



/* 让筛选区在窄屏下成为完整卡片内的主操作区 */
.list-filter { width: 100%; }
.list-filter .el-form-item { min-width: 0; }

.date-range { display: flex; align-items: center; gap: 6px; }
.date-sep { color: var(--text3); }

@media (max-width: 640px) {
  .head-actions { width: 100%; max-width: 100%; grid-template-columns: 1fr 1fr; gap: 8px; padding: 14px 14px; margin: 0 0 14px; }
  .head-btn { padding-left: 10px; padding-right: 10px; font-size: 13px; }
  .pager { justify-content: center; padding-top: 10px; }
  .changeover-table .el-table__header .cell,
  .changeover-table .el-table__body .cell { padding-left: 4px; padding-right: 4px; }
  /* 窄屏：两个日期框各占一半，不要按全局规则撑成 100% 而溢出 */
  .date-range { width: 100%; }
  .date-range :deep(.el-date-editor) { flex: 1 1 0; min-width: 0; width: auto !important; }
  .list-filter .date-range { max-width: 100%; }
}
</style>