export default function HLDReport({ data }) {
    if (!data || Object.keys(data).length === 0) {
        return (
            <div className="report">
                <p className="report__empty">No HLD report available.</p>
            </div>
        )
    }

    return (
        <div className="report fade-in">
            <div className="section-header">
                <div className="section-header__icon">HLD</div>
                <div className="section-header__text">
                    <h3>High-Level Design (HLD)</h3>
                    <p>For product engineers, architects, and engineering managers</p>
                </div>
            </div>

            {/* System Overview */}
            {data.system_overview && (
                <div className="report__block">
                    <h4 className="report__block-title">System Overview</h4>
                    <p className="report__block-text">{data.system_overview}</p>
                </div>
            )}

            {/* Components */}
            {data.components && data.components.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Components</h4>
                    <div className="report__table-wrap">
                        <table className="report__table">
                            <thead>
                                <tr>
                                    <th>Component</th>
                                    <th>Type</th>
                                    <th>Responsibility</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.components.map((c, i) => (
                                    <tr key={i}>
                                        <td className="report__table-name">{c.name}</td>
                                        <td><span className="tag tag--small">{c.type}</span></td>
                                        <td>{c.responsibility}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Data Flow */}
            {data.data_flow && data.data_flow.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Data Flow</h4>
                    <ol className="report__ordered-list">
                        {data.data_flow.map((step, i) => (
                            <li key={i}>{step}</li>
                        ))}
                    </ol>
                </div>
            )}

            {/* Scaling Strategy */}
            {data.scaling_strategy && (
                <div className="report__block">
                    <h4 className="report__block-title">Scaling Strategy</h4>
                    <p className="report__block-text">{data.scaling_strategy}</p>
                </div>
            )}

            {/* Availability */}
            {data.availability && (
                <div className="report__block">
                    <h4 className="report__block-title">Availability and DR</h4>
                    <p className="report__block-text">{data.availability}</p>
                </div>
            )}

            {/* Trade-offs */}
            {data.trade_offs && data.trade_offs.length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Trade-offs</h4>
                    <ul className="report__list">
                        {data.trade_offs.map((t, i) => (
                            <li key={i}>{t}</li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Estimated Capacity */}
            {data.estimated_capacity && Object.keys(data.estimated_capacity).length > 0 && (
                <div className="report__block">
                    <h4 className="report__block-title">Estimated Capacity</h4>
                    <div className="report__metrics">
                        {Object.entries(data.estimated_capacity).map(([key, val]) => (
                            <div key={key} className="metric-card">
                                <span className="metric-card__label">
                                    {key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                                </span>
                                <span className="metric-card__value">{String(val)}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
