import { useEffect, useState } from "react";
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
  Grid,
  Card,
  CardContent,
  Typography,
  Skeleton,
  Box,
} from "@mui/material";
import dayjs from "dayjs";
import "./css/Dashboard.css";
import tableCustomStyles from "../components/common/tableStyles";
import API from "../api/api";
import { exportToCSV } from "../utils/exportUtils.jsx";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

export default function Compliance() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [taxType, setTaxType] = useState("gst");
  const [tenure, setTenure] = useState("3M");
  const [startDate, setStartDate] = useState(dayjs().subtract(2, "month").startOf("month"));
  const [endDate, setEndDate] = useState(dayjs());
  const [searchText, setSearchText] = useState("");
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [loading, setLoading] = useState(true);

  // State for different chart data
  const [taxFilingData, setTaxFilingData] = useState([]);
  const [timelinessData, setTimelinessData] = useState([]);
  const [profitabilityData, setProfitabilityData] = useState([]);
  const [industryKpiData, setIndustryKpiData] = useState([]);
  const [kpiMetrics, setKpiMetrics] = useState({
    total_taxpayers: 0,
    filed: 0,
    delayed: 0,
    on_time: 0,
    profit: 0,
    loss: 0,
    filing_rate: 0,
    non_filing_rate: 0,
    delay_rate: 0,
    on_time_rate: 0,
    profitability_rate: 0,
    loss_rate: 0,
  });

  const BASE_PATH = "/compliance";

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

  const handleTenureChange = (e) => {
    const val = e.target.value;
    setTenure(val);
    const today = dayjs();
    let start, end;

    switch (val) {
      case "1M":
        start = today.subtract(1, "month").startOf("month");
        end = today;
        break;
      case "3M":
        start = today.subtract(2, "month").startOf("month");
        end = today;
        break;
      case "6M":
        start = today.subtract(5, "month").startOf("month");
        end = today;
        break;
      case "1Y":
        start = today.subtract(1, "year").startOf("month");
        end = today;
        break;
      case "custom":
        start = startDate || today.subtract(2, "month").startOf("month");
        end = endDate || today;
        break;
      default:
        return;
    }

    setStartDate(start);
    setEndDate(end);
  };

  // Calculate KPIs from available data
  const calculateKPIs = (filingData, timelinessData, profitabilityData) => {
    // Calculate total taxpayers and filing rates from tax filing data
    const totalTaxpayers = filingData.reduce(
      (sum, item) => sum + ((parseInt(item.filed_taxpayers) || 0) + (parseInt(item.non_filers) || 0)),
      0
    );
    const totalFiled = filingData.reduce((sum, item) => sum + (parseInt(item.filed_taxpayers) || 0), 0);
    
    // Calculate timeliness metrics
    const totalDelayed = timelinessData.reduce((sum, item) => sum + (parseInt(item.delay) || 0), 0);
    const totalOnTime = timelinessData.reduce((sum, item) => sum + (parseInt(item.on_time) || 0), 0);
    
    // Calculate profitability metrics
    const totalProfit = profitabilityData.reduce((sum, item) => sum + (parseInt(item.profit) || 0), 0);
    const totalLoss = profitabilityData.reduce((sum, item) => sum + (parseInt(item.loss) || 0), 0);
    
    const filingRate = totalTaxpayers > 0 ? totalFiled / totalTaxpayers : 0;
    const nonFilingRate = 1 - filingRate;
    
    const totalReturns = totalDelayed + totalOnTime;
    const delayRate = totalReturns > 0 ? totalDelayed / totalReturns : 0;
    const onTimeRate = totalReturns > 0 ? totalOnTime / totalReturns : 0;
    
    const totalProfitLoss = totalProfit + totalLoss;
    const profitabilityRate = totalProfitLoss > 0 ? totalProfit / totalProfitLoss : 0;
    const lossRate = totalProfitLoss > 0 ? totalLoss / totalProfitLoss : 0;
    
    return {
      total_taxpayers: totalTaxpayers,
      filed: totalFiled,
      delayed: totalDelayed,
      on_time: totalOnTime,
      profit: totalProfit,
      loss: totalLoss,
      filing_rate: filingRate,
      non_filing_rate: nonFilingRate,
      delay_rate: delayRate,
      on_time_rate: onTimeRate,
      profitability_rate: profitabilityRate,
      loss_rate: lossRate,
    };
  };

  // Fetch all compliance data
  const fetchComplianceData = async () => {
    setLoading(true);
    try {
      const params = getParams();
      
      const [
        taxFilingRes,
        timelinessRes,
        profitabilityRes,
        industryKpiRes,
      ] = await Promise.allSettled([
        API.get(BASE_PATH + "/tax-filing", { params }),
        API.get(BASE_PATH + "/timeliness", { params }),
        API.get(BASE_PATH + "/profitability", { params }),
        API.get(BASE_PATH + "/industry-kpi", { params }),
      ]);

      // Process Tax Filing Data
      let filingData = [];
      if (taxFilingRes.status === "fulfilled" && taxFilingRes.value?.data?.success) {
        filingData = taxFilingRes.value.data.data || [];
      }
      setTaxFilingData(filingData);

      // Process Timeliness Data
      let timelinessData = [];
      if (timelinessRes.status === "fulfilled" && timelinessRes.value?.data?.success) {
        timelinessData = timelinessRes.value.data.data || [];
      }
      setTimelinessData(timelinessData);

      // Process Profitability Data
      let profitabilityData = [];
      if (profitabilityRes.status === "fulfilled" && profitabilityRes.value?.data?.success) {
        profitabilityData = profitabilityRes.value.data.data || [];
      }
      setProfitabilityData(profitabilityData);

      // Process Industry KPI Data
      let industryData = [];
      if (industryKpiRes.status === "fulfilled" && industryKpiRes.value?.data?.success) {
        industryData = industryKpiRes.value.data.data || [];
      }
      setIndustryKpiData(industryData);

      // Calculate KPIs from the fetched data
      const kpis = calculateKPIs(filingData, timelinessData, profitabilityData);
      setKpiMetrics(kpis);

      // Set default selected industry
      if (industryData.length > 0 && !selectedIndustry) {
        setSelectedIndustry(industryData[0].industry);
      }

    } catch (err) {
      console.error("Error fetching compliance data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchComplianceData();
  }, [taxType, tenure, startDate, endDate]);

  // Prepare chart configurations
  const taxFilingOptions = {
    chart: {
      type: "bar",
      toolbar: { show: false },
      stacked: true,
    },
    plotOptions: {
      bar: {
        horizontal: false,
        borderRadius: 6,
        columnWidth: "70%",
      },
    },
    dataLabels: { enabled: false },
    xaxis: {
      categories: taxFilingData.map((item) => item.enterpriseactivity || "Unknown"),
      labels: { rotate: -45, style: { fontSize: "11px" } },
    },
    yaxis: {
      title: { text: "Number of Taxpayers" },
    },
    title: {
      text: "Tax Filing vs Non-Filing by Industry",
      align: "center",
    },
    tooltip: {
      y: {
        formatter: (val) => val?.toLocaleString() || "0",
      },
    },
    colors: ["#2ECC71", "#E74C3C"],
    legend: {
      position: "top",
    },
  };

  const taxFilingSeries = [
    { 
      name: "Filed Taxpayers", 
      data: taxFilingData.map((item) => parseInt(item.filed_taxpayers) || 0) 
    },
    { 
      name: "Non-Filers", 
      data: taxFilingData.map((item) => parseInt(item.non_filers) || 0) 
    },
  ];

  const timelinessOptions = {
    chart: {
      type: "bar",
      toolbar: { show: false },
      stacked: true,
    },
    plotOptions: {
      bar: {
        horizontal: false,
        borderRadius: 6,
        columnWidth: "70%",
      },
    },
    dataLabels: { enabled: false },
    xaxis: {
      categories: timelinessData.length > 0 
        ? timelinessData.map((item) => item.segment_label || "Unknown")
        : ["No Data"],
      labels: { rotate: -45, style: { fontSize: "11px" } },
    },
    yaxis: {
      title: { text: "Number of Returns" },
    },
    title: {
      text: "Delayed vs On-Time Returns by Segment",
      align: "center",
    },
    colors: ["#F39C12", "#3498DB"],
    legend: {
      position: "top",
    },
  };

  const timelinessSeries = [
    { name: "Delayed", data: timelinessData.map((item) => parseInt(item.delay) || 0) },
    { name: "On-Time", data: timelinessData.map((item) => parseInt(item.on_time) || 0) },
  ];

  const profitabilityOptions = {
    chart: {
      type: "bar",
      toolbar: { show: false },
      stacked: true,
    },
    plotOptions: {
      bar: {
        horizontal: false,
        borderRadius: 6,
        columnWidth: "70%",
      },
    },
    dataLabels: { enabled: false },
    xaxis: {
      categories: profitabilityData.map((item) => item.segment_label || "Unknown"),
      labels: { rotate: -45, style: { fontSize: "11px" } },
    },
    yaxis: {
      title: { text: "Number of Taxpayers" },
    },
    title: {
      text: "Profit vs Loss by Segment",
      align: "center",
    },
    colors: ["#27AE60", "#E74C3C"],
    legend: {
      position: "top",
    },
  };

  const profitabilitySeries = [
    { name: "Profit", data: profitabilityData.map((item) => parseInt(item.profit) || 0) },
    { name: "Loss", data: profitabilityData.map((item) => parseInt(item.loss) || 0) },
  ];

  // Industry KPI - Selected Industry Details
  const selectedIndustryData = industryKpiData.find(
    (item) => item.industry === selectedIndustry
  );

  const hasChartData = (series) => {
    return series.some(s => s.data.some(v => v > 0));
  };

  const chartSkeleton = (height) => (
    <Box>
      <Skeleton variant="text" width="40%" height={32} />
      <Skeleton variant="rectangular" height={height} sx={{ borderRadius: 2 }} />
    </Box>
  );

  // Table columns for detailed views
  const filingColumns = [
    { name: "Industry", selector: (r) => r.enterpriseactivity || "-", sortable: true },
    { name: "Filed Taxpayers", selector: (r) => (parseInt(r.filed_taxpayers) || 0).toLocaleString(), sortable: true, right: true },
    { name: "Non-Filers", selector: (r) => (parseInt(r.non_filers) || 0).toLocaleString(), sortable: true, right: true },
    { 
      name: "Filing Rate", 
      selector: (r) => {
        const filed = parseInt(r.filed_taxpayers) || 0;
        const nonFilers = parseInt(r.non_filers) || 0;
        const total = filed + nonFilers;
        return total > 0 ? ((filed / total) * 100).toFixed(2) + "%" : "0%";
      }, 
      sortable: true, 
      right: true 
    },
  ];

  const timelinessColumns = [
    { name: "Segment", selector: (r) => r.segment_label || "-", sortable: true },
    { name: "Delayed Returns", selector: (r) => parseInt(r.delay)?.toLocaleString() || "0", sortable: true, right: true },
    { name: "On-Time Returns", selector: (r) => parseInt(r.on_time)?.toLocaleString() || "0", sortable: true, right: true },
    { 
      name: "Total Returns", 
      selector: (r) => ((parseInt(r.delay) || 0) + (parseInt(r.on_time) || 0)).toLocaleString(), 
      sortable: true, 
      right: true 
    },
    { 
      name: "Delay Rate", 
      selector: (r) => {
        const total = (parseInt(r.delay) || 0) + (parseInt(r.on_time) || 0);
        return total > 0 ? (((parseInt(r.delay) || 0) / total) * 100).toFixed(2) + "%" : "0%";
      }, 
      sortable: true, 
      right: true 
    },
  ];

  const profitabilityColumns = [
    { name: "Segment", selector: (r) => r.segment_label || "-", sortable: true },
    { name: "Profit", selector: (r) => parseInt(r.profit)?.toLocaleString() || "0", sortable: true, right: true },
    { name: "Loss", selector: (r) => parseInt(r.loss)?.toLocaleString() || "0", sortable: true, right: true },
    { 
      name: "Total", 
      selector: (r) => ((parseInt(r.profit) || 0) + (parseInt(r.loss) || 0)).toLocaleString(), 
      sortable: true, 
      right: true 
    },
    { 
      name: "Profitability Rate", 
      selector: (r) => {
        const total = (parseInt(r.profit) || 0) + (parseInt(r.loss) || 0);
        return total > 0 ? (((parseInt(r.profit) || 0) / total) * 100).toFixed(2) + "%" : "0%";
      }, 
      sortable: true, 
      right: true 
    },
  ];

  // Filter functions for tables
  const filterFilingData = () => {
    return taxFilingData.filter(row => 
      row.enterpriseactivity?.toLowerCase().includes(searchText.toLowerCase())
    );
  };

  const filterTimelinessData = () => {
    return timelinessData.filter(row => 
      row.segment_label?.toLowerCase().includes(searchText.toLowerCase())
    );
  };

  const filterProfitabilityData = () => {
    return profitabilityData.filter(row => 
      row.segment_label?.toLowerCase().includes(searchText.toLowerCase())
    );
  };

  // Export handlers
  const handleExport = async (endpoint, filename) => {
    try {
      const params = getParams();
      let dataToExport = [];
      
      switch(endpoint) {
        case "/tax-filing":
          dataToExport = taxFilingData;
          break;
        case "/timeliness":
          dataToExport = timelinessData;
          break;
        case "/profitability":
          dataToExport = profitabilityData;
          break;
        case "/industry-kpi":
          dataToExport = industryKpiData;
          break;
        default:
          const res = await API.get(BASE_PATH + endpoint, { params });
          dataToExport = res.data?.data || [];
      }
      
      if (dataToExport.length > 0) {
        const columns = Object.keys(dataToExport[0]);
        exportToCSV(dataToExport, `${filename}_${taxType}`, columns);
      } else {
        alert("No data to export");
      }
    } catch (e) {
      console.error("Export failed:", e);
      alert("Export Failed");
    }
  };

  // KPI Cards Component
  const KPICards = () => {
    const totalNonFilers = taxFilingData.reduce((sum, item) => sum + (parseInt(item.non_filers) || 0), 0);
    const cards = [
      {
        title: "Filing Rate",
        value: `${(kpiMetrics.filing_rate * 100).toFixed(2)}%`,
        subtitle: `${kpiMetrics.filed.toLocaleString()} / ${kpiMetrics.total_taxpayers.toLocaleString()} taxpayers`,
        color: "#2ECC71",
      },
      {
        title: "Non-Filing Rate",
        value: `${(kpiMetrics.non_filing_rate * 100).toFixed(2)}%`,
        subtitle: `${totalNonFilers.toLocaleString()} taxpayers`,
        color: "#E74C3C",
      },
      {
        title: "Delay Rate",
        value: `${(kpiMetrics.delay_rate * 100).toFixed(2)}%`,
        subtitle: `${kpiMetrics.delayed.toLocaleString()} / ${(kpiMetrics.delayed + kpiMetrics.on_time).toLocaleString()} returns`,
        color: "#F39C12",
      },
      {
        title: "On-Time Rate",
        value: `${(kpiMetrics.on_time_rate * 100).toFixed(2)}%`,
        subtitle: `${kpiMetrics.on_time.toLocaleString()} returns`,
        color: "#3498DB",
      },
    ];

    const showProfitability = taxType === "cit" && (parseFloat(kpiMetrics.profitability_rate) || 0) > 0;
    if (showProfitability) {
      cards.push({
        title: "Profitability Rate",
        value: `${(kpiMetrics.profitability_rate * 100).toFixed(2)}%`,
        subtitle: `${kpiMetrics.profit.toLocaleString()} profitable taxpayers`,
        color: "#27AE60",
      });
    }

    return (
      <div className={`row g-3 mb-4 row-cols-1 row-cols-sm-2 row-cols-md-4 row-cols-lg-${cards.length}`}>
        {cards.map((card, idx) => (
          <div className="col" key={idx}>
            <Card
              className="h-100"
              sx={{ backgroundColor: card.color + "15", borderLeft: `4px solid ${card.color}` }}
            >
              <CardContent>
                <Typography variant="subtitle2" color="textSecondary" gutterBottom>
                  {card.title}
                </Typography>
                {loading ? (
                  <>
                    <Skeleton variant="text" width="60%" height={40} />
                    <Skeleton variant="text" width="80%" height={20} />
                  </>
                ) : (
                  <>
                    <Typography variant="h4" component="div" sx={{ fontWeight: "bold", color: card.color }}>
                      {card.value}
                    </Typography>
                    <Typography variant="caption" color="textSecondary">
                      {card.subtitle}
                    </Typography>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        ))}
      </div>
    );
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

          <main className="main-content mt-5 compliance-page">
            <div className="container-fluid">
              <div className="header-title-page mb-3">Compliance Dashboard</div>

              {/* FILTERS SECTION */}
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
                          setStartDate(newValue);
                        }}
                        slotProps={{
                          textField: { fullWidth: true, size: "small", inputProps: { readOnly: true } }
                        }}
                      />
                      <DatePicker
                        label="End Date"
                        format="DD/MM/YYYY"
                        value={endDate}
                        onChange={(newValue) => {
                          if (!newValue || !newValue.isValid()) return;
                          setEndDate(newValue);
                        }}
                        slotProps={{
                          textField: { fullWidth: true, size: "small", inputProps: { readOnly: true } }
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

              {/* KPI Cards */}
              <KPICards />

              {/* Charts Section */}
              <div className="row dashboard-row">
                {/* Tax Filing Chart */}
                <div className="col-lg-6 col-md-12 mb-4 dashboard-card-col">
                  <div className="card dashboard-card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Tax Filing vs Non-Filing by Industry</span>
                      <button
                        className="btn btn-success btn-sm d-flex align-items-center gap-1"
                        onClick={() => handleExport("/tax-filing", "tax_filing")}
                      >
                        <i className="fa fa-download"></i> Download CSV
                      </button>
                    </div>
                    <div className="card-body">
                      {loading ? (
                        chartSkeleton(400)
                      ) : taxFilingData.length > 0 && hasChartData(taxFilingSeries) ? (
                        <Chart
                          options={taxFilingOptions}
                          series={taxFilingSeries}
                          type="bar"
                          height={400}
                        />
                      ) : (
                        <div className="no-data-message">No tax filing data available for the selected criteria</div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Timeliness Chart */}
                <div className="col-lg-6 col-md-12 mb-4 dashboard-card-col">
                  <div className="card dashboard-card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Delayed vs On-Time Returns</span>
                      <button
                        className="btn btn-success btn-sm d-flex align-items-center gap-1"
                        onClick={() => handleExport("/timeliness", "timeliness")}
                      >
                        <i className="fa fa-download"></i> Download CSV
                      </button>
                    </div>
                    <div className="card-body">
                      {loading ? (
                        chartSkeleton(400)
                      ) : timelinessData.length > 0 && hasChartData(timelinessSeries) ? (
                        <Chart
                          options={timelinessOptions}
                          series={timelinessSeries}
                          type="bar"
                          height={400}
                        />
                      ) : (
                        <div className="no-data-message">No timeliness data available for the selected criteria</div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Profitability Chart (CIT only) */}
                {taxType === "cit" && (loading || (parseFloat(kpiMetrics.profitability_rate) || 0) > 0) && (
                  <div className="col-lg-6 col-md-12 mb-4 dashboard-card-col">
                    <div className="card dashboard-card">
                      <div className="card-header d-flex justify-content-between align-items-center">
                        <span>Profit vs Loss by Segment</span>
                        <button
                          className="btn btn-success btn-sm d-flex align-items-center gap-1"
                          onClick={() => handleExport("/profitability", "profitability")}
                        >
                          <i className="fa fa-download"></i> Download CSV
                        </button>
                      </div>
                      <div className="card-body">
                        {loading ? (
                          chartSkeleton(400)
                        ) : profitabilityData.length > 0 && hasChartData(profitabilitySeries) ? (
                          <Chart
                            options={profitabilityOptions}
                            series={profitabilitySeries}
                            type="bar"
                            height={400}
                          />
                        ) : (
                          <div className="no-data-message">No profitability data available for the selected criteria</div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Industry KPI Details */}
                <div className="col-lg-6 col-md-12 mb-4 dashboard-card-col">
                  <div className="card dashboard-card">
                    <div className="card-header">
                      <span>Industry Compliance KPIs</span>
                    </div>
                    <div className="card-body">
                      <div className="d-flex justify-content-end mb-3">
                        <FormControl size="small" style={{ width: "250px" }}>
                          <InputLabel id="industry-label">Select Industry</InputLabel>
                          <Select
                            labelId="industry-label"
                            label="Select Industry"
                            value={selectedIndustry}
                            onChange={(e) => setSelectedIndustry(e.target.value)}
                          >
                            {industryKpiData.map((item, idx) => (
                              <MenuItem key={idx} value={item.industry}>
                                {item.industry}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      </div>
                      {loading ? (
                        chartSkeleton(210)
                      ) : selectedIndustryData ? (
                        <div>
                          <Grid container spacing={2}>
                            <Grid item xs={6}>
                              <Typography variant="subtitle2" color="textSecondary">
                                Total Taxpayers
                              </Typography>
                              <Typography variant="h6">
                                {(parseInt(selectedIndustryData.total_taxpayers) || 0).toLocaleString()}
                              </Typography>
                            </Grid>
                            <Grid item xs={6}>
                              <Typography variant="subtitle2" color="textSecondary">
                                Filed Records
                              </Typography>
                              <Typography variant="h6">
                                {(parseInt(selectedIndustryData.filed_records) || 0).toLocaleString()}
                              </Typography>
                            </Grid>
                            <Grid item xs={6}>
                              <Typography variant="subtitle2" color="textSecondary">
                                Filing Rate
                              </Typography>
                              <Typography variant="h6" style={{ color: "#2ECC71" }}>
                                {((parseInt(selectedIndustryData.total_taxpayers) || 0) > 0)
                                  ? (((parseInt(selectedIndustryData.filed_records) || 0) / (parseInt(selectedIndustryData.total_taxpayers) || 0)) * 100).toFixed(2) + "%"
                                  : "0%"}
                              </Typography>
                            </Grid>
                            <Grid item xs={6}>
                              <Typography variant="subtitle2" color="textSecondary">
                                Delay Rate
                              </Typography>
                              <Typography variant="h6" style={{ color: "#F39C12" }}>
                                {(((parseInt(selectedIndustryData.delayed_records) || 0) + (parseInt(selectedIndustryData.on_time_records) || 0)) > 0)
                                  ? (((parseInt(selectedIndustryData.delayed_records) || 0) /
                                      ((parseInt(selectedIndustryData.delayed_records) || 0) + (parseInt(selectedIndustryData.on_time_records) || 0))) * 100).toFixed(2) + "%"
                                  : "0%"}
                              </Typography>
                            </Grid>
                          </Grid>
                        </div>
                      ) : (
                        <div className="no-data-message">Select an industry to view details</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Detailed Data Tables */}
              <div className="row mt-4">
                {/* Tax Filing Details Table */}
                {taxFilingData.length > 0 && (
                  <div className="col-md-12 mb-4">
                    <Paper className="p-3">
                      <div className="card-header d-flex justify-content-between align-items-center mb-3">
                        <span>Detailed Tax Filing Statistics by Industry</span>
                        <button
                          className="btn btn-success btn-sm d-flex align-items-center gap-1"
                          onClick={() => handleExport("/tax-filing", "tax_filing_detailed")}
                        >
                          <i className="fa fa-download"></i> Download CSV
                        </button>
                      </div>
                      <div className="d-flex justify-content-end mb-3">
                        <TextField
                          size="small"
                          placeholder="Search industry..."
                          variant="outlined"
                          onChange={(e) => setSearchText(e.target.value)}
                          value={searchText}
                          style={{ width: "250px" }}
                        />
                      </div>
                      <DataTable
                        columns={filingColumns}
                        data={filterFilingData()}
                        customStyles={tableCustomStyles}
                        pagination
                        paginationPerPage={10}
                        highlightOnHover
                        striped
                        dense
                      />
                    </Paper>
                  </div>
                )}

                {/* Timeliness Details Table */}
                {timelinessData.length > 0 && (
                  <div className="col-md-12 mb-4">
                    <Paper className="p-3">
                      <div className="card-header d-flex justify-content-between align-items-center mb-3">
                        <span>Detailed Filing Timeliness by Segment</span>
                        <button
                          className="btn btn-success btn-sm d-flex align-items-center gap-1"
                          onClick={() => handleExport("/timeliness", "timeliness_detailed")}
                        >
                          <i className="fa fa-download"></i> Download CSV
                        </button>
                      </div>
                      <DataTable
                        columns={timelinessColumns}
                        data={filterTimelinessData()}
                        customStyles={tableCustomStyles}
                        pagination
                        paginationPerPage={10}
                        highlightOnHover
                        striped
                        dense
                      />
                    </Paper>
                  </div>
                )}

                {/* Profitability Details Table (CIT only) */}
                {taxType === "cit" &&
                  (parseFloat(kpiMetrics.profitability_rate) || 0) > 0 &&
                  profitabilityData.length > 0 && (
                  <div className="col-md-12 mb-4">
                    <Paper className="p-3">
                      <div className="card-header d-flex justify-content-between align-items-center mb-3">
                        <span>Detailed Profitability by Segment</span>
                        <button
                          className="btn btn-success btn-sm d-flex align-items-center gap-1"
                          onClick={() => handleExport("/profitability", "profitability_detailed")}
                        >
                          <i className="fa fa-download"></i> Download CSV
                        </button>
                      </div>
                      <DataTable
                        columns={profitabilityColumns}
                        data={filterProfitabilityData()}
                        customStyles={tableCustomStyles}
                        pagination
                        paginationPerPage={10}
                        highlightOnHover
                        striped
                        dense
                      />
                    </Paper>
                  </div>
                )}
              </div>
            </div>
          </main>
        </div>
        <Footer />
      </div>
    </div>
  );
}
