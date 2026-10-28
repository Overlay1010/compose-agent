import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 서버는 5174번(다른 프로젝트가 쓰는 5173을 피함), /api 요청은 FastAPI(8100번)로 넘긴다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8100',
    },
  },
})
