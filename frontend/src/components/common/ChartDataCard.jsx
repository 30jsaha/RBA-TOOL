import { Box, Button } from "@mui/material";
import TableChartIcon from "@mui/icons-material/TableChart";
import BarChartIcon from "@mui/icons-material/BarChart";

import EmptyState from "./EmptyState";

export default function ChartDataCard({
  title,
  isChartView,
  onToggleView,
  onDownloadCsv,
  loading,
  hasData,
  chartSkeleton,
  tableSkeleton,
  chartContent,
  tableContent,
  emptyMessage,
}) {
  return (
    <div className="card h-100">
      <div className="card-header">
        <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
          <span>{title}</span>
          <Box className="hideme" sx={{ display: "flex", gap: 1, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <Button
              size="small"
              variant="outlined"
              color="primary"
              startIcon={isChartView ? <TableChartIcon /> : <BarChartIcon />}
              onClick={onToggleView}
            >
              {isChartView ? "View Table" : "View Chart"}
            </Button>
            <Button
              size="small"
              variant="outlined"
              color="primary"
              startIcon={<TableChartIcon />}
              onClick={onDownloadCsv}
            >
              CSV
            </Button>
          </Box>
        </div>
      </div>
      <div className="card-body">
        {loading ? (
          isChartView ? chartSkeleton : tableSkeleton
        ) : !hasData ? (
          <EmptyState message={emptyMessage} />
        ) : isChartView ? (
          chartContent
        ) : (
          tableContent
        )}
      </div>
    </div>
  );
}
