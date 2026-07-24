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
    host: true,
    // Allow Cloudflare Tunnel, ngrok, and other dev proxies
    allowedHosts: [".trycloudflare.com", ".ngrok-free.app", ".ngrok.io", "localhost"],
  },
})
