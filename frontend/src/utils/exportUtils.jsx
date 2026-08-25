import ExcelJS from "exceljs";
import { saveAs } from "file-saver";

export const exportToExcel = async (data, filename = "export") => {
  const rows = Array.isArray(data) ? data : [];
  const headerKeys = rows.length > 0 ? Object.keys(rows[0] ?? {}) : [];

  const workbook = new ExcelJS.Workbook();
  const worksheet = workbook.addWorksheet("Data");

  if (headerKeys.length > 0) {
    worksheet.columns = headerKeys.map((key) => ({
      header: key,
      key,
    }));

    rows.forEach((row) => {
      const normalizedRow = Object.fromEntries(
        headerKeys.map((key) => [key, row?.[key] ?? null])
      );
      worksheet.addRow(normalizedRow);
    });
  }

  const excelBuffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([excelBuffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

  saveAs(blob, `${filename}.xlsx`);
};

export const exportToCSVOld = (data, filename = "export") => {
  exportToCSV(data, filename);
};

export const exportToCSV = (data, filename = "export", columns = []) => {
  const hasData = Array.isArray(data) && data.length > 0;
  const headerKeys =
    Array.isArray(columns) && columns.length > 0
      ? columns
      : hasData
      ? Object.keys(data[0])
      : null;

  if (!headerKeys) return;

  const header = headerKeys.join(",") + "\n";
  const rows = hasData
    ? data
        .map((obj) =>
          headerKeys
            .map((key) => `"${(obj?.[key] ?? "").toString().replace(/"/g, '""')}"`)
            .join(",")
        )
        .join("\n")
    : "";

  const csvContent = "\uFEFF" + header + rows;

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  saveAs(blob, `${filename}.csv`);
};
