import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'

import {
  approveStageRun,
  confirmRequirements,
  getProjectFlow,
  getStageRunMessages,
  listProjectArtifacts,
  rejectStageRun,
  sendChatMessage,
  startStage,
  type Artifact,
  type Message,
  type ProjectFlow,
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
}

export default function ProjectWorkspacePage() {
  const { projectId } = useParams()
  const [flow, setFlow] = useState<ProjectFlow | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [selectedArtifactId, setSelectedArtifactId] = useState<number | null>(null)
  const [starting, setStarting] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatSending, setChatSending] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [reviewComment, setReviewComment] = useState('')
  const [reviewingId, setReviewingId] = useState<number | null>(null)

  async function load() {
    const id = Number(projectId)
    if (!Number.isFinite(id)) {
      setError('无效的项目 ID')
      return
    }
    try {
      const [nextFlow, nextArtifacts] = await Promise.all([
        getProjectFlow(id),
        listProjectArtifacts(id),
      ])
      setFlow(nextFlow)
      setArtifacts(nextArtifacts)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    }
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(timer)
  }, [projectId])

  const collectingRunId =
    flow?.stages.find(({ status, stage_run_id }) => status === 'collecting' && !!stage_run_id)
      ?.stage_run_id ?? null
  const awaitingRunId =
    flow?.stages.find(({ status, stage_run_id }) => status === 'awaiting_review' && !!stage_run_id)
      ?.stage_run_id ?? null

  useEffect(() => {
    if (!collectingRunId) {
      setMessages([])
      return
    }
    getStageRunMessages(collectingRunId)
      .then(setMessages)
      .catch((err) => setError(err instanceof Error ? err.message : '加载对话失败'))
  }, [collectingRunId])

  async function handleStart(stageCode: string, mode: 'auto' | 'chat' = 'auto') {
    const id = Number(projectId)
    if (!Number.isFinite(id)) {
      return
    }
    setStarting(stageCode)
    setError('')
    try {
      await startStage(id, stageCode, { mode })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '启动阶段失败')
    } finally {
      setStarting(null)
    }
  }

  async function handleChatSubmit(event: FormEvent) {
    event.preventDefault()
    if (!collectingRunId || !chatInput.trim()) {
      return
    }
    const content = chatInput.trim()
    setChatInput('')
    setChatSending(true)
    setError('')
    try {
      const userMessage: Message = {
        id: Date.now(),
        project_id: Number(projectId),
        stage_run_id: collectingRunId,
        role: 'user',
        agent_code: null,
        content,
        created_at: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, userMessage])
      const reply = await sendChatMessage(collectingRunId, content)
      setMessages((prev) => [...prev, reply])
    } catch (err) {
      setError(err instanceof Error ? err.message : '发送失败')
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
      await load()
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
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '评审失败')
    } finally {
      setReviewingId(null)
    }
  }

  const canStartAt = (index: number) => {
    if (!flow) {
      return false
    }
    if (index === 0) {
      return true
    }
    return flow.stages[index - 1].status === 'approved'
  }

  return (
    <div>
      <h1 className="text-lg font-semibold">项目 #{projectId}</h1>
      <p className="text-sm text-slate-500">
        {flow ? `${flow.process_model.name}工作台` : '加载中...'}
      </p>

      {error && <div className="mt-4 text-sm text-red-600">{error}</div>}

      {flow && (
        <div className="mt-6 grid grid-cols-5 gap-3">
          {flow.stages.map(({ stage, status }, index) => (
            <div
              key={stage.code}
              className="rounded-lg border border-slate-200 bg-white p-4 text-center text-sm"
            >
              <div className="mx-auto mb-2 h-8 w-8 rounded-full bg-slate-900 text-center leading-8 text-white">
                {index + 1}
              </div>
              <div className="font-medium">{stage.name}</div>
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
                    disabled={starting === stage.code}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600"
                  >
                    自动生成
                  </button>
                </div>
              )}
              {status === 'pending' && canStartAt(index) && stage.code !== 'requirements' && (
                <button
                  onClick={() => void handleStart(stage.code, 'auto')}
                  disabled={starting === stage.code}
                  className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-xs text-white"
                >
                  {starting === stage.code ? '启动中...' : '开始本阶段'}
                </button>
              )}
              {status === 'rejected' && (
                <button
                  onClick={() => void handleStart(stage.code, 'auto')}
                  disabled={starting === stage.code}
                  className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600"
                >
                  重新生成
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {collectingRunId && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="font-medium">需求访谈</h2>
          <div className="mt-3 max-h-80 space-y-2 overflow-auto">
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
          <form onSubmit={handleChatSubmit} className="mt-4 flex gap-2">
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
            className="mt-3 rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700"
          >
            {confirming ? '正在生成需求文档...' : '确认并生成需求文档'}
          </button>
        </div>
      )}

      {awaitingRunId && (
        <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-5">
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

      {flow && (
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
                {selectedArtifactId === artifact.id && (
                  <pre className="max-h-96 overflow-auto whitespace-pre-wrap border-t border-slate-200 px-4 py-3 text-sm">
                    {artifact.content_md}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
