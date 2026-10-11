<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { useWbStore } from '@/stores/wb'

// 状态放在 store：切换功能页/标签时组件会被销毁，组件内的 ref 会丢，
// store 常驻内存，切走再回来数据仍在；查询请求也不随组件卸载取消。
const store = useWbStore()
const { mode, raw, loading, result, status, lastError } = storeToRefs(store)

async function query() {
  const keys = store.splitKeys(raw.value)
  if (!keys.length) {
    ElMessage.warning(`请输入${mode.value === 'batch' ? '批次号' : 'BOM'}`)
    return
  }
  await store.runQuery(
    mode.value === 'batch' ? { batch: keys.join(',') } : { bom: keys.join(',') },
  )
}

const okCount = () => result.value?.results.filter((r) => r.ok).length || 0
const failCount = () => result.value?.results.filter((r) => !r.ok).length || 0

onMounted(() => {
  // 只在尚未取得数据源状态时拉一次；切页回来不重复查询、不重置结果。
  if (!status.value) store.loadStatus()
})
</script>

<template>
  <div class="page">
    <div class="head-title">
      <h2 class="title">WB 参数查询</h2>
      <p class="hint">按批次号或 BOM 查询白平衡参数；多个关键字用逗号 / 空格 / 换行分隔，单条失败不影响其他条目。</p>
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
        <button :class="{ active: mode === 'batch' }" @click="store.switchMode('batch')">按批次号</button>
        <button :class="{ active: mode === 'bom' }" @click="store.switchMode('bom')">按 BOM</button>
      </div>

      <el-input
        v-model="raw"
        type="textarea"
        :rows="4"
        :placeholder="
          mode === 'batch'
            ? '每行一个批次号，或用逗号分隔，例如：\nGHH500277A\nGLU500297A'
            : '每行一个 BOM，或用逗号分隔，例如：\nZ2U10401010120, Z2U10401008960'
        "
      />
      <div class="q-actions">
        <el-button type="primary" :loading="loading" @click="query">
          <el-icon><Search /></el-icon>查询
        </el-button>
        <el-button @click="store.fillDemo()">填入示例</el-button>
        <!-- 查询进行中：显示「终止」以真正取消在途请求；空闲时显示「清空」 -->
        <el-button v-if="!loading" text @click="store.clear()">清空</el-button>
        <el-button v-else type="danger" plain @click="store.stop()">终止</el-button>
        <span v-if="result" class="note">
          共 {{ result.results.length }} 条：成功 {{ okCount() }} · 失败 {{ failCount() }} · 数据源 {{ result.source }}
        </span>
      </div>
    </div>

    <el-alert
      v-if="loading"
      type="info"
      :closable="false"
      show-icon
      title="正在查询中……可切换到其他功能页，查询会在后台继续；也可点「终止」停止本次查询。"
      class="mb"
    />

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

    <el-alert
      v-else-if="lastError && !loading"
      type="error"
      :closable="false"
      show-icon
      :title="lastError"
    />
    <el-empty v-else-if="!loading" description="输入关键字后点击查询" />
  </div>
</template>

<style scoped>
.title { margin: 0 0 4px; font-size: 20px; }
.q-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.kvcard h4 { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.kvcard.bad h4 { border-left-color: var(--danger); }
.key { word-break: break-all; }
</style>
