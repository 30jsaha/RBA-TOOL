function display(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? display(value) : date.toLocaleString();
}

function decisionClass(type) {
  return {
    ORIGINAL: "bg-secondary",
    INVALID_TIN: "bg-warning text-dark",
    INVALID_TIN_DISABLED: "bg-info text-dark",
    ADMIN_OVERRIDE: "bg-danger",
  }[type] || "bg-secondary";
}

export default function BusinessDecisionSummary({ record }) {
  if (!record) {
    return <div className="alert alert-info">No current business decision is available.</div>;
  }

  const fields = [
    ["Current business decision", record.current_business_result],
    ["Original ML result", record.original_ml_result],
    ["Tax type", record.tax_type],
    ["Source record ID", record.source_record_id],
    ["Last decision", formatDate(record.decided_at)],
  ];

  return (
    <div className="border rounded p-3 bg-light" aria-label="Current business decision summary">
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <h6 className="mb-0">Current Decision</h6>
        <span className={`badge ${decisionClass(record.business_decision_type)}`}>{display(record.business_decision_type)}</span>
      </div>
      <div className="row g-3">
        {fields.map(([label, value]) => (
          <div className="col-6 col-lg" key={label}>
            <div className="small text-muted">{label}</div>
            <div className="fw-semibold text-break">{display(value)}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 small text-muted">
        Current business result: <strong>{display(record.current_business_result)}</strong>. Original rule result: <strong>{display(record.original_rule_result)}</strong>.
      </div>
    </div>
  );
}
