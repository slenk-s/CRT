<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, fmtSize, statusText } from '@/api'
import type { ChangeoverDetail, CheckItem, ItemOut } from '@/api/types'
import AuthImage from '@/components/AuthImage.vue'
import { compressImage } from '@/utils/image'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const coId = computed(() => (route.params.id ? String(route.params.id) : ''))
const isCreate = computed(() => !coId.value)

// ---------------- 创建态 ----------------
const createForm = reactive({ line: '', batch: '', shot_date: '' })
const creating = ref(false)
const allLines = ref<Record<string, string[]>>({})
// 已设置「所属车间」时，线体下拉只展示该车间的线体（分组标题保留，便于看出是被限定了）
const linesByWorkshop = computed(() => {
  const ws = user.profile?.workshop || ''
  return ws ? { [ws]: allLines.value[ws] || [] } : allLines.value
})

// 车间改动后，已选线体若不在新范围内就清掉，避免提交到别的车间
watch(linesByWorkshop, (m) => {
  if (createForm.line && !Object.values(m).flat().includes(createForm.line)) createForm.line = ''
})

async function createSession() {
  if (!createForm.line || !createForm.batch.trim()) {
    ElMessage.warning('请选择线体并填写批次')
    return
  }
  creating.value = true
  try {
    const co = await api.coCreate({
      line: createForm.line,
      batch: createForm.batch.trim(),
      shot_date: createForm.shot_date || undefined,
    })
    ElMessage.success('已创建草稿，开始录入')
    router.replace(`/changeover/${co.id}/edit`)
  } finally {
    creating.value = false
  }
}

// ---------------- 录入态 ----------------
const detail = ref<ChangeoverDetail | null>(null)
const stations = ref<{ station: string; sort: number }[]>([])
const checkMap = ref<Record<string, string[]>>({})
const activeStation = ref('')
const savingStation = ref('')
const uploading = ref(false)
const submitting = ref(false)
const previewUrl = ref('')

// itemId → 本地草稿 { checks, remark }
const drafts = reactive<Record<number, { checks: Record<string, boolean>; remark: string }>>({})

const itemByStation = computed(() => {
  const m: Record<string, ItemOut> = {}
  for (const it of detail.value?.items || []) m[it.station] = it
  return m
})

function statusOf(it: ItemOut): 'unrecorded' | 'recorded' {
  const backend = parseChecks(it.draft_check_result)
  const local = drafts[it.id]?.checks || {}
  const hasChecks = Object.values(backend).some(Boolean) || Object.values(local).some(Boolean)
  const hasRemark = (it.draft_remark || '').trim() || (drafts[it.id]?.remark || '').trim()
  if (hasChecks || hasRemark || it.has_draft_photo) return 'recorded'
  return 'unrecorded'
}

const recordedCount = computed(() => (detail.value?.items || []).filter((it) => statusOf(it) === 'recorded').length)
const photoCount = computed(() => (detail.value?.items || []).filter((i) => i.has_draft_photo).length)

function parseChecks(json: string): Record<string, boolean> {
  try {
    const o = JSON.parse(json || '{}')
    const out: Record<string, boolean> = {}
    if (o && typeof o === 'object') for (const k of Object.keys(o)) out[k] = !!o[k]
    return out
  } catch {
    return {}
  }
}

function syncDraft(it: ItemOut) {
  drafts[it.id] = { checks: parseChecks(it.draft_check_result), remark: it.draft_remark || '' }
}

async function loadDetail() {
  if (!coId.value) return
  const co = await api.coGet(coId.value)
  if (co.status !== 'draft') {
    ElMessage.info('该转产已提交，跳转至详情（更正请使用「更正」）')
    router.replace(`/changeover/${co.id}`)
    return
  }
  detail.value = co
  for (const it of co.items) syncDraft(it)
}

function itemStatus(station: string): 'unrecorded' | 'recorded' {
  const it = itemByStation.value[station]
  return it ? statusOf(it) : 'unrecorded'
}

function itemStatusLabel(s: 'unrecorded' | 'recorded') {
  return s === 'recorded' ? '已录' : '未录'
}

async function openStation(station: string) {
  if (activeStation.value === station) {
    activeStation.value = ''
    return
  }
  activeStation.value = station
  if (!itemByStation.value[station]) {
    try {
      const it = await api.coAddItem(coId.value, station)
      detail.value?.items.push(it)
      syncDraft(it)
    } catch {
      /* 提示由拦截器统一处理 */
    }
  }
}

async function saveStation(station: string) {
  const it = itemByStation.value[station]
  if (!it) return
  const d = drafts[it.id]
  savingStation.value = station
  try {
    const checks: Record<string, boolean> = {}
    for (const [k, v] of Object.entries(d?.checks || {})) if (v) checks[k] = true
    const updated = await api.itemPatch(it.id, {
      check_result: JSON.stringify(checks),
      remark: d?.remark || '',
    })
    const idx = detail.value!.items.findIndex(x => x.id === updated.id)
    if (idx >= 0) detail.value!.items[idx] = updated
    syncDraft(updated)
    ElMessage.success(`${station} 已保存`)
  } finally {
    savingStation.value = ''
  }
}

async function onPickPhoto(station: string, ev: Event) {
  const input = ev.target as HTMLInputElement
  // input.files 是实时 FileList：先转成数组把 File 取出来，再清空 input，
  // 否则 value='' 会把刚才捕获的列表一并清空，导致整个上传被静默跳过。
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return
  const it = itemByStation.value[station]
  if (!it) return
  uploading.value = true
  try {
    for (const file of files) {
      const small = await compressImage(file)
      const updated = await api.itemUploadPhoto(it.id, small)
      // 替换数组中的项以触发 computed 重新计算（Object.assign 原地修改不触发）
      const idx = detail.value!.items.findIndex(x => x.id === updated.id)
      if (idx >= 0) detail.value!.items[idx] = updated
    }
    // 不要在这里 syncDraft：它会把 drafts 里的勾选/备注重置为服务端已保存值，
    // 抹掉用户还没点「保存本工位」的修改。上传照片不影响这两项。
    ElMessage.success(`已上传 ${files.length} 张照片`)
  } catch {
    ElMessage.error('照片上传失败，请检查网络后重试')
  } finally {
    uploading.value = false
  }
}

async function onDeletePhoto(it: ItemOut, seq: number) {
  try {
    await ElMessageBox.confirm('确认删除这张照片？', '删除照片', { type: 'warning' })
  } catch { return }
  const r = await api.itemDeletePhoto(it.id, seq)
  if (r.ok) {
    ElMessage.success('已删除')
    // loadDetail 会按服务端数据重建 drafts，先把本地未保存的勾选/备注留一份
    const keep = { ...drafts }
    await loadDetail()
    Object.assign(drafts, keep)
  } else {
    ElMessage.error(r.error || '删除失败')
  }
}

async function submitAll() {
  const items = detail.value?.items || []
  if (!items.length) {
    ElMessage.warning('至少录入一个工位后再提交')
    return
  }
  const missingPhoto = items.filter((i) => !i.has_draft_photo).map((i) => i.station)
  const notAll = items.length < stations.value.length
  const lines: string[] = []
  if (notAll) lines.push(`已录 ${items.length}/${stations.value.length} 个工位，未录入的工位不会提交`)
  if (missingPhoto.length) lines.push(`未拍照工位：${missingPhoto.join('、')}`)

  try {
    await ElMessageBox.confirm(
      lines.length
        ? `${lines.join('\n')}\n\n仍要提交并转正为正式版本吗？`
        : `确认提交「${detail.value?.line} / ${detail.value?.batch}」的 ${items.length} 个工位？提交后进入正式归档（v1），后续修改将生成新版本。`,
      '统一提交',
      { type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '再检查一下' },
    )
  } catch {
    return
  }

  submitting.value = true
  try {
    const r = await api.coSubmit(coId.value)
    if (!r.ok) {
      await ElMessageBox.alert(
        `提交未成功，会话仍为草稿。\n失败条目：\n${
          r.failures.map((f) => `· ${f.station}：${f.reason}`).join('\n') || '（无，请检查照片文件）'
        }`,
        '提交失败',
        { type: 'error' },
      )
      await loadDetail()
      return
    }
    if (r.failures.length) {
      await ElMessageBox.alert(
        `已提交 ${r.versions_created} 个工位；以下条目未转正：\n${r.failures
          .map((f) => `· ${f.station}：${f.reason}`)
          .join('\n')}`,
        '部分提交完成',
        { type: 'warning' },
      )
    } else {
      ElMessage.success(`提交成功：${r.versions_created} 个工位已归档（v1）`)
    }
    router.replace(`/changeover/${coId.value}`)
  } finally {
    submitting.value = false
  }
}

async function removeDraft() {
  try {
    await ElMessageBox.confirm('确认删除本草稿？草稿照片将一并清理，不可恢复。', '删除草稿', {
      type: 'warning',
    })
  } catch {
    return
  }
  await api.coDelete(coId.value)
  ElMessage.success('草稿已删除')
  router.replace('/changeover')
}

onMounted(async () => {
  const [st, ci, ln] = await Promise.all([api.dictStations(), api.dictCheckItems(), api.dictLines()])
  stations.value = st.map((s) => ({ station: s.station, sort: s.sort }))
  allLines.value = ln.by_workshop
  const map: Record<string, string[]> = {}
  for (const c of ci as CheckItem[]) (map[c.station] ||= []).push(c.item)
  checkMap.value = map
  if (!isCreate.value) await loadDetail()
})
</script>

<template>
  <div class="page">
    <div class="head-title">
      <h2 class="title">{{ isCreate ? '新建转产' : '转产录入' }}</h2>
      <p class="hint">{{ isCreate ? '选择线体并填写批次，创建后进入逐工位录入。' : `已录 ${recordedCount}/${stations.length} · 照片 ${photoCount}` }}</p>
    </div>
    <!-- 创建态 -->
    <div v-if="isCreate" class="page-body">
      <div class="card">
        <div class="panel">
          <el-form label-position="top" @submit.prevent>
            <el-form-item label="线体（按车间分组）" required>
              <el-select v-model="createForm.line" filterable placeholder="请选择线体" style="width: 100%">
                <el-option-group v-for="(ls, ws) in linesByWorkshop" :key="ws" :label="ws">
                  <el-option v-for="l in ls" :key="l" :label="l" :value="l" />
                </el-option-group>
              </el-select>
            </el-form-item>
            <el-form-item label="批次号" required>
              <el-input v-model="createForm.batch" placeholder="如 2406A-01" clearable />
            </el-form-item>
            <el-form-item label="日期（缺省为今天）">
              <el-date-picker
                v-model="createForm.shot_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="缺省今天"
                :editable="false"
                style="width: 100%"
              />
            </el-form-item>
          </el-form>
          <el-alert
            type="info"
            :closable="false"
            title="同一「日期+线体+批次」唯一；页面内逐工位录入，最后统一提交。"
            class="mb"
          />
          <el-button type="primary" size="large" style="width: 100%" :loading="creating" @click="createSession">
            创建草稿并开始录入
          </el-button>
        </div>
      </div>
    </div>

    <!-- 录入态 -->
    <div v-else class="mobile">
      <div class="card">
        <div class="panel">
          <div class="sess">
            <span>
              <b>{{ detail?.shot_date }}</b> · {{ detail?.workshop }} · <b>{{ detail?.line }}</b>
              <br />批次：{{ detail?.batch }}
            </span>
            <el-tag :type="detail?.status === 'submitted' ? 'success' : 'info'" size="small">
              {{ detail ? statusText(detail.status) : '' }}
            </el-tag>
          </div>

          <div v-for="s in stations" :key="s.station">
            <div
              class="strow"
              :class="{ done: itemStatus(s.station) === 'recorded', active: activeStation === s.station }"
              @click="openStation(s.station)"
            >
              <span class="nm">
                <span v-if="itemStatus(s.station) === 'recorded'" class="status-icon done" aria-hidden="true">
                  <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="24" cy="24" r="17" />
                    <path d="M15 24l6 6 12-12" />
                  </svg>
                </span>
                <span v-else class="status-icon" aria-hidden="true">
                  <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="24" cy="24" r="17" />
                  </svg>
                </span>
                {{ s.station }}
              </span>
              <span class="row-right">
                <el-tag v-if="itemByStation[s.station]?.has_draft_photo" type="success" size="small" effect="plain">
                  已拍照
                </el-tag>
                <span
                  class="pill-badge"
                  :class="{ ok: itemStatus(s.station) === 'recorded', no: itemStatus(s.station) === 'unrecorded' }"
                >
                  {{ itemStatusLabel(itemStatus(s.station)) }}
                </span>
                <el-icon class="expand-arrow"><ArrowRight /></el-icon>
              </span>
            </div>

            <div v-if="activeStation === s.station && itemByStation[s.station]" class="subcard">
              <h5>检查项（勾选即为通过）</h5>
              <div v-if="checkMap[s.station]?.length" class="checks">
                <label v-for="c in checkMap[s.station]" :key="c" class="chk">
                  <span class="checkbox-wrapper">
                    <input
                      type="checkbox"
                      :checked="!!drafts[itemByStation[s.station]!.id]?.checks[c]"
                      @change="(e) => { drafts[itemByStation[s.station]!.id].checks[c] = (e.target as HTMLInputElement).checked; }"
                    >
                    <svg viewBox="0 0 35.6 35.6">
                      <circle class="background" cx="17.8" cy="17.8" r="17.8"></circle>
                      <circle class="stroke" cx="17.8" cy="17.8" r="14.37"></circle>
                      <polyline class="check" points="11.78 18.12 15.55 22.23 25.17 12.87"></polyline>
                    </svg>
                  </span>
                  {{ c }}
                </label>
              </div>
              <div v-else class="note">该工位暂无预设检查项（可由管理员在「字典管理 → 检查项」补充）。</div>

              <el-input
                :model-value="drafts[itemByStation[s.station]!.id]?.remark || ''"
                @update:model-value="
                  (v: string) => {
                    const id = itemByStation[s.station]!.id
                    drafts[id].remark = String(v)
                  }
                "
                type="textarea"
                :rows="2"
                maxlength="500"
                show-word-limit
                placeholder="备注（可选）"
                style="margin-top: 8px"
              />

              <div class="thumbs-grid">
                <template v-if="itemByStation[s.station]?.draft_photos?.length">
                  <div v-for="ph in itemByStation[s.station]!.draft_photos" :key="ph.seq" class="thumb-cell">
                    <AuthImage
                      :path="ph.url"
                      :on-preview="(u) => (previewUrl = u)"
                    />
                    <div v-if="ph.synced === 0" class="sync-badge">待同步</div>
                    <button class="del-btn" @click="onDeletePhoto(itemByStation[s.station]!, ph.seq)" title="删除">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>
                      </svg>
                    </button>
                  </div>
                </template>
                <div v-else class="thumb-ph">未拍照</div>
              </div>

              <div class="sub-actions">
                <label class="btn-like">
                  <el-icon><Camera /></el-icon>
                  <span>{{ uploading ? '上传中…' : '拍照 / 选图' }}</span>
                  <!-- 不加 capture：手机上带了 capture 会直接进相机、无法从相册选图；
                       去掉后由系统弹出「相机 / 相册 / 文件」选择 -->
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    @change="(e) => onPickPhoto(s.station, e)"
                  />
                </label>
                <el-button
                  size="small"
                  type="primary"
                  :loading="savingStation === s.station"
                  @click="saveStation(s.station)"
                >
                  保存本工位
                </el-button>
              </div>
              <div class="note">照片先存入草稿区，统一提交后归档为正式版本。</div>
            </div>
          </div>

          <div class="commit">
            <el-button type="primary" size="large" style="width: 100%" :loading="submitting" @click="submitAll">
              统一提交（{{ recordedCount }} 个工位）
            </el-button>
            <div class="commit-row">
              <el-button style="flex: 1" @click="router.push('/changeover')">返回列表</el-button>
              <el-button style="flex: 1" type="danger" plain @click="removeDraft">删除草稿</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog :model-value="!!previewUrl" width="80%" title="照片预览" append-to-body @close="previewUrl = ''">
      <img v-if="previewUrl" :src="previewUrl" class="preview" alt="照片预览" />
    </el-dialog>
  </div>
</template>

<style scoped>
.row-right { display: flex; gap: 8px; align-items: center; }
.sub-actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; align-items: center; }
.thumbs-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.thumb-cell { position: relative; width: 80px; height: 80px; }
.thumb-cell .thumb { width: 80px; height: 80px; object-fit: cover; border-radius: 4px; }
.thumb-cell .sync-badge { position: absolute; bottom: 2px; left: 2px; background: #e6a23c; color: #fff; font-size: 10px; padding: 1px 4px; border-radius: 3px; }
.thumb-cell .del-btn { position: absolute; top: 2px; right: 2px; width: 20px; height: 20px; border-radius: 50%; background: rgba(0,0,0,0.6); border: none; color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.thumb-cell .del-btn svg { width: 12px; height: 12px; }
.commit-row { display: flex; gap: 8px; margin-top: 8px; }
.preview { width: 100%; border-radius: 8px; }
/* 用 label 包隐藏 input，点击即唤起系统相机/相册，行为最稳定 */
.btn-like {
  display: inline-flex; align-items: center; gap: 5px;
  height: 24px; padding: 0 11px; font-size: 12px; cursor: pointer;
  border: 1px solid var(--el-border-color); border-radius: 4px;
  background: #fff; color: var(--text2); transition: 0.15s;
}
.btn-like:hover { color: var(--primary); border-color: #a0cfff; background: #ecf5ff; }
.btn-like input { display: none; }
/* 自定义圆形复选框 */
.chk .checkbox-wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  vertical-align: middle;
}
.chk .checkbox-wrapper input[type="checkbox"] {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  -webkit-appearance: none;
  -moz-appearance: none;
  appearance: none;
  cursor: pointer;
}
.chk .checkbox-wrapper svg {
  width: 100%;
  height: 100%;
  display: block;
}
.chk .checkbox-wrapper .background {
  fill: #dfe7f2;
  transition: fill 0.6s ease;
}
.chk .checkbox-wrapper .stroke {
  fill: none;
  stroke: #fff;
  stroke-miterlimit: 10;
  stroke-width: 2px;
  stroke-dashoffset: 100;
  stroke-dasharray: 100;
  transition: stroke-dashoffset 0.6s ease;
}
.chk .checkbox-wrapper .check {
  fill: none;
  stroke: #fff;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.4px;
  stroke-dashoffset: 22;
  stroke-dasharray: 22;
  transition: stroke-dashoffset 0.6s ease;
}
.chk:hover .checkbox-wrapper .background {
  fill: #cfe2ff;
}
.chk input[type="checkbox"]:checked + svg .background {
  fill: var(--primary);
}
.chk input[type="checkbox"]:checked + svg .stroke,
.chk input[type="checkbox"]:checked + svg .check {
  stroke-dashoffset: 0;
}</style>



