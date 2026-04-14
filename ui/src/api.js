const API_BASE = '/api'

async function request(path, options = {}, timeoutMs = 600_000) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    })

    if (!response.ok) {
      const detail = await response.text()
      throw new Error(`HTTP ${response.status}: ${detail}`)
    }

    if (response.status === 204) {
      return null
    }

    return await response.json()
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out. Please retry.')
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}

function loadModelConfig() {
  try {
    const raw = localStorage.getItem('desysflow_model')
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function getConfig() {
  return request('/config', { method: 'GET', headers: {} }, 10_000)
}

export function checkHealth() {
  return request('/health', { method: 'GET', headers: {} }, 20_000)
}

export function checkModelConnection(modelConfig = {}) {
  return request('/health/llm-check', {
    method: 'POST',
    body: JSON.stringify({
      provider: modelConfig?.provider || '',
      model: modelConfig?.model || '',
      api_key: modelConfig?.apiKey || '',
    }),
  }, 25_000)
}

export function listConversations() {
  return request('/conversations', { method: 'GET', headers: {} }, 20_000)
}

export function getConversation(sessionId) {
  return request(`/conversations/${sessionId}`, { method: 'GET', headers: {} }, 20_000)
}

export function deleteConversation(sessionId) {
  return request(`/conversations/${sessionId}`, { method: 'DELETE', headers: {} }, 20_000)
}

export function startDesignAsync(
  prompt,
  preferredLanguage = 'Python',
  diagramStyle = 'balanced',
  role = 'DevOps',
  reportStyle = 'balanced',
  cloudTarget = 'local',
  searchMode = 'auto',
) {
  const model = loadModelConfig()
  return request('/design/async', {
    method: 'POST',
    body: JSON.stringify({
      input: prompt,
      preferred_language: preferredLanguage,
      diagram_style: diagramStyle,
      role,
      report_style: reportStyle,
      cloud_target: cloudTarget,
      search_mode: searchMode,
      provider: model?.provider || '',
      model: model?.model || '',
      api_key: model?.apiKey || '',
    }),
  })
}

export function startFollowUpAsync(
  sessionId,
  message,
  preferredLanguage = 'Python',
  diagramStyle = 'balanced',
  preserveCoreDiagram = true,
  role = 'DevOps',
  reportStyle = 'balanced',
  cloudTarget = 'local',
  searchMode = 'auto',
) {
  const model = loadModelConfig()
  return request('/design/followup/async', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      message,
      preferred_language: preferredLanguage,
      diagram_style: diagramStyle,
      preserve_core_diagram: preserveCoreDiagram,
      role,
      report_style: reportStyle,
      cloud_target: cloudTarget,
      search_mode: searchMode,
      provider: model?.provider || '',
      model: model?.model || '',
      api_key: model?.apiKey || '',
    }),
  })
}

export function getOperationStatus(operationId) {
  return request(`/operations/${operationId}`, { method: 'GET', headers: {} }, 20_000)
}

export function cancelOperation(operationId) {
  return request(`/operations/${operationId}/cancel`, { method: 'POST', headers: {} }, 20_000)
}
