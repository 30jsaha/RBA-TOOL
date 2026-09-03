// CitDashboard.jsx
import { lazy, Suspense, useEffect, useRef, useState, useCallback, useMemo } from "react";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import Chart from "react-apexcharts";
import DataTable from "react-data-table-component";
import {
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Paper,
  Button,
  Tooltip,
  CircularProgress,
  Typography,
  Alert,
  Skeleton,
  Box
} from "@mui/material";
import dayjs from "dayjs";
import API from "../api/api";
import tableCustomStyles from "../components/common/tableStyles";
import "./css/Dashboard.css";
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
const PNGMapCIT = lazy(() => import("../components/maps/PNGMapCIT"));
const CHART_TOOLBAR = {
  show: false,
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
    csv: { filename: "cit-chart-data" },
    svg: { filename: "cit-chart" },
    png: { filename: "cit-chart" },
  },
};

export default function CitDashboard() {
  const [collapsed, setCollapsed] = useState(false);

  /* ================= FILTER STATE ================= */
  const [tenure, setTenure] = useState("1y");
  const [startDate, setStartDate] = useState(dayjs().startOf("year"));
  const [endDate, setEndDate] = useState(dayjs().endOf("year"));

  /* ================= DATA STATE ================= */
  const [topProfit, setTopProfit] = useState([]);
  const [topLoss, setTopLoss] = useState([]);
  const [topCount, setTopCount] = useState(10);
  const [segmentation, setSegmentation] = useState({ labels: [], series: [] });
  const [risk, setRisk] = useState({ labels: [], series: [] });

  const [superannuation, setSuperannuation] = useState([]);
  const [interest, setInterest] = useState([]);
  const [salesCogs, setSalesCogs] = useState([]);
  const [salesDetailsOpen, setSalesDetailsOpen] = useState(false);
  const [salesDetails, setSalesDetails] = useState([]);
  const [salesDetailsLoading, setSalesDetailsLoading] = useState(false);
  const [salesDetailsError, setSalesDetailsError] = useState("");
  const [selectedSalesYear, setSelectedSalesYear] = useState(null);
  const [latestRecords, setLatestRecords] = useState([]);
  const [searchText, setSearchText] = useState("");

  const [mapStaticData, setMapStaticData] = useState([]);
  const [selectedProvinceData, setSelectedProvinceData] = useState(null);
  const [dashboardError, setDashboardError] = useState("");
  const [shouldLoadProvince, setShouldLoadProvince] = useState(false);
  const [provinceLoading, setProvinceLoading] = useState(false);
  
  // Match Dashboard.jsx loading structure - but keep original loading state names
  const [sectionLoading, setSectionLoading] = useState({
    summary: true,
    sales: true,
    gst: true,
    segmentation: true,
    risk: true,
    province: false,
  });

  const dashboardCitRef = useRef();
  const activeControllersRef = useRef([]);
  const provinceSectionRef = useRef(null);
  const dashboardRequestIdRef = useRef(0);
  const provinceRequestIdRef = useRef(0);
  const isMountedRef = useRef(false);
  const loadMetricsRef = useRef({ key: "", startedAt: 0, dataReadyAt: 0, renderLogged: false });

  const downloadDashboardPDF = async () => {
    const input = dashboardCitRef.current;
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
      pdf.text("CIT Dashboard Report", 10, 10);
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
    pdf.save(`CIT-Dashboard_${fileTime}.pdf`);
  };

  /* ================= HELPERS ================= */
  const getParams = useCallback(() => {
    const params = { range_type: tenure };
    if (tenure === "custom") {
      params.start_date = startDate.format("YYYY-MM-DD");
      params.end_date = endDate.format("YYYY-MM-DD");
    }
    params.top_n = topCount;
    return params;
  }, [tenure, startDate, endDate, topCount]);

  const downloadCitCsv = async (endpoint, filename, columns, extraParams = {}) => {
    try {
      const params = getParams();
      const csvParams = columns?.length
        ? { ...params, ...extraParams, columns: columns.join(",") }
        : { ...params, ...extraParams };
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

  const downloadNetProfitCsv = () =>
    exportTopCsv(displayTopProfit, ["tin", "taxpayer", "net_profit"], "cit-net-profit.csv");
  const downloadNetLossCsv = () =>
    exportTopCsv(displayTopLoss, ["tin", "taxpayer", "net_loss"], "cit-net-loss.csv");
  const downloadSegmentationCsv = () =>
    downloadCitCsv("/cit/download-csv/segmentation", "cit-segmentation.csv", [
      "tin",
      "taxpayer_name",
      "segmentation",
      "total",
    ]);
  const downloadRiskCsv = () =>
    downloadCitCsv("/cit/download-csv/risk-flagged", "cit-risk-flagged.csv", [
      "tin",
      "taxpayer_name",
      "risk_flag",
      "total",
    ]);
  const downloadSuperCsv = () =>
    downloadCitCsv("/cit/download-csv/superannuation", "cit-superannuation.csv", [
      "tin",
      "taxpayer_name",
      "superannuation_type",
      "amount",
    ]);
  const downloadInterestCsv = () =>
    downloadCitCsv("/cit/download-csv/interest", "cit-interest.csv", [
      "tin",
      "taxpayer_name",
      "interest_type",
      "amount",
    ]);
  const downloadProvinceCsv = () =>
    downloadCitCsv("/cit/download-csv/province", "cit-province.csv", [
      "tin",
      "taxpayer_name",
      "province",
      "predicted_fraud",
      "explanation",
    ]);
  const downloadSalesCogsCsv = () =>
    downloadCitCsv("/cit/download-csv/gross-sales-cogs", "cit-gross-sales-cogs.csv", [
      "tin",
      "taxpayer_name",
      "period",
      "gross_sales",
      "cogs",
      "sales_cogs_percent",
    ]);
  const downloadLatestRecordsCsv = () =>
    downloadCitCsv("/cit/download-csv/latest-records", "latest-cit-records.csv", [
      "tin",
      "taxpayer_name",
      "tax_period_year",
      "gross_income",
      "gross_sales",
      "cogs",
      "net_profit",
      "predicted_fraud",
    ]);

  const exportTopCsv = (rows, headers, filename) => {
    const safeRows = Array.isArray(rows) ? rows : [];
    const csvRows = [
      headers.join(","),
      ...safeRows.map((r) =>
        headers.map((h) => `"${(r?.[h] ?? "")}"`).join(",")
      ),
    ];
    const blob = new Blob([csvRows.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Caching and abort functions - same as Dashboard.jsx
  const logDashboardTiming = useCallback((stage, extra = {}) => {
    if (typeof performance === "undefined") return;
    const { key, startedAt, dataReadyAt } = loadMetricsRef.current;
    const now = performance.now();
    const totalMs = startedAt ? Math.round(now - startedAt) : 0;
    const dataMs = startedAt && dataReadyAt ? Math.round(dataReadyAt - startedAt) : 0;

    console.info(`[CitDashboard] ${stage}`, {
      key,
      totalMs,
      dataMs,
      ...extra,
    });
  }, []);

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
      return `CIT dashboard request timed out after ${Math.round(timeoutMs / 1000)} seconds. Please try again.`;
    }

    return (
      error?.response?.data?.error ||
      error?.response?.data?.message ||
      "Unable to load CIT dashboard right now. Please try again."
    );
  }, []);

  const makeCacheKey = useCallback((url, params) => `${url}:${JSON.stringify(params || {})}`, []);

  const getWithTimeout = useCallback(async (url, params, options = {}) => {
    const {
      useMemoryCache = false,
      ttlMs = DASHBOARD_CACHE_TTL_MS,
      timeoutMs = 60000,
      abortable = true,
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

    const controller = abortable ? new AbortController() : null;
    if (controller) {
      activeControllersRef.current.push(controller);
    }

    const requestPromise = API.get(url, {
      params,
      ...(controller ? { signal: controller.signal } : {}),
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
      inflightDashboardRequests.delete(cacheKey);
      if (controller) {
        activeControllersRef.current = activeControllersRef.current.filter(
          (item) => item !== controller
        );
      }
    });

    inflightDashboardRequests.set(cacheKey, requestPromise);
    return requestPromise;
  }, [makeCacheKey]);

  const handleViewSalesDetails = async (year) => {
    setSelectedSalesYear(year);
    setSalesDetailsOpen(true);
    setSalesDetails([]);
    setSalesDetailsError("");
    setSalesDetailsLoading(true);

    try {
      const res = await API.get("/cit/sales-cogs-details", {
        params: { year },
      });

      if (res.data?.success) {
        setSalesDetails(res.data.data || []);
      } else {
        setSalesDetailsError(res.data?.message || "Failed to load details.");
      }
    } catch (err) {
      setSalesDetailsError(err?.response?.data?.message || err.message || "Failed to load details.");
    } finally {
      setSalesDetailsLoading(false);
    }
  };

  /* ================= APEX EXPORT TOOLBAR ================= */

  const chartSkeleton = useCallback((height = 350) => (
    <Box>
      <Skeleton variant="text" width="40%" height={32} />
      <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />
    </Box>
  ), []);

  /* ================= API CALL ================= */
  const fetchCITDashboard = useCallback(async () => {
    const requestId = dashboardRequestIdRef.current + 1;
    dashboardRequestIdRef.current = requestId;

    try {
      abortActiveRequests();
      const params = getParams();
      const requestKey = JSON.stringify(params);
      loadMetricsRef.current = {
        key: requestKey,
        startedAt: typeof performance !== "undefined" ? performance.now() : 0,
        dataReadyAt: 0,
        renderLogged: false,
      };
      setDashboardError("");
      setShouldLoadProvince(false);
      setMapStaticData([]);
      setSelectedProvinceData(null);

      setSectionLoading({
        summary: true,
        sales: true,
        gst: true,
        segmentation: true,
        risk: true,
        province: false,
      });

      const pendingCounts = {
        summary: 2,
        sales: 1,
        gst: 1,
        segmentation: 1,
        risk: 1,
      };

      const markSectionSettled = (section) => {
        pendingCounts[section] -= 1;
        if (pendingCounts[section] <= 0 && isMountedRef.current && requestId === dashboardRequestIdRef.current) {
          setSectionLoading((prev) => ({ ...prev, [section]: false }));
        }
      };

      const handleWidgetError = (label, error) => {
        console.error(`[CitDashboard] ${label} failed`, error);
        if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) {
          return;
        }
        setDashboardError((prev) => prev || getRequestErrorMessage(error));
      };

      await Promise.allSettled([
        getWithTimeout("/cit/dashboard/top-profit", params, { useMemoryCache: true, abortable: false })
          .then((profitRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            setTopProfit(asArray(profitRes.data));
          })
          .catch((error) => {
            handleWidgetError("top-profit", error);
          })
          .finally(() => {
            markSectionSettled("summary");
          }),
        getWithTimeout("/cit/dashboard/top-loss", params, { useMemoryCache: true, abortable: false })
          .then((lossRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            setTopLoss(asArray(lossRes.data));
          })
          .catch((error) => {
            handleWidgetError("top-loss", error);
          })
          .finally(() => {
            markSectionSettled("summary");
          }),
        getWithTimeout("/cit/dashboard/segmentation-distribution", params, { useMemoryCache: true, abortable: false })
          .then((segRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            setSegmentation({
              labels: asArray(segRes.data?.labels),
              series: asArray(segRes.data?.series).map(num),
            });
          })
          .catch((error) => {
            handleWidgetError("segmentation-distribution", error);
          })
          .finally(() => {
            markSectionSettled("segmentation");
          }),
        getWithTimeout("/cit/dashboard/risk-distribution", params, { useMemoryCache: true, abortable: false })
          .then((riskRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            setRisk({
              labels: asArray(riskRes.data?.labels),
              series: asArray(riskRes.data?.series).map(num),
            });
          })
          .catch((error) => {
            handleWidgetError("risk-distribution", error);
          })
          .finally(() => {
            markSectionSettled("risk");
          }),
        getWithTimeout("/cit/dashboard/superannuation", params, { useMemoryCache: true, abortable: false })
          .then((superRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            setSuperannuation([
              { type: "PNG", amount: num(superRes.data?.series?.[0]?.data?.[0] ?? superRes.data?.data?.[0]) },
              { type: "Foreign", amount: num(superRes.data?.series?.[0]?.data?.[1] ?? superRes.data?.data?.[1]) },
            ]);
          })
          .catch((error) => {
            handleWidgetError("superannuation", error);
          }),
        getWithTimeout("/cit/dashboard/interest", params, { useMemoryCache: true, abortable: false })
          .then((interestRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            setInterest([
              {
                type: "Interest Income",
                amount: num(interestRes.data?.series?.[0]?.data?.[0] ?? 0),
              },
              {
                type: "Foreign Interest Expense",
                amount: num(interestRes.data?.series?.[0]?.data?.[1] ?? 0),
              },
            ]);
          })
          .catch((error) => {
            handleWidgetError("interest", error);
          }),
        getWithTimeout("/cit/dashboard/sales-vs-cogs", params, { useMemoryCache: true, abortable: false })
          .then((salesRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            const salesData = salesRes?.data;
            if (
              salesData &&
              Array.isArray(salesData.categories) &&
              Array.isArray(salesData.series)
            ) {
              setSalesCogs(
                salesData.categories.map((cat, i) => ({
                  period: cat,
                  sales: salesData.series?.[0]?.data?.[i] || 0,
                  cogs: salesData.series?.[1]?.data?.[i] || 0,
                }))
              );
            } else {
              setSalesCogs([]);
            }
          })
          .catch((error) => {
            handleWidgetError("sales-vs-cogs", error);
          })
          .finally(() => {
            markSectionSettled("sales");
          }),
        getWithTimeout("/cit/dashboard/latest-records", params, { useMemoryCache: true, abortable: false })
          .then((latestRecordsRes) => {
            if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;
            setLatestRecords(asArray(latestRecordsRes?.data));
          })
          .catch((error) => {
            handleWidgetError("latest-records", error);
          })
          .finally(() => {
            markSectionSettled("gst");
          }),
      ]);

      if (!isMountedRef.current || requestId !== dashboardRequestIdRef.current) return;

      loadMetricsRef.current.dataReadyAt = typeof performance !== "undefined" ? performance.now() : 0;
      logDashboardTiming("data_ready", { requestCount: 8 });
    } catch (err) {
      console.error("CIT Dashboard API error:", err);
      if (requestId === dashboardRequestIdRef.current) {
        setDashboardError(getRequestErrorMessage(err));
        setSectionLoading({
          summary: false,
          sales: false,
          gst: false,
          segmentation: false,
          risk: false,
          province: false,
        });
      }
    }
  }, [abortActiveRequests, getParams, getRequestErrorMessage, getWithTimeout, logDashboardTiming]);

  useEffect(() => {
    isMountedRef.current = true;
    fetchCITDashboard();

    return () => {
      isMountedRef.current = false;
      abortActiveRequests();
    };
  }, [abortActiveRequests, fetchCITDashboard]);

  const handleProvinceSelect = useCallback((province, data) => {
    setSelectedProvinceData({
      province,
      fraud_count: data?.fraud_count ?? 0,
      risk_percentage: data?.risk_percentage ?? 0,
    });
  }, []);

  const fetchProvinceData = useCallback(async () => {
    const requestId = provinceRequestIdRef.current + 1;
    provinceRequestIdRef.current = requestId;

    try {
      setSectionLoading((prev) => ({ ...prev, province: true }));
      setProvinceLoading(true);
      const params = getParams();
      const fraudProvinceRes = await getWithTimeout(
        "/cit/dashboard/fraud-province-distribution-cit",
        params,
        { useMemoryCache: false }
      );

      if (!isMountedRef.current || requestId !== provinceRequestIdRef.current) return;

      const provObj = fraudProvinceRes?.data?.province_distribution || {};
      const heatmapArray = [];

      Object.entries(provObj).forEach(([prov, data]) => {
        heatmapArray.push({
          province: prov,
          fraud_count: data.fraud_tins || 0,
          risk_percentage: Math.round(data.risk_percentage || 0),
        });
      });

      setMapStaticData(heatmapArray);
    } catch (err) {
      console.error("❌ CIT Province API error:", err);
      if (isMountedRef.current && requestId === provinceRequestIdRef.current) {
        setDashboardError(getRequestErrorMessage(err));
      }
    } finally {
      if (isMountedRef.current && requestId === provinceRequestIdRef.current) {
        setProvinceLoading(false);
        setSectionLoading((prev) => ({ ...prev, province: false }));
      }
    }
  }, [getParams, getWithTimeout, getRequestErrorMessage]);

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
    if (shouldLoadProvince) {
      fetchProvinceData();
    }
  }, [fetchProvinceData, shouldLoadProvince]);

  useEffect(() => {
    const isDashboardReady = !sectionLoading.summary &&
      !sectionLoading.sales &&
      !sectionLoading.gst &&
      !sectionLoading.segmentation &&
      !sectionLoading.risk;

    if (!isDashboardReady || loadMetricsRef.current.renderLogged) {
      return;
    }

    loadMetricsRef.current.renderLogged = true;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        logDashboardTiming("render_dashboard", {
          strictMode: true,
        });
      });
    });
  }, [logDashboardTiming, sectionLoading.gst, sectionLoading.risk, sectionLoading.sales, sectionLoading.segmentation, sectionLoading.summary]);


  const displayTopProfit = useMemo(() => topProfit.slice(0, topCount), [topProfit, topCount]);
  const displayTopLoss = useMemo(() => topLoss.slice(0, topCount), [topLoss, topCount]);
  const hasSegmentationData = useMemo(() => (
    Array.isArray(segmentation.series) &&
    segmentation.series.some((v) => Number(v) > 0)
  ), [segmentation.series]);
  const hasRiskData = useMemo(() => (
    Array.isArray(risk.series) &&
    risk.series.some((v) => Number(v) > 0)
  ), [risk.series]);

  const segmentationChartOptions = useMemo(() => ({
    chart: {
      toolbar: CHART_TOOLBAR,
    },
    plotOptions: {
      bar: {
        distributed: true,
        columnWidth: "55%",
      },
    },
    dataLabels: {
      enabled: true,
    },
    tooltip: {
      enabled: true,
    },
    legend: {
      show: false,
    },
    xaxis: {
      categories: segmentation.labels,
      title: {
        text: "Segmentation",
      },
      labels: {
        rotate: -35,
      },
    },
    yaxis: {
      title: {
        text: "Number of taxpayers",
      },
    },
    responsive: [
      {
        breakpoint: 768,
        options: {
          plotOptions: {
            bar: {
              columnWidth: "70%",
            },
          },
          xaxis: {
            labels: {
              rotate: -20,
            },
          },
        },
      },
    ],
  }), [segmentation.labels]);
  const segmentationBarSeries = useMemo(() => ([
    {
      name: "Number of taxpayers",
      data: segmentation.series,
    },
  ]), [segmentation.series]);

  const riskChartOptions = useMemo(() => ({
    labels: risk.labels,
    chart: { toolbar: CHART_TOOLBAR },
    legend: { position: "bottom" },
  }), [risk.labels]);

  /* ================= TABLE COLUMNS ================= */
  const profitCols = useMemo(() => ([
    { name: "TIN", selector: r => r.tin, sortable: true },
    { name: "Taxpayer", selector: r => r.taxpayer, wrap: true },
    { name: "Net Profit (K)", selector: r => num(r?.net_profit ?? r?.netProfit).toLocaleString(), sortable: true },
  ]), []);

  const lossCols = useMemo(() => ([
    { name: "TIN", selector: r => r.tin, sortable: true },
    { name: "Taxpayer", selector: r => r.taxpayer, wrap: true },
    { name: "Net Loss (K)", selector: r => num(r?.net_loss ?? r?.netLoss).toLocaleString(), sortable: true },
  ]), []);

  const simpleCols = useMemo(() => ([
    { name: "Type", selector: r => str(r?.type) },
    { name: "Amount (K)", selector: r => num(r?.amount).toLocaleString() },
  ]), []);

  const salesCols = useMemo(() => ([
    { name: "Period", selector: r => str(r?.period, "") },
    { name: "Gross Sales", selector: r => num(r?.sales).toLocaleString() },
    { name: "COGS", selector: r => num(r?.cogs).toLocaleString() },
    {
      name: "Sales vs COGS %",
      selector: r => {
        const sales = num(r?.sales);
        const cogs = num(r?.cogs);
        if (!sales) return "0%";
        const percent = ((sales - cogs) / sales) * 100;
        return percent.toFixed(2) + "%";
      }
    },
    {
      name: "Action",
      cell: (row) => (
        <Button
          size="small"
          variant="outlined"
          onClick={() => handleViewSalesDetails(row.period)}
        >
          View
        </Button>
      ),
    },
  ]), [handleViewSalesDetails]);

  const salesDetailsCols = useMemo(() => ([
    { name: "TIN", selector: r => r.tin, wrap: true },
    { name: "Taxpayer Name", selector: r => r.taxpayer_name, wrap: true },
    { name: "Gross Sales", selector: r => Number(r.gross_sales || 0).toLocaleString() },
    { name: "COGS", selector: r => Number(r.cogs || 0).toLocaleString() },
    {
      name: "COGS %",
      selector: r => {
        const sales = Number(r.gross_sales || 0);
        const cogs = Number(r.cogs || 0);
        if (!sales) return "0%";
        return ((cogs / sales) * 100).toFixed(2) + "%";
      },
    },
  ]), []);

  const latestRecordsCols = useMemo(() => ([
    { name: "TIN", selector: (r) => str(r?.tin, ""), sortable: true, wrap: true },
    { name: "Taxpayer", selector: (r) => str(r?.taxpayer_name, ""), sortable: true, wrap: true },
    { name: "Year", selector: (r) => str(r?.tax_period_year, ""), sortable: true },
    { name: "Gross Income", selector: (r) => num(r?.gross_income).toLocaleString(), sortable: true },
    { name: "Gross Sales", selector: (r) => num(r?.gross_sales).toLocaleString(), sortable: true },
    { name: "COGS", selector: (r) => num(r?.cogs).toLocaleString(), sortable: true },
    { name: "Net Profit", selector: (r) => num(r?.net_profit).toLocaleString(), sortable: true },
    { name: "Fraud Status", selector: (r) => str(r?.predicted_fraud, "Unknown"), sortable: true, wrap: true },
  ]), []);

  const filteredLatestRecords = useMemo(() => asArray(latestRecords).filter((row) =>
    Object.values(row || {}).some((value) =>
      (value ?? "").toString().toLowerCase().includes(searchText.toLowerCase())
    )
  ), [latestRecords, searchText]);

  const modalOffset = collapsed ? 75 : 250;
  const modalMaxWidth = `calc(100vw - ${modalOffset + 48}px)`;

  /* ================= UI ================= */
  return (
    <div className="container-fluid">
      <Header toggleSidebar={() => setCollapsed(!collapsed)} />

      <div className="d-flex">
        <Sidebar collapsed={collapsed} />

        <main className="main-content p-3 mt-5 w-100" ref={dashboardCitRef}>
          <div className="page">
            <div style={{ 
              display: 'flex', 
              justifyContent: 'space-between', 
              alignItems: 'center', 
              marginBottom: '1rem' 
            }}>
              <h4 className="fw-bold" style={{ margin: 0 }}>CIT Dashboard</h4>
              <Button
                className="hideme"
                variant="contained"
                color="primary"
                size="small"
                onClick={downloadDashboardPDF}
              >
                Download PDF
              </Button>
            </div>

            {/* ================= FILTER ================= */}
            <div className="row mb-4">
              <div className="col-md-6">
                <FormControl fullWidth size="small">
                  <InputLabel>Tenure</InputLabel>
                  <Select value={tenure} label="Tenure" onChange={e => setTenure(e.target.value)}>
                    <MenuItem value="1y">Past 1 Year</MenuItem>
                    <MenuItem value="3y">Past 3 Years</MenuItem>
                    <MenuItem value="6y">Past 6 Years</MenuItem>
                    <MenuItem value="custom">Custom</MenuItem>
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
                        if (!newValue || !newValue.isValid()) return;
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
                        if (!newValue || !newValue.isValid()) return;
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

            {/* ================= TOP TABLES ================= */}
            <div className="row mb-4">
              <div className="col-md-6">
                <Paper className="p-3">
                  <div className="d-flex justify-content-between mb-2 align-items-center">
                    <div className="d-flex align-items-center gap-2">
                      <h6 className="fw-bold mb-0">Net Profit Taxpayers</h6>
                      <FormControl size="small" sx={{ minWidth: 90 }}>
                        <Select
                          value={topCount}
                          onChange={(e) => setTopCount(Number(e.target.value))}
                        >
                          {[5, 10, 15, 20].map((n) => (
                            <MenuItem key={n} value={n}>
                              Top {n}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </div>
                    <div className="d-flex gap-2">
                      <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadNetProfitCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>
                  <DataTable
                    columns={profitCols}
                    data={displayTopProfit}
                    pagination
                    dense
                    striped
                    customStyles={tableCustomStyles}
                    progressPending={sectionLoading.summary}
                    progressComponent={<Box sx={{ py: 6, display: "flex", justifyContent: "center" }}><CircularProgress size={28} /></Box>}
                  />
                </Paper>
              </div>

              <div className="col-md-6">
                <Paper className="p-3">
                  <div className="d-flex justify-content-between mb-2 align-items-center">
                    <h6 className="fw-bold">Net Loss Taxpayer</h6>
                    <div className="d-flex gap-2">
                      <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadNetLossCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>
                  <DataTable
                    columns={lossCols}
                    data={displayTopLoss}
                    pagination
                    dense
                    striped
                    customStyles={tableCustomStyles}
                    progressPending={sectionLoading.summary}
                    progressComponent={<Box sx={{ py: 6, display: "flex", justifyContent: "center" }}><CircularProgress size={28} /></Box>}
                  />
                </Paper>
              </div>
            </div>

            {/* ================== SEGMENTATION & RISK ================= */}
            <div className="row mb-4">
              <div className="col-md-6">
                <div className="card h-100">
                  <div className="card-header">
                    <div className="d-flex justify-content-between align-items-center fw-semibold">
                      <span>Segmentation Distribution</span>
                      <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadSegmentationCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>
                  <div className="card-body">
                    {sectionLoading.segmentation ? (
                      chartSkeleton(300)
                    ) : hasSegmentationData ? (
                      <Chart
                        type="bar"
                        height={300}
                        series={segmentationBarSeries}
                        options={segmentationChartOptions}
                      />
                    ) : (
                      <div className="text-center py-4">There are no records to display</div>
                    )}
                  </div>
                </div>
              </div>

              <div className="col-md-6">
                <div className="card h-100">
                  <div className="card-header">
                    <div className="d-flex justify-content-between align-items-center fw-semibold">
                      <span>Risk Flagged vs Non-Risk</span>
                      <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadRiskCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>
                  <div className="card-body">
                    {sectionLoading.risk ? (
                      chartSkeleton(300)
                    ) : hasRiskData ? (
                      <Chart
                        type="pie"
                        height={300}
                        series={risk.series}
                        options={riskChartOptions}
                      />
                    ) : (
                      <div className="text-center py-4">There are no records to display</div>
                    )}
                  </div>
                </div>
              </div>

              <div className="col-md-6">
                <Paper className="p-3">
                  <div className="d-flex justify-content-between mb-2 align-items-center">
                    <h6 className="fw-bold">Superannuation PNG vs Foreign</h6>
                    <div className="d-flex gap-2">
                      <Button size="small" variant="outlined" color="primary" onClick={downloadSuperCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>
                  <DataTable columns={simpleCols} data={superannuation} dense striped />
                </Paper>
              </div>

              <div className="col-md-6">
                <Paper className="p-3">
                  <div className="d-flex justify-content-between mb-2 align-items-center">
                    <h6 className="fw-bold">Interest PNG vs Foreign</h6>
                    <div className="d-flex gap-2">
                      <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadInterestCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>
                  <DataTable columns={simpleCols} data={interest} dense striped />
                </Paper>
              </div>

            </div>
          </div>
          <div className="page">
            {/* ================= DATA TABLES (NO CHARTS) ================= */}
            <div className="row mb-4">
              {/* ================= PROVINCE FRAUD MAP ================= */}
              <div className="col-12">
                <div className="card">
                  <div className="card-header">
                    <div className="d-flex justify-content-between align-items-center fw-bold">
                      <span>Fraud TIN Distribution by Province</span>
                      <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadProvinceCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>

                  <div className="card-body" ref={provinceSectionRef}>
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
                          <PNGMapCIT
                            staticData={mapStaticData}
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
              <div className="col-12 mt-3">
                <Paper className="p-3">
                  <div className="d-flex justify-content-between mb-2 align-items-center">
                    <h6 className="fw-bold">Gross Sales vs COGS</h6>
                    <div className="d-flex gap-2">
                      <Button size="small" variant="outlined" color="primary" startIcon={<TableChartIcon />} onClick={downloadSalesCogsCsv}>
                        CSV
                      </Button>
                    </div>
                  </div>
                  <DataTable
                    columns={salesCols}
                    data={salesCogs}
                    pagination
                    dense
                    striped
                    progressPending={sectionLoading.sales}
                    progressComponent={<Box sx={{ py: 6, display: "flex", justifyContent: "center" }}><CircularProgress size={28} /></Box>}
                  />
                </Paper>
              </div>
              <div className="col-12 mt-3">
                <Paper className="p-3">
                  <div className="d-flex justify-content-between mb-3 align-items-center">
                    <h6 className="fw-bold mb-0">Latest CIT Records</h6>
                    <TextField
                      size="small"
                      placeholder="Search..."
                      value={searchText}
                      onChange={(e) => setSearchText(e.target.value)}
                    />
                    <Button
                      size="small"
                      variant="outlined"
                      color="primary"
                      startIcon={<TableChartIcon />}
                      onClick={downloadLatestRecordsCsv}
                      className="hideme"
                    >
                      CSV
                    </Button>
                  </div>
                  <DataTable
                    columns={latestRecordsCols}
                    data={filteredLatestRecords}
                    pagination
                    dense
                    striped
                    customStyles={tableCustomStyles}
                    progressPending={sectionLoading.gst}
                    progressComponent={<Box sx={{ py: 6, display: "flex", justifyContent: "center" }}><CircularProgress size={28} /></Box>}
                  />
                </Paper>
              </div>
            </div>

            {/* Sales vs COGS Details Modal */}
            {salesDetailsOpen && (
              <div
                className="modal fade show"
                style={{
                  position: "fixed",
                  inset: 0,
                  paddingLeft: modalOffset,
                  paddingRight: 16,
                  display: "block",
                  background: "rgba(0,0,0,0.5)",
                  zIndex: 10050,
                }}
              >
                <div
                  className="modal-dialog"
                  style={{ maxWidth: modalMaxWidth, width: "100%" }}
                >
                  <div className="modal-content">
                    <div className="modal-header">
                      <h5 className="modal-title">
                        Sales vs COGS Details - {selectedSalesYear || "Year"}
                      </h5>
                      <button
                        className="btn-close"
                        onClick={() => setSalesDetailsOpen(false)}
                      />
                    </div>

                    <div className="modal-body">
                      <div className="d-flex justify-content-between align-items-center mb-2">
                        <div className="fw-semibold">Detailed Breakdown</div>
                        <Button
                          size="small"
                          variant="outlined"
                          color="primary"
                          startIcon={<TableChartIcon />}
                          onClick={downloadSalesCogsCsv}
                        >
                          CSV
                        </Button>
                      </div>

                      {salesDetailsLoading && (
                        <div className="d-flex align-items-center gap-2">
                          <CircularProgress size={18} />
                          <span>Loading details...</span>
                        </div>
                      )}

                      {!salesDetailsLoading && salesDetailsError && (
                        <div className="text-danger">{salesDetailsError}</div>
                      )}

                      {!salesDetailsLoading && !salesDetailsError && salesDetails.length === 0 && (
                        <div>No details found for this year.</div>
                      )}

                      {!salesDetailsLoading && salesDetails.length > 0 && (
                        <DataTable
                          columns={salesDetailsCols}
                          data={salesDetails}
                          pagination
                          dense
                          striped
                          customStyles={tableCustomStyles}
                        />
                      )}
                    </div>

                    <div className="modal-footer">
                      <button
                        className="btn btn-secondary"
                        onClick={() => setSalesDetailsOpen(false)}
                      >
                        Close
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

        </main>
      </div>

      <Footer />

    </div>
  );
}


