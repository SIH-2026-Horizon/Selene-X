import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { buttonClassName, type ButtonVariant } from './buttonStyles'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  marker?: ReactNode
}

export function Button({ variant = 'secondary', marker, className, children, ...rest }: ButtonProps) {
  return (
    <button
      className={buttonClassName(variant, className)}
      {...rest}
    >
      {marker}
      {children}
    </button>
  )
}
