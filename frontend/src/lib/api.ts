const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('sdlc_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
    ...options,
  })

  if (!response.ok) {
    const body = await response.text()
    let message = body
    try {
      const parsed = JSON.parse(body) as { detail?: string }
      if (parsed.detail) {
        message = parsed.detail
      }
    } catch {
      // body 不是 JSON 时直接使用原始文本
    }
    throw new ApiError(response.status, message || `请求失败: ${response.status}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export interface User {
  id: number
  username: string
  display_name: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
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
  status: string
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

export interface ReviewRequest {
  comment?: string
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

export interface Traceability {
  rows: TraceabilityRow[]
  entity_counts: Record<string, number>
  warnings: string[]
}

export interface ProjectStats {
  project_id: number
  stage_counts: Record<string, number>
  artifact_count: number
  total_chars: number
  entity_counts: Record<string, number>
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

export interface LoginPayload {
  username: string
  password: string
}

export interface RegisterPayload extends LoginPayload {
  display_name?: string
}

export function login(payload: LoginPayload) {
  return request<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function register(payload: RegisterPayload) {
  return request<TokenResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listProcessModels() {
  return request<ProcessModel[]>('/process-models')
}

export function listProjects() {
  return request<Project[]>('/projects')
}

export function createProject(payload: {
  name: string
  description?: string
  process_model_code: string
}) {
  return request<Project>('/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getProjectFlow(projectId: number) {
  return request<ProjectFlow>(`/projects/${projectId}/flow`)
}

export function startStage(
  projectId: number,
  stageCode: string,
  payload: StageStartPayload = {},
) {
  return request<StageRun>(`/projects/${projectId}/stages/${stageCode}/start`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getStageRun(runId: number) {
  return request<StageRun>(`/stage-runs/${runId}`)
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

export function confirmRequirements(runId: number) {
  return request<StageRun>(`/stage-runs/${runId}/confirm-requirements`, {
    method: 'POST',
  })
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

export async function exportArtifact(artifactId: number, format: 'docx' | 'pdf') {
  const response = await fetch(
    `${API_BASE}/artifacts/${artifactId}/export?format=${format}`,
    {
      headers: authHeaders(),
    },
  )
  if (!response.ok) {
    const body = await response.text()
    throw new ApiError(response.status, body || `导出失败: ${response.status}`)
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
