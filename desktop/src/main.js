'use strict'

// SDLC Agent 桌面壳（Electron）。
// 启动时拉起内置的便携 Python 运行后端，等待健康检查通过后加载界面；
// 退出时结束后端进程。数据（SQLite 与项目工作区）放在 exe 同级的 data/ 目录，
// 使整个文件夹可直接拷贝、免安装运行（绿色应用）。

const { app, BrowserWindow, dialog } = require('electron')
const { spawn, spawnSync, execFile } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const http = require('http')
const net = require('net')
const path = require('path')

let mainWindow = null
let backendProcess = null
let backendPort = null
let quitting = false

function runtimeRoot() {
  // 打包后：resources/ 下含 python/ 与 backend/；开发时：desktop/runtime/
  return app.isPackaged
    ? process.resourcesPath
    : path.join(__dirname, '..', 'runtime')
}

function resolvePython() {
  // 打包版只认内置运行时，绝不回退到用户机器上的 Python，
  // 避免用到缺少依赖的系统解释器。开发模式才允许回退到仓库 .venv。
  const candidates = [path.join(runtimeRoot(), 'python', 'python.exe')]
  if (!app.isPackaged) {
    candidates.push(
      path.join(__dirname, '..', '..', 'backend', '.venv', 'Scripts', 'python.exe'),
    )
  }
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate
    }
  }
  return null
}

function resolveBackendDir() {
  const packaged = path.join(runtimeRoot(), 'backend')
  if (fs.existsSync(path.join(packaged, 'app', 'main.py'))) {
    return packaged
  }
  return path.join(__dirname, '..', '..', 'backend')
}

function portableDataDir() {
  // 数据放在用户目录（默认隐藏），使界面上只留一个可执行文件。
  // 单文件便携模式下程序每次解压到临时目录，不能依赖 exe 同级目录。
  if (app.isPackaged) {
    return path.join(app.getPath('appData'), 'SDLC-Agent')
  }
  return path.join(__dirname, '..', '..')
}

function loadOrCreateSecret(dir) {
  const file = path.join(dir, 'secret.key')
  try {
    const existing = fs.readFileSync(file, 'utf8').trim()
    if (existing) {
      return existing
    }
  } catch (err) {
    // 首次运行尚无密钥文件，落到下面生成。
  }
  const secret = crypto.randomBytes(48).toString('hex')
  fs.writeFileSync(file, secret, { encoding: 'utf8' })
  return secret
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })
}

function waitForHealth(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(
        { host: '127.0.0.1', port, path: '/api/health', timeout: 2000 },
        (res) => {
          res.resume()
          if (res.statusCode === 200) {
            resolve()
          } else {
            retry()
          }
        },
      )
      req.on('error', retry)
      req.on('timeout', () => {
        req.destroy()
        retry()
      })
    }
    const retry = () => {
      if (Date.now() > deadline) {
        reject(new Error('后端启动超时，请检查是否被杀毒软件拦截。'))
      } else {
        setTimeout(attempt, 500)
      }
    }
    attempt()
  })
}

function startBackend(port) {
  const pythonExe = resolvePython()
  if (!pythonExe) {
    throw new Error('未找到内置 Python 运行时，应用文件可能不完整，请重新解压/安装。')
  }
  // 自带运行时自检：确认依赖完整，避免带着缺依赖的解释器启动。
  const probe = spawnSync(pythonExe, ['-c', 'import fastapi, uvicorn'], { windowsHide: true })
  if (probe.status !== 0) {
    throw new Error('内置 Python 运行时缺少依赖，应用文件可能已损坏。')
  }

  const backendDir = resolveBackendDir()
  const dataDir = portableDataDir()
  const projectsDir = path.join(dataDir, 'projects')
  fs.mkdirSync(projectsDir, { recursive: true })

  const dbPath = path.join(dataDir, 'sdlc.db').replace(/\\/g, '/')
  const env = {
    ...process.env,
    // 单用户桌面场景：保留本地免登录，避免每次启动都要登录。
    ENV: process.env.SDLC_ENV || 'development',
    SECRET_KEY: loadOrCreateSecret(dataDir),
    DATABASE_URL: `sqlite:///${dbPath}`,
    PROJECT_WORKSPACE_ROOT: projectsDir,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
  }

  const child = spawn(
    pythonExe,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    { cwd: backendDir, env, windowsHide: true },
  )
  child.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`))
  child.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`))
  child.on('exit', (code) => {
    backendProcess = null
    if (!quitting) {
      dialog.showErrorBox('后端已退出', `后端进程意外退出（code=${code}）。`)
      app.quit()
    }
  })
  return child
}

function stopBackend() {
  if (!backendProcess) {
    return
  }
  const { pid } = backendProcess
  backendProcess = null
  try {
    if (process.platform === 'win32') {
      execFile('taskkill', ['/PID', String(pid), '/T', '/F'])
    } else {
      process.kill(pid)
    }
  } catch (err) {
    // 进程可能已结束，忽略。
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    backgroundColor: '#0f172a',
    title: 'SDLC Agent',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  })
  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.on('closed', () => {
    mainWindow = null
  })
  mainWindow.loadFile(path.join(__dirname, 'loading.html'))
}

async function boot() {
  createWindow()
  try {
    backendPort = await findFreePort()
    backendProcess = startBackend(backendPort)
    await waitForHealth(backendPort, 90000)
    if (mainWindow) {
      await mainWindow.loadURL(`http://127.0.0.1:${backendPort}`)
    }
  } catch (err) {
    dialog.showErrorBox('启动失败', err && err.message ? err.message : String(err))
    app.quit()
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore()
      }
      mainWindow.focus()
    }
  })

  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', () => {
    quitting = true
    stopBackend()
  })

  app.whenReady().then(boot)
}
