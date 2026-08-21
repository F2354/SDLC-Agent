import { useEffect, useState, type FormEvent } from 'react'

import {
  createProvider,
  deleteProvider,
  listProviders,
  testProvider,
  type Provider,
  type ProviderType,
} from '../lib/api'

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

  async function load() {
    setLoading(true)
    setError('')
    try {
      setProviders(await listProviders())
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
      await createProvider({
        name,
        type,
        base_url: baseUrl,
        api_key: apiKey || null,
        default_model: defaultModel,
        models: modelsText
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean),
      })
      setCreating(false)
      setName('')
      setBaseUrl('')
      setApiKey('')
      setDefaultModel('')
      setModelsText('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    }
  }

  async function handleTest(providerId: number) {
    setTestingId(providerId)
    try {
      const result = await testProvider(providerId)
      setTestResults((prev) => ({ ...prev, [providerId]: { ok: result.ok, message: result.message } }))
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [providerId]: { ok: false, message: err instanceof Error ? err.message : '测试失败' },
      }))
    } finally {
      setTestingId(null)
    }
  }

  async function handleDelete(providerId: number) {
    setError('')
    try {
      await deleteProvider(providerId)
      setProviders((prev) => prev.filter((item) => item.id !== providerId))
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">模型服务</h1>
          <p className="text-sm text-slate-500">配置用户自己的大模型服务商</p>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white"
        >
          新增 Provider
        </button>
      </div>

      {creating && (
        <form
          onSubmit={handleCreate}
          className="mt-6 max-w-xl rounded-lg border border-slate-200 bg-white p-5"
        >
          <h2 className="font-medium">新增 Provider</h2>
          <div className="mt-4 space-y-4">
            <label className="block text-sm">
              名称
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                required
              />
            </label>
            <label className="block text-sm">
              类型
              <select
                value={type}
                onChange={(event) => setType(event.target.value as ProviderType)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
              >
                <option value="openai_compatible">OpenAI 兼容云服务</option>
                <option value="ollama">Ollama 本地</option>
              </select>
            </label>
            <label className="block text-sm">
              Base URL
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api.deepseek.com/v1 或 http://127.0.0.1:11434/v1"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
                required
              />
            </label>
            <label className="block text-sm">
              API Key（Ollama 可留空）
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="block text-sm">
              默认模型
              <input
                value={defaultModel}
                onChange={(event) => setDefaultModel(event.target.value)}
                placeholder="如 deepseek-chat"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
            <label className="block text-sm">
              可用模型（每行一个）
              <textarea
                value={modelsText}
                onChange={(event) => setModelsText(event.target.value)}
                className="mt-1 min-h-20 w-full rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
          </div>
          <div className="mt-5 flex gap-2">
            <button className="rounded-md bg-slate-900 px-4 py-2 text-sm text-white">
              保存
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
        {!loading && providers.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">
            暂无 Provider，添加 DeepSeek、MiMo 或 Ollama 后即可开始生成。
          </div>
        )}
        {providers.map((provider) => (
          <div key={provider.id} className="rounded-lg border border-slate-200 bg-white p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-medium">{provider.name}</h2>
                <p className="mt-1 text-sm text-slate-500">
                  {provider.type === 'ollama' ? 'Ollama 本地' : 'OpenAI 兼容'} ·{' '}
                  {provider.base_url} · Key: {provider.api_key_masked ?? '未设置'}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => void handleTest(provider.id)}
                  disabled={testingId === provider.id}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600"
                >
                  {testingId === provider.id ? '测试中...' : '测试连接'}
                </button>
                <button
                  onClick={() => void handleDelete(provider.id)}
                  className="rounded-md border border-red-200 px-3 py-1.5 text-sm text-red-600"
                >
                  删除
                </button>
              </div>
            </div>
            {testResults[provider.id] && (
              <div
                className={`mt-3 rounded-md px-3 py-2 text-sm ${
                  testResults[provider.id].ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
                }`}
              >
                {testResults[provider.id].message}
              </div>
            )}
            {provider.models.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {provider.models.map((model) => (
                  <span
                    key={model.id}
                    className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600"
                  >
                    {model.model_name}
                    {model.is_default ? '（默认）' : ''}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
