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
  Button,
  Tooltip,
  IconButton,
} from "@mui/material";

import DataTable from "react-data-table-component";
import DownloadIcon from "@mui/icons-material/FileDownload";
import RemoveRedEyeIcon from "@mui/icons-material/RemoveRedEye";
import Swal from "sweetalert2";

import tableCustomStyles from "../components/common/tableStyles";
import FraudReasonDialog from "../components/common/FraudReasonDialog";

import moment from "moment";
import API from "../api/api";

export default function UploadHistory() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState("");
  const [searchText, setSearchText] = useState("");

  // Fraud popup
  const [openDialog, setOpenDialog] = useState(false);
  const [fraudMessage] = useState("");

  const BASE_PATH = "/upload-history/details";

  // Fetch upload history
  useEffect(() => {
    const fetchHistory = async () => {
      setLoading(true);
      setPageError("");

      try {
        const res = await API.get(BASE_PATH);

        setRecords(res.data.records || []);
      } catch (err) {
        setPageError(err.response?.data?.message || err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchHistory();
  }, []);

  // 🔍 Filtering logic
  const filteredRecords = records.filter((row) => {
    const term = searchText.toLowerCase();
    return (
      row.file_name?.toLowerCase().includes(term) ||
      row.uploaded_by?.toLowerCase().includes(term) ||
      row.role?.toLowerCase().includes(term) ||
      row.tax_parameter?.toLowerCase().includes(term)
      // row.Tin?.toLowerCase().includes(term) ||
      // row.Taxpayer_Name?.toLowerCase().includes(term) ||
      // row.Risk_Type?.toLowerCase().includes(term) ||
      // row.Fraud?.toLowerCase().includes(term) ||
      // row.date?.toLowerCase().includes(term)
    );
  });

  // 📊 DataTable Columns
  const columns = [
    {
      name: "Date",
      selector: (row) => moment(row.date).format("DD-MM-YYYY"),
      sortable: true,
      width: "120px",
    },
    { name: "File Name", selector: (row) => row.file_name, grow: 2 },
    { name: "Tax Parameter", selector: (row) => row.tax_parameter },
    { name: "Uploaded By", selector: (row) => row.uploaded_by },
    { name: "Role", selector: (row) => row.role },
    
  ];

  return (
    <div className="container-fluid">
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
                Upload History
              </div>

              <Paper className="p-3">
                {loading ? (
                  <Box className="text-center p-4">
                    <CircularProgress />
                    <Typography variant="body2" className="mt-2">
                      Loading upload history...
                    </Typography>
                  </Box>
                ) : pageError ? (
                  <Alert severity="error">{pageError}</Alert>
                ) : (
                  <>
                    <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                      <Typography className="fw-bold">
                        Upload History ({filteredRecords.length})
                      </Typography>

                      <div className="d-flex gap-2">
                        <TextField
                          size="small"
                          placeholder="Search..."
                          variant="outlined"
                          onChange={(e) => setSearchText(e.target.value)}
                          value={searchText}
                          style={{ width: "250px" }}
                        />

                      </div>
                    </div>

                    <div className="table-container">
                      <DataTable
                        columns={columns}
                        data={filteredRecords}
                        customStyles={tableCustomStyles}
                        pagination
                        striped
                        highlightOnHover
                        dense
                      />
                    </div>
                  </>
                )}
              </Paper>
            </div>
          </main>
        </div>

        <Footer />
      </div>

      {/* FRAUD POPUP */}
      <FraudReasonDialog
        open={openDialog}
        handleClose={() => setOpenDialog(false)}
        message={fraudMessage}
      />
    </div>
  );
}


