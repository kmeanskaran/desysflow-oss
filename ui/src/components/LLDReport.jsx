export default function LLDReport({ data }) {
    if (!data || Object.keys(data).length === 0) {
        return (
            <div className="report">
                <p className="report__empty">No LLD report available.</p>
            </div>
        )
    }

    return (
        <div className="report fade-in">
            <div className="section-header">
                <div className="section-header__icon">LLD</div>
                <div className="section-header__text">
                    <h3>Low-Level Design (LLD)</h3>
                    <p>For developers implementing the system</p>
                </div>
            </div>

            {/* API Endpoints */}
            {data.api_endpoints && data.api_endpoints.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">API Endpoints</h4>
                    <div className="report__table-wrap">
                        <table className="report__table">
                            <thead>
                                <tr>
                                    <th>Method</th>
                                    <th>Path</th>
                                    <th>Description</th>
                                    <th>Request</th>
                                    <th>Response</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.api_endpoints.map((ep, i) => (
                                    <tr key={i}>
                                        <td><span className={`method-badge method-badge--${(ep.method || '').toLowerCase()}`}>{ep.method}</span></td>
                                        <td className="report__table-mono">{ep.path}</td>
                                        <td>{ep.description}</td>
                                        <td className="report__table-mono">{ep.request_body || '-'}</td>
                                        <td className="report__table-mono">{ep.response_body || '-'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Database Schemas */}
            {data.database_schemas && data.database_schemas.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Database Schemas</h4>
                    {data.database_schemas.map((db, i) => (
                        <div key={i} className="report__sub-card">
                            <div className="report__sub-card-header">
                                <span className="report__sub-card-name">{db.name}</span>
                                <span className="tag tag--small">{db.type}</span>
                            </div>
                            {db.tables_or_collections && db.tables_or_collections.map((tbl, j) => (
                                <div key={j} className="report__db-table">
                                    <p className="report__db-table-name">{tbl.name}</p>
                                    <div className="report__db-fields">
                                        {(tbl.fields || []).map((f, k) => (
                                            <code key={k} className="report__field">{f}</code>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    ))}
                </div>
            )}

            {/* Service Communication */}
            {data.service_communication && data.service_communication.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Service Communication</h4>
                    <div className="report__table-wrap">
                        <table className="report__table">
                            <thead>
                                <tr>
                                    <th>From</th>
                                    <th>To</th>
                                    <th>Protocol</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.service_communication.map((sc, i) => (
                                    <tr key={i}>
                                        <td className="report__table-name">{sc.from}</td>
                                        <td className="report__table-name">{sc.to}</td>
                                        <td><span className="tag tag--small">{sc.protocol}</span></td>
                                        <td>{sc.description}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Caching Strategy */}
            {data.caching_strategy && data.caching_strategy.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Caching Strategy</h4>
                    <div className="report__table-wrap">
                        <table className="report__table">
                            <thead>
                                <tr>
                                    <th>Layer</th>
                                    <th>Technology</th>
                                    <th>TTL</th>
                                    <th>Invalidation</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.caching_strategy.map((cs, i) => (
                                    <tr key={i}>
                                        <td>{cs.layer}</td>
                                        <td><span className="tag tag--small">{cs.technology}</span></td>
                                        <td className="report__table-mono">{cs.ttl}</td>
                                        <td>{cs.invalidation_strategy}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Error Handling */}
            {data.error_handling && data.error_handling.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Error Handling</h4>
                    {data.error_handling.map((eh, i) => (
                        <div key={i} className="report__sub-card">
                            <p className="report__sub-card-name">{eh.scenario}</p>
                            <p className="report__sub-card-detail"><strong>Strategy:</strong> {eh.strategy}</p>
                            <p className="report__sub-card-detail"><strong>Fallback:</strong> {eh.fallback}</p>
                        </div>
                    ))}
                </div>
            )}

            {/* Deployment */}
            {data.deployment && Object.keys(data.deployment).length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Deployment</h4>
                    <div className="report__metrics">
                        {Object.entries(data.deployment).map(([key, val]) => (
                            <div key={key} className="metric-card">
                                <span className="metric-card__label">
                                    {key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                                </span>
                                <span className="metric-card__value">
                                    {Array.isArray(val) ? val.join(', ') : String(val)}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Security */}
            {data.security && data.security.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Security</h4>
                    <ul className="report__list">
                        {data.security.map((s, i) => (
                            <li key={i}>{s}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}
