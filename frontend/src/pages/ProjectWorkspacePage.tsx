import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useSearchParams, useParams } from 'react-router-dom'

import {
  approveStageRun,
  confirmRequirements,
  exportArtifact,
  getCodeFile,
  getCodeTree,
  getProjectFlow,
  getProjectStats,
  getStageRunMessages,
  getTraceability,
  listActivityEvents,
  listProjectArtifacts,
  listProviders,
  rejectStageRun,
  runGeneratedCode,
  sendChatMessage,
  startStage,
  testGeneratedCode,
  updateArtifact,
  type ActivityEvent,
  type Artifact,
  type CodeRun,
  type CodeTree,
  type Message,
  type ProjectStats,
  type ProjectFlow,
  type Provider,
  type Traceability,
} from '../lib/api'

const statusLabels: Record<string, string> = {
  collecting: '需求访谈中',
  generating: '生成中',
  awaiting_review: '待评审',
  pending: '未开始',
  completed: '已完成',
  approved: '已通过',
  rejected: '已打回',
  failed: '失败',
  verification_failed: '验证未通过',
}

function cardClass(status: string) {
  const base = 'rounded-lg border bg-white p-4 text-center text-sm transition-all duration-300'
  if (status === 'approved' || status === 'completed') {
    return `${base} border-green-300 bg-green-50`
  }
  if (status === 'awaiting_review') {
    return `${base} border-amber-300 bg-amber-50`
  }
  if (status === 'collecting' || status === 'generating') {
    return `${base} animate-pulse border-blue-300 bg-blue-50`
  }
  if (status === 'rejected' || status === 'failed') {
    return `${base} border-red-200 bg-red-50`
  }
  if (status === 'verification_failed') {
    return `${base} border-orange-300 bg-orange-50`
  }
  return `${base} border-slate-200`
}

function renderTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false })
}

export default function ProjectWorkspacePage() {
  const { projectId } = useParams()
  const [searchParams] = useSearchParams()
  const tab = searchParams.get('tab') ?? 'chat'
  const [flow, setFlow] = useState<ProjectFlow | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([])
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [traceability, setTraceability] = useState<Traceability | null>(null)
  const [codeTree, setCodeTree] = useState<CodeTree>({ exists: false, files: [] })
  const [selectedCodePath, setSelectedCodePath] = useState('')
  const [codeContent, setCodeContent] = useState('')
  const [codeOutput, setCodeOutput] = useState('')
  const [codeRunning, setCodeRunning] = useState<'run' | 'test' | null>(null)
  const [exportingId, setExportingId] = useState<string | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [selectedProviderId, setSelectedProviderId] = useState<number | null>(null)
  const [selectedArtifactId, setSelectedArtifactId] = useState<number | null>(null)
  const [editingArtifactId, setEditingArtifactId] = useState<number | null>(null)
  const [editContent, setEditContent] = useState('')
  const [starting, setStarting] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatSending, setChatSending] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [reviewComment, setReviewComment] = useState('')
  const [reviewingId, setReviewingId] = useState<number | null>(null)

  const loadingRef = useRef(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const projectIdNumber = Number(projectId)
  const validProjectId =
    Number.isInteger(projectIdNumber) && projectIdNumber > 0 ? projectIdNumber : null

  const load = useCallback(
    async (options: { force?: boolean } = {}) => {
      if (validProjectId === null) {
        setError('无效的项目 ID')
        return
      }
      // 轮询并发保护：上一轮请求未结束时跳过本轮，避免请求雪崩。
      if (loadingRef.current && !options.force) {
        return
      }
      loadingRef.current = true
      setError('')
      try {
        const [nextFlow, nextArtifacts, nextEvents, nextStats, nextTrace, nextCodeTree] =
          await Promise.all([
            getProjectFlow(validProjectId),
            listProjectArtifacts(validProjectId),
            listActivityEvents(validProjectId),
            getProjectStats(validProjectId),
            getTraceability(validProjectId),
            getCodeTree(validProjectId),
          ])
        if (!mountedRef.current) return
        setFlow(nextFlow)
        setArtifacts(nextArtifacts)
        setActivityEvents(nextEvents)
        setStats(nextStats)
        setTraceability(nextTrace)
        setCodeTree(nextCodeTree)
      } catch (err) {
        if (!mountedRef.current) return
        setError(err instanceof Error ? err.message : '加载失败')
      } finally {
        loadingRef.current = false
      }
    },
    [validProjectId],
  )

  const hasActiveStages = flow?.stages.some(({ status }) =>
    status === 'generating' || status === 'collecting',
  ) ?? false

  useEffect(() => {
    void load({ force: true })
    if (!hasActiveStages) return
    const timer = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(timer)
  }, [hasActiveStages, load])

  useEffect(() => {
    listProviders()
      .then((list) => {
        if (!mountedRef.current) return
        setProviders(list)
        setSelectedProviderId((prev) => prev ?? list[0]?.id ?? null)
      })
      .catch((err) => {
        if (!mountedRef.current) return
        setError(err instanceof Error ? err.message : '加载模型服务失败')
      })
  }, [])

  const collectingRunId =
    flow?.stages.find(({ status, stage_run_id }) => status === 'collecting' && !!stage_run_id)
      ?.stage_run_id ?? null
  const awaitingRunId =
    flow?.stages.find(({ status, stage_run_id }) => (status === 'awaiting_review' || status === 'verification_failed') && !!stage_run_id)
      ?.stage_run_id ?? null

  useEffect(() => {
    if (!collectingRunId) {
      setMessages([])
      return
    }
    // 竞态保护：只接受最后一次请求的结果。
    let stale = false
    getStageRunMessages(collectingRunId)
      .then((list) => {
        if (stale || !mountedRef.current) return
        setMessages(list)
      })
      .catch((err) => {
        if (stale || !mountedRef.current) return
        setError(err instanceof Error ? err.message : '加载对话失败')
      })
    return () => {
      stale = true
    }
  }, [collectingRunId])

  async function handleStart(stageCode: string, mode: 'auto' | 'chat' = 'auto') {
    if (validProjectId === null) {
      return
    }
    if (selectedProviderId === null) {
      setError('请先在「模型服务」页配置 Provider')
      return
    }
    setStarting(stageCode)
    setError('')
    try {
      await startStage(validProjectId, stageCode, {
        mode,
        provider_id: selectedProviderId,
      })
      await load({ force: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '启动阶段失败')
    } finally {
      setStarting(null)
    }
  }

  async function handleChatSubmit(event: FormEvent) {
    event.preventDefault()
    if (!collectingRunId || !chatInput.trim() || chatSending) {
      return
    }
    const content = chatInput.trim()
    setChatSending(true)
    setError('')
    // 临时 ID 使用负数，避免与后端真实 ID 冲突造成 React key 重复。
    const tempId = -Date.now()
    const userMessage: Message = {
      id: tempId,
      project_id: validProjectId ?? 0,
      stage_run_id: collectingRunId,
      role: 'user',
      agent_code: null,
      content,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMessage])
    try {
      await sendChatMessage(collectingRunId, content)
      // 成功后再清空输入：失败时用户内容不丢失。
      setChatInput('')
      // 重新拉取以获得真实 ID 与助手回复，避免临时消息残留。
      setMessages(await getStageRunMessages(collectingRunId))
    } catch (err) {
      setError(err instanceof Error ? err.message : '发送失败')
      setMessages((prev) => prev.filter((item) => item.id !== tempId))
    } finally {
      setChatSending(false)
    }
  }

  async function handleConfirm() {
    if (!collectingRunId) {
      return
    }
    setConfirming(true)
    setError('')
    try {
      await confirmRequirements(collectingRunId)
      await load({ force: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败')
    } finally {
      setConfirming(false)
    }
  }

  async function handleReview(result: 'approved' | 'rejected') {
    if (!awaitingRunId) {
      return
    }
    setReviewingId(awaitingRunId)
    setError('')
    try {
      if (result === 'approved') {
        await approveStageRun(awaitingRunId, reviewComment)
      } else {
        await rejectStageRun(awaitingRunId, reviewComment)
      }
      setReviewComment('')
      await load({ force: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '评审失败')
    } finally {
      setReviewingId(null)
    }
  }

  function handleStartEdit(artifact: Artifact) {
    // 存在未保存修改时先确认，避免切换文档静默丢稿。
    if (editingArtifactId !== null && editingArtifactId !== artifact.id) {
      const original = artifacts.find((item) => item.id === editingArtifactId)
      if (original !== undefined && original.content_md !== editContent) {
        if (!window.confirm('当前文档有未保存的修改，放弃并切换吗？')) {
          return
        }
      }
    }
    setSelectedArtifactId(artifact.id)
    setEditContent(artifact.content_md)
    setEditingArtifactId(artifact.id)
  }

  async function handleSaveArtifact(artifact: Artifact) {
    if (editingArtifactId !== artifact.id) {
      return
    }
    setError('')
    try {
      const updated = await updateArtifact(artifact.id, editContent)
      setArtifacts((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      setEditingArtifactId(null)
      setSelectedArtifactId(updated.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存修订失败')
    }
  }

  async function handleExport(artifact: Artifact, format: 'docx' | 'pdf') {
    const key = `${artifact.id}-${format}`
    setExportingId(key)
    setError('')
    try {
      const blob = await exportArtifact(artifact.id, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `artifact-${artifact.id}.${format}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      // 延迟释放：部分浏览器在 click 后仍需要 URL 才能完成下载。
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (err) {
      setError(err instanceof Error ? err.message : '导出失败')
    } finally {
      setExportingId(null)
    }
  }

  async function handleViewCode(path: string) {
    if (validProjectId === null) {
      return
    }
    setSelectedCodePath(path)
    setError('')
    try {
      setCodeContent(await getCodeFile(validProjectId, path))
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取代码失败')
    }
  }

  async function handleRunCode(kind: 'run' | 'test') {
    if (validProjectId === null) {
      return
    }
    setCodeRunning(kind)
    setError('')
    try {
      const result: CodeRun =
        kind === 'run'
          ? await runGeneratedCode(validProjectId)
          : await testGeneratedCode(validProjectId)
      setCodeOutput(
        `${kind === 'run' ? '运行验证' : '测试运行'} ${result.ok ? '成功' : '失败'}\n${result.output}`,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '执行失败')
    } finally {
      setCodeRunning(null)
    }
  }

  // 未选择 Provider 时禁止启动阶段，避免以 null provider 发起请求。
  const startDisabled = selectedProviderId === null

  const canStartAt = (index: number) => {
    if (!flow) {
      return false
    }
    if (index === 0) {
      return true
    }
    return flow.stages[index - 1].status === 'approved'
      || flow.stages[index - 1].status === 'verification_failed'
  }

  const requirementsStage = flow?.stages[0]
  const requirementsNeedsStart =
    tab === 'chat' &&
    requirementsStage !== undefined &&
    (requirementsStage.status === 'pending' || requirementsStage.status === 'rejected')

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold">项目 #{projectId}</h1>
          <p className="text-sm text-slate-500">
            {flow ? `${flow.process_model.name}工作台` : '加载中...'}
          </p>
        </div>
        {providers.length > 0 && (
          <label className="text-sm text-slate-500">
            模型服务
            <select
              value={selectedProviderId ?? ''}
              onChange={(event) =>
                setSelectedProviderId(event.target.value ? Number(event.target.value) : null)
              }
              className="ml-2 rounded-md border border-slate-300 px-3 py-1.5"
            >
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name} · {provider.default_model || '未设默认模型'}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {error && <div className="mt-4 shrink-0 text-sm text-red-600">{error}</div>}

      {requirementsNeedsStart && (
        <div className="mt-6 flex min-h-0 flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white p-12 text-center">
          <h2 className="text-lg font-semibold">
            {requirementsStage?.status === 'rejected' ? '需求被打回，重新开始访谈' : '开始需求访谈'}
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
            需求分析师 Agent 将通过对话收集项目需求，确认后生成需求规格说明书。
          </p>
          <div className="mt-6 flex gap-3">
            <button
              onClick={() => void handleStart('requirements', 'chat')}
              disabled={starting === 'requirements' || startDisabled}
              className="rounded-md bg-slate-900 px-5 py-2.5 text-sm text-white disabled:opacity-50"
            >
              {starting === 'requirements' ? '启动中...' : '访谈模式'}
            </button>
            <button
              onClick={() => void handleStart('requirements', 'auto')}
              disabled={starting === 'requirements' || startDisabled}
              className="rounded-md border border-slate-300 px-5 py-2.5 text-sm text-slate-600 disabled:opacity-50"
            >
              自动生成
            </button>
            {startDisabled && (
              <p className="text-sm text-amber-600">请先在「模型服务」页配置 Provider</p>
            )}
          </div>
        </div>
      )}

      {tab === 'stages' && stats && (
        <div className="mt-6 grid grid-cols-4 gap-3">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">产物数量</div>
            <div className="mt-1 text-lg font-semibold">{stats.artifact_count}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">文档总字符</div>
            <div className="mt-1 text-lg font-semibold">{stats.total_chars}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">已执行阶段</div>
            <div className="mt-1 text-lg font-semibold">
              {Object.values(stats.stage_counts).reduce((sum, value) => sum + value, 0)}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">追溯条目</div>
            <div className="mt-1 text-lg font-semibold">
              {Object.values(stats.entity_counts).reduce((sum, value) => sum + value, 0)}
            </div>
          </div>
        </div>
      )}

      {flow && tab === 'code' && (
        <div className="mt-6 flex min-h-0 flex-1 flex-col rounded-lg border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">生成代码</h2>
            <div className="flex gap-2">
              <button
                onClick={() => void handleRunCode('run')}
                disabled={codeRunning !== null || !codeTree.exists}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white"
              >
                {codeRunning === 'run' ? '运行中...' : '运行验证'}
              </button>
              <button
                onClick={() => void handleRunCode('test')}
                disabled={codeRunning !== null || !codeTree.exists}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600"
              >
                {codeRunning === 'test' ? '测试中...' : '运行测试'}
              </button>
            </div>
          </div>
          {!codeTree.exists ? (
            <p className="mt-3 text-sm text-slate-500">
              尚未生成代码文件，完成“编码骨架”阶段后自动写入项目目录。
            </p>
          ) : (
            <div className="mt-3 grid min-h-0 flex-1 grid-cols-3 gap-3">
              <div className="min-h-0 overflow-auto rounded-md border border-slate-200">
                {codeTree.files.map((file) => (
                  <button
                    key={file.path}
                    onClick={() => void handleViewCode(file.path)}
                    className={`block w-full px-3 py-2 text-left text-xs ${
                      selectedCodePath === file.path
                        ? 'bg-slate-900 text-white'
                        : 'text-slate-600 hover:bg-slate-100'
                    }`}
                  >
                    {file.path}
                  </button>
                ))}
              </div>
              <div className="col-span-2">
                {selectedCodePath ? (
                  <pre className="h-full min-h-0 overflow-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                    {codeContent}
                  </pre>
                ) : (
                  <div className="flex h-full items-center justify-center rounded-md border border-dashed border-slate-300 text-sm text-slate-500">
                    选择左侧文件查看内容
                  </div>
                )}
              </div>
            </div>
          )}
          {codeOutput && (
            <pre className="mt-3 max-h-72 shrink-0 overflow-auto whitespace-pre-wrap rounded-md bg-slate-900 px-3 py-2 text-xs text-green-300">
              {codeOutput}
            </pre>
          )}
        </div>
      )}

      {flow && tab === 'stages' && (
        <div className="mt-6 grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
          {flow.stages.map(({ stage, status }, index) => (
            <div key={stage.code} className={cardClass(status)}>
              <div className="mx-auto mb-2 h-8 w-8 rounded-full bg-slate-900 text-center leading-8 text-white">
                {index + 1}
              </div>
              <div className="truncate font-medium" title={stage.description || stage.name}>{stage.name}</div>
              <div className="mt-1 text-xs text-slate-500">
                {statusLabels[status] ?? status}
              </div>
              {status === 'pending' && canStartAt(index) && stage.code === 'requirements' && (
                <div className="mt-3 flex flex-col gap-2">
                  <button
                    onClick={() => void handleStart(stage.code, 'chat')}
                    disabled={starting === stage.code}
                    className="rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white"
                  >
                    {starting === stage.code ? '启动中...' : '访谈模式'}
                  </button>
                  <button
                    onClick={() => void handleStart(stage.code, 'auto')}
                    disabled={starting === stage.code || startDisabled}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 disabled:opacity-50"
                  >
                    自动生成
                  </button>
                </div>
              )}
              {status === 'pending' && canStartAt(index) && stage.code !== 'requirements' && (
                <button
                  onClick={() => void handleStart(stage.code, 'auto')}
                  disabled={starting === stage.code || startDisabled}
                  className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-50"
                >
                  {starting === stage.code ? '启动中...' : '开始本阶段'}
                </button>
                )}
                {(status === 'rejected' || status === 'verification_failed') && (
                <button
                onClick={() => void handleStart(stage.code, 'auto')}
                disabled={starting === stage.code || startDisabled}
                className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 disabled:opacity-50"
                >
                重新生成
                </button>
                )}
            </div>
          ))}
        </div>
      )}

      {collectingRunId && tab === 'chat' && (
        <div className="mt-6 flex min-h-0 flex-1 flex-col rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="shrink-0 font-medium">需求访谈</h2>
          <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`max-w-[80%] rounded-md px-3 py-2 text-sm ${
                  message.role === 'user'
                    ? 'ml-auto bg-slate-900 text-white'
                    : 'bg-slate-100 text-slate-800'
                }`}
              >
                {message.content}
              </div>
            ))}
          </div>
          <form onSubmit={handleChatSubmit} className="mt-4 flex shrink-0 gap-2">
            <input
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder="补充项目需求..."
              className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
            <button
              disabled={chatSending || !chatInput.trim()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white"
            >
              发送
            </button>
          </form>
          <button
            onClick={() => void handleConfirm()}
            disabled={confirming}
            className="mt-3 shrink-0 self-start rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700"
          >
            {confirming ? '正在生成需求文档...' : '确认并生成需求文档'}
          </button>
        </div>
      )}

      {awaitingRunId && (tab === 'chat' || tab === 'stages') && (
        <div className="mt-6 shrink-0 rounded-lg border border-amber-200 bg-amber-50 p-5">
          <h2 className="font-medium">阶段评审</h2>
          <textarea
            value={reviewComment}
            onChange={(event) => setReviewComment(event.target.value)}
            placeholder="评审意见（可选）"
            className="mt-3 min-h-20 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          />
          <div className="mt-3 flex gap-2">
            <button
              onClick={() => void handleReview('approved')}
              disabled={reviewingId === awaitingRunId}
              className="rounded-md bg-green-700 px-4 py-2 text-sm text-white"
            >
              通过
            </button>
            <button
              onClick={() => void handleReview('rejected')}
              disabled={reviewingId === awaitingRunId}
              className="rounded-md bg-red-600 px-4 py-2 text-sm text-white"
            >
              打回
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            打回后可在阶段卡片上点击“重新生成”。
          </p>
        </div>
      )}

      {flow && tab === 'artifacts' && (
        <div className="mt-6">
          <h2 className="font-medium">阶段产物</h2>
          <div className="mt-3 space-y-2">
            {artifacts.length === 0 && (
              <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
                暂无产物，按流程开始阶段后自动生成。
              </div>
            )}
            {artifacts.map((artifact) => (
              <div key={artifact.id} className="rounded-lg border border-slate-200 bg-white">
                <button
                  onClick={() =>
                    setSelectedArtifactId(
                      selectedArtifactId === artifact.id ? null : artifact.id,
                    )
                  }
                  className="flex w-full items-center justify-between px-4 py-3 text-left text-sm"
                >
                  <span className="font-medium">{artifact.title}</span>
                  <span className="text-xs text-slate-400">
                    v{artifact.current_version} · {statusLabels[artifact.status] ?? artifact.status}
                  </span>
                </button>
                {selectedArtifactId === artifact.id && editingArtifactId !== artifact.id && (
                  <div className="border-t border-slate-200">
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap px-4 py-3 text-sm">
                      {artifact.content_md}
                    </pre>
                    <div className="border-t border-slate-100 px-4 py-2">
                      <button
                        onClick={() => void handleExport(artifact, 'docx')}
                        disabled={exportingId === `${artifact.id}-docx`}
                        className="mr-2 rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600"
                      >
                        {exportingId === `${artifact.id}-docx` ? '导出中...' : '导出 Word'}
                      </button>
                      <button
                        onClick={() => void handleExport(artifact, 'pdf')}
                        disabled={exportingId === `${artifact.id}-pdf`}
                        className="mr-2 rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600"
                      >
                        {exportingId === `${artifact.id}-pdf` ? '导出中...' : '导出 PDF'}
                      </button>
                      <button
                        onClick={() => void handleStartEdit(artifact)}
                        className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600"
                      >
                        编辑文档
                      </button>
                    </div>
                  </div>
                )}
                {selectedArtifactId === artifact.id && editingArtifactId === artifact.id && (
                  <div className="border-t border-slate-200 p-4">
                    <textarea
                      value={editContent}
                      onChange={(event) => setEditContent(event.target.value)}
                      className="min-h-72 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                    />
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={() => void handleSaveArtifact(artifact)}
                        className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white"
                      >
                        保存新版本
                      </button>
                      <button
                        onClick={() => setEditingArtifactId(null)}
                        className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-600"
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {traceability && tab === 'artifacts' && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="font-medium">追溯矩阵</h2>
          {traceability.warnings.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-amber-700">
              {traceability.warnings.map((warning, index) => (
                // 警告文本可能重复，使用索引作为 key 更安全。
                <li key={index}>{warning}</li>
              ))}
            </ul>
          )}
          {traceability.rows.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">暂无产物可追溯。</p>
          ) : (
            <div className="mt-3 overflow-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs text-slate-400">
                    <th className="py-2 pr-4">产物</th>
                    <th className="py-2 pr-4">阶段</th>
                    <th className="py-2 pr-4">RQ</th>
                    <th className="py-2 pr-4">UC</th>
                    <th className="py-2 pr-4">MOD</th>
                    <th className="py-2">TC</th>
                  </tr>
                </thead>
                <tbody>
                  {traceability.rows.map((row) => (
                    <tr key={row.artifact_id} className="border-b border-slate-100">
                      <td className="py-2 pr-4">{row.title}</td>
                      <td className="py-2 pr-4">{row.stage_code}</td>
                      <td className="py-2 pr-4">{row.entities.RQ.length}</td>
                      <td className="py-2 pr-4">{row.entities.UC.length}</td>
                      <td className="py-2 pr-4">{row.entities.MOD.length}</td>
                      <td className="py-2">{row.entities.TC.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'logs' && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="font-medium">Agent 活动日志</h2>
          <ul className="mt-3 max-h-72 space-y-2 overflow-auto text-sm">
            {activityEvents.length === 0 && (
              <li className="text-slate-500">暂无活动记录。</li>
            )}
            {activityEvents.map((event) => (
              <li key={event.id} className="flex items-start gap-2 text-slate-600">
                <span className="shrink-0 text-xs text-slate-400">
                  {renderTime(event.created_at)}
                </span>
                <span>{event.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
