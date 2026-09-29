import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
import Swal from "sweetalert2";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import Chart from "react-apexcharts";
import DataTable from "react-data-table-component";
import {
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Paper,
  Button,
  Alert,
  Skeleton,
  Box,
  Autocomplete,
  TextField,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Typography,
} from "@mui/material";
import dayjs from "dayjs";
import API from "../api/api";
import tableCustomStyles from "../components/common/tableStyles";
import EmptyState from "../components/common/EmptyState";
import TableSkeleton from "../components/common/TableSkeleton";
import ChartDataCard from "../components/common/ChartDataCard";
import "./css/Dashboard.css";
import TableChartIcon from "@mui/icons-material/TableChart";    // CSV icon

import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

const asArray = (v) => (Array.isArray(v) ? v : []);
const num = (v) => Number(v ?? 0);
const str = (v, fallback = "-") => (v === null || v === undefined || v === "" ? fallback : String(v));

/* ================= CSV EXPORT ================= */
const exportCSV = (data, filename) => {
  if (!data || !data.length) return;
  const headers = Object.keys(data[0]);
  const rows = [
    headers.join(","),
    ...data.map((r) =>
      headers.map((h) => `"${r[h] ?? ""}"`).join(",")
    ),
  ];
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
};

export default function CommonDashboard() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const ALL_TIN_OPTION = useMemo(() => ({ tin: "ALL", name: "All Taxpayers", label: "ALL - All Taxpayers" }), []);

  /* FILTERS */
  const [startDate, setStartDate] = useState(dayjs().startOf("year"));
  const [endDate, setEndDate] = useState(dayjs().endOf("year"));

  const [tinList, setTinList] = useState([ALL_TIN_OPTION]);
  const [selectedTin, setSelectedTin] = useState(ALL_TIN_OPTION);
  const [appliedFilters, setAppliedFilters] = useState(() => ({ startDate: dayjs().startOf("year"), endDate: dayjs().endOf("year"), selectedTin: ALL_TIN_OPTION }));
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [chartView, setChartView] = useState({ taxFlow: false, sector: false, fraudTrend: false, fraudDistribution: false });
  const [tinInputValue, setTinInputValue] = useState("");
  const [tinLoading, setTinLoading] = useState(false);

  /* DATA */
  const [overview, setOverview] = useState({});
  const [taxFlow, setTaxFlow] = useState({ categories: [], series: [] });
  const [riskExposure, setRiskExposure] = useState([]);
  const [sectorData, setSectorData] = useState([]);
  const [topTins, setTopTins] = useState([]);
  const [records, setRecords] = useState([]);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [recordsQuery, setRecordsQuery] = useState({ filters: { range_type: "all" }, page: 1, pageSize: 50 });
  const [recordsReload, setRecordsReload] = useState(0);
  const [rebuildStarting, setRebuildStarting] = useState(false);
  const rebuildStartingRef = useRef(false);
  const statusRequestRef = useRef(false);
  const [statusPollError, setStatusPollError] = useState("");
  const [fraudTrend, setFraudTrend] = useState([]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [taxFlowLoading, setTaxFlowLoading] = useState(false);
  const [riskExposureLoading, setRiskExposureLoading] = useState(false);
  const [sectorLoading, setSectorLoading] = useState(false);
  const [topTinsLoading, setTopTinsLoading] = useState(false);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [fraudTrendLoading, setFraudTrendLoading] = useState(false);
  const [overviewError, setOverviewError] = useState("");
  const [taxFlowError, setTaxFlowError] = useState("");
  const [riskExposureError, setRiskExposureError] = useState("");
  const [sectorError, setSectorError] = useState("");
  const [topTinsError, setTopTinsError] = useState("");
  const [recordsError, setRecordsError] = useState("");
  const [fraudTrendError, setFraudTrendError] = useState("");
  const fetchSequenceRef = useRef(0);
  const isMountedRef = useRef(true);
  const rebuildPollIntervalRef = useRef(null);
  const summaryStatusTransitionRef = useRef("idle");
  const [summaryStatus, setSummaryStatus] = useState({
    status: "idle",
    progress: 0,
    currentStep: "",
    lastUpdated: null,
    error: "",
  });
  const [summaryDialogOpen, setSummaryDialogOpen] = useState(false);

  const buildParams = (filters) => ({
    range_type: "custom",
    start_date: filters.startDate.format("YYYY-MM-DD"),
    end_date: filters.endDate.format("YYYY-MM-DD"),
    ...(filters.selectedTin?.tin && filters.selectedTin.tin !== "ALL" && { tin: filters.selectedTin.tin }),
  });

  const params = useMemo(() => buildParams(appliedFilters), [appliedFilters]);

  const getErrorMessage = useCallback(
    (err) =>
      err?.response?.data?.error ||
      err?.response?.data?.message ||
      "Unable to load this widget right now.",
    []
  );

  const applyIfCurrent = useCallback((fetchId, callback) => {
    if (!isMountedRef.current || fetchSequenceRef.current !== fetchId) {
      return;
    }
    callback();
  }, []);

  const summaryStatusColor = summaryStatus.status === "completed"
    ? "success"
    : summaryStatus.status === "failed"
      ? "error"
      : summaryStatus.status === "running"
        ? "warning"
        : "default";

  const downloadCommonCsv = useCallback(async (endpoint, filename, columns) => {
    try {
      const csvParams = columns?.length
        ? { ...params, columns: columns.join(",") }
        : params;
      const response = await API.get(endpoint, {
        params: csvParams,
        responseType: "blob",
      });

      const blob = new Blob([response.data], { type: "text/csv" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(`Failed to download ${filename}`, err);
    }
  }, [params]);

  const downloadTaxFlowCsv = useCallback(() =>
    downloadCommonCsv("/common/download-csv/tax-flow", "tax-flow.csv", [
      "tin",
      "taxpayer_name",
      "year",
      "income",
      "profit",
      "tax",
      "sector",
    ]), [downloadCommonCsv]);
  const downloadTopSectorsCsv = useCallback(() =>
    downloadCommonCsv("/common/download-csv/top-sectors", "top-sectors.csv", [
      "tin",
      "taxpayer_name",
      "sector",
      "income",
      "tax",
    ]), [downloadCommonCsv]);
  const downloadFraudYearCsv = useCallback(() =>
    downloadCommonCsv("/common/download-csv/fraud-year", "fraud-year.csv", [
      "tin",
      "taxpayer_name",
      "year",
      "fraud_cases",
    ]), [downloadCommonCsv]);
  const downloadFraudDistributionCsv = useCallback(() =>
    downloadCommonCsv("/common/download-csv/fraud-distribution", "fraud-distribution.csv", [
      "tin",
      "taxpayer_name",
      "risk_flag",
      "income",
      "exposure",
    ]), [downloadCommonCsv]);
  const downloadTopTinsCsv = useCallback(() =>
    downloadCommonCsv("/common/download-csv/top-tins", "top-tins.csv", [
      "tin",
      "taxpayer_name",
      "income",
      "tax",
      "profit",
    ]), [downloadCommonCsv]);
  const downloadConsolidatedCsv = useCallback(async () => {
    try {
      const response = await API.get("/common-dashboard/multitax-records", {
        params: { ...recordsQuery.filters, page: recordsQuery.page, page_size: recordsQuery.pageSize, format: "csv" },
        responseType: "blob",
      });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `multitax-records-page-${recordsQuery.page}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      Swal.fire({ icon: "error", text: getErrorMessage(err) });
    }
  }, [getErrorMessage, recordsQuery]);

  const chartSkeleton = (height = 350) => (
    <Box>
      <Skeleton variant="text" width="40%" height={32} />
      <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />
    </Box>
  );

  const noDataMessage = "No data exists for selected period.";

  const renderSectionError = (message) =>
    message ? (
      <Alert severity="error" sx={{ mt: 2 }}>
        {message}
      </Alert>
    ) : null;

  const renderNoData = () => (
    <Alert severity="info" sx={{ mt: 2 }}>
      {noDataMessage}
    </Alert>
  );

  /* ================= API CALL ================= */
  const loadOverview = useCallback(async (fetchId, requestParams) => {
    setOverviewLoading(true);
    setOverviewError("");
    try {
      const overviewRes = await API.get("/common-dashboard/financial-overview", { params: requestParams });
      applyIfCurrent(fetchId, () => {
        setOverview(overviewRes.data || {});
      });
    } catch (err) {
      console.error("Error fetching overview:", err);
      applyIfCurrent(fetchId, () => {
        setOverviewError(getErrorMessage(err));
      });
    } finally {
      applyIfCurrent(fetchId, () => {
        setOverviewLoading(false);
      });
    }
  }, [applyIfCurrent, getErrorMessage]);

  const loadTaxFlow = useCallback(async (fetchId, requestParams) => {
    setTaxFlowLoading(true);
    setTaxFlowError("");
    try {
      const flowRes = await API.get("/common-dashboard/tax-flow", { params: requestParams });
      applyIfCurrent(fetchId, () => {
        setTaxFlow({
          categories: flowRes.data?.categories ?? [],
          series: flowRes.data?.series ?? [],
        });
      });
    } catch (err) {
      console.error("Error fetching taxFlow:", err);
      applyIfCurrent(fetchId, () => {
        setTaxFlowError(getErrorMessage(err));
      });
    } finally {
      applyIfCurrent(fetchId, () => {
        setTaxFlowLoading(false);
      });
    }
  }, [applyIfCurrent, getErrorMessage]);

  const loadRiskExposure = useCallback(async (fetchId, requestParams) => {
    setRiskExposureLoading(true);
    setRiskExposureError("");
    try {
      const riskRes = await API.get("/common-dashboard/risk-exposure", { params: requestParams });
      applyIfCurrent(fetchId, () => {
        setRiskExposure(asArray(riskRes.data));
      });
    } catch (err) {
      console.error("Error fetching riskExposure:", err);
      applyIfCurrent(fetchId, () => {
        setRiskExposureError(getErrorMessage(err));
      });
    } finally {
      applyIfCurrent(fetchId, () => {
        setRiskExposureLoading(false);
      });
    }
  }, [applyIfCurrent, getErrorMessage]);

  const loadSectorAnalysis = useCallback(async (fetchId, requestParams) => {
    setSectorLoading(true);
    setSectorError("");
    try {
      const sectorRes = await API.get("/common-dashboard/sector-analysis", { params: requestParams });
      applyIfCurrent(fetchId, () => {
        setSectorData(asArray(sectorRes.data));
      });
    } catch (err) {
      console.error("Error fetching sector:", err);
      applyIfCurrent(fetchId, () => {
        setSectorError(getErrorMessage(err));
      });
    } finally {
      applyIfCurrent(fetchId, () => {
        setSectorLoading(false);
      });
    }
  }, [applyIfCurrent, getErrorMessage]);

  const loadTopFinancialTins = useCallback(async (fetchId, requestParams) => {
    setTopTinsLoading(true);
    setTopTinsError("");
    try {
      const topRes = await API.get("/common-dashboard/top-financial-tins", { params: requestParams });
      applyIfCurrent(fetchId, () => {
        setTopTins(asArray(topRes.data));
      });
    } catch (err) {
      console.error("Error fetching topTins:", err);
      applyIfCurrent(fetchId, () => {
        setTopTinsError(getErrorMessage(err));
      });
    } finally {
      applyIfCurrent(fetchId, () => {
        setTopTinsLoading(false);
      });
    }
  }, [applyIfCurrent, getErrorMessage]);

  useEffect(() => {
    const controller = new AbortController();
    setRecordsLoading(true);
    setRecordsError("");
    API.get("/common-dashboard/multitax-records", {
      params: { ...recordsQuery.filters, page: recordsQuery.page, page_size: recordsQuery.pageSize },
      signal: controller.signal,
    }).then(({ data }) => {
      if (controller.signal.aborted) return;
      if (data.page !== recordsQuery.page) {
        setRecordsQuery((previous) => ({ ...previous, page: data.page }));
        return;
      }
      setRecords(asArray(data.records));
      setRecordsTotal(Number(data.total) || 0);
    }).catch((err) => {
      if (!controller.signal.aborted) setRecordsError(getErrorMessage(err));
    }).finally(() => {
      if (!controller.signal.aborted) setRecordsLoading(false);
    });
    return () => controller.abort();
  }, [getErrorMessage, recordsQuery, recordsReload]);

  const loadFraudTrend = useCallback(async (fetchId, requestParams) => {
    setFraudTrendLoading(true);
    setFraudTrendError("");
    try {
      const fraudRes = await API.get("/common-dashboard/fraud-trend", { params: requestParams });
      applyIfCurrent(fetchId, () => {
        setFraudTrend(asArray(fraudRes.data));
      });
    } catch (err) {
      console.error("Error fetching fraudTrend:", err);
      applyIfCurrent(fetchId, () => {
        setFraudTrendError(getErrorMessage(err));
      });
    } finally {
      applyIfCurrent(fetchId, () => {
        setFraudTrendLoading(false);
      });
    }
  }, [applyIfCurrent, getErrorMessage]);

  const loadTinOptions = useCallback(async (query = "") => {
    setTinLoading(true);
    try {
      const res = await API.get("/common-dashboard/dropdown", {
        params: query ? { q: query } : undefined,
      });
      if (!isMountedRef.current) {
        return;
      }
      setTinList([
        ALL_TIN_OPTION,
        ...(res.data || []).map((row) => ({
          label: row.label || `${row.tin} - ${row.name || row.taxpayer_name}`,
          tin: row.tin,
          name: row.name || row.taxpayer_name,
        })),
      ]);
    } catch (err) {
      console.error("Error fetching dropdown:", err);
    } finally {
      if (isMountedRef.current) {
        setTinLoading(false);
      }
    }
  }, [ALL_TIN_OPTION]);

  const reloadDashboard = useCallback((requestParams = params) => {
    const fetchId = fetchSequenceRef.current + 1;
    fetchSequenceRef.current = fetchId;

    return Promise.all([
      loadOverview(fetchId, requestParams),
      loadTaxFlow(fetchId, requestParams),
      loadRiskExposure(fetchId, requestParams),
      loadSectorAnalysis(fetchId, requestParams),
      loadTopFinancialTins(fetchId, requestParams),
      loadFraudTrend(fetchId, requestParams),
    ]);
  }, [
    loadFraudTrend,
    loadOverview,
    loadRiskExposure,
    loadSectorAnalysis,
    loadTaxFlow,
    loadTopFinancialTins,
    params,
  ]);

  const loadSummaryStatus = useCallback(async ({ silent = false } = {}) => {
    if (statusRequestRef.current) return;
    statusRequestRef.current = true;
    try {
      const res = await API.get("/common-dashboard/rebuild-status");
      if (!isMountedRef.current) return;
      const data = res.data || {};
      setStatusPollError("");
      const rawStatus = String(data.status || "idle").toLowerCase();
      setSummaryStatus({
        status: rawStatus === "queued" ? "running" : rawStatus,
        progress: Number(data.progress ?? 0),
        currentStep: data.current_step || "",
        lastUpdated: data.last_updated || null,
        error: data.error || "",
      });
    } catch (err) {
      if (!silent) console.error("Error fetching summary status:", err);
      if (isMountedRef.current) setStatusPollError("Unable to read refresh status. The job may still be running.");
    } finally {
      statusRequestRef.current = false;
    }
  }, []);

  const startSummaryRebuild = useCallback(async () => {
    if (rebuildStartingRef.current) return;
    rebuildStartingRef.current = true;
    setRebuildStarting(true);
    try {
      await API.post("/common-dashboard/rebuild-summary");
      summaryStatusTransitionRef.current = "running";
      setSummaryStatus((previous) => ({ ...previous, status: "running", progress: 0, currentStep: "Preparing Multi-Tax Integration", error: "" }));
      setSummaryDialogOpen(true);
      await loadSummaryStatus();
    } catch (err) {
      if (err?.response?.status === 409) {
        summaryStatusTransitionRef.current = "running";
        setSummaryStatus((previous) => ({ ...previous, status: "running", error: "" }));
        setSummaryDialogOpen(true);
        await loadSummaryStatus();
        return;
      }
      console.error("Error starting summary rebuild:", err);
      if (isMountedRef.current) {
        if (!err?.response || err.response.status === 503) {
          setSummaryStatus((prev) => ({ ...prev, status: "running", currentStep: "Checking refresh status", error: "" }));
          setStatusPollError("Refresh startup was not confirmed. Checking the server before retrying.");
        } else {
          setSummaryStatus((prev) => ({ ...prev, status: "failed", error: getErrorMessage(err) }));
        }
        setSummaryDialogOpen(true);
      }
    } finally {
      rebuildStartingRef.current = false;
      if (isMountedRef.current) setRebuildStarting(false);
    }
  }, [getErrorMessage, loadSummaryStatus]);

  useEffect(() => {
    const isRunning = summaryStatus.status === "running";
    if (isRunning) {
      setSummaryDialogOpen(true);
    }
    if (isRunning || statusPollError) {
      if (!rebuildPollIntervalRef.current) {
        rebuildPollIntervalRef.current = window.setInterval(() => loadSummaryStatus({ silent: true }), 2000);
      }
    } else if (rebuildPollIntervalRef.current) {
      window.clearInterval(rebuildPollIntervalRef.current);
      rebuildPollIntervalRef.current = null;
    }
    if (summaryStatusTransitionRef.current === "running" && summaryStatus.status === "completed") {
      setSummaryDialogOpen(false);
      reloadDashboard();
      setRecordsReload((value) => value + 1);
      loadTinOptions(tinInputValue.trim());
    }
    summaryStatusTransitionRef.current = summaryStatus.status;
  }, [loadSummaryStatus, loadTinOptions, reloadDashboard, summaryStatus.status, statusPollError, tinInputValue]);

  useEffect(() => {
    isMountedRef.current = true;
    loadSummaryStatus();
    return () => {
      if (rebuildPollIntervalRef.current) {
        window.clearInterval(rebuildPollIntervalRef.current);
        rebuildPollIntervalRef.current = null;
      }
      isMountedRef.current = false;
    };
  }, [loadSummaryStatus]);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      loadTinOptions(tinInputValue.trim());
    }, 300);

    return () => window.clearTimeout(timerId);
  }, [loadTinOptions, tinInputValue]);

  const hasValidDateRange = Boolean(
    startDate?.isValid?.() &&
      endDate?.isValid?.() &&
      !startDate.isAfter(endDate, "day")
  );

  const handleSubmit = () => {
    if (isSubmitting || !hasValidDateRange) {
      return;
    }

    if (!selectedTin?.tin) {
      Swal.fire({ icon: "warning", text: "Please select TIN" });
      return;
    }

    const nextFilters = { startDate, endDate, selectedTin };
    setIsSubmitting(true);
    setAppliedFilters(nextFilters);
    setRecordsQuery((previous) => ({ ...previous, filters: buildParams(nextFilters), page: 1 }));
    Promise.all([
      reloadDashboard(buildParams(nextFilters)),
      loadTinOptions(tinInputValue.trim()),
    ]).finally(() => setIsSubmitting(false));
  };

  //SSO TOKEN HANDLING
  // useEffect(() => {
  //   const params = new URLSearchParams(window.location.search);

  //   const access = params.get("access");
  //   const refresh = params.get("refresh");


  //   if (access || refresh) {
  //     window.history.replaceState({}, document.title, "/common-dashboard");
  //   }
  // }, []);

  /* ================= KPI VALUES ================= */
  const turnover = useMemo(
    () => num(overview.total_income ?? overview.turnover ?? overview.income),
    [overview]
  );
  const profit = useMemo(() => num(overview.total_profit ?? overview.profit), [overview]);
  const tax = useMemo(
    () => num(overview.total_cit_tax ?? overview.total_tax ?? overview.tax),
    [overview]
  );
  const etr = useMemo(
    () => num(overview.effective_tax_rate ?? overview.effectiveRate ?? overview.etr),
    [overview]
  );

  const hasTaxFlowData = useMemo(() => asArray(taxFlow.categories).length > 0, [taxFlow.categories]);
  const hasSectorData = useMemo(() => asArray(sectorData).length > 0, [sectorData]);
  const hasTopTinsData = useMemo(() => asArray(topTins).length > 0, [topTins]);
  const hasRecordsData = useMemo(() => asArray(records).length > 0, [records]);
  const hasFraudTrendData = useMemo(() => asArray(fraudTrend).length > 0, [fraudTrend]);
  const hasRiskExposureData = useMemo(() => asArray(riskExposure).length > 0, [riskExposure]);
  const toggleChartView = (key) => setChartView((current) => ({ ...current, [key]: !current[key] }));
  const taxFlowTableData = useMemo(() => asArray(taxFlow.categories).map((category, index) => ({ id: `${category}-${index}`, period: category, ...Object.fromEntries(asArray(taxFlow.series).map((series, seriesIndex) => [`series_${seriesIndex}`, num(series?.data?.[index])])) })), [taxFlow]);
  const taxFlowTableColumns = useMemo(() => [{ name: "Period", selector: (row) => row.period, sortable: true }, ...asArray(taxFlow.series).map((series, index) => ({ name: series?.name || `Series ${index + 1}`, selector: (row) => row[`series_${index}`], sortable: true, right: true, format: (row) => row[`series_${index}`].toLocaleString() }))], [taxFlow]);
  const fraudTrendColumns = useMemo(() => [{ name: "Year", selector: (row) => row.year, sortable: true }, { name: "Fraud Cases", selector: (row) => num(row?.fraud_cases ?? row?.fraudCases ?? row?.count), sortable: true, right: true }], []);
  const riskExposureColumns = useMemo(() => [{ name: "Risk Status", selector: (row) => row?.predicted_fraud ?? "Unknown", sortable: true }, { name: "Taxpayers", selector: (row) => num(row?.taxpayers), sortable: true, right: true }], []);
  const hasOverviewData = useMemo(
    () => Object.keys(overview).length > 0,
    [overview]
  );

  /* ================= CHART OPTIONS ================= */

  const taxFlowCategories = useMemo(
    () => asArray(taxFlow?.categories ?? []),
    [taxFlow?.categories]
  );

  const taxFlowSeries = useMemo(
    () => asArray(taxFlow?.series ?? []),
    [taxFlow?.series]
  );

  const taxFlowOptions = useMemo(() => ({
    chart: { type: "line", height: 350 },
    stroke: { curve: "smooth", width: 3 },
    xaxis: { categories: taxFlowCategories ?? [] },
    tooltip: { shared: true, intersect: false },
    colors: ["#1E88E5", "#2ECC71", "#F39C12"],
  }), [taxFlowCategories]);

  const sectorOptions = useMemo(() => ({
    chart: {
      type: "bar",
      height: 350,
    },
    plotOptions: {
      bar: {
        horizontal: true,
        barHeight: "60%",
      },
    },
    xaxis: {
      categories: asArray(sectorData).map((s) =>
        (s.sector || "Unknown").slice(0, 30)
      ),
      labels: {
        formatter: (val) => {
          if (val >= 1_000_000_000)
            return "K " + (val / 1_000_000_000).toFixed(1) + "B";
          if (val >= 1_000_000)
            return "K " + (val / 1_000_000).toFixed(1) + "M";
          return "K " + val.toLocaleString();
        },

      },
    },
    tooltip: {
      y: {
        formatter: (val) => "K " + Number(val).toLocaleString(),
      },
    },
  }), [sectorData]);


  const sectorSeries = useMemo(() => [
    {
      name: "Income",
      data: asArray(sectorData).map((s) => num(s?.income)),
    },
  ], [sectorData]);

  const sectorColumns = useMemo(() => [
    { name: "Sector", selector: (r) => r.sector || "Unknown" },
    { name: "Income", selector: (r) => Number(r.income).toLocaleString() },
    { name: "Tax", selector: (r) => Number(r.tax).toLocaleString() },
    { name: "Taxpayers", selector: (r) => r.taxpayers },
  ], []);

  const topTinColumns = useMemo(() => [
    { name: "TIN", selector: (r) => r.tin },
    { name: "Taxpayer", selector: (r) => r.taxpayer },
    { name: "Income", selector: (r) => r.income },
    { name: "Tax", selector: (r) => r.tax },
  ], []);

  /* ================= TABLE ================= */
  const recordColumns = useMemo(() => [
    { name: "TIN", selector: (r) => str(r.tin, "") },
    { name: "Taxpayer", selector: (r) => str(r.taxpayer_name) },
    { name: "Year", selector: (r) => str(r.tax_period_year, "") },
    { name: "Account", selector: (r) => str(r.tax_account_number, "") },
    { name: "Assessment", selector: (r) => str(r.assessment_number, "") },
    { name: "CIT Gross Income", selector: (r) => num(r.cit_total_gross_income) },
    { name: "CIT Tax Payable", selector: (r) => num(r.cit_total_tax_payable) },
    { name: "GST Sales Difference", selector: (r) => num(r.gst_vs_cit_sales_diff_abs) },
    { name: "SWT Salary Difference", selector: (r) => num(r.swt_vs_cit_salary_diff_abs) },
    { name: "Sector", selector: (r) => str(r.sector_activity) },
    { name: "Multi-Tax Issue", selector: (r) => str(r.multi_tax_issue) },
  ], []);

  const fraudBarOptions = useMemo(() => ({
    chart: { type: "bar", height: 320 },
    plotOptions: {
      bar: {
        columnWidth: "50%",
        borderRadius: 4,
      },
    },
    xaxis: {
      categories: asArray(fraudTrend).map((f) => f?.year),
      title: { text: "Year" },
    },
    yaxis: {
      title: { text: "Fraud Cases" },
    },
    colors: ["#ff6850"],
  }), [fraudTrend]);

  const fraudBarSeries = useMemo(() => [
    {
      name: "Fraud Cases",
      data: asArray(fraudTrend).map((f) => num(f?.fraud_cases ?? f?.fraudCases ?? f?.count)),
    },
  ], [fraudTrend]);

  const fraudPieOptions = useMemo(() => ({
    chart: {
      toolbar: {
        show: false,
      },
    },
    labels: asArray(riskExposure).map((item) => item?.predicted_fraud ?? "Unknown"),
    legend: {
      position: "bottom",
      fontSize: "13px",
    },
    dataLabels: {
      enabled: true,
      formatter: function (val) {
        return `${val.toFixed(1)}%`;
      },
      style: {
        fontSize: "12px",
        fontWeight: "bold",
      },
      dropShadow: {
        enabled: false,
      },
    },
    tooltip: {
      custom: function ({ series, seriesIndex, w }) {
        const label = w.globals.labels[seriesIndex];
        const value = series[seriesIndex];
        const total = w.globals.seriesTotals.reduce((a, b) => a + b, 0);
        const percent = total ? ((value / total) * 100).toFixed(1) : "0.0";

        return `
          <div style="
            padding:8px 12px;
            background:#fff;
            border-radius:6px;
            border:1px solid #ddd;
            box-shadow:0 2px 6px rgba(0,0,0,0.15);
            font-size:13px;
            color:#333;
            text-align:center;
          ">
            <strong>${label}</strong><br/>
            ${value} taxpayers<br/>
            ${percent}%
          </div>
        `;
      }
    },
    plotOptions: {
      pie: {
        dataLabels: {
          offset: -5,
        },
      },
    },
  }), [riskExposure]);

  const fraudPieSeries = useMemo(
    () => asArray(riskExposure).map((item) => num(item?.taxpayers)),
    [riskExposure]
  );

  const dashboardRef = useRef();
  const downloadDashboardPDF = useCallback(async () => {
    const input = dashboardRef.current;
    if (!input) return;

    const pdf = new jsPDF("p", "mm", "a4");
    const sections = input.querySelectorAll(".page");

    const now = dayjs().format("DD MMM YYYY, HH:mm");
    let isFirstPage = true;

    // 1. Hide buttons temporarily
    const hiddenEls = input.querySelectorAll(".hideme");
    hiddenEls.forEach(el => {
      el.dataset.originalDisplay = el.style.display;
      el.style.display = "none";
    });

    // 2. Generate PDF
    for (let section of sections) {
      const canvas = await html2canvas(section, {
        scale: 2,
        useCORS: true,
        scrollY: -window.scrollY,
      });

      const imgData = canvas.toDataURL("image/png");

      const pageWidth = pdf.internal.pageSize.getWidth(); // 210
      const margin = 10; // left + right margin
      const imgWidth = pageWidth - margin * 2; // 190mm
      const imgHeight = (canvas.height * imgWidth) / canvas.width;


      if (!isFirstPage) {
        pdf.addPage();
      }

      // Header
      pdf.setFontSize(12);
      pdf.text("Common Dashboard Report", 10, 10);
      pdf.setFontSize(8);
      pdf.text(`Generated: ${now}`, 10, 15);

      pdf.addImage(imgData, "PNG", margin, 20, imgWidth, imgHeight);

      isFirstPage = false;
    }

    // 3. Restore hidden elements
    hiddenEls.forEach(el => {
      el.style.display = el.dataset.originalDisplay || "";
    });

    const fileTime = dayjs().format("YYYY-MM-DD_HH-mm");
    pdf.save(`Common-Dashboard_${fileTime}.pdf`);
  }, []);


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
          <main className="main-content p-3 mt-5 flex-grow-1" ref={dashboardRef}>

                <div className="container">

                  <div className="page">
                    <div className="d-flex flex-column flex-md-row justify-content-between align-items-md-start gap-3 mb-3">
                        <div>
                          <div className="header-title-page">Dashboard</div>
                          <Paper variant="outlined" sx={{ mt: 1.5, p: 1.5, minWidth: { xs: "100%", md: 320 } }}>
                            <div className="d-flex justify-content-between align-items-center mb-2">
                              <Typography variant="subtitle2">Dashboard Summary</Typography>
                              <Chip size="small" color={summaryStatusColor} label={summaryStatus.status === "completed" ? "Up To Date" : summaryStatus.status === "running" ? `Refreshing ${Math.round(summaryStatus.progress || 0)}%` : summaryStatus.status === "failed" ? "Refresh Failed" : "Not Built"} />
                            </div>
                            <Typography variant="body2" color="text.secondary">
                              Last Refresh {summaryStatus.lastUpdated ? dayjs(summaryStatus.lastUpdated).format("DD-MMM-YYYY HH:mm") : "-"}
                            </Typography>
                          </Paper>
                        </div>

                        <div className="d-flex align-items-center gap-2 hideme">
                          <Button variant="outlined" color="primary" size="small" disabled={rebuildStarting || summaryStatus.status === "running"} onClick={startSummaryRebuild}>
                            Run Multi-Tax Integration
                          </Button>
                          <Button variant="contained" color="primary" size="small" onClick={downloadDashboardPDF}>
                            Download PDF
                          </Button>
                        </div>
                      </div>

                    {/* FILTER ROW */}
                    <LocalizationProvider dateAdapter={AdapterDayjs}>
                      <div className="row mb-4">

                        <div className="col-md-4">
                          <DatePicker
                            label="Start Date"
                            format="DD/MM/YYYY"
                            value={startDate}
                            onChange={(newValue) => {
                              if (newValue && !newValue.isValid()) return;

                              if (!newValue) {
                                setStartDate(null);
                                return;
                              }

                              const year = newValue.year();
                              if (year < 1900 || year > 2100) return;

                              setStartDate(newValue);
                            }}
                            slotProps={{
                              textField: {
                                fullWidth: true,
                                size: "small",
                                inputProps: {
                                  readOnly: true // ðŸ”¥ BLOCK KEYBOARD
                                }
                              }
                            }}
                          />
                        </div>

                        <div className="col-md-4">
                          <DatePicker
                            label="End Date"
                            format="DD/MM/YYYY"
                            value={endDate}
                            onChange={(newValue) => {
                              if (newValue && !newValue.isValid()) return;

                              if (!newValue) {
                                setEndDate(null);
                                return;
                              }

                              const year = newValue.year();
                              if (year < 1900 || year > 2100) return;

                              setEndDate(newValue);
                            }}
                            slotProps={{
                              textField: {
                                fullWidth: true,
                                size: "small",
                                inputProps: {
                                  readOnly: true
                                }
                              }
                            }}
                          />
                        </div>

                        <div className="col-md-4">
                          <Autocomplete
                            options={tinList}
                            value={selectedTin}
                            loading={tinLoading}
                            inputValue={tinInputValue}
                            getOptionLabel={(option) => option?.label || ""}
                            isOptionEqualToValue={(option, value) =>
                              option?.tin === value?.tin
                            }
                            onChange={(_, value) => setSelectedTin(value || ALL_TIN_OPTION)}
                            onInputChange={(_, value) => setTinInputValue(value)}
                            renderInput={(params) => (
                              <TextField {...params} size="small" label="TIN / Taxpayer" />
                            )}
                          />
                        </div>

                        <div className="col-12 d-flex justify-content-end mt-2">
                          <Button
                            size="small"
                            variant="contained"
                            disabled={isSubmitting || !hasValidDateRange}
                            onClick={handleSubmit}
                          >
                            Submit
                          </Button>
                        </div>

                      </div>
                    </LocalizationProvider>

                    {/* KPI CARDS */}
                    <div className="row mb-4">
                      <div className="col-md-4">
                        <Paper className="p-3 text-center">
                          {overviewLoading ? (
                            <>
                              <Skeleton variant="text" width="55%" sx={{ mx: "auto" }} />
                              <Skeleton variant="text" width="70%" height={40} sx={{ mx: "auto" }} />
                            </>
                          ) : overviewError ? null : hasOverviewData ? (
                            <>
                              <small>Total Income</small>
                              <h4>K {turnover.toLocaleString()}</h4>
                            </>
                          ) : (
                            <small>{noDataMessage}</small>
                          )}
                        </Paper>
                      </div>

                      <div className="col-md-3">
                        <Paper className="p-3 text-center">
                          {overviewLoading ? (
                            <>
                              <Skeleton variant="text" width="55%" sx={{ mx: "auto" }} />
                              <Skeleton variant="text" width="70%" height={40} sx={{ mx: "auto" }} />
                            </>
                          ) : overviewError ? null : hasOverviewData ? (
                            <>
                              <small>Total Profit</small>
                              <h4>K {profit.toLocaleString()}</h4>
                            </>
                          ) : (
                            <small>{noDataMessage}</small>
                          )}
                        </Paper>
                      </div>

                      <div className="col-md-3">
                        <Paper className="p-3 text-center">
                          {overviewLoading ? (
                            <>
                              <Skeleton variant="text" width="55%" sx={{ mx: "auto" }} />
                              <Skeleton variant="text" width="70%" height={40} sx={{ mx: "auto" }} />
                            </>
                          ) : overviewError ? null : hasOverviewData ? (
                            <>
                              <small>Total CIT Tax</small>
                              <h4>K {tax.toLocaleString()}</h4>
                            </>
                          ) : (
                            <small>{noDataMessage}</small>
                          )}
                        </Paper>
                      </div>

                      <div className="col-md-2">
                        <Paper className="p-3 text-center">
                          {overviewLoading ? (
                            <>
                              <Skeleton variant="text" width="70%" sx={{ mx: "auto" }} />
                              <Skeleton variant="text" width="60%" height={40} sx={{ mx: "auto" }} />
                            </>
                          ) : overviewError ? null : hasOverviewData ? (
                            <>
                              <small>Effective Tax Rate</small>
                              <h4>{etr}%</h4>
                            </>
                          ) : (
                            <small>{noDataMessage}</small>
                          )}
                        </Paper>
                      </div>

                      <div className="col-md-12">
                        {renderSectionError(overviewError)}
                      </div>

                      <div className="col-md-12 mt-4">
                        {/* TAX FLOW */}
                        <ChartDataCard title="Tax Flow (Income vs Profit vs CIT)" isChartView={chartView.taxFlow} onToggleView={() => toggleChartView("taxFlow")} onDownloadCsv={downloadTaxFlowCsv} loading={taxFlowLoading} hasData={hasTaxFlowData} chartSkeleton={chartSkeleton(350)} tableSkeleton={<TableSkeleton columnCount={Math.max(asArray(taxFlow.series).length + 1, 4)} />} emptyMessage="No records available for the selected criteria"
                          chartContent={
                            <Chart
                              options={taxFlowOptions}
                              series={taxFlowSeries}
                              type="bar"
                              height={350}
                            />
                          }
                          tableContent={<DataTable columns={taxFlowTableColumns} data={taxFlowTableData} dense pagination paginationPerPage={10} customStyles={tableCustomStyles} />}
                        />
                        {renderSectionError(taxFlowError)}
                      </div>
                    </div>


                    {/* SECTOR + TOP TINS */}
                    <div className="row mb-4">
                      <div className="col-md-12">
                        <ChartDataCard title="Top Sectors by Income" isChartView={chartView.sector} onToggleView={() => toggleChartView("sector")} onDownloadCsv={downloadTopSectorsCsv} loading={sectorLoading} hasData={hasSectorData} chartSkeleton={chartSkeleton(350)} tableSkeleton={<TableSkeleton columnCount={sectorColumns.length} />} emptyMessage="No records available for the selected criteria"
                          chartContent={
                            <div style={{ overflowX: "auto" }}>
                              <div style={{ minWidth: `${sectorData.length * 120}px` }}>
                                <Chart
                                  options={sectorOptions}
                                  series={sectorSeries}
                                  type="bar"
                                  height={350}
                                />
                              </div>
                            </div>
                          }
                          tableContent={<DataTable columns={sectorColumns} data={sectorData} dense pagination paginationPerPage={10} customStyles={tableCustomStyles} />}
                        />
                        {renderSectionError(sectorError)}

                      </div>
                      <div className="col-md-12">
                        <Paper className="p-3 mb-4 table-responsive">
                          {sectorLoading ? (
                            <Skeleton variant="rectangular" height={260} sx={{ borderRadius: 2 }} />
                          ) : sectorError ? null : hasSectorData ? (
                            <DataTable
                              columns={sectorColumns}
                              data={sectorData}
                              dense
                              pagination
                              customStyles={tableCustomStyles}
                            />
                          ) : (
                            renderNoData()
                          )}
                        </Paper>
                      </div>

                    </div>

                  </div>
                  
                    <div className="row mb-4 page">

                        {/* Bar Chart */}
                        <div className="col-md-6">
                          <ChartDataCard title="Fraud Cases by Year" isChartView={chartView.fraudTrend} onToggleView={() => toggleChartView("fraudTrend")} onDownloadCsv={downloadFraudYearCsv} loading={fraudTrendLoading} hasData={hasFraudTrendData} chartSkeleton={chartSkeleton(320)} tableSkeleton={<TableSkeleton columnCount={2} />} emptyMessage="No records available for the selected criteria"
                            chartContent={
                                <Chart
                                  options={fraudBarOptions}
                                  series={fraudBarSeries}
                                  type="bar"
                                  height={320}
                                />
                            }
                            tableContent={<DataTable columns={fraudTrendColumns} data={fraudTrend} dense pagination paginationPerPage={10} customStyles={tableCustomStyles} />}
                          />
                          {renderSectionError(fraudTrendError)}
                        </div>

                        {/* Pie Chart */}
                        <div className="col-md-6">
                          <ChartDataCard title="Fraud Distribution" isChartView={chartView.fraudDistribution} onToggleView={() => toggleChartView("fraudDistribution")} onDownloadCsv={downloadFraudDistributionCsv} loading={riskExposureLoading} hasData={hasRiskExposureData} chartSkeleton={chartSkeleton(320)} tableSkeleton={<TableSkeleton columnCount={2} />} emptyMessage="No records available for the selected criteria"
                            chartContent={
                                <Chart
                                  options={fraudPieOptions}
                                  series={fraudPieSeries}
                                  type="pie"
                                  height={320}
                                />
                            }
                            tableContent={<DataTable columns={riskExposureColumns} data={riskExposure} dense pagination paginationPerPage={10} customStyles={tableCustomStyles} />}
                          />
                          {renderSectionError(riskExposureError)}
                        </div>

                      <div className="col-md-12">
                        <Paper className="p-3 mb-4 table-responsive">
                          <div className="d-flex justify-content-between align-items-center">
                            <h6>Top Financial TINs</h6>
                            <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadTopTinsCsv}>
                              CSV
                            </Button>
                          </div>
                          {topTinsLoading ? (
                            <Skeleton variant="rectangular" height={260} sx={{ borderRadius: 2 }} />
                          ) : topTinsError ? null : hasTopTinsData ? (
                            <DataTable
                              columns={topTinColumns}
                              data={topTins}
                              pagination
                              dense
                              customStyles={tableCustomStyles}
                            />
                          ) : (
                            renderNoData()
                          )}
                          {renderSectionError(topTinsError)}
                        </Paper>
                      </div>
                      <div className="col-md-12">
                        {/* MAIN TABLE */}
                        <Paper className="p-3 mb-4 table-responsive">
                          <div className="d-flex justify-content-between align-items-center">
                            <h6>Multi-Tax Records ({recordsTotal.toLocaleString()})</h6>
                            <Button size="small" onClick={() => setRecordsQuery((previous) => ({ ...previous, filters: { range_type: "all" }, page: 1 }))}>Show all records</Button>
                            <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadConsolidatedCsv} disabled={recordsLoading || !!recordsError || !hasRecordsData}>
                              CSV (current page)
                            </Button>
                          </div>
                          <p className="text-muted small">
                            {recordsQuery.filters.range_type === "all" ? "All taxpayers and all periods." : "Showing the submitted TIN and period filters."}
                          </p>
                          <DataTable
                            key={`${recordsQuery.page}-${recordsQuery.pageSize}`}
                            columns={recordColumns}
                            data={recordsError ? [] : records}
                            progressPending={recordsLoading}
                            progressComponent={<Skeleton variant="rectangular" height={320} width="100%" />}
                            noDataComponent={recordsError ? "Records could not be loaded." : "No Multi-Tax records found."}
                            pagination
                            paginationServer
                            paginationTotalRows={recordsTotal}
                            paginationPerPage={recordsQuery.pageSize}
                            paginationDefaultPage={recordsQuery.page}
                            paginationRowsPerPageOptions={[25, 50, 100, 200]}
                            onChangePage={(page) => setRecordsQuery((previous) => ({ ...previous, page }))}
                            onChangeRowsPerPage={(pageSize) => setRecordsQuery((previous) => ({ ...previous, pageSize, page: 1 }))}
                            customStyles={tableCustomStyles}
                          />
                          {renderSectionError(recordsError)}
                        </Paper>
                      </div>
                    </div>

                </div>

          <Dialog
            open={summaryDialogOpen}
            onClose={() => {
              if (summaryStatus.status !== "running") {
                setSummaryDialogOpen(false);
              }
            }}
            fullWidth
            maxWidth="xs"
          >
            <DialogTitle>Run Multi-Tax Integration</DialogTitle>
            <DialogContent>
              {statusPollError && <Alert severity="warning">{statusPollError}</Alert>}
              <Typography variant="body2" sx={{ mb: 1 }}>
                {summaryStatus.currentStep || "Refreshing dashboard summary"}
              </Typography>
              <LinearProgress variant="determinate" value={Math.min(100, Math.max(0, Number(summaryStatus.progress || 0)))} />
              <Typography variant="body2" sx={{ mt: 1 }}>
                Progress {Math.round(summaryStatus.progress || 0)}%
              </Typography>
              {summaryStatus.status === "failed" && summaryStatus.error ? (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {summaryStatus.error}
                </Alert>
              ) : null}
            </DialogContent>
          </Dialog>

          </main>
        </div>

      </div>
      <Footer />


    </div>
  );
}



