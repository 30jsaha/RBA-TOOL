import { useEffect, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";

import {
  Autocomplete,
  TextField,
  Table,
  TableRow,
  TableBody,
  TableCell,
  Paper,
  Button,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
  Box,
  Typography,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";

import API from "../api/api";
import dayjs from "dayjs";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

// Reusable Components
import useTenure from "../hooks/useTenure";

import TaxReportRiskProfilingPDFExport from "../components/common/reports/TaxReportRiskProfilingPDFExport";


export default function TaxpayerReportRiskProfiling() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const preventEnterSubmit = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  // Dropdown + Selected values
  const [tinList, setTinList] = useState([]);
  const [selectedTin, setSelectedTin] = useState(null);

  // Tenure logic
  const {
    tenure,
    startDate,
    endDate,
    handleTenureChange,
    setStartDate,
    setEndDate,
  } = useTenure("1m");
  const [appliedFilters, setAppliedFilters] = useState(() => ({ tenure: "1m", startDate: dayjs().startOf("month"), endDate: dayjs().endOf("month"), taxType: "gst", selectedTin: null }));

  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [riskModalOpen, setRiskModalOpen] = useState(false);
  const [riskType, setRiskType] = useState(null);
  const [riskDebug, setRiskDebug] = useState(null);

  const isValidDayjs = (value) => Boolean(value && dayjs(value).isValid());

  const formatDateForDisplay = (value) =>
    isValidDayjs(value) ? dayjs(value).format("DD/MM/YYYY") : "--";

  // Default GST
  const [taxType, setTaxType] = useState("gst");

  // Dynamic API base path
  const BASE_PATH =
    taxType === "gst"
      ? "/taxpayer_report_risk_profiling"
      : taxType === "swt"
      ? "/taxpayer_report_risk_profiling"
      : "/taxpayer_report_risk_profiling";

  const sectionLabels = new Set([
    "TAXPAYER DETAILS",
    "TAX ACCOUNT DETAILS",
    "BUSINESS ADDRESS ",
    "BUSINESS ACTIVITY",
    "BUSINESS CONTACT DETAILS",
    "TAX COMPLIANCE INDICATOR FOR MAIN TAX TYPES (lodgments/Tax Account balances)",
    "ASSETS & LIABILITIES",
    "RISK ANALYSIS RESULT",
    "RECOMMENDATION",
  ]);

  const formatValue = (value) => {
    if (value === null || value === undefined) return "NA";
    if (typeof value === "string") {
      const v = value.trim();
      return v === "" ? "NA" : v;
    }
    if (typeof value === "number") {
      return value === 0 ? "NA" : value;
    }
    return value;
  };

  const getRiskClass = (risk) => {
    if (!risk) return "risk-na";
    const v = risk.toString().toLowerCase();
    if (v === "high") return "risk-high";
    if (v === "medium") return "risk-medium";
    if (v === "low") return "risk-low";
    return "risk-na";
  };

  const structuredMap = (summary?.structured_report || []).reduce((acc, row) => {
    acc[row.label] = row.value;
    return acc;
  }, {});

  const openRiskModal = async (type) => {
    setRiskType(type);
    setRiskModalOpen(true);

    // Optional: fetch debug data (non-breaking)
    if (!selectedTin) return;
    try {
      const params = {
        tin: selectedTin.tin,
        range_type: appliedFilters.tenure,
        taxtype: appliedFilters.taxType,
        debug: 1,
      };
      if (appliedFilters.tenure === "custom") {
        const startOk = startDate && typeof startDate.format === "function" && startDate.isValid?.();
        const endOk = endDate && typeof endDate.format === "function" && endDate.isValid?.();
        if (startOk && endOk) {
          params.start_date = appliedFilters.startDate.format("YYYY-MM-DD");
          params.end_date = appliedFilters.endDate.format("YYYY-MM-DD");
        }
      }
      const res = await API.get(`${BASE_PATH}/taxpayer-summary`, { params });
      setRiskDebug(res.data?.debug || null);
    } catch {
      setRiskDebug(null);
    }
  };

  const closeRiskModal = () => {
    setRiskModalOpen(false);
    setRiskType(null);
  };

  const getRiskExplanation = () => {
    const riskKey =
      riskType === "CIT"
        ? "CIT Risk Identified"
        : riskType === "GST"
        ? "GST Risk Identified"
        : riskType === "SWT"
        ? "SWT Risk Identified"
        : "Other Risk Identified";

    const riskValue = formatValue(structuredMap[riskKey]);

    const reasons = [];
    const metrics = [];

    if (riskType === "GST") {
      const fraudCases = summary?.gst?.fraud_summary?.total_fraud_cases;
      const fraudPct = summary?.gst?.fraud_summary?.fraud_percentage;
      if (fraudCases !== undefined && fraudCases !== null) {
        reasons.push(`Fraud cases detected: ${fraudCases}`);
        metrics.push({ label: "Fraud Cases", value: fraudCases });
      }
      if (fraudPct !== undefined && fraudPct !== null) {
        reasons.push(`Fraud percentage: ${fraudPct}%`);
        metrics.push({ label: "Fraud Percentage", value: `${fraudPct}%` });
      }
      const gstBal = structuredMap["GST Account Balance"];
      if (gstBal !== undefined) {
        metrics.push({ label: "Account Balance", value: formatValue(gstBal) });
      }
    }

    if (riskType === "SWT") {
      const fraudCases = summary?.swt?.fraud_metrics?.total_fraud_cases;
      if (fraudCases !== undefined && fraudCases !== null) {
        reasons.push(`Payroll anomalies flagged: ${fraudCases}`);
        metrics.push({ label: "Fraud Cases", value: fraudCases });
      }
      const swtBal = structuredMap["SWT Account Balance"];
      if (swtBal !== undefined) {
        metrics.push({ label: "Account Balance", value: formatValue(swtBal) });
      }
    }

    if (riskType === "CIT") {
      const citBal = structuredMap["CIT Account Balance"];
      if (citBal !== undefined) {
        metrics.push({ label: "Account Balance", value: formatValue(citBal) });
      }
      const citOut = structuredMap["CIT Outstanding Returns"];
      if (citOut !== undefined) {
        metrics.push({ label: "Outstanding Returns", value: formatValue(citOut) });
      }
      if (riskDebug?.cit_join_coverage_pct !== undefined) {
        reasons.push(`ML join coverage: ${riskDebug.cit_join_coverage_pct}%`);
        metrics.push({ label: "ML Join Coverage", value: `${riskDebug.cit_join_coverage_pct}%` });
      }
    }

    if (riskType === "Other") {
      if (riskDebug?.gst_balance_mismatch_pct !== undefined) {
        reasons.push(`GST balance mismatch: ${riskDebug.gst_balance_mismatch_pct}%`);
        metrics.push({ label: "GST Mismatch %", value: `${riskDebug.gst_balance_mismatch_pct}%` });
      }
    }

    if (reasons.length === 0) {
      reasons.push("No evidence data available from API for this risk.");
    }

    return { riskValue, reasons, metrics };
  };

  // Fetch TIN dropdown list
  useEffect(() => {
    API.get(`${BASE_PATH}/dropdown`)
      .then((res) => {
        const formatted = res.data.map((r) => ({
          label: `${r.tin} - ${r.name}`,
          tin: r.tin,
        }));

        setTinList(formatted);

        // Auto select 1st TIN
        if (!selectedTin && formatted.length > 0) {
          setSelectedTin(formatted[0]);
          setAppliedFilters((current) => ({ ...current, taxType, selectedTin: formatted[0] }));
        }
      })
      .catch(() => console.error("TIN list fetch error"));
  }, [taxType]);

  // Fetch taxpayer summary
  useEffect(() => {
    if (!appliedFilters.selectedTin) return;

    const params = {
      tin: appliedFilters.selectedTin?.tin,
      range_type: appliedFilters.tenure,
      taxtype: appliedFilters.taxType,
    };

    if (appliedFilters.tenure === "custom") {
      const startOk = appliedFilters.startDate && typeof appliedFilters.startDate.format === "function" && appliedFilters.startDate.isValid?.();
      const endOk = appliedFilters.endDate && typeof appliedFilters.endDate.format === "function" && appliedFilters.endDate.isValid?.();
      if (!startOk || !endOk) return;
      params.start_date = appliedFilters.startDate.format("YYYY-MM-DD");
      params.end_date = appliedFilters.endDate.format("YYYY-MM-DD");
    }

    setLoading(true);

    API.get(`${BASE_PATH}/taxpayer-summary`, { params })
      .then((res) => setSummary(res.data))
      .catch(() => console.error("Summary fetch error"))
      .finally(() => setLoading(false));
  }, [appliedFilters]);

  return (
    <div className="container-fluid">
      <style>{`
        .section-header-row td {
          background: #e5e7eb;
          font-weight: 600;
          padding: 8px 12px;
          border-left: 4px solid #6366f1;
        }
        .risk-high {
          background-color: #dc2626;
          color: white;
          font-weight: bold;
          animation: blink 1s infinite;
        }
        .risk-medium, .risk-low {
          background-color: #16a34a;
          color: white;
          font-weight: 600;
        }
        .risk-na {
          background-color: #9ca3af;
          color: white;
        }
        .risk-cell {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        @keyframes blink {
          50% { opacity: 0.4; }
        }
      `}</style>
      <div className="row">
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />

        <div className="col-lg-12">
          <Sidebar
            collapsed={collapsed}
            setCollapsed={setCollapsed}
            openMenu={openMenu}
            setOpenMenu={setOpenMenu}
          />

          <main className="main-content mt-5">
            <div className="container-fluid">
              <div className="header-title-page mb-3">
                Taxpayer Report Risk Profiling
              </div>

              {/* ---------- FILTERS ---------- */}
              <div className="row g-3 mb-4">
                {/* TIN DROPDOWN */}
                <div className="col-lg-4">
                  <Autocomplete
                    options={tinList}
                    value={selectedTin}
                    getOptionLabel={(option) => option?.label || ""}
                    isOptionEqualToValue={(option, value) =>
                      option?.tin === value?.tin
                    }
                    onChange={(_, value) => setSelectedTin(value)}
                    onInputChange={(_, value) => {
                      API.get(`${BASE_PATH}/dropdown`, { params: { q: value } })
                        .then((res) =>
                          setTinList(
                            res.data.map((r) => ({
                              label: `${r.tin} - ${r.name}`,
                              tin: r.tin,
                            }))
                          )
                        )
                        .catch(() => {});
                    }}
                    renderInput={(params) => (
                      <TextField {...params} size="small" label="TIN / Taxpayer" />
                    )}
                  />
                </div>

                {/* Tenure Filter */}
                <div className="col-lg-8" onKeyDownCapture={preventEnterSubmit}>
                  <div className="row g-3 align-items-center">
                    <div className="col-md-4">
                      <FormControl fullWidth size="small">
                        <InputLabel id="tenure-label">Select Tenure</InputLabel>
                        <Select
                          labelId="tenure-label"
                          value={tenure}
                          label="Select Tenure"
                          onChange={handleTenureChange}
                        >
                          <MenuItem value="1m">Past 1 Month</MenuItem>
                          <MenuItem value="3m">Past 3 Months</MenuItem>
                          <MenuItem value="6m">Past 6 Months</MenuItem>
                          <MenuItem value="1y">Past 1 Year</MenuItem>
                          <MenuItem value="custom">Custom Date</MenuItem>
                        </Select>
                      </FormControl>
                    </div>

                    <div className="col-md-8 d-flex justify-content-md-end gap-2 pt-3 mt-md-0">
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
                                  readOnly: true,
                                },
                              },
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
                                  readOnly: true,
                                },
                              },
                            }}
                          />
                        </LocalizationProvider>
                      ) : (
                        <div className="fw-bold small d-flex align-items-center gap-2">
                          <span>{formatDateForDisplay(startDate)}</span>
                          <span>to</span>
                          <span>{formatDateForDisplay(endDate)}</span>
                        </div>
                      )}
                      <Button
                        size="small"
                        variant="contained"
                        disabled={loading || (tenure === "custom" && (!isValidDayjs(startDate) || !isValidDayjs(endDate))) || !selectedTin}
                        onClick={() => setAppliedFilters({ taxType, tenure, startDate, endDate, selectedTin })}
                      >
                        Submit
                      </Button>
                    </div>
                  </div>
                </div>
              </div>

              {/* ---------- DATA TABLE ---------- */}
              <Paper className="p-3">
                <div className="text-center fw-bold mb-1">
                  <h5>Tax Compliance Report for TIN: {selectedTin?.tin}</h5>
                </div>

                <div className="text-center small mb-3">
                  Period: {formatDateForDisplay(startDate)} to{" "}
                  {formatDateForDisplay(endDate)}
                </div>

                <div className="d-flex gap-2 justify-content-end mb-2">
                  <TaxReportRiskProfilingPDFExport
                    summary={summary}
                    tin={selectedTin?.tin}
                    startDate={startDate?.format?.("YYYY-MM-DD") || ""}
                    endDate={endDate?.format?.("YYYY-MM-DD") || ""}
                  />
                </div>


                {loading ? (
                  <div className="d-flex justify-content-center mt-4">
                    <CircularProgress />
                  </div>
                ) : (
                  <Table size="small" className="table-bordered">
                    
                    <TableBody>
                      {(summary?.structured_report || []).map((row, idx) => {
                        const isSection =
                          sectionLabels.has(row.label) &&
                          (row.value === "" || row.value === null || row.value === undefined);

                        if (isSection) {
                          return (
                            <TableRow key={`${row.label}-${idx}`} className="section-header-row">
                              <TableCell className="fw-bold">{row.label}</TableCell>
                              <TableCell colSpan={4}></TableCell>
                            </TableRow>
                          );
                        }

                        const isRiskRow = [
                          "CIT Risk Identified",
                          "GST Risk Identified",
                          "SWT Risk Identified",
                          "Other Risk Identified",
                        ].includes(row.label);

                        return (
                          <TableRow key={`${row.label}-${idx}`}>
                            <TableCell>{row.label}</TableCell>
                            <TableCell className={isRiskRow ? getRiskClass(formatValue(row.value)) : ""}>
                              {isRiskRow ? (
                                <div className="risk-cell">
                                  <span>{formatValue(row.value)}</span>
                                  <Button
                                    size="small"
                                    variant="contained"
                                    color="primary"
                                    onClick={() =>
                                      openRiskModal(
                                        row.label.startsWith("CIT")
                                          ? "CIT"
                                          : row.label.startsWith("GST")
                                          ? "GST"
                                          : row.label.startsWith("SWT")
                                          ? "SWT"
                                          : "Other"
                                      )
                                    }
                                  >
                                    View
                                  </Button>
                                </div>
                              ) : (
                                formatValue(row.value)
                              )}
                            </TableCell>
                          </TableRow>
                        );
                      })}

                    </TableBody>


                  </Table>
                )}
              </Paper>
            </div>
          </main>
        </div>
      </div>

      <Footer />

      <Dialog
        open={riskModalOpen}
        onClose={closeRiskModal}
        maxWidth="md"
        fullWidth
        PaperProps={{ style: { maxWidth: 700 } }}
      >
        <DialogTitle>
          Risk Explanation - {riskType || "NA"}
          <IconButton
            onClick={closeRiskModal}
            style={{ position: "absolute", right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers style={{ maxHeight: 500 }}>
          {(() => {
            const { riskValue, reasons, metrics } = getRiskExplanation();
            return (
              <Box>
                <Typography variant="h6" gutterBottom>
                  {riskType} Risk: <strong>{riskValue}</strong>
                </Typography>

                <Typography variant="subtitle1" gutterBottom>
                  Reason
                </Typography>
                <ul>
                  {reasons.map((r, i) => (
                    <li key={i}>
                      <strong>{r}</strong>
                    </li>
                  ))}
                </ul>

                <Typography variant="subtitle1" gutterBottom>
                  Data Evidence
                </Typography>
                <Table size="small" className="table-bordered">
                  <TableBody>
                    {metrics.length === 0 ? (
                      <TableRow>
                        <TableCell>Metric</TableCell>
                        <TableCell>NA</TableCell>
                      </TableRow>
                    ) : (
                      metrics.map((m, i) => (
                        <TableRow key={i}>
                          <TableCell>{m.label}</TableCell>
                          <TableCell><strong>{formatValue(m.value)}</strong></TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </Box>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}



