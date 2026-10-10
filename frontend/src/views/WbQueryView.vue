<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'
import type { WbQueryResponse, WbStatus } from '@/api/types'

const mode = ref<'batch' | 'bom'>('batch')
const raw = ref('')
const loading = ref(false)
const result = ref<WbQueryResponse | null>(null)
const status = ref<WbStatus | null>(null)
const showEmpty = reactive({ ok: false })

const splitKeys = (s: string) => s.split(/[,，\n;；]+/).map((x) => x.trim()).filter(Boolean)

async function query() {
  const keys = splitKeys(raw.value)
  if (!keys.length) {
    ElMessage.warning(`请输入${mode.value === 'batch' ? '批次号' : 'BOM'}`)
    return
  }
  loading.value = true
  try {
    result.value = await api.wbQuery(
      mode.value === 'batch' ? { batch: keys.join(',') } : { bom: keys.join(',') },
    )
  } catch {
    result.value = null
  } finally {
    loading.value = false
  }
}

function switchMode(m: 'batch' | 'bom') {
  mode.value = m
  result.value = null
  raw.value = ''
}

function fillDemo() {
<<<<<<< HEAD
  raw.value = mode.value === 'batch' ? 'DEMO-BATCH-001\nDEMO-BATCH-002' : 'DEMO-BOM-001'
=======
  raw.value = mode.value === 'batch' ? 'GHH500277A\nGLU500297A' : 'Z2U10401010120,Z2U10401008960'
>>>>>>> 9d0a5a9 (初始化 PCC v1.1 项目)
}

const okCount = () => result.value?.results.filter((r) => r.ok).length || 0
const failCount = () => result.value?.results.filter((r) => !r.ok).length || 0

onMounted(async () => {
  try {
    status.value = await api.wbStatus()
  } catch {
    /* 忽略：仅用于提示 */
  }
})
</script>

<template>
  <div class="page">
    <div class="head-title">
      <h2 class="title">WB 参数查询</h2>
      <p class="hint">按批次号或 BOM 查询白平衡参数；多个关键字用逗号 / 换行分隔，单条失败不影响其他条目。</p>
    </div>

    <el-alert
      v-if="status && !status.available"
      type="warning"
      :closable="false"
      show-icon
      title="WB 数据源当前不可用，查询将返回 503，请联系管理员配置数据源。"
      class="mb"
    />
    <el-alert
      v-else-if="status"
      type="success"
      :closable="false"
      show-icon
      :title="`数据源可用：${status.source}`"
      class="mb"
    />

    <div class="card panel mb">
      <div class="seg">
        <button :class="{ active: mode === 'batch' }" @click="switchMode('batch')">按批次号</button>
        <button :class="{ active: mode === 'bom' }" @click="switchMode('bom')">按 BOM</button>
      </div>

      <el-input
        v-model="raw"
        type="textarea"
        :rows="4"
        :placeholder="
          mode === 'batch'
<<<<<<< HEAD
            ? '每行一个批次号，或用逗号分隔，例如：\nDEMO-BATCH-001\nDEMO-BATCH-002'
            : '每行一个 BOM，或用逗号分隔，例如：\nDEMO-BOM-001, DEMO-BOM-002'
=======
            ? '每行一个批次号，或用逗号分隔，例如：\nGHH500277A\nGLU500297A'
            : '每行一个 BOM，或用逗号分隔，例如：\nZ2U10401010120,Z2U10401008960'
>>>>>>> 9d0a5a9 (初始化 PCC v1.1 项目)
        "
      />
      <div class="q-actions">
        <el-button type="primary" :loading="loading" @click="query">
          <el-icon><Search /></el-icon>查询
        </el-button>
        <el-button @click="fillDemo">填入示例</el-button>
        <el-button text @click="((raw = ''), (result = null))">清空</el-button>
        <span v-if="result" class="note">
          共 {{ result.results.length }} 条：成功 {{ okCount() }} · 失败 {{ failCount() }} · 数据源 {{ result.source }}
        </span>
      </div>
    </div>

    <div v-if="result" class="kvgrid">
      <div
        v-for="r in result.results"
        :key="r.key"
        class="card kvcard"
        :class="{ bad: !r.ok }"
      >
        <h4>
          <span class="key">{{ mode === 'batch' ? '批次' : 'BOM' }}：{{ r.key }}</span>
          <el-tag :type="r.ok ? 'success' : 'danger'" size="small" effect="plain">
            {{ r.ok ? '成功' : '失败' }}
          </el-tag>
        </h4>
        <template v-if="r.ok">
          <div v-for="(v, k) in r.fields" :key="k" class="kv">
            <span class="k">{{ k }}</span>
            <span class="v">{{ v || '—' }}</span>
          </div>
          <div v-if="!Object.keys(r.fields).length" class="note">该条查询未返回任何字段。</div>
        </template>
        <el-alert v-else type="error" :closable="false" show-icon :title="r.error || '查询失败'" />
      </div>
    </div>

    <el-empty v-else-if="!loading" description="输入关键字后点击查询" />
  </div>
</template>

<style scoped>
.title { margin: 0 0 4px; font-size: 20px; }
.q-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.kvcard h4 { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.kvcard.bad h4 { border-left-color: var(--danger); }
.key { word-break: break-all; }
<<<<<<< HEAD
</style>
=======
</style>
>>>>>>> 9d0a5a9 (初始化 PCC v1.1 项目)
