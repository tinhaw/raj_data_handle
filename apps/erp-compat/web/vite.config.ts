import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: Number(env.VITE_PORT || 5173),
      proxy: env.VITE_DEV_API_PROXY === 'false'
        ? undefined
        : {
            '/api': {
              target: env.VITE_DEV_API_TARGET || 'http://localhost:8080',
              changeOrigin: true,
            },
          },
    },
  }
})
