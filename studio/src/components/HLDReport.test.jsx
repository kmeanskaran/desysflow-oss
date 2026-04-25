import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import HLDReport from './HLDReport'

describe('HLDReport', () => {
  it('renders an empty state when no report is available', () => {
    render(<HLDReport data={{}} />)

    expect(screen.getByText('No HLD report available.')).toBeInTheDocument()
  })

  it('renders core HLD sections from structured data', () => {
    render(
      <HLDReport
        data={{
          system_overview: 'Professional architecture summary.',
          components: [
            { name: 'API Gateway', type: 'gateway', responsibility: 'Routes inbound traffic.' },
          ],
          data_flow: ['Client request enters the gateway.', 'Gateway forwards to app service.'],
          scaling_strategy: 'Horizontal autoscaling.',
          availability: 'Multi-instance with health checks.',
          trade_offs: ['Managed services reduce ops overhead.'],
          estimated_capacity: {
            requests_per_second: '500 RPS',
          },
        }}
      />
    )

    expect(screen.getByText('High-Level Design (HLD)')).toBeInTheDocument()
    expect(screen.getByText('Professional architecture summary.')).toBeInTheDocument()
    expect(screen.getByText('API Gateway')).toBeInTheDocument()
    expect(screen.getByText('Horizontal autoscaling.')).toBeInTheDocument()
    expect(screen.getByText('Managed services reduce ops overhead.')).toBeInTheDocument()
    expect(screen.getByText('500 RPS')).toBeInTheDocument()
  })
})
