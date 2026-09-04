import clsx from 'clsx'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'bg-ink text-canvas border-ink hover:bg-charcoal',
  secondary: 'bg-transparent text-ink border-hairline-strong hover:bg-surface-soft',
  ghost: 'bg-transparent text-body border-transparent hover:bg-surface-soft',
  danger: 'bg-transparent text-danger border-danger hover:bg-danger hover:text-canvas',
}

export function buttonClassName(variant: ButtonVariant = 'secondary', className?: string) {
  return clsx(
    'inline-flex items-center gap-2 whitespace-nowrap rounded border px-3 py-1.5 text-caption font-medium transition-colors duration-150',
    'disabled:cursor-not-allowed disabled:opacity-40',
    VARIANT_CLASS[variant],
    className,
  )
}
