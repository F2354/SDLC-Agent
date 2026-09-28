import { useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { useSearchParams, useParams } from 'react-router-dom'

import {
  approveStageRun,
  confirmStage,
  exportArtifact,
  getCodeFile,
  getCodeTree,
  getProject,
  getGitStatus,
  getGitDiff,
  initGit,
  getGitLog,
  commitGit,
  getProjectFlow,
  getProjectStats,
  listProjectSkills,
  getProjectSkill,
  listProjectMcp,
  discoverProjectMcp,
  getStageRunMessages,
  getTraceability,
  listActivityEvents,
  listProjectArtifacts,
  listProviders,
  listStageRunReviews,
  projectEventsUrl,
  rejectStageRun,
  runGeneratedCode,
  saveCodeFile,
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
  type GitStatus,
  type SkillSummary,
  type Skill,
  type McpServer,
  type ProjectStats,
  type ProjectFlow,
  type Provider,
  type Review,
  type ToolUsage,
  type Traceability,
} from '../lib/api'
import { MarkdownText } from '../components/MarkdownText'

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

// 对话空态的建议问题：降低"从零开口"的门槛。
const CHAT_SUGGESTIONS = [
  '这个系统主要解决什么问题？目标用户是谁？',
  '有哪些必须满足的约束（技术栈、合规、部署环境）？',
  '列一下最核心的 3 个功能场景',
]

/** 只取时分，用于消息时间戳。 */
function formatClock(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
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
  /** 运行中的工具调用（来自 agent_tool 事件），按 stage_run_id 归档。 */
  liveTools: Record<number, ToolUsage[]>
  className?: string
}

type FlowNodeProps = ProcessFlowProps & {
  item: ProjectFlow['stages'][number]
  index: number
}

/* ============================================================
   过程模型画布：布局表（坐标 + 边）→ SVG 连线 + HTML 节点卡片
   每个模型一份布局定义，边绘制在真实坐标之间并永远精准连接；
   V 模型是真正的 V 形，瀑布是阶梯，Scrum 是闭环圆环。
   ============================================================ */

type FlowPoint = { x: number; y: number }
type FlowEdgeKind = 'flow' | 'pair' | 'feedback'
type FlowEdgeDef = { from: string; to: string; kind: FlowEdgeKind; label?: string; bend?: number; labelDy?: number }
type ModelLayout = {
  positions: Record<string, FlowPoint>
  edges: FlowEdgeDef[]
  hub?: { x: number; y: number; kicker: string; title: string }
  rings?: { cx: number; cy: number; rx: number; ry: number }[]
}

const MODEL_LAYOUTS: Record<string, ModelLayout> = {
  'v-model': {
    positions: {
      requirements: { x: 11, y: 12 },
      architecture: { x: 17, y: 40 },
      'detailed-design': { x: 30, y: 66 },
      coding: { x: 50, y: 89 },
      'unit-test': { x: 70, y: 66 },
      'integration-test': { x: 83, y: 40 },
      'system-test': { x: 89, y: 12 },
    },
    edges: [
      { from: 'requirements', to: 'architecture', kind: 'flow' },
      { from: 'architecture', to: 'detailed-design', kind: 'flow' },
      { from: 'detailed-design', to: 'coding', kind: 'flow' },
      { from: 'coding', to: 'unit-test', kind: 'flow' },
      { from: 'unit-test', to: 'integration-test', kind: 'flow' },
      { from: 'integration-test', to: 'system-test', kind: 'flow' },
      { from: 'detailed-design', to: 'unit-test', kind: 'pair', label: '模块验证' },
      { from: 'architecture', to: 'integration-test', kind: 'pair', label: '集成验证' },
      { from: 'requirements', to: 'system-test', kind: 'pair', label: '验收追溯' },
    ],
  },
  waterfall: {
    positions: {
      requirements: { x: 10, y: 12 },
      architecture: { x: 29, y: 30 },
      'detailed-design': { x: 48, y: 48 },
      coding: { x: 67, y: 66 },
      testing: { x: 87, y: 84 },
    },
    edges: [
      { from: 'requirements', to: 'architecture', kind: 'flow' },
      { from: 'architecture', to: 'detailed-design', kind: 'flow' },
      { from: 'detailed-design', to: 'coding', kind: 'flow' },
      { from: 'coding', to: 'testing', kind: 'flow' },
      { from: 'testing', to: 'requirements', kind: 'feedback', label: '评审回溯 · 打回即沿通道返回修订', bend: 26 },
    ],
  },
  iterative: {
    positions: {
      requirements: { x: 9, y: 16 },
      architecture: { x: 27, y: 16 },
      'detailed-design': { x: 45, y: 16 },
      coding: { x: 63, y: 16 },
      testing: { x: 81, y: 16 },
      'iteration-review': { x: 45, y: 72 },
    },
    edges: [
      { from: 'requirements', to: 'architecture', kind: 'flow' },
      { from: 'architecture', to: 'detailed-design', kind: 'flow' },
      { from: 'detailed-design', to: 'coding', kind: 'flow' },
      { from: 'coding', to: 'testing', kind: 'flow' },
      { from: 'testing', to: 'iteration-review', kind: 'flow', bend: 10 },
      { from: 'iteration-review', to: 'requirements', kind: 'feedback', label: '评审产出下一轮改进需求（RQ-xxx）', bend: 22 },
    ],
  },
  spiral: {
    positions: {
      requirements: { x: 11, y: 24 },
      'risk-analysis': { x: 34, y: 10 },
      architecture: { x: 59, y: 12 },
      coding: { x: 82, y: 28 },
      testing: { x: 79, y: 58 },
      evaluation: { x: 49, y: 78 },
    },
    edges: [
      { from: 'requirements', to: 'risk-analysis', kind: 'flow' },
      { from: 'risk-analysis', to: 'architecture', kind: 'flow' },
      { from: 'architecture', to: 'coding', kind: 'flow' },
      { from: 'coding', to: 'testing', kind: 'flow' },
      { from: 'testing', to: 'evaluation', kind: 'flow' },
      { from: 'evaluation', to: 'requirements', kind: 'feedback', label: '进入下一轮螺旋 / 交付', bend: -24 },
    ],
    hub: { x: 48, y: 44, kicker: 'RISK', title: '风险驱动' },
    rings: [
      { cx: 48, cy: 44, rx: 27, ry: 31 },
      { cx: 48, cy: 44, rx: 15, ry: 17 },
    ],
  },
  prototype: {
    positions: {
      requirements: { x: 9, y: 18 },
      prototype: { x: 30, y: 18 },
      'user-feedback': { x: 52, y: 18 },
      refinement: { x: 75, y: 18 },
      coding: { x: 44, y: 72 },
      testing: { x: 76, y: 72 },
    },
    edges: [
      { from: 'requirements', to: 'prototype', kind: 'flow' },
      { from: 'prototype', to: 'user-feedback', kind: 'flow' },
      { from: 'user-feedback', to: 'refinement', kind: 'flow' },
      { from: 'refinement', to: 'coding', kind: 'flow', bend: -12 },
      { from: 'coding', to: 'testing', kind: 'flow' },
      { from: 'user-feedback', to: 'prototype', kind: 'feedback', label: '原型修订', bend: -12, labelDy: 11 },
    ],
  },
  scrum: {
    positions: {
      backlog: { x: 50, y: 8 },
      'sprint-planning': { x: 87, y: 34 },
      'sprint-dev': { x: 69, y: 84 },
      'sprint-review': { x: 31, y: 84 },
      'sprint-retrospective': { x: 13, y: 34 },
    },
    edges: [
      { from: 'backlog', to: 'sprint-planning', kind: 'flow' },
      { from: 'sprint-planning', to: 'sprint-dev', kind: 'flow' },
      { from: 'sprint-dev', to: 'sprint-review', kind: 'flow' },
      { from: 'sprint-review', to: 'sprint-retrospective', kind: 'flow' },
      { from: 'sprint-retrospective', to: 'backlog', kind: 'feedback', label: '回顾回流待办', bend: 20 },
    ],
    hub: { x: 50, y: 48, kicker: 'SPRINT', title: '迭代闭环' },
  },
}

/** 二次贝塞尔：bend 为沿法向的弯曲量（画布坐标系单位）。 */
function edgePath(a: FlowPoint, b: FlowPoint, bend = 0): { d: string; mid: FlowPoint } {
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  if (!bend) return { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, mid: { x: mx, y: my } }
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy) || 1
  const cx = mx + (-dy / len) * bend
  const cy = my + (dx / len) * bend
  return { d: `M ${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}`, mid: { x: (mx + cx) / 2, y: (my + cy) / 2 } }
}

/** 把边的端点沿各轴回缩，避免线条/箭头钻进节点卡片下方。 */
function trim(a: FlowPoint, b: FlowPoint, rx = 10, ry = 8.5): FlowPoint {
  const dx = b.x - a.x
  const dy = b.y - a.y
  return {
    x: b.x - Math.sign(dx) * Math.min(Math.abs(dx) / 2, rx),
    y: b.y - Math.sign(dy) * Math.min(Math.abs(dy) / 2, ry),
  }
}

function ProcessFlow({ flow, startDisabled, starting, canStartAt, onStart, liveTools }: ProcessFlowProps) {
  const model = flow.process_model.code
  const stages = flow.stages
  const renderNode = (item: ProjectFlow['stages'][number], index: number, className = '') => (
    <FlowNode
      key={item.stage.code}
      flow={flow}
      item={item}
      index={index}
      startDisabled={startDisabled}
      starting={starting}
      canStartAt={canStartAt}
      onStart={onStart}
      liveTools={liveTools}
      className={className}
    />
  )

  const modelDescription: Record<string, string> = {
    waterfall: '阶梯式推进：每一步只依据上一步的产物，评审打回沿回溯通道返回。',
    'v-model': '真正的 V 形：左臂定义与实现逐层下行，右臂验证逐层上行，横线即配对验证。',
    iterative: '本轮五个阶段线性交付，迭代评审产出下一轮的改进需求。',
    spiral: '围绕风险核心展开：每轮经过风险分析 → 设计 → 实现 → 验证 → 评估。',
    prototype: '原型收集反馈，反馈精化需求，编码只读精化后的需求。',
    scrum: 'Sprint 闭环：待办 → 计划 → 开发 → 评审 → 回顾，回到待办。',
  }

  const heading = (
    <div className="flow-model-heading">
      <span className="flow-model-kicker">{flow.process_model.name}</span>
      <span>{modelDescription[model] ?? '阶段节点、验证关系与回溯路径'}</span>
    </div>
  )

  const layout = MODEL_LAYOUTS[model]
  if (layout) {
    const statusByCode = new Map(stages.map((s) => [s.stage.code, s.status]))
    const isBusy = (code: string) => {
      const s = statusByCode.get(code)
      return s === 'generating' || s === 'collecting'
    }
    const edges = layout.edges
      .map((e) => {
        const a = layout.positions[e.from]
        const b = layout.positions[e.to]
        if (!a || !b) return null
        const trimmed = { ...e, from: trim(a, b), to: trim(b, a) }
        const { d, mid } = edgePath(trimmed.from, trimmed.to, e.bend ?? 0)
        return { ...e, a, b, d, mid, active: isBusy(e.from) || isBusy(e.to) }
      })
      .filter((e): e is NonNullable<typeof e> => Boolean(e))
    const placed = stages.filter((s) => layout.positions[s.stage.code])
    const overflow = stages.filter((s) => !layout.positions[s.stage.code])
    const hasPair = edges.some((e) => e.kind === 'pair')

    return (
      <div className="process-flow process-flow-canvas">
        {heading}
        <div className="flow-canvas-scroll">
          <div className="flow-canvas">
            <svg className="flow-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <marker id="edge-arrow-feedback" markerUnits="userSpaceOnUse" markerWidth="3.4" markerHeight="3.4" refX="2.7" refY="1.7" orient="auto">
                  <path d="M 0 0 L 3 1.7 L 0 3.4 z" fill="#f59e0b" />
                </marker>
              </defs>
              {layout.rings?.map((r) => (
                <ellipse
                  key={`${r.cx}-${r.rx}`}
                  className="flow-ring"
                  cx={r.cx}
                  cy={r.cy}
                  rx={r.rx}
                  ry={r.ry}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
              {edges.map((e) => (
                <path
                  key={`${e.from}->${e.to}`}
                  d={e.d}
                  className={[
                    'flow-edge',
                    `flow-edge-${e.kind}`,
                    e.active ? 'flow-edge-active' : '',
                  ].join(' ')}
                  markerEnd={e.kind === 'feedback' ? 'url(#edge-arrow-feedback)' : undefined}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </svg>
            {layout.hub && (
              <div className="flow-hub" style={{ left: `${layout.hub.x}%`, top: `${layout.hub.y}%` }}>
                <span>{layout.hub.kicker}</span>
                <b>{layout.hub.title}</b>
              </div>
            )}
            {edges
              .filter((e) => e.label)
              .map((e) => (
                <span
                  key={`label-${e.from}-${e.to}`}
                  className={`flow-edge-label flow-edge-label-${e.kind}${e.active ? ' is-active' : ''}`}
                  style={{ left: `${e.mid.x}%`, top: `${e.mid.y + (e.labelDy ?? 0)}%` }}
                >
                  {e.label}
                </span>
              ))}
            {placed.map((item) => {
              const p = layout.positions[item.stage.code]
              return (
                <div key={item.stage.code} className="flow-canvas-node" style={{ left: `${p.x}%`, top: `${p.y}%` }}>
                  {renderNode(item, stages.indexOf(item))}
                </div>
              )
            })}
          </div>
        </div>
        <div className="flow-legend">
          <span><i className="legend-dot legend-main" />阶段推进</span>
          {hasPair && <span><i className="legend-dot legend-test" />配对验证</span>}
          <span><i className="legend-dot legend-back" />回溯 / 反馈</span>
          {model === 'spiral' && <span><i className="legend-dot legend-risk" />风险核心</span>}
        </div>
        {overflow.length > 0 && (
          <div className="flow-generic-track">{overflow.map((item) => renderNode(item, stages.indexOf(item)))}</div>
        )}
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

function FlowNode({ item, index, startDisabled, starting, canStartAt, onStart, liveTools, className = '' }: FlowNodeProps) {
  const { stage, status, stage_run_id, agent_role_name, model, tool_usage, tool_call_count, parallel_peers, contract } = item
  const agent = getAgent(stage.code)
  const roleName = agent_role_name ?? agent.name
  const canStart = status === 'pending' && canStartAt(index)
  const canChat = !CODE_STAGES.has(stage.code)
  const retry = status === 'rejected' || status === 'verification_failed'
  // 运行中优先展示实时工具调用；运行结束后回落到已落库的统计。
  const live = stage_run_id != null ? liveTools[stage_run_id] : undefined
  const running = status === 'generating' || status === 'collecting'
  const hasLive = running && !!live && live.length > 0
  const usage = hasLive ? live! : tool_usage
  const total = hasLive ? live!.reduce((sum, tool) => sum + tool.count, 0) : tool_call_count
  const topTools = usage.slice(0, 3)
  const contractTitle = contract
    ? [
        contract.inputs && contract.inputs.length > 0 ? `输入契约：${contract.inputs.join('、')}` : contract.inputs && contract.inputs.length === 0 ? '输入契约：流程起点' : null,
        contract.pair_stage ? `配对验证：与「${contract.pair_stage_name ?? contract.pair_stage}」互为验证` : null,
        contract.note,
      ].filter(Boolean).join('\n')
    : undefined
  return (
    <div
      className={`flow-node ${flowStatusClass(status)} ${hasLive ? 'is-live' : ''} ${className}`}
      style={{ '--node-i': index } as CSSProperties}
      title={contractTitle || stage.description || stage.name}
    >
      <div className="flow-node-topline">
        <span className="flow-node-index">{String(index + 1).padStart(2, '0')}</span>
        <span className="flow-node-status">
          {running && <span className="live-dot" aria-hidden="true" />}
          {statusLabels[status] ?? status}
        </span>
      </div>
      <div className="flow-node-title">{stage.name}</div>
      <div className="flow-node-agent"><span className="flow-agent-icon">{agent.icon}</span><span>{roleName}</span><b>{agent.short}</b></div>
      {model && <div className="flow-node-model" title="执行模型">{model}</div>}
      {contract?.pair_stage && (
        <div className="flow-node-pair" title={`配对验证：与「${contract.pair_stage_name ?? contract.pair_stage}」互为验证关系`}>⇄ {contract.pair_stage_name ?? contract.pair_stage}</div>
      )}
      {topTools.length > 0 && (
        <div className={`flow-node-tools${hasLive ? ' is-live' : ''}`} title={`共 ${total} 次工具调用`}>
          {topTools.map((entry) => <span className="flow-tool-chip" key={entry.tool}>{entry.tool}<i>×{entry.count}</i></span>)}
          {usage.length > topTools.length && <span className="flow-tool-more">+{usage.length - topTools.length}</span>}
        </div>
      )}
      {parallel_peers.length > 0 && status !== 'pending' && (
        <div className="flow-node-parallel" title={`与该阶段并行执行：${parallel_peers.join('、')}`}><i className="parallel-pulse" aria-hidden="true" />并行通道 ×{parallel_peers.length + 1}</div>
      )}
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
  const [openCodePaths, setOpenCodePaths] = useState<string[]>([])
  const [codeDirty, setCodeDirty] = useState(false)
  const [codeDrafts, setCodeDrafts] = useState<Record<string, string>>({})
  const [codeDirtyPaths, setCodeDirtyPaths] = useState<Record<string, boolean>>({})
  const [codeSaving, setCodeSaving] = useState(false)
  const [codeOutput, setCodeOutput] = useState('')
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [gitDiff, setGitDiff] = useState('')
  const [gitLog, setGitLog] = useState<import('../lib/api').GitLogEntry[]>([])
  const [gitMessage, setGitMessage] = useState('')
  const [gitBusy, setGitBusy] = useState(false)
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null)
  const [mcpServers, setMcpServers] = useState<McpServer[]>([])
  const [mcpBusy, setMcpBusy] = useState<string | null>(null)
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
  // 运行中的工具调用流水，按 stage_run_id 归档，用于过程模型节点的实时展示。
  const [liveToolCalls, setLiveToolCalls] = useState<Record<number, ToolUsage[]>>({})
  const [savingAutoAdvance, setSavingAutoAdvance] = useState(false)
  // SSE 实时状态：已连接时不再轮询；message_delta 用于逐段渲染 agent 回复。
  const [liveConnected, setLiveConnected] = useState(false)
  const [streamingText, setStreamingText] = useState('')

  const loadingRef = useRef(false)
  const mountedRef = useRef(true)
  const reloadTimerRef = useRef<number | null>(null)
  // 对话区：自动滚动（仅在用户贴近底部时跟随）+ 输入框自适应高度。
  const chatScrollRef = useRef<HTMLDivElement | null>(null)
  const chatInputRef = useRef<HTMLTextAreaElement | null>(null)
  const chatAtBottomRef = useRef(true)

  useEffect(() => {
    const el = chatScrollRef.current
    if (!el || !chatAtBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [messages.length, streamingText])

  // 发送成功后程序化清空输入，同步把（自增高的）输入框收回单行高度。
  useEffect(() => {
    const el = chatInputRef.current
    if (el && !chatInput) el.style.height = 'auto'
  }, [chatInput])

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
        const [nextProject, nextFlow, nextArtifacts, nextEvents, nextStats, nextTrace, nextCodeTree, nextGitStatus] =
          await Promise.all([
            getProject(validProjectId),
            getProjectFlow(validProjectId),
            listProjectArtifacts(validProjectId),
            listActivityEvents(validProjectId),
            getProjectStats(validProjectId),
            getTraceability(validProjectId),
            getCodeTree(validProjectId),
            getGitStatus(validProjectId),
          ])
        if (!mountedRef.current) return
        setProject(nextProject)
        setFlow(nextFlow)
        setArtifacts(nextArtifacts)
        setActivityEvents(nextEvents)
        setStats(nextStats)
        setTraceability(nextTrace)
        setCodeTree(nextCodeTree)
        setGitStatus(nextGitStatus)
        if (nextGitStatus.is_repo) {
          void getGitLog(validProjectId).then((entries) => { if (mountedRef.current) setGitLog(entries) })
        }
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
    // 工具调用逐条到达：直接累加到对应阶段节点上，让过程模型实时可见。
    source.addEventListener('agent_tool', (event) => {
      const data = JSON.parse((event as MessageEvent).data) as {
        stage_run_id: number | null
        tool: string
      }
      if (!mountedRef.current || data.stage_run_id == null) return
      setLiveToolCalls((prev) => {
        const current = prev[data.stage_run_id as number] ?? []
        const hit = current.find((entry) => entry.tool === data.tool)
        const next = hit
          ? current.map((entry) =>
              entry.tool === data.tool ? { ...entry, count: entry.count + 1 } : entry,
            )
          : [...current, { tool: data.tool, count: 1 }]
        return { ...prev, [data.stage_run_id as number]: next }
      })
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
    if (validProjectId === null) return
    listProjectMcp(validProjectId)
      .then((list) => { if (mountedRef.current) setMcpServers(list) })
      .catch(() => { if (mountedRef.current) setMcpServers([]) })
  }, [validProjectId])

  useEffect(() => {
    if (validProjectId === null) return
    listProjectSkills(validProjectId)
      .then((list) => { if (mountedRef.current) setSkills(list) })
      .catch(() => { if (mountedRef.current) setSkills([]) })
  }, [validProjectId])

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
    if (validProjectId === null) return
    if (codeDirty && path !== selectedCodePath && !window.confirm('当前文件有未保存修改，切换文件会保留在当前编辑会话中，继续吗？')) return
    setSelectedCodePath(path)
    setOpenCodePaths((prev) => (prev.includes(path) ? prev : [...prev, path]))
    setError('')
    if (Object.prototype.hasOwnProperty.call(codeDrafts, path)) {
      setCodeContent(codeDrafts[path])
      setCodeDirty(codeDirtyPaths[path] === true)
      return
    }
    try {
      const content = await getCodeFile(validProjectId, path)
      setCodeContent(content)
      setCodeDrafts((prev) => ({ ...prev, [path]: content }))
      setCodeDirtyPaths((prev) => ({ ...prev, [path]: false }))
      setCodeDirty(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取代码失败')
    }
  }

  async function handleSaveCode() {
    if (validProjectId === null || !selectedCodePath || codeSaving) return
    setCodeSaving(true)
    setError('')
    try {
      await saveCodeFile(validProjectId, selectedCodePath, codeContent)
      setCodeDrafts((prev) => ({ ...prev, [selectedCodePath]: codeContent }))
      setCodeDirtyPaths((prev) => ({ ...prev, [selectedCodePath]: false }))
      setCodeDirty(false)
      const tree = await getCodeTree(validProjectId)
      setCodeTree(tree)
      setGitStatus(await getGitStatus(validProjectId))
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存代码失败')
    } finally {
      setCodeSaving(false)
    }
  }

  async function handleInitGit() {
    if (validProjectId === null || gitBusy) return
    setGitBusy(true)
    setError('')
    try {
      setGitStatus(await initGit(validProjectId))
      setGitLog(await getGitLog(validProjectId))
    } catch (err) {
      setError(err instanceof Error ? err.message : '初始化 Git 失败')
    } finally {
      setGitBusy(false)
    }
  }

  async function handleCommitGit() {
    if (validProjectId === null || gitBusy || !gitMessage.trim()) return
    setGitBusy(true)
    setError('')
    try {
      await commitGit(validProjectId, gitMessage)
      setGitMessage('')
      setGitStatus(await getGitStatus(validProjectId))
      setGitLog(await getGitLog(validProjectId))
      setGitDiff('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Git 提交失败')
    } finally {
      setGitBusy(false)
    }
  }

  async function handleViewDiff() {
    if (validProjectId === null) return
    setError('')
    try {
      setGitDiff(await getGitDiff(validProjectId))
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 Git diff 失败')
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
    if (!flow) return false
    const item = flow.stages[index]
    if (!item) return false
    return item.dependencies.every((dependency) =>
      flow.stages.some(
        ({ stage, status }) =>
          stage.code === dependency && (status === 'approved' || status === 'completed'),
      ),
    )
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
            <div><h2 className="text-sm font-bold text-slate-900">代码工作区</h2><p className="mt-1 text-[11px] text-slate-400">{gitStatus?.is_repo ? `${gitStatus.branch} · ${gitStatus.changed_files} 个文件变更` : '未检测到 Git 仓库'}</p></div>
            <div className="flex flex-wrap justify-end gap-2">
              {!gitStatus?.is_repo && <button onClick={() => void handleInitGit()} disabled={gitBusy} className="secondary-action px-3 py-1.5 text-xs font-semibold">{gitBusy ? '初始化中...' : '初始化 Git'}</button>}
              {gitStatus?.is_repo && <>
                <input value={gitMessage} onChange={(event) => setGitMessage(event.target.value)} placeholder="提交说明..." className="field-control w-36 px-2.5 py-1.5 text-xs" />
                <button onClick={() => void handleCommitGit()} disabled={gitBusy || !gitMessage.trim()} className="secondary-action px-3 py-1.5 text-xs font-semibold">提交</button>
              </>}
              <button
                onClick={() => void handleSaveCode()}
                disabled={!selectedCodePath || !codeDirty || codeSaving}
                className="secondary-action px-3 py-1.5 text-xs font-semibold"
              >
                {codeSaving ? '保存中...' : '保存文件'}
              </button>
              <button
                onClick={() => void handleViewDiff()}
                disabled={!gitStatus?.is_repo}
                className="secondary-action px-3 py-1.5 text-xs font-semibold"
              >
                查看 Diff
              </button>
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
              <div className="code-editor-pane col-span-2">
                {openCodePaths.length > 0 && (
                  <div className="code-tabs">
                    {openCodePaths.map((path) => (
                      <button key={path} onClick={() => void handleViewCode(path)} className={selectedCodePath === path ? 'active' : ''}>{path.split('/').pop()}</button>
                    ))}
                    <span className="ml-auto text-[10px] text-slate-400">{codeDirty ? '未保存' : '已保存'}</span>
                  </div>
                )}
                {selectedCodePath ? (
                  <textarea
                    value={codeContent}
                    onChange={(event) => {
                      const nextContent = event.target.value
                      setCodeContent(nextContent)
                      setCodeDrafts((prev) => ({ ...prev, [selectedCodePath]: nextContent }))
                      setCodeDirtyPaths((prev) => ({ ...prev, [selectedCodePath]: true }))
                      setCodeDirty(true)
                    }}
                    spellCheck={false}
                    className="code-editor-textarea"
                  />
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
          {gitDiff && (
            <pre className="git-diff-panel mt-4 max-h-80 shrink-0 overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-xs leading-6">
              {gitDiff}
            </pre>
          )}
          {gitLog.length > 0 && <div className="git-log-panel mt-4 shrink-0"><div className="git-log-title">RECENT COMMITS</div>{gitLog.map((entry) => <div key={`${entry.commit}-${entry.date}`} className="git-log-row"><code>{entry.commit}</code><span>{entry.subject}</span><time>{entry.date}</time></div>)}</div>}
          <div className="skills-panel mt-4 shrink-0">
            <div className="skills-panel-heading"><span>PROJECT SKILLS</span><b>{skills.length} loaded</b></div>
            {skills.length === 0 ? <p className="skills-empty">在项目的 .sdlc/skills、.opencode/skills 或 skills 目录放入 SKILL.md，即可加载项目规则。</p> : <div className="skills-list">{skills.map((skill) => <button key={skill.name} onClick={() => { if (validProjectId !== null) void getProjectSkill(validProjectId, skill.name).then(setSelectedSkill).catch(() => setError('读取 Skill 失败')) }} className={`skill-row ${selectedSkill?.name === skill.name ? 'active' : ''}`}><span className="skill-name">{skill.name}</span><span className="skill-description">{skill.description}</span><code>{skill.source}</code></button>)}</div>}
            {selectedSkill && <pre className="skill-content">{selectedSkill.content}</pre>}
          </div>
          <div className="mcp-panel mt-4 shrink-0">
            <div className="skills-panel-heading"><span>MCP SERVERS</span><b>{mcpServers.length} configured</b></div>
            {mcpServers.length === 0 ? <p className="skills-empty">在项目的 .sdlc/mcp.json、.opencode/mcp.json 或 mcp.json 中配置本地 MCP Server。</p> : <div className="mcp-list">{mcpServers.map((server) => <div key={server.name} className="mcp-row"><div className="mcp-copy"><b>{server.name}</b><small>{server.type} · {server.enabled ? 'enabled' : 'disabled'} · {server.tools.length} tools</small></div><button onClick={async () => { if (validProjectId === null) return; setMcpBusy(server.name); try { const updated = await discoverProjectMcp(validProjectId, server.name); setMcpServers((prev) => prev.map((item) => item.name === server.name ? updated : item)) } catch { setError('MCP 工具发现失败') } finally { setMcpBusy(null) } }} disabled={mcpBusy === server.name || !server.enabled} className="secondary-action px-3 py-1.5 text-[10px] font-semibold">{mcpBusy === server.name ? '发现中...' : '发现工具'}</button></div>)}</div>}
            {mcpServers.some((server) => server.tools.length > 0) && <div className="mcp-tools">{mcpServers.flatMap((server) => server.tools.map((tool) => <span key={`${server.name}:${tool.name}`} title={tool.description}>{server.name}/{tool.name}</span>))}</div>}
          </div>
        </div>
      )}

      {flow && tab === 'stages' && (
        <div className="process-flow-section">
          <ProcessFlow flow={flow} startDisabled={startDisabled} starting={starting} canStartAt={canStartAt} onStart={(stageCode, mode) => void handleStart(stageCode, mode)} liveTools={liveToolCalls} />
        </div>
      )}

      {collectingRunId && tab === 'chat' && (
        <section className="chat-panel workspace-conversation">
          <header className="chat-head">
            <span className="chat-head-avatar">✦</span>
            <div className="chat-head-copy">
              <h2>{collectingStage?.stage.name ?? ''} · 阶段对话</h2>
              <p>{chatSending || streamingText ? 'Agent 正在整理你的输入…' : 'Agent 基于当前项目上下文与你协作，确认后生成阶段产物'}</p>
            </div>
            <div className="chat-head-meta">
              <span className="chat-head-count">{messages.length} 条消息</span>
              <span className={`chat-live-pill${chatSending || streamingText ? ' is-busy' : ''}`}>
                <span className="status-dot" />
                {chatSending || streamingText ? '正在生成' : '在线协作'}
              </span>
            </div>
          </header>

          <div
            className="chat-scroll"
            ref={chatScrollRef}
            onScroll={() => {
              const el = chatScrollRef.current
              if (!el) return
              chatAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140
            }}
          >
            {messages.length === 0 && !streamingText ? (
              <div className="chat-empty-state">
                <span className="chat-empty-icon">✦</span>
                <h3>从这里开始协作</h3>
                <p>介绍你的目标、用户和核心问题，Agent 会将它们整理成可评审的阶段产物。</p>
                <div className="chat-suggestions">
                  {CHAT_SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => {
                        setChatInput(suggestion)
                        chatInputRef.current?.focus()
                      }}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="chat-thread">
                {messages.map((message) =>
                  message.role === 'user' ? (
                    <div key={message.id} className="chat-turn chat-turn-user">
                      <div className="chat-bubble-user">{message.content}</div>
                      <span className="chat-avatar chat-avatar-user">U</span>
                    </div>
                  ) : (
                    <div key={message.id} className="chat-turn chat-turn-agent">
                      <span className="chat-avatar">✦</span>
                      <div className="chat-turn-body">
                        <div className="chat-turn-meta">
                          <b>{message.agent_code || 'SDLC Agent'}</b>
                          <time>{formatClock(message.created_at)}</time>
                        </div>
                        <MarkdownText text={message.content} />
                      </div>
                    </div>
                  ),
                )}
                {(chatSending || streamingText) && (
                  <div className="chat-turn chat-turn-agent">
                    <span className="chat-avatar">✦</span>
                    <div className="chat-turn-body">
                      <div className="chat-turn-meta">
                        <b>SDLC Agent</b>
                        <span className="chat-typing" aria-label="正在生成"><i /><i /><i /></span>
                      </div>
                      {streamingText ? (
                        <MarkdownText text={streamingText} className="is-streaming" />
                      ) : (
                        <div className="chat-thinking">正在组织内容…</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <footer className="chat-dock">
            <form onSubmit={handleChatSubmit} className="chat-composer">
              <textarea
                ref={chatInputRef}
                value={chatInput}
                onChange={(event) => {
                  setChatInput(event.target.value)
                  const el = event.target
                  el.style.height = 'auto'
                  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault()
                    event.currentTarget.form?.requestSubmit()
                  }
                }}
                placeholder="回复 Agent，补充本阶段信息…"
                rows={1}
                className="chat-composer-input"
              />
              <div className="chat-composer-bar">
                <span className="chat-hint"><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</span>
                <button type="submit" disabled={chatSending || !chatInput.trim()} className="chat-send-button">
                  <span className="chat-send-icon">↑</span>
                  {chatSending ? '生成中' : '发送'}
                </button>
              </div>
            </form>
            <div className="chat-actions-row">
              <span className="chat-action-note">确认后将生成本阶段正式文档，并进入人工评审。</span>
              <button onClick={() => void handleConfirm()} disabled={confirming} className="chat-confirm-button">
                {confirming ? '正在生成阶段文档…' : '确认并生成阶段文档'} <span>→</span>
              </button>
            </div>
          </footer>
        </section>
      )}

      {awaitingRunId && (tab === 'chat' || tab === 'stages') && (
        <section className="review-card">
          <header className="review-head">
            <span className="review-flag">阶段评审</span>
            <div className="review-title">
              <h2>{awaitingStage?.stage.name ?? ''}</h2>
              <p>产物已生成，通过后进入下一阶段</p>
            </div>
            <span className="review-status">待人工确认</span>
          </header>

          {agentReviews.length > 0 && (
            <div className="review-agent">
              <div className="review-agent-head">
                <span className="review-agent-icon">✦</span>
                <b>评审 Agent 建议</b>
                <i>自动生成 · 仅供参考</i>
              </div>
              <div className="review-agent-body">
                {agentReviews.map((review) => <MarkdownText key={review.id} text={review.comment} />)}
              </div>
            </div>
          )}

          <textarea
            value={reviewComment}
            onChange={(event) => setReviewComment(event.target.value)}
            placeholder="评审意见（可选）：写清楚通过或打回的理由"
            className="review-input"
          />
          <div className="review-actions">
            <button
              onClick={() => void handleReview('approved')}
              disabled={reviewingId === awaitingRunId}
              className="review-approve"
            >
              {reviewingId === awaitingRunId ? '处理中…' : '通过并继续'}
            </button>
            <button
              onClick={() => void handleReview('rejected')}
              disabled={reviewingId === awaitingRunId}
              className="review-reject"
            >
              打回修改
            </button>
          </div>
          <p className="review-note">
            {autoAdvance
              ? '已开启统筹自动推进：通过后将自动启动下一阶段。'
              : '通过后可在阶段卡片上点击「自动生成」启动下一阶段；打回后可「重新生成」。'}
          </p>
        </section>
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
