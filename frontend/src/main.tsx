import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ToastProvider } from './components/ui/toast.tsx'

// Apply persisted / preferred theme before the first paint to avoid a flash.
(function initTheme() {
  try {
    const stored = window.localStorage.getItem('cc.theme');
    const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    const theme = stored === 'light' || stored === 'dark'
      ? stored
      : prefersDark
        ? 'dark'
        : 'light';
    document.documentElement.classList.toggle('dark', theme === 'dark');
  } catch {
    /* no-op */
  }
})();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
)
