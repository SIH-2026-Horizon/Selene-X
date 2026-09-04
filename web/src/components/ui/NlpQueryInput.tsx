import { useState, type KeyboardEvent } from 'react'
import { Button } from './Button'

interface NlpQueryInputProps {
  label?: string
  placeholder?: string
  initialValue?: string
  examples?: string[]
  onSubmit: (query: string) => void
  loading?: boolean
}

export function NlpQueryInput({
  label = 'SEMANTIC KNOWLEDGE QUERY',
  placeholder = 'Search persisted entity labels, identifiers, or relationships…',
  initialValue = '',
  examples = [],
  onSubmit,
  loading,
}: NlpQueryInputProps) {
  const [value, setValue] = useState(initialValue)

  function submit() {
    if (value.trim()) onSubmit(value.trim())
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border border-hairline p-4">
      <label htmlFor="nlp-query" className="text-micro font-medium uppercase tracking-wide text-mute">
        {label}
      </label>
      <div className="mt-2 flex items-start gap-3">
        <textarea
          id="nlp-query"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={2}
          placeholder={placeholder}
          className="w-full resize-none bg-transparent text-body text-ink placeholder:text-ash focus:outline-none"
        />
        <Button variant="primary" onClick={submit} disabled={loading} aria-label="Query graph">
          {loading ? '···' : '[→] Query graph'}
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-hairline pt-3">
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              setValue(example)
              onSubmit(example)
            }}
            className="text-caption text-mute hover:text-accent hover:underline"
          >
            "{example}"
          </button>
        ))}
      </div>
    </div>
  )
}
