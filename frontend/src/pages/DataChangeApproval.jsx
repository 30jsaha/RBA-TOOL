// ✅ src/pages/DataChangeApproval.jsx

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
import DataTableExport from "../components/common/DataTableExport";
import API from "../api/api";
import DataChangeDetailView from "../components/DataChangeDetailView";

const monthNames = [
  "", "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

export default function DataChangeApproval() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const [records, setRecords] = useState([]);
  const [selectedRecord, setSelectedRecord] = useState(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchText, setSearchText] = useState("");
  const [category, setCategory] = useState("gst");

  const BASE_PATH = "/temp-records/recent";

  // ---------------- Fetch Records ----------------
  const fetchRecords = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await API.get(BASE_PATH, {
        params: { type: category },
      });
      setRecords(res.data.records || []);
    } catch (err) {
      setError(err.response?.data?.message || err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRecords();
  }, [category]);

  // ---------------- Approve / Reject ----------------
  // const handleApprove = async (fields) => {
  //   try {
  //     await API.post(`/temp-records/${selectedRecord.id}/action`, {
  //       status: "Approved",
  //       fields,
  //     });
  //     setSelectedRecord(null);
  //     fetchRecords();
  //   } catch (err) {
  //     alert(err.response?.data?.message || err.message);
  //   }
  // };

  // const handleReject = async (fields) => {
  //   try {
  //     await API.post(`/temp-records/${selectedRecord.id}/action`, {
  //       status: "Disapproved",
  //       fields,
  //     });
  //     setSelectedRecord(null);
  //     fetchRecords();
  //   } catch (err) {
  //     alert(err.response?.data?.message || err.message);
  //   }
  // };

  // ---------------- Approve / Reject ----------------
  const handleStatusUpdate = async (statusValue) => {
    try {
      await API.post("/temp-records/update-status", {
        type: category,
        id: selectedRecord.id,
        status: statusValue, // 1 = approve, 2 = reject
      });

      setSelectedRecord(null);
      fetchRecords(); // refresh list
    } catch (err) {
      alert(err.response?.data?.message || err.message);
    }
  };

  const handleApprove = () => handleStatusUpdate(1);
  const handleReject = () => handleStatusUpdate(2);

  // ---------------- Search ----------------
  const filteredRecords = records.filter((row) => {
    const t = searchText.toLowerCase();
    return (
      row.tin?.toLowerCase().includes(t) ||
      row.assessment_number?.toLowerCase().includes(t) ||
      row.tax_period_year?.toString().includes(t) ||
      row.tax_period_month?.toString().includes(t)
    );
  });

  // ---------------- Table Columns ----------------
  const columns = [
    { name: "TIN", selector: (row) => row.tin, sortable: true },
    { name: "Assessment No", selector: (row) => row.assessment_number || "-", sortable: true },
    {
      name: "Month",
      selector: (row) => monthNames[row.tax_period_month] || row.tax_period_month,
      sortable: true,
    },
    { name: "Year", selector: (row) => row.tax_period_year, sortable: true },
    { name: "Fields Changed", selector: (row) => row.total_fields_changed, sortable: true },
    {
      name: "Status",
      selector: (row) => row.status || "Pending",
      cell: (row) => (
        <span
          style={{
            fontWeight: "bold",
            color:
              row.status === "Approved"
                ? "green"
                : row.status === "Disapproved"
                ? "red"
                : "orange",
          }}
        >
          {row.status || "Pending"}
        </span>
      ),
    },
    {
      name: "View",
      cell: (row) => (
        <Button
          size="small"
          variant="contained"
          onClick={() => setSelectedRecord(row)}
        >
          View
        </Button>
      ),
      button: true,
    },
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
            <div className="header-title-page mb-3">
              Data Change Approval
            </div>

            <Paper className="p-3">
              {error && <Alert severity="error">{error}</Alert>}

              {selectedRecord ? (
                <DataChangeDetailView
                  record={selectedRecord}
                  onBack={() => setSelectedRecord(null)}
                  onApprove={handleApprove}
                  onReject={handleReject}
                />
              ) : (
                <>
                  <div className="d-flex flex-wrap justify-content-between align-items-center mb-3 gap-2">
                    <Box className="d-flex align-items-center gap-2">
                      <FormControl size="small" style={{ minWidth: 160 }}>
                        <InputLabel>Category</InputLabel>
                        <Select
                          value={category}
                          label="Category"
                          onChange={(e) => setCategory(e.target.value)}
                        >
                          <MenuItem value="gst">GST</MenuItem>
                          <MenuItem value="swt">SWT</MenuItem>
                          <MenuItem value="cit">CIT</MenuItem>
                        </Select>
                      </FormControl>

                      <Typography variant="subtitle1" className="fw-bold mb-0">
                        Total Records: {filteredRecords.length}
                      </Typography>
                    </Box>

                    <TextField
                      size="small"
                      placeholder="Search..."
                      value={searchText}
                      onChange={(e) => setSearchText(e.target.value)}
                      style={{ width: "260px", backgroundColor: "#fff" }}
                    />

                    <DataTableExport
                      data={filteredRecords}
                      filename="DataChangeApproval"
                    />
                  </div>

                  {loading ? (
                    <Box className="text-center p-4">
                      <CircularProgress />
                    </Box>
                  ) : (
                    <DataTable
                      columns={columns}
                      data={filteredRecords}
                      customStyles={tableCustomStyles}
                      pagination
                      highlightOnHover
                      striped
                      dense
                    />
                  )}
                </>
              )}
            </Paper>
          </div>
        </main>
      </div>

      <Footer />
    </div>
  );
}