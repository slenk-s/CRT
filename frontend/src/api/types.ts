// 与后端 Pydantic 模型对应的类型定义

export interface UserProfile {
  emp_id: string
  name: string
  role: 'line' | 'admin'
  must_change_password: number
}

export interface TokenResponse {
  token: string
  token_type: string
  user: UserProfile
}

export interface DictLine { id: number; workshop: string; line: string; sort: number }
export interface DictLinesResponse { items: DictLine[]; by_workshop: Record<string, string[]> }
export interface DictStation { id: number; station: string; sort: number }
export interface CheckItem { id: number; station: string; item: string; sort: number }

export interface ItemPhotoOut {
  seq: number
  rel_path: string
  name: string
  size: number
  synced: number          // 0=本地待同步, 1=SMB
  uploader_emp_id: string
  uploader_name: string
  created_at: string
  url: string | null
}

export interface ItemOut {
  id: number
  station: string
  station_sort: number
  current_ver: number
  has_draft_photo: boolean
  item_status: 'unrecorded' | 'filled' | 'recorded'
  draft_check_result: string
  draft_remark: string
  draft_size: number
  draft_updated_at: string | null
  updated_at: string
  photo_url: string | null
  draft_photos: ItemPhotoOut[]
  has_photo_pending_sync: boolean
}

export interface ChangeoverOut {
  id: number
  shot_date: string
  workshop: string
  line: string
  batch: string
  status: 'draft' | 'submitted'
  uploader_emp_id: string
  uploader_name: string
  created_at: string
  submitted_at: string | null
  updated_at: string
  item_total: number
  item_with_photo: number
}

export interface ChangeoverDetail extends ChangeoverOut { items: ItemOut[] }
export interface ChangeoverPage { total: number; page: number; size: number; items: ChangeoverOut[] }

export interface VersionOut {
  ver: number
  photo_rel_path: string
  photo_name: string
  file_size: number
  check_result: string
  remark: string
  edit_note: string
  uploader_emp_id: string
  uploader_name: string
  created_at: string
  photo_url: string | null
}

export interface SubmitFailure { item_id: number; station: string; ok: boolean; reason: string }
export interface SubmitResult {
  ok: boolean
  changeover_id: number
  status: string
  versions_created: number
  no_photo_items: number
  failures: SubmitFailure[]
  submitted_at: string | null
}

export interface WbResult { key: string; ok: boolean; error: string; fields: Record<string, string> }
export interface WbQueryResponse { mode: string; source: string; results: WbResult[] }
export interface WbStatus { available: boolean; source: string | null; mode: string }

export interface LineAdmin { id: number; workshop: string; line: string; sort: number; active: number }
export interface StationAdmin { id: number; station: string; sort: number; active: number }
export interface CheckItemAdmin { id: number; station: string; item: string; sort: number; active: number }
export interface UserAdmin {
  emp_id: string; name: string; role: string; active: number; must_change_password: number; created_at: string
}

export interface StatsResponse {
  days: number
  series: { date: string; changeovers: number; items: number }[]
  by_line: { line: string; count: number }[]
}