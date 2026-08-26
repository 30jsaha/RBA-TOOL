import { useEffect, useMemo, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";

import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  CircularProgress,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from "@mui/material";

import RemoveRedEyeIcon from "@mui/icons-material/RemoveRedEye";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import dayjs from "dayjs";

import DataTable from "react-data-table-component";
import "./css/Dashboard.css";
import tableCustomStyles from "../components/common/tableStyles";

import useTenure from "../hooks/useTenure";
import DataTableExport from "../components/common/DataTableExport";
import FraudReasonContent from "../components/common/FraudReasonContent";
import API from "../api/api";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

const PAGE_SIZE = 100;

const monthLabel = (year, month) => {
  if (!year) return "Unknown Period";
  if (month == null) return `${year}`;
  return dayjs(`${year}-${String(month).padStart(2, "0")}-01`).format("YYYY MMMM");
};


export default function TaxpayerProfile() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [riskRecords, setRiskRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  const [taxType, setTaxType] = useState("gst");
  const [selectedTaxpayer, setSelectedTaxpayer] = useState([]);
  const [selectedTin, setSelectedTin] = useState("");
  const [expandedHistoryYear, setExpandedHistoryYear] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [openReasonDialog, setOpenReasonDialog] = useState(false);
  const [fraudReasons, setFraudReasons] = useState([]);
  const [fraudReasonTin, setFraudReasonTin] = useState("");
  const [fraudReasonLoading, setFraudReasonLoading] = useState(false);
  const [fraudReasonError, setFraudReasonError] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalRecords, setTotalRecords] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrevious, setHasPrevious] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [sortBy, setSortBy] = useState("");
  const [sortOrder, setSortOrder] = useState("desc");

  const isValidDayjs = (value) => Boolean(value && dayjs(value).isValid());

  const formatDateForDisplay = (value) =>
    isValidDayjs(value) ? dayjs(value).format("DD-MM-YYYY") : "--";

  const {
    tenure,
    startDate,
    endDate,
    handleTenureChange,
    setStartDate,
    setEndDate,
  } = useTenure("3m");

  const BASE_PATH = "/predicted-records/all-tax-records";
  const HISTORY_PATH = "/predicted-records/taxpayer-history";
  const FRAUD_REASONS_PATH = "/predicted-records/fraud-reasons";

  const getFilterParams = () => ({
    taxtype: taxType,
    range_type: tenure,
    ...(tenure === "custom" && isValidDayjs(startDate) && isValidDayjs(endDate)
      ? {
          start_date: dayjs(startDate).format("YYYY-MM-DD"),
          end_date: dayjs(endDate).format("YYYY-MM-DD"),
        }
      : {}),
  });

  const getParams = () => ({
    ...getFilterParams(),
    page: currentPage,
    page_size: PAGE_SIZE,
    ...(searchTerm ? { search: searchTerm } : {}),
    ...(sortBy ? { sort_by: sortBy, sort_order: sortOrder } : {}),
  });

  const getVisiblePages = () => {
    if (!totalPages) return [];
    const windowStart = Math.floor((currentPage - 1) / 10) * 10 + 1;
    const windowEnd = Math.min(windowStart + 9, totalPages);
    return Array.from({ length: windowEnd - windowStart + 1 }, (_, index) => windowStart + index);
  };

  const fetchCoreData = async () => {
    if (tenure === "custom" && (!isValidDayjs(startDate) || !isValidDayjs(endDate))) {
      setRiskRecords([]);
      setTotalRecords(0);
      setTotalPages(0);
      setHasNext(false);
      setHasPrevious(false);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);

      const res = await API.get(BASE_PATH, {
        params: getParams(),
      });

      const rawRecords = Array.isArray(res?.data?.records) ? res.data.records : [];
      const normalizedRecords = rawRecords.map((row, index) => ({
        ...row,
        tin: row.tin || row.tin_number || "",
        taxpayer_name: row.taxpayer_name || row.taxpayer || "",
        row_key:
          row.row_key ||
          `${taxType}-${row.tin || row.tin_number || ""}-${row.tax_period_year || ""}-${
            row.tax_period_month ?? "annual"
          }-${index}`,
      }));

      setRiskRecords(normalizedRecords);
      setTotalRecords(Number(res?.data?.total_records || 0));
      setTotalPages(Number(res?.data?.total_pages || 0));
      setHasNext(Boolean(res?.data?.has_next));
      setHasPrevious(Boolean(res?.data?.has_previous));
      setErrorMsg("");
    } catch (err) {
      console.error(err);
      setErrorMsg("Error loading taxpayer records.");
      setRiskRecords([]);
      setTotalRecords(0);
      setTotalPages(0);
      setHasNext(false);
      setHasPrevious(false);
    } finally {
      setLoading(false);
    }
  };

  const openTaxpayerHistory = async (row) => {
    const tinValue = row.tin || row.tin_number || "";
    if (!tinValue) return;

    setSelectedTin(tinValue);
    setSelectedTaxpayer([]);
    setHistoryError("");
    setHistoryLoading(true);

    try {
      const res = await API.get(HISTORY_PATH, {
        params: {
          ...getFilterParams(),
          tin: tinValue,
        },
      });

      const records = Array.isArray(res?.data?.records) ? res.data.records : [];
      setSelectedTaxpayer(records);
      setExpandedHistoryYear(records.length > 0 ? String(records[0].tax_period_year || "") : "");
    } catch (err) {
      console.error(err);
      setHistoryError("Error loading taxpayer history.");
      setSelectedTaxpayer([]);
      setExpandedHistoryYear("");
    } finally {
      setHistoryLoading(false);
    }
  };

  const openFraudReasons = async (row) => {
    const tinValue = row.tin || row.tin_number || "";
    if (!tinValue) return;

    setFraudReasonTin(tinValue);
    setFraudReasons([]);
    setFraudReasonError("");
    setOpenReasonDialog(true);
    setFraudReasonLoading(true);

    try {
      const res = await API.get(FRAUD_REASONS_PATH, {
        params: {
          ...getFilterParams(),
          tin: tinValue,
        },
      });

      setFraudReasons(Array.isArray(res?.data?.records) ? res.data.records : []);
    } catch (err) {
      console.error(err);
      setFraudReasonError("Error loading fraud reasons.");
      setFraudReasons([]);
    } finally {
      setFraudReasonLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setCurrentPage(1);
      setSearchTerm(searchInput.trim());
    }, 400);

    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setCurrentPage(1);
    setSelectedTaxpayer([]);
    setSelectedTin("");
    setExpandedHistoryYear("");
    setFraudReasons([]);
    setFraudReasonTin("");
    setOpenReasonDialog(false);
  }, [taxType, tenure, startDate, endDate]);

  useEffect(() => {
    fetchCoreData();
  }, [taxType, tenure, startDate, endDate, currentPage, searchTerm, sortBy, sortOrder]);

  const columns = [
    {
      name: "TIN",
      selector: (row) => row.tin || row.tin_number || "-",
      sortable: true,
      sortField: "tin",
    },
    {
      name: "Taxpayer Name",
      selector: (row) => row.taxpayer_name || row.taxpayer || "-",
      sortable: true,
      sortField: "taxpayer_name",
      wrap: true,
    },
    {
      name: "Year",
      selector: (row) => row.tax_period_year || "-",
      sortable: true,
      sortField: "tax_period_year",
    },
    {
      name: "Month",
      selector: (row) => row.tax_period_month ?? "-",
      sortable: true,
      sortField: "tax_period_month",
    },
    {
      name: "Is Fraud",
      cell: (row) => {
        const isFraud = Number(row?.is_fraud) === 1;
        return (
          <span style={{ fontWeight: 700, color: isFraud ? "#dc2626" : "#16a34a" }}>
            {isFraud ? "YES" : "NO"}
          </span>
        );
      },
      sortable: true,
      sortField: "is_fraud",
    },
    {
      name: "Risk Type",
      selector: (row) => row.risk_type || "-",
      sortable: true,
      sortField: "risk_type",
    },
    {
      name: "Flagged",
      selector: (row) => row.flagged ?? "-",
      sortable: true,
      sortField: "flagged",
    },
    {
      name: "View",
      cell: (row) => (
        <Button variant="outlined" size="small" onClick={() => openTaxpayerHistory(row)}>
          <RemoveRedEyeIcon fontSize="small" />
        </Button>
      ),
    },
    {
      name: "Fraud Reason",
      cell: (row) =>
        row.fraud_reason ? (
          <Button
            className="badge bg-danger"
            style={{ color: "#fff", fontSize: "12px" }}
            onClick={() => openFraudReasons(row)}
          >
            View Reason
          </Button>
        ) : (
          "-"
        ),
      button: true,
    },
  ];

  const visiblePages = getVisiblePages();
  const showingStart = totalRecords === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1;
  const showingEnd = totalRecords === 0 ? 0 : Math.min(currentPage * PAGE_SIZE, totalRecords);

  const reasonDialogTitle = useMemo(() => {
    return fraudReasonTin ? `Fraud Reason Details - ${fraudReasonTin}` : "Fraud Reason Details";
  }, [fraudReasonTin]);

  const historyByYear = useMemo(() => {
    const grouped = selectedTaxpayer.reduce((acc, row) => {
      const yearKey = String(row.tax_period_year || "Unknown");
      if (!acc[yearKey]) acc[yearKey] = [];
      acc[yearKey].push(row);
      return acc;
    }, {});

    return Object.entries(grouped)
      .sort(([yearA], [yearB]) => Number(yearB) - Number(yearA))
      .map(([year, rows]) => ({
        year,
        rows: [...rows].sort((a, b) => Number(b.tax_period_month ?? -1) - Number(a.tax_period_month ?? -1)),
      }));
  }, [selectedTaxpayer]);

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

          <main className="main-content mt-5 p-3">
            <div className="container-fluid">
              <div className="header-title-page mb-3">Taxpayer Profile</div>

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
                </div>
              </div>

              <div className="card taxpayer-profile-table">
                <div className="card-header fw-bold d-flex justify-content-between align-items-center">
                  <span>Risk Profiling Summary ({totalRecords.toLocaleString()})</span>
                  <span className="small text-muted">
                    Showing {showingStart.toLocaleString()}-{showingEnd.toLocaleString()} of {totalRecords.toLocaleString()} records
                  </span>
                </div>

                <div className="card-body">
                  {errorMsg ? <div className="alert alert-danger">{errorMsg}</div> : null}

                  <DataTable
                    columns={columns}
                    data={riskRecords}
                    keyField="row_key"
                    highlightOnHover
                    dense
                    fixedHeader
                    fixedHeaderScrollHeight="420px"
                    customStyles={tableCustomStyles}
                    noDataComponent={<div className="no-data-message">No records</div>}
                    progressPending={loading}
                    progressComponent={
                      <div className="text-center py-4">
                        <CircularProgress size={32} />
                        <div className="mt-2">Loading taxpayer records...</div>
                      </div>
                    }
                    subHeader
                    sortServer
                    onSort={(column, direction) => {
                      if (!column.sortField) return;
                      setSortBy(column.sortField);
                      setSortOrder(direction);
                      setCurrentPage(1);
                    }}
                    subHeaderComponent={
                      <div className="d-flex flex-wrap justify-content-end align-items-center w-100 gap-2">
                        <input
                          type="text"
                          placeholder="Search taxpayer..."
                          className="form-control"
                          style={{ width: "250px" }}
                          value={searchInput}
                          onChange={(e) => setSearchInput(e.target.value)}
                        />

                        <DataTableExport data={riskRecords} filename="Taxpayer Profile" showExcel={false} />
                      </div>
                    }
                  />

                  <div className="d-flex flex-wrap justify-content-between align-items-center gap-3 mt-3">
                    <div className="small text-muted">
                      Showing {showingStart.toLocaleString()}-{showingEnd.toLocaleString()} of {totalRecords.toLocaleString()} records
                    </div>

                    <div
                      className="d-flex align-items-center gap-1"
                      style={{
                        flexWrap: "nowrap",
                        overflowX: "auto",
                        whiteSpace: "nowrap",
                        maxWidth: "100%",
                        paddingBottom: "2px",
                      }}
                    >
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={!hasPrevious}
                        onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                        style={{ minWidth: "72px", flexShrink: 0 }}
                      >
                        Prev
                      </Button>

                      {visiblePages.map((pageNumber) => (
                        <Button
                          key={pageNumber}
                          size="small"
                          variant={pageNumber === currentPage ? "contained" : "outlined"}
                          onClick={() => setCurrentPage(pageNumber)}
                          style={{ minWidth: "40px", flexShrink: 0, paddingInline: "10px" }}
                        >
                          {pageNumber}
                        </Button>
                      ))}

                      <Button
                        size="small"
                        variant="outlined"
                        disabled={!hasNext}
                        onClick={() => setCurrentPage((page) => Math.min(page + 1, totalPages || 1))}
                        style={{ minWidth: "72px", flexShrink: 0 }}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>
      </div>

      <Dialog open={openReasonDialog} onClose={() => setOpenReasonDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle style={{ fontWeight: "bold", color: "#D2122E", display: "flex", alignItems: "center", gap: 8 }}>
          <WarningAmberIcon />
          {reasonDialogTitle}
        </DialogTitle>
        <DialogContent dividers>
          {fraudReasonLoading ? (
            <div className="text-center py-4">
              <CircularProgress size={28} />
            </div>
          ) : fraudReasonError ? (
            <div className="alert alert-danger mb-0">{fraudReasonError}</div>
          ) : fraudReasons.length === 0 ? (
            <Typography variant="body2">No fraud reasons found for this taxpayer.</Typography>
          ) : (
            fraudReasons.map((item) => {
              const accordionKey = `${fraudReasonTin}-${item.year}-${item.month ?? "annual"}`;
              return (
                <Accordion key={accordionKey} defaultExpanded={accordionKey === `${fraudReasonTin}-${fraudReasons[0].year}-${fraudReasons[0].month ?? "annual"}`}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography fontWeight={600}>{monthLabel(item.year, item.month)}</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <FraudReasonContent message={item.fraud_reason} typographyVariant="body2" />
                  </AccordionDetails>
                </Accordion>
              );
            })
          )}
        </DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={() => setOpenReasonDialog(false)}>
            Close
          </Button>
        </DialogActions>
      </Dialog>

      {(selectedTaxpayer.length > 0 || historyLoading || historyError) && (
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
                <h5 className="modal-title">Taxpayer Details {selectedTin ? `- ${selectedTin}` : ""}</h5>
                <button
                  className="btn-close"
                  onClick={() => {
                    setSelectedTaxpayer([]);
                    setSelectedTin("");
                    setExpandedHistoryYear("");
                    setHistoryError("");
                  }}
                />
              </div>
              <div className="modal-body">
                {historyLoading ? (
                  <div className="text-center py-4">
                    <CircularProgress size={28} />
                  </div>
                ) : historyError ? (
                  <div className="alert alert-danger mb-0">{historyError}</div>
                ) : (
                  <div>
                    {historyByYear.map(({ year, rows }) => {
                      const isExpanded = expandedHistoryYear === year;
                      return (
                        <Accordion
                          key={year}
                          expanded={isExpanded}
                          onChange={(_, expanded) => setExpandedHistoryYear(expanded ? year : "")}
                        >
                          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography fontWeight={600}>{`${year} (${rows.length} ${rows.length === 1 ? "Month" : "Months"})`}</Typography>
                          </AccordionSummary>
                          <AccordionDetails>
                            <div className="table-responsive">
                              <table className="table table-bordered mb-0">
                                <thead>
                                  <tr>
                                    <th>Year</th>
                                    <th>Month</th>
                                    <th>Income</th>
                                    <th>Tax</th>
                                    <th>Segment</th>
                                    <th>Flag</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {rows.map((row) => (
                                    <tr key={row.row_key}>
                                      <td>{row.tax_period_year || "-"}</td>
                                      <td>{row.tax_period_month ?? "-"}</td>
                                      <td>{row.total_sales_income ?? "-"}</td>
                                      <td>{row.gst_payable ?? "-"}</td>
                                      <td>{row.segment_label || "-"}</td>
                                      <td>{row.flagged ?? "-"}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </AccordionDetails>
                        </Accordion>
                      );
                    })}
                  </div>
                )}
              </div>
              <div className="modal-footer">
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    setSelectedTaxpayer([]);
                    setSelectedTin("");
                    setExpandedHistoryYear("");
                    setHistoryError("");
                  }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <Footer />
    </div>
  );
}







