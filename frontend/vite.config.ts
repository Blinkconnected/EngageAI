/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Vite's dev server rejects any request whose Host header it doesn't
    // recognise (DNS-rebinding protection), which 403s every request that
    // reaches it through nginx under the real domain rather than
    // localhost. Listed explicitly instead of disabling the check with
    // `true`, so only this deployment's hostname is accepted.
    allowedHosts: ['engage.blinkconnected.com'],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    // Default (5000ms) is tight for MUI X Data Grid + dialog interaction
    // tests under userEvent's real-timer typing, especially with several
    // test files' jsdom environments running concurrently on constrained
    // hardware — bumped rather than reducing file parallelism, which
    // would slow the whole suite down on ordinary CI hardware to fix a
    // problem that's specific to this sandbox.
    testTimeout: 15_000,
  },
})
