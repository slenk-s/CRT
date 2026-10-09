import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'

export const TOKEN_KEY = 'co_token'

const http: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (!location.pathname.startsWith('/login')) {
        ElMessage.warning('登录已过期，请重新登录')
        location.href = '/login'
      }
    } else if (status === 403) {
      ElMessage.error(detail || '没有权限执行该操作')
    } else if (status === 503) {
      ElMessage.error(detail || '数据源/存储暂不可用，请稍后重试')
    } else if (status && status !== 404) {
      ElMessage.error(detail || `请求失败（${status}）`)
    }
    return Promise.reject(error)
  },
)

/** 受保护图片：带 token 取回二进制 → objectURL（<img> 无法带 Authorization 头） */
export async function fetchBlobUrl(path: string): Promise<string> {
  const resp = await http.get(path, { responseType: 'blob' })
  return URL.createObjectURL(resp.data as Blob)
}

/** 触发浏览器下载（用于 CSV 导出） */
export async function downloadFile(path: string, params: Record<string, unknown>, filename: string) {
  const resp = await http.get(path, { params, responseType: 'blob' })
  const url = URL.createObjectURL(resp.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default http