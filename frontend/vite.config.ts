import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

const backend = 'http://127.0.0.1:8000'

export default defineConfig(({ command }) => ({
  plugins: [svelte()],
  base: command === 'build' ? '/static/' : '/', // Django/whitenoise serves the build under /static/
  build: { target: 'es2022', cssCodeSplit: false },
  server: {
    proxy: {
      '/api': backend,
      '/carddav': backend,
      '/.well-known': backend,
      '/django-admin': backend,
      '^/(person|company)/.*\\.vcf$': backend,
      '/sw.js': backend,
    },
  },
}))
