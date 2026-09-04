interface LoadingStateProps {
  label?: string
}

export function LoadingState({ label = 'Loading' }: LoadingStateProps) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6 text-caption text-mute">
      <span aria-hidden="true" className="animate-pulse">
        [···]
      </span>
      <span>{label}</span>
    </div>
  )
}
