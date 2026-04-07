function renderList(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return <p className="doc-empty">No data available.</p>
  }
  return (
    <ul className="doc-list">
      {items.map((item, index) => (
        <li key={index}>{typeof item === 'string' ? item : JSON.stringify(item)}</li>
      ))}
    </ul>
  )
}

export default function TechDocument({ data }) {
  if (!data || Object.keys(data).length === 0) {
    return <p className="doc-empty">No technical document available yet.</p>
  }

  const overview = data.overview || {}
  const architecture = data.architecture || {}
  const implementation = data.implementation || {}
  const platform = data.platform || {}
  const futureImprovements = data.future_improvements || []

  return (
    <div className="doc-view fade-in">
      <section className="doc-section">
        <h4>Summary</h4>
        <p>{overview.summary || 'No summary available.'}</p>
      </section>

      <section className="doc-grid">
        <article className="doc-card">
          <h4>Requirements</h4>
          {Object.keys(overview.requirements || {}).length === 0 ? (
            <p className="doc-empty">No requirements available.</p>
          ) : (
            <dl className="doc-facts">
              {Object.entries(overview.requirements || {}).map(([key, value]) => (
                <div key={key} className="doc-facts__row">
                  <dt>{key.replace(/_/g, ' ')}</dt>
                  <dd>{Array.isArray(value) ? value.join(', ') : String(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </article>

        <article className="doc-card">
          <h4>Capacity</h4>
          {Object.keys(overview.capacity || {}).length === 0 ? (
            <p className="doc-empty">No capacity notes available.</p>
          ) : (
            <dl className="doc-facts">
              {Object.entries(overview.capacity || {}).map(([key, value]) => (
                <div key={key} className="doc-facts__row">
                  <dt>{key.replace(/_/g, ' ')}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </article>
      </section>

      <section className="doc-grid">
        <article className="doc-card">
          <h4>Architecture</h4>
          <p><strong>Scaling:</strong> {architecture.scaling_strategy || 'Not specified.'}</p>
          <p><strong>Availability:</strong> {architecture.availability || 'Not specified.'}</p>
          <h5>Components</h5>
          {renderList((architecture.components || []).map((item) => `${item.name}: ${item.responsibility}`))}
          <h5>Data Flow</h5>
          {renderList(architecture.data_flow || [])}
        </article>

        <article className="doc-card">
          <h4>Implementation</h4>
          <h5>APIs</h5>
          {renderList((implementation.api_endpoints || []).map((item) => `${item.method} ${item.path}: ${item.description}`))}
          <h5>Service Communication</h5>
          {renderList((implementation.service_communication || []).map((item) => `${item.from} -> ${item.to} via ${item.protocol}`))}
          <h5>Security</h5>
          {renderList(implementation.security || [])}
        </article>
      </section>

      <section className="doc-grid">
        <article className="doc-card">
          <h4>Trade-offs</h4>
          {renderList(architecture.trade_offs || [])}
        </article>
        <article className="doc-card">
          <h4>Platform</h4>
          <h5>Tech Stack</h5>
          {Object.keys(platform.tech_stack || {}).length === 0 ? (
            <p className="doc-empty">No platform data available.</p>
          ) : (
            <dl className="doc-facts">
              {Object.entries(platform.tech_stack || {}).map(([key, value]) => (
                <div key={key} className="doc-facts__row">
                  <dt>{key.replace(/_/g, ' ')}</dt>
                  <dd>{Array.isArray(value) ? value.join(', ') : String(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </article>
      </section>

      <section className="doc-section">
        <h4>Future Improvements</h4>
        {renderList(futureImprovements)}
      </section>
    </div>
  )
}
