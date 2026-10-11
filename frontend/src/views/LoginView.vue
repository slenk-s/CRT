<script setup lang="ts">
import { onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const router = useRouter()
const route = useRoute()

const form = reactive({ emp_id: '', password: '' })
const loading = ref(false)
const launching = ref(false)
const loginError = ref('')
const loginErrorVisible = ref(false)
let loginErrorTimer: ReturnType<typeof setTimeout> | undefined

function closeLoginError() {
  if (loginErrorTimer) clearTimeout(loginErrorTimer)
  loginError.value = ''
  loginErrorVisible.value = false
}

function showLoginError(message: string) {
  if (loginErrorTimer) clearTimeout(loginErrorTimer)
  loginError.value = message || '登录失败，请稍后重试'
  loginErrorVisible.value = true
  const hideTimer = setTimeout(() => {
    loginErrorVisible.value = false
    loginErrorTimer = setTimeout(() => {
      loginError.value = ''
      loginErrorVisible.value = false
    }, 1400)
  }, 1000)
  loginErrorTimer = hideTimer
}

onUnmounted(() => {
  if (loginErrorTimer) clearTimeout(loginErrorTimer)
})

function errorMessage(err: unknown): string {
  const detail = (err as any)?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  const message = (err as any)?.message
  if (typeof message === 'string' && message.trim()) return message.trim()
  const status = (err as any)?.response?.status
  if (status === 401) return '工号或口令错误'
  if (status === 423 || status === 403) return '该账号当前不可登录，请联系管理员'
  if (!(err as any)?.response) return '网络连接异常，请稍后重试'
  return '登录失败（' + status + '）'
}

async function submit() {
  if (!form.emp_id.trim() || !form.password) {
    showLoginError('请输入工号与口令')
    return
  }
  loginError.value = ''
  loading.value = true
  try {
    await user.login(form.emp_id.trim(), form.password)
    launching.value = true
    await new Promise((resolve) => setTimeout(resolve, 520))
    const redirect = (route.query.redirect as string) || '/changeover'
    router.replace(redirect)
  } catch (err) {
    showLoginError(errorMessage(err))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap" :class="{ launching }">
    <div class="login-stage">
      <div class="aurora aurora-1"></div>
      <div class="aurora aurora-2"></div>
      <div class="aurora aurora-3"></div>

      <div class="login-card">
        <div class="login-card-glow"></div>
        <div class="login-content">
          <div class="login-head">
            <div class="logo">转</div>
            <h1>产线转产管理</h1>
            <p>惠州 TV 工厂 · 转产记录 / WB 参数查询</p>
          </div>

          <form class="login-form" @submit.prevent="submit">
            <label class="field">
              <span>工号</span>
              <span class="field-box">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-4 0-7 2.2-7 5v1h14v-1c0-2.8-3-5-7-5Z" /></svg>
                <input v-model="form.emp_id" autocomplete="username" placeholder="请输入工号（如 00660301）" />
              </span>
            </label>

            <label class="field">
              <span>口令</span>
              <span class="field-box">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 9V7a5 5 0 1 0-10 0v2H5v11h14V9h-2ZM9 7a3 3 0 1 1 6 0v2H9V7Z" /></svg>
                <input v-model="form.password" type="password" autocomplete="current-password" placeholder="请输入口令" />
              </span>
            </label>

            <button class="login-btn" type="submit" :disabled="loading">
              <span class="btn-shine"></span>
              <span class="btn-label">{{ loading ? '登录中…' : '登录' }}</span>
              <svg v-if="loading" class="spinner" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /></svg>
            </button>
          </form>

          <p class="tip">首次登录使用管理员分配的初始口令，登录后请及时修改。</p>
        </div>
      </div>

      <div v-if="loginError" class="login-alert" :class="{ leaving: !loginErrorVisible }" role="alert" @click="closeLoginError">
        <div class="login-alert-card">
          <div class="login-alert-head">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 1 21h22L12 2Zm0 6c.6 0 1 .4 1 1v5.6c0 .6-.4 1-1 1s-1-.4-1-1V9c0-.6.4-1 1-1Zm0 9.2c.7 0 1.2.5 1.2 1.1s-.5 1.1-1.2 1.1-1.2-.5-1.2-1.1.5-1.1 1.2-1.1Z" /></svg>
            <span>登录提示</span>
          </div>
          <p>{{ loginError }}</p>
        </div>
      </div>

      <div class="login-footer">
        <span>PCC v1.0</span>
        <span>Secure Local Sign-in</span>
      </div>
      <div class="login-rise-veil" :class="{ active: launching }"></div>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 26px 16px;
  color: #eaf6ff;
  background:
    radial-gradient(circle at 16% 14%, rgba(63, 208, 255, .34), transparent 28%),
    radial-gradient(circle at 82% 18%, rgba(124, 92, 255, .32), transparent 34%),
    radial-gradient(circle at 50% 88%, rgba(0, 255, 196, .18), transparent 34%),
    linear-gradient(145deg, #07101d 0%, #0c1728 42%, #142847 78%, #08111f 100%);
  overflow: hidden;
  position: relative;
  isolation: isolate;
}
.login-wrap::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -2;
  background-image:
    linear-gradient(rgba(255, 255, 255, .045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, .035) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(circle at center, black 0%, transparent 72%);
}
.login-stage {
  position: relative;
  width: min(440px, 100%);
}
.aurora {
  position: absolute;
  border-radius: 999px;
  filter: blur(46px);
  opacity: .42;
  z-index: -1;
  pointer-events: none;
  animation: aurora-drift 9s ease-in-out infinite alternate;
}
.aurora-1 { width: 260px; height: 260px; top: -110px; left: -70px; background: #30d5ff; }
.aurora-2 { width: 240px; height: 240px; right: -90px; top: 10px; background: #8b5cf6; animation-delay: -2s; }
.aurora-3 { width: 310px; height: 310px; left: 40%; bottom: -170px; background: #2dd4bf; opacity: .24; animation-delay: -4s; }
@keyframes aurora-drift {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to   { transform: translate3d(18px, -12px, 0) scale(1.12); }
}
.login-card {
  position: relative;
  border-radius: 28px;
  padding: 2px;
  background: conic-gradient(from 140deg, rgba(45, 212, 191, .55), rgba(56, 189, 248, .25) 25%, rgba(139, 92, 246, .52) 55%, rgba(45, 212, 191, .38));
  box-shadow: 0 34px 80px rgba(0, 0, 0, .48), 0 0 0 1px rgba(255,255,255,.04);
}
.login-card-glow {
  position: absolute;
  inset: -58px -42px -58px -42px;
  border-radius: 60px;
  background:
    radial-gradient(circle at 18% 18%, rgba(45, 212, 191, .25), transparent 34%),
    radial-gradient(circle at 80% 32%, rgba(99, 102, 241, .24), transparent 36%),
    radial-gradient(circle at 50% 96%, rgba(56, 189, 248, .22), transparent 38%);
  filter: blur(34px);
  opacity: .72;
  z-index: -1;
  pointer-events: none;
}
.login-content {
  position: relative;
  border-radius: 26px;
  padding: 34px 28px 26px;
  background:
    linear-gradient(160deg, rgba(12, 23, 40, .92), rgba(20, 40, 71, .88) 55%, rgba(8, 17, 31, .94)),
    radial-gradient(circle at 80% 12%, rgba(99, 102, 241, .16), transparent 42%);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(255, 255, 255, .08);
}
.login-head {
  display: grid;
  justify-items: center;
  gap: 6px;
  margin-bottom: 24px;
}
.logo {
  width: 62px;
  height: 62px;
  margin-bottom: 7px;
  border-radius: 20px;
  display: grid;
  place-items: center;
  color: white;
  font-size: 30px;
  font-weight: 900;
  background: linear-gradient(145deg, #06b6d4, #6366f1 55%, #8b5cf6);
  box-shadow: 0 12px 30px rgba(99, 102, 241, .42), inset 0 1px 0 rgba(255,255,255,.3);
}
.login-head h1 {
  margin: 0;
  font-size: 23px;
  letter-spacing: 1px;
  background: linear-gradient(90deg, #a5f3fc, #c7d2fe);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.login-head p {
  margin: 0;
  color: rgba(198, 224, 245, .68);
  font-size: 13px;
}
.login-form {
  display: grid;
  gap: 14px;
}
.field {
  display: grid;
  gap: 7px;
}
.field > span:first-child {
  font-size: 12px;
  color: rgba(205, 229, 255, .78);
  font-weight: 700;
}
.field-box {
  position: relative;
  display: block;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.13);
  background: rgba(255,255,255,.06);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 10px 24px rgba(0,0,0,.18);
  overflow: hidden;
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s cubic-bezier(.34,1.56,.64,1);
}
.field-box:focus-within {
  border-color: rgba(103, 232, 249, .75);
  box-shadow: 0 0 0 4px rgba(34, 211, 238, .16), inset 0 1px 0 rgba(255,255,255,.12);
}
.field-box svg {
  position: absolute;
  left: 14px;
  top: 50%;
  width: 18px;
  height: 18px;
  fill: rgba(186, 230, 253, .72);
  transform: translateY(-50%);
  pointer-events: none;
}
.field-box input {
  width: 100%;
  height: 50px;
  border: 0;
  outline: 0;
  padding: 0 16px 0 44px;
  border-radius: 14px;
  color: #f4fbff;
  background: transparent;
  font: inherit;
}
.field-box input::placeholder { color: rgba(203, 225, 245, .42); }
.login-btn {
  position: relative;
  height: 52px;
  border: 0;
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: white;
  font-weight: 800;
  font-size: 15px;
  letter-spacing: .8px;
  background: linear-gradient(135deg, #22d3ee, #3b82f6 52%, #8b5cf6);
  box-shadow: 0 16px 34px rgba(59, 130, 246, .36), inset 0 1px 0 rgba(255,255,255,.28);
  transition: transform .18s cubic-bezier(.34,1.56,.64,1), box-shadow .18s ease, filter .18s ease;
}
.login-btn::before {
  content: '';
  position: absolute;
  inset: 1px;
  border-radius: 15px;
  background: linear-gradient(90deg, rgba(255,255,255,.18), transparent 42%, rgba(255,255,255,.12));
  opacity: .4;
}
.btn-shine {
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 38%, rgba(255,255,255,.42) 50%, transparent 62%);
  transform: translateX(-120%);
  animation: btn-shine 5.2s linear infinite;
}
@keyframes btn-shine {
  0% { transform: translateX(-120%); }
  50%, 100% { transform: translateX(120%); }
}
.btn-label { position: relative; z-index: 1; }
.login-btn:hover { filter: brightness(1.06); transform: translateY(-1px); box-shadow: 0 20px 42px rgba(59, 130, 246, .44); }
.login-btn:active:not(:disabled) { transform: scale(.96); box-shadow: inset 0 6px 16px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.08); }
.login-btn:disabled { opacity: .78; cursor: not-allowed; }
.spinner {
  position: relative;
  z-index: 1;
  width: 17px;
  height: 17px;
  fill: none;
  stroke: white;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-dasharray: 38 22;
  animation: spin .72s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.tip {
  margin: 16px 0 0;
  color: rgba(194, 219, 242, .58);
  font-size: 12px;
  text-align: center;
}
.login-footer {
  position: absolute;
  inset: auto 0 -48px 0;
  display: flex;
  justify-content: space-between;
  padding: 0 4px;
  color: rgba(213, 235, 255, .48);
  font-size: 11px;
  letter-spacing: .5px;
}
@media (max-width: 420px) {
  .login-content { padding: 28px 18px 22px; }
  .login-head h1 { font-size: 21px; }
  .field-box, .login-btn { height: 48px; }
}
.login-alert {
  position: absolute;
  inset: -100px -22px auto -22px;
  z-index: 6;
  display: grid;
  place-items: center;
  pointer-events: none;
}
.login-alert-card {
  pointer-events: auto;
  width: min(408px, calc(100vw - 48px));
  padding: 14px 16px;
  border: 1px solid rgba(255, 177, 90, .46);
  border-radius: 18px;
  background:
    linear-gradient(145deg, rgba(18, 31, 53, .94), rgba(43, 33, 86, .9)),
    linear-gradient(135deg, rgba(255, 177, 90, .12), rgba(139, 92, 246, .16));
  box-shadow:
    0 18px 36px rgba(0, 0, 0, .34),
    0 0 0 1px rgba(255, 255, 255, .06) inset,
    0 0 28px rgba(255, 177, 90, .18);
  backdrop-filter: blur(16px);
  cursor: pointer;
  animation: login-alert-in .22s cubic-bezier(.34, 1.3, .5, 1);
  transition: opacity .9s ease 1.1s, transform .9s ease 1.1s;
}

.login-alert.leaving .login-alert-card {
  animation: none;
  opacity: 0;
  transform: translateY(-8px) scale(.98);
  filter: brightness(.92);
}
.login-alert-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  color: #ffdf9e;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: .6px;
}
.login-alert-head svg {
  width: 18px;
  height: 18px;
  fill: rgba(255, 199, 102, .9);
  filter: drop-shadow(0 0 8px rgba(255, 177, 90, .38));
}
.login-alert-card p {
  margin: 0;
  color: rgba(255, 248, 235, .92);
  font-size: 13px;
  line-height: 1.55;
}
@keyframes login-alert-in {
  from { opacity: 0; transform: translateY(-10px) scale(.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>

<style scoped>
.login-rise-veil {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  height: 0;
  z-index: 40;
  pointer-events: none;
  background:
    radial-gradient(circle at 14% 52%, rgba(64, 189, 255, .30), transparent 36%),
    radial-gradient(circle at 74% 48%, rgba(139, 92, 246, .28), transparent 42%),
    radial-gradient(circle at 50% 118%, rgba(45, 212, 191, .18), transparent 38%),
    linear-gradient(145deg, #07101d 0%, #0c1728 42%, #142847 78%, #08111f 100%);
  box-shadow: 0 -18px 60px rgba(56, 189, 248, .22);
  transform: translateY(0);
  opacity: 0;
  transition: height .52s cubic-bezier(.34,1.2,.5,1), opacity .18s ease .16s, transform .52s cubic-bezier(.34,1.2,.5,1);
}
.login-wrap { transition: transform .52s cubic-bezier(.34,1.2,.5,1), filter .52s ease, opacity .52s ease; }
.login-wrap.launching { transform: translateY(-28px) scale(1.01); filter: brightness(1.02); }
.login-rise-veil.active {
  height: 100vh;
  opacity: 1;
  transform: translateY(0);
}
.login-rise-veil.active::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -48px;
  width: min(860px, 94vw);
  height: 150px;
  transform: translateX(-50%) scale(.96);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(56, 189, 248, .62) 0%, rgba(99, 102, 241, .38) 35%, transparent 70%);
  filter: blur(42px);
  opacity: .72;
  animation: topbar-glow-breathe 3.6s ease-in-out infinite;
}
</style>
