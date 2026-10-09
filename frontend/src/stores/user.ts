import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api'
import type { UserProfile } from '@/api/types'
import { TOKEN_KEY } from '@/api/http'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const profile = ref<UserProfile | null>(null)
  const isAdmin = computed(() => profile.value?.role === 'admin')

  function setToken(t: string) {
    token.value = t
    localStorage.setItem(TOKEN_KEY, t)
  }

  async function login(emp_id: string, password: string) {
    const r = await api.login(emp_id, password)
    setToken(r.token)
    profile.value = r.user
    return r.user
  }

  async function fetchMe() {
    profile.value = await api.me()
    return profile.value
  }

  function logout() {
    token.value = ''
    profile.value = null
    localStorage.removeItem(TOKEN_KEY)
  }

  return { token, profile, isAdmin, setToken, login, fetchMe, logout }
})