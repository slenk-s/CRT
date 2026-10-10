<script setup lang="ts">
import { computed, onMounted, ref, watch, type Ref } from 'vue'
import { api } from '@/api'
import type { StatsResponse } from '@/api/types'

const days = ref(14)
const loading = ref(false)
const data = ref<StatsResponse | null>(null)
const activePoint = ref(-1)

async function changeDays(d: number) {
  days.value = d
  load()
}

async function load() {
  loading.value = true
  try {
    data.value = await api.stats(days.value)
  } finally {
    loading.value = false
  }
}

// ---------------- 手绘 SVG 折线（无额外图表依赖） ----------------
const W = 760
const H = 240
const PAD = { l: 38, r: 18, t: 18, b: 30 }

const chart = computed(() => {
  const series = data.value?.series || []
  const n = series.length
  if (!n) return null
  const maxY = Math.max(1, ...series.map((s) => Math.max(s.changeovers, s.items)))
  const innerW = W - PAD.l - PAD.r
  const innerH = H - PAD.t - PAD.b
  const x = (i: number) => PAD.l + (n === 1 ? innerW / 2 : (i * innerW) / (n - 1))
  const y = (v: number) => H - PAD.b - (v / maxY) * innerH

  const coPts = series.map((s, i) => `${x(i)},${y(s.changeovers)}`).join(' ')
  const itemPts = series.map((s, i) => `${x(i)},${y(s.items)}`).join(' ')
  const coSeries = series.map((s, i) => ({ ...s, x: x(i), y: y(s.changeovers) }))
  const itemSeries = series.map((s, i) => ({ ...s, x: x(i), y: y(s.items) }))
  const area = `${PAD.l},${H - PAD.b} ${coPts} ${x(n - 1)},${H - PAD.b}`

  const step = Math.max(1, Math.ceil(n / 7))
  const labels = series
    .map((s, i) => ({ i, text: s.date.slice(5) }))
    .filter((_, i) => i % step === 0)

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    v: Math.round(maxY * f),
    y: y(maxY * f),
  }))

  return { series, coSeries, itemSeries, x, y, coPts, itemPts, area, labels, ticks, maxY }
})

const totalCo = computed(() => (data.value?.series || []).reduce((a, b) => a + b.changeovers, 0))
const totalItems = computed(() => (data.value?.series || []).reduce((a, b) => a + b.items, 0))
const maxLine = computed(() => Math.max(1, ...(data.value?.by_line || []).map((x) => x.count)))

// ---- Odometer Ticker ----
const displayedCo = ref(0)
const displayedItems = ref(0)
const displayedLines = ref(0)

function animateTo(target: number, current: Ref<number>, duration = 800) {
  const start = current.value
  const diff = target - start
  const startTime = performance.now()
  function tick(now: number) {
    const elapsed = now - startTime
    const t = Math.min(1, elapsed / duration)
    const ease = 1 - Math.pow(1 - t, 3)
    current.value = Math.round(start + diff * ease)
    if (t < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

watch(totalCo, (v) => animateTo(v, displayedCo))
watch(totalItems, (v) => animateTo(v, displayedItems))
watch(() => data.value?.by_line.length || 0, (v) => animateTo(v, displayedLines))

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="head-title">
<<<<<<< HEAD
      <h2 class="title">统计</h2>
=======
      <h2 class="title">条目统计</h2>
>>>>>>> 9d0a5a9 (初始化 PCC v1.1 项目)
      <p class="hint">转产提交量与条目量趋势（仅管理员可见）。</p>
    </div>

    <div class="card panel toolbar-card mb">
      <div class="toolbar-left">
        <b>周期</b>
        <span>数据范围按转产提交日期统计。</span>
      </div>
      <div class="toolbar-controls">
        <div class="periods" role="group" aria-label="统计周期">
          <button v-for="d in [7, 14, 30, 90]" :key="d" type="button" :class="{ active: days === d }" @click="changeDays(d)">近 {{ d }} 天</button>
        </div>
        <el-button class="refresh-btn" :icon="'Refresh'" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="stat-cards">
      <div class="card stat">
        <span class="lb">提交转产数</span>
        <b class="ticker"><span class="val">{{ displayedCo }}</span></b>
        <span class="n1">近 {{ days }} 天</span>
      </div>
      <div class="card stat">
        <span class="lb">转产条目数</span>
        <b class="ticker"><span class="val">{{ displayedItems }}</span></b>
        <span class="n1">近 {{ days }} 天</span>
      </div>
      <div class="card stat">
        <span class="lb">覆盖线体数</span>
        <b class="ticker"><span class="val">{{ displayedLines }}</span></b>
        <span class="n1">Top 10 展示</span>
      </div>
    </div>

    <div class="card panel mb">
      <div class="chart-head">
        <b>提交趋势</b>
        <span class="legend">
          <i class="dot co" />提交转产
          <i class="dot item" />条目数
        </span>
      </div>
      <div v-if="chart" class="chart-wrap chart-scroll">
        <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" class="chart">
          <defs>
            <linearGradient id="coFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#409eff" stop-opacity="0.28" />
              <stop offset="100%" stop-color="#409eff" stop-opacity="0.02" />
            </linearGradient>
          </defs>
          <!-- 网格与刻度 -->
          <g class="grid">
            <line v-for="t in chart.ticks" :key="t.y" :x1="PAD.l" :x2="W - PAD.r" :y1="t.y" :y2="t.y" />
            <text v-for="t in chart.ticks" :key="`t${t.y}`" :x="PAD.l - 6" :y="t.y + 4" text-anchor="end">
              {{ t.v }}
            </text>
          </g>
          <!-- 面积 + 折线 -->
          <polygon :points="chart.area" fill="url(#coFill)" />
          <polyline :points="chart.coPts" class="line co" />
          <polyline :points="chart.itemPts" class="line item" />
          <circle
            v-for="(p, i) in chart.coSeries"
            :key="`co-${i}`"
            :cx="p.x"
            :cy="p.y"
            :r="activePoint === i ? 6.2 : 2.8"
            class="pt co"
            @mouseenter="activePoint = i"
            @mouseleave="activePoint = -1"
            @click="activePoint = activePoint === i ? -1 : i"
          />
          <circle
            v-for="(p, i) in chart.itemSeries"
            :key="`item-${i}`"
            :cx="p.x"
            :cy="p.y"
            :r="activePoint === i ? 5.4 : 2.4"
            class="pt item"
            @mouseenter="activePoint = i"
            @mouseleave="activePoint = -1"
            @click="activePoint = activePoint === i ? -1 : i"
          />
          <g v-if="activePoint >= 0 && chart.series[activePoint]">
            <line :x1="chart.x(activePoint)" :x2="chart.x(activePoint)" :y1="PAD.t" :y2="H - PAD.b" class="snap-line" />
            <text :x="chart.x(activePoint)" :y="PAD.t - 4" text-anchor="middle" class="snap-label">{{ chart.series[activePoint].date }} · {{ chart.series[activePoint].changeovers }}/{{ chart.series[activePoint].items }}</text>
          </g>
          <!-- X 轴标签 -->
          <text
            v-for="l in chart.labels"
            :key="l.i"
            :x="chart.x(l.i)"
            :y="H - 8"
            text-anchor="middle"
            class="xlabel"
          >
            {{ l.text }}
          </text>
        </svg>
      </div>
      <el-empty v-else description="暂无数据" />
    </div>

    <div class="card panel">
      <b>线体分布（Top 10）</b>
      <div class="barlist mt">
        <div v-for="b in data?.by_line || []" :key="b.line" class="barrow">
          <span class="lb">{{ b.line }}</span>
          <span class="track"><span class="fill" :style="{ width: `${(b.count / maxLine) * 100}%` }" /></span>
          <span class="num">{{ b.count }}</span>
        </div>
        <el-empty v-if="!(data?.by_line || []).length" description="暂无数据" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.title { margin: 0; font-size: 20px; }
.stat-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 16px; }
.stat { padding: 16px 18px; display: flex; flex-direction: column; gap: 2px; }
.stat .lb { color: var(--text3); font-size: 13px; }
.stat b { font-size: 26px; color: var(--text); }
.stat .n1 { font-size: 12px; color: var(--text3); }
.stat .ticker {
  display: inline-block;
  font-variant-numeric: tabular-nums;
  font-size: 26px;
  font-weight: 700;
  color: var(--primary);
  line-height: 1.2;
}
.stat .ticker .val {
  display: inline-block;
  transition: transform 0.1s ease;
}
.chart-wrap {
  overflow-x: auto;
  scroll-behavior: smooth;
  -webkit-overflow-scrolling: touch;
}
.chart-wrap::-webkit-scrollbar { height: 4px; }
.chart-wrap::-webkit-scrollbar-thumb {
  background: var(--primary);
  border-radius: 2px;
}
/* Magnetic snap points */
.snap-line { stroke: rgba(64,158,255,.45); stroke-width: 1; stroke-dasharray: 4 4; transition: all .18s ease; }
.snap-label { font-size: 11px; fill: var(--primary); font-weight: 700; paint-order: stroke; stroke: #fff; stroke-width: 3; }
.chart .pt {
  transition: r 0.2s cubic-bezier(0.34, 1.56, 0.64, 1),
              fill 0.2s ease;
  cursor: pointer;
}
.chart .pt.co { fill: #409eff; }
.chart .pt.item { fill: #67c23a; }
.chart .pt:hover { fill: var(--primary); filter: drop-shadow(0 0 5px rgba(64,158,255,.55)); }
.toolbar-card { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; padding: 14px 16px; min-width: 0; }
.toolbar-left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.toolbar-left b { font-size: 15px; color: var(--text); }
.toolbar-left span { font-size: 12.5px; color: var(--text3); }
.toolbar-controls { display: flex; align-items: center; gap: 10px; flex: 1 1 360px; min-width: 0; flex-wrap: wrap; }
.periods { flex: 1 1 260px; min-width: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.periods button { height: 36px; border: 1px solid var(--border-l); border-radius: 9px; background: #fff; color: var(--text2); cursor: pointer; font-size: 13px; transition: .16s; }
.periods button:hover { border-color: #bfe0ff; color: var(--primary); }
.periods button.active { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; box-shadow: 0 6px 14px rgba(64,158,255,.2); }
.refresh-btn { flex: 0 0 auto; min-width: 78px; }

@media (max-width: 640px) {
  .toolbar-card { align-items: stretch; }
  .toolbar-controls { width: 100%; }
  .periods { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .refresh-btn { width: 100%; }
}

.chart-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.legend { font-size: 12.5px; color: var(--text3); display: flex; align-items: center; gap: 6px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-left: 10px; }
.dot.co { background: #409eff; }
.dot.item { background: #67c23a; }
.chart { width: 100%; height: 240px; }
.grid line { stroke: #eef2f7; stroke-width: 1; }
.grid text { font-size: 10px; fill: #b0b8c3; }
.line { fill: none; stroke-width: 2.2; stroke-linejoin: round; stroke-linecap: round; }
.line.co { stroke: #409eff; }
.line.item { stroke: #67c23a; }
.pt { fill: #409eff; }
.xlabel { font-size: 10.5px; fill: #909399; }
<<<<<<< HEAD
</style>
=======
</style>
>>>>>>> 9d0a5a9 (初始化 PCC v1.1 项目)
