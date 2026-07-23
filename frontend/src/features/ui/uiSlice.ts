import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { Direction, ThemeMode } from '../../theme/theme'

const THEME_STORAGE_KEY = 'blinkengage.themeMode'
const DIRECTION_STORAGE_KEY = 'blinkengage.direction'

function readStoredThemeMode(): ThemeMode {
  const stored = localStorage.getItem(THEME_STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function readStoredDirection(): Direction {
  const stored = localStorage.getItem(DIRECTION_STORAGE_KEY)
  return stored === 'rtl' ? 'rtl' : 'ltr'
}

export interface UiState {
  themeMode: ThemeMode
  direction: Direction
}

const initialState: UiState = {
  themeMode: readStoredThemeMode(),
  direction: readStoredDirection(),
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    setThemeMode(state, action: PayloadAction<ThemeMode>) {
      state.themeMode = action.payload
      localStorage.setItem(THEME_STORAGE_KEY, action.payload)
    },
    toggleThemeMode(state) {
      state.themeMode = state.themeMode === 'light' ? 'dark' : 'light'
      localStorage.setItem(THEME_STORAGE_KEY, state.themeMode)
    },
    setDirection(state, action: PayloadAction<Direction>) {
      state.direction = action.payload
      localStorage.setItem(DIRECTION_STORAGE_KEY, action.payload)
    },
  },
})

export const { setThemeMode, toggleThemeMode, setDirection } = uiSlice.actions
export default uiSlice.reducer
