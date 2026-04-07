import MermaidDiagram from './MermaidDiagram'

function inlineFormat(text) {
  const safe = text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  return safe
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
}

function TextBlock({ text }) {
  const rows = text
    .split('\n')
    .map((line) => line.trimEnd())
    .filter((line) => line.trim() !== '')

  const nodes = []
  let i = 0

  while (i < rows.length) {
    const line = rows[i]
    if (/^#{1,3}\s+/.test(line)) {
      const level = line.match(/^#{1,3}/)[0].length
      const label = line.replace(/^#{1,3}\s+/, '')
      const Tag = level === 1 ? 'h4' : level === 2 ? 'h5' : 'h6'
      nodes.push(<Tag key={`h-${i}`} dangerouslySetInnerHTML={{ __html: inlineFormat(label) }} />)
      i += 1
      continue
    }

    if (/^[-*]\s+/.test(line)) {
      const items = []
      while (i < rows.length && /^[-*]\s+/.test(rows[i])) {
        items.push(rows[i].replace(/^[-*]\s+/, ''))
        i += 1
      }
      nodes.push(
        <ul key={`ul-${i}`}>
          {items.map((item, idx) => (
            <li key={`uli-${idx}`} dangerouslySetInnerHTML={{ __html: inlineFormat(item) }} />
          ))}
        </ul>
      )
      continue
    }

    if (/^\d+\.\s+/.test(line)) {
      const items = []
      while (i < rows.length && /^\d+\.\s+/.test(rows[i])) {
        items.push(rows[i].replace(/^\d+\.\s+/, ''))
        i += 1
      }
      nodes.push(
        <ol key={`ol-${i}`}>
          {items.map((item, idx) => (
            <li key={`oli-${idx}`} dangerouslySetInnerHTML={{ __html: inlineFormat(item) }} />
          ))}
        </ol>
      )
      continue
    }

    if (/^>\s+/.test(line)) {
      nodes.push(
        <blockquote
          key={`q-${i}`}
          dangerouslySetInnerHTML={{ __html: inlineFormat(line.replace(/^>\s+/, '')) }}
        />
      )
      i += 1
      continue
    }

    nodes.push(<p key={`p-${i}`} dangerouslySetInnerHTML={{ __html: inlineFormat(line) }} />)
    i += 1
  }

  return <div className="msg-md">{nodes}</div>
}

export default function MessageContent({ content = '', role = 'assistant' }) {
  const text = String(content || '')
  const mermaidBlock = /```mermaid\s*([\s\S]*?)```/gi
  const codeBlock = /```(\w+)?\s*([\s\S]*?)```/gi

  // Users are rendered as plain text bubbles for readability.
  if (role === 'user') return <span>{text}</span>

  const blocks = []
  let index = 0
  let match

  while ((match = mermaidBlock.exec(text)) !== null) {
    if (match.index > index) {
      blocks.push({ type: 'text', value: text.slice(index, match.index) })
    }
    blocks.push({ type: 'mermaid', value: match[1].trim() })
    index = mermaidBlock.lastIndex
  }
  if (index < text.length) blocks.push({ type: 'text', value: text.slice(index) })

  const withCodeFallback = []
  blocks.forEach((block) => {
    if (block.type !== 'text') {
      withCodeFallback.push(block)
      return
    }
    let cursor = 0
    let codeMatch
    while ((codeMatch = codeBlock.exec(block.value)) !== null) {
      if (codeMatch.index > cursor) {
        withCodeFallback.push({ type: 'text', value: block.value.slice(cursor, codeMatch.index) })
      }
      withCodeFallback.push({ type: 'code', lang: (codeMatch[1] || '').toLowerCase(), value: codeMatch[2].trim() })
      cursor = codeBlock.lastIndex
    }
    if (cursor < block.value.length) {
      withCodeFallback.push({ type: 'text', value: block.value.slice(cursor) })
    }
    codeBlock.lastIndex = 0
  })
  mermaidBlock.lastIndex = 0

  return (
    <>
      {withCodeFallback
        .filter((b) => (b.value || '').trim().length > 0)
        .map((block, idx) => {
          if (block.type === 'mermaid') {
            return (
              <div key={`m-${idx}`} className="msg-mermaid">
                <MermaidDiagram code={block.value} />
              </div>
            )
          }
          if (block.type === 'code') {
            return (
              <pre key={`c-${idx}`} className="msg-code">
                <code>{block.value}</code>
              </pre>
            )
          }
          return <TextBlock key={`t-${idx}`} text={block.value} />
        })}
    </>
  )
}
