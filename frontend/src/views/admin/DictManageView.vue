<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import type { CheckItemAdmin, LineAdmin, StationAdmin } from '@/api/types'

const tab = ref('lines')
const loading = ref(false)

const lines = ref<LineAdmin[]>([])
const stations = ref<StationAdmin[]>([])
const checkItems = ref<CheckItemAdmin[]>([])
const stationFilter = ref('')

const filteredCheckItems = computed(() =>
  stationFilter.value ? checkItems.value.filter((c) => c.station === stationFilter.value) : checkItems.value,
)

// ---------------- 线体 ----------------
const lineDialog = reactive({ visible: false, id: 0, workshop: '', line: '', sort: 0 })
function openLine(row?: LineAdmin) {
  lineDialog.id = row?.id || 0
  lineDialog.workshop = row?.workshop || ''
  lineDialog.line = row?.line || ''
  lineDialog.sort = row?.sort ?? 0
  lineDialog.visible = true
}
async function saveLine() {
  if (!lineDialog.workshop.trim() || !lineDialog.line.trim()) {
    ElMessage.warning('车间与线体均不能为空')
    return
  }
  const body = { workshop: lineDialog.workshop.trim(), line: lineDialog.line.trim(), sort: lineDialog.sort }
  if (lineDialog.id) await api.adminUpdateLine(lineDialog.id, body)
  else await api.adminCreateLine(body)
  ElMessage.success('已保存')
  lineDialog.visible = false
  await loadLines()
}

const importDialog = reactive({ visible: false, text: '', saving: false })
async function doImport() {
  if (!importDialog.text.trim()) return
  importDialog.saving = true
  try {
    const r = await api.adminImportLines(importDialog.text)
    ElMessage.success(`导入完成：新增 ${r.added}，恢复 ${r.reactivated}，跳过 ${r.skipped}`)
    importDialog.visible = false
    importDialog.text = ''
    await loadLines()
  } finally {
    importDialog.saving = false
  }
}

// ---------------- 工位 ----------------
const stDialog = reactive({ visible: false, id: 0, station: '', sort: 0 })
function openStation(row?: StationAdmin) {
  stDialog.id = row?.id || 0
  stDialog.station = row?.station || ''
  stDialog.sort = row?.sort ?? 0
  stDialog.visible = true
}
async function saveStation() {
  if (!stDialog.station.trim()) {
    ElMessage.warning('工位名不能为空')
    return
  }
  const body = { station: stDialog.station.trim(), sort: stDialog.sort }
  if (stDialog.id) await api.adminUpdateStation(stDialog.id, body)
  else await api.adminCreateStation(body)
  ElMessage.success('已保存')
  stDialog.visible = false
  await Promise.all([loadStations(), loadCheckItems()])
}

// ---------------- 检查项 ----------------
const ckDialog = reactive({ visible: false, id: 0, station: '', item: '', sort: 0 })
function openCheckItem(row?: CheckItemAdmin) {
  ckDialog.id = row?.id || 0
  ckDialog.station = row?.station || stationFilter.value || stations.value[0]?.station || ''
  ckDialog.item = row?.item || ''
  ckDialog.sort = row?.sort ?? 0
  ckDialog.visible = true
}
async function saveCheckItem() {
  if (!ckDialog.station || !ckDialog.item.trim()) {
    ElMessage.warning('工位与检查项均不能为空')
    return
  }
  const body = { station: ckDialog.station, item: ckDialog.item.trim(), sort: ckDialog.sort }
  if (ckDialog.id) await api.adminUpdateCheckItem(ckDialog.id, body)
  else await api.adminCreateCheckItem(body)
  ElMessage.success('已保存')
  ckDialog.visible = false
  await loadCheckItems()
}

// ---------------- 通用（删除/启用） ----------------
async function removeRow(kind: 'line' | 'station' | 'item', row: LineAdmin | StationAdmin | CheckItemAdmin) {
  const label = kind === 'line' ? (row as LineAdmin).line : kind === 'station' ? (row as StationAdmin).station : (row as CheckItemAdmin).item
  const confirmText = `确认删除「${label}」？删除后该字典项将不会出现在新建转产中。已有历史记录仍保留。`
  try {
    await ElMessageBox.confirm(confirmText, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  if (kind === 'line') await api.adminDeleteLine((row as LineAdmin).id)
  else if (kind === 'station') await api.adminDeleteStation((row as StationAdmin).id)
  else await api.adminDeleteCheckItem((row as CheckItemAdmin).id)
  ElMessage.success('已删除')
  await refreshAll()
}

async function toggleActive(
  kind: 'line' | 'station' | 'item',
  row: LineAdmin | StationAdmin | CheckItemAdmin,
) {
  const next = row.active ? 0 : 1
  if (kind === 'line') await api.adminUpdateLine(row.id, { active: next })
  else if (kind === 'station') await api.adminUpdateStation(row.id, { active: next })
  else await api.adminUpdateCheckItem(row.id, { active: next })
  ElMessage.success(next ? '已启用' : '已停用')
  await refreshAll()
}

// ---------------- 加载 ----------------
async function loadLines() {
  loading.value = true
  try {
    lines.value = await api.adminLines()
  } finally {
    loading.value = false
  }
}
async function loadStations() {
  stations.value = await api.adminStations()
}
async function loadCheckItems() {
  checkItems.value = await api.adminCheckItems()
}
async function refreshAll() {
  await Promise.all([loadLines(), loadStations(), loadCheckItems()])
}
onMounted(refreshAll)
</script>

<template>
  <div class="page">
    <div class="head-title">
      <h2 class="title">字典管理</h2>
      <p class="hint">线体 / 工位 / 检查项维护（仅管理员）；停用为软删除，保证历史转产记录完整可追溯。</p>
    </div>

    <div class="card panel">
      <el-tabs v-model="tab">
        <!-- 线体 -->
        <el-tab-pane label="线体" name="lines">
          <div class="toolbar">
            <el-button type="primary" :icon="'Plus'" @click="openLine()">新增线体</el-button>
            <el-button :icon="'Upload'" @click="importDialog.visible = true">批量导入</el-button>
            <span class="note">共 {{ lines.length }} 条（含停用）</span>
          </div>
          <el-table v-loading="loading" :data="lines" stripe>
            <el-table-column prop="workshop" label="车间" width="116" />
            <el-table-column prop="line" label="线体" width="116" />
            <el-table-column prop="sort" label="排序" width="70" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.active ? 'success' : 'info'" size="small" effect="plain">
                  {{ row.active ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="170">
              <template #default="{ row }">
                <el-button link type="primary" @click="openLine(row)">编辑</el-button>
                <el-button link type="primary" @click="toggleActive('line', row)">
                  {{ row.active ? '停用' : '启用' }}
                </el-button>
                <el-button link type="danger" @click="removeRow('line', row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 工位 -->
        <el-tab-pane label="工位" name="stations">
          <div class="toolbar">
            <el-button type="primary" :icon="'Plus'" @click="openStation()">新增工位</el-button>
            <span class="note">共 {{ stations.length }} 条</span>
          </div>
          <el-table :data="stations" stripe>
            <el-table-column prop="station" label="工位" min-width="150" />
            <el-table-column prop="sort" label="排序" width="70" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.active ? 'success' : 'info'" size="small" effect="plain">
                  {{ row.active ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="170">
              <template #default="{ row }">
                <el-button link type="primary" @click="openStation(row)">编辑</el-button>
                <el-button link type="primary" @click="toggleActive('station', row)">
                  {{ row.active ? '停用' : '启用' }}
                </el-button>
                <el-button link type="danger" @click="removeRow('station', row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 检查项 -->
        <el-tab-pane label="检查项" name="checks">
          <div class="toolbar">
            <el-button type="primary" :icon="'Plus'" @click="openCheckItem()">新增检查项</el-button>
            <el-select v-model="stationFilter" clearable placeholder="按工位筛选" style="width: 200px">
              <el-option v-for="s in stations" :key="s.id" :label="s.station" :value="s.station" />
            </el-select>
            <span class="note">共 {{ filteredCheckItems.length }} 条</span>
          </div>
          <el-table :data="filteredCheckItems" stripe>
            <el-table-column prop="station" label="工位" width="120" />
            <el-table-column prop="item" label="检查项" min-width="210" show-overflow-tooltip />
            <el-table-column prop="sort" label="排序" width="70" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.active ? 'success' : 'info'" size="small" effect="plain">
                  {{ row.active ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="170">
              <template #default="{ row }">
                <el-button link type="primary" @click="openCheckItem(row)">编辑</el-button>
                <el-button link type="primary" @click="toggleActive('item', row)">
                  {{ row.active ? '停用' : '启用' }}
                </el-button>
                <el-button link type="danger" @click="removeRow('item', row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 线体表单 -->
    <el-dialog v-model="lineDialog.visible" :title="lineDialog.id ? '编辑线体' : '新增线体'" width="420px" append-to-body>
      <el-form label-width="76px" @submit.prevent>
        <el-form-item label="车间" required>
          <el-input v-model="lineDialog.workshop" placeholder="如 一车间" />
        </el-form-item>
        <el-form-item label="线体" required>
          <el-input v-model="lineDialog.line" placeholder="如 1F01" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="lineDialog.sort" :min="0" :step="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="lineDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveLine">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入 -->
    <el-dialog v-model="importDialog.visible" title="批量导入线体" width="520px" append-to-body>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="每行一条「车间,线体」，分隔符支持 Tab / 中英文逗号 / 空白；已存在的线体自动跳过。"
        class="mb"
      />
      <el-input
        v-model="importDialog.text"
        type="textarea"
        :rows="8"
        placeholder="一车间,1F01&#10;一车间,1F02&#10;二车间,2F01"
      />
      <template #footer>
        <el-button @click="importDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="importDialog.saving" @click="doImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 工位表单 -->
    <el-dialog v-model="stDialog.visible" :title="stDialog.id ? '编辑工位' : '新增工位'" width="420px" append-to-body>
      <el-form label-width="76px" @submit.prevent>
        <el-form-item label="工位" required>
          <el-input v-model="stDialog.station" placeholder="如 白平衡工位" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="stDialog.sort" :min="0" :step="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="stDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveStation">保存</el-button>
      </template>
    </el-dialog>

    <!-- 检查项表单 -->
    <el-dialog v-model="ckDialog.visible" :title="ckDialog.id ? '编辑检查项' : '新增检查项'" width="480px" append-to-body>
      <el-form label-width="76px" @submit.prevent>
        <el-form-item label="工位" required>
          <el-select v-model="ckDialog.station" filterable style="width: 100%">
            <el-option v-for="s in stations" :key="s.id" :label="s.station" :value="s.station" />
          </el-select>
        </el-form-item>
        <el-form-item label="检查项" required>
          <el-input v-model="ckDialog.item" placeholder="如 光感" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="ckDialog.sort" :min="0" :step="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ckDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveCheckItem">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.title { margin: 0 0 4px; font-size: 20px; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
</style>