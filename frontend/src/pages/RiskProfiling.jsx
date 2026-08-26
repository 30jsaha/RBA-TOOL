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
  Table,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  CircularProgress,
  Alert,
  Paper,
} from "@mui/material";
import dayjs from "dayjs";
// import axios from "axios";
import "./css/Dashboard.css";
import DataTableExport from "../components/common/DataTableExport";
import API from "../api/api";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";


export default function RiskProfiling() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [tenure, setTenure] = useState("3m");
  const [startDate, setStartDate] = useState(dayjs().startOf("month"));
  const [endDate, setEndDate] = useState(dayjs().endOf("month"));

  // Data states
  const [freqData, setFreqData] = useState(null);
  const [breakdownData, setBreakdownData] = useState([]);
  const [payableData, setPayableData] = useState({ per_sector: [] });
  const [inputOutputData, setInputOutputData] = useState({ per_sector: [] });
  const [gstSales, setGstSales] = useState([]);
  const [riskTable, setRiskTable] = useState([]);
  const [delayedData, setDelayedData] = useState({ late_returns: [], missing_months: [] });

  const [loading, setLoading] = useState(true);
  const [subLoading, setSubLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const [selectedIndustry, setSelectedIndustry] = useState("");

  // NEW TAX TYPE STATE (default remains GST)
  const [taxType, setTaxType] = useState("gst");

  

  // const getParams = () => {
  //   const params = { range_type: tenure };

  //   if (tenure === "custom" && startDate && endDate) {
  //     params.start_date = startDate.format("YYYY-MM-DD");
  //     params.end_date = endDate.format("YYYY-MM-DD");
  //   }

  //   //ONLY add taxtype when user selects swt or cit
  //   if (taxType !== "gst") {
  //     params.taxtype = { taxType;
  //   }

  //   return params;
  // };

  // NEW TAX TYPE STATE (default remains GST)
const getParams = () => {
  const params = {
    range_type: tenure,
    taxtype: taxType,
  };

  if (tenure === "custom" && startDate && endDate) {
    params.start_date = startDate.format("YYYY-MM-DD");
    params.end_date = endDate.format("YYYY-MM-DD");
  }

  return params;
};

/** Handle Tenure Change */
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


  const chartExportToolbar = {
      show: true,
      tools: {
        download: true, // enables toolbar button
         selection: false,
          zoom: false,
          zoomin: false,
          zoomout: false,
          pan: false,
          reset: false,  // Home icon
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

  // const axiosInstance = axios.create({
  //   baseURL: BASE,
  //   headers: { Authorization: accessToken ? `Bearer ${accessToken}` : "" },
  // });

  // Build Params
  const BASE_PATH =
  taxType === "gst"
    ? "/risk-profiling"
    : taxType === "swt"
    ? "/risk-profiling"
    : "/risk-profiling";



  // Load initial data
  const fetchCoreData = async () => {
    try {
      const params = getParams();
      const [freqRes, breakdownRes, payableRes, inputRes, gstRes] = await Promise.all([
              API.get(BASE_PATH + "/frequency-anomalies", { params }),
              API.get(BASE_PATH + "/breakdown-category", { params }),
              API.get(BASE_PATH + "/payable-vs-refundable", { params }),
              API.get(BASE_PATH + "/input-vs-output", { params }),
              API.get(BASE_PATH + "/gst-sales-comparison", { params }),
            ]);


      setFreqData(freqRes.data);
      setBreakdownData(breakdownRes.data);
      // Filter out 'Unknown' or blank industries
      const cleanPayable = {
        ...payableRes.data,
        per_sector: payableRes.data.per_sector.filter(
          (r) => r.industry && r.industry.toLowerCase() !== "unknown"
        ),
      };
      const cleanInput = {
        ...inputRes.data,
        per_sector: inputRes.data.per_sector.filter(
          (r) => r.industry && r.industry.toLowerCase() !== "unknown"
        ),
      };

      setPayableData(cleanPayable);
      setInputOutputData(cleanInput);

      // Set default selected industry (first clean one)
      if (cleanPayable.per_sector.length > 0) {
        setSelectedIndustry(cleanPayable.per_sector[0].industry);
      }

      const cleanGst = gstRes.data.data.filter(
        (r) => r.industry && r.industry.trim().toLowerCase() !== "unknown"
      );


      //setGstSales(gstRes.data.data);
      setGstSales(cleanGst);

      // Default selected industry
      if (payableRes.data.per_sector?.length > 0) {
        setSelectedIndustry(payableRes.data.per_sector[0].industry);
      }

      setLoading(false);
      fetchSecondaryData(); // Fetch tables async
    } catch (err) {
      setErrorMsg("âŒ Failed to load core data.");
      setLoading(false);
    }
  };

  // Load slower data async
  const fetchSecondaryData = async () => {
    setSubLoading(true);
    try {
      const params = getParams();
      const [riskRes, delayedRes] = await Promise.all([
        API.get("/risk-profiling/taxpayers-risk", { params }),
        API.get("/risk-profiling/delayed-returns", { params }),
      ]);
      setRiskTable(riskRes.data.data);
      setDelayedData(delayedRes.data);
    } catch {
      console.warn("Secondary data failed to load");
    } finally {
      setSubLoading(false);
    }
  };

  useEffect(() => {
    fetchCoreData();
  },  [tenure, startDate, endDate, taxType]);

  // Filter charts by selected industry
  const filteredPayable =
    payableData.per_sector.find((r) => r.industry === selectedIndustry) || {};
  const filteredInput =
    inputOutputData.per_sector.find((r) => r.industry === selectedIndustry) || {};

  // Chart Configs
  const freqOptions = {
    chart: { type: "pie", toolbar: chartExportToolbar, },
    labels: ["Flagged", "Not Flagged"],
    title: { text: "Frequency of Risk Anomalies", style: { fontWeight: "bold" } },
    legend: { position: "bottom" },
  };

  const breakdownOptions = {
    chart: { type: "bar", toolbar: chartExportToolbar},
    plotOptions: {
      bar: {
        borderRadius: 6,
        dataLabels: {
          position: "top", // label on top of each bar
        },
      },
    },
    dataLabels: {
      enabled: true,
      formatter: (val) => (val ? val.toLocaleString() : ""),
      offsetY: -15,
      style: {
        fontSize: "9px",
        colors: ["#000"], // black text
        fontWeight: "500",
      },
    },
    xaxis: { categories: breakdownData.map((r) => r.segment_label) },
    title: { text: "Risk Breakdown by Category", style: { fontWeight: "bold" } },
    colors: ["#3498DB", "#E74C3C"],
  };

  const payableOptions = {
    chart: { type: "bar", toolbar: chartExportToolbar, },
    plotOptions: {
      bar: {
        borderRadius: 6,
        dataLabels: {
          position: "top", // label on top of each bar
        },
      },
    },
    dataLabels: {
      enabled: true,
      formatter: (val) => (val ? val.toLocaleString() : ""),
      offsetY: -15,
      style: {
        fontSize: "9px",
        colors: ["#000"], // black text
        fontWeight: "500",
      },
    },
    xaxis: { categories: ["Payable", "Refundable"], title: { text: "Industry" } },
    title: { text: `Selected Industry: ${selectedIndustry}`, style: { fontWeight: "bold" } },
    colors: ["#16A085", "#E67E22"],
    legend: { position: "top" },
  };


  const inputOptions = {
    chart: { type: "bar", toolbar: chartExportToolbar },
    plotOptions: {
      bar: {
        borderRadius: 6,
        dataLabels: {
          position: "top",
        },
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
    xaxis: { categories: ["Input Credits", "Output Debits"], title: { text: "Industry" } },
    title: { text: `Selected Industry: ${selectedIndustry}`, style: { fontWeight: "bold" } },
    colors: ["#2980B9", "#C0392B"],
    legend: { position: "top" },
  };


  // if (loading)
  //   return (
  //     <div className="d-flex justify-content-center align-items-center vh-100">
  //       <CircularProgress />
  //     </div>
  //   );

  return (
    <div className="container-fluid">
      <div className="row">
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />
        <div className="col-lg-12 col-md-12">
          <Sidebar collapsed={collapsed} setCollapsed={setCollapsed} openMenu={openMenu} setOpenMenu={setOpenMenu} />

          <main className="main-content mt-5">
            <div className="container-fluid">
              <div className="header-title-page mb-3">Risk Profiling Dashboard</div>

              {/* FILTERS SECTION WITH TAX TYPE */}
                <div className="row risk-filter-area align-items-center mb-4">
  
                  {/* NEW Dropdown Taxtype */}
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
  
                  {/* Tenure */}
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
  
                  {/* Date Picker */}
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

              {/* Charts */}
              <div className="row">
                {/* Frequency Chart */}
                <div className="col-lg-6 col-md-12 mb-4">
                  <div className="card">
                    <div className="card-body">
                      <Chart
                        options={freqOptions}
                        series={[freqData?.flagged_count || 0, freqData?.not_flagged_count || 0]}
                        type="pie"
                        height={350}
                      />
                    </div>
                  </div>
                </div>

                {/* Breakdown Chart */}
                <div className="col-lg-6 col-md-12 mb-4">
                  <div className="card">
                    <div className="card-body">
                      <Chart
                        options={breakdownOptions}
                        series={[
                          { name: "Flagged", data: breakdownData.map((r) => r.flagged_count) },
                          { name: "Total Records", data: breakdownData.map((r) => r.records) },
                        ]}
                        type="bar"
                        height={350}
                      />
                    </div>
                  </div>
                </div>

                {/* Payable vs Refundable */}
                <div className="col-lg-6 col-md-12 mb-4">
                  <div className="card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Payable vs Refundable</span>
                      <FormControl size="small" style={{ width: "180px" }}>
                        <Select
                          value={selectedIndustry}
                          onChange={(e) => setSelectedIndustry(e.target.value)}
                        >
                          {payableData.per_sector.map((r, i) => (
                            <MenuItem key={i} value={r.industry}>{r.industry}</MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </div>
                    <div className="card-body">
                      <Chart
                        options={payableOptions}
                        series={[
                          { name: "Payable", data: [filteredPayable.sum_payable || 0] },
                          { name: "Refundable", data: [filteredPayable.sum_refundable || 0] },
                        ]}
                        type="bar"
                        height={350}
                      />
                    </div>
                  </div>
                </div>

                {/* Input vs Output */}
                <div className="col-lg-6 col-md-12 mb-4">
                  <div className="card">
                    <div className="card-header d-flex justify-content-between align-items-center">
                      <span>Input Credits vs Output Debits</span>
                      <FormControl size="small" style={{ width: "180px" }}>
                        <Select
                          value={selectedIndustry}
                          onChange={(e) => setSelectedIndustry(e.target.value)}
                        >
                          {inputOutputData.per_sector.map((r, i) => (
                            <MenuItem key={i} value={r.industry}>{r.industry}</MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </div>
                    <div className="card-body">
                      <Chart
                        options={inputOptions}
                        series={[
                          { name: "Input Credits", data: [filteredInput.sum_input_credits || 0] },
                          { name: "Output Debits", data: [filteredInput.sum_output_debits || 0] },
                        ]}
                        type="bar"
                        height={350}
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* GST Sales Table */}
              <div className="card mt-4">
                <div className="card-header">
                    <h6 className="fw-bold">Sales Comparison</h6>
                      <DataTableExport data={gstSales} filename="Risk Profiling" />
                  </div>
                <div className="card-body">
                  <Table size="small" className="table-striped table-bordered">
                    <TableHead>
                      <TableRow>
                        <TableCell>Industry</TableCell>
                        <TableCell>Year</TableCell>
                        <TableCell>Total Sales</TableCell>
                        <TableCell>Taxable Sales</TableCell>
                        <TableCell>Taxpayers</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {gstSales.map((row, i) => (
                        <TableRow key={i}>
                          <TableCell>{row.industry}</TableCell>
                          <TableCell>{row.year}</TableCell>
                          <TableCell>{row.total_sales_income?.toLocaleString()}</TableCell>
                          <TableCell>{row.gst_taxable_sales?.toLocaleString()}</TableCell>
                          <TableCell>{row.taxpayers}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>

              {subLoading && (
                <div className="text-center mt-3 text-secondary small">Loading secondary tables...</div>
              )}
            </div>
          </main>
        </div>
        <Footer />
      </div>
    </div>
  );
}
