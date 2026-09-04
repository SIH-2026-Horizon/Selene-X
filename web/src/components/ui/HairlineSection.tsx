import type { HTMLAttributes } from 'react'
import clsx from 'clsx'

export function HairlineSection({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx('border border-hairline', className)} {...rest} />
}
