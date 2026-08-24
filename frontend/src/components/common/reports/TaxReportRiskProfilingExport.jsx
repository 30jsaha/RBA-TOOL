// ✅ src/components/common/reports/TaxReportRiskProfilingExport.jsx

import DataTableExport from "../DataTableExport";

export default function TaxReportRiskProfilingExport({ summary, tin }) {
  if (!summary || !Array.isArray(summary.structured_report)) return null;

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

  const exportData = summary.structured_report.map((row) => ({
    "#NAME?": row.label,
    VALUE: row.value === "" ? "" : formatValue(row.value),
  }));

  return (
    <DataTableExport
      data={exportData}
      filename={`Taxpayer_Risk_Profiling_Report_TIN_${tin}`}
    />
  );
}
