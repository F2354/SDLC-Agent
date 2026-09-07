import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** 全局错误边界：避免任一页面渲染异常导致整站白屏。 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('页面渲染出错:', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (error) {
      return (
        <div className="flex h-full items-center justify-center p-10">
          <div className="max-w-md rounded-lg border border-red-200 bg-red-50 p-6 text-center">
            <h2 className="font-semibold text-red-700">页面出错了</h2>
            <p className="mt-2 break-all text-sm text-red-600">{error.message}</p>
            <button
              onClick={() => this.setState({ error: null })}
              className="mt-5 rounded-md bg-slate-900 px-4 py-2 text-sm text-white"
            >
              重试
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
