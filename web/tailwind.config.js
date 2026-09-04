/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      canvas: 'var(--canvas)',
      ink: 'var(--ink)',
      charcoal: 'var(--charcoal)',
      body: 'var(--body)',
      mute: 'var(--mute)',
      stone: 'var(--stone)',
      ash: 'var(--ash)',
      'surface-soft': 'var(--surface-soft)',
      'surface-card': 'var(--surface-card)',
      'surface-dark': 'var(--surface-dark)',
      'surface-dark-elevated': 'var(--surface-dark-elevated)',
      hairline: 'var(--hairline)',
      'hairline-strong': 'var(--hairline-strong)',
      accent: 'var(--accent)',
      success: 'var(--success)',
      warning: 'var(--warning)',
      danger: 'var(--danger)',
      white: '#ffffff',
      black: '#000000',
    },
    fontFamily: {
      mono: 'var(--font-mono)',
    },
    fontSize: {
      micro: ['12px', { lineHeight: '1.4' }],
      caption: ['13px', { lineHeight: '1.4' }],
      body: ['16px', { lineHeight: '1.5' }],
      'section-title': ['16px', { lineHeight: '1.4', fontWeight: '700' }],
      'page-title': ['26px', { lineHeight: '1.3', fontWeight: '700' }],
      display: ['38px', { lineHeight: '1.5', fontWeight: '700' }],
    },
    // Deliberately not overriding `spacing` — Tailwind's default scale already maps
    // 1/2/3/4/6/8/12/16/24 to exactly 4/8/12/16/24/32/48/64/96px (the spec's own base
    // system) as a subset, while still leaving every other spacing utility
    // (h-96, w-60, gap-1.5, ...) usable throughout the app.
    borderRadius: {
      none: '0px',
      container: 'var(--radius-container)',
      DEFAULT: 'var(--radius-interactive)',
      interactive: 'var(--radius-interactive)',
      full: '9999px',
    },
    extend: {
      boxShadow: {
        none: 'none',
      },
    },
  },
  plugins: [],
}
