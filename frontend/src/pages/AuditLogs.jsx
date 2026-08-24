import { useEffect, useMemo, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import "./css/ConflictsList.css";
import "../styles/conflicts.css";
import API from "../api/api";
import Swal from "sweetalert2";

export default function AuditLogs() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [taxType, setTaxType] = useState("");

  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("settings");

  const params = useMemo(
    () => ({
      tax_type: taxType || undefined,
    }),
    [taxType]
  );

  useEffect(() => {
    loadRows();
  }, [params]);

  const loadRows = async () => {
    try {
      setLoading(true);
      const res = await API.get("/admin/conflicts/history", { params });
      setRows(res.data.data || []);
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Load Failed",
        text: err.response?.data?.message || "Failed to load audit logs",
      });
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (v) => (v ? new Date(v).toLocaleString() : "-");

  return (
    <div className="container-fluid">
      <div className="row">
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />

        <div className="col-lg-12">
          <Sidebar
            collapsed={collapsed}
            setCollapsed={setCollapsed}
            openMenu={openMenu}
            setOpenMenu={setOpenMenu}
          />

          <main className="main-content mt-5">
            <div className="container-fluid">
              <div className="header-title-page mb-3">Audit Logs</div>

              <div className="card mb-3">
                <div className="card-body d-flex align-items-center gap-3">
                  <label className="mb-0 fw-bold">Tax Type:</label>
                  <select
                    className="form-select w-auto"
                    value={taxType}
                    onChange={(e) => setTaxType(e.target.value)}
                  >
                    <option value="">All</option>
                    <option value="GST">GST</option>
                    <option value="SWT">SWT</option>
                    <option value="CIT">CIT</option>
                  </select>
                </div>
              </div>

              <div className="card">
                <div className="card-header">
                  <h5 className="mb-0">Fraud Justification History</h5>
                </div>

                <div className="card-body">
                  <div className="conflicts-table-wrapper">
                    <table className="table table-bordered table-striped align-middle conflicts-table">
                      <thead>
                        <tr>
                          <th className="col-id">ID</th>
                          <th className="col-tax-type">Tax Type</th>
                          <th className="col-tin">TIN</th>
                          <th className="col-taxpayer-name">Taxpayer Name</th>
                          <th className="col-field-name">Field Name</th>
                          <th className="col-prev">Old Value</th>
                          <th className="col-curr">New Value</th>
                          <th className="col-status">Action Type</th>
                          <th className="col-status">Changed By</th>
                          <th className="col-field-name">Change Reason</th>
                          <th className="col-tin">Upload Batch ID</th>
                          <th className="col-created-at">Created At</th>
                        </tr>
                      </thead>

                      <tbody>
                        {loading ? (
                          <tr>
                            <td colSpan="12" className="text-center py-4">
                              <div className="d-flex justify-content-center align-items-center gap-2">
                                <div className="spinner-border spinner-border-sm" role="status" />
                                <span>Loading...</span>
                              </div>
                            </td>
                          </tr>
                        ) : (rows || []).length === 0 ? (
                          <tr>
                            <td colSpan="12" className="text-center">
                              No audit logs found
                            </td>
                          </tr>
                        ) : (
                          (rows || []).map((r) => (
                            <tr key={r.id}>
                              <td className="text-primary">{r.id}</td>
                              <td>{r.tax_type || "-"}</td>
                              <td>{r.tin || "-"}</td>
                              <td className="text-break">{r.taxpayer_name || "-"}</td>
                              <td className="text-break">{r.field_name || "-"}</td>
                              <td className="text-break">{r.old_value ?? "-"}</td>
                              <td className="text-break">{r.new_value ?? "-"}</td>
                              <td className="text-break">{r.action_type || "-"}</td>
                              <td>{r.changed_by ?? "-"}</td>
                              <td className="text-break">{r.change_reason ?? "-"}</td>
                              <td className="text-break">{r.upload_batch_id ?? "-"}</td>
                              <td>{formatDate(r.created_at)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>

        <Footer />
      </div>
    </div>
  );
}

