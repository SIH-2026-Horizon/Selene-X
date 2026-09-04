import clsx from 'clsx'
import { useThemeStore, type ThemePreference } from '@/stores/themeStore'

const OPTIONS: { value: ThemePreference; label: string; aria: string }[] = [
  { value: 'light', label: '☀', aria: 'Light theme' },
  { value: 'dark', label: '☾', aria: 'Dark theme' },
  { value: 'system', label: 'AUTO', aria: 'Match system theme' },
]

export function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme)
  const setTheme = useThemeStore((s) => s.setTheme)

  return (
    <div
      role="radiogroup"
      aria-label="Color theme"
      className="flex items-center gap-0.5 rounded border border-hairline p-0.5"
    >
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={theme === opt.value}
          aria-label={opt.aria}
          onClick={() => setTheme(opt.value)}
          className={clsx(
            'rounded px-1.5 py-0.5 text-micro leading-none',
            theme === opt.value ? 'bg-ink text-canvas' : 'text-mute hover:text-ink',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
