import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";

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
  Tooltip,
  CircularProgress,
  Typography,
  Alert,
  Skeleton,
  Box,
} from "@mui/material";
import RemoveRedEyeIcon from "@mui/icons-material/RemoveRedEye";
import dayjs from "dayjs";
// import axios from "axios";
import "./css/Dashboard.css";
import tableCustomStyles from "../components/common/tableStyles";

// Reusable Fraud Reason Popup
import FraudReasonDialog from "../components/common/FraudReasonDialog";
import DataTableExport from "../components/common/DataTableExport";
import API from "../api/api";
import TableChartIcon from "@mui/icons-material/TableChart";    // CSV icon
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

const PNGMapGST = lazy(() =>
  import("../components/maps/PNGMapGST")
);

const asArray = (v) => (Array.isArray(v) ? v : []);
const num = (v) => Number(v ?? 0);
const str = (v, fallback = "") => (v === null || v === undefined ? fallback : String(v));
const DASHBOARD_CACHE_TTL_MS = 5 * 60 * 1000;
const dashboardMemoryCache = new Map();
const inflightDashboardRequests = new Map();


export default function Dashboard() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const [tenure, setTenure] = useState("1m");
  const [startDate, setStartDate] = useState(dayjs().startOf("month"));
  const [endDate, setEndDate] = useState(dayjs().endOf("month"));

  const [summary, setSummary] = useState({});
  const [salesChart, setSalesChart] = useState({ categories: [], series: [] });
  const [gstChart, setGstChart] = useState({ categories: [], series: [] });
  const [segmentation, setSegmentation] = useState({ labels: [], series: [] });
  const [riskChart, setRiskChart] = useState({ labels: [], series: [] });
  // const [excelDownload, setExcelDownload] = useState(null);

  const [mapStaticData, setMapStaticData] = useState([]);
  const [selectedProvinceData, setSelectedProvinceData] = useState(null);
  const [dashboardError, setDashboardError] = useState("");
  const [shouldLoadProvince, setShouldLoadProvince] = useState(false);
  const [sectionLoading, setSectionLoading] = useState({
    summary: true,
    sales: true,
    gst: true,
    segmentation: true,
    risk: true,
    province: false,
  });



  const [searchText, setSearchText] = useState("");

  // Fraud popup state
  const [openDialog, setOpenDialog] = useState(false);
  const [fraudMessage, setFraudMessage] = useState("");

  const memoizedMapData = useMemo(
    () => mapStaticData,
    [mapStaticData]
  );

  const handleProvinceSelect = useCallback(
    (province, data) => {
      setSelectedProvinceData({
        province,
        fraud_count: data?.fraud_count ?? 0,
        risk_percentage: data?.risk_percentage ?? 0,
      });
    },
    []
  );

  const dashboardRef = useRef();
  const activeControllersRef = useRef([]);
  const provinceSectionRef = useRef(null);
  // const downloadDashboardPDF = async () => {
  //   const input = dashboardRef.current;

  //   if (!input) return;

  //   const canvas = await html2canvas(input, {
  //     scale: 2,
  //     useCORS: true,
  //     scrollY: -window.scrollY,
  //   });

  //   const imgData = canvas.toDataURL("image/png");

  //   const pdf = new jsPDF("p", "mm", "a4");

  //   const imgWidth = 210;
  //   const pageHeight = 297;
  //   const imgHeight = (canvas.height * imgWidth) / canvas.width;

  //   let heightLeft = imgHeight;
  //   let position = 0;

  //   pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
  //   heightLeft -= pageHeight;

  //   while (heightLeft > 0) {
  //     position = heightLeft - imgHeight;
  //     pdf.addPage();
  //     pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
  //     heightLeft -= pageHeight;
  //   }

  //   const fileTime = dayjs().format("YYYY-MM-DD_HH-mm");
  //   pdf.save(`GST-Dashboard_${fileTime}.pdf`);
  // };

  const downloadDashboardPDF = async () => {
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
      pdf.text("GST Dashboard Report", 10, 10);
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
    pdf.save(`GST-Dashboard_${fileTime}.pdf`);
  };



  const chartExportToolbar = {
    show: true,
    tools: {
      download: true,
      selection: false,
      zoom: false,
      zoomin: false,
      zoomout: false,
      pan: false,
      reset: false,
    },
    export: {
      csv: {
        filename: "chart-data",
        columnDelimiter: ",",
        headerCategory: "Category",
        headerValue: "Value",
      },
      svg: { filename: "chart-image" },
      png: { filename: "chart-image" },
    },
  };

  // const BASE = "http://127.0.0.1:5000/api";
  // const accessToken = localStorage.getItem("access");

  // const axiosInstance = axios.create({
  //   baseURL: BASE,
  //   headers: { Authorization: accessToken ? `Bearer ${accessToken}` : "" },
  // });



  // Build params based on selected tenure/date
  const getParams = () => {
    const params = { range_type: tenure };
    if (tenure === "custom" && startDate && endDate) {
      params.start_date = startDate.format("YYYY-MM-DD");
      params.end_date = endDate.format("YYYY-MM-DD");
    }
    return params;
  };

  const selectedRangeMonths = startDate && endDate
    ? endDate.diff(startDate, "month") + 1
    : 0;
  const isLargeDashboardRange = selectedRangeMonths > 24;

    

  // tenure change logic
const handleTenureChange = (e) => {
  const val = e.target.value;
  setTenure(val);

    const today = dayjs();
    let start, end;

    switch (val) {
      case "1m":
        start = today.startOf("month");
        end = today.endOf("month");
        break;
      case "3m":
        start = today.subtract(2, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "6m":
        start = today.subtract(5, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "1y":
        start = today.subtract(11, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "custom":
      default:
        return; // handled via date pickers
    }

    setStartDate(start);
    setEndDate(end);
  };

  const downloadCsv = async (endpoint, filename, columns) => {
    try {
      const params = getParams();
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
  };

  const downloadSalesCsv = () =>
    downloadCsv("/gst/download-csv/sales-comparison", "sales-comparison.csv", [
      "tin",
      "taxpayer_name",
      "month",
      "total_sales",
      "exempt_sales",
      "zero_rated_sales",
      "taxable_sales",
    ]);
  const downloadPayableCsv = () =>
    downloadCsv("/gst/download-csv/payable-vs-refundable", "payable-vs-refundable.csv", [
      "tin",
      "taxpayer_name",
      "month",
      "gst_payable",
      "gst_refundable",
    ]);
  const downloadSegmentationCsv = () =>
    downloadCsv("/gst/download-csv/segmentation", "segmentation.csv", [
      "tin",
      "taxpayer_name",
      "segment",
    ]);
  const downloadRiskCsv = () =>
    downloadCsv("/gst/download-csv/risk-flagged", "risk-flagged.csv", [
      "tin",
      "taxpayer_name",
      "risk_flag",
      "count",
    ]);
  const downloadProvinceCsv = () =>
    downloadCsv("/gst/download-csv/province", "province.csv", [
      "tin",
      "taxpayer_name",
      "province",
      "risk_percentage",
    ]);

const [loading, setLoading] = useState(true);
const abortActiveRequests = () => {
  activeControllersRef.current.forEach((controller) => {
    try {
      controller.abort();
    } catch {
      // no-op
    }
  });
  activeControllersRef.current = [];
};

const getRequestErrorMessage = (error, timeoutMs = 60000) => {
  if (error?.code === "ERR_CANCELED" || error?.code === "ECONNABORTED") {
    return `GST dashboard request timed out after ${Math.round(timeoutMs / 1000)} seconds. Please try again.`;
  }

  const backendMessage =
    error?.response?.data?.error ||
    error?.response?.data?.message;

  if (backendMessage) {
    return backendMessage;
  }

  return "Unable to load GST dashboard right now. Please try again.";
};

const makeCacheKey = (url, params) => `${url}:${JSON.stringify(params || {})}`;

const getWithTimeout = async (url, params, options = {}) => {
  const {
    useMemoryCache = false,
    ttlMs = DASHBOARD_CACHE_TTL_MS,
    timeoutMs = 60000,
  } = options;
  const cacheKey = makeCacheKey(url, params);

  if (useMemoryCache) {
    const cached = dashboardMemoryCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value;
    }
  }

  if (inflightDashboardRequests.has(cacheKey)) {
    return inflightDashboardRequests.get(cacheKey);
  }

  const controller = new AbortController();
  activeControllersRef.current.push(controller);

  const requestPromise = API.get(url, {
      params,
      signal: controller.signal,
      timeout: timeoutMs,
    })
    .then((response) => {
      if (useMemoryCache) {
        dashboardMemoryCache.set(cacheKey, {
          value: response,
          expiresAt: Date.now() + ttlMs,
        });
      }
      return response;
    })
    .finally(() => {
      inflightDashboardRequests.delete(cacheKey);
      activeControllersRef.current = activeControllersRef.current.filter(
        (item) => item !== controller
      );
    });

  inflightDashboardRequests.set(cacheKey, requestPromise);
  return requestPromise;
};

const formatCurrency = (val) => {
  if (val === null || val === undefined) return "PGK 0.00";
  return "K " + Number(val).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

  // fetch dashboard data
const fetchDashboardData = async () => {
  try {
    abortActiveRequests();
    setLoading(true);   // start loader
    setDashboardError("");
    setShouldLoadProvince(false);
    setMapStaticData([]);
    setSectionLoading({
      summary: true,
      sales: true,
      gst: true,
      segmentation: true,
      risk: true,
      province: false,
    });
    const params = getParams();
    const dashboardTimeoutMs = isLargeDashboardRange ? 90000 : 60000;

    const summaryRes = await getWithTimeout("/dashboard/data", params, {
      useMemoryCache: false,
      timeoutMs: dashboardTimeoutMs,
    });

    console.log("SUMMARY API RESPONSE:", summaryRes?.data);

    const summaryData = summaryRes?.data || {};

    setSummary({
      total_tax_payers: Number(
        summaryData.total_tax_payers ??
        summaryData.total_tax_payers_count ??
        0
      ),

      total_sales_income: Number(
        summaryData.total_sales_income ??
        summaryData.total_sales ??
        summaryData.sales_income ??
        0
      ),

      total_gst_payable: Number(
        summaryData.total_gst_payable ??
        summaryData.gst_payable ??
        summaryData.gstPayable ??
        0
      ),

      total_gst_refundable: Number(
        summaryData.total_gst_refundable ??
        summaryData.gst_refundable ??
        summaryData.gstRefundable ??
        0
      ),
    });

    setSectionLoading((prev) => ({
      ...prev,
      summary: false,
    }));

    const salesRes = await getWithTimeout("/dashboard/sales-comparison", params, {
      useMemoryCache: true,
      timeoutMs: dashboardTimeoutMs,
    });
    setSalesChart({
      categories: asArray(salesRes.data?.categories),
      series: asArray(salesRes.data?.series),
    });
    setSectionLoading((prev) => ({ ...prev, sales: false }));

    const [gstRes, segRes, riskRes] = await Promise.all([
      getWithTimeout("/dashboard/gst-payable-vs-refund", params, {
        useMemoryCache: true,
        timeoutMs: dashboardTimeoutMs,
      }),
      getWithTimeout("/dashboard/segmentation-distribution", params, {
        useMemoryCache: true,
        timeoutMs: dashboardTimeoutMs,
      }),
      getWithTimeout("/dashboard/risk-flagged", params, {
        useMemoryCache: true,
        timeoutMs: dashboardTimeoutMs,
      }),
    ]);

    setGstChart({
      categories: asArray(gstRes.data?.categories),
      series: asArray(gstRes.data?.series),
    });
    setSegmentation({
      labels: asArray(segRes.data?.labels),
      series: asArray(segRes.data?.series),
    });
    setRiskChart({
      labels: asArray(riskRes.data?.labels),
      series: asArray(riskRes.data?.series),
    });
    setSectionLoading((prev) => ({
      ...prev,
      gst: false,
      segmentation: false,
      risk: false,
    }));



  } catch (err) {
    console.error("Error fetching dashboard data:", err);
    setDashboardError(
      getRequestErrorMessage(err, isLargeDashboardRange ? 90000 : 60000)
    );
    setSectionLoading({
      summary: false,
      sales: false,
      gst: false,
      segmentation: false,
      risk: false,
      province: false,
    });
  } finally {
    setLoading(false);   // stop loader
  }
};

const fetchProvinceData = async () => {
  try {
    setSectionLoading((prev) => ({ ...prev, province: true }));
    const params = getParams();
    const dashboardTimeoutMs = isLargeDashboardRange ? 90000 : 60000;
    const fraudMapRes = await getWithTimeout(
      "/dashboard/fraud-province-distribution",
      params,
      { useMemoryCache: false, timeoutMs: dashboardTimeoutMs }
    );

    const provObj = fraudMapRes?.data?.province_distribution || {};
    const heatmapArray = Object.entries(
      provObj
    ).map(([prov, rec]) => ({
      province: prov,
      fraud_count: Number(
        rec?.fraud_tins ?? 0
      ),
      risk_percentage: Number(
        rec?.risk_percentage ?? 0
      ),
    }));

    setMapStaticData(heatmapArray);
  } catch (err) {
    console.error("Error fetching province distribution:", err);
    setDashboardError(
      getRequestErrorMessage(err, isLargeDashboardRange ? 90000 : 60000)
    );
  } finally {
    setSectionLoading((prev) => ({ ...prev, province: false }));
  }
};

  // Trigger API call when tenure or date changes
  useEffect(() => {
    fetchDashboardData();
  }, [tenure, startDate, endDate]);

  useEffect(() => {
    return () => {
      abortActiveRequests();
    };
  }, []);

  useEffect(() => {
    if (!provinceSectionRef.current || shouldLoadProvince) {
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting) {
          setShouldLoadProvince(true);
        }
      },
      { rootMargin: "200px 0px" }
    );

    observer.observe(provinceSectionRef.current);

    return () => observer.disconnect();
  }, [shouldLoadProvince]);

  useEffect(() => {
    if (!shouldLoadProvince) return;

    const timeout = setTimeout(() => {
      fetchProvinceData();
    }, 50);

    return () => clearTimeout(timeout);
  }, [
    shouldLoadProvince,
    tenure,
    startDate?.valueOf(),
    endDate?.valueOf(),
  ]);

  // Apex options
  const salesOptions = {
  chart: {
    type: "line",
    toolbar: {
      show: true,
      tools: {
        download: true,
      },
    },
    zoom: { enabled: true },
  },
  xaxis: {
    categories: salesChart.categories,
    tickPlacement: "on",
    labels: { rotate: -45 },
  },
  stroke: { curve: "smooth" },
  legend: {
    position: "top",
    horizontalAlign: "left",
  },
  yaxis: {
    labels: {
      formatter: (val) => formatCurrency(val),
    },
  },
  tooltip: {
    y: {
      formatter: (val) => formatCurrency(val),
    },
  },
};


  // Horizontal bar for Segmentation Distribution
  const segmentationOptions = {
    chart: { type: "bar", toolbar: chartExportToolbar },
    plotOptions: {
      bar: {
        borderRadius: 6,
        dataLabels: { position: "top" },
      },
    },
    dataLabels: {
      enabled: true,
      formatter: (val) => (val ? val.toLocaleString() : ""),
      offsetY: -15,
      style: {
        fontSize: "9px",
        colors: ["#000"],
        fontWeight: "500",
      },
    },
    xaxis: { categories: segmentation.labels },
    colors: ["#1E90FF", "#2ECC71", "#F1C40F", "#E67E22", "#9B59B6", "#E74C3C"],
    title: {
      text: "Segmentation Distribution (by Count)",
      style: { color: "#333", fontWeight: "bold" },
    },
  };

  const riskOptions = {
    chart: { type: "pie", toolbar: chartExportToolbar },
    labels: riskChart.labels,
    legend: { position: "bottom" },
  };

  // DataTable Columns (includes View button for Fraud Reason)
  const columns = [
    { name: "TIN", selector: (row) => row.tin_number, sortable: true },
    { name: "Taxpayer Name", selector: (row) => row.taxpayer_name, sortable: true, wrap: true },
    { name: "Segmentation", selector: (row) => row.segment_label || "-", sortable: true },
    { name: "Total Sales", selector: (row) => row.total_sales_income || 0, sortable: true },
    { name: "GST Payable", selector: (row) => row.gst_payable || 0, sortable: true },
    { name: "GST Refundable", selector: (row) => row.gst_refundable || 0, sortable: true },
    {
      name: "Tax Year & Month",
      selector: (row) =>
        `${row.tax_period_year}-${String(row.tax_period_month).padStart(2, "0")}`,
      sortable: true,
    },
    {
      name: "Fraud",
      selector: (row) => row.flagged,
      sortable: true,
      cell: (row) => (
        <span className={`badge ${row.flagged === "Yes" ? "bg-danger" : "bg-success"}`}>
          {row.flagged || "-"}
        </span>
      ),
    },
    { name: "Risk Type", selector: (row) => row.risk_type || "-", sortable: true },
    {
      name: "Fraud Reason",
      selector: (row) => row.fraud_reason,
      grow: 3,
      cell: (row) =>
        row.fraud_reason ? (
          <Tooltip title="View Fraud Reason">
            <Button
              variant="outlined"
              size="small"
              style={{ backgroundColor: "#dc3545", color: "#fff" }}
              onClick={() => {
                setFraudMessage(row.fraud_reason);
                setOpenDialog(true);
              }}
            >
              <RemoveRedEyeIcon fontSize="small" />
            </Button>
          </Tooltip>
        ) : (
          "-"
        ),
    },
  ];

  const chartSkeleton = (height = 350) => (
    <Box>
      <Skeleton variant="text" width="40%" height={32} />
      <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />
    </Box>
  );

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

          <main className="main-content mt-5" ref={dashboardRef}>
            <div className="container">
              <div className="page">
                  <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center', 
                  marginBottom: '1rem' 
                }}>
                  <div className="header-title-page" style={{ margin: 0 }}>GST Dashboard</div>
                  <Button
                    variant="contained"
                    color="primary"
                    size="small"
                    onClick={downloadDashboardPDF}
                    className="hideme"
                  >
                    Download PDF
                  </Button>
                </div>
                {/* Filters */}
                <div className="row align-items-center mb-4">
                  <div className="col-md-6 pb-3">
                    <FormControl fullWidth size="small">
                      <InputLabel>Select Tenure</InputLabel>
                      <Select value={tenure} label="Select Tenure" onChange={handleTenureChange}>
                        <MenuItem value="1m">Past 1 Month</MenuItem>
                        <MenuItem value="3m">Past 3 Months</MenuItem>
                        <MenuItem value="6m">Past 6 Months</MenuItem>
                        <MenuItem value="1y">Past 1 Year</MenuItem>
                        <MenuItem value="custom">Custom Date</MenuItem>
                      </Select>
                    </FormControl>
                  </div>

                  <div className="col-md-6 d-flex justify-content-md-end gap-2 mt-2 mt-md-0">
                    

                    {tenure === "custom" ? (
                      <LocalizationProvider dateAdapter={AdapterDayjs}>
                        <DatePicker
                          label="Start Date"
                          format="DD/MM/YYYY"
                          value={startDate}
                          onChange={(newValue) => {
                            if (!newValue) return;
                            if (!newValue.isValid()) return;

                            const year = newValue.year();
                            if (year < 1900 || year > 2100) return;

                            setStartDate(newValue);
                          }}
                          slotProps={{
                            textField: {
                              id: "outlined",
                              fullWidth: true,
                              size: "small",
                              inputProps: {
                                readOnly: true
                              },
                              sx: { minWidth: 160 },
                            }
                          }}
                        />
                        <DatePicker
                          label="End Date"
                          format="DD/MM/YYYY"
                          value={endDate}
                          onChange={(newValue) => {
                            if (!newValue) return;
                            if (!newValue.isValid()) return;

                            const year = newValue.year();
                            if (year < 1900 || year > 2100) return;

                            setEndDate(newValue);
                          }}
                          slotProps={{
                            textField: {
                              id: "outlined",
                              fullWidth: true,
                              size: "small",
                              inputProps: {
                                readOnly: true
                              }
                            }
                          }}
                        />
                      </LocalizationProvider>
                    ) : (
                      <div className="fw-bold small d-flex align-items-center gap-2">
                        <span>{startDate.format("DD-MM-YYYY")}</span>
                        <span>to</span>
                        <span>{endDate.format("DD-MM-YYYY")}</span>
                      </div>
                    )}
                  </div>
                </div>

                {dashboardError && (
                  <Alert severity="error" sx={{ mb: 3 }}>
                    {dashboardError}
                  </Alert>
                )}

                {!dashboardError && isLargeDashboardRange && (
                  <Alert severity="info" sx={{ mb: 3 }}>
                    Showing yearly aggregated data for large date ranges.
                  </Alert>
                )}

                {/* Summary Cards */}
                <div className="row mb-4">
                  {[
                      {
                        color: "#5096FF",
                        title: "Total Tax Payers",
                        value: num(summary.total_tax_payers),
                      },
                      {
                        color: "#47C99E",
                        title: "Total Sales Income",
                        value: formatCurrency(summary.total_sales_income),
                      },
                      {
                        color: "#F96992",
                        title: "Total GST Payable",
                        value: formatCurrency(summary.total_gst_payable),
                      },
                      {
                        color: "#FFA56D",
                        title: "Total GST Refundable",
                        value: formatCurrency(summary.total_gst_refundable),
                      },
                    ].map((w, i) => (
                    <div key={i} className="col-lg-3 col-md-6 mb-3">
                      <div className="card text-white h-100" style={{ background: w.color }}>
                        <div className="card-body">
                          {sectionLoading.summary ? (
                            <>
                              <Skeleton variant="text" width="70%" height={34} />
                              <Skeleton variant="text" width="50%" height={20} />
                            </>
                          ) : (
                            <>
                              <h4 className="mb-0 fw-bold">{w.value}</h4>
                              <small>{w.title}</small>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Charts */}
                <div className="row">
                  <div className="col-lg-12 col-md-12 mb-4">
                    <div className="card">
                      <div className="card-header">
                        <div className="d-flex justify-content-between align-items-center">
                          <span>Sales Comparison</span>
                          <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadSalesCsv}>
                            CSV
                          </Button>
                        </div>
                      </div>
                      <div className="card-body">
                        {sectionLoading.sales ? (
                          chartSkeleton(350)
                        ) : (
                          <div style={{ overflowX: "auto" }}>
                            <div style={{ minWidth: `${salesChart.categories.length * 60}px` }}>
                              <Chart
                                options={{
                                  ...salesOptions,

                                  chart: {
                                    ...salesOptions.chart,
                                    type: isLargeDashboardRange ? "bar" : "line",
                                  },

                                  plotOptions: isLargeDashboardRange
                                    ? {
                                        bar: {
                                          horizontal: false,
                                          columnWidth: "55%",
                                          borderRadius: 4,
                                        },
                                      }
                                    : {},

                                  stroke: isLargeDashboardRange
                                    ? { width: 0 }
                                    : { curve: "smooth" },

                                  dataLabels: {
                                    enabled: isLargeDashboardRange,
                                  },
                                }}
                                series={salesChart.series}
                                type={isLargeDashboardRange ? "bar" : "line"}
                                height={350}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="col-lg-12 col-md-12 mb-4">
                    <div className="card">
                      <div className="card-header">
                        <div className="d-flex justify-content-between align-items-center">
                          <span>GST Payable vs Refundable</span>
                          <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadPayableCsv}>
                            CSV
                          </Button>
                        </div>
                      </div>
                      <div className="card-body">
                        {sectionLoading.gst ? (
                          chartSkeleton(380)
                        ) : (
                        <div style={{ overflowX: "auto", overflowY: "visible" }}>
                          <div style={{ minWidth: `${gstChart.categories.length * 60}px` }}>
                            <Chart
                              options={{
                                chart: {
                                  type: "bar",
                                  toolbar: chartExportToolbar,
                                },

                                colors: ["#e74c3c", "#2ecc71"], // Payable red, Refundable green

                                plotOptions: {
                                  bar: {
                                    horizontal: false,
                                    columnWidth: "55%",
                                    borderRadius: 0, // square bars
                                    dataLabels: {
                                      position: "top", // labels above bars
                                    },
                                  },
                                },

                                dataLabels: {
                                  enabled: false, // prevent overlap
                                },

                                xaxis: {
                                  categories: gstChart.categories,
                                  labels: { rotate: -45 },
                                },

                                legend: {
                                  position: "top",
                                  horizontalAlign: "left",
                                },

                                 tooltip: {
                                    enabled: true,
                                    shared: true,
                                    intersect: false,
                                    y: {
                                      formatter: (val) => formatCurrency(val),
                                    },
                                  },

                                yaxis: {
                                  labels: {
                                    formatter: (val) => formatCurrency(val),
                                  },
                                },
                              }}
                              series={[
                                {
                                  name: "GST Payable",
                                  data: gstChart.series?.[0]?.data || [],
                                },
                                {
                                  name: "GST Refundable",
                                  data: gstChart.series?.[1]?.data || [],
                                },
                              ]}
                              type="bar"
                              height={380}
                            />
                          </div>
                        </div>
                        )}

                      </div>
                    </div>
                  </div>
                </div>

              </div>
              
                <div className="page">
                <div className="row mb-4">
                  <div className="col-lg-6 col-md-12 mb-4">
                    <div className="card">
                      <div className="card-header">
                        <div className="d-flex justify-content-between align-items-center">
                          <span>Segmentation Distribution</span>
                          <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadSegmentationCsv}>
                            CSV
                          </Button>
                        </div>
                      </div>
                      <div className="card-body">
                        {sectionLoading.segmentation ? (
                          chartSkeleton(350)
                        ) : (
                          <Chart
                            options={segmentationOptions}
                            series={[{ data: segmentation.series }]}
                            type="bar"
                            height={350}
                          />
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="col-lg-6 col-md-12 mb-4">
                    <div className="card">
                      <div className="card-header">
                        <div className="d-flex justify-content-between align-items-center">
                          <span>Risk Flagged vs Non-Risk</span>
                          <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadRiskCsv}>
                            CSV
                          </Button>
                        </div>
                      </div>
                      <div className="card-body">
                        {sectionLoading.risk ? (
                          chartSkeleton(350)
                        ) : (
                          <Chart options={riskOptions} series={riskChart.series} type="pie" height={350} />
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="row mb-4" ref={provinceSectionRef}>
                  <div className="col-12">
                    <div className="card">
                      <div className="card-header">
                        <div className="d-flex justify-content-between align-items-center">
                          <span className="fw-bold">Fraud TIN Distribution by Province</span>
                          <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadProvinceCsv}>
                            CSV
                          </Button>
                        </div>
                      </div>

                      <div className="card-body">
                        {!shouldLoadProvince ? (
                          <Box>
                            <Typography variant="body2" sx={{ mb: 2 }}>
                              Province distribution will load when you scroll near this section.
                            </Typography>
                            <Skeleton variant="rectangular" height={550} sx={{ borderRadius: 2 }} />
                          </Box>
                        ) : sectionLoading.province ? (
                          <Skeleton variant="rectangular" height={550} sx={{ borderRadius: 2 }} />
                        ) : (
                          <div style={{ height: "550px", width: "100%" }}>
                            <Suspense
                              fallback={
                                <Box
                                  sx={{
                                    height: 550,
                                    display: "flex",
                                    justifyContent: "center",
                                    alignItems: "center",
                                  }}
                                >
                                  <CircularProgress />
                                </Box>
                              }
                            >
                              <PNGMapGST
                                staticData={memoizedMapData}
                                onProvinceSelect={handleProvinceSelect}
                              />
                            </Suspense>

                          </div>
                        )}

                        {selectedProvinceData && (
                          <div className="alert alert-info mt-3">
                            <div className="fw-bold mb-1">
                              Province: {selectedProvinceData.province}
                            </div>
                            <div>
                              Fraud TIN Count:
                              <strong> {selectedProvinceData.fraud_count}</strong>
                            </div>
                            <div>
                              Risk Percentage:
                              <strong> {selectedProvinceData.risk_percentage}%</strong>
                            </div>
                          </div>
                        )}

                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>
        <Footer />
      </div>

      {/* Reusable Fraud Reason Popup */}
      <FraudReasonDialog
        open={openDialog}
        handleClose={() => setOpenDialog(false)}
        message={fraudMessage}
      />

    </div>

  );
}
