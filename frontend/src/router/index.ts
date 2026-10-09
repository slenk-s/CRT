import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { TOKEN_KEY } from '@/api/http'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  { path: '/', redirect: '/changeover' },
  {
    path: '/changeover',
    name: 'changeover-list',
    component: () => import('@/views/ChangeoverListView.vue'),
    meta: { title: '转产记录' },
  },
  {
    path: '/changeover/new',
    name: 'changeover-new',
    component: () => import('@/views/ChangeoverEditView.vue'),
    meta: { title: '新建转产' },
  },
  {
    path: '/changeover/:id/edit',
    name: 'changeover-edit',
    component: () => import('@/views/ChangeoverEditView.vue'),
    meta: { title: '转产录入' },
  },
  {
    path: '/changeover/:id',
    name: 'changeover-detail',
    component: () => import('@/views/ChangeoverDetailView.vue'),
    meta: { title: '转产详情' },
  },
  {
    path: '/wb',
    name: 'wb-query',
    component: () => import('@/views/WbQueryView.vue'),
    meta: { title: 'WB 参数查询' },
  },
  {
    path: '/stats',
    name: 'stats',
    component: () => import('@/views/StatsView.vue'),
    meta: { title: '统计', requiresAdmin: true },
  },
  {
    path: '/admin/dicts',
    name: 'admin-dicts',
    component: () => import('@/views/admin/DictManageView.vue'),
    meta: { title: '字典管理', requiresAdmin: true },
  },
  {
    path: '/admin/users',
    name: 'admin-users',
    component: () => import('@/views/admin/UserManageView.vue'),
    meta: { title: '用户管理', requiresAdmin: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/changeover' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const user = useUserStore()
  if (to.meta.public) return true

  if (!user.token && !localStorage.getItem(TOKEN_KEY)) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // 管理端路由：确认当前用户身份（刷新后 profile 为空时拉取）
  if (to.meta.requiresAdmin) {
    try {
      if (!user.profile) await user.fetchMe()
      if (!user.isAdmin) return { path: '/changeover' }
    } catch {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title as string} · 产线转产管理`
    : '产线转产管理'
})

export default router