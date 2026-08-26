import { Button, Stack } from "@mui/material";
import TableChartIcon from "@mui/icons-material/TableChart";

import { exportToCSV } from "../../utils/exportUtils.jsx";

export default function DataTableExport({ data, filename, emptyMessage }) {
  const hasData = Array.isArray(data) && data.length > 0;

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
