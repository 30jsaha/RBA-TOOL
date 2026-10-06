import { useCallback, useEffect, useState } from "react";
import { fetchBusinessDecisionJob } from "../../services/businessDecisionService";

const TERMINAL_STATES = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

function safeError(error) {
  const status = error?.response?.status;
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to view job status.";
  if (status === 404) return "The business-decision job was not found.";
  return "Unable to load job status.";
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export default function InvalidTinJobStatus({ jobId, onCompleted, onClose }) {
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadJob = useCallback(async () => {
    if (!jobId) return null;
    try {
      const response = await fetchBusinessDecisionJob(jobId);
      const nextJob = response?.data?.data || null;
      setJob(nextJob);
      setError("");
      if (nextJob && TERMINAL_STATES.has(nextJob.status)) onCompleted?.(nextJob);
      return nextJob;
    } catch (requestError) {
      setError(safeError(requestError));
      return { stopPolling: true };
    } finally {
      setLoading(false);
    }
  }, [jobId, onCompleted]);

  useEffect(() => {
    let active = true;
    let timer;

    const start = async () => {
      const first = await loadJob();
      if (!active || !first || first.stopPolling || TERMINAL_STATES.has(first.status)) return;
      timer = window.setInterval(async () => {
        const next = await loadJob();
        if (next && (next.stopPolling || TERMINAL_STATES.has(next.status)) && timer) {
          window.clearInterval(timer);
          timer = undefined;
        }
      }, 3000);
    };

    start();
    return () => {
      active = false;
      if (timer) window.clearInterval(timer);
    };
  }, [loadJob]);

  return (
    <div className="card border-info mt-3" aria-live="polite">
      <div className="card-header d-flex justify-content-between align-items-center">
        <span>Invalid-TIN processing status</span>
        <button type="button" className="btn-close" aria-label="Close job status" onClick={onClose}></button>
      </div>
      <div className="card-body">
        {loading && !job ? (
          <div className="text-muted" role="status">Loading job status…</div>
        ) : error ? (
          <div className="alert alert-danger mb-0" role="alert">{error}</div>
        ) : job ? (
          <>
            <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
              <span className="badge bg-primary">{job.status}</span>
              <span className="small">TIN: {job.tin || "—"}</span>
              <span className="small">Action: {job.requested_action || "—"}</span>
              <span className="small">Tax type: {job.current_tax_type || "—"}</span>
            </div>
            <div className="row g-3">
              <div className="col-6 col-md-3"><div className="small text-muted">Processed</div><strong>{job.records_processed ?? 0}</strong></div>
              <div className="col-6 col-md-3"><div className="small text-muted">Overridden</div><strong>{job.records_overridden ?? 0}</strong></div>
              <div className="col-6 col-md-3"><div className="small text-muted">Skipped</div><strong>{job.records_skipped ?? 0}</strong></div>
              <div className="col-6 col-md-3"><div className="small text-muted">Retries</div><strong>{job.retry_count ?? 0}</strong></div>
            </div>
            <div className="small text-muted mt-3">
              Started: {formatDate(job.started_at)} · Updated: {formatDate(job.updated_at)} · Completed: {formatDate(job.completed_at)}
            </div>
            {job.status === "FAILED" && job.error_message && <div className="alert alert-danger mt-3 mb-0">{job.error_message}</div>}
          </>
        ) : (
          <div className="text-muted">No job status is available.</div>
        )}
      </div>
    </div>
  );
}
