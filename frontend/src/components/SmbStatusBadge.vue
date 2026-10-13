<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api'

/** 顶部标题栏 SMB 状态标：轮询 /api/health 展示共享盘连通性。
 *  外观取自 uiverse 动态光晕按钮（结构与动画原样保留），文字放在样式内部：
 *  绿色=已连接 / 红色=离线 / 蓝色=检测中。 */
type State = 'online' | 'offline' | 'checking'

const POLL_MS = 15000
const POLL_FAST_MS = 3000   // 检测中时加快轮询，让结果尽快落定

const state = ref<State>('checking')
const message = ref('正在检测共享盘…')
const pending = ref(0)
let timer: number | undefined

async function refresh() {
  try {
    const h = await api.health()
    pending.value = Number(h?.pending_sync) || 0
    // checked_at 为空表示后端尚未完成首次探测（探测在后台线程进行）
    if (h?.smb && typeof h.smb.ok === 'boolean' && h.smb.checked_at) {
      state.value = h.smb.ok ? 'online' : 'offline'
      message.value = h.smb.message || (h.smb.ok ? 'SMB 已连接' : 'SMB 离线')
    } else {
      state.value = 'checking'
      message.value = h?.smb?.message || 'SMB 状态检测中'
    }
  } catch {
    // 取不到状态时不要断言「离线」——可能只是后端刚重启、首次探测还没跑完。
    // 只有后端明确给出判定（checked_at 有值）才显示在线/离线。
    state.value = 'checking'
    message.value = '暂时取不到 SMB 状态，稍后自动重试'
  }
}

function schedule() {
  if (timer !== undefined) window.clearTimeout(timer)
  timer = window.setTimeout(async () => {
    await refresh()
    schedule()
  }, state.value === 'checking' ? POLL_FAST_MS : POLL_MS)
}

onMounted(async () => {
  await refresh()
  schedule()
})

onBeforeUnmount(() => {
  if (timer !== undefined) window.clearTimeout(timer)
})

const head = computed(() =>
  state.value === 'online' ? 'SMB 已连接' : state.value === 'offline' ? 'SMB 离线' : 'SMB 检测中',
)
const sub = computed(() => (pending.value > 0 ? `待同步 ${pending.value} 张` : ''))
</script>

<template>
  <div class="uiverse smb-status" :class="`is-${state}`" :title="message" role="status" aria-live="polite">
    <div class="wrapper">
      <span class="smb-label">
        <b class="smb-head">{{ head }}</b>
        <i v-if="sub" class="smb-sub">{{ sub }}</i>
      </span>
      <div class="circle circle-12"></div>
      <div class="circle circle-11"></div>
      <div class="circle circle-10"></div>
      <div class="circle circle-9"></div>
      <div class="circle circle-8"></div>
      <div class="circle circle-7"></div>
      <div class="circle circle-6"></div>
      <div class="circle circle-5"></div>
      <div class="circle circle-4"></div>
      <div class="circle circle-3"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-1"></div>
    </div>
  </div>
</template>

<style scoped>
/* ============ 原组件样式：结构与动态效果原样保留 ============ */
.uiverse {
  --duration: 7s;
  --easing: linear;
  --c-color-1: rgba(255, 163, 26, 0.7);
  --c-color-2: #1a23ff;
  --c-color-3: #e21bda;
  --c-color-4: rgba(255, 232, 26, 0.7);
  --c-shadow: rgba(255, 223, 87, 0.5);
  --c-shadow-inset-top: rgba(255, 223, 52, 0.9);
  --c-shadow-inset-bottom: rgba(255, 250, 215, 0.8);
  --c-radial-inner: #ffd215;
  --c-radial-outer: #fff172;
  --c-color: #fff;
  -webkit-tap-highlight-color: transparent;
  -webkit-appearance: none;
  outline: none;
  position: relative;
  cursor: pointer;
  border: none;
  display: table;
  border-radius: 24px;
  padding: 0;
  margin: 0;
  text-align: center;
  font-weight: 600;
  font-size: 16px;
  letter-spacing: 0.02em;
  line-height: 1.5;
  color: var(--c-color);
  background: radial-gradient(
    circle,
    var(--c-radial-inner),
    var(--c-radial-outer) 80%
  );
  box-shadow: 0 0 14px var(--c-shadow);
}

.uiverse:before {
  content: "";
  pointer-events: none;
  position: absolute;
  z-index: 3;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  border-radius: 24px;
  box-shadow:
    inset 0 3px 12px var(--c-shadow-inset-top),
    inset 0 -3px 4px var(--c-shadow-inset-bottom);
}

.uiverse .wrapper {
  -webkit-mask-image: -webkit-radial-gradient(white, black);
  overflow: hidden;
  border-radius: 24px;
  min-width: 132px;
  padding: 12px 0;
}

.uiverse .wrapper span {
  display: inline-block;
  position: relative;
  z-index: 1;
}

.uiverse:hover {
  --duration: 1400ms;
}

.uiverse .wrapper .circle {
  position: absolute;
  left: 0;
  top: 0;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  filter: blur(var(--blur, 8px));
  background: var(--background, transparent);
  transform: translate(var(--x, 0), var(--y, 0)) translateZ(0);
  animation: var(--animation, none) var(--duration) var(--easing) infinite;
}

.uiverse .wrapper .circle.circle-1,
.uiverse .wrapper .circle.circle-9,
.uiverse .wrapper .circle.circle-10 {
  --background: var(--c-color-4);
}

.uiverse .wrapper .circle.circle-3,
.uiverse .wrapper .circle.circle-4 {
  --background: var(--c-color-2);
  --blur: 14px;
}

.uiverse .wrapper .circle.circle-5,
.uiverse .wrapper .circle.circle-6 {
  --background: var(--c-color-3);
  --blur: 16px;
}

.uiverse .wrapper .circle.circle-2,
.uiverse .wrapper .circle.circle-7,
.uiverse .wrapper .circle.circle-8,
.uiverse .wrapper .circle.circle-11,
.uiverse .wrapper .circle.circle-12 {
  --background: var(--c-color-1);
  --blur: 12px;
}

.uiverse .wrapper .circle.circle-1 {
  --x: 0;
  --y: -40px;
  --animation: circle-1;
}

.uiverse .wrapper .circle.circle-2 {
  --x: 92px;
  --y: 8px;
  --animation: circle-2;
}

.uiverse .wrapper .circle.circle-3 {
  --x: -12px;
  --y: -12px;
  --animation: circle-3;
}

.uiverse .wrapper .circle.circle-4 {
  --x: 80px;
  --y: -12px;
  --animation: circle-4;
}

.uiverse .wrapper .circle.circle-5 {
  --x: 12px;
  --y: -4px;
  --animation: circle-5;
}

.uiverse .wrapper .circle.circle-6 {
  --x: 56px;
  --y: 16px;
  --animation: circle-6;
}

.uiverse .wrapper .circle.circle-7 {
  --x: 8px;
  --y: 28px;
  --animation: circle-7;
}

.uiverse .wrapper .circle.circle-8 {
  --x: 28px;
  --y: -4px;
  --animation: circle-8;
}

.uiverse .wrapper .circle.circle-9 {
  --x: 20px;
  --y: -12px;
  --animation: circle-9;
}

.uiverse .wrapper .circle.circle-10 {
  --x: 64px;
  --y: 16px;
  --animation: circle-10;
}

.uiverse .wrapper .circle.circle-11 {
  --x: 4px;
  --y: 4px;
  --animation: circle-11;
}

.uiverse .wrapper .circle.circle-12 {
  --blur: 14px;
  --x: 52px;
  --y: 4px;
  --animation: circle-12;
}

@keyframes circle-1 {
  33% {
    transform: translate(0px, 16px) translateZ(0);
  }

  66% {
    transform: translate(12px, 64px) translateZ(0);
  }
}

@keyframes circle-2 {
  33% {
    transform: translate(80px, -10px) translateZ(0);
  }

  66% {
    transform: translate(72px, -48px) translateZ(0);
  }
}

@keyframes circle-3 {
  33% {
    transform: translate(20px, 12px) translateZ(0);
  }

  66% {
    transform: translate(12px, 4px) translateZ(0);
  }
}

@keyframes circle-4 {
  33% {
    transform: translate(76px, -12px) translateZ(0);
  }

  66% {
    transform: translate(112px, -8px) translateZ(0);
  }
}

@keyframes circle-5 {
  33% {
    transform: translate(84px, 28px) translateZ(0);
  }

  66% {
    transform: translate(40px, -32px) translateZ(0);
  }
}

@keyframes circle-6 {
  33% {
    transform: translate(28px, -16px) translateZ(0);
  }

  66% {
    transform: translate(76px, -56px) translateZ(0);
  }
}

@keyframes circle-7 {
  33% {
    transform: translate(8px, 28px) translateZ(0);
  }

  66% {
    transform: translate(20px, -60px) translateZ(0);
  }
}

@keyframes circle-8 {
  33% {
    transform: translate(32px, -4px) translateZ(0);
  }

  66% {
    transform: translate(56px, -20px) translateZ(0);
  }
}

@keyframes circle-9 {
  33% {
    transform: translate(20px, -12px) translateZ(0);
  }

  66% {
    transform: translate(80px, -8px) translateZ(0);
  }
}

@keyframes circle-10 {
  33% {
    transform: translate(68px, 20px) translateZ(0);
  }

  66% {
    transform: translate(100px, 28px) translateZ(0);
  }
}

@keyframes circle-11 {
  33% {
    transform: translate(4px, 4px) translateZ(0);
  }

  66% {
    transform: translate(68px, 20px) translateZ(0);
  }
}

@keyframes circle-12 {
  33% {
    transform: translate(56px, 0px) translateZ(0);
  }

  66% {
    transform: translate(60px, -32px) translateZ(0);
  }
}

/* ============ 状态配色：把原设计的金色系映射为绿 / 红 / 蓝 ============ */
.is-online {
  --c-color-1: rgba(34, 197, 94, 0.7);
  --c-color-2: #16a34a;
  --c-color-3: #22c55e;
  --c-color-4: rgba(187, 247, 208, 0.7);
  --c-shadow: rgba(74, 222, 128, 0.5);
  --c-shadow-inset-top: rgba(134, 239, 172, 0.9);
  --c-shadow-inset-bottom: rgba(220, 252, 231, 0.8);
  --c-radial-inner: #22c55e;
  --c-radial-outer: #86efac;
}
.is-offline {
  --c-color-1: rgba(239, 68, 68, 0.7);
  --c-color-2: #b91c1c;
  --c-color-3: #dc2626;
  --c-color-4: rgba(254, 202, 202, 0.7);
  --c-shadow: rgba(248, 113, 113, 0.5);
  --c-shadow-inset-top: rgba(252, 165, 165, 0.9);
  --c-shadow-inset-bottom: rgba(254, 226, 226, 0.8);
  --c-radial-inner: #ef4444;
  --c-radial-outer: #fca5a5;
}
.is-checking {
  --c-color-1: rgba(56, 189, 248, 0.7);
  --c-color-2: #0369a1;
  --c-color-3: #0ea5e9;
  --c-color-4: rgba(186, 230, 253, 0.7);
  --c-shadow: rgba(125, 211, 252, 0.5);
  --c-shadow-inset-top: rgba(186, 230, 253, 0.9);
  --c-shadow-inset-bottom: rgba(224, 242, 254, 0.8);
  --c-radial-inner: #38bdf8;
  --c-radial-outer: #bae6fd;
}

/* ============ 标题栏内的尺寸收窄（仅几何，不动动画） ============ */
.smb-status {
  display: table;
  cursor: default;
  border-radius: 16px;
  font-size: 12.5px;
  line-height: 1.25;
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.smb-status:before { border-radius: 16px; }
.smb-status .wrapper {
  border-radius: 16px;
  min-width: 168px;
  padding: 12px 16px;
}

.smb-label { display: inline-flex; align-items: baseline; gap: 6px; }
.smb-head { font-weight: 700; }
.smb-sub { font-style: normal; font-size: 11px; color: rgba(255, 255, 255, 0.82); }

/* 窄屏：收起「待同步 N 张」，并压缩内边距，避免把右侧用户区挤出标题栏 */
@media (max-width: 620px) {
  .smb-status .wrapper { min-width: 0; padding: 10px 13px; }
  .smb-sub { display: none; }
}
</style>
