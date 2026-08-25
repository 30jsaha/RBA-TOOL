import { useState } from "react";
import { Navigate } from "react-router-dom";
import { Button, Alert, CircularProgress } from "@mui/material";
import Swal from "sweetalert2";

import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import { hasPermission } from "../services/auth";

import "./css/ResetDB.css";

export default function ResetDB() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [cleanupConfirmChecked, setCleanupConfirmChecked] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [cleanupProcessing, setCleanupProcessing] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [cleanupError, setCleanupError] = useState("");
  const [cleanupSuccess, setCleanupSuccess] = useState("");

  const canResetDb = hasPermission("settings.reset_db");

  const showAlert = (icon, title, text) =>
    Swal.fire({
      icon,
      title,
      text,
      confirmButtonColor: "#6A00FF",
    });

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (!confirmChecked) {
      setError(
        "Please confirm the reset by checking the checkbox before continuing."
      );
      return;
    }

    const confirmResult = await Swal.fire({
      icon: "warning",
      title: "Are you confirm about this task!",
      text: "This action will permanently delete all financial data.",
      showCancelButton: true,
      confirmButtonText: "Yes",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#6A00FF",
      cancelButtonColor: "#6c757d",
    });

    if (!confirmResult.isConfirmed) return;

    setProcessing(true);
    try {
      const res = await API.post("/admin/reset-db");
      const message = res.data?.message || "Database reset successfully";
      setSuccess(message);
      await showAlert("success", "Success", "Database reset successfully");
      setConfirmChecked(false);
    } catch (err) {
      const message =
        err.response?.data?.message || err.message || "Reset failed.";
      setError(message);
      await showAlert("error", "Reset Failed", message);
    } finally {
      setProcessing(false);
    }
  };

  const handleCleanupSubmit = async (event) => {
    event.preventDefault();
    setCleanupError("");
    setCleanupSuccess("");

    if (!cleanupConfirmChecked) {
      setCleanupError(
        "Please confirm the cleanup by checking the checkbox before continuing."
      );
      return;
    }

    const confirmResult = await Swal.fire({
      icon: "warning",
      title: "Clean temporary files?",
      text: "This will permanently remove all temporary files from GST, SWT and CIT final output folders. Database records will not be deleted.",
      showCancelButton: true,
      confirmButtonText: "Yes, Cleanup Files",
      cancelButtonText: "Cancel",
      confirmButtonColor: "#6A00FF",
      cancelButtonColor: "#6c757d",
    });

    if (!confirmResult.isConfirmed) return;

    setCleanupProcessing(true);
    try {
      const res = await API.post("/admin/cleanup-temp-files", { confirm: true });
      const deleted = res.data?.deleted || {};
      const totalDeleted = res.data?.total_deleted ?? 0;
      const failed = Array.isArray(res.data?.failed) ? res.data.failed : [];
      const message =
        res.data?.message || "Temporary files cleaned successfully.";

      const details = [
        message,
        `GST: ${deleted.gst ?? 0}`,
        `SWT: ${deleted.swt ?? 0}`,
        `CIT: ${deleted.cit ?? 0}`,
        `Total: ${totalDeleted}`,
      ];

      if (failed.length) {
        details.push(`Warnings: ${failed.length} file(s) could not be deleted.`);
      }

      setCleanupSuccess(details.join(" | "));
      await showAlert("success", "Success", details.join(" "));
      setCleanupConfirmChecked(false);
    } catch (err) {
      const message =
        err.response?.data?.message || err.message || "Cleanup failed.";
      setCleanupError(message);
      await showAlert("error", "Cleanup Failed", message);
    } finally {
      setCleanupProcessing(false);
    }
  };

  if (!canResetDb) {
    return <Navigate to="/gst" replace />;
  }

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

          <main className="main-content mt-5 reset-db-main">
            <div className="container-fluid">
              <div className="header-title-page mb-3">Reset DB</div>

              <div className="reset-db-card">
                <form onSubmit={handleSubmit}>
                  <div className="form-check mb-3">
                    <input
                      className="form-check-input"
                      type="checkbox"
                      id="confirmResetDb"
                      checked={confirmChecked}
                      disabled={processing}
                      onChange={(e) => setConfirmChecked(e.target.checked)}
                    />
                    <label
                      className="form-check-label"
                      htmlFor="confirmResetDb"
                    >
                      Are you sure you want to reset DB? This will remove all
                      financial records.
                    </label>
                  </div>

                  {error && (
                    <Alert severity="error" className="mb-3">
                      {error}
                    </Alert>
                  )}

                  {success && (
                    <Alert severity="success" className="mb-3">
                      {success}
                    </Alert>
                  )}

                  <Button
                    type="submit"
                    variant="contained"
                    color="error"
                    disabled={processing}
                    startIcon={
                      processing ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : null
                    }
                  >
                    {processing ? "Resetting..." : "Reset Database"}
                  </Button>
                </form>
              </div>

              <div className="reset-db-card mt-4">
           
                <form onSubmit={handleCleanupSubmit}>
                  <div className="form-check mb-3">
                    <input
                      className="form-check-input"
                      type="checkbox"
                      id="confirmCleanupTempFiles"
                      checked={cleanupConfirmChecked}
                      disabled={cleanupProcessing}
                      onChange={(e) =>
                        setCleanupConfirmChecked(e.target.checked)
                      }
                    />
                    <label
                      className="form-check-label"
                      htmlFor="confirmCleanupTempFiles"
                    >
                      Are you sure you want to clean temporary encrypted processing files on server?
                    </label>
                  </div>

                  {cleanupError && (
                    <Alert severity="error" className="mb-3">
                      {cleanupError}
                    </Alert>
                  )}

                  {cleanupSuccess && (
                    <Alert severity="success" className="mb-3">
                      {cleanupSuccess}
                    </Alert>
                  )}

                  <Button
                    type="submit"
                    variant="contained"
                    color="warning"
                    disabled={cleanupProcessing || !cleanupConfirmChecked}
                    startIcon={
                      cleanupProcessing ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : null
                    }
                  >
                    {cleanupProcessing ? "Cleaning..." : "CLEANUP TEMP FILES"}
                  </Button>
                </form>
              </div>
            </div>
          </main>
        </div>

        <Footer />
      </div>
    </div>
  );
}
