import { useEffect, useState, type FormEvent } from 'react'

import { createProvider, deleteProvider, listProviders, testProvider, type Provider, type ProviderType } from '../lib/api'

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [type, setType] = useState<ProviderType>('openai_compatible')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [defaultModel, setDefaultModel] = useState('')
  const [modelsText, setModelsText] = useState('')
  const [testResults, setTestResults] = useState<Record<number, { ok: boolean; message: string }>>({})
  const [testingId, setTestingId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  async function load() { setLoading(true); setError(''); try { setProviders(await listProviders()) } catch (err) { setError(err instanceof Error ? err.message : '加载失败') } finally { setLoading(false) } }
  useEffect(() => { void load() }, [])

  async function handleCreate(event: FormEvent) {
    event.preventDefault(); if (saving) return; setError(''); setSaving(true)
    try {
      await createProvider({ name, type, base_url: baseUrl, api_key: apiKey || null, default_model: defaultModel, models: modelsText.split('\n').map((item) => item.trim()).filter(Boolean) })
      setCreating(false); setName(''); setType('openai_compatible'); setBaseUrl(''); setApiKey(''); setDefaultModel(''); setModelsText(''); await load()
    } catch (err) { setError(err instanceof Error ? err.message : '创建失败') } finally { setSaving(false) }
  }

  async function handleTest(providerId: number) { setTestingId(providerId); try { const result = await testProvider(providerId); setTestResults((prev) => ({ ...prev, [providerId]: { ok: result.ok, message: result.message } })) } catch (err) { setTestResults((prev) => ({ ...prev, [providerId]: { ok: false, message: err instanceof Error ? err.message : '测试失败' } })) } finally { setTestingId(null) } }
  async function handleDelete(provider: Provider) { if (!window.confirm(`确定删除 Provider「${provider.name}」吗？此操作不可撤销。`)) return; setError(''); setDeletingId(provider.id); try { await deleteProvider(provider.id); setProviders((prev) => prev.filter((item) => item.id !== provider.id)); setTestResults((prev) => { const next = { ...prev }; delete next[provider.id]; return next }) } catch (err) { setError(err instanceof Error ? err.message : '删除失败') } finally { setDeletingId(null) } }

  return (
    <div className="page-container">
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div><div className="page-eyebrow">Model gateway</div><h1 className="page-title mt-2">模型服务</h1><p className="page-subtitle mt-3">连接你自己的云端模型或本地 Ollama，让每个阶段 Agent 都拥有可靠的推理能力。</p></div>
        <button onClick={() => setCreating(true)} className="primary-action px-5 py-3 text-sm font-semibold"><span className="mr-2">+</span>新增 Provider</button>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-3"><InfoStat icon="◉" label="已配置服务" value={String(providers.length)} /><InfoStat icon="⚡" label="连接方式" value="云端 / 本地" /><InfoStat icon="▣" label="密钥存储" value="加密保存" /></div>

      {creating && <form onSubmit={handleCreate} className="surface-section section-indigo mt-6 p-7"><div className="flex items-start justify-between border-b soft-divider pb-5"><div><div className="page-eyebrow">New provider</div><h2 className="mt-1 text-base font-bold text-slate-900">新增模型服务</h2><p className="mt-1 text-xs text-slate-400">API Key 仅用于服务调用，不会在界面中明文展示。</p></div><button type="button" onClick={() => setCreating(false)} className="secondary-action flex h-8 w-8 items-center justify-center rounded-lg p-0 text-lg">×</button></div><div className="mt-6 grid gap-5 md:grid-cols-2"><Field label="服务名称"><input value={name} onChange={(event) => setName(event.target.value)} className="field-control mt-2 px-3.5 py-3" placeholder="例如：DeepSeek" required /></Field><Field label="服务类型"><select value={type} onChange={(event) => setType(event.target.value as ProviderType)} className="field-control mt-2 px-3.5 py-3"><option value="openai_compatible">OpenAI 兼容云服务</option><option value="ollama">Ollama 本地</option></select></Field><Field label="Base URL"><input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.deepseek.com/v1" className="field-control mt-2 px-3.5 py-3" required /></Field><Field label="API Key（Ollama 可留空）"><input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} className="field-control mt-2 px-3.5 py-3" placeholder="sk-..." /></Field><Field label="默认模型"><input value={defaultModel} onChange={(event) => setDefaultModel(event.target.value)} placeholder="如 deepseek-chat" className="field-control mt-2 px-3.5 py-3" /></Field><Field label="可用模型（每行一个）"><textarea value={modelsText} onChange={(event) => setModelsText(event.target.value)} className="field-control mt-2 min-h-24 px-3.5 py-3" placeholder="deepseek-chat\ndeepseek-reasoner" /></Field></div><div className="mt-6 flex gap-3"><button type="submit" disabled={saving} className="primary-action px-5 py-2.5 text-sm font-semibold">{saving ? '保存中...' : '保存服务'}</button><button type="button" onClick={() => setCreating(false)} className="secondary-action px-5 py-2.5 text-sm font-semibold">取消</button></div></form>}

      {error && <div className="mt-5 rounded-xl border border-red-100 bg-red-50 px-3.5 py-3 text-xs text-red-600">{error}</div>}
      <div className="mt-8 space-y-4">
        {loading && <div className="surface-section section-slate p-10 text-center text-xs text-slate-400">正在加载模型服务...</div>}
        {!loading && providers.length === 0 && <div className="empty-state p-14 text-center"><div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-2xl text-indigo-500">✦</div><h2 className="mt-4 text-base font-bold text-slate-800">还没有模型服务</h2><p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-slate-500">添加一个 OpenAI 兼容服务或连接本地 Ollama，开始使用阶段 Agent。</p><button onClick={() => setCreating(true)} className="primary-action mt-5 px-5 py-2.5 text-xs font-semibold">添加第一个服务</button></div>}
        {providers.map((provider) => <ProviderCard key={provider.id} provider={provider} testResult={testResults[provider.id]} testing={testingId === provider.id} deleting={deletingId === provider.id} onTest={() => void handleTest(provider.id)} onDelete={() => void handleDelete(provider)} />)}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block"><span className="field-label">{label}</span>{children}</label> }
function InfoStat({ icon, label, value }: { icon: string; label: string; value: string }) { return <div className="surface-section section-emerald flex items-center gap-3 p-4"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-sm text-indigo-600">{icon}</span><div><div className="text-[11px] font-medium text-slate-400">{label}</div><div className="mt-0.5 text-sm font-bold text-slate-800">{value}</div></div></div> }
function ProviderCard({ provider, testResult, testing, deleting, onTest, onDelete }: { provider: Provider; testResult?: { ok: boolean; message: string }; testing: boolean; deleting: boolean; onTest: () => void; onDelete: () => void }) { return <div className="provider-row section-slate p-5 lg:p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div className="flex min-w-0 items-center gap-3"><span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-sm font-bold text-white ${provider.type === 'ollama' ? 'bg-gradient-to-br from-orange-400 to-rose-500' : 'bg-gradient-to-br from-indigo-500 to-violet-600'}`}>{provider.type === 'ollama' ? 'OL' : 'AI'}</span><div className="min-w-0"><div className="flex items-center gap-2"><h2 className="truncate text-sm font-bold text-slate-900">{provider.name}</h2><span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-600">已启用</span></div><p className="mt-1 max-w-[600px] truncate text-xs text-slate-400">{provider.type === 'ollama' ? 'Ollama 本地服务' : 'OpenAI 兼容服务'} · {provider.base_url}</p></div></div><div className="flex gap-2"><button onClick={onTest} disabled={testing} className="secondary-action px-3 py-2 text-xs font-semibold">{testing ? '测试中...' : '测试连接'}</button><button onClick={onDelete} disabled={deleting} className="rounded-lg border border-red-100 px-3 py-2 text-xs font-semibold text-red-500 hover:bg-red-50 disabled:opacity-50">{deleting ? '删除中...' : '删除'}</button></div></div>{testResult && <div className={`mt-4 rounded-xl px-3.5 py-3 text-xs ${testResult.ok ? 'border border-emerald-100 bg-emerald-50 text-emerald-700' : 'border border-red-100 bg-red-50 text-red-600'}`}>{testResult.message}</div>}<div className="mt-5 flex flex-wrap items-center gap-2 border-t soft-divider pt-4"><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Models</span>{provider.models.length > 0 ? provider.models.map((model) => <span key={model.id} className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-[11px] font-medium text-slate-600">{model.model_name}{model.is_default ? <span className="ml-1 text-indigo-500">· 默认</span> : ''}</span>) : <span className="text-xs text-slate-400">未登记可用模型</span>}<span className="ml-auto text-[11px] text-slate-400">Key: {provider.api_key_masked ?? '未设置'}</span></div></div> }
