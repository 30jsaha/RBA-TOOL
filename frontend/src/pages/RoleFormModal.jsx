import { useState } from "react";

export default function RoleFormModal({ role, onClose, onSaved }) {
  const [name, setName] = useState(role?.name || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isSystemRole = Boolean(role?.is_system);

  const submit = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Role name is required");
      return;
    }

    setSaving(true);
    setError("");

    try {
      await onSaved(trimmedName);
      onClose();
    } catch (err) {
      setError(err?.response?.data?.message || err?.data?.message || err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal show d-block">
      <div className="modal-dialog">
        <div className="modal-content">
          <div className="modal-header">
            <h5>{role ? "Edit Role" : "Create Role"}</h5>
            <button className="btn-close" onClick={onClose} />
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}
            {isSystemRole && (
              <div className="alert alert-warning py-2">
                System roles are protected and cannot be renamed.
              </div>
            )}

            <label className="form-label">Role Name</label>
            <input
              className="form-control"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isSystemRole || saving}
              placeholder="Enter role name"
            />
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={onClose} disabled={saving}>
              Back
            </button>
            <button className="btn btn-primary" onClick={submit} disabled={saving || isSystemRole}>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
