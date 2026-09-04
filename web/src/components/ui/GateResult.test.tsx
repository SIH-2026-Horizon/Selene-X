import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GateResult } from './GateResult'
import type { QualityGate } from '@/types/metrics'

const passingGate: QualityGate = {
  id: 'coverage',
  label: 'COVERAGE',
  measured: { status: 'measured', value: 76, unit: '%' },
  thresholdLabel: '≥70%',
  verdict: 'pass',
}

const failingGate: QualityGate = {
  ...passingGate,
  id: 'rmse',
  label: 'SOURCE RMSE',
  verdict: 'fail',
  measured: { status: 'measured', value: 1.4, unit: 'px' },
  thresholdLabel: '<1.00 px',
}

describe('GateResult', () => {
  it('renders the measured value and threshold for a passing gate', () => {
    render(<GateResult gate={passingGate} />)
    expect(screen.getByText('COVERAGE')).toBeInTheDocument()
    expect(screen.getByText('76')).toBeInTheDocument()
    expect(screen.getByText('≥70%')).toBeInTheDocument()
  })

  it('renders a failing gate with its own threshold', () => {
    render(<GateResult gate={failingGate} />)
    expect(screen.getByText('SOURCE RMSE')).toBeInTheDocument()
    expect(screen.getByText('<1.00 px')).toBeInTheDocument()
  })
})
