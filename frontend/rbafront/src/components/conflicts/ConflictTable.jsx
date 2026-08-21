const taxBadge = (tax) => {
  if (tax === "GST") return "bg-primary";
  if (tax === "SWT") return "bg-info";
  if (tax === "CIT") return "bg-dark";
  return "bg-secondary";
};

const statusBadge = (status) => {
  const s = Number(status);
  if (s === 1) return { text: "Approved", cls: "badge bg-success" };
  if (s === 2) return { text: "Rejected", cls: "badge bg-danger" };
  return { text: "Pending", cls: "badge bg-warning text-dark" };
};

const toNumber = (v) => {
  if (v === null || v === undefined) return 0;
  const n = Number(v);
  if (!Number.isNaN(n)) return n;
  const n2 = Number(String(v).replace(/,/g, "").trim());
  return Number.isNaN(n2) ? 0 : n2;
};

const formatNumber = (v) =>
  toNumber(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

export default function ConflictTable({
  rows,
  loading,
  showActions,
  showActionColumn = true,
  onApprove,
  onReject,
}) {
  return (
    <div className="conflicts-table-wrapper">
      <table className="table table-bordered table-striped align-middle conflicts-table">
        <thead>
          <tr>
            <th className="col-id">ID</th>
            <th className="col-tax-type">Tax Type</th>
            <th className="col-tin">TIN</th>
            <th className="col-taxpayer-name">Taxpayer Name</th>
            <th className="col-field-name">Field Name</th>
            <th className="col-prev text-end">Previous Value</th>
            <th className="col-curr text-end">Current Value</th>
            <th className="col-diff text-end">Difference</th>
            <th className="col-status">Status</th>
            <th className="col-created-at">Created At</th>
            {showActionColumn && <th className="col-action">Action</th>}
          </tr>
        </thead>

        <tbody>
          {loading ? (
            <tr>
              <td colSpan={showActionColumn ? 11 : 10} className="text-center py-4">
                <div className="d-flex justify-content-center align-items-center gap-2">
                  <div className="spinner-border spinner-border-sm" role="status" />
                  <span>Loading...</span>
                </div>
              </td>
            </tr>
          ) : (rows || []).length === 0 ? (
            <tr>
              <td colSpan={showActionColumn ? 11 : 10} className="text-center">
                No conflicts found
              </td>
            </tr>
          ) : (
            (rows || []).map((c) => {
              const st = statusBadge(c.status);
              const isApproved = Number(c.status) === 1;
              const isRejected = Number(c.status) === 2;

              return (
                <tr key={`${c.tax_type}-${c.id}`}>
                  <td className="text-primary">{c.id}</td>

                  <td>
                    <span className={`badge tax-badge ${taxBadge(c.tax_type)}`}>{c.tax_type}</span>
                  </td>

                  <td>{c.tin || "-"}</td>
                  <td className="text-break">{c.taxpayer_name || "-"}</td>
                  <td className="text-break">{c.field_name || "-"}</td>
                  <td className="text-end">{formatNumber(c.previous_value)}</td>
                  <td className="text-end">{formatNumber(c.current_value)}</td>
                  <td className="text-end">{formatNumber(c.difference)}</td>

                  <td>
                    <span className={`${st.cls} status-badge`}>{st.text}</span>
                  </td>

                  <td>{c.created_at ? new Date(c.created_at).toLocaleString() : "-"}</td>

                  {showActionColumn && (
                    <td>
                      {!showActions ? (
                        <span className="text-muted">—</span>
                      ) : Number(c.status) !== 0 ? (
                        <span className="text-muted">Processed</span>
                      ) : (
                        <div className="action-buttons">
                          <button className="btn btn-success btn-sm" onClick={() => onApprove(c)}>
                            Approve
                          </button>
                          <button className="btn btn-danger btn-sm" onClick={() => onReject(c)}>
                            Reject
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
