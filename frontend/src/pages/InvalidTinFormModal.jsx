import { useEffect, useState } from "react";
import API from "../api/api";

export default function InvalidTinFormModal({ tin, onClose, onSaved }) {
  const [tinNumber, setTinNumber] = useState("");

  useEffect(() => {
    if (tin) {
      setTinNumber(tin.tin_number);
    }
  }, [tin]);

  const submit = async () => {
    if (!tinNumber.trim()) {
      alert("TIN number is required");
      return;
    }

    try {
      if (tin) {
        await API.put(`/invalid-tins/${tin.id}`, {
          tin_number: tinNumber,
        });
      } else {
        await API.post("/invalid-tins/create-invalid-tin", {
          tin_number: tinNumber,
        });
      }

      onSaved();
      onClose();
    } catch (err) {
      alert(err.response?.data?.message || "Operation failed");
    }
  };

  return (
    <div className="modal show d-block" tabIndex="-1">
      <div className="modal-dialog">
        <div className="modal-content">

          <div className="modal-header">
            <h5 className="modal-title">
              {tin ? "Edit Invalid TIN" : "Add Invalid TIN"}
            </h5>
            <button className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            <div className="form-group">
              <label>TIN Number</label>
              <input
                type="text"
                className="form-control"
                value={tinNumber}
                onChange={(e) => setTinNumber(e.target.value)}
                placeholder="Enter TIN number"
              />
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={onClose}>
              Back
            </button>
            <button className="btn btn-primary" onClick={submit}>
              Save
            </button>
          </div>

        </div>
      </div>
    </div>
  );
}