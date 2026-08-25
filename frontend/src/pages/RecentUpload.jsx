// src/pages/RecentUpload.jsx

import { useEffect, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import {
  Paper,
  CircularProgress,
  Alert,
  Typography,
  Box,
  TextField,
  FormControl,
  Select,
  MenuItem,
  InputLabel,
  Button,
} from "@mui/material";
import DataTable from "react-data-table-component";
import tableCustomStyles from "../components/common/tableStyles";
import API from "../api/api";
import dayjs from "dayjs";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";

export default function RecentUpload() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const [records, setRecords] = useState([]);
  const [totalRecords, setTotalRecords] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchText, setSearchText] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [category, setCategory] = useState("gst");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [userTouchedDate, setUserTouchedDate] = useState(false);

  const BASE_PATH = "/predicted-records/recent-uploads";

  const deriveRangeFromRecords = (rows) => {
    if (!rows || !rows.length) return null;

    let latestYear = null;
    let latestMonth = null;

    rows.forEach((row) => {
      const year = Number(row.tax_period_year);
      const month = row.tax_period_month === null || row.tax_period_month === undefined
        ? null
        : Number(row.tax_period_month);

      if (!Number.isFinite(year)) return;

      if (latestYear === null) {
        latestYear = year;
        latestMonth = month;
        return;
      }

      const compareMonth = month ?? 12;
      const latestCompareMonth = latestMonth ?? 12;

      if (year > latestYear || (year === latestYear && compareMonth > latestCompareMonth)) {
        latestYear = year;
        latestMonth = month;
      }
    });

    if (latestYear === null) return null;

    if (latestMonth === null || latestMonth === undefined) {
      return {
        start: `${latestYear}-01-01`,
        end: `${latestYear}-12-31`,
      };
    }

    const monthStr = String(latestMonth).padStart(2, "0");
    const start = `${latestYear}-${monthStr}-01`;
    const endDateObj = new Date(latestYear, latestMonth, 0);
    const endMonthStr = String(latestMonth).padStart(2, "0");
    const endDayStr = String(endDateObj.getDate()).padStart(2, "0");
    return {
      start,
      end: `${latestYear}-${endMonthStr}-${endDayStr}`,
    };
  };

  const fetchRecent = async () => {
    setLoading(true);
    setError("");

    try {
      const params = {
        tax_type: category,
        search: debouncedSearch || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      };

      const res = await API.get(BASE_PATH, { params });

      const rows = res.data.records || [];
      setRecords(
        rows.map((row) => ({
          ...row,
          is_fraud: Number(row?.is_fraud) === 1 ? 1 : 0,
        }))
      );
      setTotalRecords(res.data.total_records || 0);

      const range = res.data.date_range || {};
      if (!userTouchedDate) {
        if (range.start_date && range.end_date) {
          setStartDate(range.start_date);
          setEndDate(range.end_date);
        } else {
          const derived = deriveRangeFromRecords(rows);
          if (derived?.start && derived?.end) {
              setStartDate(derived.start);
            setEndDate(derived.end);
          }
        }
      }
    } catch (err) {
      setError(err.response?.data?.message || err.message);
      setRecords([]);
      setTotalRecords(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const handle = setTimeout(() => {
      setDebouncedSearch(searchText);
    }, 400);

    return () => clearTimeout(handle);
  }, [searchText]);

  useEffect(() => {
    fetchRecent();
  }, [category, startDate, endDate, debouncedSearch]);

  const handleDownloadCSV = async () => {
    setError("");

    try {
      const csvUrl = "/upload-history/recent-uploads/download-csv";
      const params = {
        tax_type: category,
        search: debouncedSearch || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      };
      const response = await API.get(csvUrl, {
        params,
        withCredentials: true,
        responseType: "blob",
      });

      const disposition = response?.headers?.["content-disposition"] || "";
      const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
      const filename = filenameMatch?.[1] || "recent_uploads.csv";
      const blob = new Blob([response.data], { type: response.data?.type || "text/csv" });
      const objectUrl = window.URL.createObjectURL(blob);

      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (err) {
      setError(err.response?.data?.message || err.message || "Download failed.");
    }
  };

  const columns = [
    { name: "TIN", selector: (row) => row.tin, sortable: true, width: "120px" },
    { name: "Taxpayer Name", selector: (row) => row.taxpayer_name, sortable: true, wrap: true, grow: 1.5 },
    {
      name: "Is Fraud",
      cell: (row) => {
        const isFraud = Number(row?.is_fraud) === 1;
        return (
          <span className={isFraud ? "text-danger fw-bold" : "text-success fw-bold"}>
            {isFraud ? "YES" : "NO"}
          </span>
        );
      },
      sortable: true,
      width: "90px",
    },
    { name: "Type", selector: (row) => row.taxpayer_type, sortable: true },
    { name: "Tax Account No", selector: (row) => row.tax_account_number || "-", sortable: true },
    { name: "Month", selector: (row) => row.tax_period_month ?? "-", sortable: true },
    { name: "Year", selector: (row) => row.tax_period_year ?? "-", sortable: true },
  ];

  return (
    <div className="row">
      <Header toggleSidebar={() => setCollapsed(!collapsed)} />
      <div className="col-lg-12 col-md-12">
        <Sidebar
          collapsed={collapsed}
          setCollapsed={setCollapsed}
          openMenu={openMenu}
          setOpenMenu={setOpenMenu}
        />

        <main className="main-content flex-grow-1 p-4 mt-5">
          <div className="container-fluid">
            <div className="header-title-page mb-3">Recent Uploads</div>

            <Paper className="p-3">
              {error && <Alert severity="error" className="mb-3">{error}</Alert>}

              <div className="d-flex flex-wrap justify-content-between align-items-center mb-3 gap-3">
                <Box className="d-flex align-items-center gap-2">
                  <FormControl size="small" style={{ minWidth: 160 }}>
                    <InputLabel>Category</InputLabel>
                    <Select
                      value={category}
                      label="Category"
                      onChange={(e) => {
                        setCategory(e.target.value);
                        setUserTouchedDate(false);
                        setStartDate("");
                        setEndDate("");
                      }}
                    >
                      <MenuItem value="all">All</MenuItem>
                      <MenuItem value="gst">GST</MenuItem>
                      <MenuItem value="swt">SWT</MenuItem>
                      <MenuItem value="cit">CIT</MenuItem>
                    </Select>
                  </FormControl>

                  <Typography variant="subtitle1" className="fw-bold mb-0">
                    Total Records: {totalRecords}
                  </Typography>
                </Box>

                <Box className="d-flex align-items-center gap-2 flex-wrap">
                  <Typography variant="subtitle1" className="fw-bold mb-0">
                    Date Range:
                  </Typography>
                  <LocalizationProvider dateAdapter={AdapterDayjs}>
                    <DatePicker
                      label="Start Date"
                      format="DD/MM/YYYY"
                      value={startDate ? dayjs(startDate) : null}
                      onChange={(newValue) => {
                        if (!newValue || !newValue.isValid()) return;

                        const year = newValue.year();
                        if (year < 1900 || year > 2100) return;

                        setStartDate(newValue.format("YYYY-MM-DD"));
                        setUserTouchedDate(true);
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
                  <Typography variant="subtitle1" className="mb-0">
                    to
                  </Typography>
                  <LocalizationProvider dateAdapter={AdapterDayjs}>
                    <DatePicker
                      label="End Date"
                      format="DD/MM/YYYY"
                      value={endDate ? dayjs(endDate) : null}
                      onChange={(newValue) => {
                        if (!newValue || !newValue.isValid()) return;

                        const year = newValue.year();
                        if (year < 1900 || year > 2100) return;

                        setEndDate(newValue.format("YYYY-MM-DD"));
                        setUserTouchedDate(true);
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
                </Box>
              </div>

              <div className="d-flex flex-wrap justify-content-between align-items-center mb-3 gap-2">
                <TextField
                  size="small"
                  placeholder="Search TIN / Company / Year..."
                  variant="outlined"
                  onChange={(e) => setSearchText(e.target.value)}
                  value={searchText}
                  style={{
                    width: "260px",
                    backgroundColor: "#fff",
                    borderRadius: "6px",
                  }}
                />

                <Button
                  variant="contained"
                  color="success"
                  size="small"
                  onClick={handleDownloadCSV}
                  disabled={loading}
                >
                  Download CSV
                </Button>
              </div>

              {loading ? (
                <Box className="text-center p-4">
                  <CircularProgress />
                  <Typography variant="body2" className="mt-2">
                    Loading recent uploads...
                  </Typography>
                </Box>
              ) : (
                <div className="table-container">
                  <DataTable
                    columns={columns}
                    data={records}
                    customStyles={tableCustomStyles}
                    pagination
                    highlightOnHover
                    striped
                    dense
                    noDataComponent="There is no record to display"
                  />
                </div>
              )}
            </Paper>
          </div>
        </main>
      </div>

      <Footer />
    </div>
  );
}
