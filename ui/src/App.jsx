import { useState, useEffect, useRef, useCallback } from 'react'
import {
  cancelOperation,
  checkModelConnection,
  deleteConversation,
  getConfig,
  getConversation,
  getOperationStatus,
  listConversations,
  startDesignAsync,
  startFollowUpAsync,
} from './api'
import LoadingState from './components/LoadingState'
import MermaidDiagram from './components/MermaidDiagram'
import HLDReport from './components/HLDReport'
import LLDReport from './components/LLDReport'
import MessageContent from './components/MessageContent'
import TechDocument from './components/TechDocument'
import NonTechnicalDoc from './components/NonTechnicalDoc'
import TechStack from './components/TechStack'
import CloudInfra from './components/CloudInfra'

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function buildArtifacts(source) {
  const p = source?.latest_result || source?.payload?.latest_result || source?.payload || source || {}
  return {
    mermaidCode: p.mermaid_code || '',
    technicalDoc: p.system_design_doc || {},
    nonTechnicalDoc: p.non_technical_doc || {},
    hldDoc: p.hld_report || p.hld_doc || {},
    lldDoc: p.lld_report || p.lld_doc || {},
    techStack: p.tech_stack || {},
    cloudInfra: p.cloud_infrastructure || {},
    warnings: p.warnings || [],
  }
}

function buildRequestPrompt({ prompt, role, preferredLanguage, diagramStyle, reportStyle, cloudTarget, searchMode }) {
  return [
    prompt,
    '',
    'Workspace preferences:',
    `- Role: ${role}`,
    `- Preferred implementation language: ${preferredLanguage}`,
    `- Diagram style: ${diagramStyle}`,
    `- Report depth: ${reportStyle}`,
    `- Cloud target: ${cloudTarget}`,
    `- Web search mode: ${searchMode}`,
    '- Product rule: return one clean technical document and one non-technical project brief.',
  ].join('\n')
}

function formatFieldLabel(key) {
  return String(key || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function StructuredDataView({ title, doc }) {
  if (!doc || typeof doc !== 'object' || Object.keys(doc).length === 0) {
    return null
  }

  const renderValue = (val) => {
    if (val == null || val === '') return <span className="structured__muted">Not provided</span>

    if (Array.isArray(val)) {
      if (val.length === 0) return <span className="structured__muted">Not provided</span>
      if (val.every((item) => typeof item !== 'object' || item === null)) {
        return (
          <ul className="structured__list">
            {val.map((item, idx) => (
              <li key={idx}>{String(item)}</li>
            ))}
          </ul>
        )
      }
      return (
        <div className="structured__stack">
          {val.map((item, idx) => (
            <pre key={idx} className="structured__json">
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
        </div>
      )
    }

    if (typeof val === 'object') {
      const rows = Object.entries(val)
      if (rows.length === 0) return <span className="structured__muted">Not provided</span>
      return (
        <div className="structured__kv">
          {rows.map(([k, v]) => (
            <div key={k} className="structured__kv-row">
              <span className="structured__kv-key">{formatFieldLabel(k)}</span>
              <div className="structured__kv-value">{renderValue(v)}</div>
            </div>
          ))}
        </div>
      )
    }

    return <span>{String(val)}</span>
  }

  return (
    <div className="artifact-section fade-in">
      <div className="artifact-section__title">{title}</div>
      {Object.entries(doc).map(([key, val]) => (
        <div key={key} className="artifact-section__content structured">
          <h4 className="structured__title">{formatFieldLabel(key)}</h4>
          <div className="structured__body">{renderValue(val)}</div>
        </div>
      ))}
    </div>
  )
}

// ── Artifact Renderers ────────────────────────────────────────────────────────

function ArtifactDiagram({ code }) {
  if (!code) return <div className="empty"><div className="empty__title">No diagram yet</div></div>
  return <MermaidDiagram code={code} />
}

function ArtifactTechDoc({ doc, hldDoc, lldDoc, techStack, cloudInfra }) {
  const hasHld = hldDoc && Object.keys(hldDoc).length > 0
  const hasLld = lldDoc && Object.keys(lldDoc).length > 0
  const hasDoc = doc && Object.keys(doc).length > 0
  const hasStack = techStack && Object.keys(techStack).length > 0
  const hasCloud = cloudInfra && Object.keys(cloudInfra).length > 0

  if (!hasHld && !hasLld && !hasDoc && !hasStack && !hasCloud) {
    return <div className="empty"><div className="empty__title">No technical doc yet</div></div>
  }

  return (
    <div className="artifact-section fade-in">
      {hasDoc && <TechDocument data={doc} />}
      {hasStack && <TechStack data={techStack} />}
      {hasCloud && <CloudInfra data={cloudInfra} />}
      {hasHld && <HLDReport data={hldDoc} />}
      {hasLld && <LLDReport data={lldDoc} />}
      {!hasDoc && !hasHld && !hasLld && <StructuredDataView title="Technical Document" doc={doc} />}
    </div>
  )
}

function ArtifactNonTechDoc({ doc }) {
  if (!doc || Object.keys(doc).length === 0) return <div className="empty"><div className="empty__title">No non-technical doc yet</div></div>
  return <NonTechnicalDoc data={doc} />
}

// ── Setup / Model Modal ───────────────────────────────────────────────────────

const FALLBACK_CONFIG = {
  roles: ['MLOps / AIOps', 'DevOps', 'DevSecOps', 'Principal Architect'],
  languages: ['Python', 'TypeScript', 'Go', 'Java', 'Rust'],
  styles: ['minimal', 'balanced', 'detailed'],
  clouds: ['local', 'aws', 'gcp', 'azure', 'hybrid'],
  search_modes: ['auto', 'on', 'off'],
  providers: [
    { id: 'openai',    label: 'GPT-lover',    desc: 'OpenAI GPT models',      default_model: 'gpt-4o' },
    { id: 'anthropic', label: 'Claude-lover',  desc: 'Anthropic Claude models', default_model: 'claude-sonnet-4-20250514' },
    { id: 'ollama',    label: 'Ollama-lover',  desc: 'Local models via Ollama', default_model: 'gpt-oss:20b-cloud' },
  ],
  defaults: { role: 'DevOps', language: 'Python', style: 'balanced', cloud: 'local', search_mode: 'auto' },
}

function SetupModal({ saved, onSave, config }) {
  const providers = config.providers || FALLBACK_CONFIG.providers
  const [provider, setProvider] = useState(saved?.provider || '')
  const [model, setModel]       = useState(saved?.model || '')
  const [apiKey, setApiKey]     = useState(saved?.apiKey || '')
  const [status, setStatus]     = useState('')
  const [error, setError]       = useState('')

  const defaultModel = (p) => {
    const match = providers.find((item) => item.id === p)
    return match?.default_model || ''
  }

  const handleProviderSelect = (id) => {
    setProvider(id)
    setModel(defaultModel(id))
    setError('')
    setStatus('')
  }

  const handleCheckStatus = async () => {
    setStatus('checking')
    setError('')
    try {
      const d = await checkModelConnection({
        provider,
        model,
        apiKey,
      })
      if (d?.status === 'available') {
        setStatus('ok')
      } else {
        setStatus('err')
        setError(d?.message || 'Model not reachable. Check provider settings.')
      }
    } catch {
      setStatus('err')
      setError('Could not connect. Verify the provider is running and keys are correct.')
    }
  }

  const handleSave = () => {
    if (!provider)                             { setError('Select a provider.'); return }
    if (provider !== 'ollama' && !apiKey.trim()) { setError('API key required for GPT/Claude.'); return }
    if (!model.trim())                        { setError('Model name is required.'); return }
    setError('')
    onSave({ provider, model: model.trim(), apiKey: apiKey.trim() })
  }

  return (
    <div className="modal-overlay">
      <div className="modal fade-in">
        <div>
          <div className="modal__title">Configure your AI model</div>
          <div className="modal__subtitle">Saved in browser localStorage and sent only to your local backend per request. Avoid shared/public machines.</div>
        </div>

        <div className="modal__options">
          {providers.map((opt) => (
            <button
              key={opt.id}
              className={`modal__option${provider === opt.id ? ' modal__option--selected' : ''}`}
              onClick={() => handleProviderSelect(opt.id)}
              type="button"
            >
              <span>
                <div className="modal__option-label">{opt.label}</div>
                <div className="modal__option-desc">{opt.desc}</div>
              </span>
            </button>
          ))}
        </div>

        {provider && (
          <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="modal__field">
              <label className="modal__label">Model name</label>
              <input
                className="modal__input"
                placeholder={defaultModel(provider)}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </div>
            {provider !== 'ollama' && (
              <div className="modal__field">
                <label className="modal__label">API key</label>
                <input
                  className="modal__input"
                  type="password"
                  placeholder={`Your ${provider} API key`}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </div>
            )}
            <button
              className={`modal__btn modal__btn--check ${status === 'ok' ? 'modal__btn--success' : status === 'err' ? 'modal__btn--danger' : ''}`}
              onClick={handleCheckStatus}
              disabled={status === 'checking'}
              type="button"
            >
              {status === 'checking' ? 'Checking...' : status === 'ok' ? 'Connected' : status === 'err' ? 'Retry check' : 'Check status'}
            </button>
          </div>
        )}

        {error && <div className="modal__error">{error}</div>}

        <div className="modal__actions">
          <button className="modal__btn modal__btn--primary" onClick={handleSave} type="button">
            Save &amp; connect
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [appConfig, setAppConfig]             = useState(FALLBACK_CONFIG)
  const [modelConfig, setModelConfig]         = useState(null)
  const [modelStatus, setModelStatus]         = useState('checking')
  const [liveModel, setLiveModel]             = useState(null)
  const [sidebarOpen, setSidebarOpen]         = useState(true)
  const [sessions, setSessions]               = useState([])

  const [sessionId, setSessionId]             = useState('')
  const [chatHistory, setChatHistory]          = useState([])
  const [artifacts, setArtifacts]             = useState(buildArtifacts(null))
  const [activeArtifact, setActiveArtifact]   = useState('diagram')

  const [prompt, setPrompt]                   = useState('')
  const [role, setRole]                       = useState('DevOps')
  const [preferredLanguage, setPreferredLanguage] = useState('Python')
  const [diagramStyle, setDiagramStyle]       = useState('balanced')
  const [reportStyle, setReportStyle]         = useState('balanced')
  const [cloudTarget, setCloudTarget]         = useState('local')
  const [searchMode, setSearchMode]           = useState('auto')

  const [loading, setLoading]                = useState(false)
  const [loadingMode, setLoadingMode]          = useState('design')
  const [operationId, setOperationId]          = useState('')
  const [operation, setOperation]               = useState(null)
  const [error, setError]                     = useState('')

  const textareaRef       = useRef(null)
  const chatScrollRef     = useRef(null)
  const artifactScrollRef = useRef(null)
  const nearChatBottomRef = useRef(true)

  // ── Init ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const raw = localStorage.getItem('desysflow_model')
    if (raw) {
      try { setModelConfig(JSON.parse(raw)) }
      catch (_) { setModelStatus('needs_setup') }
    } else {
      setModelStatus('needs_setup')
    }

    getConfig()
      .then((cfg) => {
        if (cfg && typeof cfg === 'object') {
          setAppConfig(cfg)
          const d = cfg.defaults || {}
          if (d.role) setRole(d.role)
          if (d.language) setPreferredLanguage(d.language)
          if (d.style) setDiagramStyle(d.style)
          if (d.cloud) setCloudTarget(d.cloud)
          if (d.search_mode) setSearchMode(d.search_mode)
        }
      })
      .catch(() => {})

    listConversations()
      .then((d) => setSessions(d?.conversations || []))
      .catch(() => {})
  }, [])

  // ── Model health check ────────────────────────────────────────────────────
  useEffect(() => {
    if (!modelConfig) return
    setModelStatus('checking')
    checkModelConnection(modelConfig)
      .then((d) => {
        setModelStatus(d?.status === 'available' ? 'ok' : 'err')
        setLiveModel({ provider: modelConfig.provider, model: modelConfig.model })
      })
      .catch(() => setModelStatus('err'))
  }, [modelConfig])

  // ── Auto-scroll chat ─────────────────────────────────────────────────────
  const handleChatScroll = useCallback(() => {
    if (!chatScrollRef.current) return
    const { scrollTop, clientHeight, scrollHeight } = chatScrollRef.current
    nearChatBottomRef.current = scrollHeight - (scrollTop + clientHeight) < 88
  }, [])

  useEffect(() => {
    if (!chatScrollRef.current) return
    if (nearChatBottomRef.current || loading) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
    }
  }, [chatHistory, loading])

  // ── Operation polling ────────────────────────────────────────────────────
  useEffect(() => {
    if (!operationId) return
    let cancelled = false, busy = false
    const poll = async () => {
      if (cancelled || busy) return
      busy = true
      try {
        const status = await getOperationStatus(operationId)
        if (cancelled) return
        setOperation(status)
        if (status.status === 'completed' && status.result) {
          const r = status.result
          setSessionId(r.session_id || sessionId)
          setChatHistory(r.chat_history || [])
          setArtifacts(buildArtifacts(r))
          setActiveArtifact('diagram')
          setLoading(false)
          setOperationId('')
          setOperation(null)
          listConversations().then((d) => setSessions(d?.conversations || [])).catch(() => {})
        } else if (status.status === 'cancelled') {
          setError(status.error || 'Generation interrupted.')
          setLoading(false)
          setOperationId('')
          setOperation(null)
        } else if (status.status === 'failed') {
          setError(status.error || 'Generation failed.')
          setLoading(false)
          setOperationId('')
          setOperation(null)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e.message || 'Polling failed.')
          setLoading(false)
          setOperationId('')
          setOperation(null)
        }
      } finally { busy = false }
    }
    poll()
    const timer = setInterval(poll, 900)
    return () => { cancelled = true; clearInterval(timer) }
  }, [operationId, sessionId])

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleModelSave = ({ provider, model, apiKey }) => {
    localStorage.setItem('desysflow_model', JSON.stringify({ provider, model, apiKey }))
    setModelConfig({ provider, model, apiKey })
    setModelStatus('checking')
  }

  const handleNewChat = () => {
    setSessionId(''); setChatHistory([]); setArtifacts(buildArtifacts(null))
    setActiveArtifact('diagram'); setError(''); setOperationId(''); setOperation(null)
    setLoading(false); setPrompt('')
    if (window.innerWidth <= 900) setSidebarOpen(false)
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleLoadSession = async (sid) => {
    if (!sid || loading) return
    setError('')
    try {
      const detail = await getConversation(sid)
      const p = detail?.payload || {}
      setSessionId(detail.session_id || sid)
      setChatHistory(detail.chat_history || [])
      setPreferredLanguage(p.preferred_language || 'Python')
      setArtifacts(buildArtifacts(p))
      setActiveArtifact('diagram')
      if (window.innerWidth <= 900) setSidebarOpen(false)
    } catch (e) {
      setError(e.message || 'Failed to load session.')
    }
  }

  const handleDeleteSession = async (sid) => {
    try {
      await deleteConversation(sid)
      if (sid === sessionId) handleNewChat()
      setSessions((prev) => prev.filter((s) => s.session_id !== sid))
    } catch (e) {
      setError(e.message || 'Failed to delete session.')
    }
  }

  const handleTextareaInput = (e) => {
    setPrompt(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`
  }

  const handleSubmit = async () => {
    const trimmed = prompt.trim()
    if (!trimmed || loading) return
    if (modelStatus === 'needs_setup') { setError('Configure your model first.'); return }

    setError(''); setLoading(true); setLoadingMode(sessionId ? 'followup' : 'design')
    const requestPrompt = buildRequestPrompt({ prompt: trimmed, role, preferredLanguage, diagramStyle, reportStyle, cloudTarget, searchMode })

    try {
      const op = sessionId
        ? await startFollowUpAsync(
            sessionId,
            requestPrompt,
            preferredLanguage,
            diagramStyle,
            true,
            role,
            reportStyle,
            cloudTarget,
            searchMode,
          )
        : await startDesignAsync(
            requestPrompt,
            preferredLanguage,
            diagramStyle,
            role,
            reportStyle,
            cloudTarget,
            searchMode,
          )
      setOperationId(op.operation_id || '')
      setPrompt('')
      if (textareaRef.current) textareaRef.current.style.height = 'auto'
    } catch (e) {
      setError(e.message || 'Request failed.')
      setLoading(false)
    }
  }

  const handleInterrupt = async () => {
    if (!operationId || !loading) return
    const opId = operationId
    setError('')
    try {
      await cancelOperation(opId)
    } catch (e) {
      setError(e.message || 'Failed to interrupt generation.')
    } finally {
      setLoading(false)
      setOperationId('')
      setOperation(null)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const activeSession  = sessions.find((s) => s.session_id === sessionId)
  const hasArtifacts   = Boolean(
    artifacts.mermaidCode ||
    Object.keys(artifacts.technicalDoc || {}).length ||
    Object.keys(artifacts.nonTechnicalDoc || {}).length ||
    Object.keys(artifacts.hldDoc || {}).length ||
    Object.keys(artifacts.lldDoc || {}).length ||
    Object.keys(artifacts.techStack || {}).length ||
    Object.keys(artifacts.cloudInfra || {}).length
  )
  const dotClass = modelStatus === 'ok' ? '' : modelStatus === 'err' ? 'header__dot--err' : 'header__dot--warn'

  const renderArtifact = () => {
    if (activeArtifact === 'technical') {
      return (
        <ArtifactTechDoc
          doc={artifacts.technicalDoc}
          hldDoc={artifacts.hldDoc}
          lldDoc={artifacts.lldDoc}
          techStack={artifacts.techStack}
          cloudInfra={artifacts.cloudInfra}
        />
      )
    }
    if (activeArtifact === 'nontechnical') return <ArtifactNonTechDoc doc={artifacts.nonTechnicalDoc} />
    return <ArtifactDiagram code={artifacts.mermaidCode} />
  }

  return (
    <>
      {modelStatus === 'needs_setup' && <SetupModal saved={modelConfig} onSave={handleModelSave} config={appConfig} />}

      <div className="app">
        {/* ── Header ── */}
        <header className="header">
          <button className="header__menu-btn" onClick={() => setSidebarOpen(!sidebarOpen)} type="button" aria-label="Toggle sidebar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
          </button>
          <div className="header__logo">
            <div className="header__logo-mark">D</div>
            <span className="header__logo-text">DeSysFlow</span>
          </div>
          <div className="header__spacer" />
          {modelConfig && (
            <div className="header__status">
              <div className={`header__dot ${dotClass}`} />
              <span className="header__status-text">
                {liveModel
                  ? `${liveModel.provider} / ${liveModel.model}`
                  : `${modelConfig.provider} / ${modelConfig.model}`}
              </span>
            </div>
          )}
          <button className="header__btn" onClick={handleNewChat} type="button">+ New</button>
          <button className="header__btn header__btn--icon" onClick={() => setModelStatus('needs_setup')} type="button" title="Configure model">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
        </header>

        {/* ── Sidebar ── */}
        <aside className={`sidebar${sidebarOpen ? '' : ' sidebar--collapsed'}`}>
          <div className="sidebar__inner">
            <button className="sidebar__new-chat-btn" onClick={handleNewChat} type="button">
              + New Chat
            </button>
            <div className="sidebar__section-label">Sessions</div>
            <div className="session-list">
              {sessions.length === 0 ? (
                <div style={{ fontSize: '.8rem', color: 'var(--muted)', padding: '8px 4px' }}>No sessions yet.</div>
              ) : sessions.map((s) => (
                <button
                  key={s.session_id}
                  className={`session-item${s.session_id === sessionId ? ' session-item--active' : ''}`}
                  onClick={() => handleLoadSession(s.session_id)}
                  type="button"
                >
                  <div className="session-item__title">{s.title || 'Untitled'}</div>
                  <div className="session-item__meta">{formatTime(s.updated_at)}</div>
                </button>
              ))}
            </div>
            <div className="sidebar__footer">
              <div className="sidebar__footer-info">{sessions.length} session{sessions.length !== 1 ? 's' : ''}</div>
            </div>
          </div>
        </aside>
        {sidebarOpen && <button className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} type="button" aria-label="Close sidebar" />}

        {/* ── Main ── */}
        <main className="main">
          <div className="workspace-bar">
            <div className="workspace-bar__title">{activeSession ? activeSession.title || 'Design session' : 'New design'}</div>
            <div className="workspace-bar__spacer" />
            <div className="workspace-bar__meta">{sessionId ? `Session: ${sessionId.slice(0, 8)}…` : 'Fresh design'}</div>
            {sessionId && (
              <button className="header__btn header__btn--danger" onClick={() => handleDeleteSession(sessionId)} type="button">Delete</button>
            )}
          </div>

          {error && (
            <div style={{ padding: '0 16px', flexShrink: 0 }}>
              <div className="notice notice--err">{error}</div>
            </div>
          )}

          <div className="panels">
            {/* Chat */}
            <div className="panel panel--chat">
              <div className="panel__header"><span className="panel__title">Chat</span></div>
              <div className="panel__body" ref={chatScrollRef} onScroll={handleChatScroll}>
                {chatHistory.length === 0 && !loading ? (
                  <div className="empty">
                    <div className="empty__title">Describe your system</div>
                    <div className="empty__hint">Include product goal, users, scale hints, or quality attributes. DesysFlow will produce a complete architecture package.</div>
                  </div>
                ) : chatHistory.filter((m) => m?.content?.trim() && m.role !== 'system').map((m, i) => (
                  <div key={i} className={`msg msg--${m.role === 'user' ? 'user' : 'assistant'} fade-in`}>
                    <div className="msg__bubble"><MessageContent content={m.content} role={m.role} /></div>
                    <div className="msg__time">{formatTime(m.created_at)}</div>
                  </div>
                ))}
                {loading && <LoadingState mode={loadingMode} operation={operation} />}
              </div>
            </div>

            {/* Artifacts */}
            <div className="panel">
              <div className="panel__header"><span className="panel__title">Artifacts</span></div>
              <div className="tab-bar">
                {[['diagram', 'Diagram'], ['technical', 'HLD/LLD'], ['nontechnical', 'Non-Tech']].map(([key, label]) => (
                  <button key={key} className={`tab${activeArtifact === key ? ' tab--active' : ''}`} onClick={() => setActiveArtifact(key)} type="button">{label}</button>
                ))}
              </div>
              <div className="artifact-body" ref={artifactScrollRef}>
                {!hasArtifacts && !loading ? (
                  <div className="empty">
                    <div className="empty__title">Artifacts appear here</div>
                    <div className="empty__hint">Send a message and DesysFlow will generate a complete design package.</div>
                  </div>
                ) : renderArtifact()}
              </div>
            </div>
          </div>

          {/* Controls */}
          <div className="controls">
            <label>Role
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {(appConfig.roles || FALLBACK_CONFIG.roles).map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label>Language
              <select value={preferredLanguage} onChange={(e) => setPreferredLanguage(e.target.value)}>
                {(appConfig.languages || FALLBACK_CONFIG.languages).map((l) => <option key={l}>{l}</option>)}
              </select>
            </label>
            <label>Style
              <select value={diagramStyle} onChange={(e) => setDiagramStyle(e.target.value)}>
                {(appConfig.styles || FALLBACK_CONFIG.styles).map((s) => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
              </select>
            </label>
            <label>Cloud
              <select value={cloudTarget} onChange={(e) => setCloudTarget(e.target.value)}>
                {(appConfig.clouds || FALLBACK_CONFIG.clouds).map((c) => <option key={c} value={c}>{c.toUpperCase()}</option>)}
              </select>
            </label>
            <label>Search
              <select value={searchMode} onChange={(e) => setSearchMode(e.target.value)}>
                {(appConfig.search_modes || FALLBACK_CONFIG.search_modes).map((v) => <option key={v} value={v}>{v.charAt(0).toUpperCase() + v.slice(1)}</option>)}
              </select>
            </label>
          </div>

          {/* Input */}
          <div className="input-area">
            <textarea
              ref={textareaRef}
              className="input-area__textarea"
              placeholder="Describe your product, constraints, users, or system goal… (Enter to send, Shift+Enter for newline)"
              value={prompt}
              onChange={handleTextareaInput}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit() } }}
              rows={1}
            />
            <div className="input-area__actions">
              <button
                className="input-area__send"
                onClick={handleSubmit}
                disabled={!prompt.trim() || loading || modelStatus === 'needs_setup'}
                type="button"
              >
                {loading ? 'Running…' : sessionId ? 'Refine' : 'Generate'}
              </button>
              {loading && (
                <button
                  className="input-area__stop"
                  onClick={handleInterrupt}
                  type="button"
                  title="Interrupt generation"
                  aria-label="Interrupt generation"
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                    <rect x="2" y="2" width="8" height="8" rx="1.5" fill="currentColor" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </main>
      </div>
    </>
  )
}
