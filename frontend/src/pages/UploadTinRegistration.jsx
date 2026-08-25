import { useRef, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import {
  Button,
  Paper,
  Alert,
  LinearProgress,
  Typography,
} from "@mui/material";
import { FaCloudUploadAlt } from "react-icons/fa";

export default function UploadTinRegistration() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [syncError, setSyncError] = useState("");

  const fileInputRef = useRef();

  const handleFileClick = () => fileInputRef.current?.click();

  const handleFileChosen = (chosenFile) => {
    setError("");
    setMessage("");
    setResult(null);

    if (!chosenFile) return;

    const lower = chosenFile.name.toLowerCase();
    if (!lower.endsWith(".csv") && !lower.endsWith(".xlsx")) {
      setError("Only CSV and XLSX files are supported.");
      setFile(null);
      return;
    }

    setFile(chosenFile);
  };

  const handleReset = () => {
    setFile(null);
    setUploading(false);
    setProcessing(false);
    setProgress(0);
    setResult(null);
    setError("");
    setMessage("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };


  const handleSyncMissing = async () => {
    setSyncError("");
    setSyncMessage("");
    setSyncing(true);
    try {
      const payload = result?.missing_tins_payload || [];
      const res = await API.post("/tin/sync-missing", payload);
      const count = res.data?.inserted_records ?? 0;
      setSyncMessage(`${count} records synced successfully`);
    } catch (err) {
      setSyncError("Failed to sync TINs");
    } finally {
      setSyncing(false);
    }
  };

  const handleUpload = async () => {
    setError("");
    setMessage("");

    if (!file) {
      setError("Please select a file first.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      setUploading(true);
      setProcessing(false);
      setProgress(0);

      const res = await API.post("/upload-tin-reg", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (event) => {
          if (!event.total) return;
          const pct = Math.round((event.loaded / event.total) * 100);
          setProgress(pct);
          if (pct >= 100) setProcessing(true);
        },
      });

      setResult(res.data);
      setMessage(res.data.message || "Upload processed successfully.");
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    } finally {
      setUploading(false);
      setProcessing(false);
    }
  };

  return (
    <div className="container-fluid">
      <div className="row">
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />

        <div className="col-lg-12 col-md-12">
          <Sidebar
            collapsed={collapsed}
            setCollapsed={setCollapsed}
            openMenu={openMenu}
            setOpenMenu={setOpenMenu}
          />

          <main className="main-content mt-5">
            <div className="container-fluid">
              <div className="d-flex justify-content-between align-items-center mb-3">
                <div className="header-title-page">Upload TIN Registration</div>
              </div>

              <Paper className="p-4 mb-3">
                <div
                  className="border rounded text-center p-4 mb-3 bg-light"
                  onClick={handleFileClick}
                  onDrop={(e) => {
                    e.preventDefault();
                    handleFileChosen(e.dataTransfer.files[0]);
                  }}
                  onDragOver={(e) => e.preventDefault()}
                  style={{ cursor: "pointer" }}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv,.xlsx"
                    style={{ display: "none" }}
                    onChange={(e) => handleFileChosen(e.target.files[0])}
                  />
                  <FaCloudUploadAlt size={44} className="text-primary mb-2" />
                  <div className="fw-semibold">
                    {file ? file.name : "Click or drop CSV/XLSX file here"}
                  </div>
                  <div className="text-muted small">CSV or Excel only</div>
                </div>

                <div className="d-flex gap-2 flex-wrap">
                  <Button
                    variant="contained"
                    color="primary"
                    onClick={handleUpload}
                    disabled={!file || uploading}
                  >
                    {uploading ? "Uploading..." : "Upload"}
                  </Button>
                  <Button variant="outlined" onClick={handleReset}>
                    Reset
                  </Button>
                </div>

                {uploading && (
                  <div className="mt-3">
                    {progress < 100 ? (
                      <LinearProgress variant="determinate" value={progress} />
                    ) : (
                      <LinearProgress />
                    )}
                    <Typography variant="body2" className="mt-2">
                      {progress < 100
                        ? `Uploading: ${progress}%`
                        : "Upload complete. Processing on server..."}
                    </Typography>
                  </div>
                )}

                {processing && !uploading && (
                  <div className="mt-3">
                    <LinearProgress />
                    <Typography variant="body2" className="mt-2">
                      Processing on server...
                    </Typography>
                  </div>
                )}

                {error && (
                  <Alert severity="error" className="mt-3">
                    {error}
                  </Alert>
                )}
                {message && (
                  <Alert severity="success" className="mt-3">
                    {message}
                  </Alert>
                )}

                {result && (
                  <Paper className="p-3 mt-3">
                    <Typography variant="subtitle1" gutterBottom>
                      Upload Summary
                    </Typography>
                    <div>
                      <strong>Total Records:</strong> {result.total_records ?? 0}
                    </div>
                    <div>
                      <strong>Inserted:</strong> {result.inserted ?? 0}
                    </div>
                    <div>
                      <strong>Duplicates:</strong> {result.duplicates ?? 0}
                    </div>

                    <div className="mt-3 d-flex align-items-center gap-2 flex-wrap">
                      <Button
                        variant="contained"
                        color="secondary"
                        onClick={handleSyncMissing}
                        disabled={syncing}
                      >
                        {syncing ? "Syncing..." : "Sync Missing TINs"}
                      </Button>
                      {syncing && <LinearProgress style={{ width: 160 }} />}
                    </div>

                    {syncMessage && (
                      <Alert severity="success" className="mt-3">
                        {syncMessage}
                      </Alert>
                    )}
                    {syncError && (
                      <Alert severity="error" className="mt-3">
                        {syncError}
                      </Alert>
                    )}
                  </Paper>
                )}
              </Paper>
            </div>
          </main>
        </div>

        <Footer />
      </div>
    </div>
  );
}








