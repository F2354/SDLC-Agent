import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { login } from '../lib/api'
import { useAuthStore } from '../store/auth'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const setToken = useAuthStore((state) => state.setToken)
  const navigate = useNavigate()

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      const result = await login({ username, password })
      setToken(result.access_token)
      navigate('/projects')
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold">登录 SDLC Agent</h1>
        <p className="mb-6 text-sm text-slate-500">软件生命周期智能协作平台</p>
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
            登录
          </button>
        </form>
        <p className="mt-4 text-sm text-slate-500">
          还没有账号？<Link className="text-slate-900 underline" to="/register">注册</Link>
        </p>
        <Link to="/projects" className="mt-2 block text-sm text-slate-500 underline">
          直接进入开发预览
        </Link>
      </div>
    </div>
  )
}
