import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { App } from 'components/App'
import { Playground } from 'pages/Playground'
import { Layout } from 'components/Layout'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/admin/*" element={<App />} />
          <Route path="/playground/*" element={<Playground />} />
          <Route path="*" element={<Navigate to="/admin/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  </StrictMode>
)
