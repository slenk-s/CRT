<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, fmtDateTime, fmtSize, statusText } from '@/api'
import type { ChangeoverDetail, CheckItem, ItemOut, VersionOut } from '@/api/types'
import AuthImage from '@/components/AuthImage.vue'
import { compressImage } from '@/utils/image'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const coId = computed(() => String(route.params.id))
const detail = ref<ChangeoverDetail | null>(null)
const loading = ref(false)
const previewUrl = ref('')

const isSubmitted = computed(() => detail.value?.status === 'submitted')
const canOperate = computed(
  () =>
    !!detail.value &&
    (user.isAdmin || detail.value.uploader_emp_id === user.profile?.emp_id),
)

async function load() {
  loading.value = true
  try {
    detail.value = await api.coGet(coId.value)
    for (const it of detail.value.items) {
      drafts[it.id] = { checks: parseChecks(it.draft_check_result), remark: it.draft_remark || '' }
    }
  } finally {
    loading.value = false
  }
}

// ---------------- 条目解析 ----------------
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
function submittedStatusOf(it: ItemOut): 'unrecorded' | 'recorded' {
  if (isSubmitted.value) {
    const checks = parseChecks(it.draft_check_result)
    const hasChecks = Object.values(checks).some(Boolean)
    const hasRemark = (it.draft_remark || '').trim()
    if (hasChecks || hasRemark || it.has_draft_photo) return 'recorded'
    return 'unrecorded'
  }
  return it.item_status === 'recorded' ? 'recorded' : 'unrecorded'
}

function statusLabel(s: 'unrecorded' | 'recorded') {
  return s === 'recorded' ? '已录' : '未录'
}

function checkedList(it: ItemOut): string[] {
  const src = isSubmitted.value ? it.draft_check_result : it.draft_check_result
  return Object.entries(parseChecks(src))
    .filter(([, v]) => v)
    .map(([k]) => k)
}
function totalChecks(it: ItemOut): number {
  return Object.keys(parseChecks(it.draft_check_result)).length
}

// ---------------- 更正（生成新版本） ----------------
const drafts = reactive<Record<number, { checks: Record<string, boolean>; remark: string }>>({})
const correctVisible = ref(false)
const correctItem = ref<ItemOut | null>(null)
const correctForm = reactive({ checks: {} as Record<string, boolean>, remark: '', edit_note: '' })
const correcting = ref(false)

// 工位 → 预设检查项（更正时需展示全部可选项，而非仅已勾选项）
const checkMap = ref<Record<string, string[]>>({})
const stationChecks = computed(() => {
  const st = correctItem.value?.station || ''
  const preset = checkMap.value[st] || []
  const existing = Object.keys(correctForm.checks)
  const all = [...preset]
  for (const k of existing) if (!all.includes(k)) all.push(k)
  return all
})

function openCorrect(it: ItemOut) {
  correctItem.value = it
  const prev = parseChecks(it.draft_check_result)
  const checks: Record<string, boolean> = {}
  for (const name of checkMap.value[it.station] || []) checks[name] = !!prev[name]
  for (const [k, v] of Object.entries(prev)) if (!(k in checks)) checks[k] = v
  correctForm.checks = checks
  correctForm.remark = it.draft_remark || ''
  correctForm.edit_note = '更正'
  correctVisible.value = true
}

async function submitCorrect() {
  const it = correctItem.value
  if (!it) return
  correcting.value = true
  try {
    const checks: Record<string, boolean> = {}
    for (const [k, v] of Object.entries(correctForm.checks)) if (v) checks[k] = true
    await api.itemCorrect(it.id, {
      check_result: JSON.stringify(checks),
      remark: correctForm.remark,
      edit_note: correctForm.edit_note || '更正',
    })
    ElMessage.success('已更正并生成新版本')
    correctVisible.value = false
    await load()
  } finally {
    correcting.value = false
  }
}

// ---------------- 替换照片（生成新版本） ----------------
const replacingId = ref(0)
async function onReplacePhoto(it: ItemOut, ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  replacingId.value = it.id
  try {
    const small = await compressImage(file)
    await api.itemUploadPhoto(it.id, small)
    ElMessage.success('照片已替换并生成新版本')
    await load()
  } finally {
    replacingId.value = 0
  }
}

async function removeItem(it: ItemOut) {
  try {
    await ElMessageBox.confirm(
      isSubmitted.value
        ? `确认移除「${it.station}」条目？已提交记录为软删除，正式文件与版本历史仍保留。`
        : `确认移除「${it.station}」条目及其草稿照片？`,
      '移除条目',
      { type: 'warning' },
    )
  } catch {
    return
  }
  await api.itemDelete(it.id)
  ElMessage.success('已移除')
  await load()
}

// ---------------- 版本历史 ----------------
const verVisible = ref(false)
const verLoading = ref(false)
const verItem = ref<ItemOut | null>(null)
const versions = ref<VersionOut[]>([])

async function openVersions(it: ItemOut) {
  verItem.value = it
  verVisible.value = true
  verLoading.value = true
  try {
    versions.value = await api.itemVersions(it.id)
  } finally {
    verLoading.value = false
  }
}

onMounted(async () => {
  try {
    const ci = (await api.dictCheckItems()) as CheckItem[]
    const map: Record<string, string[]> = {}
    for (const c of ci) (map[c.station] ||= []).push(c.item)
    checkMap.value = map
  } catch {
    /* 字典失败不阻断详情展示 */
  }
  await load()
})
</script>

<template>
  <div class="page detail-enter" v-loading="loading">
    <div class="head-title">
      <h2 class="title">转产详情</h2>
      <p class="hint">提交后条目内容不可直接修改，更正会生成新版本，历史版本完整留存。</p>
    </div>
    <div class="head-actions">
      <el-button @click="router.push('/changeover')">返回列表</el-button>
      <el-button
        v-if="canOperate && !isSubmitted"
        type="primary"
        @click="router.push(`/changeover/${coId}/edit`)"
      >
        继续录入
      </el-button>
    </div>

    <div v-if="detail" class="card panel mb">
      <div class="meta">
        <div><span>日期</span><b>{{ detail.shot_date }}</b></div>
        <div><span>车间</span><b>{{ detail.workshop }}</b></div>
        <div><span>线体</span><b>{{ detail.line }}</b></div>
        <div><span>批次</span><b>{{ detail.batch }}</b></div>
        <div><span>状态</span>
          <el-tag :type="isSubmitted ? 'success' : 'info'" size="small">{{ statusText(detail.status) }}</el-tag>
        </div>
        <div><span>上传人</span><b>{{ detail.uploader_name }}（{{ detail.uploader_emp_id }}）</b></div>
        <div><span>创建时间</span><b>{{ fmtDateTime(detail.created_at) }}</b></div>
        <div><span>提交时间</span><b>{{ fmtDateTime(detail.submitted_at) }}</b></div>
        <div><span>工位/照片</span><b>{{ detail.item_with_photo }}/{{ detail.item_total }}</b></div>
      </div>
    </div>

    <div v-if="detail" class="grid2">
      <div v-for="it in detail.items" :key="it.id" class="card kvcard">
        <h4>
          {{ it.station }}
          <el-tag size="small" effect="plain" style="margin-left: 6px">v{{ it.current_ver }}</el-tag>
          <el-tag v-if="!it.has_draft_photo" size="small" type="warning" effect="plain" style="margin-left: 6px">
            无照片
          </el-tag>
          <el-tag v-if="it.has_photo_pending_sync" size="small" type="danger" effect="plain" style="margin-left: 6px" class="pending-tag">
            <el-icon><WarningFilled /></el-icon>待同步
          </el-tag>
        </h4>

        <div class="thumbs-grid">
          <template v-if="it.draft_photos?.length">
            <div
              v-for="ph in it.draft_photos"
              :key="`${it.current_ver}-${ph.seq}`"
              class="photo-wrap"
              :class="{ 'photo-pending': ph.synced === 0 }"
            >
              <AuthImage :path="ph.url" :on-preview="(u) => (previewUrl = u)" />
              <span v-if="ph.synced === 0" class="pending-badge">待同步</span>
            </div>
          </template>
          <div v-else class="thumb-ph">未拍照</div>
        </div>
        <div v-if="it.has_photo_pending_sync" class="sync-note">
          <el-icon><WarningFilled /></el-icon>
          部分照片在本地暂存，SMB 恢复后自动同步
        </div>

        <div class="checks-view">
          <template v-if="totalChecks(it)">
            <el-tag
              v-for="c in checkedList(it)"
              :key="c"
              size="small"
              type="success"
              effect="plain"
              class="chk-tag"
            >{{ c }}</el-tag>
          </template>
          <span v-else class="note">未勾选任何检查项</span>
        </div>

        <div v-if="it.draft_remark" class="remark">备注：{{ it.draft_remark }}</div>
        <div class="note">
          更新：{{ fmtDateTime(it.draft_updated_at || it.updated_at) }}
          <template v-if="isSubmitted"> · 大小 {{ fmtSize(it.draft_size) }}</template>
        </div>

        <div v-if="canOperate" class="item-actions">
          <el-button size="small" @click="openCorrect(it)">
            <el-icon><EditPen /></el-icon>更正
          </el-button>
          <label class="btn-like" :class="{ disabled: replacingId === it.id }">
            <el-icon><Refresh /></el-icon>
            <span>{{ replacingId === it.id ? '替换中…' : '替换照片' }}</span>
            <input type="file" accept="image/*" @change="(e) => onReplacePhoto(it, e)" />
          </label>
          <el-button size="small" @click="openVersions(it)">
            <el-icon><Clock /></el-icon>版本历史
          </el-button>
          <!-- 草稿中的工位不可移除（草稿请回录入页删整份草稿）；已提交记录为软删 -->
          <el-button v-if="isSubmitted" size="small" type="danger" plain @click="removeItem(it)">移除</el-button>
        </div>
      </div>
    </div>

    <el-empty v-else-if="!loading" description="暂无数据" />

    <!-- 更正对话框 -->
    <el-dialog v-model="correctVisible" :title="`更正 · ${correctItem?.station || ''}`" width="520px" append-to-body>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="更正将生成新版本（ver + 1），历史版本保留可追溯。"
        class="mb"
      />
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="检查项（勾选即为通过）">
          <div class="checks">
            <label v-for="name in stationChecks" :key="name" class="chk">
              <el-checkbox v-model="correctForm.checks[name]" />{{ name }}
            </label>
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="correctForm.remark" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="更正说明">
          <el-input v-model="correctForm.edit_note" maxlength="200" placeholder="如：白平衡复测通过" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="correctVisible = false">取消</el-button>
        <el-button type="primary" :loading="correcting" @click="submitCorrect">保存并生成新版本</el-button>
      </template>
    </el-dialog>

    <!-- 版本历史 -->
    <el-dialog
      v-model="verVisible"
      :title="`版本历史 · ${verItem?.station || ''}`"
      width="360px"
      class="version-dialog"
      append-to-body
      :close-on-click-modal="false"
    >
      <div class="version-body" v-loading="verLoading">
        <el-timeline v-if="versions.length" class="version-timeline">
          <el-timeline-item
            v-for="v in versions"
            :key="v.ver"
            :timestamp="fmtDateTime(v.created_at)"
            placement="top"
            :type="v.ver === verItem?.current_ver ? 'primary' : 'info'"
          >
            <div class="ver-card">
              <div class="ver-head">
                <b>v{{ v.ver }}</b>
                <el-tag v-if="v.ver === verItem?.current_ver" size="small" type="primary" effect="plain">当前</el-tag>
                <span class="note">{{ v.uploader_name }}（{{ v.uploader_emp_id }}）· {{ fmtSize(v.file_size) }}</span>
              </div>
              <AuthImage
                v-if="v.photo_url"
                :key="`${v.ver}-${v.created_at}`"
                :path="v.photo_url"
                :on-preview="(u) => (previewUrl = u)"
              />
              <div v-else class="thumb-ph">v{{ v.ver }} 无照片</div>
              <div v-if="Object.keys(parseChecks(v.check_result)).length" class="checks-view" style="margin-top: 8px">
                <el-tag
                  v-for="c in Object.entries(parseChecks(v.check_result)).filter(([, x]) => x).map(([k]) => k)"
                  :key="c"
                  size="small"
                  type="success"
                  effect="plain"
                  class="chk-tag"
                >{{ c }}</el-tag>
              </div>
              <div v-if="v.remark" class="remark">备注：{{ v.remark }}</div>
              <div v-if="v.edit_note" class="note">说明：{{ v.edit_note }}</div>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无版本记录" :image-size="54" />
      </div>
    </el-dialog>

    <el-dialog :model-value="!!previewUrl" width="80%" title="照片预览" append-to-body @close="previewUrl = ''">
      <img v-if="previewUrl" :src="previewUrl" class="preview-lg" alt="照片预览" />
    </el-dialog>
  </div>
</template>

<style scoped>
.title { margin: 0; font-size: 20px; }
.meta { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px 20px; }
.meta > div { display: flex; gap: 8px; font-size: 13px; }
.meta span { color: var(--text3); flex: 0 0 66px; }
.checks-view { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.chk-tag { max-width: 100%; }
.remark { margin-top: 8px; font-size: 13px; color: var(--text2); background: #fafcff; border-left: 3px solid #d9ecff; padding: 6px 10px; border-radius: 0 6px 6px 0; }
.thumbs-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.thumbs-grid .thumb { width: 80px; height: 80px; object-fit: cover; border-radius: 4px; }
.photo-wrap { position: relative; display: inline-block; }
.photo-pending { border-radius: 4px; }
.photo-pending :deep(img) { border: 2px solid var(--el-color-danger); }
.pending-badge {
  position: absolute; bottom: 2px; left: 2px;
  font-size: 10px; padding: 1px 4px; border-radius: 3px;
  background: var(--el-color-danger); color: #fff; white-space: nowrap;
}
.sync-note {
  display: flex; align-items: center; gap: 5px;
  margin-top: 6px; font-size: 12px; color: var(--el-color-danger);
}
.item-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; align-items: center; }
.version-body { max-height: min(62vh, 540px); overflow-y: auto; padding-right: 4px; }
.version-timeline { padding-left: 2px; }
.ver-card { border: 1px solid var(--border-l); border-radius: 10px; padding: 10px 12px; background: #fafcff; }
:deep(.version-dialog .el-dialog) { border-radius: 14px; }
:deep(.version-dialog .el-dialog__body) { padding: 16px 18px 4px; }
.ver-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.preview-lg { width: 100%; border-radius: 8px; }
.btn-like {
  display: inline-flex; align-items: center; gap: 5px;
  height: 24px; padding: 0 11px; font-size: 12px; cursor: pointer;
  border: 1px solid var(--el-border-color); border-radius: 4px;
  background: #fff; color: var(--text2); transition: 0.15s;
}
.btn-like:hover { color: var(--primary); border-color: #a0cfff; background: #ecf5ff; }
.btn-like.disabled { opacity: 0.6; cursor: not-allowed; }
.btn-like input { display: none; }
</style>