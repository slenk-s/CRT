<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import { useUserStore } from '@/stores/user'
import SmbStatusBadge from '@/components/SmbStatusBadge.vue'

const user = useUserStore()
const route = useRoute()
const mobileMenu = ref(false)
const userPanel = ref(false)
const router = useRouter()

const who = computed(() => user.profile?.name || user.profile?.emp_id || '—')

// ---------------- 修改口令 ----------------
const pwdVisible = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })
const pwdSaving = ref(false)
const forced = computed(() => user.profile?.must_change_password === 1)

watch(
  () => user.profile?.must_change_password,
  (v) => {
    if (v === 1) {
      pwdVisible.value = true
      ElMessage.warning('首次登录（或口令被重置），请先修改口令')
    }
  },
  { immediate: true },
)

function openPwd() {
  userPanel.value = false
  pwdForm.old_password = ''
  pwdForm.new_password = ''
  pwdForm.confirm = ''
  pwdVisible.value = true
}

async function submitPwd() {
  if (!pwdForm.old_password || pwdForm.new_password.length < 6) {
    ElMessage.warning('新口令至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新口令不一致')
    return
  }
  pwdSaving.value = true
  try {
    await api.changePassword(pwdForm.old_password, pwdForm.new_password)
    ElMessage.success('口令已更新')
    pwdVisible.value = false
    await user.fetchMe().catch(() => {})
  } finally {
    pwdSaving.value = false
  }
}

// ---------------- 所属车间 ----------------
const wsVisible = ref(false)
const wsSaving = ref(false)
const wsForm = reactive({ workshop: '' })
const workshops = ref<string[]>([])
const wsLabel = computed(() => user.profile?.workshop || '全部车间')

async function openWorkshop() {
  userPanel.value = false
  wsForm.workshop = user.profile?.workshop || ''
  wsVisible.value = true
  if (!workshops.value.length) {
    try {
      workshops.value = Object.keys((await api.dictLines()).by_workshop)
    } catch {
      /* 提示由拦截器统一处理 */
    }
  }
}

async function submitWorkshop() {
  wsSaving.value = true
  try {
    user.profile = await api.setWorkshop(wsForm.workshop)
    ElMessage.success(wsForm.workshop ? `所属车间已设为「${wsForm.workshop}」` : '已取消车间限定')
    wsVisible.value = false
  } finally {
    wsSaving.value = false
  }
}

// ---------------- 退出 ----------------
async function doLogout() {
  userPanel.value = false
  try {
    await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  } catch {
    return
  }
  user.logout()
  router.push('/login')
}
</script>

<template>
  <header class="topbar">
    <button class="menu-toggle" type="button" aria-label="打开菜单" @click="mobileMenu = true">
      <el-icon size="22"><Operation /></el-icon>
    </button>

    <div class="brand"><span class="brand-title">产线转产</span><span class="brand-sub">管理</span></div>

    <!-- SMB 连接状态：顶部标题栏居中（绿=已连接 / 红=离线） -->
    <div class="smb-slot">
      <SmbStatusBadge />
    </div>

    <button
      class="user-dropdown who"
      type="button"
      aria-haspopup="dialog"
      :aria-expanded="userPanel"
      @click="userPanel = true"
    >
      <el-icon><User /></el-icon>
      <b class="who-name">{{ who }}</b>
      <el-tag v-if="user.isAdmin" class="admin-tag" size="small" type="warning" effect="dark">管理员</el-tag>
      <el-icon class="user-caret"><ArrowDown /></el-icon>
    </button>
  </header>

  <transition name="nav-pop">
    <div v-if="mobileMenu" class="nav-overlay">
      <div class="nav-backdrop" @click="mobileMenu = false"></div>
      <aside class="nav-panel" role="dialog" aria-label="移动端导航">
        <div class="panel-header">
          <div class="brand"><span class="brand-title">产线转产</span><span class="brand-sub">管理</span></div>
          <button class="close-x" type="button" aria-label="关闭菜单" @click="mobileMenu = false">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <nav class="nav-list" aria-label="移动端导航">
          <router-link to="/changeover" @click="mobileMenu = false">转产记录</router-link>
          <router-link to="/changeover/new" @click="mobileMenu = false">新建转产</router-link>
          <router-link to="/wb" @click="mobileMenu = false">参数查询</router-link>
          <router-link v-if="user.isAdmin" to="/stats" @click="mobileMenu = false">条目统计</router-link>
          <router-link v-if="user.isAdmin" to="/admin/dicts" @click="mobileMenu = false">字典管理</router-link>
          <router-link v-if="user.isAdmin" to="/admin/users" @click="mobileMenu = false">用户管理</router-link>
        </nav>
      </aside>
    </div>
  </transition>

  <!-- 用户菜单：与左侧导航同一套面板样式，从右上角滑出 -->
  <transition name="nav-pop">
    <div v-if="userPanel" class="nav-overlay nav-overlay--user">
      <div class="nav-backdrop" @click="userPanel = false"></div>
      <aside class="nav-panel" role="dialog" aria-label="用户菜单">
        <div class="panel-header">
          <div class="brand">
            <span class="brand-title">{{ who }}</span>
            <span class="brand-sub">{{ user.isAdmin ? '管理员' : '线体' }} · {{ user.profile?.emp_id }}</span>
          </div>
          <button class="close-x" type="button" aria-label="关闭菜单" @click="userPanel = false">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <nav class="nav-list" aria-label="用户菜单">
          <button class="nav-item" type="button" @click="openWorkshop">
            所属车间<span class="nav-item-val">{{ wsLabel }}</span>
          </button>
          <button class="nav-item" type="button" @click="openPwd">修改口令</button>
          <button class="nav-item" type="button" @click="doLogout">退出登录</button>
        </nav>
      </aside>
    </div>
  </transition>

  <main class="main-shell">
    <router-view v-slot="{ Component }">
      <transition name="router-fade" mode="out-in">
        <component :is="Component" :key="route.fullPath" class="route-stage" />
      </transition>
    </router-view>
  </main>

  <el-dialog
    v-model="pwdVisible"
    :title="forced ? '首次登录，请修改口令' : '修改口令'"
    width="420px"
    class="fluid-morph-dialog"
    :close-on-click-modal="!forced"
    :show-close="!forced"
    :close-on-press-escape="!forced"
  >
    <el-alert
      v-if="forced"
      type="warning"
      :closable="false"
      show-icon
      title="为保障账号安全，首次登录必须设置新口令后方可继续使用。"
      class="mb"
    />
    <el-form label-width="86px" @submit.prevent>
      <el-form-item label="原口令">
        <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="请输入当前口令" />
      </el-form-item>
      <el-form-item label="新口令">
        <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" />
      </el-form-item>
      <el-form-item label="确认新口令">
        <el-input v-model="pwdForm.confirm" type="password" @keyup.enter="submitPwd" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button v-if="!forced" @click="pwdVisible = false">取消</el-button>
      <el-button v-else @click="doLogout">退出登录</el-button>
      <el-button type="primary" :loading="pwdSaving" @click="submitPwd">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="wsVisible" title="所属车间" width="420px" class="fluid-morph-dialog">
    <p class="hint ws-hint">
      选定后，新建转产与转产记录列表的线体下拉只展示该车间的线体；选择「全部车间」则不限制。
    </p>
    <el-select v-model="wsForm.workshop" placeholder="全部车间（不限定）" style="width: 100%">
      <el-option label="全部车间（不限定）" value="" />
      <el-option v-for="w in workshops" :key="w" :label="w" :value="w" />
    </el-select>
    <template #footer>
      <el-button @click="wsVisible = false">取消</el-button>
      <el-button type="primary" :loading="wsSaving" @click="submitWorkshop">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.main-shell { padding-top: 8px; }
.route-stage { }
.brand { display: flex; align-items: baseline; gap: 4px; min-width: 0; }
.brand-title { color: #fff; font-weight: 700; }
.brand-sub { color: #a3b1c2; font-size: 12px; font-weight: 500; }
.user-dropdown { display: inline-flex; }
.who {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 9px; border-radius: 999px;
  border: 0; background: transparent; color: inherit; font: inherit; cursor: pointer;
  transition: background .18s ease, transform .18s cubic-bezier(.34,1.56,.64,1);
}
.who:hover { background: rgba(255,255,255,.1); }
.who:active { transform: scale(.96); }
.who-name { color: #fff; font-weight: 700; }
.admin-tag { padding: 0 6px; height: 20px; line-height: 18px; border-radius: 999px; }
.user-caret { font-size: 12px; color: #c0c4cc; }
.ws-hint { margin: 0 0 12px; line-height: 1.6; }
.el-drawer { animation: drawer-slide .38s cubic-bezier(0.34, 1.56, 0.64, 1); }
@keyframes drawer-slide {
  from { transform: translateX(-100%); opacity: .4; }
  to   { transform: translateX(0);      opacity: 1; }
}
.nav-overlay {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  padding: 74px 0 0 24px;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(6px);
  animation: overlay-fade .22s ease-out;
}

/* 铺满整个浮层，作为「点击空白处关闭」的落点。
   面板是 position:relative + z-index:1，仍在其上方，点面板不会触发关闭。
   原先写成 static，等于一个零尺寸空 div，关闭逻辑根本点不到。 */
.nav-backdrop { position: absolute; inset: 0; }

/* 用户菜单从右上角滑出（触发器在标题栏右侧） */
.nav-overlay--user { justify-content: flex-end; padding: 74px 24px 0 0; }
.nav-overlay--user .nav-panel {
  width: min(280px, calc(100vw - 48px));
  min-height: 0;
  animation: panel-slide-in-right .42s cubic-bezier(.2, 1.1, .35, 1);
}
@keyframes panel-slide-in-right {
  from { transform: translate(8px, -6px) scale(.96); opacity: 0; }
  to   { transform: translate(0, 0) scale(1); opacity: 1; }
}

.nav-panel {
  position: relative;
  z-index: 1;
  width: min(300px, calc(100vw - 48px));
  height: auto;
  min-height: 360px;
  max-height: calc(100vh - 112px);
  padding: 18px 16px;
  border-radius: 18px;
  background: var(--card);
  box-shadow: 0 22px 54px rgba(15, 23, 42, 0.20), inset 0 1px 0 rgba(255, 255, 255, 0.72);
  border: 1px solid var(--border-l);
  animation: panel-slide-in .42s cubic-bezier(.2, 1.1, .35, 1);
}

.nav-panel .panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 0 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border-l);
}

.nav-panel .brand { display: flex; align-items: baseline; gap: 6px; }
.nav-panel .brand-title { color: var(--topbar); font-size: 16px; font-weight: 800; }
.nav-panel .brand-sub { color: #a3b1c2; font-size: 12px; font-weight: 500; }

.close-x {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 8px;
  background: #f3f6fb;
  color: var(--text2);
  cursor: pointer;
  transition: transform .18s ease, background .18s ease, color .18s ease;
}

.close-x:hover { background: #e8edf5; color: var(--text); }
.close-x:active { transform: scale(.96); }

.nav-list { display: flex; flex-direction: column; gap: 8px; }

.nav-list a,
.nav-list .nav-item {
  position: relative;
  overflow: hidden;
  padding: 12px 14px;
  border-radius: 10px;
  background: #f6f8fb;
  color: var(--text);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  border: 1px solid transparent;
  transition: transform .18s cubic-bezier(.34, 1.56, .64, 1), background .18s ease, box-shadow .18s ease, color .18s ease;
  animation: nav-item-in .32s ease-out both;
}

/* 按钮版条目：撑满一行、文字左对齐，与链接保持一致 */
.nav-list .nav-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
  line-height: 1.4;
}
.nav-item-val { color: var(--text3); font-size: 12.5px; font-weight: 500; }

.nav-list a:nth-child(1),
.nav-list .nav-item:nth-child(1) { animation-delay: .04s; }
.nav-list a:nth-child(2),
.nav-list .nav-item:nth-child(2) { animation-delay: .09s; }
.nav-list a:nth-child(3),
.nav-list .nav-item:nth-child(3) { animation-delay: .14s; }
.nav-list a:nth-child(4),
.nav-list .nav-item:nth-child(4) { animation-delay: .19s; }
.nav-list a:nth-child(5),
.nav-list .nav-item:nth-child(5) { animation-delay: .24s; }
.nav-list a:nth-child(6),
.nav-list .nav-item:nth-child(6) { animation-delay: .29s; }

.nav-list a::after,
.nav-list .nav-item::after {
  content: '';
  position: absolute;
  inset: auto -20% -70% -20%;
  height: 60%;
  background: radial-gradient(circle, rgba(64, 158, 255, 0.20), transparent 68%);
  filter: blur(18px);
  opacity: 0;
  transition: opacity .18s ease;
}

.nav-list a:hover,
.nav-list .nav-item:hover {
  transform: translateY(-2px);
  background: #fff;
  border-color: #e3eaf3;
  box-shadow: 0 12px 24px rgba(31, 45, 61, 0.08);
}

.nav-list a:active,
.nav-list .nav-item:active { transform: scale(.96); }
.nav-list a.router-link-active { background: var(--primary); color: #fff; border-color: var(--primary); }
.nav-list a.router-link-active::after { opacity: .42; }

@keyframes overlay-fade {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes panel-slide-in {
  from { transform: translate(-8px, -6px) scale(.96); opacity: 0; }
  to   { transform: translate(0, 0) scale(1); opacity: 1; }
}

@keyframes nav-item-in {
  from { transform: translateY(10px); opacity: 0; }
  to   { transform: translateY(0); opacity: 1; }
}

.nav-pop-enter-active,
.nav-pop-leave-active {
  transition: opacity .22s ease-out, transform .3s cubic-bezier(.2, 1.1, .35, 1);
  transform-origin: 0 0;
}

.nav-pop-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(.94);
}

.nav-pop-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(.94);
}

.el-popover.el-dropdown__popper {
  animation: origin-pop .24s cubic-bezier(.34,1.42,.55,1);
  transform-origin: top right;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 18px 42px rgba(31,45,61,.18);
}
</style>


