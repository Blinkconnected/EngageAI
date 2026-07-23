import { createTheme, type Theme } from '@mui/material/styles'

export type ThemeMode = 'light' | 'dark'
export type Direction = 'ltr' | 'rtl'

// Blink brand palette
const brand = {
  green: '#8CC63F',
  greenDark: '#6BA82D',
  black: '#171412',
  charcoal: '#231F20',
  slate: '#4D4948',
  line: '#E4E3E1',
  soft: '#F2F2F0',
}

const softShadow = (opacity: number) => `0 1px 3px rgba(23, 20, 18, ${opacity})`

export function createAppTheme(mode: ThemeMode, direction: Direction): Theme {
  const isDark = mode === 'dark'

  return createTheme({
    direction,
    palette: {
      mode,
      primary: {
        main: brand.green,
        dark: brand.greenDark,
        light: '#A6D666',
        contrastText: brand.black,
      },
      secondary: {
        main: brand.charcoal,
      },
      divider: isDark ? 'rgba(228, 227, 225, 0.12)' : brand.line,
      background: isDark
        ? { default: brand.black, paper: '#1E1B19' }
        : { default: brand.soft, paper: '#FFFFFF' },
      text: isDark
        ? { primary: brand.soft, secondary: 'rgba(242, 242, 240, 0.7)' }
        : { primary: brand.black, secondary: brand.slate },
    },
    shape: {
      borderRadius: 12,
    },
    typography: {
      fontFamily: ['"Nunito Sans"', 'system-ui', '-apple-system', 'sans-serif'].join(','),
      h1: { fontFamily: '"Baloo 2", system-ui, sans-serif', fontWeight: 700 },
      h2: { fontFamily: '"Baloo 2", system-ui, sans-serif', fontWeight: 700 },
      h3: { fontFamily: '"Baloo 2", system-ui, sans-serif', fontWeight: 600 },
      h4: { fontFamily: '"Baloo 2", system-ui, sans-serif', fontWeight: 600 },
      h5: { fontFamily: '"Baloo 2", system-ui, sans-serif', fontWeight: 600 },
      h6: { fontFamily: '"Baloo 2", system-ui, sans-serif', fontWeight: 600 },
      button: { fontWeight: 700 },
    },
    components: {
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: { textTransform: 'none', borderRadius: 999, paddingInline: 20 },
          outlined: { borderWidth: 1.5 },
        },
        variants: [
          {
            props: { variant: 'contained', color: 'primary' },
            style: {
              color: brand.black,
              '&:hover': {
                boxShadow: `0 8px 20px ${isDark ? 'rgba(140, 198, 63, 0.35)' : 'rgba(140, 198, 63, 0.4)'}`,
              },
            },
          },
        ],
      },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: 'none' },
          elevation1: { boxShadow: softShadow(isDark ? 0.4 : 0.06) },
          elevation2: { boxShadow: softShadow(isDark ? 0.5 : 0.08) },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            boxShadow: softShadow(isDark ? 0.4 : 0.06),
            border: `1px solid ${isDark ? 'rgba(228, 227, 225, 0.08)' : brand.line}`,
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          colorDefault: {
            backgroundColor: isDark ? brand.black : '#FFFFFF',
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 999, fontWeight: 600 },
        },
      },
    },
  })
}
