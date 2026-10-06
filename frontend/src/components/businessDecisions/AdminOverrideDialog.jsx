import { useState } from "react";
import { submitBusinessDecisionOverride } from "../../services/businessDecisionService";

function errorMessage(error) {
  const status = error?.response?.status;
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to create an admin override.";
  if (status === 404) return "The source record was not found.";
  if (status === 400) return error?.response?.data?.message || "Please correct the override details.";
  return "Unable to save the admin override. Please try again.";
}

export default function AdminOverrideDialog({ record, onClose, onSaved }) {
  const [result, setResult] = useState("Fraud");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const trimmedReason = reason.trim();
    if (trimmedReason.length < 3) {
      setError("Enter a meaningful reason of at least 3 characters.");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      await submitBusinessDecisionOverride(record.tax_type, record.source_record_id, {
        result,
        reason: trimmedReason,
      });
      await onSaved?.();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal show d-block" role="dialog" aria-modal="true" aria-labelledby="admin-override-title" tabIndex="-1">
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">
          <form onSubmit={submit}>
            <div className="modal-header">
              <h5 id="admin-override-title" className="modal-title">Admin Override</h5>
              <button type="button" className="btn-close" aria-label="Close" onClick={onClose} disabled={submitting}></button>
            </div>
            <div className="modal-body">
              <div className="alert alert-warning" role="alert">
                Admin Override changes the current business decision and becomes authoritative over automatic Invalid-TIN decisions.
              </div>
              <div className="small text-muted mb-3">
                Target: {record.tax_type} / source record {record.source_record_id}
              </div>
              {error && <div className="alert alert-danger" role="alert">{error}</div>}
              <div className="mb-3">
                <label className="form-label" htmlFor="override-result">Target result</label>
                <select id="override-result" className="form-select" value={result} onChange={(event) => setResult(event.target.value)} disabled={submitting}>
                  <option value="Fraud">Fraud</option>
                  <option value="Non-Fraud">Non-Fraud</option>
                </select>
              </div>
              <div className="mb-1">
                <label className="form-label" htmlFor="override-reason">Reason <span className="text-danger">*</span></label>
                <textarea
                  id="override-reason"
                  className="form-control"
                  rows="4"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  aria-describedby="override-reason-help"
                  required
                  disabled={submitting}
                />
                <div id="override-reason-help" className="form-text">Provide a meaningful business reason.</div>
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={onClose} disabled={submitting}>Cancel</button>
              <button type="submit" className="btn btn-danger" disabled={submitting}>
                {submitting ? "Saving…" : "Confirm Override"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
