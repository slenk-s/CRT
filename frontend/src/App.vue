<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import AppShell from '@/layouts/AppShell.vue'

const user = useUserStore()
const route = useRoute()

onMounted(() => {
  // 刷新后凭本地 token 拉取当前用户（失败由拦截器统一处理）
  if (user.token && !user.profile) user.fetchMe().catch(() => {})
})
</script>

<template>
  <!-- 登录页独立全屏，其余走 AppShell 布局 -->
  <router-view name="default" v-if="route.meta.public" />
  <AppShell v-else />
</template>