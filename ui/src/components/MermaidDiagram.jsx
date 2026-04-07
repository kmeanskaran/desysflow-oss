import { useRef, useEffect, useState } from 'react'
import mermaid from 'mermaid'

// Initialize mermaid with a clean light theme
mermaid.initialize({
    startOnLoad: false,
    theme: 'base',
    securityLevel: 'strict',
    themeVariables: {
        background: '#f7f7f2',
        primaryColor: '#f1efe6',
        primaryTextColor: '#1d232a',
        primaryBorderColor: '#1f6f5f',
        lineColor: '#63707a',
        secondaryColor: '#f7f4ec',
        tertiaryColor: '#ece8de',
        fontFamily: 'IBM Plex Sans, -apple-system, sans-serif',
        fontSize: '14px',
        clusterBkg: '#f6f1e8',
        clusterBorder: '#9ba6af',
        edgeLabelBackground: '#f7f7f2',
        noteBkgColor: '#fffdf7',
        noteTextColor: '#1d232a',
        noteBorderColor: '#9ba6af',
    },
    flowchart: {
        htmlLabels: false,
        curve: 'basis',
        padding: 20,
        nodeSpacing: 50,
        rankSpacing: 60,
    },
})

let renderCounter = 0
let latestRenderToken = 0

function normalizeMermaidInput(rawCode = '') {
    const cleaned = String(rawCode || '')
        .replace(/```mermaid/gi, '```')
        .replace(/```/g, '')
        .trim()

    const flowchartIndex = cleaned.toLowerCase().indexOf('flowchart ')
    if (flowchartIndex >= 0) {
        return cleaned.slice(flowchartIndex).trim()
    }
    return cleaned
}

export default function MermaidDiagram({ code }) {
    const containerRef = useRef(null)
    const viewportRef = useRef(null)
    const dragRef = useRef({ dragging: false, startX: 0, startY: 0, scrollLeft: 0, scrollTop: 0 })
    const [error, setError] = useState(null)
    const [zoom, setZoom] = useState(1)

    const clampZoom = (value) => Math.max(0.6, Math.min(2.2, value))

    const updateZoom = (nextZoom) => {
        setZoom(clampZoom(nextZoom))
    }

    useEffect(() => {
        if (!code || !containerRef.current) return

        const render = async () => {
            const token = ++latestRenderToken
            try {
                setError(null)
                const id = `mermaid-${++renderCounter}`
                const normalizedCode = normalizeMermaidInput(code)
                containerRef.current.innerHTML = ''
                const { svg } = await mermaid.render(id, normalizedCode)
                if (token !== latestRenderToken) return
                if (containerRef.current) {
                    containerRef.current.innerHTML = svg
                    const svgNode = containerRef.current.querySelector('svg')
                    if (svgNode) {
                        svgNode.style.maxWidth = 'none'
                        svgNode.style.height = 'auto'
                        svgNode.style.display = 'block'
                    }
                }
            } catch (err) {
                console.error('Mermaid render error:', err)
                setError('Failed to render diagram. The Mermaid syntax may be invalid.')
            }
        }

        render()
    }, [code])

    useEffect(() => {
        setZoom(1)
        if (viewportRef.current) {
            viewportRef.current.scrollTo({ left: 0, top: 0 })
        }
    }, [code])

    const handleMouseDown = (event) => {
        if (!viewportRef.current) return
        dragRef.current = {
            dragging: true,
            startX: event.clientX,
            startY: event.clientY,
            scrollLeft: viewportRef.current.scrollLeft,
            scrollTop: viewportRef.current.scrollTop,
        }
    }

    const handleMouseMove = (event) => {
        if (!dragRef.current.dragging || !viewportRef.current) return
        const dx = event.clientX - dragRef.current.startX
        const dy = event.clientY - dragRef.current.startY
        viewportRef.current.scrollLeft = dragRef.current.scrollLeft - dx
        viewportRef.current.scrollTop = dragRef.current.scrollTop - dy
    }

    const handleMouseUp = () => {
        dragRef.current.dragging = false
    }

    if (!code) {
        return (
            <div className="diagram-canvas">
                <p className="diagram-canvas__empty">No diagram code available.</p>
            </div>
        )
    }

    return (
            <div className="diagram-canvas fade-in">
            {error && <p className="diagram-canvas__error">{error}</p>}

            <div className="diagram-canvas__toolbar">
                <p className="diagram-canvas__hint">Drag to pan. Use controls to zoom.</p>
                <div className="diagram-canvas__controls">
                    <button type="button" className="btn" onClick={() => updateZoom(zoom - 0.1)}>-</button>
                    <span>{Math.round(zoom * 100)}%</span>
                    <button type="button" className="btn" onClick={() => updateZoom(zoom + 0.1)}>+</button>
                    <button type="button" className="btn" onClick={() => updateZoom(1)}>Reset</button>
                </div>
            </div>

            <div
                className="diagram-canvas__viewport"
                ref={viewportRef}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseUp}
                onMouseUp={handleMouseUp}
            >
                <div
                    className="diagram-canvas__inner"
                    ref={containerRef}
                    style={{ transform: `scale(${zoom})` }}
                />
            </div>
        </div>
    )
}
