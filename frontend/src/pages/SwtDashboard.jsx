// SwtDashboard.jsx
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
  TextField,
  Paper,
  Button,
  CircularProgress,
  Typography,
  Alert,
  Skeleton,
  Box
} from "@mui/material";
import dayjs from "dayjs";
import "./css/Dashboard.css";
import tableCustomStyles from "../components/common/tableStyles";
import EmptyState from "../components/common/EmptyState";
import TableSkeleton from "../components/common/TableSkeleton";
import ChartDataCard from "../components/common/ChartDataCard";
import DataTableExport from "../components/common/DataTableExport";
import API from "../api/api";
import TableChartIcon from "@mui/icons-material/TableChart";    // CSV icon
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

const asArray = (v) => (Array.isArray(v) ? v : []);
const num = (v) => Number(v ?? 0);
const str = (v, fallback = "-") => (v === null || v === undefined || v === "" ? fallback : String(v));
const DASHBOARD_CACHE_TTL_MS = 5 * 60 * 1000;
const dashboardMemoryCache = new Map();
const inflightDashboardRequests = new Map();
const VIEW_KEYS = { salary: "salary", fraud: "fraud", segmentation: "segmentation" };
const PNGMapSWT = lazy(() => import("../components/maps/PNGMapSWT"));

export default function SwtDashboard() {
  const [collapsed, setCollapsed] = useState(true);               // Sidebar collapsed by default
  const [openMenu, setOpenMenu] = useState(null);

  const [tenure, setTenure] = useState("1m");
  const [startDate, setStartDate] = useState(dayjs().startOf("month"));
  const [endDate, setEndDate] = useState(dayjs().endOf("month"));
  const [appliedFilters, setAppliedFilters] = useState(() => ({
    tenure: "1m",
    startDate: dayjs().startOf("month"),
    endDate: dayjs().endOf("month"),
  }));
  const [chartView, setChartView] = useState({
    [VIEW_KEYS.salary]: false,
    [VIEW_KEYS.fraud]: false,
    [VIEW_KEYS.segmentation]: false,
  });

  const [summary, setSummary] = useState({});
  const [swtSalaryChart, setSwtSalaryChart] = useState({
    categories: [],
    series: [],
    chartData: [],
    availableTins: [],
    selectedTin: "",
  });
  const [fraudChart, setFraudChart] = useState({ categories: [], series: [] });
  const [segmentation, setSegmentation] = useState({ labels: [], series: [] });
  const [latestRecords, setLatestRecords] = useState([]);
  const [recordsPage, setRecordsPage] = useState(1);
  const [recordsPerPage, setRecordsPerPage] = useState(10);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [mapStaticData, setMapStaticData] = useState([]);
  const [selectedProvinceData, setSelectedProvinceData] = useState(null);
  const [searchText, setSearchText] = useState("");

  const [provinceTinInfo, setProvinceTinInfo] = useState({});
  const [tinModalOpen, setTinModalOpen] = useState(false);
  const [selectedTinList, setSelectedTinList] = useState([]);
  const [dashboardError, setDashboardError] = useState("");
  const [shouldLoadProvince, setShouldLoadProvince] = useState(false);
  
  // Match Dashboard.jsx loading structure
  const [sectionLoading, setSectionLoading] = useState({
    summary: true,
    sales: true,
    gst: true,
    segmentation: true,
    risk: true,
    province: false,
  });

  const dashboardSWTRef = useRef();
  const activeControllersRef = useRef([]);
  const provinceSectionRef = useRef(null);
  const dashboardRequestIdRef = useRef(0);
  const provinceRequestIdRef = useRef(0);
  const salaryRequestIdRef = useRef(0);

  const downloadDashboardSWTPDF = async () => {
      const input = dashboardSWTRef.current;
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
        pdf.text("SWT Dashboard Report", 10, 10);
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
      pdf.save(`SWT-Dashboard_${fileTime}.pdf`);
    };
  


  const normalize = useCallback((s) =>
    (s || "").trim().toLowerCase().replace(/[^a-z]/g, ""), []);

  const formatLargeNumber = useCallback((value) => {
    const numericValue = Number(value ?? 0);
    if (Math.abs(numericValue) >= 1000000000) {
      return `${(numericValue / 1000000000).toFixed(1)}B`;
    }
    if (Math.abs(numericValue) >= 1000000) {
      return `${(numericValue / 1000000).toFixed(1)}M`;
    }
    if (Math.abs(numericValue) >= 1000) {
      return `${(numericValue / 1000).toFixed(1)}K`;
    }
    return numericValue.toLocaleString();
  }, []);

  const formatCurrency = useCallback((value) => `K ${Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, []);

  const getParams = useCallback(() => {
    const params = { range_type: appliedFilters.tenure };
    if (appliedFilters.tenure === "custom" && appliedFilters.startDate && appliedFilters.endDate) {
      params.start_date = appliedFilters.startDate.format("YYYY-MM-DD");
      params.end_date = appliedFilters.endDate.format("YYYY-MM-DD");
    }
    return params;
  }, [appliedFilters]);

  const handleTenureChange = useCallback((e) => {
    const val = e.target.value;
    setTenure(val);

    const today = dayjs();
    let start = today.startOf("month");
    let end = today.endOf("month");

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
      default:
        return;
    }

    setStartDate(start);
    setEndDate(end);
  }, []);

  const canSubmit = tenure !== "custom" || !endDate.isBefore(startDate, "day");
  const isDashboardSubmitting =
    sectionLoading.summary ||
    sectionLoading.sales ||
    sectionLoading.segmentation ||
    sectionLoading.risk;
  const handleSubmitFilters = () => {
    if (!canSubmit || isDashboardSubmitting) return;
    setRecordsPage(1);
    setAppliedFilters({ tenure, startDate, endDate });
  };
  const toggleChartView = (key) => {
    setChartView((current) => ({ ...current, [key]: !current[key] }));
  };

  const handleCsvDownload = async (endpoint, fileName, columns) => {
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
      link.setAttribute("download", fileName);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(`Failed to download ${fileName}`, err);
    }
  };

  const downloadSalaryVsSwtCsv = () =>
    handleCsvDownload("/swt/download-csv/salary-vs-swt", "salary-vs-swt.csv", [
      "tin",
      "taxpayer_name",
      "month",
      "swt_deducted",
      "salary_wages_paid",
    ]);

  const downloadFraudMonthlyCsv = () =>
    handleCsvDownload("/swt/download-csv/fraud-monthly", "fraud-monthly.csv", [
      "tin",
      "taxpayer_name",
      "month",
      "fraud_cases",
    ]);

  const downloadSegmentationCsv = () =>
    handleCsvDownload("/swt/download-csv/segmentation", "segmentation.csv", [
      "tin",
      "taxpayer_name",
      "segmentation",
      "total",
    ]);

  const downloadProvinceCsv = () =>
    handleCsvDownload("/swt/download-csv/province", "province.csv", [
      "tin",
      "taxpayer_name",
      "province",
      "risk_percentage",
    ]);

  const abortActiveRequests = useCallback((scope) => {
    const remaining = [];

    activeControllersRef.current.forEach((entry) => {
      if (!scope || entry.scope === scope) {
        try {
          entry.controller.abort();
        } catch {
          // no-op
        }

        const inflightEntry = inflightDashboardRequests.get(entry.key);
        if (inflightEntry?.controller === entry.controller) {
          inflightDashboardRequests.delete(entry.key);
        }
      } else {
        remaining.push(entry);
      }
    });

    activeControllersRef.current = remaining;
  }, []);

  const getRequestErrorMessage = useCallback((error, timeoutMs = 60000) => {
    if (error?.code === "ERR_CANCELED" || error?.name === "CanceledError") {
      return "";
    }

    if (error?.code === "ECONNABORTED") {
      return `SWT dashboard request timed out after ${Math.round(timeoutMs / 1000)} seconds. Please try again.`;
    }

    return (
      error?.response?.data?.error ||
      error?.response?.data?.message ||
      "Unable to load SWT dashboard right now. Please try again."
    );
  }, []);

  const makeCacheKey = useCallback((url, params) => `${url}:${JSON.stringify(params || {})}`, []);

  const getWithTimeout = useCallback(async (url, params, options = {}) => {
    const {
      useMemoryCache = false,
      ttlMs = DASHBOARD_CACHE_TTL_MS,
      timeoutMs = 60000,
      scope = "dashboard",
    } = options;
    const cacheKey = makeCacheKey(url, params);

    if (useMemoryCache) {
      const cached = dashboardMemoryCache.get(cacheKey);
      if (cached && cached.expiresAt > Date.now()) {
        return cached.value;
      }
    }

    const inflightEntry = inflightDashboardRequests.get(cacheKey);
    if (inflightEntry) {
      if (inflightEntry.controller.signal.aborted) {
        inflightDashboardRequests.delete(cacheKey);
      } else {
        return inflightEntry.promise;
      }
    }

    const controller = new AbortController();
    activeControllersRef.current.push({ controller, key: cacheKey, scope });

    const requestPromise = API.get(url, {
      params,
      signal: controller.signal,
      timeout: timeoutMs,
    }).then((response) => {
      if (useMemoryCache) {
        dashboardMemoryCache.set(cacheKey, {
          value: response,
          expiresAt: Date.now() + ttlMs,
        });
      }
      return response;
    }).finally(() => {
      const currentInflightEntry = inflightDashboardRequests.get(cacheKey);
      if (currentInflightEntry?.controller === controller) {
        inflightDashboardRequests.delete(cacheKey);
      }
      activeControllersRef.current = activeControllersRef.current.filter(
        (item) => item.controller !== controller
      );
    });

    inflightDashboardRequests.set(cacheKey, {
      promise: requestPromise,
      controller,
    });
    return requestPromise;
  }, [makeCacheKey]);

  const fetchDashboardData = useCallback(async () => {
    const requestId = dashboardRequestIdRef.current + 1;
    dashboardRequestIdRef.current = requestId;

    abortActiveRequests("dashboard");
    setDashboardError("");
    setShouldLoadProvince(false);
    setMapStaticData([]);
    setProvinceTinInfo({});
    setSelectedProvinceData(null);
    setSelectedTinList([]);
    setTinModalOpen(false);
    
    // Match Dashboard.jsx loading structure
    setSectionLoading({
      summary: true,
      sales: true,
      gst: true,
      segmentation: true,
      risk: true,
      province: false,
    });

    const params = getParams();

    const handleSectionError = (err) => {
      const message = getRequestErrorMessage(err);
      if (message) {
        setDashboardError(message);
      }
    };

    await Promise.all([
      getWithTimeout("/swt/dashboard/data", params, {
        useMemoryCache: true,
        scope: "dashboard",
      }).then((summaryRes) => {
        if (requestId !== dashboardRequestIdRef.current) return;
        setSummary(summaryRes.data || {});
      }).catch(handleSectionError).finally(() => {
        if (requestId === dashboardRequestIdRef.current) {
          setSectionLoading((prev) => ({
            ...prev,
            summary: false,
          }));
        }
      }),
      getWithTimeout("/swt/dashboard/swt-vs-salary", params, {
        useMemoryCache: true,
        scope: "dashboard",
      }).then((salaryRes) => {
        if (requestId !== dashboardRequestIdRef.current) return;
        setSwtSalaryChart({
          categories: asArray(salaryRes.data?.categories),
          series: asArray(salaryRes.data?.series),
          chartData: asArray(salaryRes.data?.chart_data),
          availableTins: asArray(salaryRes.data?.available_tins),
          selectedTin: str(salaryRes.data?.selected_tin, ""),
        });
      }).catch(handleSectionError).finally(() => {
        if (requestId === dashboardRequestIdRef.current) {
          setSectionLoading((prev) => ({
            ...prev,
            sales: false,
          }));
        }
      }),
      getWithTimeout("/swt/dashboard/segmentation-distribution", params, {
        useMemoryCache: true,
        scope: "dashboard",
      }).then((segmentationRes) => {
        if (requestId !== dashboardRequestIdRef.current) return;
        setSegmentation({
          labels: asArray(segmentationRes.data?.labels),
          series: asArray(segmentationRes.data?.series),
        });
      }).catch(handleSectionError).finally(() => {
        if (requestId === dashboardRequestIdRef.current) {
          setSectionLoading((prev) => ({
            ...prev,
            segmentation: false,
          }));
        }
      }),
      getWithTimeout("/swt/dashboard/fraud-monthly", params, {
        useMemoryCache: true,
        scope: "dashboard",
      }).then((fraudRes) => {
        if (requestId !== dashboardRequestIdRef.current) return;
        setFraudChart({
          categories: asArray(fraudRes.data?.categories),
          series: asArray(fraudRes.data?.series),
        });
      }).catch(handleSectionError).finally(() => {
        if (requestId === dashboardRequestIdRef.current) {
          setSectionLoading((prev) => ({
            ...prev,
            risk: false,
          }));
        }
      }),
    ]);

    if (requestId === dashboardRequestIdRef.current) {
      // All sections loaded
    }
  }, [abortActiveRequests, getParams, getRequestErrorMessage, getWithTimeout]);

  const fetchLatestRecords = useCallback(async (page = recordsPage, pageSize = recordsPerPage) => {
    setRecordsLoading(true);
    try {
      const response = await getWithTimeout("/swt/dashboard/latest-records", {
        ...getParams(), limit: pageSize, offset: (page - 1) * pageSize,
      }, { useMemoryCache: true, scope: "records" });
      setLatestRecords(asArray(response.data?.records));
      setRecordsTotal(Number(response.data?.pagination?.total ?? 0));
    } catch (err) {
      const message = getRequestErrorMessage(err);
      if (message) setDashboardError(message);
    } finally {
      setRecordsLoading(false);
    }
  }, [getParams, getRequestErrorMessage, getWithTimeout, recordsPage, recordsPerPage]);

  const fetchProvinceData = useCallback(async () => {
    const requestId = provinceRequestIdRef.current + 1;
    provinceRequestIdRef.current = requestId;

    try {
      abortActiveRequests("province");
      setSectionLoading((prev) => ({ ...prev, province: true }));
      const params = getParams();
      const fraudProvinceRes = await getWithTimeout(
        "/swt/dashboard/fraud-province-distribution-swt",
        params,
        { useMemoryCache: true, scope: "province" }
      );

      if (requestId !== provinceRequestIdRef.current) {
        return;
      }

      const provObj = fraudProvinceRes?.data?.province_distribution || {};
      const heatmapArray = [];
      const provinceTinDetails = {};

      Object.entries(provObj).forEach(([prov, data]) => {
        const normProv = normalize(prov);
        const taxpayers = asArray(data?.fraud_taxpayers);
        const tinMap = new Map();

        taxpayers.forEach((x) => {
          if (!tinMap.has(x.tin)) {
            tinMap.set(x.tin, x.taxpayer_name);
          }
        });

        heatmapArray.push({
          province: prov,
          fraud_count: num(data?.fraud_tins ?? tinMap.size),
          risk_percentage: Math.round(num(data?.risk_percentage)),
        });

        provinceTinDetails[normProv] = [...tinMap.entries()].map(([tin, name]) => ({
          tin,
          taxpayer_name: name,
        }));
      });

      setMapStaticData(heatmapArray);
      setProvinceTinInfo(provinceTinDetails);
    } catch (err) {
      console.error("SWT Province Error:", err);
      const message = getRequestErrorMessage(err);
      if (message) {
        setDashboardError(message);
      }
    } finally {
      if (requestId === provinceRequestIdRef.current) {
        setSectionLoading((prev) => ({ ...prev, province: false }));
      }
    }
  }, [abortActiveRequests, getParams, getRequestErrorMessage, getWithTimeout, normalize]);

  useEffect(() => {
    fetchDashboardData();
  }, [fetchDashboardData]);

  useEffect(() => {
    fetchLatestRecords();
  }, [fetchLatestRecords]);

  useEffect(() => () => abortActiveRequests(), [abortActiveRequests]);

  useEffect(() => {
    if (!provinceSectionRef.current || shouldLoadProvince) {
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
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
  }, [fetchProvinceData, shouldLoadProvince]);

  const handleSwtSalaryTinChange = useCallback(async (event) => {
    const nextTin = event.target.value;
    const requestId = salaryRequestIdRef.current + 1;
    salaryRequestIdRef.current = requestId;

    setSwtSalaryChart((prev) => ({
      ...prev,
      selectedTin: nextTin,
    }));

    try {
      abortActiveRequests("salary");
      setDashboardError("");
      setSectionLoading((prev) => ({ ...prev, sales: true }));

      const salaryRes = await getWithTimeout(
        "/swt/dashboard/swt-vs-salary",
        { ...getParams(), tin: nextTin },
        { useMemoryCache: true, scope: "salary" }
      );

      if (requestId !== salaryRequestIdRef.current) {
        return;
      }

      setSwtSalaryChart({
        categories: asArray(salaryRes.data?.categories),
        series: asArray(salaryRes.data?.series),
        chartData: asArray(salaryRes.data?.chart_data),
        availableTins: asArray(salaryRes.data?.available_tins),
        selectedTin: str(salaryRes.data?.selected_tin ?? nextTin, ""),
      });
    } catch (err) {
      const message = getRequestErrorMessage(err);
      if (message) {
        setDashboardError(message);
      }
    } finally {
      if (requestId === salaryRequestIdRef.current) {
        setSectionLoading((prev) => ({ ...prev, sales: false }));
      }
    }
  }, [abortActiveRequests, getParams, getRequestErrorMessage, getWithTimeout]);

  // ---------------- CHART CUSTOMIZATIONS ----------------

  const swtSalaryChartWidth = useMemo(() => Math.max(1200, asArray(swtSalaryChart.chartData).length * 90), [swtSalaryChart.chartData]);

  const swtVsSalaryOptions = useMemo(() => ({
  chart: {
    type: "line",
    toolbar: { show: true, tools: { download: false, selection: false, zoom: true, zoomin: true, zoomout: true, pan: false, reset: true } },
    zoom: { enabled: true }
  },
  stroke: { curve: "smooth", width: 3 },
  colors: ["#006EDC", "#10B981"],
  dataLabels: { enabled: false },
  markers: { size: 4 },
  tooltip: {
    shared: true,
    intersect: false,
    y: {
      formatter: (value) => `K ${Number(value ?? 0).toLocaleString()}`,
    },
  },
  legend: {
    position: "top",
  },
  grid: {
    borderColor: "#e7e7e7",
    strokeDashArray: 4,
  },
  xaxis: {
    categories: swtSalaryChart.categories,
    labels: {
      rotate: -45,
      trim: false,
      hideOverlappingLabels: true,
    },
  },
  yaxis: {
    labels: {
      formatter: (value) => formatLargeNumber(value),
    },
  },
  noData: {
    text: "No SWT salary comparison data found",
    align: "center",
    verticalAlign: "middle",
  },
}), [formatLargeNumber, swtSalaryChart.categories]);


  // Fraud Chart (BAR CLEARER THAN HEATMAP)
  const fraudOptions = useMemo(() => ({
    chart: { type: "bar", toolbar: { show: false } },
    colors: ["#ff4757"],
    plotOptions: { bar: { borderRadius: 6 }},
    xaxis: { categories: fraudChart.categories },
  }), [fraudChart.categories]);

  // Segmentation PIE Chart
  const segmentationOptions = useMemo(() => ({
    chart: { type: "bar", toolbar: { show: false } },
    plotOptions: {
      bar: {
        horizontal: false,
        distributed: true,
        borderRadius: 4,
        columnWidth: "45%"
      }
    },
    dataLabels: { enabled: false },
    xaxis: { categories: segmentation.labels },
    colors: ["#00A36C", "#007BFF", "#FF7F50", "#A66DD4", "#FFC300"],
  }), [segmentation.labels]);

  const filteredRecords = useMemo(() => asArray(latestRecords).filter((row) =>
    Object.values(row || {}).some((v) => (v ?? "").toString().toLowerCase().includes(searchText.toLowerCase()))
  ), [latestRecords, searchText]);

  const columns = useMemo(() => [
    { name: "TIN", selector: (row) => str(row?.tin ?? row?.tin_number ?? row?.tinNumber, ""), sortable: true },
    { name: "Employer", selector: (row) => str(row?.taxpayer_name ?? row?.taxpayer ?? row?.name), wrap: true },
    { name: "Segmentation", selector: (row) => str(row?.segmentation, "-"), sortable: true },
    { name: "Salary", selector: (row) => num(row?.salary ?? row?.total_salary_wages_paid ?? row?.salary_wages_paid), sortable: true },
    { name: "SWT Deducted", selector: (row) => num(row?.swt_tax ?? row?.total_swt_tax_deducted ?? row?.swt_deducted), sortable: true },
    { name: "Period", selector: (row) => str(row?.period ?? row?.month ?? row?.tax_period, ""), sortable: true },
  ], []);

  const chartSkeleton = useCallback((height = 350) => (
    <Box>
      <Skeleton variant="text" width="40%" height={32} />
      <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />
    </Box>
  ), []);

  const summaryCards = useMemo(() => ([
    { color: "#5096FF", title: "Total Employers", value: num(summary.total_employers ?? summary.total_tax_payers ?? summary.total_employer) },
    { color: "#47C99E", title: "Total Wages Paid", value: formatCurrency(summary.total_salary_wages_paid ?? summary.total_wages_paid ?? summary.total_salary) },
    { color: "#F96992", title: "Total SWT Deducted", value: formatCurrency(summary.total_swt_tax_deducted ?? summary.total_swt_deducted ?? summary.swt_tax) },
    { color: "#FFA56D", title: "Effective SWT Rate", value: `${(num(summary.effective_rate ?? summary.effectiveRate) * 100).toFixed(2)}%` },
  ]), [formatCurrency, summary]);

  const buildSeriesRows = (categories, series) => asArray(categories).map((category, rowIndex) => {
    const row = { id: `${category}-${rowIndex}`, category: str(category) };
    asArray(series).forEach((item, seriesIndex) => {
      row[`series_${seriesIndex}`] = Number(item?.data?.[rowIndex] ?? 0);
    });
    return row;
  });
  const buildSeriesColumns = (label, series, formatter = (value) => value.toLocaleString()) => [
    { name: label, selector: (row) => row.category, sortable: true, wrap: true },
    ...asArray(series).map((item, index) => ({
      name: item?.name || `Series ${index + 1}`,
      selector: (row) => row[`series_${index}`],
      sortable: true,
      right: true,
      format: (row) => formatter(row[`series_${index}`]),
    })),
  ];
  const salaryTableData = buildSeriesRows(swtSalaryChart.categories, swtSalaryChart.series);
  const fraudTableData = buildSeriesRows(fraudChart.categories, fraudChart.series);
  const segmentationTableData = asArray(segmentation.labels).map((label, index) => ({
    id: `${label}-${index}`,
    segment: str(label),
    count: Number(segmentation.series?.[index] ?? 0),
  }));
  const salaryTableColumns = buildSeriesColumns("Month", swtSalaryChart.series, formatCurrency);
  const fraudTableColumns = buildSeriesColumns("Month", fraudChart.series);
  const segmentationTableColumns = [
    { name: "Segment", selector: (row) => row.segment, sortable: true, wrap: true },
    { name: "Count", selector: (row) => row.count, sortable: true, right: true, format: (row) => row.count.toLocaleString() },
  ];
  const hasSeriesData = (categories, series) => asArray(categories).length > 0 && asArray(series).some((item) => asArray(item?.data).length > 0);
  const hasSalaryData = hasSeriesData(swtSalaryChart.categories, swtSalaryChart.series);
  const hasFraudData = hasSeriesData(fraudChart.categories, fraudChart.series);
  const hasSegmentationData = asArray(segmentation.labels).length > 0 && asArray(segmentation.series).length > 0;

  return (
    <div className="container-fluid">
      <div className="row">
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />

        <div className="col-lg-12 col-md-12">
          <Sidebar collapsed={collapsed} setCollapsed={setCollapsed} openMenu={openMenu} setOpenMenu={setOpenMenu} />

          <main className="main-content mt-5" ref={dashboardSWTRef}>
            <div className="container">
              <div className="page">

                <div style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center',
                    marginBottom: '1rem'
                  }}>
                    <div className="header-title-page" style={{ margin: 0 }}>SWT Dashboard</div>
                    <Button
                      className="hideme"
                      variant="contained"
                      color="primary"
                      size="small"
                      onClick={downloadDashboardSWTPDF}
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
                    <Button
                      size="small"
                      variant="contained"
                      onClick={handleSubmitFilters}
                      disabled={!canSubmit || isDashboardSubmitting}
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

                {/* Summary cards - Matches Dashboard.jsx exactly */}
                <div className="row mb-4">
                  {summaryCards.map((c, i) => (
                    <div key={i} className="col-lg-3 col-md-6 mb-3">
                      <div className="card text-white h-100" style={{ background: c.color }}>
                        <div className="card-body">
                          {sectionLoading.summary ? (
                            <>
                              <Skeleton variant="text" width="70%" height={34} />
                              <Skeleton variant="text" width="50%" height={20} />
                            </>
                          ) : (
                            <>
                              <h4 className="fw-bold mb-0">{c.value}</h4>
                              <small>{c.title}</small>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Charts */}
                <div className="row">
                  <div className="col-lg-12 mb-4">
                    <ChartDataCard
                      title="Salary Wages Paid vs SWT Deducted"
                      isChartView={chartView[VIEW_KEYS.salary]}
                      onToggleView={() => toggleChartView(VIEW_KEYS.salary)}
                      onDownloadCsv={downloadSalaryVsSwtCsv}
                      loading={sectionLoading.sales}
                      hasData={hasSalaryData}
                      chartSkeleton={chartSkeleton(380)}
                      tableSkeleton={<TableSkeleton columnCount={Math.max(swtSalaryChart.series.length + 1, 3)} />}
                      emptyMessage="No records available for the selected criteria"
                      chartContent={<>
                        <div className="d-flex justify-content-between align-items-center flex-wrap gap-3 mb-3">
                          <Typography variant="body2" color="text.secondary">
                            {swtSalaryChart.selectedTin
                              ? `TIN: ${swtSalaryChart.selectedTin}`
                              : "No TIN available"}
                          </Typography>
                          <FormControl size="small" style={{ minWidth: 220 }}>
                            <InputLabel id="swt-salary-tin-label">TIN</InputLabel>
                            <Select
                              labelId="swt-salary-tin-label"
                              value={swtSalaryChart.selectedTin || ""}
                              label="TIN"
                              onChange={handleSwtSalaryTinChange}
                              disabled={!asArray(swtSalaryChart.availableTins).length || sectionLoading.sales}
                            >
                              {asArray(swtSalaryChart.availableTins).map((item) => (
                                <MenuItem key={item.tin} value={item.tin}>
                                  {item.label}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </div>
                        {asArray(swtSalaryChart.chartData).length ? (
                          <div
                            style={{
                              overflowX: "auto",
                              overflowY: "hidden",
                              width: "100%",
                              paddingBottom: "8px",
                              scrollBehavior: "smooth",
                            }}
                          >
                            <div
                              style={{
                                minWidth: `${swtSalaryChartWidth}px`,
                              }}
                            >
                              <Chart
                                options={swtVsSalaryOptions}
                                series={swtSalaryChart.series}
                                type="line"
                                height={380}
                                width={swtSalaryChartWidth}
                              />
                            </div>
                          </div>
                        ) : <EmptyState message="No records available for the selected criteria" />}
                      </>}
                      tableContent={<DataTable columns={salaryTableColumns} data={salaryTableData} customStyles={tableCustomStyles} dense pagination paginationPerPage={10} highlightOnHover responsive persistTableHead />}
                    />
                  </div>

                  {/* Fraud bar chart - Matches Dashboard.jsx styling */}
                  <div className="col-lg-6 mb-4">
                    <ChartDataCard title="Fraud / Red Flag Cases (Monthly)" isChartView={chartView[VIEW_KEYS.fraud]} onToggleView={() => toggleChartView(VIEW_KEYS.fraud)} onDownloadCsv={downloadFraudMonthlyCsv} loading={sectionLoading.risk} hasData={hasFraudData} chartSkeleton={chartSkeleton(350)} tableSkeleton={<TableSkeleton columnCount={Math.max(fraudChart.series.length + 1, 2)} />} emptyMessage="No records available for the selected criteria"
                      chartContent={<div style={{ overflowX: "auto" }}>
                          <div style={{ minWidth: `${Math.max(fraudChart.categories.length, 1) * 60}px` }}>
                            <Chart
                              options={fraudOptions}
                              series={fraudChart.series}
                              type="bar"
                              height={350}
                            />
                          </div>
                        </div>}
                      tableContent={<DataTable columns={fraudTableColumns} data={fraudTableData} customStyles={tableCustomStyles} dense pagination paginationPerPage={10} highlightOnHover responsive persistTableHead />}
                    />
                  </div>

                  {/* Segmentation - Matches Dashboard.jsx styling */}
                  <div className="col-lg-6 mb-4">
                    <ChartDataCard title="Segmentation Distribution" isChartView={chartView[VIEW_KEYS.segmentation]} onToggleView={() => toggleChartView(VIEW_KEYS.segmentation)} onDownloadCsv={downloadSegmentationCsv} loading={sectionLoading.segmentation} hasData={hasSegmentationData} chartSkeleton={chartSkeleton(350)} tableSkeleton={<TableSkeleton columnCount={2} />} emptyMessage="No records available for the selected criteria"
                      chartContent={<Chart options={segmentationOptions} series={[{ data: segmentation.series }]} type="bar" height={350} />}
                      tableContent={<DataTable columns={segmentationTableColumns} data={segmentationTableData} customStyles={tableCustomStyles} dense pagination paginationPerPage={10} highlightOnHover responsive persistTableHead />}
                    />
                  </div>
                </div>

                <div className="page">
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
                              <PNGMapSWT
                                staticData={mapStaticData}
                                onProvinceSelect={(province, data) => {
                                  const normProv = normalize(province);

                                  setSelectedProvinceData({
                                    province,
                                    fraud_count: data.fraud_count,
                                    risk_percentage: data.risk_percentage,
                                  });

                                  setSelectedTinList(provinceTinInfo[normProv] || []);
                                  setTinModalOpen(true);
                                }}
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

                        {/* Unique TINs Modal */}
                        {tinModalOpen && (
                          <div
                            className="modal fade show"
                            style={{
                              display: "block",
                              background: "rgba(0,0,0,0.5)",
                              zIndex: 5000,
                            }}
                          >
                            <div className="modal-dialog modal-lg">
                              <div className="modal-content">
                                <div className="modal-header">
                                  <h5 className="modal-title">
                                    Fraud TINs — {selectedProvinceData?.province}
                                  </h5>
                                  <button
                                    className="btn-close"
                                    onClick={() => setTinModalOpen(false)}
                                  />
                                </div>

                                <div className="modal-body">
                                  {selectedTinList.length === 0 ? (
                                    <p>No fraud TINs found.</p>
                                  ) : (
                                    <table className="table table-bordered">
                                      <thead>
                                        <tr>
                                          <th>TIN</th>
                                          <th>Taxpayer Name</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {selectedTinList.map((row, idx) => (
                                          <tr key={idx}>
                                            <td>{row.tin}</td>
                                            <td>{row.taxpayer_name}</td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  )}
                                </div>

                                <div className="modal-footer">
                                  <button
                                    className="btn btn-secondary"
                                    onClick={() => setTinModalOpen(false)}
                                  >
                                    Close
                                  </button>
                                </div>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
                </div>

              </div>
              

              {/* Latest SWT Records Table */}
              <Paper className="p-3 mb-4 page">
                <div className="d-flex justify-content-between mb-3">
                  <h6 className="fw-bold">Latest SWT Records</h6>
                  <TextField size="small" placeholder="Search..." value={searchText}
                    onChange={(e) => setSearchText(e.target.value)} />
                  <DataTableExport data={filteredRecords} filename="SWT-Records" />
                </div>

                <DataTable
                  columns={columns}
                  data={filteredRecords}
                  pagination
                  paginationServer
                  paginationTotalRows={recordsTotal}
                  paginationPerPage={recordsPerPage}
                  onChangePage={(page) => setRecordsPage(page)}
                  onChangeRowsPerPage={(pageSize) => {
                    setRecordsPerPage(pageSize);
                    setRecordsPage(1);
                  }}
                  customStyles={tableCustomStyles}
                  dense
                  striped
                  progressPending={recordsLoading}
                  progressComponent={<Box sx={{ py: 6, display: "flex", justifyContent: "center" }}><CircularProgress size={28} /></Box>}
                />
              </Paper>

            </div>
          </main>
        </div>

        <Footer />
      </div>

    </div>
  );
}
