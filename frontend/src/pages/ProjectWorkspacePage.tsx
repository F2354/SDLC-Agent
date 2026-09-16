import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useSearchParams, useParams } from 'react-router-dom'

import {
  approveStageRun,
  confirmStage,
  exportArtifact,
  getCodeFile,
  getCodeTree,
  getProject,
  getProjectFlow,
  getProjectStats,
  getStageRunMessages,
  getTraceability,
  listActivityEvents,
  listProjectArtifacts,
  listProviders,
  listStageRunReviews,
  projectEventsUrl,
  rejectStageRun,
  runGeneratedCode,
  sendChatMessage,
  startStage,
  testGeneratedCode,
  updateArtifact,
  updateProject,
  type ActivityEvent,
  type Artifact,
  type CodeRun,
  type CodeTree,
  type Message,
  type Project,
  type ProjectStats,
  type ProjectFlow,
  type Provider,
  type Review,
  type Traceability,
} from '../lib/api'

const statusLabels: Record<string, string> = {
  collecting: '对话中',
  generating: '生成中',
  awaiting_review: '待评审',
  pending: '未开始',
  completed: '已完成',
  approved: '已通过',
  rejected: '已打回',
  failed: '失败',
  verification_failed: '验证未通过',
}

// 需要真实写盘并运行验证的阶段：只能使用自动模式。
const CODE_STAGES = new Set([
  'coding',
  'testing',
  'unit-test',
  'integration-test',
  'system-test',
  'prototype',
  'sprint-dev',
])

// 触发项目数据刷新的 SSE 事件。
const REFRESH_EVENTS = [
  'stage_status',
  'agent_started',
  'artifact_saved',
  'review_opened',
  'review_result',
  'review_suggested',
  'stage_completed',
  'error',
]



function renderTime(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false })
}

const agentLabels: Record<string, { name: string; short: string; icon: string }> = {
  requirements: { name: '需求分析师', short: 'REQ', icon: '⌕' },
  architecture: { name: '架构师', short: 'ARCH', icon: '⌘' },
  'detailed-design': { name: '设计工程师', short: 'DESIGN', icon: '◇' },
  coding: { name: '开发工程师', short: 'DEV', icon: '</>' },
  testing: { name: '测试工程师', short: 'TEST', icon: '✓' },
  'unit-test': { name: '测试工程师', short: 'UNIT', icon: '✓' },
  'integration-test': { name: '测试工程师', short: 'INT', icon: '⇄' },
  'system-test': { name: '测试工程师', short: 'SYSTEM', icon: '◎' },
  'risk-analysis': { name: '风险分析师', short: 'RISK', icon: '!' },
  evaluation: { name: '评审 Agent', short: 'REVIEW', icon: '◈' },
  'iteration-review': { name: '评审 Agent', short: 'REVIEW', icon: '◈' },
  prototype: { name: '开发工程师', short: 'PROTO', icon: '⌘' },
  'user-feedback': { name: '需求分析师', short: 'FEEDBACK', icon: '↗' },
  refinement: { name: '需求分析师', short: 'REFINE', icon: '↻' },
  backlog: { name: '统筹 Agent', short: 'BACKLOG', icon: '≡' },
  'sprint-planning': { name: '统筹 Agent', short: 'PLAN', icon: '◷' },
  'sprint-dev': { name: '开发工程师', short: 'SPRINT', icon: '</>' },
  'sprint-review': { name: '统筹 Agent', short: 'REVIEW', icon: '◈' },
  'sprint-retrospective': { name: '统筹 Agent', short: 'RETRO', icon: '↻' },
}

function getAgent(stageCode: string) {
  return agentLabels[stageCode] ?? { name: 'Agent', short: 'AGENT', icon: '✦' }
}

function flowStatusClass(status: string) {
  if (status === 'approved' || status === 'completed') return 'is-approved'
  if (status === 'collecting' || status === 'generating') return 'is-active'
  if (status === 'awaiting_review') return 'is-review'
  if (status === 'rejected' || status === 'failed' || status === 'verification_failed') return 'is-error'
  return 'is-pending'
}

type ProcessFlowProps = {
  flow: ProjectFlow
  startDisabled: boolean
  starting: string | null
  canStartAt: (index: number) => boolean
  onStart: (stageCode: string, mode: 'auto' | 'chat') => void
  className?: string
}

type FlowNodeProps = ProcessFlowProps & {
  stage: ProjectFlow['stages'][number]['stage']
  status: string
  index: number
}

function ProcessFlow({ flow, startDisabled, starting, canStartAt, onStart }: ProcessFlowProps) {
  const model = flow.process_model.code
  const stages = flow.stages
  const renderNode = (item: ProjectFlow['stages'][number], index: number, className = '') => (
    <FlowNode
      key={item.stage.code}
      flow={flow}
      stage={item.stage}
      status={item.status}
      index={index}
      startDisabled={startDisabled}
      starting={starting}
      canStartAt={canStartAt}
      onStart={onStart}
      className={className}
    />
  )

  const modelDescription: Record<string, string> = {
    waterfall: '主流程逐段交付，评审打回时沿回溯通道返回上一阶段修订。',
    'v-model': '左侧定义与实现、右侧验证与测试通过映射关系持续追溯。',
    iterative: '每轮开发都经过测试和评审，反馈会回到下一轮需求。',
    spiral: '以风险为中心展开多轮螺旋，每轮都经过评估再决定下一步。',
    prototype: '原型验证收集用户反馈，反馈会回流到需求精化和下一版原型。',
    scrum: 'Sprint 评审与回顾将结果反馈回产品待办，形成持续迭代闭环。',
  }

  const heading = (
    <div className="flow-model-heading">
      <span className="flow-model-kicker">{flow.process_model.name}</span>
      <span>{modelDescription[model] ?? '阶段节点、验证关系与回溯路径'}</span>
    </div>
  )

  if (model === 'v-model') {
    const leftCodes = new Set(['requirements', 'architecture', 'detailed-design'])
    const left = stages.filter(({ stage }) => leftCodes.has(stage.code))
    const coding = stages.find(({ stage }) => stage.code === 'coding')
    const right = stages.filter(({ stage }) => CODE_STAGES.has(stage.code) && stage.code !== 'coding')
    const pairs = [
      { left: left.find(({ stage }) => stage.code === 'requirements'), right: right.find(({ stage }) => stage.code === 'system-test'), label: '验收追溯' },
      { left: left.find(({ stage }) => stage.code === 'architecture'), right: right.find(({ stage }) => stage.code === 'integration-test'), label: '集成验证' },
      { left: left.find(({ stage }) => stage.code === 'detailed-design'), right: right.find(({ stage }) => stage.code === 'unit-test'), label: '模块验证' },
    ].filter((pair): pair is { left: ProjectFlow['stages'][number]; right: ProjectFlow['stages'][number]; label: string } => Boolean(pair.left && pair.right))

    return (
      <div className="process-flow process-flow-v-model">
        {heading}
        <div className="v-model-map">
          <div className="v-model-column v-model-left">
            <div className="flow-column-label">定义 / 实现</div>
            {pairs.map((pair) => renderNode(pair.left, stages.indexOf(pair.left), 'v-branch-node'))}
          </div>
          <div className="v-model-center">
            <div className="flow-column-label">汇合点</div>
            {coding ? renderNode(coding, stages.indexOf(coding), 'v-coding-node') : null}
            <div className="v-center-caption">代码是开发与验证的汇合点</div>
          </div>
          <div className="v-model-column v-model-right">
            <div className="flow-column-label">验证 / 测试</div>
            {pairs.map((pair) => (
              <div className="v-test-pair" key={pair.right.stage.code}>
                {renderNode(pair.right, stages.indexOf(pair.right), 'v-branch-node')}
                <span className="v-pair-label">{pair.label}</span>
              </div>
            ))}
          </div>
          <svg className="v-branch-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <path className="flow-line" d="M 25 16 L 50 84 L 75 16" />
            <path className="flow-line flow-line-strong" d="M 25 40 L 50 84 L 75 40" />
            <path className="flow-line flow-line-soft" d="M 25 64 L 50 84 L 75 64" />
          </svg>
        </div>
        <div className="flow-legend"><span><i className="legend-dot legend-main" />开发主线</span><span><i className="legend-dot legend-test" />测试对应</span><span><i className="legend-dot legend-back" />结果可回溯</span></div>
      </div>
    )
  }

  if (model === 'waterfall') {
    return (
      <div className="process-flow process-flow-waterfall">
        {heading}
        <div className="waterfall-map">
          <div className="waterfall-mainline" aria-hidden="true" />
          <div className="waterfall-track">
            {stages.map((item, index) => (
              <div className="waterfall-step" key={item.stage.code}>
                {renderNode(item, index)}
                {index < stages.length - 1 && <span className="flow-arrow flow-arrow-down">↓</span>}
              </div>
            ))}
          </div>
          <div className="waterfall-feedback">
            <span className="feedback-kicker">REVIEW LOOP</span>
            <span className="feedback-arrow">↶</span>
            <p>任一阶段评审打回后，沿回溯通道返回对应阶段修订，不会丢失后续验证上下文。</p>
          </div>
        </div>
        <div className="flow-legend"><span><i className="legend-dot legend-main" />阶段推进</span><span><i className="legend-dot legend-back" />评审回溯 / 重生成</span></div>
      </div>
    )
  }

  if (model === 'iterative') {
    return (
      <div className="process-flow process-flow-iterative">
        {heading}
        <div className="iteration-map">
          <div className="iteration-main-row">{stages.map((item, index) => renderNode(item, index, 'iteration-node'))}</div>
          <div className="iteration-loop-line"><span>迭代评审</span><b>↺</b><span>反馈进入下一轮需求</span></div>
          <div className="iteration-feedback-arrow">↑</div>
        </div>
        <div className="flow-legend"><span><i className="legend-dot legend-main" />本轮交付</span><span><i className="legend-dot legend-back" />下一轮回溯</span></div>
      </div>
    )
  }

  if (model === 'spiral') {
    return (
      <div className="process-flow process-flow-spiral">
        {heading}
        <div className="spiral-map">
          <div className="spiral-orbit spiral-orbit-outer" />
          <div className="spiral-orbit spiral-orbit-inner" />
          <div className="spiral-center"><span>RISK</span><b>风险<br />评估</b></div>
          <div className="spiral-nodes">{stages.map((item, index) => renderNode(item, index, item.stage.code === 'risk-analysis' ? 'spiral-risk-node' : ''))}</div>
          <div className="spiral-caption">每轮完成风险分析 → 设计 → 实现 → 验证 → 阶段评估，再决定是否进入下一轮。</div>
        </div>
        <div className="flow-legend"><span><i className="legend-dot legend-risk" />风险驱动</span><span><i className="legend-dot legend-back" />阶段评估回溯</span></div>
      </div>
    )
  }

  if (model === 'prototype') {
    return (
      <div className="process-flow process-flow-prototype">
        {heading}
        <div className="prototype-map">
          <div className="prototype-mainline">{stages.map((item, index) => renderNode(item, index, 'prototype-node'))}</div>
          <div className="prototype-feedback-path"><span>用户反馈</span><b>↺</b><span>需求精化 / 原型修订</span></div>
          <div className="prototype-feedback-line" aria-hidden="true" />
        </div>
        <div className="flow-legend"><span><i className="legend-dot legend-main" />构建主线</span><span><i className="legend-dot legend-back" />用户反馈回流</span></div>
      </div>
    )
  }

  if (model === 'scrum') {
    return (
      <div className="process-flow process-flow-scrum">
        {heading}
        <div className="scrum-map">
          <div className="scrum-track">{stages.map((item, index) => <div className="scrum-step" key={item.stage.code}>{renderNode(item, index, 'scrum-node')}{index < stages.length - 1 && <span className="scrum-arrow">→</span>}</div>)}</div>
          <div className="scrum-feedback"><span>Sprint 回顾 / 评审</span><b>↶</b><span>返回产品待办</span></div>
        </div>
        <div className="flow-legend"><span><i className="legend-dot legend-main" />Sprint 主线</span><span><i className="legend-dot legend-back" />持续反馈</span></div>
      </div>
    )
  }

  return (
    <div className="process-flow process-flow-generic">
      {heading}
      <div className="flow-generic-track">{stages.map((item, index) => renderNode(item, index))}</div>
    </div>
  )
}

function FlowNode({ stage, status, index, startDisabled, starting, canStartAt, onStart, className = '' }: FlowNodeProps) {
  const agent = getAgent(stage.code)
  const canStart = status === 'pending' && canStartAt(index)
  const canChat = !CODE_STAGES.has(stage.code)
  const retry = status === 'rejected' || status === 'verification_failed'
  return (
    <div className={`flow-node ${flowStatusClass(status)} ${className}`} title={stage.description || stage.name}>
      <div className="flow-node-topline"><span className="flow-node-index">{String(index + 1).padStart(2, '0')}</span><span className="flow-node-status">{statusLabels[status] ?? status}</span></div>
      <div className="flow-node-title">{stage.name}</div>
      <div className="flow-node-agent"><span className="flow-agent-icon">{agent.icon}</span><span>{agent.name}</span><b>{agent.short}</b></div>
      {(canStart || retry) && <div className="flow-node-actions">{canStart && canChat && <button onClick={() => onStart(stage.code, 'chat')} disabled={starting === stage.code || startDisabled}>对话</button>}<button onClick={() => onStart(stage.code, 'auto')} disabled={starting === stage.code || startDisabled}>{starting === stage.code ? '启动中' : retry ? '重试' : '自动'}</button></div>}
    </div>
  )
}

export default function ProjectWorkspacePage() {
  const { projectId } = useParams()
  const [searchParams] = useSearchParams()
  const tab = searchParams.get('tab') ?? 'chat'
  const [project, setProject] = useState<Project | null>(null)
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
  const [reviews, setReviews] = useState<Review[]>([])
  const [autoAdvance, setAutoAdvance] = useState(false)
  const [savingAutoAdvance, setSavingAutoAdvance] = useState(false)
  // SSE 实时状态：已连接时不再轮询；message_delta 用于逐段渲染 agent 回复。
  const [liveConnected, setLiveConnected] = useState(false)
  const [streamingText, setStreamingText] = useState('')

  const loadingRef = useRef(false)
  const mountedRef = useRef(true)
  const reloadTimerRef = useRef<number | null>(null)

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
        const [nextProject, nextFlow, nextArtifacts, nextEvents, nextStats, nextTrace, nextCodeTree] =
          await Promise.all([
            getProject(validProjectId),
            getProjectFlow(validProjectId),
            listProjectArtifacts(validProjectId),
            listActivityEvents(validProjectId),
            getProjectStats(validProjectId),
            getTraceability(validProjectId),
            getCodeTree(validProjectId),
          ])
        if (!mountedRef.current) return
        setProject(nextProject)
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

  const hasActiveStages =
    flow?.stages.some(({ status }) => status === 'generating' || status === 'collecting') ??
    false

  useEffect(() => {
    void load({ force: true })
  }, [load])

  // SSE 断开或服务端不可用时，退化为轮询兜底。
  useEffect(() => {
    if (liveConnected) return
    if (!hasActiveStages) return
    const timer = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(timer)
  }, [hasActiveStages, liveConnected, load])

  // 项目事件流订阅。
  useEffect(() => {
    if (validProjectId === null) return
    let source: EventSource
    try {
      source = new EventSource(projectEventsUrl(validProjectId))
    } catch {
      return
    }

    const scheduleReload = () => {
      if (reloadTimerRef.current !== null) return
      reloadTimerRef.current = window.setTimeout(() => {
        reloadTimerRef.current = null
        void load()
      }, 300)
    }

    source.onopen = () => {
      if (mountedRef.current) setLiveConnected(true)
    }
    source.onerror = () => {
      if (mountedRef.current) setLiveConnected(false)
    }
    source.addEventListener('message_delta', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as { content: string }
      if (mountedRef.current) setStreamingText((prev) => prev + data.content)
    })
    source.addEventListener('message', () => {
      if (!mountedRef.current) return
      setStreamingText('')
      scheduleReload()
    })
    for (const name of REFRESH_EVENTS) {
      source.addEventListener(name, scheduleReload)
    }

    return () => {
      source.close()
      if (reloadTimerRef.current !== null) {
        window.clearTimeout(reloadTimerRef.current)
        reloadTimerRef.current = null
      }
      setLiveConnected(false)
    }
  }, [validProjectId, load])

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

  // 自动推进开关跟随项目数据同步。
  useEffect(() => {
    if (flow) {
      setAutoAdvance(flow.auto_advance ?? false)
    }
  }, [flow])

  const collectingStage = flow?.stages.find(
    ({ status, stage_run_id }) => status === 'collecting' && !!stage_run_id,
  )
  const collectingRunId = collectingStage?.stage_run_id ?? null
  const awaitingStage = flow?.stages.find(
    ({ status, stage_run_id }) =>
      (status === 'awaiting_review' || status === 'verification_failed') && !!stage_run_id,
  )
  const awaitingRunId = awaitingStage?.stage_run_id ?? null

  useEffect(() => {
    if (!collectingRunId) {
      setMessages([])
      setStreamingText('')
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

  // 评审记录（含评审 Agent 自动建议），随阶段流转刷新。
  useEffect(() => {
    if (!awaitingRunId) {
      setReviews([])
      return
    }
    let stale = false
    listStageRunReviews(awaitingRunId)
      .then((list) => {
        if (stale || !mountedRef.current) return
        setReviews(list)
      })
      .catch(() => undefined)
    return () => {
      stale = true
    }
  }, [awaitingRunId, activityEvents.length])

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
    setStreamingText('')
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
      setStreamingText('')
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
      await confirmStage(collectingRunId)
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

  async function handleToggleAutoAdvance() {
    if (validProjectId === null || savingAutoAdvance) {
      return
    }
    const next = !autoAdvance
    setAutoAdvance(next)
    setSavingAutoAdvance(true)
    try {
      await updateProject(validProjectId, { auto_advance: next })
    } catch (err) {
      setAutoAdvance(!next)
      setError(err instanceof Error ? err.message : '切换自动推进失败')
    } finally {
      setSavingAutoAdvance(false)
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
      await load({ force: true })
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
  }

  const firstStage = flow?.stages[0]
  const firstStageNeedsStart =
    tab === 'chat' &&
    firstStage !== undefined &&
    (firstStage.status === 'pending' || firstStage.status === 'rejected') &&
    canStartAt(0)

  const agentReviews = reviews.filter((review) => review.reviewer_type === 'agent')
  const teamStages = flow?.stages ?? []
  const runningStages = teamStages.filter(({ status }) => status === 'collecting' || status === 'generating')
  const completedStages = teamStages.filter(({ status }) => status === 'approved' || status === 'completed')

  return (
    <div className="page-container workspace-frame flex min-h-full min-h-0 flex-col">
      <div className="workspace-header flex shrink-0 flex-wrap items-center justify-between gap-4">
        <div>
          <div className="workspace-breadcrumb">WORKSPACE / {flow?.process_model.name || 'PROCESS MODEL'}</div>
          <h1 className="page-title mt-1 text-2xl">
            {project?.name || `项目 #${projectId}`}
            <span
              className={`ml-3 inline-flex items-center gap-1.5 rounded-full px-2 py-1 align-middle text-[10px] font-semibold ${
                liveConnected ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'
              }`}
            >
              <span className="status-dot" /> {liveConnected ? '实时连接' : '轮询模式'}
            </span>
          </h1>
          <p className="mt-1 text-xs text-slate-500">{project?.folder || '本地项目工作区'}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600">
            <input
              type="checkbox"
              checked={autoAdvance}
              disabled={savingAutoAdvance}
              onChange={() => void handleToggleAutoAdvance()}
            />
            统筹自动推进
          </label>
          {providers.length > 0 && (
            <label className="text-sm text-slate-500">
              模型服务
              <select
                value={selectedProviderId ?? ''}
                onChange={(event) =>
                  setSelectedProviderId(event.target.value ? Number(event.target.value) : null)
                }
                className="ml-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-700"
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
      </div>

      <div className="team-strip">
        <div className="team-strip-heading"><span>AGENT TEAM</span><b>{runningStages.length > 0 ? `${runningStages.length} 个 Agent 正在工作` : '团队待命'}</b></div>
        <div className="team-agent-list">
          {teamStages.map(({ stage, status }) => {
            const agent = getAgent(stage.code)
            const active = status === 'collecting' || status === 'generating'
            const done = status === 'approved' || status === 'completed'
            return <div key={stage.code} className={`team-agent ${active ? 'active' : ''} ${done ? 'done' : ''}`} title={`${stage.name} · ${agent.name}`}><span className="team-agent-icon">{agent.icon}</span><span className="team-agent-copy"><b>{agent.name}</b><small>{stage.name}</small></span><i>{active ? 'RUNNING' : done ? 'DONE' : statusLabels[status] ?? status}</i></div>
          })}
          {teamStages.length === 0 && <span className="ide-empty">正在加载团队状态...</span>}
        </div>
        <div className="team-summary"><span>{completedStages.length}/{teamStages.length || 0} 阶段完成</span><span>{runningStages.length} 并行执行</span></div>
      </div>

      {error && <div className="mt-4 shrink-0 rounded-xl border border-red-100 bg-red-50 px-3.5 py-3 text-xs text-red-600">{error}</div>}

      {firstStageNeedsStart && (
        <div className="hero-panel mt-6 flex min-h-0 flex-1 flex-col items-center justify-center p-12 text-center">
          <h2 className="text-lg font-semibold">
            {firstStage?.status === 'rejected'
              ? '首阶段被打回，重新开始'
              : `开始「${firstStage?.stage.name ?? ''}」`}
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
            对应角色 Agent 将通过对话与你确认本阶段内容，确认后生成正式文档。
          </p>
          <div className="mt-6 flex gap-3">
            <button
              onClick={() => void handleStart(firstStage?.stage.code ?? '', 'chat')}
              disabled={starting !== null || startDisabled}
              className="primary-action px-5 py-2.5 text-sm font-semibold disabled:opacity-50"
            >
              {starting ? '启动中...' : '对话模式'}
            </button>
            <button
              onClick={() => void handleStart(firstStage?.stage.code ?? '', 'auto')}
              disabled={starting !== null || startDisabled}
              className="secondary-action px-5 py-2.5 text-sm font-semibold disabled:opacity-50"
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
        <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="workspace-stat stat-indigo p-4">
            <div className="text-xs text-slate-500">产物数量</div>
            <div className="mt-1 text-lg font-semibold">{stats.artifact_count}</div>
          </div>
          <div className="workspace-stat stat-sky p-4">
            <div className="text-xs text-slate-500">文档总字符</div>
            <div className="mt-1 text-lg font-semibold">{stats.total_chars}</div>
          </div>
          <div className="workspace-stat stat-emerald p-4">
            <div className="text-xs text-slate-500">已执行阶段</div>
            <div className="mt-1 text-lg font-semibold">
              {Object.values(stats.stage_counts).reduce((sum, value) => sum + value, 0)}
            </div>
          </div>
          <div className="workspace-stat stat-amber p-4">
            <div className="text-xs text-slate-500">追溯关系</div>
            <div className="mt-1 text-lg font-semibold">{traceability?.links.length ?? 0}</div>
          </div>
        </div>
      )}

      {flow && tab === 'code' && (
        <div className="surface-card mt-6 flex min-h-0 flex-1 flex-col p-5 lg:p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-slate-900">生成代码</h2>
            <div className="flex gap-2">
              <button
                onClick={() => void handleRunCode('run')}
                disabled={codeRunning !== null || !codeTree.exists}
                className="primary-action px-3 py-1.5 text-xs font-semibold"
              >
                {codeRunning === 'run' ? '运行中...' : '运行验证'}
              </button>
              <button
                onClick={() => void handleRunCode('test')}
                disabled={codeRunning !== null || !codeTree.exists}
                className="secondary-action px-3 py-1.5 text-xs font-semibold"
              >
                {codeRunning === 'test' ? '测试中...' : '运行测试'}
              </button>
            </div>
          </div>
          {!codeTree.exists ? (
            <p className="mt-3 text-sm text-slate-500">
              尚未生成代码文件，完成编码类阶段后自动写入项目目录。
            </p>
          ) : (
            <div className="mt-4 grid min-h-0 flex-1 grid-cols-3 gap-4">
              <div className="min-h-0 overflow-auto rounded-xl border border-slate-200 bg-slate-50/50 p-1">
                {codeTree.files.map((file) => (
                  <button
                    key={file.path}
                    onClick={() => void handleViewCode(file.path)}
                    className={`block w-full px-3 py-2 text-left text-xs ${
                      selectedCodePath === file.path
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'text-slate-600 hover:bg-slate-100'
                    }`}
                  >
                    {file.path}
                  </button>
                ))}
              </div>
              <div className="col-span-2">
                {selectedCodePath ? (
                  <pre className="h-full min-h-0 overflow-auto whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-950 px-4 py-3 font-mono text-xs leading-6 text-slate-200">
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
            <pre className="mt-4 max-h-72 shrink-0 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 px-4 py-3 font-mono text-xs leading-6 text-emerald-300">
              {codeOutput}
            </pre>
          )}
        </div>
      )}

      {flow && tab === 'stages' && (
        <div className="process-flow-section">
          <ProcessFlow flow={flow} startDisabled={startDisabled} starting={starting} canStartAt={canStartAt} onStart={(stageCode, mode) => void handleStart(stageCode, mode)} />
        </div>
      )}

      {collectingRunId && tab === 'chat' && (
        <section className="chat-panel workspace-conversation mt-4 flex min-h-0 flex-1 flex-col">
          <div className="chat-panel-header">
            <div className="flex items-center gap-3">
              <span className="chat-agent-avatar">✦</span>
              <div>
                <h2 className="text-sm font-bold text-slate-900">{collectingStage?.stage.name ?? ''} · 阶段对话</h2>
                <p className="mt-1 text-[11px] text-slate-400">与你协作的 Agent 会基于当前项目上下文持续追问和整理。</p>
              </div>
            </div>
            <span className="chat-live-pill"><span className="status-dot" /> AI 正在协作</span>
          </div>

          <div className="chat-scroll min-h-0 flex-1 overflow-y-auto px-5 py-6 lg:px-10">
            {messages.length === 0 && !streamingText && (
              <div className="chat-empty-state">
                <span className="chat-empty-icon">✦</span>
                <h3>从这里开始协作</h3>
                <p>介绍你的目标、用户和核心问题，Agent 会将它们整理成可评审的阶段产物。</p>
              </div>
            )}
            <div className="mx-auto max-w-3xl space-y-7">
              {messages.map((message) => {
                const isUser = message.role === 'user'
                return (
                  <div key={message.id} className={`chat-message ${isUser ? 'user' : 'agent'}`}>
                    {!isUser && <span className="chat-message-avatar">✦</span>}
                    <div className={isUser ? 'chat-user-content-wrap' : 'min-w-0 flex-1'}>
                      {!isUser && <div className="chat-message-label">{message.agent_code || 'SDLC Agent'}</div>}
                      <div className="chat-message-content">{message.content}</div>
                    </div>
                    {isUser && <span className="chat-message-avatar user-avatar">U</span>}
                  </div>
                )
              })}
              {streamingText && (
                <div className="chat-message agent">
                  <span className="chat-message-avatar">✦</span>
                  <div className="min-w-0 flex-1">
                    <div className="chat-message-label">SDLC Agent <span className="ml-1 text-indigo-400">正在输入</span></div>
                    <div className="chat-message-content">{streamingText}<span className="ml-0.5 animate-pulse text-indigo-500">▍</span></div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="chat-composer-wrap">
            <form onSubmit={handleChatSubmit} className="chat-composer">
              <textarea
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder="回复 Agent，补充本阶段信息..."
                rows={1}
                className="chat-composer-input"
              />
              <div className="chat-composer-footer">
                <span className="chat-hint">点击发送 · Shift + Enter 换行</span>
                <button type="submit" disabled={chatSending || !chatInput.trim()} className="chat-send-button">
                  {chatSending ? '发送中...' : '发送'} <span>↑</span>
                </button>
              </div>
            </form>
            <div className="chat-actions-row">
              <span className="chat-action-note">确认后将生成本阶段正式文档，并进入人工评审。</span>
              <button onClick={() => void handleConfirm()} disabled={confirming} className="chat-confirm-button">
                {confirming ? '正在生成阶段文档...' : '确认并生成阶段文档'} <span>→</span>
              </button>
            </div>
          </div>
        </section>
      )}

      {awaitingRunId && (tab === 'chat' || tab === 'stages') && (
        <div className="mt-6 shrink-0 rounded-lg border border-amber-200 bg-amber-50 p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">
              {awaitingStage?.stage.name ?? ''} · 阶段评审
            </h2>
            <span className="text-xs text-slate-500">
              产物已生成，通过后进入下一阶段
            </span>
          </div>

          {agentReviews.length > 0 && (
            <div className="mt-3 rounded-md border border-slate-200 bg-white p-3">
              <div className="text-xs font-medium text-slate-500">
                评审 Agent 建议（自动生成，仅供参考）
              </div>
              {agentReviews.map((review) => (
                <pre
                  key={review.id}
                  className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-700"
                >
                  {review.comment}
                </pre>
              ))}
            </div>
          )}

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
              className="rounded-md bg-green-700 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              通过
            </button>
            <button
              onClick={() => void handleReview('rejected')}
              disabled={reviewingId === awaitingRunId}
              className="rounded-md bg-red-600 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              打回
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            {autoAdvance
              ? '已开启统筹自动推进：通过后将自动启动下一阶段。'
              : '通过后可在阶段卡片上点击「自动生成」启动下一阶段；打回后可「重新生成」。'}
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

          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs text-slate-500">需求 → 用例</div>
              <div className="mt-1 font-semibold">
                {traceability.coverage.rq_with_uc}/{traceability.coverage.rq_total}
              </div>
            </div>
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs text-slate-500">需求 → 模块</div>
              <div className="mt-1 font-semibold">
                {traceability.coverage.rq_with_mod}/{traceability.coverage.rq_total}
              </div>
            </div>
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs text-slate-500">模块 → 测试用例</div>
              <div className="mt-1 font-semibold">
                {traceability.coverage.mod_with_tc}/{traceability.coverage.mod_total}
              </div>
            </div>
          </div>

          {traceability.warnings.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm text-amber-700">
              {traceability.warnings.map((warning, index) => (
                // 警告文本可能重复，使用索引作为 key 更安全。
                <li key={index}>{warning}</li>
              ))}
            </ul>
          )}

          {traceability.links.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-sm text-slate-600">
                查看全部追溯关系（{traceability.links.length} 条）
              </summary>
              <div className="mt-2 max-h-64 overflow-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 text-slate-400">
                      <th className="py-1.5 pr-4">来源</th>
                      <th className="py-1.5 pr-4">关系</th>
                      <th className="py-1.5">目标</th>
                    </tr>
                  </thead>
                  <tbody>
                    {traceability.links.map((link, index) => (
                      <tr key={index} className="border-b border-slate-100">
                        <td className="py-1.5 pr-4">
                          {link.from_type} {link.from_key}
                        </td>
                        <td className="py-1.5 pr-4 text-slate-500">{link.relation}</td>
                        <td className="py-1.5">
                          {link.to_type} {link.to_key}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
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
