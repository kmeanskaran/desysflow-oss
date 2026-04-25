import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import MessageContent from './MessageContent'

vi.mock('./MermaidDiagram', () => ({
  default: function MermaidDiagramMock({ code }) {
    return <div data-testid="mermaid-diagram">{code}</div>
  },
}))

describe('MessageContent', () => {
  it('renders user messages as plain text', () => {
    render(<MessageContent role="user" content="plain user text" />)

    expect(screen.getByText('plain user text')).toBeInTheDocument()
  })

  it('renders markdown-like text, code blocks, and mermaid blocks', () => {
    render(
      <MessageContent
        role="assistant"
        content={[
          '# Heading',
          '- item one',
          '```js',
          'const x = 1',
          '```',
          '```mermaid',
          'flowchart TD',
          'A --> B',
          '```',
        ].join('\n')}
      />
    )

    expect(screen.getByRole('heading', { name: 'Heading' })).toBeInTheDocument()
    expect(screen.getByText('item one')).toBeInTheDocument()
    expect(screen.getByText('const x = 1')).toBeInTheDocument()
    expect(screen.getByTestId('mermaid-diagram')).toHaveTextContent('flowchart TD')
  })
})
