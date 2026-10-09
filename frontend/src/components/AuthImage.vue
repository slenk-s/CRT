<script setup lang="ts">
// 受保护图片：后端图片接口需要 Authorization 头，<img> 无法携带，
// 故通过 axios 取回 Blob 生成 objectURL 展示。
import { onBeforeUnmount, ref, watch } from 'vue'
import { fetchBlobUrl } from '@/api/http'

const props = defineProps<{
  path: string | null | undefined
  alt?: string
  /** 点击回调（用于放大预览） */
  onPreview?: (url: string) => void
}>()

const url = ref('')
const loading = ref(false)
const failed = ref(false)
let current = ''

async function load() {
  if (!props.path) {
    url.value = ''
    return
  }
  if (url.value.startsWith('blob:')) URL.revokeObjectURL(url.value)
  url.value = ''
  failed.value = false
  loading.value = true
  try {
    url.value = await fetchBlobUrl(props.path)
    current = url.value
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

watch(() => props.path, load, { immediate: true })

function open() {
  if (url.value && props.onPreview) props.onPreview(url.value)
}

onBeforeUnmount(() => {
  if (current.startsWith('blob:')) URL.revokeObjectURL(current)
})
</script>

<template>
  <img
    v-if="url"
    :src="url"
    :alt="alt || '照片'"
    class="thumb"
    style="cursor: zoom-in"
    @click="open"
  />
  <div v-else-if="loading" class="thumb-ph">加载中…</div>
  <div v-else-if="failed" class="thumb-ph" title="照片加载失败">加载失败</div>
  <div v-else class="thumb-ph">无照片</div>
</template>