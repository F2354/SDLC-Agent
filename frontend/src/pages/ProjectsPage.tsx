import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  createProject,
  listProcessModels,
  listProjects,
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

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      const project = await createProject({
        name,
        description,
        process_model_code: modelCode,
      })
      navigate(`/projects/${project.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">项目列表</h1>
          <p className="text-sm text-slate-500">创建并管理软件生命周期项目</p>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white"
        >
          新建项目
        </button>
      </div>

      {creating && (
        <form
          onSubmit={handleCreate}
          className="mt-6 max-w-xl rounded-lg border border-slate-200 bg-white p-5"
        >
          <h2 className="font-medium">新建项目</h2>
          <div className="mt-4 space-y-4">
            <label className="block text-sm">
              项目名称
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                required
              />
            </label>
            <label className="block text-sm">
              项目描述
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="mt-1 min-h-20 w-full rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="block text-sm">
              过程模型
              <select
                value={modelCode}
                onChange={(event) => setModelCode(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
              >
                {processModels.map((model) => (
                  <option key={model.code} value={model.code}>
                    {model.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-5 flex gap-2">
            <button className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white">
              创建
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-600"
            >
              取消
            </button>
          </div>
        </form>
      )}

      {error && <div className="mt-4 text-sm text-red-600">{error}</div>}

      <div className="mt-6 space-y-3">
        {loading && <div className="text-sm text-slate-500">加载中...</div>}
        {!loading && projects.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
            暂无项目，点击右上角创建第一个项目。
          </div>
        )}
        {projects.map((project) => (
          <button
            key={project.id}
            onClick={() => navigate(`/projects/${project.id}`)}
            className="block w-full rounded-lg border border-slate-200 bg-white p-5 text-left hover:border-slate-400"
          >
            <div className="flex items-center justify-between">
              <h2 className="font-medium">{project.name}</h2>
              <span className="text-xs text-slate-400">
                {project.process_model?.name ?? '未设置过程模型'}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              {project.description || '暂无项目描述'}
            </p>
          </button>
        ))}
      </div>
    </div>
  )
}
