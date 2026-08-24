import { Button } from "@mui/material";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";

const SECTION_LABELS = new Set([
  "TAXPAYER DETAILS",
  "TAX ACCOUNT DETAILS",
  "BUSINESS ADDRESS ",
  "BUSINESS ACTIVITY",
  "BUSINESS CONTACT DETAILS",
  "TAX COMPLIANCE INDICATOR FOR MAIN TAX TYPES (lodgments/Tax Account balances)",
  "ASSETS & LIABILITIES",
  "RISK ANALYSIS RESULT",
  "RECOMMENDATION",
]);


function normalizeDateInput(value) {
  if (!value) return "";
  const parts = String(value).split("-");
  if (parts.length === 3 && parts[0].length === 2 && parts[2].length === 4) {
    return `${parts[2]}-${parts[1]}-${parts[0]}`;
  }
  return String(value);
}

function formatDateDisplay(value) {
  const normalized = normalizeDateInput(value);
  const parts = normalized.split("-");
  if (parts.length === 3) {
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
  }
  return normalized || "NA";
}

function formatDisplayValue(value) {
  if (value === null || value === undefined) return "NA";
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || "NA";
  }
  if (typeof value === "number") {
    return value === 0 ? "NA" : String(value);
  }
  return String(value);
}

function findValue(rows, label) {
  const match = rows.find((row) => String(row?.label || "").trim().toLowerCase() === label.toLowerCase());
  return match?.value;
}

function buildSections(rows) {
  const sections = [];
  let currentSection = null;

  rows.forEach((row) => {
    const label = String(row?.label || "");
    const isSection = SECTION_LABELS.has(label) && (row?.value === "" || row?.value === null || row?.value === undefined);

    if (isSection) {
      currentSection = {
        title: label.trim(),
        rows: [],
      };
      sections.push(currentSection);
      return;
    }

    if (!currentSection) {
      currentSection = {
        title: "TAXPAYER DETAILS",
        rows: [],
      };
      sections.push(currentSection);
    }

    currentSection.rows.push({
      label,
      value: row?.value,
    });
  });

  return sections.filter((section) => section.rows.length > 0);
}

function sectionTitle(title) {
  const map = {
    "BUSINESS ADDRESS": "BUSINESS ADDRESS",
    "TAX COMPLIANCE INDICATOR FOR MAIN TAX TYPES (lodgments/Tax Account balances)": "TAX COMPLIANCE INDICATORS",
    "RISK ANALYSIS RESULT": "RISK ANALYSIS",
  };
  return map[title] || title;
}

function sectionHeaders(title) {
  if (title === "RISK ANALYSIS RESULT") {
    return [["Tax Type", "Risk"]];
  }
  if (title === "RECOMMENDATION") {
    return [["Tax Type", "Recommendation"]];
  }
  if (title === "TAX COMPLIANCE INDICATOR FOR MAIN TAX TYPES (lodgments/Tax Account balances)") {
    return [["Indicator", "Value"]];
  }
  if (title === "ASSETS & LIABILITIES") {
    return [["Item", "Value"]];
  }
  return [["Field", "Value"]];
}

function taxTypeFromLabel(label, suffix) {
  return String(label || "").replace(suffix, "").trim() || String(label || "");
}

function sectionBody(section) {
  if (section.title === "RISK ANALYSIS RESULT") {
    return section.rows.map((row) => [
      taxTypeFromLabel(row.label, "Risk Identified"),
      formatDisplayValue(row.value),
    ]);
  }

  if (section.title === "RECOMMENDATION") {
    return section.rows.map((row) => [
      taxTypeFromLabel(row.label, "Recommendation"),
      formatDisplayValue(row.value),
    ]);
  }

  return section.rows.map((row) => [row.label, formatDisplayValue(row.value)]);
}

function riskTextColor(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "high") return [185, 28, 28];
  if (normalized === "medium") return [194, 120, 3];
  if (normalized === "low") return [21, 128, 61];
  return [107, 114, 128];
}

export default function TaxReportRiskProfilingPDFExport({
  summary,
  tin,
  startDate,
  endDate,
}) {
  const handleDownloadPDF = () => {
    if (!summary) {
      alert("No data found!");
      return;
    }

    if (!tin) {
      alert("TIN is required.");
      return;
    }

    if (!startDate || !endDate) {
      alert("Date range is required.");
      return;
    }

    const structuredReport = summary?.structured_report || [];
    const sections = buildSections(structuredReport);
    const taxpayerName = formatDisplayValue(findValue(structuredReport, "Taxpayer Name"));
    const reportingPeriod = `${formatDateDisplay(startDate)} to ${formatDateDisplay(endDate)}`;
    const generatedOn = new Date().toLocaleString("en-GB", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });

    const doc = new jsPDF({ unit: "mm", format: "a4" });
    const totalPagesExp = "{total_pages_count_string}";
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const marginX = 14;
    const headerBottomY = 50;

    const drawPageChrome = () => {
      const currentPage = doc.internal.getNumberOfPages();

      doc.setDrawColor(180, 180, 180);
      doc.setLineWidth(0.3);
      doc.rect(marginX, 10, pageWidth - marginX * 2, 36);
      doc.line(marginX, 21, pageWidth - marginX, 21);

      doc.setFont("helvetica", "bold");
      doc.setFontSize(16);
      doc.text("RBA TOOL", marginX + 4, 17);
      doc.setFontSize(12);
      doc.text("Tax Compliance Report", marginX + 4, 26);

      doc.setFont("helvetica", "normal");
      doc.setFontSize(9);
      const metaLeftX = marginX + 4;
      const metaRightX = pageWidth / 2 + 8;
      doc.text(`TIN: ${formatDisplayValue(tin)}`, metaLeftX, 33);
      doc.text(`Taxpayer Name: ${taxpayerName}`, metaLeftX, 39);
      doc.text(`Reporting Period: ${reportingPeriod}`, metaRightX, 33);
      doc.text(`Generated On: ${generatedOn}`, metaRightX, 39);

      doc.setDrawColor(180, 180, 180);
      doc.line(marginX, pageHeight - 12, pageWidth - marginX, pageHeight - 12);
      doc.setFontSize(8.5);
      doc.text("Generated by RBA Tool", marginX, pageHeight - 7);
      doc.text(`Page ${currentPage} of ${totalPagesExp}`, pageWidth - marginX, pageHeight - 7, { align: "right" });
    };

    const prepareSectionStart = (startY) => {
      if (startY > pageHeight - 35) {
        doc.addPage();
        return 58;
      }
      return startY;
    };

    const renderSection = (section, startY) => {
      const title = sectionTitle(section.title);
      const tableHead = sectionHeaders(section.title);
      const tableBody = sectionBody(section);
      const safeStartY = prepareSectionStart(startY);

      doc.setFillColor(236, 239, 241);
      doc.setDrawColor(180, 180, 180);
      doc.rect(marginX, safeStartY, pageWidth - marginX * 2, 8, "FD");
      doc.setFont("helvetica", "bold");
      doc.setFontSize(10.5);
      doc.text(title, marginX + 3, safeStartY + 5.4);

      autoTable(doc, {
        startY: safeStartY + 8,
        margin: { left: marginX, right: marginX, top: 58, bottom: 18 },
        head: tableHead,
        body: tableBody,
        theme: "grid",
        styles: {
          font: "helvetica",
          fontSize: 9,
          cellPadding: 2.4,
          overflow: "linebreak",
          lineColor: [190, 190, 190],
          lineWidth: 0.2,
          textColor: [40, 40, 40],
          valign: "top",
        },
        headStyles: {
          fillColor: [245, 245, 245],
          textColor: [33, 33, 33],
          fontStyle: "bold",
          lineColor: [180, 180, 180],
          lineWidth: 0.25,
        },
        columnStyles: {
          0: { cellWidth: 62, fontStyle: "bold" },
          1: { cellWidth: "auto" },
        },
        didParseCell: (hook) => {
          if (section.title === "RISK ANALYSIS RESULT" && hook.section === "body" && hook.column.index === 1) {
            hook.cell.styles.textColor = riskTextColor(hook.cell.raw);
            hook.cell.styles.fontStyle = "bold";
          }
        },
        didDrawPage: drawPageChrome,
      });

      return (doc.lastAutoTable?.finalY || safeStartY + 20) + 8;
    };

    drawPageChrome();
    let cursorY = headerBottomY + 8;
    sections.forEach((section) => {
      cursorY = renderSection(section, cursorY);
    });

    if (typeof doc.putTotalPages === "function") {
      doc.putTotalPages(totalPagesExp);
    }

    doc.save(`Risk_Profile_${tin}.pdf`);
  };

  return (
    <Button
      variant="contained"
      color="error"
      size="small"
      startIcon={<PictureAsPdfIcon />}
      onClick={handleDownloadPDF}
    >
      PDF
    </Button>
  );
}

