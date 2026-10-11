import http from './http'
import type {
  CheckItem,
  ChangeoverDetail,
  ChangeoverOut,
  ChangeoverPage,
  CheckItemAdmin,
  DictLinesResponse,
  DictStation,
  ItemOut,
  LineAdmin,
  StationAdmin,
  StatsResponse,
  SubmitResult,
  TokenResponse,
  UserAdmin,
  UserProfile,
  VersionOut,
  WbQueryResponse,
  WbStatus,
} from './types'

type Dict<T> = Record<string, T>

export const api = {
  // ---- 认证 ----
  login: (emp_id: string, password: string) =>
    http.post<TokenResponse>('/api/auth/login', { emp_id, password }).then((r) => r.data),
  me: () => http.get('/api/auth/me').then((r) => r.data),
  changePassword: (old_password: string, new_password: string) =>
    http.post('/api/auth/change-password', { old_password, new_password }).then((r) => r.data),

  // ---- 字典（登录即可读） ----
  dictLines: () => http.get<DictLinesResponse>('/api/dict/lines').then((r) => r.data),
  dictStations: () => http.get<DictStation[]>('/api/dict/stations').then((r) => r.data),
  dictCheckItems: (station?: string) =>
    http.get<CheckItem[]>('/api/dict/check-items', { params: station ? { station } : {} }).then((r) => r.data),

  // ---- 转产会话 ----
  coCreate: (body: { line: string; batch: string; shot_date?: string; note?: string }) =>
    http.post<ChangeoverDetail>('/api/changeover', body).then((r) => r.data),
  coList: (params: Dict<unknown>) =>
    http.get<ChangeoverPage>('/api/changeover', { params }).then((r) => r.data),
  coGet: (id: number | string) =>
    http.get<ChangeoverDetail>(`/api/changeover/${id}`).then((r) => r.data),
  coPatch: (id: number | string, body: { batch?: string; note?: string }) =>
    http.patch<ChangeoverOut>(`/api/changeover/${id}`, body).then((r) => r.data),
  coDelete: (id: number | string) =>
    http.delete<{ ok: boolean }>(`/api/changeover/${id}`).then((r) => r.data),
  coSubmit: (id: number | string) =>
    http.post<SubmitResult>(`/api/changeover/${id}/submit`).then((r) => r.data),

  // ---- 条目 ----
  coAddItem: (coId: number | string, station: string) =>
    http.post<ItemOut>(`/api/changeover/${coId}/items`, { station }).then((r) => r.data),
  itemPatch: (itemId: number, body: { check_result?: string; remark?: string }) =>
    http.patch<ItemOut>(`/api/changeover/items/${itemId}`, body).then((r) => r.data),
  itemCorrect: (itemId: number, body: { check_result?: string; remark?: string; edit_note: string }) =>
    http.put<ItemOut>(`/api/changeover/items/${itemId}`, body).then((r) => r.data),
  itemDelete: (itemId: number) =>
    http.delete<{ ok: boolean }>(`/api/changeover/items/${itemId}`).then((r) => r.data),
  itemUploadPhoto: (itemId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return http
      .post<ItemOut>(`/api/changeover/items/${itemId}/photo`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
  itemVersions: (itemId: number) =>
    http.get<VersionOut[]>(`/api/changeover/items/${itemId}/versions`).then((r) => r.data),

  // ---- 管理端 ----
  adminLines: () => http.get<LineAdmin[]>('/api/admin/lines').then((r) => r.data),
  adminCreateLine: (body: { workshop: string; line: string; sort?: number }) =>
    http.post<LineAdmin>('/api/admin/lines', body).then((r) => r.data),
  adminUpdateLine: (id: number, body: Dict<unknown>) =>
    http.put<LineAdmin>(`/api/admin/lines/${id}`, body).then((r) => r.data),
  adminDeleteLine: (id: number) =>
    http.delete(`/api/admin/lines/${id}`).then((r) => r.data),
  adminImportLines: (text: string) =>
    http.post<{ ok: boolean; added: number; reactivated: number; skipped: number }>(
      '/api/admin/lines/import', { text },
    ).then((r) => r.data),

  adminStations: () => http.get<StationAdmin[]>('/api/admin/stations').then((r) => r.data),
  adminCreateStation: (body: { station: string; sort?: number }) =>
    http.post<StationAdmin>('/api/admin/stations', body).then((r) => r.data),
  adminUpdateStation: (id: number, body: Dict<unknown>) =>
    http.put<StationAdmin>(`/api/admin/stations/${id}`, body).then((r) => r.data),
  adminDeleteStation: (id: number) =>
    http.delete(`/api/admin/stations/${id}`).then((r) => r.data),

  adminCheckItems: () => http.get<CheckItemAdmin[]>('/api/admin/check-items').then((r) => r.data),
  adminCreateCheckItem: (body: { station: string; item: string; sort?: number }) =>
    http.post<CheckItemAdmin>('/api/admin/check-items', body).then((r) => r.data),
  adminUpdateCheckItem: (id: number, body: Dict<unknown>) =>
    http.put<CheckItemAdmin>(`/api/admin/check-items/${id}`, body).then((r) => r.data),
  adminDeleteCheckItem: (id: number) =>
    http.delete(`/api/admin/check-items/${id}`).then((r) => r.data),

  adminUsers: () => http.get<UserAdmin[]>('/api/admin/users').then((r) => r.data),
  adminCreateUser: (body: { emp_id: string; name: string; password: string; role: string }) =>
    http.post<UserAdmin>('/api/admin/users', body).then((r) => r.data),
  adminUpdateUser: (emp_id: string, body: Dict<unknown>) =>
    http.put<UserAdmin>(`/api/admin/users/${emp_id}`, body).then((r) => r.data),

  // ---- 统计 ----
  stats: (days: number) =>
    http.get<StatsResponse>('/api/stats/changeover', { params: { days } }).then((r) => r.data),

  // ---- WB 查询 ----
  // 数据源较慢（单批次内部串联 MID/白平衡/ODF/料单多个上游接口），单独放宽超时，
  // 避免多批次被全局 30s 超时掐断；后端另有 25s 预算兜底，正常会在预算内返回。
  // 传入 signal 可真正终止请求（查询进行中点「终止」）。
  wbQuery: (params: { batch?: string; bom?: string }, signal?: AbortSignal) =>
    http
      .get<WbQueryResponse>('/api/wb/query', { params, timeout: 120000, signal })
      .then((r) => r.data),
  wbStatus: () => http.get<WbStatus>('/api/wb/status').then((r) => r.data),
}

export const fmtDateTime = (s?: string | null) => (s ? s.replace('T', ' ').slice(0, 19) : '—')
export const fmtSize = (n?: number | null) => {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}
export const statusText = (s: string) => (s === 'submitted' ? '已提交' : '草稿')