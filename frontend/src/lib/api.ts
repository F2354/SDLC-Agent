const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** 默认请求超时（毫秒）。 */
const DEFAULT_TIMEOUT_MS = 30_000
/** 可能耗时很长的请求（阶段运行、代码执行）超时（毫秒）。 */
const LONG_TIMEOUT_MS = 600_000

export function parseErrorBody(body: string, status: number): string {
  try {
    const parsed = JSON.parse(body) as { detail?: string }
    if (parsed.detail) {
      return parsed.detail
    }
  } catch {
    // body 不是 JSON 时直接使用原始文本
  }
  return body || `请求失败: ${status}`
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  // 组合调用方传入的 signal，保证组件卸载时能取消请求。
  const external = options.signal
  const onExternalAbort = () => controller.abort()
  external?.addEventListener('abort', onExternalAbort, { once: true })

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      // headers 必须在 ...options 之后合并，否则会被整体覆盖导致 Content-Type 丢失。
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers ?? {}),
      },
      signal: controller.signal,
    })
  } catch (err) {
    if (controller.signal.aborted && !external?.aborted) {
      throw new ApiError(0, `请求超时（${Math.round(timeoutMs / 1000)} 秒）`)
    }
    throw err
  } finally {
    clearTimeout(timer)
    external?.removeEventListener('abort', onExternalAbort)
  }

  if (!response.ok) {
    throw new ApiError(response.status, parseErrorBody(await response.text(), response.status))
  }

  if (response.status === 204) {
    return undefined as T
  }

  const body = await response.text()
  if (!body.trim()) {
    // 后端返回空响应体时不应抛 SyntaxError。
    return undefined as T
  }
  return JSON.parse(body) as T
}

export interface Stage {
  id: number
  seq: number
  code: string
  name: string
  description?: string
}

export interface ProcessModel {
  id: number
  code: string
  name: string
  description?: string
  version?: string
  stages?: Stage[]
}

export interface Project {
  id: number
  name: string
  description: string
  folder: string | null
  status: string
  auto_advance: boolean
  process_model?: ProcessModel
  owner_id: number
  created_at: string
  updated_at: string
}

export interface ProjectFlowStage {
  stage: Stage
  status: string
  stage_run_id: number | null
}

export interface ProjectFlow {
  process_model: ProcessModel
  stages: ProjectFlowStage[]
  auto_advance: boolean
}

export interface Artifact {
  id: number
  project_id: number
  stage_run_id: number
  type: string
  title: string
  content_md: string
  current_version: number
  status: string
  created_at: string
  updated_at: string
}

export interface StageRun {
  id: number
  project_id: number
  stage_id: number
  stage_code: string
  stage_name: string
  provider_id: number | null
  status: string
  mode: string
  error: string | null
  artifacts: Artifact[]
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface StageStartPayload {
  mode?: 'auto' | 'chat'
  provider_id?: number | null
}

export interface Message {
  id: number
  project_id: number
  stage_run_id: number
  role: string
  agent_code: string | null
  content: string
  created_at: string
}

export interface ActivityEvent {
  id: number
  project_id: number
  stage_run_id: number | null
  event_type: string
  message: string
  created_at: string
}

export interface EntityGroup {
  RQ: string[]
  UC: string[]
  MOD: string[]
  TC: string[]
}

export interface TraceabilityRow {
  artifact_id: number
  title: string
  stage_code: string
  entities: EntityGroup
}

export interface TraceabilityLink {
  from_type: string
  from_key: string
  to_type: string
  to_key: string
  relation: string
}

export interface TraceabilityCoverage {
  rq_total: number
  rq_with_uc: number
  rq_with_mod: number
  rq_with_tc: number
  mod_total: number
  mod_with_tc: number
  tc_total: number
  unresolved: string[]
}

export interface Traceability {
  rows: TraceabilityRow[]
  entity_counts: Record<string, number>
  warnings: string[]
  links: TraceabilityLink[]
  coverage: TraceabilityCoverage
}

export interface Review {
  id: number
  stage_run_id: number
  artifact_id: number | null
  reviewer_type: string
  result: string
  comment: string
  created_at: string
}

export interface ProjectStats {
  project_id: number
  stage_counts: Record<string, number>
  artifact_count: number
  total_chars: number
  entity_counts: Record<string, number>
}

export interface CodeFile {
  path: string
  size: number
}

export interface CodeTree {
  exists: boolean
  files: CodeFile[]
}

export interface CodeRun {
  ok: boolean
  phase: string
  output: string
}

export type ProviderType = 'openai_compatible' | 'ollama'

export interface ProviderModel {
  id: number
  model_name: string
  is_default: boolean
  context_window: number | null
}

export interface Provider {
  id: number
  name: string
  type: ProviderType
  base_url: string
  api_key_masked: string | null
  default_model: string
  enabled: boolean
  models: ProviderModel[]
  created_at: string
  updated_at: string
}

export interface ProviderPayload {
  name: string
  type: ProviderType
  base_url: string
  api_key?: string | null
  default_model?: string
  models?: string[]
  enabled?: boolean
}

export interface ProviderTestResult {
  ok: boolean
  message: string
  models: string[]
}

export function listProcessModels() {
  return request<ProcessModel[]>('/process-models')
}

/** 项目 SSE 事件流地址，供 EventSource 订阅。 */
export function projectEventsUrl(projectId: number) {
  return `${API_BASE}/projects/${projectId}/events`
}

export function updateProject(
  projectId: number,
  payload: { name?: string; description?: string; auto_advance?: boolean },
) {
  return request<Project>(`/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function listProjects() {
  return request<Project[]>('/projects')
}

export function createProject(payload: {
  name: string
  description?: string
  process_model_code: string
  folder?: string | null
}) {
  return request<Project>('/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface FsEntry {
  name: string
  path: string
}

export interface FsBrowse {
  path: string
  parent: string | null
  entries: FsEntry[]
}

export function browseFilesystem(path = '') {
  return request<FsBrowse>(`/filesystem?path=${encodeURIComponent(path)}`)
}

export function getProjectFlow(projectId: number) {
  return request<ProjectFlow>(`/projects/${projectId}/flow`)
}

export function startStage(
  projectId: number,
  stageCode: string,
  payload: StageStartPayload = {},
) {
  return request<StageRun>(
    `/projects/${projectId}/stages/${stageCode}/start`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    LONG_TIMEOUT_MS,
  )
}

export function listProjectArtifacts(projectId: number) {
  return request<Artifact[]>(`/projects/${projectId}/artifacts`)
}

export function getStageRunMessages(runId: number) {
  return request<Message[]>(`/stage-runs/${runId}/messages`)
}

export function sendChatMessage(runId: number, content: string) {
  return request<Message>(`/stage-runs/${runId}/chat`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

export function confirmStage(runId: number) {
  return request<StageRun>(
    `/stage-runs/${runId}/confirm`,
    { method: 'POST' },
    LONG_TIMEOUT_MS,
  )
}

export function listStageRunReviews(runId: number) {
  return request<Review[]>(`/stage-runs/${runId}/review`)
}

export function approveStageRun(runId: number, comment = '') {
  return request<StageRun>(`/stage-runs/${runId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  })
}

export function rejectStageRun(runId: number, comment = '') {
  return request<StageRun>(`/stage-runs/${runId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  })
}

export function listActivityEvents(projectId: number) {
  return request<ActivityEvent[]>(`/projects/${projectId}/activity-events`)
}

export function updateArtifact(artifactId: number, contentMd: string) {
  return request<Artifact>(`/artifacts/${artifactId}`, {
    method: 'PATCH',
    body: JSON.stringify({ content_md: contentMd }),
  })
}

export function getProjectStats(projectId: number) {
  return request<ProjectStats>(`/projects/${projectId}/stats`)
}

export function getTraceability(projectId: number) {
  return request<Traceability>(`/projects/${projectId}/traceability`)
}

export function getCodeTree(projectId: number) {
  return request<CodeTree>(`/projects/${projectId}/code/tree`)
}

export async function getCodeFile(projectId: number, path: string) {
  const response = await fetch(
    `${API_BASE}/projects/${projectId}/code/file?path=${encodeURIComponent(path)}`,
  )
  if (!response.ok) {
    throw new ApiError(response.status, parseErrorBody(await response.text(), response.status))
  }
  return response.text()
}

export function runGeneratedCode(projectId: number) {
  return request<CodeRun>(
    `/projects/${projectId}/code/run`,
    { method: 'POST' },
    LONG_TIMEOUT_MS,
  )
}

export function testGeneratedCode(projectId: number) {
  return request<CodeRun>(
    `/projects/${projectId}/code/test`,
    { method: 'POST' },
    LONG_TIMEOUT_MS,
  )
}

export async function exportArtifact(artifactId: number, format: 'docx' | 'pdf') {
  const response = await fetch(`${API_BASE}/artifacts/${artifactId}/export?format=${format}`)
  if (!response.ok) {
    throw new ApiError(response.status, parseErrorBody(await response.text(), response.status))
  }
  return response.blob()
}

export function listProviders() {
  return request<Provider[]>('/providers')
}

export function createProvider(payload: ProviderPayload) {
  return request<Provider>('/providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function testProvider(providerId: number) {
  return request<ProviderTestResult>(`/providers/${providerId}/test`, {
    method: 'POST',
  })
}

export function deleteProvider(providerId: number) {
  return request<void>(`/providers/${providerId}`, {
    method: 'DELETE',
  })
}
