import { useEffect, useMemo, useState } from "react";
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
} from "@mui/material";
import dayjs from "dayjs";
import "./css/Dashboard.css";
import tableCustomStyles from "../components/common/tableStyles";
import API from "../api/api";

import { exportToCSV } from "../utils/exportUtils.jsx";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

const EMPTY_CHART_OPTIONS = {
  chart: {
    toolbar: { show: false },
  },
  grid: {
    padding: {
      left: 10,
      right: 10,
    },
  },
  xaxis: {
    categories: [],
  },
  yaxis: {},
  noData: {
    text: "Loading...",
  },
};

const ensureChartOptions = (options) => ({
  ...EMPTY_CHART_OPTIONS,
  ...(options || {}),
  chart: {
    ...EMPTY_CHART_OPTIONS.chart,
    ...(options?.chart || {}),
  },
  grid: {
    ...EMPTY_CHART_OPTIONS.grid,
    ...(options?.grid || {}),
    padding: {
      ...EMPTY_CHART_OPTIONS.grid.padding,
      ...(options?.grid?.padding || {}),
    },
  },
  xaxis: {
    ...EMPTY_CHART_OPTIONS.xaxis,
    ...(options?.xaxis || {}),
  },
  yaxis: {
    ...EMPTY_CHART_OPTIONS.yaxis,
    ...(options?.yaxis || {}),
  },
  noData: {
    ...EMPTY_CHART_OPTIONS.noData,
    ...(options?.noData || {}),
  },
});

export default function RiskAssessment() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const [taxType, setTaxType] = useState("gst");

  const [tenure, setTenure] = useState("1M");
  const [startDate, setStartDate] = useState(dayjs().startOf("month"));
  const [endDate, setEndDate] = useState(dayjs().endOf("month"));

  const [industryChart, setIndustryChart] = useState({ labels: [], data: [] });
  const [industryLoading, setIndustryLoading] = useState(false);
  const [selectedSector, setSelectedSector] = useState("");
  const [searchText, setSearchText] = useState("");

  const [categoryChart, setCategoryChart] = useState({
    labels: [],
    total_series: [],
    flagged_series: [],
    percent_series: [],
  });

  const [taxpayerRisk, setTaxpayerRisk] = useState({
    labels: [],
    total_series: [],
    flagged_series: [],
  });

  const [anomalyChart, setAnomalyChart] = useState({ labels: [], values: [], series: [] });
  const [anomalyYear, setAnomalyYear] = useState("");
  const [anomalyMonth, setAnomalyMonth] = useState("");
  const [anomalyFilterOptions, setAnomalyFilterOptions] = useState({
    years: [],
    months: [],
  });

  const [topFraud, setTopFraud] = useState([]);

  const BASE_PATH =
    taxType === "gst"
      ? "/risk-assessment"
      : taxType === "swt"
      ? "/risk-assessment"
      : "/risk-assessment";

  const getParams = () => {
    const params = {
      taxtype: taxType,
      range_type: tenure.toUpperCase(),
    };

    if (tenure === "custom" && startDate && endDate) {
      params.start_date = startDate.format("YYYY-MM-DD");
      params.end_date = endDate.format("YYYY-MM-DD");
    }
    return params;
  };

  const getAnomalyParams = () => {
    const params = getParams();

    if (anomalyYear) {
      params.year = anomalyYear;
    }

    if (taxType !== "cit" && anomalyMonth) {
      params.month = anomalyMonth;
    }

    return params;
  };

  const handleTenureChange = (e) => {
    const val = e.target.value;
    setTenure(val);
    const today = dayjs();
    let start, end;

    switch (val) {
      case "1M":
        start = today.subtract(1, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "3M":
        start = today.subtract(3, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "6M":
        start = today.subtract(6, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "1Y":
        start = today.subtract(1, "year").startOf("month");
        end = today.endOf("month");
        break;
      case "custom":
        start = startDate || today.startOf("month");
        end = endDate || today.endOf("month");
        break;
      default:
        return;
    }

    setStartDate(start);
    setEndDate(end);
  };

  const fetchIndustryChart = async () => {
    try {
      setIndustryLoading(true);
      const res = await API.get(BASE_PATH + "/industry", {
        params: getParams(),
      });

      const industries = res.data || [];
      const labels = industries.map((d) => d.sector);

      if (!selectedSector && labels.length > 0) {
        setSelectedSector(labels[0]);
      }

      setIndustryChart({ labels, data: industries });
    } catch (err) {
      console.error("Industry API failed:", err);
    } finally {
      setIndustryLoading(false);
    }
  };

  const fetchRiskData = async () => {
    try {
      const params = getParams();
      const [categoryRes, taxpayerRes, topFraudRes] =
        await Promise.all([
          API.get(BASE_PATH + "/category", { params }),
          API.get(BASE_PATH + "/taxpayer-vs-risk", { params }),
          API.get(BASE_PATH + "/top-fraud-companies", { params }),
        ]);

      const cat = categoryRes?.data || [];
      setCategoryChart({
        labels: cat.map((d) => d.segment_label),
        total_series: cat.map((d) => d.total_records),
        flagged_series: cat.map((d) => d.flagged_records),
        percent_series: cat.map((d) => d.flagged_percentage),
      });

      const tpr = taxpayerRes?.data || {};
      setTaxpayerRisk({
        labels: tpr.labels || [],
        total_series: tpr.total_series || [],
        flagged_series: tpr.flagged_series || [],
      });

      setTopFraud(topFraudRes?.data || []);
    } catch (err) {
      console.error("Error fetching dashboard:", err);
    }
  };

  const fetchAnomalyChart = async () => {
    try {
      const res = await API.get(BASE_PATH + "/frequency-anomalies", {
        params: getAnomalyParams(),
      });
      const anom = res?.data || {};
      setAnomalyChart({
        labels: anom.labels || [],
        values: anom.values || [],
        series: Array.isArray(anom.series)
          ? anom.series
          : (anom.labels || []).length
          ? [{ name: "Risk Anomalies", data: anom.values || [] }]
          : [],
      });
    } catch (err) {
      console.error("Anomaly API failed:", err);
    }
  };

  const fetchAnomalyFilters = async () => {
    try {
      const res = await API.get(BASE_PATH + "/filters", {
        params: getParams(),
      });
      const years = Array.isArray(res?.data?.years) ? res.data.years : [];
      const months = Array.isArray(res?.data?.months) ? res.data.months : [];

      setAnomalyFilterOptions({ years, months });
      setAnomalyYear((current) =>
        current && years.includes(Number(current)) ? current : ""
      );
      setAnomalyMonth((current) => {
        if (taxType === "cit") {
          return "";
        }

        return current && months.includes(Number(current)) ? current : "";
      });
    } catch (err) {
      console.error("Anomaly filters API failed:", err);
      setAnomalyFilterOptions({ years: [], months: [] });
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchRiskData();
      fetchIndustryChart();
      fetchAnomalyChart();
      fetchAnomalyFilters();
    }, 250);

    return () => clearTimeout(timer);
  }, [taxType, tenure, startDate, endDate]);

  useEffect(() => {
    fetchAnomalyChart();
  }, [taxType, anomalyYear, anomalyMonth]);

  const categoryOptions = {
    chart: { type: "bar", toolbar: { show: false } },
    plotOptions: { bar: { borderRadius: 6, dataLabels: { position: "top" } } },
    dataLabels: {
      enabled: true,
      formatter: (val) => (val ? val.toLocaleString() : ""),
      offsetY: -15,
    },
    xaxis: {
      categories: categoryChart.labels,
      labels: { rotate: -45 },
    },
    title: { text: "Risk Breakdown by Category (Segment)" },
    colors: ["#3498DB", "#E74C3C"],
  };

  const selectedIndustry = industryChart.data.find(
    (s) => s.sector === selectedSector
  );
  const industrySeries = selectedIndustry
    ? [
        {
          name: selectedSector,
          data: [
            selectedIndustry.total_taxpayers || 0,
            selectedIndustry.risk_flagged || 0,
          ],
        },
      ]
    : [{ name: "", data: [0, 0] }];

  const industryOptions = {
    chart: { type: "bar", toolbar: { show: false } },
    xaxis: { categories: ["Total Taxpayers", "Risk Flagged"] },
    dataLabels: { enabled: true },
    title: { text: `Sector Risk - ${selectedSector || "-"}` },
    colors: ["#2ECC71", "#E74C3C"],
  };

  const taxpayerOptions = {
    chart: {
      type: "bar",
      toolbar: { show: false },
      zoom: { enabled: false },
    },
    plotOptions: {
      bar: {
        borderRadius: 4,
        columnWidth: "60%",
      },
    },
    dataLabels: { enabled: false },
    xaxis: {
      categories: taxpayerRisk.labels,
      labels: {
        rotate: -45,
        rotateAlways: true,
        hideOverlappingLabels: true,
        trim: true,
        style: {
          fontSize: "10px",
        },
      },
      tickPlacement: "on",
    },
    tooltip: {
      shared: true,
      intersect: false,
    },
    title: {
      text: "Total Taxpayers vs Risk Flagged",
    },
  };

  const safeAnomalyLabels = Array.isArray(anomalyChart.labels)
    ? anomalyChart.labels
    : [];
  const safeAnomalySeries = Array.isArray(anomalyChart.series)
    ? anomalyChart.series
    : [];

  const anomalyDisplayLabels =
    taxType === "cit"
      ? safeAnomalyLabels.map((label) =>
          label === "High Risk Taxpayer"
            ? "High Risk"
            : label === "Normal Taxpayer"
            ? "Normal"
            : label
        )
      : safeAnomalyLabels;

  const anomalyOptions = {
    chart: {
      type: "bar",
      stacked: false,
      toolbar: { show: true },
      zoom: { enabled: true },
      width: taxType === "cit" ? "100%" : undefined,
    },
    plotOptions: {
      bar: {
        borderRadius: 4,
        columnWidth: taxType === "cit" ? "35%" : "60%",
        distributed: taxType === "cit" ? false : undefined,
      },
    },
    dataLabels: { enabled: false },
    xaxis: {
      categories: anomalyDisplayLabels,
      labels: {
        rotate: taxType === "cit" ? -25 : -45,
        rotateAlways: true,
        hideOverlappingLabels: true,
        trim: taxType === "cit",
        maxHeight: taxType === "cit" ? 60 : undefined,
        style: {
          fontSize: "10px",
        },
      },
      tickPlacement: "on",
    },
    tooltip: {
      shared: taxType === "cit" ? false : true,
      intersect: taxType === "cit",
      ...(taxType === "cit"
        ? {
            x: {
              show: false,
            },
            y: {
              formatter: (val, { dataPointIndex }) =>
                `${anomalyDisplayLabels[dataPointIndex] || ""}: ${val}`,
            },
          }
        : {}),
    },
    legend: {
      show: true,
      position: "top",
    },
    grid:
      taxType === "cit"
        ? {
            padding: {
              left: 10,
              right: 10,
            },
          }
        : undefined,
    title: { text: "Frequency of Risk Anomalies" },
  };

  const hasSeriesData = (series) =>
    Array.isArray(series) &&
    series.length > 0 &&
    series.some((s) => Array.isArray(s.data) && s.data.some((v) => v > 0));

  const categorySeries = [
    { name: "Total Records", data: categoryChart.total_series },
    { name: "Flagged Records", data: categoryChart.flagged_series },
  ];
  const taxpayerSeries = [
    { name: "Total Taxpayers", data: taxpayerRisk.total_series },
    { name: "Risk Flagged", data: taxpayerRisk.flagged_series },
  ];
  const anomalySeriesForCheck = safeAnomalySeries;
  const anomalyChartKey = useMemo(() => {
    if (taxType !== "cit") {
      return `anomaly-${taxType}-${anomalyYear || "all"}-${anomalyMonth || "all"}`;
    }

    return `cit-${anomalyYear || "all"}`;
  }, [taxType, anomalyYear, anomalyMonth]);

  const hasCategoryData = hasSeriesData(categorySeries);
  const hasTaxpayerData = hasSeriesData(taxpayerSeries);
  const hasAnomalyData = hasSeriesData(anomalySeriesForCheck);
  const hasIndustryData = hasSeriesData(industrySeries);
  const safeCategorySeries = Array.isArray(categorySeries) ? categorySeries : [];
  const safeTaxpayerSeries = Array.isArray(taxpayerSeries) ? taxpayerSeries : [];
  const safeIndustrySeries = Array.isArray(industrySeries) ? industrySeries : [];
  const safeCategoryOptions = ensureChartOptions(categoryOptions);
  const safeTaxpayerOptions = ensureChartOptions(taxpayerOptions);
  const safeIndustryOptions = ensureChartOptions(industryOptions);
  const safeAnomalyOptions = ensureChartOptions(anomalyOptions);

  const filteredData = topFraud.filter((row) => {
    const term = searchText.toLowerCase();
    return (
      row.taxpayer_name?.toLowerCase().includes(term) ||
      row.total_sales?.toString().toLowerCase().includes(term) ||
      row.total_flags?.toString().toLowerCase().includes(term) ||
      row.tin?.toLowerCase().includes(term) ||
      row.tin_number?.toLowerCase().includes(term)
    );
  });

  const columns = [
    { name: "Tin", selector: (r) => r.tin || r.tin_number || "-", sortable: true },
    { name: "Taxpayer Name", selector: (r) => r.taxpayer_name || "-", sortable: true },
    {
      name: "Total Sales (K)",
      selector: (r) => (r.total_sales ? r.total_sales.toLocaleString() : "0"),
      sortable: true,
      right: true,
    },
    { name: "Total Flags", selector: (r) => r.total_flags ?? 0, sortable: true, right: true },
  ];

  const normalizeTin = (row) => {
    const rawTin = row?.tin || row?.tin_number || "";
    return typeof rawTin === "string" && rawTin.startsWith("<Route") ? "" : rawTin;
  };
  const normalizeTaxpayerName = (row) =>
    row?.taxpayer_name || row?.taxpayer || "Unknown";

  const handleDownloadRiskAByCategoryCSV = async () => {
    try {
      const res = await API.get("/risk-assessment/download-segment-risk", {
        params: getParams(),
      });

      const rows = res.data?.rows || [];
      const csvData = rows.map((r) => ({
        tin: normalizeTin(r),
        taxpayer_name: normalizeTaxpayerName(r),
        segment: r.segment,
        tax_period_year: r.tax_period_year,
        tax_period_month: r.tax_period_month,
      }));
      const csvColumns = [
        "tin",
        "taxpayer_name",
        "segment",
        "tax_period_year",
        "tax_period_month",
      ];

      exportToCSV(csvData, `risk_segments_${taxType}`, csvColumns);
    } catch (e) {
      console.error("Error:", e);
      alert("CSV Export Failed");
    }
  };

  const handleDownloadIndustryCSV = async () => {
    try {
      const res = await API.get("/risk-assessment/download-industry", {
        params: getParams(),
      });

      const rows = res.data?.rows || [];
      const csvData = rows.map((r) => ({
        tin: normalizeTin(r),
        taxpayer_name: normalizeTaxpayerName(r),
        sector: r.sector,
        total_sales: r.total_sales,
        flagged: r.flagged,
      }));
      const csvColumns = ["tin", "taxpayer_name", "sector", "total_sales", "flagged"];

      exportToCSV(csvData, `industry_risk_${taxType}`, csvColumns);
    } catch (e) {
      console.error(e);
      alert("Export Failed");
    }
  };

  const handleDownloadTaxpayerCSV = async () => {
    try {
      const res = await API.get("/risk-assessment/download-taxpayer-vs-risk", {
        params: getParams(),
      });

      const rows = res.data?.rows || [];
      const csvData = rows.map((r) => ({
        tin: normalizeTin(r),
        taxpayer_name: normalizeTaxpayerName(r),
        tax_year: r.tax_period_year,
        tax_month: r.tax_period_month,
        is_flag: r.flagged,
      }));
      const csvColumns = ["tin", "taxpayer_name", "tax_year", "tax_month", "is_flag"];

      exportToCSV(csvData, `taxpayer_risk_${taxType}`, csvColumns);
    } catch (e) {
      alert("Export Failed");
    }
  };

  const handleDownloadAnomaliesCSV = async () => {
    try {
      const res = await API.get("/risk-assessment/download-frequency-anomalies", {
        params: getParams(),
      });

      const rows = res.data?.rows || [];
      const csvData =
        taxType === "gst"
          ? rows.map((r) => ({
              tin: normalizeTin(r),
              taxpayer_name: normalizeTaxpayerName(r),
              tax_year: r.tax_period_year,
              tax_month: r.tax_period_month,
              exempt_sales: r.exempt_sales,
              total_sales_income: r.total_sales_income,
              gst_payable: r.gst_payable,
              excessive_exempt_sales_flag: r.excessive_exempt_sales_flag,
              suspiciously_low_output_flag: r.suspiciously_low_output_flag,
            }))
          : rows.map((r) => ({
              tin: normalizeTin(r),
              taxpayer_name: normalizeTaxpayerName(r),
              tax_year: r.tax_period_year,
              tax_month: r.tax_period_month,
              employees_paid_swt: r.employees_paid_swt,
              employees_on_payroll: r.employees_on_payroll,
              total_swt_tax_deducted: r.total_swt_tax_deducted,
              total_salary_wages_paid: r.total_salary_wages_paid,
              ghost_employee_flag: r.ghost_employee_flag,
              excessive_tax_flag: r.excessive_tax_flag,
            }));
      const csvColumns =
        taxType === "gst"
          ? [
              "tin",
              "taxpayer_name",
              "tax_year",
              "tax_month",
              "exempt_sales",
              "total_sales_income",
              "gst_payable",
              "excessive_exempt_sales_flag",
              "suspiciously_low_output_flag",
            ]
          : [
              "tin",
              "taxpayer_name",
              "tax_year",
              "tax_month",
              "employees_paid_swt",
              "employees_on_payroll",
              "total_swt_tax_deducted",
              "total_salary_wages_paid",
              "ghost_employee_flag",
              "excessive_tax_flag",
            ];

      exportToCSV(csvData, `anomalies_${taxType}`, csvColumns);
    } catch (e) {
      console.error("Export Failed", e);
      alert("Export Failed");
    }
  };

  const handleDownloadTopFraudCSV = async () => {
    try {
      const res = await API.get("/risk-assessment/download-top-fraud-companies", {
        params: getParams(),
      });

      const rows = res.data?.rows || [];
      const csvData = rows.map((r) => ({
        tin: normalizeTin(r),
        taxpayer_name: normalizeTaxpayerName(r),
        tax_year: r.tax_period_year,
        tax_month: r.tax_period_month,
        total_sales: r.total_sales,
        is_flag: r.is_flag,
      }));
      const csvColumns = [
        "tin",
        "taxpayer_name",
        "tax_year",
        "tax_month",
        "total_sales",
        "is_flag",
      ];

      exportToCSV(csvData, `r_companies_${taxType}`, csvColumns);
    } catch (e) {
      console.error(e);
      alert("Export Failed");
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

          <main className="main-content mt-5 risk-assessment-page">
            <div className="container-fluid">
              <div className="header-title-page mb-3">Risk Assessment Dashboard</div>

              <div className="row risk-filter-area align-items-center mb-4">
                <div className="col-md-3 pb-3">
                  <FormControl fullWidth size="small">
                    <InputLabel id="tax-label">Select Tax Type</InputLabel>
                    <Select
                      labelId="tax-label"
                      value={taxType}
                      label="Select Tax Type"
                      onChange={(e) => setTaxType(e.target.value)}
                    >
                      <MenuItem value="gst">GST</MenuItem>
                      <MenuItem value="swt">SWT</MenuItem>
                      <MenuItem value="cit">CIT</MenuItem>
                    </Select>
                  </FormControl>
                </div>

                <div className="col-md-3 pb-3">
                  <FormControl fullWidth size="small">
                    <InputLabel id="tenure-label">Select Tenure</InputLabel>
                    <Select
                      labelId="tenure-label"
                      value={tenure}
                      label="Select Tenure"
                      onChange={handleTenureChange}
                    >
                      <MenuItem value="1M">Past 1 Month</MenuItem>
                      <MenuItem value="3M">Past 3 Months</MenuItem>
                      <MenuItem value="6M">Past 6 Months</MenuItem>
                      <MenuItem value="1Y">Past 1 Year</MenuItem>
                      <MenuItem value="custom">Custom Date</MenuItem>
                    </Select>
                  </FormControl>
                </div>

                <div className="col-md-6 pb-3 d-flex justify-content-md-end gap-2 mt-md-0">
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
                            fullWidth: true,
                            size: "small",
                            inputProps: {
                              readOnly: true
                            }
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

              <div className="row dashboard-row">
                <div className="col-lg-6 col-md-12 mb-4 dashboard-card-col">
                  <div className="card dashboard-card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Risk Breakdown by Category (Segment)</span>
                      <button
                        className="btn btn-success btn-sm d-flex align-items-center gap-1"
                        onClick={handleDownloadRiskAByCategoryCSV}
                      >
                        <i className="fa fa-download"></i> Download CSV
                      </button>
                    </div>
                    <div className="card-body">
                      {hasCategoryData ? (
                        safeCategoryOptions ? (
                          <Chart
                            options={safeCategoryOptions}
                            series={safeCategorySeries}
                            type="bar"
                            height={400}
                          />
                        ) : null
                      ) : (
                        <div className="no-data-message">There are no records to display</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="col-lg-6 col-md-12 mb-4 dashboard-card-col">
                  <div className="card dashboard-card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Sector-based Risk (By Industry)</span>
                      <button
                        className="btn btn-success btn-sm d-flex align-items-center gap-1"
                        onClick={handleDownloadIndustryCSV}
                      >
                        <i className="fa fa-download"></i> Download CSV
                      </button>
                    </div>

                    <div className="card-body">
                      <div className="d-flex justify-content-end mb-2">
                        <FormControl size="small" style={{ width: "250px" }}>
                          <InputLabel id="sector-label">Select Sector</InputLabel>
                          <Select
                            labelId="sector-label"
                            label="Select Sector"
                            value={selectedSector}
                            onChange={(e) => setSelectedSector(e.target.value)}
                          >
                            {industryChart.labels.map((sector, i) => (
                              <MenuItem key={i} value={sector}>
                                {sector}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      </div>
                      {hasIndustryData ? (
                        safeIndustryOptions ? (
                          <Chart
                            options={safeIndustryOptions}
                            series={safeIndustrySeries}
                            type="bar"
                            height={350}
                          />
                        ) : null
                      ) : (
                        <div className="no-data-message">There are no records to display</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="col-lg-6 col-md-6 mb-4 dashboard-card-col">
                  <div className="card dashboard-card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Total Taxpayers vs Risk Flagged</span>
                      <button
                        className="btn btn-success btn-sm d-flex align-items-center gap-1"
                        onClick={handleDownloadTaxpayerCSV}
                      >
                        <i className="fa fa-download"></i> Download CSV
                      </button>
                    </div>
                    <div className="card-body" style={{ overflowX: "auto" }}>
                      {hasTaxpayerData ? (
                        <div style={{ minWidth: `${taxpayerRisk.labels.length * 60}px` }}>
                          {safeTaxpayerOptions ? (
                            <Chart
                              options={safeTaxpayerOptions}
                              series={safeTaxpayerSeries}
                              type="bar"
                              height={350}
                            />
                          ) : null}
                        </div>
                      ) : (
                        <div className="no-data-message">There are no records to display</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="col-lg-6 col-md-6 mb-4 dashboard-card-col">
                  <div className="card dashboard-card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Frequency of Risk Anomalies</span>
                      <button
                        className="btn btn-success btn-sm d-flex align-items-center gap-1"
                        onClick={handleDownloadAnomaliesCSV}
                      >
                        <i className="fa fa-download"></i> Download CSV
                      </button>
                    </div>
                    <div className="card-body">
                      {taxType === "cit" ? (
                        <div className="d-flex flex-wrap gap-2 mb-3">
                          <FormControl size="small" style={{ minWidth: "160px" }}>
                            <InputLabel id="anomaly-year-label">Select Year</InputLabel>
                            <Select
                              labelId="anomaly-year-label"
                              label="Select Year"
                              value={anomalyYear}
                              onChange={(e) => setAnomalyYear(e.target.value)}
                            >
                              <MenuItem value="">Any</MenuItem>
                              {anomalyFilterOptions.years.map((year) => (
                                <MenuItem key={year} value={String(year)}>
                                  {year}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </div>
                      ) : (
                        <div className="d-flex flex-wrap gap-2 mb-3">
                          <FormControl size="small" style={{ minWidth: "160px" }}>
                            <InputLabel id="anomaly-year-label">Select Year</InputLabel>
                            <Select
                              labelId="anomaly-year-label"
                              label="Select Year"
                              value={anomalyYear}
                              onChange={(e) => setAnomalyYear(e.target.value)}
                            >
                              <MenuItem value="">Any</MenuItem>
                              {anomalyFilterOptions.years.map((year) => (
                                <MenuItem key={year} value={String(year)}>
                                  {year}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>

                          <FormControl size="small" style={{ minWidth: "160px" }}>
                            <InputLabel id="anomaly-month-label">Select Month</InputLabel>
                            <Select
                              labelId="anomaly-month-label"
                              label="Select Month"
                              value={anomalyMonth}
                              onChange={(e) => setAnomalyMonth(e.target.value)}
                            >
                              <MenuItem value="">Any</MenuItem>
                              {anomalyFilterOptions.months.map((month) => (
                                <MenuItem key={month} value={String(month)}>
                                  {month}
                                </MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </div>
                      )}
                      {hasAnomalyData && safeAnomalySeries.length > 0 ? (
                        safeAnomalyOptions ? (
                          <Chart
                            key={anomalyChartKey}
                            options={safeAnomalyOptions}
                            series={safeAnomalySeries}
                            type="bar"
                            height={350}
                            width="100%"
                          />
                        ) : null
                      ) : (
                        <div className="no-data-message">There are no records to display</div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="col-md-12 mb-4">
                  <Paper className="p-3">
                    <div className="card-header d-flex justify-content-between align-items-center mb-3">
                      <span>Top High Risk Assessment Companies</span>
                      <button
                        className="btn btn-success btn-sm d-flex align-items-center gap-1"
                        onClick={handleDownloadTopFraudCSV}
                      >
                        <i className="fa fa-download"></i> Download CSV
                      </button>
                    </div>
                    <div className="d-flex justify-content-end mb-3">
                      <TextField
                        size="small"
                        placeholder="Search..."
                        variant="outlined"
                        onChange={(e) => setSearchText(e.target.value)}
                        value={searchText}
                        style={{ width: "250px" }}
                      />
                    </div>
                    <DataTable
                      columns={columns}
                      data={filteredData}
                      customStyles={tableCustomStyles}
                      pagination
                      paginationPerPage={5}
                      highlightOnHover
                      striped
                      dense
                    />
                  </Paper>
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
