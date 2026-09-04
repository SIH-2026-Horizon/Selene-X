import type { ReactNode } from 'react'

export function FilterPanel({ children }: { children: ReactNode }) {
  return <div className="flex flex-col divide-y divide-hairline border border-hairline">{children}</div>
}

export function FilterSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="p-3">
      <div className="mb-2 text-micro font-medium uppercase tracking-wide text-mute">{title}</div>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  )
}

interface FilterCheckboxProps {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  count?: number
}

export function FilterCheckbox({ label, checked, onChange, count }: FilterCheckboxProps) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-caption text-body">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-ink"
      />
      <span className="flex-1">{label}</span>
      {count !== undefined && <span className="text-micro text-ash">{count}</span>}
    </label>
  )
}

interface FilterRangeProps {
  label: string
  min: number
  max: number
  value: [number, number]
  step?: number
  unit?: string
  onChange: (value: [number, number]) => void
}

export function FilterRange({ label, min, max, value, step = 1, unit, onChange }: FilterRangeProps) {
  return (
    <div>
      <div className="flex items-center justify-between text-caption text-body">
        <span>{label}</span>
        <span className="tabular-nums text-mute">
          {value[0]}
          {unit} – {value[1]}
          {unit}
        </span>
      </div>
      <div className="mt-1.5 flex gap-2">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value[0]}
          onChange={(e) => onChange([Number(e.target.value), value[1]])}
          className="w-full accent-ink"
          aria-label={`${label} minimum`}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value[1]}
          onChange={(e) => onChange([value[0], Number(e.target.value)])}
          className="w-full accent-ink"
          aria-label={`${label} maximum`}
        />
      </div>
    </div>
  )
}
