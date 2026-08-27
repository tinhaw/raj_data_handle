import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    // The imported ERP source remains a traceable upstream snapshot. Current
    // pages use relative imports, so @ can safely resolve the original ERP
    // module graph without copying or rewriting those components.
    alias: {
      '@': fileURLToPath(new URL('../erp-compat/web/src', import.meta.url)),
    },
    dedupe: ['vue', 'vue-router', 'pinia', 'element-plus', 'axios', 'decimal.js', '@vueuse/core'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/erp-api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/erp-api/, ''),
      },
    },
  },
})
