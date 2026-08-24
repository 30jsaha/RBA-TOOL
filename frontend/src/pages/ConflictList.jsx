import { useEffect, useMemo, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import ConflictTable from "../components/conflicts/ConflictTable";
import "./css/ConflictsList.css";
import "../styles/conflicts.css";
import API from "../api/api";
import Swal from "sweetalert2";

export default function ConflictList() {
  const [conflicts, setConflicts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [taxType, setTaxType] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("settings");

  const params = useMemo(
    () => ({
      tax_type: taxType || undefined,
      status: statusFilter === "" ? undefined : statusFilter,
    }),
    [taxType, statusFilter]
  );

  useEffect(() => {
    loadConflicts();
  }, [params]);

  const loadConflicts = async () => {
    try {
      setLoading(true);
      const res = await API.get("/admin/conflicts/list", { params });
      setConflicts(res.data.data || []);
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Load Failed",
        text: err.response?.data?.message || "Failed to load conflicts",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (row) => {
    const result = await Swal.fire({
      title: "Approve Conflict?",
      text: "This will update fraud data and rerun process.",
      icon: "warning",
      showCancelButton: true,
      confirmButtonText: "Approve",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#198754",
    });

    if (!result.isConfirmed) return;

    try {
      await API.post(`/admin/conflicts/${row.id}/approve`);
      await Swal.fire({
        toast: true,
        position: "top-end",
        icon: "success",
        title: "Conflict approved",
        showConfirmButton: false,
        timer: 2000,
        timerProgressBar: true,
      });
      await loadConflicts();
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Approval Failed",
        text: err.response?.data?.message || "Approval failed",
      });
    }
  };

  const handleReject = async (row) => {
    const result = await Swal.fire({
      title: "Reject Conflict?",
      text: "This conflict will be rejected.",
      icon: "warning",
      showCancelButton: true,
      confirmButtonText: "Reject",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#dc3545",
    });

    if (!result.isConfirmed) return;

    try {
      await API.post(`/admin/conflicts/${row.id}/reject`);
      await Swal.fire({
        toast: true,
        position: "top-end",
        icon: "success",
        title: "Conflict rejected",
        showConfirmButton: false,
        timer: 2000,
        timerProgressBar: true,
      });
      await loadConflicts();
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Rejection Failed",
        text: err.response?.data?.message || "Rejection failed",
      });
    }
  };

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
              <div className="header-title-page mb-3">Conflict List</div>

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

          <label className="mb-0 fw-bold ms-2">Status:</label>
          <select
            className="form-select w-auto"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All</option>
            <option value="0">Pending</option>
            <option value="1">Approved</option>
            <option value="2">Rejected</option>
          </select>
        </div>
      </div>

              <div className="card">
                <div className="card-header">
                  <h5 className="mb-0">Conflict Listing</h5>
                </div>

                <div className="card-body">
                  <ConflictTable
                    rows={conflicts}
                    loading={loading}
                    showActions={true}
                    onApprove={handleApprove}
                    onReject={handleReject}
                  />
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
