// src/components/common/DataTableExport.jsx

import { Button, Stack } from "@mui/material";
import DescriptionIcon from "@mui/icons-material/Description";  // Excel icon
import TableChartIcon from "@mui/icons-material/TableChart";    // CSV icon

import { exportToExcel, exportToCSV } from "../../utils/exportUtils.jsx";

export default function DataTableExport({ data, filename, emptyMessage, showExcel = true }) {
  const hasData = Array.isArray(data) && data.length > 0;

  const handleExportExcel = async () => {
    if (!hasData) {
      if (emptyMessage) {
        alert(emptyMessage);
      }
      return;
    }
    await exportToExcel(data, filename);
  };

  const handleExportCSV = () => {
    if (!hasData) {
      if (emptyMessage) {
        alert(emptyMessage);
      }
      return;
    }
    exportToCSV(data, filename);
  };

  return (
    <Stack direction="row" spacing={1}>
      {showExcel ? (
        <Button
          variant="contained"
          size="small"
          color="success"
          startIcon={<DescriptionIcon />}
          onClick={handleExportExcel}
          className="hideme"
        >
          Excel
        </Button>
      ) : null}

      <Button
        variant="outlined"
        size="small"
        color="primary"
        startIcon={<TableChartIcon />}
        onClick={handleExportCSV}
        className="hideme"
      >
        CSV
      </Button>
    </Stack>
  );
}

