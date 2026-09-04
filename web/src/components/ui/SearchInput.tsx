import type { InputHTMLAttributes } from 'react'
import clsx from 'clsx'

interface SearchInputProps extends InputHTMLAttributes<HTMLInputElement> {
  shortcut?: string
}

export function SearchInput({ shortcut, className, ...rest }: SearchInputProps) {
  return (
    <div className={clsx('flex items-center gap-2 rounded border border-hairline bg-surface-soft px-3 py-1.5', className)}>
      <span aria-hidden="true" className="text-mute">
        [?]
      </span>
      <input
        className="w-full bg-transparent text-caption text-ink placeholder:text-ash focus:outline-none"
        {...rest}
      />
      {shortcut && (
        <kbd className="rounded border border-hairline-strong px-1.5 py-0.5 text-micro text-mute">{shortcut}</kbd>
      )}
    </div>
  )
}
