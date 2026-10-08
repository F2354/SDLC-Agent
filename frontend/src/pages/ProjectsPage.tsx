import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'

import {
  browseFilesystem,
  createProject,
  listProcessModels,
  listProjects,
  type FsBrowse,
  type ProcessModel,
  type Project,
} from '../lib/api'

const CHAT_SUGGESTIONS = [
  '做一个在线考试系统，支持出题、组卷、判分',
  '做一个待办清单应用，支持分类、提醒、统计',
  '做一个博客系统，支持文章、评论、标签',
]

function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export default function ProjectsPage() {
  const [processModels, setProcessModels] = useState<ProcessModel[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [modelCode, setModelCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [folder, setFolder] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [browse, setBrowse] = useState<FsBrowse | null>(null)
  const [pickerLoading, setPickerLoading] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  async function load() {
    setError('')
    try {
      const [models, projectList] = await Promise.all([listProcessModels(), listProjects()])
      setProcessModels(models)
      setModelCode((prev) => prev || models[0]?.code || '')
      setProjects(projectList)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    }
  }

  useEffect(() => { void load() }, [])
  useEffect(() => { if (searchParams.get('new') === '1') setCreating(true) }, [searchParams])

  async function openPicker() {
    setPickerOpen(true)
    setPickerLoading(true)
    try { setBrowse(await browseFilesystem(browse?.path ?? '')) }
    catch (err) { setError(err instanceof Error ? err.message : '打开文件夹选择器失败'); setPickerOpen(false) }
    finally { setPickerLoading(false) }
  }

  async function enter(entryPath: string) {
    setPickerLoading(true)
    try { setBrowse(await browseFilesystem(entryPath)) }
    catch (err) { setError(err instanceof Error ? err.message : '无法打开该文件夹') }
    finally { setPickerLoading(false) }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    if (!folder) { setError('请先选择项目文件夹'); return }
    if (!modelCode) { setError('开发模型尚未加载完成，请稍后重试'); return }
    const finalName = name.trim() || description.trim().split('\n')[0].slice(0, 24) || '未命名项目'
    setError('')
    setSubmitting(true)
    try {
      const project = await createProject({ name: finalName, description, process_model_code: modelCode, folder })
      navigate(`/projects/${project.id}`)
    } catch (err) { setError(err instanceof Error ? err.message : '创建失败') }
    finally { setSubmitting(false) }
  }

  // 完整表单（从侧栏「新建项目」进入），保留全部选项。
  if (creating) {
    return (
      <div className="page-container">
        <div className="mb-7 flex items-end justify-between gap-6">
          <div>
            <div className="page-eyebrow">New workspace</div>
            <h1 className="page-title mt-2">创建一个新项目</h1>
            <p className="page-subtitle mt-3">选择过程模型和本地工作目录，Agent 将从需求访谈开始协同推进。</p>
          </div>
          <button type="button" onClick={() => { setCreating(false); setError(''); navigate('/projects', { replace: true }) }} className="secondary-action px-4 py-2 text-xs font-semibold">返回</button>
        </div>

        <form onSubmit={handleCreate} className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <section className="surface-section p-7">
            <div className="flex items-center gap-3 border-b soft-divider pb-5">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-lg text-slate-500">✦</span>
              <div><h2 className="text-base font-bold text-slate-900">项目基本信息</h2><p className="mt-0.5 text-xs text-slate-400">先定义项目边界，后续阶段会以此为上下文。</p></div>
            </div>
            <div className="mt-6 grid gap-5">
              <label className="block"><span className="field-label">项目名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：在线考试系统" className="field-control mt-2 px-3.5 py-3" /></label>
              <label className="block"><span className="field-label">项目描述</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述项目目标、用户和需要解决的核心问题" className="field-control mt-2 min-h-32 resize-y px-3.5 py-3 leading-6" /></label>
              <div><span className="field-label">项目文件夹</span><div className="mt-2 flex gap-2"><input value={folder ?? ''} readOnly placeholder="选择一个本地文件夹作为工作区" className="field-control min-w-0 flex-1 px-3.5 py-3 text-slate-600" /><button type="button" onClick={() => void openPicker()} className="secondary-action shrink-0 px-4 py-2.5 text-xs font-semibold">浏览文件夹</button></div><p className="mt-2 text-[11px] text-slate-400">代码和阶段文档会写入该目录，请选择有写入权限的位置。</p></div>
            </div>
            {error && <div className="mt-5 rounded-lg border border-red-200 bg-red-50 px-3.5 py-3 text-xs text-red-600">{error}</div>}
            <div className="mt-7 flex gap-3"><button className="primary-action px-6 py-3 text-sm font-semibold" disabled={!folder || !modelCode || submitting}>{submitting ? '创建中...' : '创建项目并开始'}</button><button type="button" onClick={() => { setCreating(false); setError(''); navigate('/projects', { replace: true }) }} className="secondary-action px-6 py-3 text-sm font-semibold">取消</button></div>
          </section>

          <aside className="space-y-4">
            <section className="surface-section p-6"><div className="page-eyebrow">Process model</div><h2 className="mt-2 text-base font-bold text-slate-900">选择开发过程</h2><p className="mt-2 text-xs leading-5 text-slate-500">不同模型会影响阶段顺序和 Agent 的协作方式。</p><div className="mt-5 space-y-2.5">{processModels.map((model) => <label key={model.code} className={`process-model-option flex cursor-pointer items-start gap-3 p-3.5 ${modelCode === model.code ? 'selected' : ''}`}><input type="radio" name="process-model" value={model.code} checked={modelCode === model.code} onChange={() => setModelCode(model.code)} className="mt-1 accent-indigo-600" /><span><span className="block text-xs font-bold text-slate-800">{model.name}</span><span className="mt-1 block text-[11px] leading-4 text-slate-500">{model.description || '配置化的软件开发流程'}</span><span className="mt-2 inline-flex rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">{model.stages?.length ?? 0} 个阶段</span></span></label>)}</div></section>
            <section className="rounded-lg border border-amber-200 bg-amber-50/70 p-5"><div className="flex gap-3"><span className="text-lg">✧</span><div><h3 className="text-xs font-bold text-amber-900">建议</h3><p className="mt-1 text-[11px] leading-5 text-amber-800/80">第一次使用可以选择瀑布模型，流程清晰，适合完整体验需求到测试的闭环。</p></div></div></section>
          </aside>
        </form>

        {pickerOpen && browse && <FolderPicker browse={browse} loading={pickerLoading} onEnter={enter} onUp={() => browse.parent && void enter(browse.parent)} onClose={() => setPickerOpen(false)} onSelect={() => { if (browse.path) setFolder(browse.path); setPickerOpen(false) }} />}
      </div>
    )
  }

  // 默认：任务输入 + 项目列表（DeepSeek / Codex 式入口）。
  return (
    <div className="page-container task-home">
      <div className="task-hero">
        <div className="page-eyebrow">SDLC Agent</div>
        <h1 className="page-title mt-3">要做什么？</h1>
        <p className="page-subtitle mt-3">描述一个想法或需求，Agent 团队会按所选过程模型从需求访谈一路协同到代码验证。</p>
      </div>

      <form onSubmit={handleCreate} className="task-composer">
        <textarea
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="例如：做一个在线考试系统，支持出题、组卷、判分…"
        />
        <div className="task-composer-bar">
          <button type="button" className="task-folder" onClick={() => void openPicker()} title={folder ?? '选择项目文件夹'}>
            <span aria-hidden="true">📁</span>
            <span>{folder ?? '选择项目文件夹'}</span>
          </button>
          <select value={modelCode} onChange={(event) => setModelCode(event.target.value)} title="过程模型">
            {processModels.map((model) => <option key={model.code} value={model.code}>{model.name}</option>)}
          </select>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="项目名称（可选）" />
          <button type="submit" className="task-start" disabled={!folder || !modelCode || submitting || !description.trim()}>
            {submitting ? '创建中…' : '开始 →'}
          </button>
        </div>
        {error && <div className="border-t border-red-200 bg-red-50 px-4 py-3 text-xs text-red-600">{error}</div>}
      </form>

      {description.trim() === '' && (
        <div className="chat-suggestions mt-4" style={{ justifyContent: 'flex-start' }}>
          {CHAT_SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => setDescription(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <div className="task-list-head">最近项目</div>
      <div className="task-list">
        {projects.length === 0 ? (
          <div className="task-empty">还没有项目。从上方描述一个想法开始。</div>
        ) : (
          projects.map((project) => (
            <Link key={project.id} to={`/projects/${project.id}`} className="task-row">
              <span className="task-row-icon">⌁</span>
              <span className="task-row-copy">
                <b>{project.name}</b>
                <small>{project.process_model?.name || project.description || '本地项目'}</small>
              </span>
              <span className="task-row-meta">{formatDate(project.created_at)}</span>
            </Link>
          ))
        )}
      </div>

      {pickerOpen && browse && <FolderPicker browse={browse} loading={pickerLoading} onEnter={enter} onUp={() => browse.parent && void enter(browse.parent)} onClose={() => setPickerOpen(false)} onSelect={() => { if (browse.path) setFolder(browse.path); setPickerOpen(false) }} />}
    </div>
  )
}

function FolderPicker({ browse, loading, onEnter, onUp, onClose, onSelect }: { browse: FsBrowse; loading: boolean; onEnter: (path: string) => void; onUp: () => void; onClose: () => void; onSelect: () => void }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm"><div className="modal-surface flex max-h-[min(680px,92vh)] w-[min(620px,94vw)] flex-col overflow-hidden p-6"><div className="flex items-start justify-between"><div><div className="page-eyebrow">Workspace folder</div><h3 className="mt-1 text-lg font-bold text-slate-900">选择项目文件夹</h3></div><button type="button" onClick={onClose} className="secondary-action flex h-8 w-8 items-center justify-center rounded-lg p-0 text-lg">×</button></div><div className="mt-4 break-all rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-500">{browse.path || '此电脑'}</div><div className="mt-3 min-h-40 flex-1 overflow-y-auto rounded-lg border border-slate-200 bg-white">{loading ? <div className="px-4 py-12 text-center text-xs text-slate-400">正在读取文件夹...</div> : browse.entries.length === 0 ? <div className="px-4 py-12 text-center text-xs text-slate-400">没有可进入的子文件夹</div> : browse.entries.map((entry) => <button key={entry.path} onClick={() => onEnter(entry.path)} className="flex w-full items-center gap-3 border-b border-slate-100 px-4 py-3 text-left text-sm text-slate-700 last:border-0 hover:bg-slate-50"><span className="text-amber-400">▰</span><span className="truncate">{entry.name}</span><span className="ml-auto text-slate-300">›</span></button>)}</div><div className="mt-4 flex items-center justify-between"><button type="button" onClick={onUp} disabled={!browse.parent} className="secondary-action px-4 py-2 text-xs font-semibold disabled:opacity-40">← 上级</button><div className="flex gap-2"><button type="button" onClick={onClose} className="secondary-action px-4 py-2 text-xs font-semibold">取消</button><button type="button" onClick={onSelect} disabled={!browse.path} className="primary-action px-4 py-2 text-xs font-semibold disabled:opacity-40">选择此文件夹</button></div></div></div></div> }
