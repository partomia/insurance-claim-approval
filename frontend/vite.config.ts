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
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5550",
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api/, ""),
      },
    },

    allowedHosts: [".trycloudflare.com", ".ngrok-free.app", ".ngrok.io", "localhost", ".cloudera.site"],
  },
})
