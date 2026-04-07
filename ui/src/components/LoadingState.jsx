import { useEffect, useState } from 'react'

const PIPELINES = {
  design: {
    title: 'Generating design package',
    subtitle: 'Running parallel sub-agents, then a lightweight reviewer loop',
    steps: [
      { key: 'scope', label: 'Reading prompt and constraints', icon: '1' },
      { key: 'extract', label: 'Extracting requirements in parallel', icon: '2' },
      { key: 'draft', label: 'Drafting architecture, diagram, and reports', icon: '3' },
      { key: 'review', label: 'Reviewer loop improving consistency', icon: '4' },
      { key: 'package', label: 'Packaging final artifacts', icon: '5' },
    ],
  },
  followup: {
    title: 'Refining active design',
    subtitle: 'Applying the new request to the current session and regenerating outputs',
    steps: [
      { key: 'context', label: 'Loading current design context', icon: '1' },
      { key: 'update', label: 'Updating requirements and trade-offs', icon: '2' },
      { key: 'draft', label: 'Refreshing architecture and reports', icon: '3' },
      { key: 'review', label: 'Running reviewer loop', icon: '4' },
      { key: 'package', label: 'Returning updated artifacts', icon: '5' },
    ],
  },
}

export default function LoadingState({ mode = 'design', operation = null }) {
  const pipeline = PIPELINES[mode] || PIPELINES.design
  const serverSteps = Array.isArray(operation?.steps) && operation.steps.length > 0
    ? operation.steps.map((item, index) => ({
        key: String(item.key || index),
        label: String(item.label || item.key || ''),
        icon: String(index + 1),
      }))
    : null
  const steps = serverSteps || pipeline.steps
  const [activeStep, setActiveStep] = useState(0)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    setActiveStep(0)
    setElapsed(0)
  }, [mode, operation?.operation_id])

  useEffect(() => {
    if (!operation || !Array.isArray(steps) || steps.length === 0) return
    const index = Number(operation.current_step_index || 0)
    if (Number.isFinite(index) && index >= 0) {
      setActiveStep(Math.min(index, steps.length - 1))
    }
  }, [operation, steps])

  useEffect(() => {
    if (serverSteps) return undefined
    const interval = setInterval(() => {
      setActiveStep((prev) => (prev < steps.length - 1 ? prev + 1 : prev))
    }, 2200)
    return () => clearInterval(interval)
  }, [steps.length, serverSteps])

  useEffect(() => {
    const timer = setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  const formatTime = (seconds) => {
    const minutes = Math.floor(seconds / 60)
    const remaining = seconds % 60
    return `${minutes}:${remaining.toString().padStart(2, '0')}`
  }

  const progressPercent = Number(operation?.progress_percent)
  const progress = Number.isFinite(progressPercent)
    ? Math.max(0, Math.min(100, progressPercent))
    : Math.round(((activeStep + 1) / Math.max(steps.length, 1)) * 100)

  return (
    <div className="loading fade-in">
      <div className="loading__header">
        <div>
          <p className="loading__title">{pipeline.title}</p>
          <p className="loading__subtitle">{pipeline.subtitle}</p>
        </div>
        <div className="loading__meta">
          <span className="loading__elapsed">Elapsed {formatTime(elapsed)}</span>
          <span className="loading__percent">{progress}%</span>
        </div>
      </div>

      <div className="loading__progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100">
        <div className="loading__progress-fill" style={{ width: `${progress}%` }} />
      </div>

      <div className="loading__pipeline">
        {steps.map((step, index) => {
          let status = 'pending'
          if (index < activeStep) status = 'done'
          else if (index === activeStep) status = 'active'

          return (
            <div key={step.key} className={`loading__step loading__step--${status}`}>
              <div className="loading__step-bullet">{status === 'done' ? '✓' : step.icon}</div>
              <span className="loading__step-label">{step.label}</span>
              <span className={`loading__step-status loading__step-status--${status}`}>
                {status === 'done' ? 'Done' : status === 'active' ? 'Running' : 'Queued'}
              </span>
            </div>
          )
        })}
      </div>

      {operation?.current_step_label && (
        <p className="loading__current-step">Active step: {operation.current_step_label}</p>
      )}
    </div>
  )
}
