// src/pages/RecentUpload.jsx

import { useState } from "react";
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchText, setSearchText] = useState("");
  const [category, setCategory] = useState("gst");
  const [draftStartDate, setDraftStartDate] = useState("");
  const [draftEndDate, setDraftEndDate] = useState("");
  const [appliedStartDate, setAppliedStartDate] = useState("");
  const [appliedEndDate, setAppliedEndDate] = useState("");
  const [hasSubmitted, setHasSubmitted] = useState(false);

  const BASE_PATH = "/predicted-records/recent-uploads";

  const fetchRecent = async ({ startDate, endDate, search } = {}) => {
    setLoading(true);
    setError("");

    try {
      const params = {
        tax_type: category,
        search: search || undefined,
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

    } catch (err) {
      setError(err.response?.data?.message || err.message);
      setRecords([]);
      setTotalRecords(0);
    } finally {
      setLoading(false);
    }
  };

  const isDateFilterDirty =
    draftStartDate !== appliedStartDate || draftEndDate !== appliedEndDate;

  const handleSubmitDates = () => {
    if (loading || !isDateFilterDirty) return;

    if (
      draftStartDate &&
      draftEndDate &&
      dayjs(draftEndDate).isBefore(dayjs(draftStartDate), "day")
    ) {
      setError("End date must be on or after the start date.");
      return;
    }

    setError("");
    setHasSubmitted(true);
    setAppliedStartDate(draftStartDate);
    setAppliedEndDate(draftEndDate);
    fetchRecent({
      startDate: draftStartDate,
      endDate: draftEndDate,
      search: searchText,
    });
  };

  const handleDownloadCSV = async () => {
    setError("");

    try {
      const csvUrl = "/upload-history/recent-uploads/download-csv";
      const params = {
        tax_type: category,
        search: searchText || undefined,
        start_date: appliedStartDate || undefined,
        end_date: appliedEndDate || undefined,
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

  const filteredRecords = records.filter((row) => {
    const query = searchText.trim().toLowerCase();
    if (!query) return true;

    return [row.tin, row.taxpayer_name, row.tax_period_year]
      .some((value) => String(value ?? "").toLowerCase().includes(query));
  });

  const columns = [
    { name: "TIN", selector: (row) => row.tin, sortable: true, width: "110px", minWidth: "100px", wrap: true },
    { name: "Taxpayer Name", selector: (row) => row.taxpayer_name, sortable: true, wrap: true, width: "240px", minWidth: "220px", grow: 2 },
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
      width: "115px",
      minWidth: "110px",
      wrap: true,
    },
    { name: "Type", selector: (row) => row.taxpayer_type, sortable: true, width: "120px", minWidth: "120px", wrap: true },
    { name: "Tax Account No", selector: (row) => row.tax_account_number || "-", sortable: true, width: "160px", minWidth: "150px", wrap: true },
    { name: "Month", selector: (row) => row.tax_period_month ?? "-", sortable: true, width: "90px", minWidth: "90px", wrap: true },
    { name: "Year", selector: (row) => row.tax_period_year ?? "-", sortable: true, width: "90px", minWidth: "90px", wrap: true },
  ];

  return (
    <div className="row" style={{ width: "100%", marginLeft: 0, marginRight: 0 }}>
      <Header toggleSidebar={() => setCollapsed(!collapsed)} />
      <div className="col-lg-12 col-md-12" style={{ minWidth: 0, maxWidth: "100%" }}>
        <Sidebar
          collapsed={collapsed}
          setCollapsed={setCollapsed}
          openMenu={openMenu}
          setOpenMenu={setOpenMenu}
        />

        <main className="main-content flex-grow-1 p-4 mt-5" style={{ minWidth: 0, maxWidth: "100%" }}>
          <div className="container-fluid">
            <div className="header-title-page mb-3">Recent Uploads</div>

            <Paper className="p-3" sx={{ maxWidth: "100%", minWidth: 0 }}>
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
                        setDraftStartDate("");
                        setDraftEndDate("");
                        setAppliedStartDate("");
                        setAppliedEndDate("");
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
                      value={draftStartDate ? dayjs(draftStartDate) : null}
                      onChange={(newValue) => {
                        if (!newValue || !newValue.isValid()) return;

                        const year = newValue.year();
                        if (year < 1900 || year > 2100) return;

                        setDraftStartDate(newValue.format("YYYY-MM-DD"));
                      }}
                      slotProps={{
                        textField: {
                          fullWidth: true,
                          size: "small",
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
                      value={draftEndDate ? dayjs(draftEndDate) : null}
                      onChange={(newValue) => {
                        if (!newValue || !newValue.isValid()) return;

                        const year = newValue.year();
                        if (year < 1900 || year > 2100) return;

                        setDraftEndDate(newValue.format("YYYY-MM-DD"));
                      }}
                      slotProps={{
                        textField: {
                          fullWidth: true,
                          size: "small",
                        }
                      }}
                    />
                  </LocalizationProvider>
                  <Button
                    size="small"
                    variant="contained"
                    onClick={handleSubmitDates}
                    disabled={loading || !isDateFilterDirty}
                  >
                    Submit
                  </Button>
                </Box>
              </div>

              <div className="d-flex flex-wrap justify-content-between align-items-center mb-3 gap-2">
                <Box>
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
                  <Alert severity="info" icon={false} sx={{ mt: 1, py: 0, px: 1.5, fontSize: "0.8rem" }}>
                    Select the required date range and click Submit to apply the filter.
                    {isDateFilterDirty ? " Pending changes." : ""}
                  </Alert>
                </Box>

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
                <div className="table-container" style={{ overflowX: "auto" }}>
                  <DataTable
                    columns={columns}
                    customStyles={tableCustomStyles}
                    pagination
                    highlightOnHover
                    striped
                    dense
                    responsive
                    data={filteredRecords}
                    noDataComponent={
                      hasSubmitted
                        ? "No records available for the selected criteria"
                        : "Please select a date range and click Submit."
                    }
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
