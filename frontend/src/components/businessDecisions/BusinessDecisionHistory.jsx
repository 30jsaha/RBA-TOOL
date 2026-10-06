import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "../../context/useAuth";
import { fetchBusinessDecisionHistory } from "../../services/businessDecisionService";
import BusinessDecisionSummary from "./BusinessDecisionSummary";
import AdminOverrideDialog from "./AdminOverrideDialog";

const PAGE_SIZE = 20;

const permissionMessage = "You do not have permission to view business decisions.";

function safeError(error, fallback) {
  const status = error?.response?.status;
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to view business decisions.";
  if (status === 404) return "The Invalid TIN or business-decision record was not found.";
  if (status === 400) return error?.response?.data?.message || "The history request is invalid.";
  return fallback;
}

function display(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? display(value) : date.toLocaleString();
}

function decisionBadgeClass(type) {
  return {
    ORIGINAL: "bg-secondary",
    INVALID_TIN: "bg-warning text-dark",
    INVALID_TIN_DISABLED: "bg-info text-dark",
    ADMIN_OVERRIDE: "bg-danger",
  }[type] || "bg-secondary";
}

export default function BusinessDecisionHistory({ tin, onNotice }) {
  const { user } = useAuth();
  const canView = Array.isArray(user?.permissions) && user.permissions.includes("business_decisions.view");
  const canOverride = Array.isArray(user?.permissions) && user.permissions.includes("business_decisions.override");
  const [records, setRecords] = useState([]);
  const [page, setPage] = useState(1);
  const [pageInfo, setPageInfo] = useState({ page: 1, page_size: PAGE_SIZE, has_next: false });
  const [filters, setFilters] = useState({ tax_type: "", decision_type: "", current_only: false });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [overrideRecord, setOverrideRecord] = useState(null);

  const loadHistory = useCallback(async (requestedPage = page) => {
    if (!tin || !canView) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetchBusinessDecisionHistory(tin, {
        page: requestedPage,
        page_size: PAGE_SIZE,
        ...(filters.tax_type ? { tax_type: filters.tax_type } : {}),
        ...(filters.decision_type ? { decision_type: filters.decision_type } : {}),
        ...(filters.current_only ? { current_only: "true" } : {}),
      });
      const data = response?.data?.data || {};
      setRecords(Array.isArray(data.records) ? data.records : []);
      setPageInfo({
        page: Number(data.page) || requestedPage,
        page_size: Number(data.page_size) || PAGE_SIZE,
        has_next: Boolean(data.has_next),
      });
      setPage(Number(data.page) || requestedPage);
    } catch (requestError) {
      setRecords([]);
      setError(safeError(requestError, "Unable to load business-decision history."));
    } finally {
      setLoading(false);
    }
  }, [canView, filters, page, tin]);

  useEffect(() => {
    loadHistory(page);
  }, [loadHistory, page]);

  const currentRecord = useMemo(
    () => records.find((record) => Number(record.is_current) === 1) || records[0] || null,
    [records]
  );

  if (!canView) {
    return <div className="alert alert-secondary mb-0">{permissionMessage}</div>;
  }

  if (!tin) {
    return <div className="alert alert-info mb-0">Select an Invalid TIN to view business decisions.</div>;
  }

  return (
    <section className="card mt-4" aria-labelledby="business-decision-history-title">
      <div className="card-header d-flex flex-wrap gap-2 justify-content-between align-items-center">
        <div>
          <h5 id="business-decision-history-title" className="mb-1">Business Decision History</h5>
          <div className="small text-muted">TIN: {tin}</div>
        </div>
        <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => loadHistory(page)} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="card-body">
        {error && <div className="alert alert-danger" role="alert">{error}</div>}

        <div className="row g-2 mb-3" aria-label="Business decision filters">
          <div className="col-sm-4 col-md-3">
            <label className="form-label" htmlFor="business-decision-tax-type">Tax type</label>
            <select
              id="business-decision-tax-type"
              className="form-select form-select-sm"
              value={filters.tax_type}
              onChange={(event) => { setPage(1); setFilters((current) => ({ ...current, tax_type: event.target.value })); }}
            >
              <option value="">All tax types</option>
              <option value="GST">GST</option>
              <option value="SWT">SWT</option>
              <option value="CIT">CIT</option>
            </select>
          </div>
          <div className="col-sm-5 col-md-4">
            <label className="form-label" htmlFor="business-decision-type">Decision type</label>
            <select
              id="business-decision-type"
              className="form-select form-select-sm"
              value={filters.decision_type}
              onChange={(event) => { setPage(1); setFilters((current) => ({ ...current, decision_type: event.target.value })); }}
            >
              <option value="">All decisions</option>
              <option value="ORIGINAL">ORIGINAL</option>
              <option value="INVALID_TIN">INVALID_TIN</option>
              <option value="INVALID_TIN_DISABLED">INVALID_TIN_DISABLED</option>
              <option value="ADMIN_OVERRIDE">ADMIN_OVERRIDE</option>
            </select>
          </div>
          <div className="col-sm-3 col-md-3 d-flex align-items-end">
            <div className="form-check mb-1">
              <input
                id="business-decision-current-only"
                className="form-check-input"
                type="checkbox"
                checked={filters.current_only}
                onChange={(event) => { setPage(1); setFilters((current) => ({ ...current, current_only: event.target.checked })); }}
              />
              <label className="form-check-label" htmlFor="business-decision-current-only">Current only</label>
            </div>
          </div>
        </div>

        {loading && records.length === 0 ? (
          <div className="text-center text-muted py-4" role="status">Loading business decisions…</div>
        ) : records.length === 0 ? (
          <div className="alert alert-info mb-0">No business decision history is available for this TIN.</div>
        ) : (
          <>
            <BusinessDecisionSummary record={currentRecord} />

            <div className="table-responsive mt-4">
              <table className="table table-bordered table-striped align-middle">
                <caption className="visually-hidden">Business decision history for {tin}</caption>
                <thead>
                  <tr>
                    <th scope="col">Version</th>
                    <th scope="col">Decision</th>
                    <th scope="col">Tax / Source</th>
                    <th scope="col">Original result</th>
                    <th scope="col">Current result</th>
                    <th scope="col">Reason</th>
                    <th scope="col">Decided</th>
                    <th scope="col">State</th>
                    {canOverride && <th scope="col">Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => (
                    <tr key={`${record.tax_type}-${record.source_record_id}-${record.decision_version}`} className={Number(record.is_current) === 1 ? "table-primary" : ""}>
                      <td>{display(record.decision_version)}</td>
                      <td><span className={`badge ${decisionBadgeClass(record.business_decision_type)}`}>{display(record.business_decision_type)}</span></td>
                      <td>{display(record.tax_type)}<br /><span className="small text-muted">#{display(record.source_record_id)}</span></td>
                      <td>{display(record.original_ml_result)}</td>
                      <td>{display(record.current_business_result)}</td>
                      <td className="text-break">{display(record.override_reason || record.decision_reason)}</td>
                      <td>{formatDate(record.decided_at)}</td>
                      <td>{Number(record.is_current) === 1 ? <span className="badge bg-success">Current</span> : <span className="badge bg-light text-dark border">Historical</span>}</td>
                      {canOverride && (
                        <td>
                          <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => setOverrideRecord(record)}>
                            Override
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="d-flex justify-content-between align-items-center mt-3">
              <span className="small text-muted">Page {pageInfo.page}</span>
              <div className="btn-group" role="group" aria-label="History pagination">
                <button type="button" className="btn btn-outline-secondary btn-sm" disabled={loading || page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button>
                <button type="button" className="btn btn-outline-secondary btn-sm" disabled={loading || !pageInfo.has_next} onClick={() => setPage((current) => current + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </div>

      {overrideRecord && (
        <AdminOverrideDialog
          record={overrideRecord}
          onClose={() => setOverrideRecord(null)}
          onSaved={async () => {
            setOverrideRecord(null);
            onNotice?.("Business decision override saved.", "success");
            await loadHistory(page);
          }}
        />
      )}
    </section>
  );
}
