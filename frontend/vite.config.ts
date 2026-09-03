import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from "path"

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Forward backend API paths to uvicorn VERBATIM (no path rewrite). The
    // FastAPI routers are mounted WITH these prefixes — e.g.
    // `APIRouter(prefix="/api/dashboard")` — so stripping "/api" would turn
    // "/api/dashboard/stats" into a 404 ("/dashboard/stats") that falls back to
    // index.html and breaks the frontend's JSON parsing.
    //
    // Auth for each portal lives OUTSIDE "/api" (`/auth/*`, `/agent/auth/*`,
    // `/insurer/auth/*`). We proxy those exact API subtrees only — NOT bare
    // `/auth`, `/agent`, or `/insurer`, because those collide with client-side
    // SPA routes (e.g. the `/auth` page, `/agent/dashboard`, `/insurer/claims`)
    // that must be served by Vite/React Router on reload, not the backend.
    proxy: Object.fromEntries(
      ["/api", "/auth/", "/agent/auth", "/insurer/auth"].map(prefix => [
        prefix,
        { target: "http://127.0.0.1:5550", changeOrigin: true },
      ])
    ),

    allowedHosts: [".trycloudflare.com", ".ngrok-free.app", ".ngrok.io", "localhost", ".cloudera.site"],
  },
})
