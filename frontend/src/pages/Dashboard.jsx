import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
import Chart from "react-apexcharts";
import DataTable from "react-data-table-component";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Skeleton,
  Typography,
} from "@mui/material";
import TableChartIcon from "@mui/icons-material/TableChart";
import dayjs from "dayjs";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import tableCustomStyles from "../components/common/tableStyles";
import EmptyState from "../components/common/EmptyState";
import TableSkeleton from "../components/common/TableSkeleton";
import ChartDataCard from "../components/common/ChartDataCard";
import API from "../api/api";
import "./css/Dashboard.css";

const PNGMapGST = lazy(() => import("../components/maps/PNGMapGST"));

const asArray = (value) => (Array.isArray(value) ? value : []);
const num = (value) => Number(value ?? 0);
const str = (value, fallback = "") => (value === null || value === undefined ? fallback : String(value));
const DASHBOARD_CACHE_TTL_MS = 5 * 60 * 1000;
const dashboardMemoryCache = new Map();
const inflightDashboardRequests = new Map();
const VIEW_KEYS = {
  sales: "sales",
  gst: "gst",
  segmentation: "segmentation",
  risk: "risk",
};

const getRangeDates = (rangeType, baseDate = dayjs()) => {
  switch (rangeType) {
    case "1m":
      return { start: baseDate.startOf("month"), end: baseDate.endOf("month") };
    case "3m":
      return {
        start: baseDate.subtract(2, "month").startOf("month"),
        end: baseDate.endOf("month"),
      };
    case "6m":
      return {
        start: baseDate.subtract(5, "month").startOf("month"),
        end: baseDate.endOf("month"),
      };
    case "1y":
      return {
        start: baseDate.subtract(11, "month").startOf("month"),
        end: baseDate.endOf("month"),
      };
    default:
      return null;
  }
};

const getParamsFromFilters = (tenure, startDate, endDate) => {
  const params = { range_type: tenure };

  if (tenure === "custom" && startDate && endDate) {
    params.start_date = startDate.format("YYYY-MM-DD");
    params.end_date = endDate.format("YYYY-MM-DD");
  }

  return params;
};

const hasCartesianChartData = (categories, series) =>
  Array.isArray(categories) &&
  categories.length > 0 &&
  Array.isArray(series) &&
  series.some((item) => Array.isArray(item?.data) && item.data.length > 0);

const hasLabeledSeriesData = (labels, series) =>
  Array.isArray(labels) &&
  labels.length > 0 &&
  Array.isArray(series) &&
  series.length > 0;

const buildSeriesTableRows = (categories = [], series = []) =>
  asArray(categories).map((category, rowIndex) => {
    const row = {
      id: `${str(category, "row")}-${rowIndex}`,
      category: str(category, "-"),
    };

    asArray(series).forEach((item, seriesIndex) => {
      row[`series_${seriesIndex}`] = Number(item?.data?.[rowIndex] ?? 0);
    });

    return row;
  });

const getSeriesTableColumns = (categoryLabel, series = [], formatValue) => [
  {
    name: categoryLabel,
    selector: (row) => row.category,
    sortable: true,
    wrap: true,
  },
  ...asArray(series).map((item, index) => ({
    name: str(item?.name, `Series ${index + 1}`),
    selector: (row) => row[`series_${index}`],
    sortable: true,
    right: true,
    format: (row) => formatValue(row[`series_${index}`]),
  })),
];

const formatCurrency = (value) => {
  if (value === null || value === undefined) {
    return "K 0.00";
  }

  return `K ${Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

const makeCacheKey = (url, params) => `${url}:${JSON.stringify(params || {})}`;

export default function Dashboard() {
  const initialRange = getRangeDates("1m");

  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [draftTenure, setDraftTenure] = useState("1m");
  const [draftStartDate, setDraftStartDate] = useState(initialRange.start);
  const [draftEndDate, setDraftEndDate] = useState(initialRange.end);
  const [appliedTenure, setAppliedTenure] = useState("1m");
  const [appliedStartDate, setAppliedStartDate] = useState(initialRange.start);
  const [appliedEndDate, setAppliedEndDate] = useState(initialRange.end);

  const [summary, setSummary] = useState({});
  const [salesChart, setSalesChart] = useState({ categories: [], series: [] });
  const [gstChart, setGstChart] = useState({ categories: [], series: [] });
  const [segmentation, setSegmentation] = useState({ labels: [], series: [] });
  const [riskChart, setRiskChart] = useState({ labels: [], series: [] });
  const [mapStaticData, setMapStaticData] = useState([]);
  const [selectedProvinceData, setSelectedProvinceData] = useState(null);
  const [dashboardError, setDashboardError] = useState("");
  const [shouldLoadProvince, setShouldLoadProvince] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sectionLoading, setSectionLoading] = useState({
    summary: true,
    sales: true,
    gst: true,
    segmentation: true,
    risk: true,
    province: false,
  });
  const [chartView, setChartView] = useState({
    [VIEW_KEYS.sales]: false,
    [VIEW_KEYS.gst]: false,
    [VIEW_KEYS.segmentation]: false,
    [VIEW_KEYS.risk]: false,
  });

  const dashboardRef = useRef();
  const activeControllersRef = useRef([]);
  const provinceSectionRef = useRef(null);

  const memoizedMapData = useMemo(() => mapStaticData, [mapStaticData]);
  const selectedRangeMonths = appliedStartDate && appliedEndDate
    ? appliedEndDate.diff(appliedStartDate, "month") + 1
    : 0;
  const isLargeDashboardRange = selectedRangeMonths > 24;
  const appliedFiltersKey = `${appliedTenure}|${appliedStartDate?.valueOf() ?? ""}|${appliedEndDate?.valueOf() ?? ""}`;
  const draftFiltersKey = `${draftTenure}|${draftStartDate?.valueOf() ?? ""}|${draftEndDate?.valueOf() ?? ""}`;
  const isFilterDirty = draftFiltersKey !== appliedFiltersKey;
  const canSubmitCustomRange =
    draftTenure !== "custom" ||
    (draftStartDate && draftEndDate && !draftEndDate.isBefore(draftStartDate, "day"));

  const handleProvinceSelect = useCallback((province, data) => {
    setSelectedProvinceData({
      province,
      fraud_count: data?.fraud_count ?? 0,
      risk_percentage: data?.risk_percentage ?? 0,
    });
  }, []);

  const salesInteractionToolbar = useMemo(() => ({
    show: true,
    tools: {
      download: false,
      selection: false,
      zoom: true,
      zoomin: true,
      zoomout: true,
      pan: false,
      reset: true,
    },
  }), []);

  const getAppliedParams = useCallback(
    () => getParamsFromFilters(appliedTenure, appliedStartDate, appliedEndDate),
    [appliedTenure, appliedStartDate, appliedEndDate]
  );

  const abortActiveRequests = useCallback(() => {
    activeControllersRef.current.forEach((controller) => {
      try {
        controller.abort();
      } catch {
        // no-op
      }
    });
    activeControllersRef.current = [];
  }, []);

  const getRequestErrorMessage = useCallback((error, timeoutMs = 60000) => {
    if (error?.code === "ERR_CANCELED" || error?.code === "ECONNABORTED") {
      return `GST dashboard request timed out after ${Math.round(timeoutMs / 1000)} seconds. Please try again.`;
    }

    const backendMessage = error?.response?.data?.error || error?.response?.data?.message;
    if (backendMessage) {
      return backendMessage;
    }

    return "Unable to load GST dashboard right now. Please try again.";
  }, []);

  const getWithTimeout = useCallback(async (url, params, options = {}) => {
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
  }, []);

  const fetchDashboardData = useCallback(async () => {
    try {
      abortActiveRequests();
      setLoading(true);
      setDashboardError("");
      setShouldLoadProvince(false);
      setSelectedProvinceData(null);
      setMapStaticData([]);
      setSectionLoading({
        summary: true,
        sales: true,
        gst: true,
        segmentation: true,
        risk: true,
        province: false,
      });

      const params = getAppliedParams();
      const dashboardTimeoutMs = isLargeDashboardRange ? 90000 : 60000;

      const summaryRes = await getWithTimeout("/dashboard/data", params, {
        useMemoryCache: false,
        timeoutMs: dashboardTimeoutMs,
      });

      const summaryData = summaryRes?.data || {};
      setSummary({
        total_tax_payers: Number(summaryData.total_tax_payers ?? summaryData.total_tax_payers_count ?? 0),
        total_sales_income: Number(summaryData.total_sales_income ?? summaryData.total_sales ?? summaryData.sales_income ?? 0),
        total_gst_payable: Number(summaryData.total_gst_payable ?? summaryData.gst_payable ?? summaryData.gstPayable ?? 0),
        total_gst_refundable: Number(summaryData.total_gst_refundable ?? summaryData.gst_refundable ?? summaryData.gstRefundable ?? 0),
      });
      setSectionLoading((prev) => ({ ...prev, summary: false }));

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
    } catch (error) {
      console.error("Error fetching dashboard data:", error);
      setDashboardError(
        getRequestErrorMessage(error, isLargeDashboardRange ? 90000 : 60000)
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
      setLoading(false);
    }
  }, [
    abortActiveRequests,
    getAppliedParams,
    getRequestErrorMessage,
    getWithTimeout,
    isLargeDashboardRange,
  ]);

  const fetchProvinceData = useCallback(async () => {
    try {
      setSectionLoading((prev) => ({ ...prev, province: true }));
      const params = getAppliedParams();
      const dashboardTimeoutMs = isLargeDashboardRange ? 90000 : 60000;
      const fraudMapRes = await getWithTimeout(
        "/dashboard/fraud-province-distribution",
        params,
        { useMemoryCache: false, timeoutMs: dashboardTimeoutMs }
      );

      const provinceDistribution = fraudMapRes?.data?.province_distribution || {};
      const heatmapArray = Object.entries(provinceDistribution).map(([province, record]) => ({
        province,
        fraud_count: Number(record?.fraud_tins ?? 0),
        risk_percentage: Number(record?.risk_percentage ?? 0),
      }));

      setMapStaticData(heatmapArray);
    } catch (error) {
      console.error("Error fetching province distribution:", error);
      setDashboardError(
        getRequestErrorMessage(error, isLargeDashboardRange ? 90000 : 60000)
      );
    } finally {
      setSectionLoading((prev) => ({ ...prev, province: false }));
    }
  }, [getAppliedParams, getRequestErrorMessage, getWithTimeout, isLargeDashboardRange]);

  useEffect(() => {
    fetchDashboardData();
  }, [fetchDashboardData]);

  useEffect(() => () => {
    abortActiveRequests();
  }, [abortActiveRequests]);

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
    if (!shouldLoadProvince) {
      return undefined;
    }

    const timeout = setTimeout(() => {
      fetchProvinceData();
    }, 50);

    return () => clearTimeout(timeout);
  }, [shouldLoadProvince, fetchProvinceData]);

  const salesOptions = useMemo(() => ({
    chart: {
      type: "line",
      toolbar: salesInteractionToolbar,
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
        formatter: (value) => formatCurrency(value),
      },
    },
    tooltip: {
      y: {
        formatter: (value) => formatCurrency(value),
      },
    },
  }), [salesChart.categories, salesInteractionToolbar]);

  const segmentationOptions = useMemo(() => ({
    chart: { type: "bar", toolbar: { show: false } },
    plotOptions: {
      bar: {
        borderRadius: 6,
        dataLabels: { position: "top" },
      },
    },
    dataLabels: {
      enabled: true,
      formatter: (value) => (value ? value.toLocaleString() : ""),
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
  }), [segmentation.labels]);

  const riskOptions = useMemo(() => ({
    chart: { type: "pie", toolbar: { show: false } },
    labels: riskChart.labels,
    legend: { position: "bottom" },
  }), [riskChart.labels]);

  const chartSkeleton = useCallback((height = 350) => (
    <Box>
      <Skeleton variant="text" width="40%" height={32} />
      <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />
    </Box>
  ), []);

  const handleTenureChange = (event) => {
    const nextTenure = event.target.value;
    setDraftTenure(nextTenure);

    const nextRange = getRangeDates(nextTenure);
    if (nextRange) {
      setDraftStartDate(nextRange.start);
      setDraftEndDate(nextRange.end);
    }
  };

  const handleSubmitFilters = () => {
    if (loading || !canSubmitCustomRange || !isFilterDirty) {
      return;
    }

    setAppliedTenure(draftTenure);
    setAppliedStartDate(draftStartDate);
    setAppliedEndDate(draftEndDate);
  };

  const downloadDashboardPDF = async () => {
    const input = dashboardRef.current;
    if (!input) {
      return;
    }

    const pdf = new jsPDF("p", "mm", "a4");
    const sections = input.querySelectorAll(".page");
    const now = dayjs().format("DD MMM YYYY, HH:mm");
    let isFirstPage = true;

    const hiddenElements = input.querySelectorAll(".hideme");
    hiddenElements.forEach((element) => {
      element.dataset.originalDisplay = element.style.display;
      element.style.display = "none";
    });

    for (const section of sections) {
      const canvas = await html2canvas(section, {
        scale: 2,
        useCORS: true,
        scrollY: -window.scrollY,
      });

      const imageData = canvas.toDataURL("image/png");
      const pageWidth = pdf.internal.pageSize.getWidth();
      const margin = 10;
      const imageWidth = pageWidth - margin * 2;
      const imageHeight = (canvas.height * imageWidth) / canvas.width;

      if (!isFirstPage) {
        pdf.addPage();
      }

      pdf.setFontSize(12);
      pdf.text("GST Dashboard Report", 10, 10);
      pdf.setFontSize(8);
      pdf.text(`Generated: ${now}`, 10, 15);
      pdf.addImage(imageData, "PNG", margin, 20, imageWidth, imageHeight);

      isFirstPage = false;
    }

    hiddenElements.forEach((element) => {
      element.style.display = element.dataset.originalDisplay || "";
    });

    pdf.save(`GST-Dashboard_${dayjs().format("YYYY-MM-DD_HH-mm")}.pdf`);
  };

  const downloadCsv = async (endpoint, filename, columns) => {
    try {
      const params = getAppliedParams();
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
    } catch (error) {
      console.error(`Failed to download ${filename}`, error);
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

  const toggleChartView = (key) => {
    setChartView((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const hasSalesData = hasCartesianChartData(salesChart.categories, salesChart.series);
  const hasGstData = hasCartesianChartData(gstChart.categories, gstChart.series);
  const hasSegmentationData = hasLabeledSeriesData(segmentation.labels, segmentation.series);
  const hasRiskData = hasLabeledSeriesData(riskChart.labels, riskChart.series);

  const salesTableColumns = useMemo(
    () => getSeriesTableColumns("Month", salesChart.series, formatCurrency),
    [salesChart.series]
  );
  const salesTableData = useMemo(
    () => buildSeriesTableRows(salesChart.categories, salesChart.series),
    [salesChart.categories, salesChart.series]
  );

  const gstSeries = useMemo(
    () =>
      asArray(gstChart.series).map((item, index) => ({
        ...item,
        name: str(item?.name, index === 0 ? "GST Payable" : "GST Refundable"),
        data: asArray(item?.data),
      })),
    [gstChart.series]
  );
  const gstTableColumns = useMemo(
    () => getSeriesTableColumns("Month", gstSeries, formatCurrency),
    [gstSeries]
  );
  const gstTableData = useMemo(
    () => buildSeriesTableRows(gstChart.categories, gstSeries),
    [gstChart.categories, gstSeries]
  );

  const segmentationTableColumns = useMemo(() => [
    { name: "Segment", selector: (row) => row.segment, sortable: true, wrap: true },
    {
      name: "Count",
      selector: (row) => row.count,
      sortable: true,
      right: true,
      format: (row) => row.count.toLocaleString(),
    },
  ], []);
  const segmentationTableData = useMemo(
    () =>
      asArray(segmentation.labels).map((label, index) => ({
        id: `${str(label, "segment")}-${index}`,
        segment: str(label, "Unknown"),
        count: Number(segmentation.series?.[index] ?? 0),
      })),
    [segmentation.labels, segmentation.series]
  );

  const riskTotal = useMemo(
    () => asArray(riskChart.series).reduce((sum, value) => sum + Number(value ?? 0), 0),
    [riskChart.series]
  );
  const riskTableColumns = useMemo(() => [
    { name: "Risk Status", selector: (row) => row.status, sortable: true, wrap: true },
    {
      name: "Count",
      selector: (row) => row.count,
      sortable: true,
      right: true,
      format: (row) => row.count.toLocaleString(),
    },
    {
      name: "Percentage",
      selector: (row) => row.percentageValue,
      sortable: true,
      right: true,
      format: (row) => row.percentage,
    },
  ], []);
  const riskTableData = useMemo(
    () =>
      asArray(riskChart.labels).map((label, index) => {
        const count = Number(riskChart.series?.[index] ?? 0);
        const percentageValue = riskTotal > 0 ? (count / riskTotal) * 100 : 0;

        return {
          id: `${str(label, "risk")}-${index}`,
          status: str(label, "Unknown"),
          count,
          percentageValue,
          percentage: `${percentageValue.toFixed(2)}%`,
        };
      }),
    [riskChart.labels, riskChart.series, riskTotal]
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
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: "1rem",
                  }}
                >
                  <div className="header-title-page" style={{ margin: 0 }}>
                    GST Dashboard
                  </div>
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

                <div className="row align-items-center mb-4">
                  <div className="col-md-6 pb-3">
                    <FormControl fullWidth size="small">
                      <InputLabel>Select Tenure</InputLabel>
                      <Select value={draftTenure} label="Select Tenure" onChange={handleTenureChange}>
                        <MenuItem value="1m">Past 1 Month</MenuItem>
                        <MenuItem value="3m">Past 3 Months</MenuItem>
                        <MenuItem value="6m">Past 6 Months</MenuItem>
                        <MenuItem value="1y">Past 1 Year</MenuItem>
                        <MenuItem value="custom">Custom Date</MenuItem>
                      </Select>
                    </FormControl>
                  </div>

                  <div className="col-md-6 d-flex justify-content-md-end gap-2 mt-2 mt-md-0">
                    {draftTenure === "custom" ? (
                      <LocalizationProvider dateAdapter={AdapterDayjs}>
                        <DatePicker
                          label="Start Date"
                          format="DD/MM/YYYY"
                          value={draftStartDate}
                          onChange={(newValue) => {
                            if (!newValue || !newValue.isValid()) {
                              return;
                            }

                            const year = newValue.year();
                            if (year < 1900 || year > 2100) {
                              return;
                            }

                            setDraftStartDate(newValue);
                          }}
                          slotProps={{
                            textField: {
                              id: "outlined",
                              fullWidth: true,
                              size: "small",
                              inputProps: { readOnly: true },
                              sx: { minWidth: 160 },
                            },
                          }}
                        />
                        <DatePicker
                          label="End Date"
                          format="DD/MM/YYYY"
                          value={draftEndDate}
                          onChange={(newValue) => {
                            if (!newValue || !newValue.isValid()) {
                              return;
                            }

                            const year = newValue.year();
                            if (year < 1900 || year > 2100) {
                              return;
                            }

                            setDraftEndDate(newValue);
                          }}
                          slotProps={{
                            textField: {
                              id: "outlined",
                              fullWidth: true,
                              size: "small",
                              inputProps: { readOnly: true },
                              sx: { minWidth: 160 },
                            },
                          }}
                        />
                      </LocalizationProvider>
                    ) : (
                      <div className="fw-bold small d-flex align-items-center gap-2">
                        <span>{draftStartDate.format("DD-MM-YYYY")}</span>
                        <span>to</span>
                        <span>{draftEndDate.format("DD-MM-YYYY")}</span>
                      </div>
                    )}

                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleSubmitFilters}
                      disabled={loading || !canSubmitCustomRange || !isFilterDirty}
                      className="hideme"
                    >
                      Submit
                    </Button>
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
                  ].map((item, index) => (
                    <div key={index} className="col-lg-3 col-md-6 mb-3">
                      <div className="card text-white h-100" style={{ background: item.color }}>
                        <div className="card-body">
                          {sectionLoading.summary ? (
                            <>
                              <Skeleton variant="text" width="70%" height={34} />
                              <Skeleton variant="text" width="50%" height={20} />
                            </>
                          ) : (
                            <>
                              <h4 className="mb-0 fw-bold">{item.value}</h4>
                              <small>{item.title}</small>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="row">
                  <div className="col-lg-12 col-md-12 mb-4">
                    <ChartDataCard
                      title="Sales Comparison"
                      isChartView={chartView[VIEW_KEYS.sales]}
                      onToggleView={() => toggleChartView(VIEW_KEYS.sales)}
                      onDownloadCsv={downloadSalesCsv}
                      loading={sectionLoading.sales}
                      hasData={hasSalesData}
                      chartSkeleton={chartSkeleton(350)}
                      tableSkeleton={<TableSkeleton columnCount={Math.max(salesChart.series.length + 1, 5)} />}
                      emptyMessage="No records available for the selected criteria"
                      chartContent={
                        <div style={{ overflowX: "auto" }}>
                          <div style={{ minWidth: `${Math.max(salesChart.categories.length, 6) * 60}px` }}>
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
                                stroke: isLargeDashboardRange ? { width: 0 } : { curve: "smooth" },
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
                      }
                      tableContent={
                        <DataTable
                          columns={salesTableColumns}
                          data={salesTableData}
                          customStyles={tableCustomStyles}
                          dense
                          pagination
                          highlightOnHover
                          responsive
                          persistTableHead
                        />
                      }
                    />
                  </div>

                  <div className="col-lg-12 col-md-12 mb-4">
                    <ChartDataCard
                      title="GST Payable vs Refundable"
                      isChartView={chartView[VIEW_KEYS.gst]}
                      onToggleView={() => toggleChartView(VIEW_KEYS.gst)}
                      onDownloadCsv={downloadPayableCsv}
                      loading={sectionLoading.gst}
                      hasData={hasGstData}
                      chartSkeleton={chartSkeleton(380)}
                      tableSkeleton={<TableSkeleton columnCount={Math.max(gstSeries.length + 1, 3)} />}
                      emptyMessage="No records available for the selected criteria"
                      chartContent={
                        <div style={{ overflowX: "auto", overflowY: "visible" }}>
                          <div style={{ minWidth: `${Math.max(gstChart.categories.length, 6) * 60}px` }}>
                            <Chart
                              options={{
                                chart: {
                                  type: "bar",
                                  toolbar: { show: false },
                                },
                                colors: ["#e74c3c", "#2ecc71"],
                                plotOptions: {
                                  bar: {
                                    horizontal: false,
                                    columnWidth: "55%",
                                    borderRadius: 0,
                                    dataLabels: {
                                      position: "top",
                                    },
                                  },
                                },
                                dataLabels: {
                                  enabled: false,
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
                                    formatter: (value) => formatCurrency(value),
                                  },
                                },
                                yaxis: {
                                  labels: {
                                    formatter: (value) => formatCurrency(value),
                                  },
                                },
                              }}
                              series={gstSeries}
                              type="bar"
                              height={380}
                            />
                          </div>
                        </div>
                      }
                      tableContent={
                        <DataTable
                          columns={gstTableColumns}
                          data={gstTableData}
                          customStyles={tableCustomStyles}
                          dense
                          pagination
                          highlightOnHover
                          responsive
                          persistTableHead
                        />
                      }
                    />
                  </div>
                </div>
              </div>

              <div className="page">
                <div className="row mb-4">
                  <div className="col-lg-6 col-md-12 mb-4">
                    <ChartDataCard
                      title="Segmentation Distribution"
                      isChartView={chartView[VIEW_KEYS.segmentation]}
                      onToggleView={() => toggleChartView(VIEW_KEYS.segmentation)}
                      onDownloadCsv={downloadSegmentationCsv}
                      loading={sectionLoading.segmentation}
                      hasData={hasSegmentationData}
                      chartSkeleton={chartSkeleton(350)}
                      tableSkeleton={<TableSkeleton columnCount={2} />}
                      emptyMessage="No records available for the selected criteria"
                      chartContent={
                        <Chart
                          options={segmentationOptions}
                          series={[{ data: segmentation.series }]}
                          type="bar"
                          height={350}
                        />
                      }
                      tableContent={
                        <DataTable
                          columns={segmentationTableColumns}
                          data={segmentationTableData}
                          customStyles={tableCustomStyles}
                          dense
                          pagination
                          highlightOnHover
                          responsive
                          persistTableHead
                        />
                      }
                    />
                  </div>

                  <div className="col-lg-6 col-md-12 mb-4">
                    <ChartDataCard
                      title="Risk Flagged vs Non-Risk"
                      isChartView={chartView[VIEW_KEYS.risk]}
                      onToggleView={() => toggleChartView(VIEW_KEYS.risk)}
                      onDownloadCsv={downloadRiskCsv}
                      loading={sectionLoading.risk}
                      hasData={hasRiskData}
                      chartSkeleton={chartSkeleton(350)}
                      tableSkeleton={<TableSkeleton columnCount={3} />}
                      emptyMessage="No records available for the selected criteria"
                      chartContent={
                        <Chart options={riskOptions} series={riskChart.series} type="pie" height={350} />
                      }
                      tableContent={
                        <DataTable
                          columns={riskTableColumns}
                          data={riskTableData}
                          customStyles={tableCustomStyles}
                          dense
                          pagination
                          highlightOnHover
                          responsive
                          persistTableHead
                        />
                      }
                    />
                  </div>
                </div>

                <div className="row mb-4" ref={provinceSectionRef}>
                  <div className="col-12">
                    <div className="card">
                      <div className="card-header">
                        <div className="d-flex justify-content-between align-items-center">
                          <span className="fw-bold">Fraud TIN Distribution by Province</span>
                          <Button
                            size="small"
                            variant="outlined"
                            color="primary"
                            startIcon={<TableChartIcon />}
                            onClick={downloadProvinceCsv}
                            className="hideme"
                          >
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
                        ) : memoizedMapData.length === 0 ? (
                          <EmptyState message="No records available for the selected criteria" />
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
    </div>
  );
}
