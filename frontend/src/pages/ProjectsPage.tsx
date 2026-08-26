import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  browseFilesystem,
  createProject,
  listProcessModels,
  listProjects,
  type FsBrowse,
  type ProcessModel,
  type Project,
} from '../lib/api'

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [processModels, setProcessModels] = useState<ProcessModel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [modelCode, setModelCode] = useState('waterfall')
  const [folder, setFolder] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [browse, setBrowse] = useState<FsBrowse | null>(null)
  const [pickerLoading, setPickerLoading] = useState(false)
  const navigate = useNavigate()

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [projectList, models] = await Promise.all([listProjects(), listProcessModels()])
      setProjects(projectList)
      setProcessModels(models)
      if (models.length > 0) {
        setModelCode(models[0].code)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function openPicker() {
    setPickerOpen(true)
    setPickerLoading(true)
    try {
      setBrowse(await browseFilesystem(browse?.path ?? ''))
    } catch (err) {
      setError(err instanceof Error ? err.message : '打开文件夹选择器失败')
      setPickerOpen(false)
    } finally {
      setPickerLoading(false)
    }
  }

  async function enter(entryPath: string) {
    setPickerLoading(true)
    try {
      setBrowse(await browseFilesystem(entryPath))
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法打开该文件夹')
    } finally {
      setPickerLoading(false)
    }
  }

  async function goUp() {
    if (!browse?.parent) return
    await enter(browse.parent)
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (!folder) {
      setError('请先选择项目文件夹')
      return
    }
    setError('')
    try {
      const project = await createProject({
        name,
        description,
        process_model_code: modelCode,
        folder,
      })
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    }
  }

  return (
    <div className="grid h-full grid-cols-1 gap-6 lg:grid-cols-[300px_1fr]">
      <aside className="flex min-h-0 flex-col rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold">我的项目</h2>
          <p className="mt-0.5 text-xs text-slate-400">{projects.length} 个项目</p>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-3">
          {loading && <div className="px-2 py-6 text-center text-xs text-slate-400">加载中...</div>}
          {!loading && projects.length === 0 && (
            <div className="px-2 py-8 text-center text-xs leading-5 text-slate-400">
              还没有项目
              <br />
              从右侧创建第一个项目
            </div>
          )}
          <div className="space-y-2">
            {projects.map((project) => (
              <button
                key={project.id}
                onClick={() => navigate(`/projects/${project.id}`)}
                className="block w-full rounded-md border border-transparent px-3 py-2.5 text-left hover:border-slate-200 hover:bg-slate-50"
              >
                <div className="truncate text-sm font-medium text-slate-800">{project.name}</div>
                <div className="mt-0.5 truncate text-xs text-slate-400">
                  {project.process_model?.name ?? '未设置过程模型'}
                </div>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <section className="flex min-h-0 flex-col rounded-lg border border-slate-200 bg-white">
        {creating ? (
          <form onSubmit={handleCreate} className="flex min-h-0 flex-1 flex-col overflow-auto p-8">
            <h1 className="text-xl font-semibold">创建新项目</h1>
            <p className="mt-1 text-sm text-slate-500">
              选择开发模型和本地文件夹，Agent 将按阶段推进并生成文档与可运行代码。
            </p>
            <div className="mt-8 grid max-w-2xl gap-5">
              <label className="block text-sm">
                <span className="font-medium text-slate-700">项目名称</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="例如：在线考试系统"
                  className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2.5"
                  required
                />
              </label>
              <label className="block text-sm">
                <span className="font-medium text-slate-700">项目描述</span>
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="简单描述项目目标，需求访谈时 Agent 会深入展开"
                  className="mt-1.5 min-h-24 w-full rounded-md border border-slate-300 px-3 py-2.5"
                />
              </label>
              <label className="block text-sm">
                <span className="font-medium text-slate-700">开发模型</span>
                <select
                  value={modelCode}
                  onChange={(event) => setModelCode(event.target.value)}
                  className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2.5"
                >
                  {processModels.map((model) => (
                    <option key={model.code} value={model.code}>
                      {model.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="text-sm">
                <span className="font-medium text-slate-700">项目文件夹</span>
                <div className="mt-1.5 flex gap-2">
                  <input
                    value={folder ?? ''}
                    readOnly
                    placeholder="尚未选择，点击右侧按钮选择"
                    className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2.5 text-slate-600"
                  />
                  <button
                    type="button"
                    onClick={() => void openPicker()}
                    className="shrink-0 rounded-md border border-slate-300 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-100"
                  >
                    浏览
                  </button>
                </div>
              </div>
            </div>
            {error && <div className="mt-5 text-sm text-red-600">{error}</div>}
            <div className="mt-8 flex gap-3">
              <button
                className="rounded-md bg-slate-900 px-6 py-2.5 text-sm text-white disabled:opacity-50"
                disabled={!folder}
              >
                创建项目
              </button>
              <button
                type="button"
                onClick={() => {
                  setCreating(false)
                  setError('')
                }}
                className="rounded-md border border-slate-300 px-6 py-2.5 text-sm text-slate-600"
              >
                取消
              </button>
            </div>
          </form>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center p-10 text-center">
            <h1 className="text-2xl font-semibold">开始一个新项目</h1>
            <p className="mt-3 max-w-md text-sm leading-6 text-slate-500">
              从需求访谈开始，Agent 按阶段推进开发模型，输出文档并生成可运行代码。
            </p>
            <button
              onClick={() => setCreating(true)}
              className="mt-8 rounded-md bg-slate-900 px-8 py-3 text-sm text-white"
            >
              快速创建项目
            </button>
            {error && <div className="mt-5 text-sm text-red-600">{error}</div>}
          </div>
        )}
      </section>

      {pickerOpen && browse && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[560px] max-w-[92vw] rounded-lg bg-white p-5 shadow-xl">
            <h3 className="font-medium">选择项目文件夹</h3>
            <div className="mt-2 break-all rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
              {browse.path || '此电脑'}
            </div>
            <div className="mt-3 max-h-72 min-h-40 overflow-auto rounded-md border border-slate-200">
              {pickerLoading && (
                <div className="px-4 py-8 text-center text-xs text-slate-400">加载中...</div>
              )}
              {!pickerLoading && browse.entries.length === 0 && (
                <div className="px-4 py-8 text-center text-xs text-slate-400">
                  没有可进入的子文件夹
                </div>
              )}
              {browse.entries.map((entry) => (
                <button
                  key={entry.path}
                  onClick={() => void enter(entry.path)}
                  className="block w-full truncate px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50"
                >
                  {entry.name}
                </button>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={() => void goUp()}
                disabled={!browse.parent}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-600 disabled:opacity-40"
              >
                上级
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setPickerOpen(false)}
                  className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-600"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (browse.path) {
                      setFolder(browse.path)
                    }
                    setPickerOpen(false)
                  }}
                  disabled={!browse.path}
                  className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40"
                >
                  选择此文件夹
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
