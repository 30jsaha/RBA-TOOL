import { useCallback, useEffect, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import InvalidTinFormModal from "./InvalidTinFormModal";
import BusinessDecisionHistory from "../components/businessDecisions/BusinessDecisionHistory";
import InvalidTinJobStatus from "../components/businessDecisions/InvalidTinJobStatus";
import { useAuth } from "../context/useAuth";

export default function InvalidTins() {
  const { user } = useAuth();
  const [tins, setTins] = useState([]);
  const [open, setOpen] = useState(false);
  const [editTin, setEditTin] = useState(null);

  // layout states (same as other pages)
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("");
  const [selectedTin, setSelectedTin] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  const canViewDecisions = Array.isArray(user?.permissions) && user.permissions.includes("business_decisions.view");
  const canViewJobs = Array.isArray(user?.permissions) && user.permissions.includes("business_decisions.jobs");

  const handleJobCompleted = useCallback(() => {
    loadTins();
    setHistoryRefreshKey((current) => current + 1);
    setNotice({ type: "success", message: "Invalid-TIN business-decision processing completed." });
  }, []);

  const loadTins = async () => {
    const res = await API.get("/invalid-tins/list");
    setTins(res.data.data || []);
  };

  useEffect(() => {
    loadTins();
  }, []);

  const toggleStatus = async (id, status) => {
    try {
      const response = await API.put(`/invalid-tins/${id}/status`, {
        status: !status,
      });

      // Optimistic UI update
      setTins((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, status: !status } : t
        )
      );
      const returnedJobId = response?.data?.job_id;
      if (returnedJobId && canViewJobs) setJobId(returnedJobId);
      setNotice({ type: "success", message: returnedJobId ? "Invalid TIN status change queued." : "Invalid TIN status updated." });
    } catch (err) {
      const statusCode = err.response?.status;
      const message = statusCode === 409
        ? "An opposite Invalid-TIN action is already active."
        : statusCode === 403
          ? "You do not have permission to change Invalid-TIN status."
          : statusCode === 404
            ? "The Invalid TIN was not found."
            : err.response?.data?.message || "Action failed";
      setNotice({ type: "danger", message });
    }
  };

  return (
    <div className="container-fluid">
      <div className="row">
        {/* HEADER */}
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />

        {/* SIDEBAR + CONTENT */}
        <div className="col-lg-12">
          <Sidebar
            collapsed={collapsed}
            setCollapsed={setCollapsed}
            openMenu={openMenu}
            setOpenMenu={setOpenMenu}
          />

          <main className="main-content mt-5">
            <div className="container-fluid">
              {/* PAGE TITLE */}
              <div className="header-title-page mb-3">
                Invalid TIN Management
              </div>

              {/* CARD */}
              <div className="card">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <h5 className="mb-0">Invalid TINs</h5>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => setOpen(true)}
                  >
                    + Add Invalid TIN
                  </button>
                </div>

                <div className="card-body">
                  <div className="table-container">
                    <table className="table table-bordered table-striped">
                      <thead>
                        <tr>
                          <th>TIN Number</th>
                          <th>Status</th>
                          <th>Created Date</th>
                          <th style={{ width: "290px" }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tins.length === 0 ? (
                          <tr>
                            <td colSpan="4" className="text-center">
                              No invalid TINs found
                            </td>
                          </tr>
                        ) : (
                          tins.map((t) => (
                            <tr key={t.id}>
                              <td>{t.tin_number}</td>
                              <td>
                                <span
                                  className={`badge ${
                                    t.status ? "bg-success" : "bg-danger"
                                  }`}
                                >
                                  {t.status ? "Active" : "Inactive"}
                                </span>
                              </td>
                              <td>
                                {new Date(t.created_date).toLocaleString()}
                              </td>
                              <td>
                                <button
                                  className="btn btn-info btn-sm me-2"
                                  onClick={() => {
                                    setEditTin(t);
                                    setOpen(true);
                                  }}
                                >
                                  Edit
                                </button>

                                <button
                                  className="btn btn-warning btn-sm"
                                  onClick={() =>
                                    toggleStatus(t.id, t.status)
                                  }
                                >
                                  {t.status ? "Disable" : "Enable"}
                                </button>
                                {canViewDecisions && (
                                  <button
                                    className="btn btn-outline-primary btn-sm ms-2"
                                    onClick={() => setSelectedTin(t)}
                                  >
                                    Decisions
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              {notice && (
                <div className={`alert alert-${notice.type} mt-3`} role="alert">
                  <div className="d-flex justify-content-between align-items-center gap-2">
                    <span>{notice.message}</span>
                    <button type="button" className="btn-close" aria-label="Dismiss notification" onClick={() => setNotice(null)}></button>
                  </div>
                </div>
              )}

              {canViewJobs && jobId && (
                <InvalidTinJobStatus
                  jobId={jobId}
                  onClose={() => setJobId(null)}
                  onCompleted={handleJobCompleted}
                />
              )}

              {canViewDecisions && selectedTin && (
                <BusinessDecisionHistory
                  key={`${selectedTin.tin_number}-${historyRefreshKey}`}
                  tin={selectedTin.tin_number}
                  onNotice={(message, type = "info") => setNotice({ message, type })}
                />
              )}
            </div>
          </main>
        </div>

        {/* FOOTER */}
        <Footer />
      </div>

      {/* CREATE / EDIT MODAL */}
      {open && (
        <InvalidTinFormModal
          tin={editTin}
          onClose={() => {
            setOpen(false);
            setEditTin(null);
          }}
          onSaved={loadTins}
        />
      )}
    </div>
  );
}
