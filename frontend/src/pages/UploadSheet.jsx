import { useState, useRef, useEffect } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import Papa from "papaparse";
import axios from "axios";
import API from "../api/api";
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
  DialogActions,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Skeleton,
  IconButton,
  Collapse,
} from "@mui/material";
import { FaCloudUploadAlt } from "react-icons/fa";
import DataTable from "react-data-table-component";
import "./css/UploadSheet.css";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import tableCustomStyles from "../components/common/tableStyles";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import dayjs from "dayjs";
import DescriptionIcon from "@mui/icons-material/Description";
import Swal from "sweetalert2";
import API_BASE_URL, { SERVER_BASE_URL } from "../config/api.config";
import { getToken } from "../services/auth";

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
      return `Database Insert: ${insertedRows.toLocaleString()} / ${totalRows.toLocaleString()} (${insertPercent || 0}%)`;
    }
    return "Database insert in progress...";
  }

  if (rawStep) {
    if (normalizedStep.includes("prediction")) return `Prediction running... (${rawStep})`;
    if (normalizedStep.includes("justification")) return `Generating fraud justification... (${rawStep})`;
    if (normalizedStep === "queued") return "Queued...";
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

  // --- Page State Machine ---
  // 'INITIAL' | 'FILE_SELECTED' | 'PREVIEW_LOADING' | 'PREVIEW_READY' | 'UPLOAD_VALIDATING' | 'UPLOAD_SUCCESS' | 'UPLOAD_ERROR'
  const [pageState, setPageState] = useState("INITIAL");
  const [isPreviewExpanded, setIsPreviewExpanded] = useState(true);

  const [file, setFile] = useState(null);
  const [previewRows, setPreviewRows] = useState([]);
  const [uploadResponse, setUploadResponse] = useState(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [pipelineState, setPipelineState] = useState(createInitialPipelineState);
  const [runId, setRunId] = useState(null);
  const terminalRunIdRef = useRef(null);

  const [mergedData, setMergedData] = useState([]);
  const [excelUrl, setExcelUrl] = useState("");
  const [showMergedTable, setShowMergedTable] = useState(false);
  const [filterText, setFilterText] = useState("");
  const [conflictCount, setConflictCount] = useState(null);

  // Sheet Upload Tax Parameter & Dates
  const [taxType, setTaxType] = useState("gst");
  const [startDate, setStartDate] = useState(null);
  const [endDate, setEndDate] = useState(null);

  // --- Create Segmentation State Machine ---
  // 'SEGMENTATION_IDLE' | 'SEGMENTATION_RUNNING' | 'SEGMENTATION_COMPLETED' | 'SEGMENTATION_FAILED'
  const [segmentationState, setSegmentationState] = useState("SEGMENTATION_IDLE");
  const [isSegmentationModalOpen, setIsSegmentationModalOpen] = useState(false);
  const [segTaxType, setSegTaxType] = useState("GST");
  const [segStartDate, setSegStartDate] = useState(null);
  const [segEndDate, setSegEndDate] = useState(null);
  const [segDateError, setSegDateError] = useState("");
  const [segmentationValidationError, setSegmentationValidationError] = useState(null); // { message, missingYears }

  const [segmentationMsg, setSegmentationMsg] = useState("");
  const [segmentationJobId, setSegmentationJobId] = useState(null);
  const [segmentationProgress, setSegmentationProgress] = useState(0);

  const parseManualDate = (value) => {
    if (!value) return null;
    const parsed = dayjs(value, ["DD/MM/YYYY", "YYYY-MM-DD"], true);
    return parsed.isValid() ? parsed : null;
  };

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

  const getAuthHeaders = () => {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  const showAlert = (icon, title, text) =>
    Swal.fire({
      icon,
      title,
      text,
      confirmButtonColor: "#6A00FF",
    });

  const resetUploadSheet = () => {
    terminalRunIdRef.current = null;

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
    setMergedData([]);
    setExcelUrl("");
    setShowMergedTable(false);
    setFilterText("");
    setConflictCount(null);
    setStartDate(null);
    setEndDate(null);

    setPageState("INITIAL");
    setSegmentationState("SEGMENTATION_IDLE");
    setSegmentationMsg("");
    setSegmentationJobId(null);
    setSegmentationProgress(0);
    setSegDateError("");
    setSegmentationValidationError(null);

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

    if (!hasStart && !hasEnd) return true;

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
  // SEGMENTATION MODAL HANDLERS
  // ---------------------------------
  const handleOpenSegmentationModal = () => {
    if (segmentationState === "SEGMENTATION_RUNNING") return;
    setIsSegmentationModalOpen(true);
    setSegDateError("");
    setSegmentationValidationError(null);
    setSegmentationState("SEGMENTATION_IDLE");
  };

  const handleCloseSegmentationModal = () => {
    if (segmentationState === "SEGMENTATION_RUNNING") return; // Block closing while running
    setIsSegmentationModalOpen(false);
    setSegDateError("");
    setSegmentationValidationError(null);
    setSegmentationState("SEGMENTATION_IDLE");
    setSegmentationProgress(0);
    setSegmentationMsg("");
  };

  const handleStartSegmentation = async () => {
    setSegDateError("");
    setSegmentationValidationError(null);

    if (!segTaxType) {
      setSegDateError("Please select a Tax Parameter.");
      return;
    }

    if (!segStartDate || !segEndDate) {
      setSegDateError("Please select both From and To dates.");
      return;
    }

    const parsedStart = dayjs(segStartDate);
    const parsedEnd = dayjs(segEndDate);

    if (!parsedStart.isValid() || !parsedEnd.isValid()) {
      setSegDateError("Please enter valid dates (DD/MM/YYYY).");
      return;
    }

    if (parsedEnd.isBefore(parsedStart, "day")) {
      setSegDateError("End date must be on or after start date.");
      return;
    }

    const formattedStartDate = parsedStart.format("YYYY-MM-DD");
    const formattedEndDate = parsedEnd.format("YYYY-MM-DD");

    setSegmentationState("SEGMENTATION_RUNNING");
    setSegmentationMsg("Validating historical data...");
    setSegmentationProgress(0);

    // Step 1: Validate history against DB
    try {
      await API.post("/segmentation/validate-history", {
        tax_type: String(segTaxType || "").toUpperCase(),
        start_date: formattedStartDate,
        end_date: formattedEndDate,
      });
    } catch (err) {
      // STOP LOADER IMMEDIATELY & Transition existing modal into in-modal error view (No nested modal!)
      const validationData = err.response?.data;
      const validationMsg = validationData?.message || "Past 3 years data not available.";
      const missingYears = validationData?.missing_years || [];

      setSegmentationState("SEGMENTATION_FAILED");
      setSegmentationValidationError({
        message: validationMsg,
        missingYears: missingYears,
      });
      return;
    }

    // Step 2: History valid, start segmentation background job
    try {
      setSegmentationMsg("Queueing segmentation job...");

      const startRes = await API.post("/segmentation/start", {
        start_date: formattedStartDate,
        end_date: formattedEndDate,
      });

      setSegmentationJobId(startRes.data.job_id);
      setSegmentationMsg("Queued: Waiting for background worker...");
      setSegmentationProgress(0);
    } catch (err) {
      const valData = err.response?.data;
      const msg = valData?.error || valData?.message || err.message || "Segmentation job failed.";
      setSegmentationState("SEGMENTATION_FAILED");
      setSegmentationValidationError({
        message: msg,
        missingYears: [],
      });
    }
  };

  // Polling Effect for Segmentation Job Status
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
          setSegmentationState("SEGMENTATION_COMPLETED");
          setSegmentationJobId(null); // Stop polling immediately
          setSegmentationProgress(100);
          setSegmentationMsg(`Segmentation Completed Successfully. Total segmented: ${totalSegmented}`);
          setInfo("Segmentation completed successfully.");
          return;
        }

        if (normalizedStatus === "failed") {
          const msg = nextError || "Segmentation failed.";
          setSegmentationState("SEGMENTATION_FAILED");
          setSegmentationJobId(null); // Stop polling immediately
          setSegmentationValidationError({
            message: msg,
            missingYears: [],
          });
        }
      } catch (err) {
        if (!isActive) return;
        const msg = err.response?.data?.error || err.response?.data?.message || err.message || "Segmentation status check failed.";
        setSegmentationState("SEGMENTATION_FAILED");
        setSegmentationJobId(null); // Stop polling immediately
        setSegmentationValidationError({
          message: msg,
          missingYears: [],
        });
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

  const TAX_PATH = `/${taxType}`;

  const canProcess =
    uploadResponse?.valid === true &&
    Number(uploadResponse?.valid_records || 0) > 0;
  const validating =
    pipelineState.phase === "validating" || pipelineState.phase === "validation-complete";
  const processing = pipelineState.phase === "processing";
  const controlsDisabled = pipelineState.busy || segmentationState === "SEGMENTATION_RUNNING";
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
      setPageState("INITIAL");
      return;
    }

    setFile(chosenFile);
    setPageState("FILE_SELECTED");
  };

  const handleFileClick = () => {
    if (controlsDisabled) return;
    fileInputRef.current?.click();
  };

  const handlePreview = () => {
    if (controlsDisabled || !file) return;

    setError("");
    setPageState("PREVIEW_LOADING");
    setIsPreviewExpanded(true);

    setTimeout(() => {
      Papa.parse(file, {
        header: true,
        skipEmptyLines: true,
        complete: (result) => {
          setPreviewRows(result.data.slice(0, 10));
          setPageState("PREVIEW_READY");
          setIsPreviewExpanded(true);
        },
        error: (err) => {
          setError("Failed to parse CSV preview: " + err.message);
          setPageState("INITIAL");
        },
      });
    }, 300);
  };

  // Cancel Preview Action - resets upload workflow without changing unrelated page state
  const handleCancelPreview = () => {
    setFile(null);
    setPreviewRows([]);
    setUploadResponse(null);
    setError("");
    setInfo("");
    setPageState("INITIAL");
    setIsPreviewExpanded(true);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  // -------------------------------
  // Upload + validate
  // -------------------------------
  const handleUploadPreview = async () => {
    if (pipelineState.busy || validating) return;
    setError("");
    setInfo("");
    setConflictCount(null);

    if (!file) return setError("Please select a file.");
    if (!(await validateDateRangeIfProvided())) return;

    const formData = new FormData();
    formData.append("file", file);

    if (validationCompletionTimeoutRef.current) {
      window.clearTimeout(validationCompletionTimeoutRef.current);
      validationCompletionTimeoutRef.current = null;
    }

    setPageState("UPLOAD_VALIDATING");
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
      const res = await API.post(`${TAX_PATH}/validate`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });

      setUploadResponse(res.data);
      setConflictCount(
        Number(
          res.data.financial_difference_count ??
            res.data.db_financial_difference_fields_count ??
            res.data.db_financial_differences_count ??
            0
        )
      );
      setPipelineState((prev) => ({
        ...prev,
        phase: "validation-complete",
        busy: true,
        message: "Validation Complete",
        showValidationSummary: false,
      }));

      validationCompletionTimeoutRef.current = window.setTimeout(() => {
        setPageState("UPLOAD_SUCCESS");
        setIsPreviewExpanded(false); // Automatically collapse table when Process button arrives!
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
      setPageState("UPLOAD_ERROR");
      setError(msg);
      showAlert("error", "Validation Failed", msg);
    }
  };

  // -------------------------------
  // Fetch Sample Files
  // -------------------------------
  const fetchSampleFiles = async () => {
    try {
      const res = await API.get("/segmentation/get-sample-files");
      setSampleLinks({
        gst: res.data.gst.url,
        swt: res.data.swt.url,
        cit: res.data.cit.url,
      });
    } catch (e) {
      console.error("Failed to fetch sample links:", e);
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
    try {
      const response = await axios.get(url, {
        responseType: "blob",
        headers: getAuthHeaders(),
      });

      const link = document.createElement("a");
      link.href = window.URL.createObjectURL(new Blob([response.data]));
      link.download = fileName;
      link.click();
    } catch (err) {
      showAlert("error", "Download Failed", "Could not download sample file.");
    }
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
      const headers = getAuthHeaders();

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

  const handleBack = () => {
    resetUploadSheet();
  };

  useEffect(() => {
    if (!runId) return;

    let isActive = true;
    let pollInFlight = false;
    pipelinePollIntervalRef.current = setInterval(async () => {
      if (!isActive || pollInFlight || terminalRunIdRef.current === runId) {
        return;
      }

      pollInFlight = true;
      try {
        const res = await API.get(`${TAX_PATH}/status/${runId}`);
        if (!isActive || terminalRunIdRef.current === runId) {
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
            setRunId(null);
            const result = await showAlert("success", "Completed", "Upload completed successfully.");
            if (result?.isConfirmed) {
              resetUploadSheet();
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
      const filename = resp?.validated_file;
      if (filename) return String(filename).trim();
      return null;
    };

    const validatedFileName = getValidatedFileName(uploadResponse);
    if (!validatedFileName) {
      return setError("Validated file is missing. Please validate again.");
    }

    setError("");
    terminalRunIdRef.current = null;
    setPipelineState((prev) => ({
      ...prev,
      phase: "processing",
      busy: true,
      progress: 0,
      message: "Queued...",
      showValidationSummary: true,
    }));

    const formData = new FormData();
    formData.append("validated_file", validatedFileName);
    formData.append("date_from", parsedStart.format("YYYY-MM-DD"));
    formData.append("date_to", parsedEnd.format("YYYY-MM-DD"));

    try {
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
            color: row.Fraud === "Fraud Detected" ? "#ff4d4d" : "#036b48",
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
              {/* Top Header & Action Row */}
              <div className="d-flex flex-column flex-md-row justify-content-between align-items-start align-items-md-center gap-3 mb-4">
                <div className="header-title-page text-nowrap">Upload Sheet</div>

                <div className="d-flex flex-wrap align-items-center gap-3 w-100 w-md-auto justify-content-end">
                  {/* Sample Files Container */}
                  <div className="sample-files-card">
                    <div className="sample-files-title">Sample Files</div>
                    <div className="sample-files-btn-group">
                      <Button
                        component="a"
                        variant="outlined"
                        size="small"
                        color="primary"
                        className="sample-file-btn"
                        startIcon={<FileDownloadIcon />}
                        onClick={() => downloadFile(sampleLinks.gst, "sample_gst.csv")}
                        disabled={controlsDisabled}
                      >
                        Sample GST
                      </Button>
                      <Button
                        component="a"
                        variant="outlined"
                        size="small"
                        color="primary"
                        className="sample-file-btn"
                        startIcon={<FileDownloadIcon />}
                        onClick={() => downloadFile(sampleLinks.swt, "sample_swt.csv")}
                        disabled={controlsDisabled}
                      >
                        Sample SWT
                      </Button>
                      <Button
                        component="a"
                        variant="outlined"
                        size="small"
                        color="primary"
                        className="sample-file-btn"
                        startIcon={<FileDownloadIcon />}
                        onClick={() => downloadFile(sampleLinks.cit, "sample_cit.csv")}
                        disabled={controlsDisabled}
                      >
                        Sample CIT
                      </Button>
                    </div>
                  </div>

                  {/* Create Segmentation Action & Requirement Note Card (No BG) */}
                  <div className="create-segmentation-card">
                    <Button
                      variant="contained"
                      color="secondary"
                      onClick={handleOpenSegmentationModal}
                      disabled={segmentationState === "SEGMENTATION_RUNNING" || controlsDisabled}
                      sx={{
                        backgroundColor: "#6A00FF",
                        fontWeight: "bold",
                        px: 3,
                        py: 1,
                        "&:hover": { backgroundColor: "#5700d1" },
                      }}
                    >
                      CREATE SEGMENTATION
                    </Button>

                    <div className="segmentation-requirement-note">
                      <InfoOutlinedIcon fontSize="small" color="primary" />
                      <span>
                        Requirement: Three years of historical GST, SWT, and CIT data must be available before segmentation can be created.
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Sheet Selection & Date Filters */}
              <LocalizationProvider dateAdapter={AdapterDayjs}>
                <div className="row g-3 align-items-end mb-4">
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

              {/* Main Upload / Preview / Summary Section */}
              {!showMergedTable && (
                <Paper className="p-4 mb-3 upload-paper">
                  {/* Dropzone & Show Preview Button - Hidden when preview is ready or uploaded */}
                  {pageState !== "PREVIEW_READY" &&
                    pageState !== "UPLOAD_VALIDATING" &&
                    pageState !== "UPLOAD_SUCCESS" && (
                      <>
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

                        <div className="d-flex gap-2 flex-wrap">
                          <Button
                            variant="contained"
                            color="secondary"
                            onClick={handlePreview}
                            disabled={!file || controlsDisabled || pageState === "PREVIEW_LOADING"}
                            sx={{ backgroundColor: "#6A00FF" }}
                          >
                            {pageState === "PREVIEW_LOADING" ? "Loading Preview..." : "SHOW PREVIEW"}
                          </Button>
                          <Button
                            variant="outlined"
                            onClick={handleCancelPreview}
                            disabled={controlsDisabled}
                          >
                            CANCEL
                          </Button>
                        </div>
                      </>
                    )}

                  {/* Skeleton Loading State for Preview */}
                  {pageState === "PREVIEW_LOADING" && (
                    <Paper className="p-3 mt-3 preview-table-container">
                      <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                        File Preview — First 10 Rows
                      </Typography>
                      <Box sx={{ p: 2 }}>
                        <Skeleton variant="rectangular" height={40} sx={{ mb: 1, borderRadius: 1 }} />
                        <Skeleton variant="rectangular" height={30} sx={{ mb: 1, borderRadius: 1 }} />
                        <Skeleton variant="rectangular" height={30} sx={{ mb: 1, borderRadius: 1 }} />
                        <Skeleton variant="rectangular" height={30} sx={{ mb: 1, borderRadius: 1 }} />
                        <Skeleton variant="rectangular" height={30} sx={{ borderRadius: 1 }} />
                      </Box>
                    </Paper>
                  )}

                  {/* Render Table Container & Bottom Actions when Preview is Ready */}
                  {(pageState === "PREVIEW_READY" ||
                    pageState === "UPLOAD_VALIDATING" ||
                    pageState === "UPLOAD_SUCCESS") &&
                    previewRows.length > 0 && (
                      <Paper className="p-3 mt-3 preview-table-container">
                        <div
                          className="preview-table-header d-flex justify-content-between align-items-center"
                          onClick={() => setIsPreviewExpanded((prev) => !prev)}
                        >
                          <div className="d-flex align-items-center gap-2">
                            <Typography variant="subtitle1" fontWeight="bold" color="text.primary">
                              File Preview — First 10 Rows
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              ({file?.name})
                            </Typography>
                          </div>

                          <div className="d-flex align-items-center gap-2">
                            <Typography variant="caption" color="text.secondary" sx={{ display: { xs: "none", sm: "inline" } }}>
                              {isPreviewExpanded ? "Click to collapse" : "Click to expand"}
                            </Typography>
                            <IconButton size="small" aria-label={isPreviewExpanded ? "Collapse preview table" : "Expand preview table"}>
                              {isPreviewExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                            </IconButton>
                          </div>
                        </div>

                        <Collapse in={isPreviewExpanded}>
                          <div className="preview-table-wrapper subtle-scrollbar mt-2">
                            <table className="table table-sm table-bordered table-striped table-hover mb-0 preview-table">
                              <thead>
                                <tr>
                                  {Object.keys(previewRows[0]).map((col) => (
                                    <th key={col} className="sticky-header">
                                      {col}
                                    </th>
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

                          {/* Bottom-right Action Buttons after Preview */}
                          {pageState === "PREVIEW_READY" && (
                            <div className="d-flex justify-content-end gap-2 mt-3 pt-2 border-top">
                              <Button
                                variant="outlined"
                                color="inherit"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleCancelPreview();
                                }}
                                disabled={controlsDisabled}
                              >
                                CANCEL
                              </Button>

                              <Button
                                variant="contained"
                                color="secondary"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleUploadPreview();
                                }}
                                disabled={!file || controlsDisabled}
                                startIcon={validating ? <CircularProgress size={18} color="inherit" /> : null}
                                sx={{ backgroundColor: "#6A00FF", fontWeight: "bold" }}
                              >
                                {validating ? "Validating..." : "UPLOAD & VALIDATE"}
                              </Button>
                            </div>
                          )}
                        </Collapse>
                      </Paper>
                    )}

                  {/* Validation Summary Report */}
                  {showValidationSummary && uploadResponse && (
                    <Paper className="p-3 mt-3 upload-paper border">
                      <div className="d-flex justify-content-between mb-2 flex-wrap">
                        <div>
                          <strong>File:</strong> {file?.name || "Uploaded CSV"}
                        </div>
                        <div>
                          <strong>Total:</strong> {uploadResponse.total_records ?? 0} |{" "}
                          <strong>Valid:</strong> {uploadResponse.valid_records ?? 0} |{" "}
                          <strong>Invalid:</strong> {uploadResponse.invalid_records ?? 0}
                        </div>
                      </div>

                      <div className="mb-3">
                        <strong>Duplicates:</strong> {uploadResponse.db_duplicates_count ?? 0} |{" "}
                        <strong>Financial Differences:</strong>{" "}
                        {uploadResponse.financial_difference_count ??
                          uploadResponse.db_financial_difference_fields_count ??
                          uploadResponse.db_financial_differences_count ??
                          0}{" "}
                        | <strong>TIN Invalid:</strong> {uploadResponse.tin_invalid_count ?? 0} |{" "}
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
                            <strong>Financial Differences (Pending Approval):</strong> {conflictCount}
                          </div>
                          {Number(conflictCount ?? 0) > 0 &&
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
                        </>
                      )}
                    </Paper>
                  )}

                  {error && <Alert severity="error" className="mt-3">{error}</Alert>}
                  {info && <Alert severity="info" className="mt-3">{info}</Alert>}

                  {/* Final Process Button */}
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

              {/* Merged Audit Summary Table */}
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
                    <Button variant="outlined" color="secondary" onClick={handleBack} disabled={controlsDisabled}>
                      Back
                    </Button>
                  </div>
                </Paper>
              )}

              {/* Pipeline Processing Indicator */}
              {processing && (
                <Paper className="p-3 upload-paper mt-3">
                  <Typography variant="subtitle1" gutterBottom>
                    Processing Pipeline
                  </Typography>
                  <Box sx={{ width: "100%" }} className="mb-2">
                    <LinearProgress variant="determinate" value={progress} sx={{ height: 10 }} />
                  </Box>
                  <Typography variant="body2">{statusMsg}</Typography>
                </Paper>
              )}

              {/* Upload Validation Dialog */}
              <Dialog
                open={validationDialogOpen}
                onClose={(event, reason) => {
                  if (reason === "backdropClick" || reason === "escapeKeyDown") return;
                }}
                disableEscapeKeyDown
                maxWidth="xs"
                fullWidth
              >
                <DialogTitle>
                  {pipelineState.phase === "validation-complete" ? "Validation Complete" : "Validating uploaded file"}
                </DialogTitle>
                <DialogContent>
                  <Box
                    role="status"
                    aria-live="polite"
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

              {/* STANDALONE CREATE SEGMENTATION MODAL */}
              <Dialog
                open={isSegmentationModalOpen}
                onClose={(event, reason) => {
                  if (reason === "backdropClick" || reason === "escapeKeyDown") {
                    if (segmentationState !== "SEGMENTATION_RUNNING") {
                      handleCloseSegmentationModal();
                    }
                  }
                }}
                disableEscapeKeyDown={segmentationState === "SEGMENTATION_RUNNING"}
                aria-labelledby="segmentation-dialog-title"
                maxWidth="sm"
                fullWidth
              >
                <DialogTitle
                  id="segmentation-dialog-title"
                  component="div"
                  sx={{ borderBottom: "1px solid #e2e8f0", pb: 1, fontWeight: "bold", fontSize: "1.25rem" }}
                >
                  {segmentationState === "SEGMENTATION_RUNNING"
                    ? "Creating Segmentation"
                    : segmentationState === "SEGMENTATION_COMPLETED"
                    ? "Segmentation Completed"
                    : "Create Segmentation"}
                </DialogTitle>

                <DialogContent sx={{ pt: 3, overflowX: "hidden" }}>
                  {/* State 1: Running Progress View */}
                  {segmentationState === "SEGMENTATION_RUNNING" && (
                    <Box sx={{ py: 2, textAlign: "center" }}>
                      <Typography variant="body1" fontWeight="500" sx={{ mb: 2 }}>
                        {segmentationMsg || "Validating historical data..."}
                      </Typography>

                      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 1 }}>
                        <Box sx={{ width: "100%" }}>
                          <LinearProgress
                            variant="determinate"
                            value={Math.min(100, Math.max(0, segmentationProgress))}
                            sx={{ height: 10, borderRadius: 5, backgroundColor: "#e2e8f0" }}
                            aria-valuenow={segmentationProgress}
                            aria-valuemin={0}
                            aria-valuemax={100}
                          />
                        </Box>
                        <Typography variant="body2" fontWeight="bold" color="text.secondary">
                          {Math.round(segmentationProgress)}%
                        </Typography>
                      </Box>

                      <Typography variant="caption" color="text.secondary">
                        {Math.round(segmentationProgress)}% Complete
                      </Typography>
                    </Box>
                  )}

                  {/* State 2: In-Modal Validation / Job Error State (No Nested Modal!) */}
                  {segmentationValidationError && segmentationState === "SEGMENTATION_FAILED" && (
                    <Box className="modal-error-box">
                      <Box sx={{ display: "flex", alignItems: "center", gap: 1, color: "#dc2626", mb: 1 }}>
                        <WarningAmberIcon />
                        <Typography variant="subtitle1" fontWeight="bold">
                          Validation Failed
                        </Typography>
                      </Box>

                      <Typography variant="body2" color="text.primary" sx={{ mb: 1.5 }}>
                        Requirements: Three years of historical GST, SWT, and CIT data must be available in the database.
                      </Typography>

                      <Typography variant="body2" color="error.main" fontWeight="500">
                        {segmentationValidationError.message}
                      </Typography>

                      {segmentationValidationError.missingYears &&
                        segmentationValidationError.missingYears.length > 0 && (
                          <Box sx={{ mt: 1.5 }}>
                            <Typography variant="caption" fontWeight="bold" color="text.secondary">
                              Missing Years:
                            </Typography>
                            <div className="missing-years-list">
                              {segmentationValidationError.missingYears.map((year) => (
                                <span key={year} className="missing-year-chip">
                                  {year}
                                </span>
                              ))}
                            </div>
                          </Box>
                        )}

                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>
                        Please upload the required historical data files and try again.
                      </Typography>
                    </Box>
                  )}

                  {/* State 3: Completed Success View */}
                  {segmentationState === "SEGMENTATION_COMPLETED" && (
                    <Box sx={{ py: 3, textAlign: "center" }}>
                      <CheckCircleOutlineIcon color="success" sx={{ fontSize: 56, mb: 1.5 }} />
                      <Typography variant="h6" color="success.main" fontWeight="bold" sx={{ mb: 1 }}>
                        Segmentation Completed!
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {segmentationMsg}
                      </Typography>
                    </Box>
                  )}

                  {/* State 4: Initial Input Form View */}
                  {segmentationState === "SEGMENTATION_IDLE" && !segmentationValidationError && (
                    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5, pt: 1 }}>
                      <Typography variant="body2" color="text.secondary">
                        Select the tax parameter and assessment period to generate the segmentation.
                      </Typography>

                      <FormControl fullWidth size="small">
                        <InputLabel id="seg-tax-label">Tax Parameter</InputLabel>
                        <Select
                          labelId="seg-tax-label"
                          value={segTaxType}
                          label="Tax Parameter"
                          onChange={(e) => setSegTaxType(e.target.value)}
                        >
                          <MenuItem value="GST">GST</MenuItem>
                          <MenuItem value="SWT">SWT</MenuItem>
                          <MenuItem value="CIT">CIT</MenuItem>
                        </Select>
                      </FormControl>

                      <LocalizationProvider dateAdapter={AdapterDayjs}>
                        <Box sx={{ display: "flex", gap: 2, flexDirection: { xs: "column", sm: "row" } }}>
                          <Box sx={{ flex: 1 }}>
                            <label className="form-label fw-semibold small">Assessment Date: From</label>
                            <DatePicker
                              format="DD/MM/YYYY"
                              value={segStartDate}
                              onChange={(val) => setSegStartDate(val)}
                              slotProps={{
                                textField: {
                                  fullWidth: true,
                                  size: "small",
                                  placeholder: "DD/MM/YYYY",
                                },
                              }}
                            />
                          </Box>

                          <Box sx={{ flex: 1 }}>
                            <label className="form-label fw-semibold small">To</label>
                            <DatePicker
                              format="DD/MM/YYYY"
                              value={segEndDate}
                              onChange={(val) => setSegEndDate(val)}
                              slotProps={{
                                textField: {
                                  fullWidth: true,
                                  size: "small",
                                  placeholder: "DD/MM/YYYY",
                                },
                              }}
                            />
                          </Box>
                        </Box>
                      </LocalizationProvider>

                      {segDateError && (
                        <Alert severity="warning" sx={{ py: 0.5 }}>
                          {segDateError}
                        </Alert>
                      )}
                    </Box>
                  )}
                </DialogContent>

                <DialogActions sx={{ px: 3, pb: 2.5, pt: 1, borderTop: "1px solid #f1f5f9" }}>
                  {segmentationState === "SEGMENTATION_COMPLETED" ? (
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={handleCloseSegmentationModal}
                      sx={{ backgroundColor: "#6A00FF" }}
                    >
                      DONE
                    </Button>
                  ) : segmentationValidationError && segmentationState === "SEGMENTATION_FAILED" ? (
                    <>
                      <Button variant="outlined" color="inherit" onClick={handleCloseSegmentationModal}>
                        CANCEL
                      </Button>
                      <Button
                        variant="contained"
                        color="primary"
                        onClick={() => {
                          setSegmentationValidationError(null);
                          setSegmentationState("SEGMENTATION_IDLE");
                        }}
                        sx={{ backgroundColor: "#6A00FF" }}
                      >
                        RETRY
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        variant="outlined"
                        color="inherit"
                        onClick={handleCloseSegmentationModal}
                        disabled={segmentationState === "SEGMENTATION_RUNNING"}
                      >
                        CANCEL
                      </Button>
                      <Button
                        variant="contained"
                        color="secondary"
                        onClick={handleStartSegmentation}
                        disabled={segmentationState === "SEGMENTATION_RUNNING"}
                        sx={{ backgroundColor: "#6A00FF", fontWeight: "bold" }}
                      >
                        {segmentationState === "SEGMENTATION_RUNNING"
                          ? "PROCESSING..."
                          : "START SEGMENTATION"}
                      </Button>
                    </>
                  )}
                </DialogActions>
              </Dialog>
            </div>
          </main>
        </div>

        <Footer />
      </div>
    </div>
  );
}
