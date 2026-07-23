import { describe, expect, it, beforeEach } from 'vitest'
import reducer, { setDirection, setThemeMode, toggleThemeMode } from './uiSlice'

describe('uiSlice', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('toggles theme mode between light and dark', () => {
    const initial = { themeMode: 'light' as const, direction: 'ltr' as const }
    const afterToggle = reducer(initial, toggleThemeMode())
    expect(afterToggle.themeMode).toBe('dark')

    const afterSecondToggle = reducer(afterToggle, toggleThemeMode())
    expect(afterSecondToggle.themeMode).toBe('light')
  })

  it('sets an explicit theme mode and persists it', () => {
    const initial = { themeMode: 'light' as const, direction: 'ltr' as const }
    const next = reducer(initial, setThemeMode('dark'))
    expect(next.themeMode).toBe('dark')
    expect(localStorage.getItem('blinkengage.themeMode')).toBe('dark')
  })

  it('sets direction for RTL locales', () => {
    const initial = { themeMode: 'light' as const, direction: 'ltr' as const }
    const next = reducer(initial, setDirection('rtl'))
    expect(next.direction).toBe('rtl')
    expect(localStorage.getItem('blinkengage.direction')).toBe('rtl')
  })
})
