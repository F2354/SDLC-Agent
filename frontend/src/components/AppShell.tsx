import { useEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { listProjects, listProviders, type Project, type Provider } from '../lib/api'

const workspaceSections = [
  { key: 'chat', label: '对话', icon: '⌁' },
  { key: 'stages', label: '过程模型', icon: '⇆' },
  { key: 'artifacts', label: '制品', icon: '≡' },
  { key: 'code', label: '代码', icon: '</>' },
  { key: 'logs', label: '运行日志', icon: '◷' },
]

const menus = [
  { key: 'file', label: '文件', items: [{ label: '新建项目', action: 'new-project' }, { label: '模型服务', action: 'providers' }] },
  { key: 'view', label: '视图', items: [{ label: '折叠项目区', action: 'toggle-projects' }] },
  { key: 'help', label: '帮助', items: [{ label: '关于', action: 'about' }] },
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
    let stale = false
    Promise.all([
      listProjects().then((list) => { if (!stale) setProjects(list) }),
      listProviders().then((list) => { if (!stale) setProvider(list[0] ?? null) }),
    ]).then(() => {
      if (!stale) setLoadError('')
    }).catch((err) => {
      if (!stale) setLoadError(err instanceof Error ? err.message : '加载失败，请检查后端服务')
    })
    return () => { stale = true }
  }, [location.pathname])

  useEffect(() => {
    function closeMenus(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpenMenu(null)
    }
    function onKeydown(event: KeyboardEvent) {
      if (event.key === 'Escape') { setOpenMenu(null); setAboutOpen(false) }
    }
    document.addEventListener('mousedown', closeMenus)
    document.addEventListener('keydown', onKeydown)
    return () => { document.removeEventListener('mousedown', closeMenus); document.removeEventListener('keydown', onKeydown) }
  }, [])

  function handleMenuAction(action: string) {
    setOpenMenu(null)
    if (action === 'new-project') navigate('/projects?new=1')
    if (action === 'providers') navigate('/providers')
    if (action === 'toggle-projects') setProjectsOpen((value) => !value)
    if (action === 'about') setAboutOpen(true)
  }

  return (
    <div className="ide-shell flex h-screen flex-col overflow-hidden text-slate-900">
      <header ref={menuRef} className="ide-topbar flex shrink-0 items-center">
        <Link to="/projects" className="ide-brand">
          <span className="ide-brand-mark">&gt;_</span>
          <span><b>SDLC Agent</b><small>LOCAL DEVELOPMENT WORKSPACE</small></span>
        </Link>
        <nav className="ide-menu-bar">
          {menus.map((menu) => (
            <div key={menu.key} className="relative">
              <button onClick={() => setOpenMenu(openMenu === menu.key ? null : menu.key)} className={`ide-menu-item ${openMenu === menu.key ? 'active' : ''}`}>{menu.label}</button>
              {openMenu === menu.key && <div className="ide-dropdown">{menu.items.map((item) => <button key={item.action} onClick={() => handleMenuAction(item.action)}>{item.label}</button>)}</div>}
            </div>
          ))}
        </nav>
        <div className="ide-topbar-right">
          <span className="ide-connection"><i /> 本地工作区</span>
          <span className="ide-user">U</span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="ide-sidebar flex shrink-0 flex-col">
          <div className="ide-sidebar-toolbar"><span>PROJECTS</span><button onClick={() => navigate('/projects?new=1')} title="新建项目">＋</button></div>
          <button onClick={() => navigate('/projects?new=1')} className="ide-new-project"><span>＋</span> 新建项目</button>
          {loadError && <div className="ide-error">{loadError}</div>}
          {projectsOpen && <nav className="ide-project-list">{projects.length === 0 && <span className="ide-empty">暂无项目</span>}{projects.map((project) => <Link key={project.id} to={`/projects/${project.id}`} className={`ide-project-link ${activeProjectId === project.id ? 'active' : ''}`}><span className="ide-project-dot" /> <span className="truncate">{project.name}</span></Link>)}</nav>}
          {activeProjectId !== null && projectsOpen && <div className="ide-workspace-nav"><div className="ide-sidebar-label">WORKSPACE</div>{workspaceSections.map((section) => <Link key={section.key} to={`/projects/${activeProjectId}?tab=${section.key}`} className={`ide-nav-link ${activeTab === section.key ? 'active' : ''}`}><span>{section.icon}</span>{section.label}</Link>)}</div>}
          <button onClick={() => navigate('/providers')} className="ide-provider-status"><span className="ide-provider-icon">⌘</span><span className="min-w-0 flex-1"><b className="block truncate">{provider?.name || '未配置模型服务'}</b><small className="block truncate">{provider?.default_model || '配置 Provider'}</small></span><span className="text-slate-400">›</span></button>
        </aside>
        <main className="ide-main min-w-0 flex-1 overflow-auto"><Outlet /></main>
      </div>

      {aboutOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4 backdrop-blur-sm" onClick={() => setAboutOpen(false)}><div className="modal-surface w-96 p-7 text-center" onClick={(event) => event.stopPropagation()}><span className="ide-brand-mark mx-auto">&gt;_</span><h3 className="mt-4 text-base font-bold">SDLC Agent</h3><p className="mt-2 text-xs leading-5 text-slate-500">面向软件生命周期的本地多 Agent 开发工作台。</p><button onClick={() => setAboutOpen(false)} className="secondary-action mt-6 w-full px-4 py-2.5 text-xs font-semibold">关闭</button></div></div>}
    </div>
  )
}
