import { useCallback, useEffect, useState } from "react";
import { 
  Alert, Button, Checkbox, CircularProgress, Dialog, DialogActions, 
  DialogContent, DialogTitle, FormControlLabel, FormGroup, LinearProgress, 
  Radio, RadioGroup, Tab, Tabs, TextField 
} from "@mui/material";
import { Database, Download, RefreshCw, ShieldAlert, AlertTriangle } from "lucide-react";
import { Navigate } from "react-router-dom";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import { hasPermission } from "../services/auth";
import "./css/DatabaseRestorePoint.css";

const dateText = (value) => value ? new Date(value).toLocaleString() : "—";
const sizeText = (value) => value ? `${(Number(value) / 1024 / 1024).toFixed(2)} MB` : "—";

export default function DatabaseRestorePoint() {
  const [collapsed, setCollapsed] = useState(false); 
  const [openMenu, setOpenMenu] = useState(null);
  const [status, setStatus] = useState(null); 
  const [backups, setBackups] = useState([]); 
  const [tables, setTables] = useState([]); 
  const [loading, setLoading] = useState(true);
  
  const [backupState, setBackupState] = useState("IDLE"); 
  const [backupError, setBackupError] = useState(""); 
  const [backupScope, setBackupScope] = useState("ALL_TABLES"); 
  const [selectedTables, setSelectedTables] = useState([]);
  
  const [message, setMessage] = useState(null); 
  const [tab, setTab] = useState(0); 
  const [selectedId, setSelectedId] = useState(""); 
  const [preview, setPreview] = useState(null); 
  const [previewing, setPreviewing] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const canView = hasPermission("settings.db_restore_point.view"); 
  const canCreate = hasPermission("settings.db_restore_point.create"); 
  const canRestore = hasPermission("settings.db_restore_point.restore");

  const load = useCallback(async () => { 
    setLoading(true); 
    try { 
      const [summary, history, tableResponse] = await Promise.all([
        API.get("/database-backup/status"), 
        API.get("/database-backup/list"), 
        API.get("/database-backup/tables")
      ]); 
      setStatus(summary.data); 
      setBackups(history.data?.backups || []); 
      setTables(tableResponse.data?.tables || []); 
    } catch (error) { 
      setMessage({ type: "error", text: error.response?.data?.message || "Unable to load backup information." }); 
    } finally { 
      setLoading(false); 
    } 
  }, []);

  useEffect(() => { if (canView) load(); }, [canView, load]);

  const createBackup = async () => { 
    setBackupState("STARTING"); 
    setBackupError(""); 
    setMessage(null); 
    try { 
      setBackupState("RUNNING"); 
      const payload = backupScope === "SELECTED_TABLES" ? { scope: backupScope, tables: selectedTables } : { scope: "ALL_TABLES" }; 
      const response = await API.post("/database-backup/create", payload); 
      setBackupState("SUCCESS"); 
      setMessage({ type: "success", text: response.data?.message || "Database backup created successfully." }); 
      await load(); 
    } catch (error) { 
      const reason = error.response?.data?.message || "Backup creation failed."; 
      setBackupState("FAILED"); 
      setBackupError(reason); 
      setMessage({ type: "error", text: reason }); 
    } 
  };

  const previewRestore = async (id) => { 
    setMessage(null); 
    setPreview(null); 
    setPreviewing(true); 
    try { 
      const response = await API.post(`/database-backup/${id}/preview`); 
      setPreview(response.data); 
    } catch (error) { 
      setMessage({ type: "error", text: error.response?.data?.message || "Safe restore preview is unavailable." }); 
    } finally { 
      setPreviewing(false); 
    } 
  };

  // Handler to perform direct Production Restore
  const executeProductionRestore = async () => {
    if (!preview?.backup_id) return;
    if (!window.confirm("Are you sure you want to restore this backup into live PRODUCTION? A safety snapshot will be taken automatically.")) return;
    
    setRestoring(true);
    setMessage(null);
    try {
      const response = await API.post("/database-backup/restore", {
        backup_id: preview.backup_id,
        confirmation: "RESTORE_PRODUCTION"
      });
      setMessage({ type: "success", text: response.data?.message || "Production database restored successfully." });
      setPreview(null);
      await load();
    } catch (error) {
      setMessage({ type: "error", text: error.response?.data?.message || "Production restore failed." });
    } finally {
      setRestoring(false);
    }
  };

  const download = async (id, name) => { 
    try { 
      const response = await API.get(`/database-backup/download/${id}`, { responseType: "blob" }); 
      const url = URL.createObjectURL(response.data); 
      const link = document.createElement("a"); 
      link.href = url; 
      link.download = name; 
      link.click(); 
      URL.revokeObjectURL(url); 
    } catch (error) { 
      setMessage({ type: "error", text: error.response?.data?.message || "Download failed." }); 
    } 
  };

  const toggleTable = (name) => setSelectedTables((current) => current.includes(name) ? current.filter((item) => item !== name) : [...current, name]);

  if (!canView) return <Navigate to="/gst" replace />;
  const successful = backups.filter((item) => item.status === "SUCCESS"); 
  const selected = successful.find((item) => String(item.id) === String(selectedId)); 
  const running = ["STARTING", "RUNNING"].includes(backupState);

  return (
    <div className="container-fluid">
      <div className="row">
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />
        <div className="col-lg-12">
          <Sidebar collapsed={collapsed} setCollapsed={setCollapsed} openMenu={openMenu} setOpenMenu={setOpenMenu} />
          <main className="main-content mt-5 db-restore-main">
            <div className="container-fluid">
              <div className="d-flex justify-content-between align-items-start mb-3">
                <div>
                  <div className="header-title-page">Database Backup &amp; Restore</div>
                  <p className="text-muted">Manage database backups, restore points and cleanup operations</p>
                </div>
                <Button onClick={load} startIcon={<RefreshCw size={16} />} disabled={loading || running}>Refresh</Button>
              </div>

              {message && <Alert severity={message.type} className="mb-3" onClose={() => setMessage(null)}>{message.text}</Alert>}

              <div className="db-stat-grid">
                <div className="db-stat"><span>DATABASE</span><strong>{status?.database || "—"}</strong><small>{status?.engine || "MySQL 8.0"}</small></div>
                <div className="db-stat"><span>TOTAL TABLES</span><strong>{status?.total_tables ?? "—"}</strong><small>Application tables</small></div>
                <div className="db-stat"><span>LAST BACKUP</span><strong>{dateText(status?.last_backup?.completed_at)}</strong><small>{status?.last_backup?.backup_type || "No successful backup"}</small></div>
                <div className="db-stat"><span>BACKUP LOCATION</span><strong className="path-value">{status?.backup_location || "—"}</strong><small>Server-side storage</small></div>
              </div>

              <div className="db-panel">
                <Tabs value={tab} onChange={(_, value) => setTab(value)}>
                  <Tab label="Backup & Restore" />
                  <Tab label="Information" />
                </Tabs>

                {tab === 1 ? (
                  <div className="db-info">
                    <h5>Backup safety</h5>
                    <p><b>Full Backup:</b> Complete configured database snapshot.</p>
                    <p><b>Selected Tables:</b> Server validates every selected name against the configured database.</p>
                    <p><b>Restore Preview:</b> Uses an isolated staging database to validate files prior to production application.</p>
                    <p><b>Restore Safety:</b> Production restores automatically generate an emergency rollback snapshot before executing.</p>
                  </div>
                ) : (
                  <>
                    <div className="db-actions">
                      <div>
                        <h5>BACKUP</h5>
                        <p>Create a compressed backup without changing business data.</p>
                        <RadioGroup row value={backupScope} onChange={(event) => setBackupScope(event.target.value)}>
                          <FormControlLabel value="ALL_TABLES" control={<Radio />} label="All Tables" />
                          <FormControlLabel value="SELECTED_TABLES" control={<Radio />} label="Selected Tables" />
                        </RadioGroup>
                        
                        {backupScope === "SELECTED_TABLES" && (
                          <div className="table-picker">
                            <div className="table-picker-actions">
                              <Button size="small" onClick={() => setSelectedTables(tables)}>Select all</Button>
                              <Button size="small" onClick={() => setSelectedTables([])}>Clear</Button>
                            </div>
                            <FormGroup>
                              {tables.map((name) => (
                                <FormControlLabel key={name} control={<Checkbox checked={selectedTables.includes(name)} onChange={() => toggleTable(name)} />} label={name} />
                              ))}
                            </FormGroup>
                            {!tables.length && <small>No tables available.</small>}
                          </div>
                        )}

                        <Button variant="contained" onClick={createBackup} disabled={!canCreate || running || (backupScope === "SELECTED_TABLES" && !selectedTables.length)} startIcon={running ? <CircularProgress size={16} color="inherit" /> : <Database size={17} />}>
                          {running ? "Creating backup..." : "CREATE BACKUP"}
                        </Button>

                        <div className="backup-progress" aria-live="polite">
                          <div className="progress-label">{backupState === "STARTING" ? "Starting backup…" : backupState === "RUNNING" ? "Creating database backup…" : backupState === "SUCCESS" ? "Backup completed successfully." : backupState === "FAILED" ? "Backup failed." : "Ready"}</div>
                          {running && <LinearProgress />}
                          {backupState === "RUNNING" && <small>Cancellation is not supported by the current backend.</small>}
                          {backupError && <Alert severity="error" className="mt-2">{backupError}</Alert>}
                        </div>
                      </div>

                      <div className="restore-action">
                        <h5>RESTORE POINT</h5>
                        <p>Select a successful backup to validate it and request a safe isolated restore preview.</p>
                        <TextField select fullWidth size="small" label="Select successful backup" InputLabelProps={{ shrink: true }} value={selectedId} onChange={(event) => setSelectedId(event.target.value)} SelectProps={{ native: true }} disabled={!canRestore || !successful.length || previewing}>
                          <option value="">Choose a backup...</option>
                          {successful.map((item) => (
                            <option key={item.id} value={item.id}>{item.id} · {item.backup_name} · {dateText(item.created_at)}</option>
                          ))}
                        </TextField>
                        <Button color="primary" variant="outlined" disabled={!canRestore || !selected || previewing} startIcon={previewing ? <CircularProgress size={16} /> : <ShieldAlert size={17} />} onClick={() => previewRestore(selected.id)}>
                          {previewing ? "VALIDATING RESTORE..." : "PREVIEW RESTORE"}
                        </Button>
                      </div>
                    </div>

                    <h5 className="history-title">BACKUP HISTORY</h5>
                    <div className="table-responsive">
                      <table className="table align-middle">
                        <thead>
                          <tr><th>ID</th><th>Backup Name</th><th>Type</th><th>Created</th><th>Size</th><th>Status</th><th>Duration</th><th>Actions</th></tr>
                        </thead>
                        <tbody>
                          {loading ? (
                            <tr><td colSpan="8" className="text-center">Loading...</td></tr>
                          ) : backups.map((item) => (
                            <tr key={item.id}>
                              <td>{item.id}</td>
                              <td>{item.backup_name}</td>
                              <td>{item.backup_type}</td>
                              <td>{dateText(item.created_at)}</td>
                              <td>{sizeText(item.file_size)}</td>
                              <td><span className={`status-pill ${String(item.status).toLowerCase()}`}>{item.status}</span></td>
                              <td>{item.duration ? `${item.duration}s` : "—"}</td>
                              <td>
                                {item.status === "SUCCESS" && (
                                  <>
                                    <Button size="small" onClick={() => download(item.id, item.backup_name)} startIcon={<Download size={15} />}>Download</Button>
                                    <Button size="small" onClick={() => { setSelectedId(item.id); previewRestore(item.id); }}>Preview Restore</Button>
                                  </>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            </div>
          </main>
        </div>
        <Footer />
      </div>

      {/* RESTORE PREVIEW & CONFIRMATION DIALOG */}
      <Dialog open={Boolean(preview)} onClose={() => setPreview(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Restore Preview & Confirmation</DialogTitle>
        <DialogContent>
          <Alert severity="info" className="mb-3">
            This preview was validated in an isolated staging database. Live production data has <b>NOT</b> been modified yet.
          </Alert>
          {preview && (
            <>
              <p><b>Backup:</b> {preview.backup_name}</p>
              <p><b>Created:</b> {dateText(preview.created_at)}</p>
              <p><b>Size:</b> {sizeText(preview.file_size)}</p>
              <p><b>Source Database:</b> {preview.database_name || status?.database}</p>
              <p><b>Staging Database:</b> {preview.staging_database || "—"}</p>
              <p><b>Tables:</b> {preview.tables ?? "—"}</p>
              <p><b>Tables Affected:</b> {preview.tables_affected ?? "—"}</p>
              <p><b>Validation Status:</b> {preview.validation_status || "—"}</p>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPreview(null)} disabled={restoring}>CANCEL</Button>
          <Button 
            color="error" 
            variant="contained" 
            onClick={executeProductionRestore} 
            disabled={restoring || !canRestore}
            startIcon={restoring ? <CircularProgress size={16} color="inherit" /> : <AlertTriangle size={16} />}
          >
            {restoring ? "RESTORING PRODUCTION..." : "RESTORE TO PRODUCTION"}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}