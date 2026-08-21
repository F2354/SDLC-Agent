import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { register } from '../lib/api'
import { useAuthStore } from '../store/auth'

export default function RegisterPage() {
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const setToken = useAuthStore((state) => state.setToken)
  const navigate = useNavigate()

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      const result = await register({ username, password, display_name: displayName })
      setToken(result.access_token)
      navigate('/projects')
    } catch (err) {
      setError(err instanceof Error ? err.message : '注册失败')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold">注册 SDLC Agent</h1>
        <p className="mb-6 text-sm text-slate-500">创建项目开始软件生命周期协作</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block text-sm">
            用户名
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            显示名称
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            密码
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          {error && <div className="text-sm text-red-600">{error}</div>}
          <button className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm text-white">
            注册
          </button>
        </form>
        <p className="mt-4 text-sm text-slate-500">
          已有账号？<Link className="text-slate-900 underline" to="/login">登录</Link>
        </p>
      </div>
    </div>
  )
}
