import { useState, useRef, useEffect } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import Papa from "papaparse";
import axios from "axios";
import API from "../api/api";               //  NEW GLOBAL API IMPORT
import {
  LinearProgress,
  Box,
  Typography,
  Button,
  Paper,
  Alert,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import { FaCloudUploadAlt } from "react-icons/fa";
import DataTable from "react-data-table-component";
import "./css/UploadSheet.css";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import tableCustomStyles from "../components/common/tableStyles";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import dayjs from "dayjs";
import DescriptionIcon from "@mui/icons-material/Description";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import Swal from "sweetalert2";
import API_BASE_URL, { SERVER_BASE_URL } from "../config/api.config";

const VALIDATION_DIALOG_MESSAGES = [
  "Uploading file...",
  "Reading CSV...",
  "Validating data...",
  "Checking duplicates...",
  "Preparing validation summary...",
];

const createInitialPipelineState = () => ({
  phase: "idle",
  busy: false,
  message: "Idle",
  progress: 0,
  showValidationSummary: false,
  validationStepIndex: 0,
});

const formatPipelineStatus = ({ status, step, insertedRows, totalRows, insertPercent }) => {
  const normalizedStatus = String(status || "").toLowerCase();
  const rawStep = String(step || "").trim();
  const normalizedStep = rawStep.toLowerCase();

  if (normalizedStatus === "inserting") {
    if (insertedRows > 0 && totalRows > 0) {
      return `Database Insert: ${insertedRows} / ${totalRows} (${insertPercent || 0}%)`;
    }
    return "Database insert in progress...";
  }

  if (rawStep) {
    if (normalizedStep.includes("prediction")) return `Prediction running... ${rawStep}`;
    if (normalizedStep.includes("justification")) return `Generating fraud justification... ${rawStep}`;
    if (normalizedStep.includes("queue")) return `Queued... ${rawStep}`;
    return rawStep;
  }

  if (normalizedStatus === "queued") return "Queued...";
  if (normalizedStatus === "running") return "Preparing processing...";
  if (normalizedStatus === "prediction") return "Prediction running...";
  if (normalizedStatus === "justification") return "Generating fraud justification...";
  if (normalizedStatus === "completed" || normalizedStatus === "success") return "Completed";
  if (normalizedStatus === "failed") return "Processing failed.";
  if (!normalizedStatus) return "Preparing processing...";

  return `${normalizedStatus.charAt(0).toUpperCase()}${normalizedStatus.slice(1)}...`;
};

export default function UploadSheet() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [file, setFile] = useState(null);
  const [previewRows, setPreviewRows] = useState([]);
  const [uploadResponse, setUploadResponse] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [pipelineState, setPipelineState] = useState(createInitialPipelineState);
  const [runId, setRunId] = useState(null);
  const terminalRunIdRef = useRef(null);
  const multitaxRefreshStartedRef = useRef(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [mergedData, setMergedData] = useState([]);
  const [excelUrl, setExcelUrl] = useState("");
  const [showMergedTable, setShowMergedTable] = useState(false);
  const [filterText, setFilterText] = useState("");
  const [conflictCount, setConflictCount] = useState(null);

  const [taxType, setTaxType] = useState("gst");
  const [startDate, setStartDate] = useState(null);
  const [endDate, setEndDate] = useState(null);

  const [segmentationRunning, setSegmentationRunning] = useState(false);
  const [segmentationMsg, setSegmentationMsg] = useState("");
  const [segmentationJobId, setSegmentationJobId] = useState(null);
  const [segmentationProgress, setSegmentationProgress] = useState(0);

  const parseManualDate = (value) => {
    if (!value) return null;
    const parsed = dayjs(value, ["DD/MM/YYYY", "YYYY-MM-DD"], true);
    return parsed.isValid() ? parsed : null;
  };


  const FILE_BASE_URL = SERVER_BASE_URL;


  const [sampleLinks, setSampleLinks] = useState({
    gst: "",
    swt: "",
    cit: "",
  });

  const fileInputRef = useRef();
  const validationCompletionTimeoutRef = useRef(null);
  const validationStepIntervalRef = useRef(null);
  const segmentationPollIntervalRef = useRef(null);
  const pipelinePollIntervalRef = useRef(null);
  const accessToken = localStorage.getItem("access_token");

  const showAlert = (icon, title, text) =>
    Swal.fire({
      icon,
      title,
      text,
      confirmButtonColor: "#6A00FF",
    });

  const showHistoryValidationAlert = async (message, missingYears = []) => {
    const years = Array.isArray(missingYears)
      ? missingYears.filter((year) => year !== null && year !== undefined)
      : [];

    await Swal.fire({
      icon: "error",
      title: "Validation Failed",
      html:
        years.length > 0
          ? `${message}<br/><br/><strong>Missing Years:</strong><br/>${years.join("<br/>")}`
          : message,
      confirmButtonColor: "#6A00FF",
    });
  };

  const resetUploadSheet = () => {
    terminalRunIdRef.current = null;
    multitaxRefreshStartedRef.current = false;

    if (validationCompletionTimeoutRef.current) {
      window.clearTimeout(validationCompletionTimeoutRef.current);
      validationCompletionTimeoutRef.current = null;
    }

    if (validationStepIntervalRef.current) {
      window.clearInterval(validationStepIntervalRef.current);
      validationStepIntervalRef.current = null;
    }

    if (segmentationPollIntervalRef.current) {
      window.clearInterval(segmentationPollIntervalRef.current);
      segmentationPollIntervalRef.current = null;
    }

    if (pipelinePollIntervalRef.current) {
      window.clearInterval(pipelinePollIntervalRef.current);
      pipelinePollIntervalRef.current = null;
    }

    setFile(null);
    setPreviewRows([]);
    setUploadResponse(null);
    setError("");
    setInfo("");
    setPipelineState(createInitialPipelineState());
    setRunId(null);
    setPreviewVisible(false);
    setMergedData([]);
    setExcelUrl("");
    setShowMergedTable(false);
    setFilterText("");
    setConflictCount(null);
    setTaxType("gst");
    setStartDate(null);
    setEndDate(null);
    setSegmentationRunning(false);
    setSegmentationMsg("");
    setSegmentationJobId(null);
    setSegmentationProgress(0);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const validateDateRangeIfProvided = async () => {
    const hasStart = !!startDate;
    const hasEnd = !!endDate;

    if (hasStart !== hasEnd) {
      await showAlert("error", "Missing Date", "Please enter both From and To dates.");
      return false;
    }

    if (!hasStart && !hasEnd) return true; // dates are optional for validate/run

    const parsedStart = dayjs(startDate);
    const parsedEnd = dayjs(endDate);

    if (!parsedStart.isValid() || !parsedEnd.isValid()) {
      await showAlert("error", "Invalid Date", "Please enter valid dates (DD/MM/YYYY).");
      return false;
    }

    if (parsedEnd.isBefore(parsedStart, "day")) {
      await showAlert("error", "Invalid Date Range", "To date must be on/after From date.");
      return false;
    }

    return true;
  };

// ---------------------------------
// CREATE SEGMENTATION
// ---------------------------------
const handleCreateSegmentation = async () => {
  setError("");
  setInfo("");
  setSegmentationMsg("");
  setSegmentationProgress(0);

  if (!startDate || !endDate) {
    await showAlert("error", "Missing Date", "Please enter both dates.");
    return;
  }

  const parsedStart = dayjs(startDate);
  const parsedEnd = dayjs(endDate);

  if (!parsedStart.isValid() || !parsedEnd.isValid()) {
    await showAlert(
      "error",
      "Invalid Date",
      "Please enter valid dates in YYYY-MM-DD format."
    );
    return;
  }

  const formattedStartDate = parsedStart.format("YYYY-MM-DD");
  const formattedEndDate = parsedEnd.format("YYYY-MM-DD");

  setSegmentationRunning(true);

  try {
    setSegmentationMsg("Validating historical data...");

    await API.post("/segmentation/validate-history", {
      tax_type: String(taxType || "").toUpperCase(),
      start_date: formattedStartDate,
      end_date: formattedEndDate,
    });

    setSegmentationMsg("Queueing segmentation job...");

    const startRes = await API.post("/segmentation/start", {
      start_date: formattedStartDate,
      end_date: formattedEndDate,
    });

    setSegmentationJobId(startRes.data.job_id);
    setSegmentationMsg("Queued: Waiting for background worker...");
    setSegmentationProgress(0);
  } catch (err) {
    const validationData = err.response?.data;
    const validationMsg = validationData?.message || "Past 3 years data not available.";
    const missingYears = validationData?.missing_years || [];
    const isHistoryValidationError =
      err.response?.config?.url?.includes("/segmentation/validate-history") &&
      validationData?.valid === false;

    if (isHistoryValidationError) {
      setSegmentationRunning(false);
      setError(validationMsg);
      await showHistoryValidationAlert(validationMsg, missingYears);
      return;
    }

    const msg = validationData?.error || validationData?.message || err.message || "Segmentation failed.";
    setSegmentationRunning(false);
    setSegmentationJobId(null);
    setError(msg);
    await showAlert("error", "Segmentation Failed", msg);
  }
};

useEffect(() => {
  if (!segmentationJobId) return undefined;

  let isActive = true;
  let pollInFlight = false;

  const pollStatus = async () => {
    if (!isActive || pollInFlight) return;
    pollInFlight = true;

    try {
      const res = await API.get(`/segmentation/status/${segmentationJobId}`);
      if (!isActive) return;

      const status = String(res.data?.status || "Queued");
      const normalizedStatus = status.toLowerCase();
      const currentStep = res.data?.current_step || "";
      const nextProgress = Number(res.data?.percentage ?? 0);
      const totalSegmented = Number(res.data?.total_segmented ?? 0);
      const nextError = res.data?.error || res.data?.message;

      setSegmentationProgress(Number.isFinite(nextProgress) ? nextProgress : 0);
      setSegmentationMsg(currentStep ? `${status}: ${currentStep}` : status);

      if (normalizedStatus === "completed") {
        setSegmentationRunning(false);
        setSegmentationJobId(null);
        setSegmentationProgress(100);
        setSegmentationMsg(`Segmentation Completed Successfully. Total segmented: ${totalSegmented}`);
        setInfo("Segmentation completed successfully.");
        const result = await showAlert("success", "Success", "Segmentation completed successfully.");
        if (result?.isConfirmed) {
          resetUploadSheet();
        }
        return;
      }

      if (normalizedStatus === "failed") {
        const msg = nextError || "Segmentation failed.";
        setSegmentationRunning(false);
        setSegmentationJobId(null);
        setError(msg);
        await showAlert("error", "Segmentation Failed", msg);
      }
    } catch (err) {
      if (!isActive) return;
      const msg = err.response?.data?.error || err.response?.data?.message || err.message || "Segmentation status check failed.";
      setSegmentationRunning(false);
      setSegmentationJobId(null);
      setError(msg);
      await showAlert("error", "Segmentation Failed", msg);
    } finally {
      pollInFlight = false;
    }
  };

  pollStatus();
  segmentationPollIntervalRef.current = window.setInterval(pollStatus, 3000);

  return () => {
    isActive = false;
    if (segmentationPollIntervalRef.current) {
      window.clearInterval(segmentationPollIntervalRef.current);
      segmentationPollIntervalRef.current = null;
    }
  };
}, [segmentationJobId]);

  // -------------------------------------------------
  //  NEW DYNAMIC BASE PATH (NO HOST, NO LOCALHOST)
  // -------------------------------------------------
  const TAX_PATH = `/${taxType}`;
  // -------------------------------------------------

  const canProcess =
    uploadResponse?.valid === true &&
    Number(uploadResponse?.valid_records || 0) > 0;
  const validating =
    pipelineState.phase === "validating" || pipelineState.phase === "validation-complete";
  const processing = pipelineState.phase === "processing";
  const controlsDisabled = pipelineState.busy;
  const statusMsg = pipelineState.message;
  const progress = pipelineState.progress;
  const showValidationSummary = pipelineState.showValidationSummary;
  const validationDialogOpen = validating;
  const validationDialogMessage =
    pipelineState.phase === "validation-complete"
      ? "Validation summary ready."
      : VALIDATION_DIALOG_MESSAGES[pipelineState.validationStepIndex] || VALIDATION_DIALOG_MESSAGES[0];

  // -------------------------------
  // File selection + preview
  // -------------------------------
  const handleFileChosen = (chosenFile) => {
    if (controlsDisabled) return;
    setError("");
    setInfo("");
    if (!chosenFile) return;

    const lowerName = chosenFile.name.toLowerCase();
    const isSupported = lowerName.endsWith(".csv") || lowerName.endsWith(".parquet");
    if (!isSupported) {
      setError("Only CSV and Parquet files are supported.");
      setFile(null);
      return;
    }

    setFile(chosenFile);
    setPreviewVisible(false);
  };

  const handleFileClick = () => {
    if (controlsDisabled) return;
    fileInputRef.current?.click();
  };

  const handlePreview = () => {
    if (controlsDisabled) return;
    if (!file) return setError("Please select a file first.");

    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (result) => {
        setPreviewRows(result.data.slice(0, 10));
        setPreviewVisible(true);
      },
    });
  };


// -------------------------------
// Upload + validate (FIXED)
// -------------------------------
  const handleUploadPreview = async () => {
  if (pipelineState.busy || validating) return;
  setError("");
  setInfo("");
  setConflictCount(null);

  if (!file) return setError("Please select a file.");

  // Dates are optional for validate/run, but if provided they must be valid and ordered.
  if (!(await validateDateRangeIfProvided())) return;

  const formData = new FormData();
  formData.append("file", file);

  if (validationCompletionTimeoutRef.current) {
    window.clearTimeout(validationCompletionTimeoutRef.current);
    validationCompletionTimeoutRef.current = null;
  }

  setPipelineState({
    phase: "validating",
    busy: true,
    message: "Uploading file...",
    progress: 0,
    showValidationSummary: false,
    validationStepIndex: 0,
  });

  try {
    setInfo("Validating file...");

    const taxTypeLower = String(taxType || "").toLowerCase();
    const validateApi = `${API_BASE_URL}/${taxTypeLower}/validate`;
    console.log("Selected Tax Type:", taxType);
    console.log("Validate API:", validateApi);

    const res = await API.post(`${TAX_PATH}/validate`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });

    setUploadResponse(res.data);
    setConflictCount(Number(res.data.db_financial_differences_count ?? 0));
    setPipelineState((prev) => ({
      ...prev,
      phase: "validation-complete",
      busy: true,
      message: "Validation Complete",
      showValidationSummary: false,
    }));

    validationCompletionTimeoutRef.current = window.setTimeout(() => {
      setPreviewVisible(false);
      setInfo(res.data.valid ? "Validation successful." : "Validation completed.");
      setPipelineState((prev) => ({
        ...prev,
        phase: "ready",
        busy: false,
        message: res.data.valid ? "Validation successful." : "Validation completed.",
        showValidationSummary: true,
      }));
      validationCompletionTimeoutRef.current = null;
    }, 700);
  } catch (err) {
    const msg =
      err.response?.data?.message ||
      err.response?.data?.error ||
      err.message ||
      "Validation failed.";
    setPipelineState(createInitialPipelineState());
    setError(msg);
    showAlert("error", "Validation Failed", msg);
  }
};




  // -------------------------------
  // Fetch Sample Files
  // -------------------------------
  const fetchSampleFiles = async () => {
    try {
      const res = await API.get("/segmentation/get-sample-files"); //  FIXED: remove localhost
      setSampleLinks({
        gst: res.data.gst.url,
        swt: res.data.swt.url,
        cit: res.data.cit.url,
      });
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchSampleFiles();
  }, []);

  useEffect(() => {
    if (pipelineState.phase !== "validating") return undefined;

    validationStepIntervalRef.current = window.setInterval(() => {
      setPipelineState((prev) => {
        if (prev.phase !== "validating") return prev;
        return {
          ...prev,
          validationStepIndex: (prev.validationStepIndex + 1) % VALIDATION_DIALOG_MESSAGES.length,
        };
      });
    }, 800);

    return () => {
      if (validationStepIntervalRef.current) {
        window.clearInterval(validationStepIntervalRef.current);
        validationStepIntervalRef.current = null;
      }
    };
  }, [pipelineState.phase]);

  useEffect(() => {
    if (!pipelineState.busy) return undefined;

    const handleBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [pipelineState.busy]);

  useEffect(() => () => {
    if (validationCompletionTimeoutRef.current) {
      window.clearTimeout(validationCompletionTimeoutRef.current);
      validationCompletionTimeoutRef.current = null;
    }
    if (validationStepIntervalRef.current) {
      window.clearInterval(validationStepIntervalRef.current);
      validationStepIntervalRef.current = null;
    }
    if (segmentationPollIntervalRef.current) {
      window.clearInterval(segmentationPollIntervalRef.current);
      segmentationPollIntervalRef.current = null;
    }
    if (pipelinePollIntervalRef.current) {
      window.clearInterval(pipelinePollIntervalRef.current);
      pipelinePollIntervalRef.current = null;
    }
  }, []);

  const downloadFile = async (url, fileName) => {
    const response = await axios.get(url, {
      responseType: "blob",
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    const link = document.createElement("a");
    link.href = window.URL.createObjectURL(new Blob([response.data]));
    link.download = fileName;
    link.click();
  };

  const downloadInvalidCsv = async (removedDataFile) => {
    try {
      const raw = String(removedDataFile || "").trim();
      if (!raw) throw new Error("Missing filename");

      const filename = raw
        .replace(/\\/g, "/")
        .split("/")
        .filter(Boolean)
        .pop();

      const taxTypeLower = String(taxType || "").toLowerCase();
      const primaryUrl = `${API_BASE_URL}/${taxTypeLower}/download/${encodeURIComponent(filename)}`;
      const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined;

      const res = await axios.get(primaryUrl, { responseType: "blob", headers });

      const ct = String(res?.headers?.["content-type"] || "");
      if (ct.includes("application/json")) {
        let txt = "";
        try {
          txt = await new Response(res.data).text();
        } catch {
          txt = "";
        }
        throw new Error(txt || "Download failed.");
      }

      const blob = res.data;
      const link = document.createElement("a");
      link.href = window.URL.createObjectURL(new Blob([blob]));
      link.download = filename;
      link.click();
    } catch (e) {
      const msg =
        e?.response?.status === 404
          ? "File not found on server (404)."
          : e?.response?.data?.message || e?.message || "Download failed.";
      await showAlert("error", "Download Failed", msg);
    }
  };

  // -------------------------------
  // Reset everything
  // -------------------------------
  const handleBack = () => {
    resetUploadSheet();
  };

  // Legacy client-side processing flow removed.
  useEffect(() => {
    if (!runId) return;

    let isActive = true;
    let pollInFlight = false;
    pipelinePollIntervalRef.current = setInterval(async () => {
      if (
        !isActive ||
        pollInFlight ||
        terminalRunIdRef.current === runId ||
        multitaxRefreshStartedRef.current
      ) {
        return;
      }

      pollInFlight = true;
      try {
        const res = await API.get(`${TAX_PATH}/status/${runId}`);
        if (
          !isActive ||
          terminalRunIdRef.current === runId ||
          multitaxRefreshStartedRef.current
        ) {
          return;
        }

        const nextProgress = Number(res.data?.progress ?? 0);
        const nextStatus = String(res.data?.status || "running").toLowerCase();
        const nextStep = res.data?.step || "";
        const insertedRows = Number(res.data?.inserted_rows ?? 0);
        const totalRows = Number(res.data?.total_rows ?? 0);
        const insertPercent = Number(res.data?.insert_percent ?? 0);
        const nextError = res.data?.error;
        const isCompleted =
          nextProgress >= 100 ||
          insertPercent >= 100 ||
          (insertedRows > 0 && totalRows > 0 && insertedRows >= totalRows) ||
          nextStatus === "completed" ||
          nextStatus === "success";
        const isFailed = nextStatus === "failed";
        const nextMessage = formatPipelineStatus({
          status: nextStatus,
          step: nextStep,
          insertedRows,
          totalRows,
          insertPercent,
        });

        if (isCompleted || isFailed) {
          terminalRunIdRef.current = runId;
          if (pipelinePollIntervalRef.current) {
            clearInterval(pipelinePollIntervalRef.current);
            pipelinePollIntervalRef.current = null;
          }
          setPipelineState((prev) => ({
            ...prev,
            phase: isFailed ? "failed" : "completed",
            busy: false,
            message: isFailed ? (nextError || "Processing failed.") : "Completed",
            progress: Number.isFinite(nextProgress) ? nextProgress : prev.progress,
            showValidationSummary: true,
          }));

          if (isCompleted && !isFailed) {
            try {
              multitaxRefreshStartedRef.current = true;
              setPipelineState((prev) => ({
                ...prev,
                phase: "processing",
                busy: true,
                message: "Processing MultiTax Calculation...",
                progress: 100,
                showValidationSummary: true,
              }));

              const refreshResponse = await API.post("/multitax/refresh");
              console.log("Refresh response", refreshResponse?.data);
              const refreshJobId = refreshResponse?.data?.job_id;
              console.log("Job ID", refreshJobId);

              if (!refreshJobId) {
                throw new Error("MultiTax refresh did not return a job_id.");
              }

              console.log("Starting polling...");
              while (isActive) {
                console.log("Polling", refreshJobId);
                const statusResponse = await API.get("/multitax/refresh/status", {
                  params: { job_id: refreshJobId },
                });
                const refreshStatus = String(statusResponse?.data?.status || "").toLowerCase();
                const refreshDetail =
                  statusResponse?.data?.detail ||
                  statusResponse?.data?.message ||
                  "MultiTax integration failed.";

                setPipelineState((prev) => ({
                  ...prev,
                  phase: "processing",
                  busy: refreshStatus === "running",
                  message:
                    refreshStatus === "completed"
                      ? "Completed"
                      : "Process MultiTax Integration...",
                  progress: 100,
                  showValidationSummary: true,
                }));

                if (refreshStatus === "completed") {
                  setRunId(null);
                  const result = await showAlert("success", "Completed", "Upload completed successfully.");
                  if (result?.isConfirmed) {
                    resetUploadSheet();
                  }
                  break;
                }

                if (refreshStatus === "error") {
                  const msg = `MultiTax integration failed.${refreshDetail}`;
                  setRunId(null);
                  setError(msg);
                  setPipelineState((prev) => ({
                    ...prev,
                    phase: "ready",
                    busy: false,
                    message: msg,
                    progress: 100,
                    showValidationSummary: true,
                  }));
                  await showAlert("error", "MultiTax Integration Failed", msg);
                  break;
                }

                await new Promise((resolve) => window.setTimeout(resolve, 3000));
              }
            } catch (e) {
              setRunId(null);
              const msg =
                e?.response?.data?.detail ||
                e?.response?.data?.message ||
                e?.response?.data?.error ||
                e?.message ||
                "MultiTax integration failed.";
              console.error("[MultiTax] refresh failed:", e);
              setError(`MultiTax integration failed.${msg}`);
              setPipelineState((prev) => ({
                ...prev,
                phase: "ready",
                busy: false,
                message: "MultiTax integration failed.",
                progress: 100,
                showValidationSummary: true,
              }));
              await showAlert(
                "error",
                "MultiTax Integration Failed",
                `MultiTax integration failed.${msg}`
              );
            }
          } else {
            setRunId(null);
            const msg = nextError || "Processing failed.";
            setError(msg);
            await showAlert("error", "Failed", msg);
          }
          return;
        }

        setPipelineState((prev) => ({
          ...prev,
          phase: "processing",
          busy: true,
          progress: Number.isFinite(nextProgress) ? nextProgress : 0,
          message: nextMessage,
          showValidationSummary: true,
        }));
      } catch (err) {
        if (!isActive) return;
        if (pipelinePollIntervalRef.current) {
          clearInterval(pipelinePollIntervalRef.current);
          pipelinePollIntervalRef.current = null;
        }
        const status = err?.response?.status;
        const msg =
          status === 404
            ? "GST run status was not found. The background worker may have stopped unexpectedly."
            : err?.response?.data?.message ||
              err?.response?.data?.error ||
              err?.message ||
              "Status check failed.";
        setRunId(null);
        setError(msg);
        setPipelineState((prev) => ({
          ...prev,
          phase: "failed",
          busy: false,
          message: msg,
          progress: 100,
          showValidationSummary: true,
        }));
        await showAlert("error", "Failed", msg);
      } finally {
        pollInFlight = false;
      }
    }, 5000);

    return () => {
      isActive = false;
      if (pipelinePollIntervalRef.current) {
        clearInterval(pipelinePollIntervalRef.current);
        pipelinePollIntervalRef.current = null;
      }
    };
  }, [runId, TAX_PATH]);

  const handleProcess = async () => {
    if (pipelineState.busy) return;

    const requestTraceId = `swt-run-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    console.log("[SWT FRONTEND] handleProcess called", {
      requestTraceId,
      timestamp: new Date().toISOString(),
      taxType,
      processing,
      runId,
    });
    if (!file) return setError("Please select a file first.");
    if (!uploadResponse?.valid) return setError("Please validate the file first.");
    if (Number(uploadResponse?.valid_records || 0) <= 0) {
      return setError("No valid records available to process.");
    }

    if (!startDate || !endDate) {
      await showAlert("error", "Missing Date", "Please enter both From and To dates.");
      return;
    }

    const parsedStart = dayjs(startDate);
    const parsedEnd = dayjs(endDate);

    if (!parsedStart.isValid() || !parsedEnd.isValid()) {
      await showAlert("error", "Invalid Date", "Please enter valid dates (DD/MM/YYYY).");
      return;
    }

    if (parsedEnd.isBefore(parsedStart, "day")) {
      await showAlert("error", "Invalid Date Range", "To date must be on/after From date.");
      return;
    }

    const getValidatedFileName = (resp) => {
      console.log("validate response =>", resp);

      const filename = resp?.validated_file;

      if (filename) {
        console.log("Using validated filename:", filename);
        return String(filename).trim();
      }

      return null;
    };

    const validatedFileName = getValidatedFileName(uploadResponse);
    if (!validatedFileName) {
      return setError("Validated file is missing. Please validate again.");
    }

    console.log(uploadResponse);

    setError("");
    terminalRunIdRef.current = null;
    multitaxRefreshStartedRef.current = false;
    setPipelineState((prev) => ({
      ...prev,
      phase: "processing",
      busy: true,
      progress: 0,
      message: "Queued...",
      showValidationSummary: true,
    }));

    const formData = new FormData();
    // IMPORTANT: run API expects the validated artifact name, not the raw uploaded file.
    formData.append("validated_file", validatedFileName);

    // Required for processing
    formData.append("date_from", parsedStart.format("YYYY-MM-DD"));
    formData.append("date_to", parsedEnd.format("YYYY-MM-DD"));

    try {
      const taxTypeLower = String(taxType || "").toLowerCase();
      const runApi = `${API_BASE_URL}/${taxTypeLower}/run`;
      console.log("Selected Tax Type:", taxType);
      console.log("Run API:", runApi);
      console.log("[SWT FRONTEND] POST /run", {
        requestTraceId,
        endpoint: `${TAX_PATH}/run`,
        validatedFileName,
        date_from: parsedStart.format("YYYY-MM-DD"),
        date_to: parsedEnd.format("YYYY-MM-DD"),
        timestamp: new Date().toISOString(),
      });

      const res = await API.post(`${TAX_PATH}/run`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      const nextRunId = res.data?.run_id;
      if (!nextRunId) throw new Error("Missing run_id from server.");

      setRunId(nextRunId);
      setPipelineState((prev) => ({
        ...prev,
        phase: "processing",
        busy: true,
        message: formatPipelineStatus({ status: res.data?.status || "queued", step: res.data?.step || "" }),
        showValidationSummary: true,
      }));
    } catch (err) {
      const msg =
        err.response?.data?.message ||
        err.response?.data?.error ||
        err.message ||
        "Run failed.";
      console.error("Run failed:", err?.response?.status, err?.response?.data || err);

      // If backend can't locate the validated artifact, fall back to uploading the raw file.
      // This keeps the UI working across environments where backend final_output isn't shared.
      const status = err?.response?.status;
      const errText = String(err?.response?.data?.error || err?.response?.data?.message || "");
      const looksLikeMissingValidatedFile =
        status === 404 && errText.toLowerCase().includes("validated_file not found");

      if (looksLikeMissingValidatedFile) {
        try {
          console.log("[SWT FRONTEND] POST /run fallback with raw file", {
            requestTraceId,
            endpoint: `${TAX_PATH}/run`,
            originalError: errText,
            timestamp: new Date().toISOString(),
          });
          const fallbackFormData = new FormData();
          fallbackFormData.append("file", file);
          if (startDate) fallbackFormData.append("date_from", dayjs(startDate).format("YYYY-MM-DD"));
          if (endDate) fallbackFormData.append("date_to", dayjs(endDate).format("YYYY-MM-DD"));

          const fallbackRes = await API.post(`${TAX_PATH}/run`, fallbackFormData, {
            headers: { "Content-Type": "multipart/form-data" },
          });

          const fallbackRunId = fallbackRes.data?.run_id;
          if (!fallbackRunId) throw new Error("Missing run_id from server.");

          terminalRunIdRef.current = null;
          multitaxRefreshStartedRef.current = false;
          setRunId(fallbackRunId);
          setPipelineState((prev) => ({
            ...prev,
            phase: "processing",
            busy: true,
            message: formatPipelineStatus({ status: fallbackRes.data?.status || "queued", step: fallbackRes.data?.step || "" }),
            showValidationSummary: true,
          }));
          return;
        } catch (fallbackErr) {
          const fallbackMsg =
            fallbackErr.response?.data?.message ||
            fallbackErr.response?.data?.error ||
            fallbackErr.message ||
            msg;
          setError(fallbackMsg);
          setPipelineState((prev) => ({
            ...prev,
            phase: "ready",
            busy: false,
            showValidationSummary: true,
          }));
          showAlert("error", "Run Failed", fallbackMsg);
          return;
        }
      }

      setError(msg);
      setPipelineState((prev) => ({
        ...prev,
        phase: "ready",
        busy: false,
        showValidationSummary: true,
      }));
      showAlert("error", "Run Failed", msg);
    }
  };


  // -------------------------------
  // FETCH MERGED DATA
  // -------------------------------
  const filteredData = mergedData.filter((item) =>
    Object.values(item).some((v) =>
      String(v).toLowerCase().includes(filterText.toLowerCase())
    )
  );

  const columns = [
    { name: "TIN", selector: (row) => row.Tin },
    { name: "Taxpayer Name", selector: (row) => row.Taxpayer_Name },
    { name: "Type", selector: (row) => row.Type },
    { name: "Segmentation", selector: (row) => row.Segmentation },
    { name: "Total Sales", selector: (row) => row.Total_Sales },
    { name: "GST Payable", selector: (row) => row.Gst_Payable },
    { name: "GST Refundable", selector: (row) => row.Gst_Refundable },
    {
      name: "Fraud",
      selector: (row) => row.Fraud,
      cell: (row) => (
        <span
          style={{
            color:
              row.Fraud === "Fraud Detected" ? "#ff4d4d" : "#036b48",
            fontWeight: "bold",
          }}
        >
          {row.Fraud}
        </span>
      ),
    },
    { name: "Risk Type", selector: (row) => row.Risk_Type },
    { name: "Fraud Reason", selector: (row) => row.Fraud_Reason },
  ];

  // ===============================
  // Render layout
  // ===============================
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
                  <div className="header-title-page">Upload Sheet</div>
                    <div className="d-flex gap-2">
                      <div className="d-flex flex-column align-items-start">
                        {/* Bootstrap Message */}
                        <small className="text-muted mt-2">
                          <strong>*Only after uploading GST, SWT & CIT files</strong>
                        </small>

                         <Button
                          variant="contained"
                          color="secondary"
                          onClick={handleCreateSegmentation}
                          disabled={segmentationRunning || controlsDisabled}
                          startIcon={
                            segmentationRunning ? (
                              <CircularProgress size={16} color="inherit" />
                            ) : null
                          }
                        >
                          {segmentationRunning ? "Segmenting..." : "Create Segmentation"}
                        </Button>

                        {(segmentationRunning || segmentationMsg) && (
                          <Paper sx={{ mt: 1.5, p: 1.5, width: "100%", minWidth: 280 }}>
                            <Typography variant="body2" sx={{ mb: 1 }}>
                              {segmentationMsg || "Queued..."}
                            </Typography>
                            <LinearProgress
                              variant="determinate"
                              value={Math.min(100, Math.max(0, segmentationProgress))}
                              sx={{ height: 8, borderRadius: 4 }}
                            />
                          </Paper>
                        )}

                      </div>
                      
                      <Button
                        component="a"
                        download
                        variant="contained"
                        size="small"
                        color="success"
                        startIcon={<DescriptionIcon />}
                        onClick={() => downloadFile(sampleLinks.gst, "sample_gst.csv")}
                        disabled={controlsDisabled}
                      >
                        Sample GST
                      </Button>

                      <Button
                        component="a"
                        download
                        variant="contained"
                        size="small"
                        color="success"
                        startIcon={<DescriptionIcon />}
                        onClick={() => downloadFile(sampleLinks.swt, "sample_swt.csv")}
                        disabled={controlsDisabled}
                      >
                        Sample SWT
                      </Button>

                      <Button
                        component="a"
                        download
                        variant="contained"
                        size="small"
                        color="success"
                        startIcon={<DescriptionIcon />}
                        onClick={() => downloadFile(sampleLinks.cit, "sample_cit.csv")}
                        disabled={controlsDisabled}
                      >
                        Sample CIT
                      </Button>

                    </div>
                  </div>


              <LocalizationProvider dateAdapter={AdapterDayjs}>
                <div className="row g-3 align-items-end">

                  {/* Tax Parameter Dropdown */}
                  <div className="col-lg-4 col-md-12">
                    <label htmlFor="taxSelect" className="form-label fw-bold">
                      Select Tax Parameter
                    </label>
                    <select
                      id="taxSelect"
                      className="form-select"
                      value={taxType}
                      onChange={(e) => setTaxType(e.target.value)}
                      disabled={controlsDisabled}
                    >
                      <option value="gst">GST</option>
                      <option value="swt">SWT</option>
                      <option value="cit">CIT</option>
                    </select>
                  </div>

                  {/* Start Date Material UI Date Picker */}
                  <div className="col-lg-4 col-md-6">
                    <label className="form-label fw-bold">Assessed Dates: From</label>
                    <DatePicker
                      format="DD/MM/YYYY"
                      value={startDate}
                      onChange={(newValue) => setStartDate(newValue)}
                      disabled={controlsDisabled}
                      slotProps={{
                        textField: {
                          fullWidth: true,
                          size: "small",
                          onBlur: (e) => {
                            const parsed = parseManualDate(e.target.value);
                            if (parsed || e.target.value === "") {
                              setStartDate(parsed);
                            }
                          },
                        },
                      }}
                    />
                  </div>

                  {/* End Date Material UI Date Picker */}
                  <div className="col-lg-4 col-md-6">
                    <label className="form-label fw-bold">To</label>
                    <DatePicker
                      format="DD/MM/YYYY"
                      value={endDate}
                      onChange={(newValue) => setEndDate(newValue)}
                      disabled={controlsDisabled}
                      slotProps={{
                        textField: {
                          fullWidth: true,
                          size: "small",
                          onBlur: (e) => {
                            const parsed = parseManualDate(e.target.value);
                            if (parsed || e.target.value === "") {
                              setEndDate(parsed);
                            }
                          },
                        },
                      }}
                    />
                  </div>

                </div>
              </LocalizationProvider>



              {/* Upload Section */}
              {!showMergedTable && (
                <Paper className="p-4 mb-3 upload-paper">
                  {/* Dropzone */}
                  <div
                    className="upload-dropzone border rounded text-center p-4 mb-3 bg-light"
                    onClick={handleFileClick}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (controlsDisabled) return;
                      handleFileChosen(e.dataTransfer.files[0]);
                    }}
                    onDragOver={(e) => e.preventDefault()}
                    style={{ cursor: controlsDisabled ? "not-allowed" : "pointer" }}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".csv"
                      style={{ display: "none" }}
                      disabled={controlsDisabled}
                      onChange={(e) => handleFileChosen(e.target.files[0])}
                    />
                    <FaCloudUploadAlt size={44} className="text-primary mb-2" />
                    <div className="fw-semibold">
                      {file ? file.name : "Click or drop CSV file here"}
                    </div>
                    <div className="text-muted small">Only CSV files supported</div>
                  </div>

                  {/* Buttons */}
                  <div className="d-flex gap-2 flex-wrap">
                    {!uploadResponse && (
                      <Button
                        variant="contained"
                        color="secondary"
                        onClick={handlePreview}
                        disabled={!file || controlsDisabled}
                      >
                        Show Preview
                      </Button>
                    )}

                    {previewVisible && (
                      <Button
                        variant="contained"
                        color="purple"
                        onClick={handleUploadPreview}
                        disabled={!file || controlsDisabled}
                        startIcon={validating ? <CircularProgress size={18} color="inherit" /> : null}
                      >
                        {validating ? "Validating..." : "Upload & Validate"}
                      </Button>
                    )}

                    <Button variant="outlined" onClick={handleBack} disabled={controlsDisabled}>
                      Back
                    </Button>
                  </div>

                  {/* CSV Preview Section */}
                  {previewVisible && previewRows.length > 0 && (
                    <Paper className="p-3 mt-3">
                      <Typography variant="subtitle1" gutterBottom>
                        File Preview (first 10 rows)
                      </Typography>
                      <div
                        className="table-responsive"
                        style={{ maxHeight: "300px", overflowY: "auto" }}
                      >
                        <table className="table table-sm table-striped">
                          <thead>
                            <tr>
                              {Object.keys(previewRows[0]).map((col) => (
                                <th key={col}>{col}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {previewRows.map((row, i) => (
                              <tr key={i}>
                                {Object.values(row).map((val, j) => (
                                  <td key={j}>{String(val)}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Paper>
                  )}

                  {showValidationSummary && uploadResponse && (
                    <>
                      <Paper className="p-3 mb-3 upload-paper">
                        <div className="d-flex justify-content-between mb-2 flex-wrap">
                          <div><strong>File:</strong> {file?.name || "ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â"}</div>
                          <div>
                            <strong>Total:</strong> {uploadResponse.total_records ?? 0} |{" "}
                            <strong>Valid:</strong> {uploadResponse.valid_records ?? 0} |{" "}
                            <strong>Invalid:</strong> {uploadResponse.invalid_records ?? 0}
                          </div>
                        </div>

                        <div className="mb-3">
                          <strong>Duplicates:</strong> {uploadResponse.db_duplicates_count ?? 0} |{" "}
                          <strong>Financial Differences:</strong>{" "}
                          {uploadResponse.db_financial_differences_count ?? 0} |{" "}
                          <strong>TIN Invalid:</strong> {uploadResponse.tin_invalid_count ?? 0} |{" "}
                          <span style={{ marginLeft: 8 }}>
                            {(() => {
                              const invalid = Number(uploadResponse.invalid_records ?? 0);
                              const dup = Number(uploadResponse.db_duplicates_count ?? 0);
                              const tinInvalid = Number(uploadResponse.tin_invalid_count ?? 0);
                              const sum = dup + tinInvalid;
                              const ruleFail = Math.max(0, invalid - sum);
                              return (
                                <>
                                  <strong>Rule validation Fail:</strong> {ruleFail ?? 0}
                                </>
                              );
                            })()}
                          </span>
                        </div>

                        {Number(uploadResponse.invalid_records ?? 0) > 0 &&
                          uploadResponse.removed_data_file && (
                            <div className="mb-3">
                              <Button
                                variant="outlined"
                                color="warning"
                                size="small"
                                onClick={() => {
                                  downloadInvalidCsv(uploadResponse.removed_data_file);
                                }}
                              >
                                Download Invalid Records CSV
                              </Button>
                            </div>
                          )}

                        {conflictCount !== null && (
                          <>
                            <div className="mb-1">
                              <strong>Financial Differences (Pending Approval):</strong>{" "}
                              {conflictCount}
                            </div>
                            {Number(uploadResponse?.financial_difference_count ?? uploadResponse?.db_financial_differences_count ?? 0) > 0 &&
                              uploadResponse?.financial_difference_file && (
                                <div className="mb-1">
                                  <Button
                                    variant="outlined"
                                    color="info"
                                    size="small"
                                    onClick={() => {
                                      downloadInvalidCsv(uploadResponse.financial_difference_file);
                                    }}
                                  >
                                    Download Financial Difference CSV
                                  </Button>
                                </div>
                              )}
                            {uploadResponse?.financial_diff_file && (
                              <div className="mb-1">
                                <Button
                                    component="a"
                                    href={uploadResponse.financial_diff_file}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    variant="outlined"
                                    color="info"
                                    size="small"
                                >
                                  Download Financial Differences
                                </Button>
                              </div>
                            )}
                          </>
                        )}
                      </Paper>
                    </>
                  )}


                  {error && <Alert severity="error" className="mt-3">{error}</Alert>}
                  {info && <Alert severity="info" className="mt-3">{info}</Alert>}

                  {/* Process button */}
                  {showValidationSummary && uploadResponse && (
                    <div className="d-flex justify-content-end mt-3">
                      <Button
                        variant="contained"
                        color="primary"
                        onClick={handleProcess}
                        disabled={controlsDisabled || !canProcess}
                        startIcon={processing ? <CircularProgress size={16} color="inherit" /> : null}
                      >
                        {processing ? "Processing..." : "Process"}
                      </Button>
                    </div>
                  )}

                </Paper>
              )}

              {/* Merged Table */}
              {showMergedTable && (
                <Paper className="p-4 mt-3">
                  <Typography variant="h6" gutterBottom>
                    Final Merged Audit Summary
                  </Typography>

                  <input
                    type="text"
                    placeholder="Search..."
                    className="form-control mb-3"
                    value={filterText}
                    onChange={(e) => setFilterText(e.target.value)}
                  />

                  <DataTable
                    columns={columns}
                    data={filteredData}
                    pagination
                    highlightOnHover
                    striped
                    dense
                    customStyles={tableCustomStyles}
                  />

                  <div className="d-flex gap-3 mt-3">
                    {excelUrl !== "" && (
                      <Button
                        variant="contained"
                        startIcon={<FileDownloadIcon />}
                        style={{ backgroundColor: "#6A00FF" }}
                        onClick={async () => {
                          try {
                            const baseName = String(excelUrl || "")
                              .replace(/\\/g, "/")
                              .split("/")
                              .filter(Boolean)
                              .pop();

                            if (!baseName) throw new Error("Missing filename");

                            const downloadUrl = `${API_BASE_URL}/${taxType}/download/${encodeURIComponent(baseName)}`;
                            console.log("Download URL:", downloadUrl);

                            const res = await axios.get(downloadUrl, {
                              responseType: "blob",
                              headers: { Authorization: `Bearer ${accessToken}` },
                            });

                            const link = document.createElement("a");
                            link.href = window.URL.createObjectURL(new Blob([res.data]));
                            link.download = baseName;
                            link.click();
                            return;
                          } catch (e) {
                            const msg =
                              e?.response?.data?.message ||
                              e?.response?.data?.error ||
                              e?.message ||
                              "Download failed.";
                            await showAlert("error", "Download Failed", msg);
                          }
                        }}
                      >
                        Download
                      </Button>
                    )}

                    <Button variant="outlined" color="secondary" onClick={handleBack} disabled={controlsDisabled}>
                      Back
                    </Button>
                  </div>
                </Paper>
              )}

              {processing && (
                <Paper className="p-3 upload-paper">
                  <Typography variant="subtitle1" gutterBottom>
                    Processing Pipeline
                  </Typography>
                  <Box sx={{ width: "100%" }} className="mb-2">
                    <LinearProgress variant="determinate" value={progress} sx={{ height: 10 }} />
                  </Box>
                  <Typography variant="body2">{statusMsg}</Typography>
                </Paper>
              )}

              <Dialog
                open={validationDialogOpen}
                onClose={(event, reason) => {
                  if (reason === "backdropClick" || reason === "escapeKeyDown") return;
                }}
                disableEscapeKeyDown
                aria-labelledby="upload-validation-dialog-title"
                aria-describedby="upload-validation-dialog-description"
                maxWidth="xs"
                fullWidth
              >
                <DialogTitle id="upload-validation-dialog-title">
                  {pipelineState.phase === "validation-complete" ? "Validation Complete" : "Validating uploaded file"}
                </DialogTitle>
                <DialogContent>
                  <Box
                    id="upload-validation-dialog-description"
                    role="status"
                    aria-live="polite"
                    aria-atomic="true"
                    sx={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", py: 1 }}
                  >
                    {pipelineState.phase === "validation-complete" ? (
                      <CheckCircleOutlineIcon color="success" sx={{ fontSize: 48, mb: 2 }} />
                    ) : (
                      <CircularProgress size={42} aria-label="Validation in progress" sx={{ mb: 2 }} />
                    )}
                    <Typography variant="body1" sx={{ mb: 1 }}>
                      {validationDialogMessage}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {pipelineState.phase === "validation-complete"
                        ? "Validation summary is ready."
                        : "This may take several minutes for large files."}
                    </Typography>
                  </Box>
                </DialogContent>
              </Dialog>
            </div>

          </main>
        </div>

        <Footer />
      </div>
    </div>
  );
}





