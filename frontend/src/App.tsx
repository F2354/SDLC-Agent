import { Navigate, Route, Routes } from 'react-router-dom'

import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import ProjectWorkspacePage from './pages/ProjectWorkspacePage'
import ProjectsPage from './pages/ProjectsPage'
import ProvidersPage from './pages/ProvidersPage'
import RegisterPage from './pages/RegisterPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<AppShell />}>
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<ProjectWorkspacePage />} />
        <Route path="/providers" element={<ProvidersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}
