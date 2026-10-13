<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, fmtDateTime } from '@/api'
import type { UserAdmin } from '@/api/types'
import { useUserStore } from '@/stores/user'

const me = useUserStore()
const rows = ref<UserAdmin[]>([])
const loading = ref(false)

const dialog = reactive({
  visible: false,
  isNew: true,
  emp_id: '',
  origEmpId: '',
  name: '',
  password: '',
  role: 'line',
  active: 1,
  saving: false,
})

async function load() {
  loading.value = true
  try {
    rows.value = await api.adminUsers()
  } finally {
    loading.value = false
  }
}

function openNew() {
  Object.assign(dialog, { visible: true, isNew: true, emp_id: '', origEmpId: '', name: '', password: '', role: 'line', active: 1 })
}
function openEdit(row: UserAdmin) {
  Object.assign(dialog, {
    visible: true,
    isNew: false,
    emp_id: row.emp_id,
    origEmpId: row.emp_id,
    name: row.name,
    password: '',
    role: row.role,
    active: row.active,
  })
}

async function save() {
  const empId = dialog.emp_id.trim()
  if (!empId) {
    ElMessage.warning('工号不能为空')
    return
  }
  if (dialog.isNew && (!dialog.name.trim() || dialog.password.length < 6)) {
    ElMessage.warning('请填写工号、姓名，初始口令至少 6 位')
    return
  }
  const renamed = !dialog.isNew && empId !== dialog.origEmpId
  if (renamed && dialog.origEmpId === me.profile?.emp_id) {
    ElMessage.warning('不能修改当前登录账号的工号，请用其他管理员账号操作')
    return
  }
  dialog.saving = true
  try {
    if (dialog.isNew) {
      await api.adminCreateUser({
        emp_id: empId,
        name: dialog.name.trim(),
        password: dialog.password,
        role: dialog.role,
      })
      ElMessage.success('用户已创建（首次登录需修改口令）')
    } else {
      const body: Record<string, unknown> = { name: dialog.name.trim(), role: dialog.role, active: dialog.active }
      if (renamed) body.emp_id = empId
      if (dialog.password) body.password = dialog.password
      // 用原工号定位记录，改名后后端会返回新工号
      await api.adminUpdateUser(dialog.origEmpId, body)
      if (renamed) ElMessage.success(`工号已改为 ${empId}，历史记录归属已同步`)
      else ElMessage.success(dialog.password ? '已保存，并重置口令（下次登录需改密）' : '已保存')
    }
    dialog.visible = false
    await load()
  } finally {
    dialog.saving = false
  }
}

async function toggleActive(row: UserAdmin) {
  const next = row.active ? 0 : 1
  try {
    await api.adminUpdateUser(row.emp_id, { active: next })
    // 停用是「收权」动作，用红色提示与成功态区分开
    if (next) ElMessage.success('已启用')
    else ElMessage.error('已停用')
    await load()
  } catch {
    /* 自保护场景由后端返回 400，拦截器已提示 */
  }
}

async function resetPwd(row: UserAdmin) {
  try {
    const { value } = await ElMessageBox.prompt(
      `为「${row.name}（${row.emp_id}）」设置新的初始口令（至少 6 位，下次登录需改密）：`,
      '重置口令',
      { inputType: 'password', inputValidator: (v: string) => (v && v.length >= 6) || '至少 6 位' },
    )
    await api.adminUpdateUser(row.emp_id, { password: value })
    ElMessage.success('口令已重置')
    await load()
  } catch {
    /* 取消 */
  }
}

const isSelf = (row: UserAdmin) => row.emp_id === me.profile?.emp_id

async function removeUser(row: UserAdmin) {
  try {
    await ElMessageBox.confirm(
      `确认移除账号「${row.name}（${row.emp_id}）」？\n账号将无法再登录；其历史转产记录与照片保留，只是不再归属任何账号。`,
      '移除账号',
      { type: 'warning', confirmButtonText: '确认移除', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  await api.adminDeleteUser(row.emp_id)
  ElMessage.error('账号已移除')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="head-title">
      <h2 class="title">用户管理</h2>
      <p class="hint">账号由管理员创建并分配初始口令；首次登录强制修改，角色分为「产线用户」与「管理员」。</p>
    </div>

    <div class="card panel">
      <div class="toolbar">
        <el-button type="primary" :icon="'Plus'" @click="openNew">新增用户</el-button>
        <span class="note">共 {{ rows.length }} 个账号</span>
      </div>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="emp_id" label="工号" width="112" />
        <el-table-column prop="name" label="姓名" width="118">
          <template #default="{ row }">
            {{ row.name }}
            <el-tag v-if="isSelf(row)" size="small" type="warning" effect="plain">当前登录</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="102">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'warning' : 'primary'" size="small" effect="plain">
              {{ row.role === 'admin' ? '管理员' : '产线用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="94">
          <template #default="{ row }">
            <el-tag :type="row.active ? 'success' : 'info'" size="small" effect="plain">
              {{ row.active ? '启用' : '停用' }}
            </el-tag>
            <el-tag v-if="row.must_change_password" size="small" type="warning" effect="plain" style="margin-left: 4px">
              待改密
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="136">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="228">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="resetPwd(row)">重置</el-button>
            <el-button link :type="row.active ? 'danger' : 'success'" :disabled="isSelf(row)" @click="toggleActive(row)">
              {{ row.active ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" :disabled="isSelf(row)" @click="removeUser(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog.visible" :title="dialog.isNew ? '新增用户' : `编辑用户 · ${dialog.origEmpId}`" width="min(480px, 94vw)" :append-to-body="true" class="user-form-dialog">
      <el-form label-width="88px" @submit.prevent>
        <el-form-item label="工号" required>
          <el-input
            v-model="dialog.emp_id"
            :disabled="!dialog.isNew && dialog.origEmpId === me.profile?.emp_id"
            placeholder="如 00660301"
          />
          <div v-if="!dialog.isNew" class="note emp-note">
            {{ dialog.origEmpId === me.profile?.emp_id
              ? '当前登录账号的工号不可修改。'
              : '改工号会同步更新其历史转产记录的归属，改完该账号需重新登录。' }}
          </div>
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="dialog.name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="dialog.role" style="width: 100%">
            <el-option label="产线用户" value="line" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!dialog.isNew" label="状态">
          <el-switch v-model="dialog.active" :active-value="1" :inactive-value="0" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item :label="dialog.isNew ? '初始口令' : '重置口令'">
          <el-input
            v-model="dialog.password"
            type="password"
            show-password
            :placeholder="dialog.isNew ? '至少 6 位' : '留空则不修改'"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.title { margin: 0 0 4px; font-size: 20px; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.emp-note { width: 100%; margin-top: 4px; line-height: 1.5; }

</style>
<style>
/* 用户新增/编辑弹窗：el-dialog 与 user-form-dialog 为同一元素，直接选择自身 */
.user-form-dialog {
  width: min(480px, 94vw) !important;
  max-width: 94vw !important;
  max-height: 90vh !important;
  display: flex !important;
  flex-direction: column !important;
  box-sizing: border-box;
  margin: 5vh auto !important;
}
.user-form-dialog .el-dialog__header { flex-shrink: 0; }
.user-form-dialog .el-dialog__body {
  padding: 18px 20px 6px;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  -webkit-overflow-scrolling: touch;
}
.user-form-dialog .el-dialog__footer { flex-shrink: 0; }
.user-form-dialog .el-form { width: 100%; max-width: 100%; }
.user-form-dialog .el-form-item {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  margin-right: 0;
}
.user-form-dialog .el-form-item__label {
  flex: 0 0 auto !important;
  width: 88px !important;
  max-width: 88px !important;
  white-space: nowrap !important;
}
.user-form-dialog .el-form-item__content {
  flex: 1 1 auto;
  min-width: 0;
  width: auto !important;
}
.user-form-dialog .el-input,
.user-form-dialog .el-select {
  width: 100% !important;
  max-width: 100%;
  min-width: 0;
}
.user-form-dialog .el-form-item__label .el-form-item__error {
  width: 100%;
  white-space: normal;
  text-overflow: clip;
}

</style>

