// End-to-end tests (e2e/): `npm run test:e2e` against a running Kartei with fresh `seed_demo` data.
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: 'e2e',
  workers: 1, // the tests share one database
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE || 'http://localhost:8000',
    locale: 'en',
    trace: 'retain-on-failure',
  },
})
