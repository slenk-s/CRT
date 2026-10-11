import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api'
import type { WbQueryResponse, WbStatus } from '@/api/types'

type Mode = 'batch' | 'bom'

// 会话级持久化：切换页面由 Pinia 保活；刷新页面由 sessionStorage 兜底。
const SS_KEY = 'wb-query-state'

interface PersistedState {
  mode: Mode
  raw: string
  result: WbQueryResponse | null
  lastError: string
}

function loadPersisted(): PersistedState {
  try {
    const text = sessionStorage.getItem(SS_KEY)
    if (text) {
      const p = JSON.parse(text) as Partial<PersistedState>
      return {
        mode: p.mode === 'bom' ? 'bom' : 'batch',
        raw: typeof p.raw === 'string' ? p.raw : '',
        result: (p.result as WbQueryResponse | null) ?? null,
        lastError: typeof p.lastError === 'string' ? p.lastError : '',
      }
    }
  } catch {
    /* 缓存损坏则忽略，回到默认值 */
  }
  return { mode: 'batch', raw: '', result: null, lastError: '' }
}

/**
 * WB 查询状态提升到 store：
 * - 组件在切换功能页时会被销毁（router-view 无 keep-alive 且以 fullPath 为 key），
 *   store 常驻内存，切走再回来数据仍在；
 * - 查询在 store 内发起，不随组件卸载取消，切页期间继续跑；
 * - 「清空」立即清空输入框与结果；
 * - 「终止」（查询进行中）真正 abort 在途请求，并使结果不回填；
 * - 用「代次(generation)」兜底：任何过期响应一律丢弃。
 */
export const useWbStore = defineStore('wb', () => {
  const saved = loadPersisted()

  const mode = ref<Mode>(saved.mode)
  const raw = ref(saved.raw)
  const result = ref<WbQueryResponse | null>(saved.result)
  const lastError = ref(saved.lastError)
  const loading = ref(false)
  const status = ref<WbStatus | null>(null)

  // 每发生一次「清空 / 终止 / 切换模式」就 +1；在途请求返回时若代次已变，则丢弃其结果。
  let generation = 0
  // 当前在途请求的取消控制器：点「终止」时真正 abort。
  let controller: AbortController | null = null

  function persist() {
    try {
      sessionStorage.setItem(
        SS_KEY,
        JSON.stringify({
          mode: mode.value,
          raw: raw.value,
          result: result.value,
          lastError: lastError.value,
        }),
      )
    } catch {
      /* 隐私模式等导致写入失败时忽略 */
    }
  }

  /** 立即清空输入框、结果、错误与加载态，取消在途请求，并写入持久化（刷新后仍为空白）。 */
  function resetState() {
    generation++
    controller?.abort()
    controller = null
    raw.value = ''
    result.value = null
    lastError.value = ''
    loading.value = false
    persist()
  }

  // 与后端 _SPLIT 保持一致：逗号 / 顿号 / 分号 / 空白（空格、Tab、换行）都作为分隔符。
  function splitKeys(s: string): string[] {
    return s.split(/[,，、;；\s]+/).map((x) => x.trim()).filter(Boolean)
  }

  function friendlyError(e: unknown): string {
    const err = e as {
      code?: string
      response?: { status?: number; data?: { detail?: string } }
    }
    if (err?.code === 'ECONNABORTED' || err?.code === 'ETIMEDOUT') {
      return '查询超时：批次较多或数据源较慢，请减少批次数量后重试。'
    }
    const st = err?.response?.status
    if (st === 503) return err?.response?.data?.detail || '数据源未配置，请联系管理员。'
    if (st) return err?.response?.data?.detail || `查询失败（HTTP ${st}）`
    return '网络异常或服务未响应，请稍后重试。'
  }

  /** 是否为「主动终止」导致的取消（不当作错误提示）。 */
  function isAborted(e: unknown): boolean {
    const err = e as { code?: string; name?: string }
    return (
      err?.code === 'ERR_CANCELED' ||
      err?.name === 'CanceledError' ||
      err?.name === 'AbortError'
    )
  }

  /** 发起查询；结果写入 store（不随组件卸载而丢失，也不覆盖之后的清空/终止）。 */
  async function runQuery(params: { batch?: string; bom?: string }) {
    controller?.abort() // 若已有在途查询，先终止
    const ctrl = new AbortController()
    controller = ctrl
    const gen = generation
    loading.value = true
    lastError.value = ''
    try {
      const data = await api.wbQuery(params, ctrl.signal)
      if (gen !== generation) return // 期间已清空/终止/切换模式 → 丢弃过期结果
      result.value = data
    } catch (e) {
      if (gen !== generation || isAborted(e)) return // 主动终止：不提示、不回填
      result.value = null
      lastError.value = friendlyError(e)
    } finally {
      if (controller === ctrl) controller = null
      if (gen === generation) {
        loading.value = false
        persist()
      }
    }
  }

  async function loadStatus() {
    try {
      status.value = await api.wbStatus()
    } catch {
      /* 仅用于顶部提示，失败忽略 */
    }
  }

  function switchMode(m: Mode) {
    mode.value = m
    resetState()
  }

  /** 清空：立即清掉输入框与结果，并让任何在途查询作废（不会再回填）。 */
  function clear() {
    resetState()
  }

  /** 终止：真正取消在途查询（结果不会回填），保留输入框内容以便重查。 */
  function stop() {
    generation++
    controller?.abort()
    controller = null
    loading.value = false
  }

  function fillDemo() {
    raw.value = mode.value === 'batch' ? 'GHH500277A\nGLU500297A' : 'Z2U10401010120,Z2U10401008960'
    persist()
  }

  return {
    mode,
    raw,
    result,
    lastError,
    loading,
    status,
    splitKeys,
    runQuery,
    loadStatus,
    switchMode,
    clear,
    stop,
    fillDemo,
  }
})
