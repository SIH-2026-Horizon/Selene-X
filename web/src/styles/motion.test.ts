import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const motionStyles = readFileSync(resolve(process.cwd(), 'src/styles/motion.css'), 'utf8')

describe('motion styles', () => {
  it('disables every motion utility when reduced motion is requested', () => {
    const reducedMotionBlock = motionStyles.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*)\n\}/)?.[1]

    expect(reducedMotionBlock).toContain('.motion-enter')
    expect(reducedMotionBlock).toContain('.motion-reveal')
    expect(reducedMotionBlock).toContain('.motion-status-running')
    expect(reducedMotionBlock).toContain('.motion-progress')
    expect(reducedMotionBlock).toContain('animation: none !important')
    expect(reducedMotionBlock).toContain('transition: none !important')
  })
})
