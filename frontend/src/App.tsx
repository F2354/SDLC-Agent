import { Navigate, Route, Routes } from 'react-router-dom'

import AppShell from './components/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import ProjectWorkspacePage from './pages/ProjectWorkspacePage'
import ProjectsPage from './pages/ProjectsPage'
import ProvidersPage from './pages/ProvidersPage'

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route element={<AppShell />}>
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectWorkspacePage />} />
          <Route path="/providers" element={<ProvidersPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Routes>
    </ErrorBoundary>
  )
}
