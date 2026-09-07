import { useEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { listProjects, listProviders, type Project, type Provider } from '../lib/api'

const workspaceSections = [
  { key: 'chat', label: '对话' },
  { key: 'stages', label: '阶段流程' },
  { key: 'artifacts', label: '文档产物' },
  { key: 'code', label: '生成代码' },
  { key: 'logs', label: '活动日志' },
]

const menus = [
  {
    key: 'file',
    label: '文件',
    items: [
      { label: '新建项目', action: 'new-project' },
      { label: '模型服务', action: 'providers' },
    ],
  },
  {
    key: 'view',
    label: '视图',
    items: [{ label: '折叠/展开项目区', action: 'toggle-projects' }],
  },
  {
    key: 'help',
    label: '帮助',
    items: [{ label: '关于', action: 'about' }],
  },
]

export default function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [provider, setProvider] = useState<Provider | null>(null)
  const [projectsOpen, setProjectsOpen] = useState(true)
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [loadError, setLoadError] = useState('')
  const menuRef = useRef<HTMLDivElement>(null)

  const projectMatch = location.pathname.match(/^\/projects\/(\d+)/)
  const activeProjectId = projectMatch ? Number(projectMatch[1]) : null
  const activeTab = new URLSearchParams(location.search).get('tab') ?? 'chat'

  useEffect(() => {
    // 竞态保护：组件卸载或路由已切换时丢弃过期响应。
    let stale = false
    Promise.all([
      listProjects().then((list) => {
        if (!stale) setProjects(list)
      }),
      listProviders().then((list) => {
        if (!stale) setProvider(list[0] ?? null)
      }),
    ])
      .then(() => {
        if (!stale) setLoadError('')
      })
      .catch((err) => {
        if (stale) return
        setLoadError(err instanceof Error ? err.message : '加载失败，请检查后端服务是否已启动')
      })
    return () => {
      stale = true
    }
  }, [location.pathname])

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpenMenu(null)
      }
    }
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpenMenu(null)
        setAboutOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKeydown)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKeydown)
    }
  }, [])

  function handleMenuAction(action: string) {
    setOpenMenu(null)
    if (action === 'new-project') {
      navigate('/projects?new=1')
    } else if (action === 'providers') {
      navigate('/providers')
    } else if (action === 'toggle-projects') {
      setProjectsOpen((value) => !value)
    } else if (action === 'about') {
      setAboutOpen(true)
    }
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50 text-slate-900">
      <header
        ref={menuRef}
        className="relative z-40 flex h-10 shrink-0 items-center border-b border-slate-200 bg-white px-3"
      >
        <span className="mr-3 text-sm font-semibold">SDLC Agent</span>
        {menus.map((menu) => (
          <div key={menu.key} className="relative">
            <button
              onClick={() => setOpenMenu(openMenu === menu.key ? null : menu.key)}
              className={`rounded px-3 py-1 text-sm ${
                openMenu === menu.key ? 'bg-slate-100' : 'text-slate-700 hover:bg-slate-100'
              }`}
            >
              {menu.label}
            </button>
            {openMenu === menu.key && (
              <div className="absolute left-0 top-8 w-44 rounded-md border border-slate-200 bg-white py-1 shadow-lg">
                {menu.items.map((item) => (
                  <button
                    key={item.action}
                    onClick={() => handleMenuAction(item.action)}
                    className="block w-full px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-100"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
          <div className="px-3 pt-3">
            <button
              onClick={() => navigate('/projects?new=1')}
              className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-700"
            >
              + 新项目
            </button>
          </div>

          <button
            onClick={() => setProjectsOpen((value) => !value)}
            className="mt-4 flex items-center justify-between px-4 text-xs font-medium text-slate-500 hover:text-slate-700"
          >
            项目
            <span className="text-slate-400">{projectsOpen ? '▾' : '▸'}</span>
          </button>
          {loadError && (
            <div className="mx-4 mt-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] leading-4 text-red-600">
              {loadError}
            </div>
          )}
          {projectsOpen && (
            <nav className="mt-1 min-h-0 flex-1 overflow-y-auto px-2">
              {projects.length === 0 && (
                <div className="px-2 py-3 text-xs text-slate-400">暂无项目</div>
              )}
              {projects.map((project) => (
                <Link
                  key={project.id}
                  to={`/projects/${project.id}`}
                  className={`block truncate rounded-md px-2 py-1.5 text-sm ${
                    activeProjectId === project.id
                      ? 'bg-slate-100 font-medium text-slate-900'
                      : 'text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {project.name}
                </Link>
              ))}
            </nav>
          )}

          {activeProjectId !== null && projectsOpen && (
            <div className="mt-4 shrink-0 border-t border-slate-100 px-2 pt-3">
              <div className="px-2 text-xs font-medium text-slate-500">工作台</div>
              <nav className="mt-1 space-y-0.5">
                {workspaceSections.map((section) => (
                  <Link
                    key={section.key}
                    to={`/projects/${activeProjectId}?tab=${section.key}`}
                    className={`block rounded-md px-2 py-1.5 text-sm ${
                      activeTab === section.key
                        ? 'bg-slate-100 font-medium text-slate-900'
                        : 'text-slate-600 hover:bg-slate-50'
                    }`}
                  >
                    {section.label}
                  </Link>
                ))}
              </nav>
            </div>
          )}

          <button
            onClick={() => navigate('/providers')}
            className="mt-auto flex items-center gap-2 border-t border-slate-200 px-3 py-3 text-left hover:bg-slate-50"
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-slate-900 text-[10px] text-white">
              AI
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs font-medium text-slate-700">
                {provider ? provider.name : '未配置模型服务'}
              </span>
              {provider && (
                <span className="block truncate text-[10px] text-slate-400">
                  {provider.default_model || '未设默认模型'}
                </span>
              )}
            </span>
          </button>
        </aside>

        <main className="min-w-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>

      {aboutOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center overflow-auto bg-black/40 p-4"
          onClick={() => setAboutOpen(false)}
        >
          <div
            className="max-h-full w-80 rounded-lg bg-white p-6 text-center shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 className="font-semibold">SDLC Agent</h3>
            <p className="mt-2 text-sm text-slate-500">
              软件生命周期智能协作平台
              <br />
              本地单机版
            </p>
            <button
              onClick={() => setAboutOpen(false)}
              className="mt-5 w-full rounded-md bg-slate-900 px-4 py-2 text-sm text-white"
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
