import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  browseFilesystem,
  createProject,
  listProcessModels,
  type FsBrowse,
  type ProcessModel,
} from '../lib/api'

export default function ProjectsPage() {
  const [processModels, setProcessModels] = useState<ProcessModel[]>([])
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
      const models = await listProcessModels()
      setProcessModels(models)
      setModelCode((prev) => prev || models[0]?.code || '')
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载过程模型失败')
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
    setError('')
    setSubmitting(true)
    try {
      const project = await createProject({ name, description, process_model_code: modelCode, folder })
      navigate(`/projects/${project.id}`)
    } catch (err) { setError(err instanceof Error ? err.message : '创建失败') }
    finally { setSubmitting(false) }
  }

  if (creating) {
    return (
      <div className="page-container">
        <div className="mb-7 flex items-end justify-between gap-6">
          <div>
            <div className="page-eyebrow">New workspace</div>
            <h1 className="page-title mt-2">创建一个新项目</h1>
            <p className="page-subtitle mt-3">选择过程模型和本地工作目录，Agent 将从需求访谈开始协同推进。</p>
          </div>
          <button type="button" onClick={() => { setCreating(false); setError(''); navigate('/projects', { replace: true }) }} className="secondary-action px-4 py-2 text-xs font-semibold">返回项目列表</button>
        </div>

        <form onSubmit={handleCreate} className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <section className="surface-section section-indigo p-7">
            <div className="flex items-center gap-3 border-b soft-divider pb-5">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-lg text-indigo-600">✦</span>
              <div><h2 className="text-base font-bold text-slate-900">项目基本信息</h2><p className="mt-0.5 text-xs text-slate-400">先定义项目边界，后续阶段会以此为上下文。</p></div>
            </div>
            <div className="mt-6 grid gap-5">
              <label className="block"><span className="field-label">项目名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：在线考试系统" className="field-control mt-2 px-3.5 py-3" required /></label>
              <label className="block"><span className="field-label">项目描述</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述项目目标、用户和需要解决的核心问题" className="field-control mt-2 min-h-32 resize-y px-3.5 py-3 leading-6" /></label>
              <div><span className="field-label">项目文件夹</span><div className="mt-2 flex gap-2"><input value={folder ?? ''} readOnly placeholder="选择一个本地文件夹作为工作区" className="field-control min-w-0 flex-1 px-3.5 py-3 text-slate-600" /><button type="button" onClick={() => void openPicker()} className="secondary-action shrink-0 px-4 py-2.5 text-xs font-semibold">浏览文件夹</button></div><p className="mt-2 text-[11px] text-slate-400">代码和阶段文档会写入该目录，请选择有写入权限的位置。</p></div>
            </div>
            {error && <div className="mt-5 rounded-xl border border-red-100 bg-red-50 px-3.5 py-3 text-xs text-red-600">{error}</div>}
            <div className="mt-7 flex gap-3"><button className="primary-action px-6 py-3 text-sm font-semibold" disabled={!folder || !modelCode || submitting}>{submitting ? '创建中...' : '创建项目并开始'}</button><button type="button" onClick={() => { setCreating(false); setError(''); navigate('/projects', { replace: true }) }} className="secondary-action px-6 py-3 text-sm font-semibold">取消</button></div>
          </section>

          <aside className="space-y-4">
            <section className="surface-section section-slate p-6"><div className="page-eyebrow">Process model</div><h2 className="mt-2 text-base font-bold text-slate-900">选择开发过程</h2><p className="mt-2 text-xs leading-5 text-slate-500">不同模型会影响阶段顺序和 Agent 的协作方式。</p><div className="mt-5 space-y-2.5">{processModels.map((model) => <label key={model.code} className={`process-model-option flex cursor-pointer items-start gap-3 p-3.5 transition-all ${modelCode === model.code ? 'selected' : ''}`}><input type="radio" name="process-model" value={model.code} checked={modelCode === model.code} onChange={() => setModelCode(model.code)} className="mt-1 accent-indigo-600" /><span><span className="block text-xs font-bold text-slate-800">{model.name}</span><span className="mt-1 block text-[11px] leading-4 text-slate-500">{model.description || '配置化的软件开发流程'}</span><span className="mt-2 inline-flex rounded-full bg-white/80 px-2 py-1 text-[10px] font-semibold text-indigo-600">{model.stages?.length ?? 0} 个阶段</span></span></label>)}</div></section>
            <section className="rounded-2xl border border-amber-100 bg-amber-50/70 p-5"><div className="flex gap-3"><span className="text-lg">✧</span><div><h3 className="text-xs font-bold text-amber-900">建议</h3><p className="mt-1 text-[11px] leading-5 text-amber-800/80">第一次使用可以选择瀑布模型，流程清晰，适合完整体验需求到测试的闭环。</p></div></div></section>
          </aside>
        </form>

        {pickerOpen && browse && <FolderPicker browse={browse} loading={pickerLoading} onEnter={enter} onUp={() => browse.parent && void enter(browse.parent)} onClose={() => setPickerOpen(false)} onSelect={() => { if (browse.path) setFolder(browse.path); setPickerOpen(false) }} />}
      </div>
    )
  }

  return (
    <div className="page-container">
      <section className="hero-panel p-8 lg:p-11">
        <div className="relative z-10 max-w-2xl">
          <div className="page-eyebrow">Software lifecycle studio</div>
          <h1 className="page-title mt-3">让每一个想法，<br /><span className="text-indigo-600">变成可交付的软件。</span></h1>
          <p className="page-subtitle mt-5">从需求访谈、架构设计到代码验证，多个专业 Agent 在同一条生命周期流水线上协作。</p>
          <button onClick={() => setCreating(true)} className="primary-action mt-7 px-6 py-3 text-sm font-semibold">开始一个新项目 <span className="ml-2">→</span></button>
        </div>
        <div className="relative z-10 mt-10 grid max-w-3xl grid-cols-3 gap-3 border-t border-indigo-100/70 pt-5 sm:gap-8"><Metric label="智能协作阶段" value="6+" /><Metric label="支持开发模型" value="6" /><Metric label="持续交付闭环" value="1" /></div>
      </section>
      <div className="mt-8 grid gap-4 md:grid-cols-3"><Feature icon="01" title="需求先行" text="通过对话把模糊想法整理成可确认、可追溯的需求。" /><Feature icon="02" title="阶段推进" text="每个阶段都有产物、评审和明确的下一步。" /><Feature icon="03" title="真实验证" text="编码阶段直接落盘并运行验证，让输出不止停留在文档。" /></div>
      {error && <div className="mt-5 rounded-xl border border-red-100 bg-red-50 px-3.5 py-3 text-xs text-red-600">{error}</div>}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) { return <div><div className="text-2xl font-bold tracking-tight text-slate-900">{value}</div><div className="mt-1 text-[11px] font-medium text-slate-500">{label}</div></div> }
function Feature({ icon, title, text }: { icon: string; title: string; text: string }) { return <div className="surface-section section-slate p-5"><span className="text-xs font-bold text-indigo-500">{icon}</span><h3 className="mt-3 text-sm font-bold text-slate-900">{title}</h3><p className="mt-2 text-xs leading-5 text-slate-500">{text}</p></div> }
function FolderPicker({ browse, loading, onEnter, onUp, onClose, onSelect }: { browse: FsBrowse; loading: boolean; onEnter: (path: string) => void; onUp: () => void; onClose: () => void; onSelect: () => void }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm"><div className="modal-surface flex max-h-[min(680px,92vh)] w-[min(620px,94vw)] flex-col overflow-hidden p-6"><div className="flex items-start justify-between"><div><div className="page-eyebrow">Workspace folder</div><h3 className="mt-1 text-lg font-bold text-slate-900">选择项目文件夹</h3></div><button type="button" onClick={onClose} className="secondary-action flex h-8 w-8 items-center justify-center rounded-lg p-0 text-lg">×</button></div><div className="mt-4 break-all rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-500">{browse.path || '此电脑'}</div><div className="mt-3 min-h-40 flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white">{loading ? <div className="px-4 py-12 text-center text-xs text-slate-400">正在读取文件夹...</div> : browse.entries.length === 0 ? <div className="px-4 py-12 text-center text-xs text-slate-400">没有可进入的子文件夹</div> : browse.entries.map((entry) => <button key={entry.path} onClick={() => onEnter(entry.path)} className="flex w-full items-center gap-3 border-b border-slate-100 px-4 py-3 text-left text-sm text-slate-700 last:border-0 hover:bg-indigo-50/60"><span className="text-amber-400">▰</span><span className="truncate">{entry.name}</span><span className="ml-auto text-slate-300">›</span></button>)}</div><div className="mt-4 flex items-center justify-between"><button type="button" onClick={onUp} disabled={!browse.parent} className="secondary-action px-4 py-2 text-xs font-semibold disabled:opacity-40">← 上级</button><div className="flex gap-2"><button type="button" onClick={onClose} className="secondary-action px-4 py-2 text-xs font-semibold">取消</button><button type="button" onClick={onSelect} disabled={!browse.path} className="primary-action px-4 py-2 text-xs font-semibold disabled:opacity-40">选择此文件夹</button></div></div></div></div> }
