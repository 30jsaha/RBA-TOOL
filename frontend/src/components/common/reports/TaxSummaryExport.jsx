// src/components/reports/TaxSummaryExport.jsx

import DataTableExport from "../DataTableExport";

export default function TaxSummaryExport({ summary, tin }) {
  if (!summary) return null;

  const exportData = [
    // ---- GST ANALYSIS ----
    { Section: "GST ANALYSIS", Field: "", Value: "" },

    // ---- Overview ----
    { Section: "Overview", Field: "Total Records", Value: summary.overview?.total_records },
    { Section: "Overview", Field: "Total Months Filed", Value: summary.overview?.total_months_filed },
    { Section: "Overview", Field: "Total Input Credit", Value: summary.overview?.total_input_credit },
    { Section: "Overview", Field: "Total Output Debit", Value: summary.overview?.total_output_debit },
    { Section: "Overview", Field: "Total Net Tax", Value: summary.overview?.total_net_tax },
    { Section: "Overview", Field: "Average Monthly Tax", Value: summary.overview?.average_monthly_tax },

    // ---- Payable vs Refundable ----
    { Section: "Payable vs Refundable", Field: "Total Payable", Value: summary.payable_vs_refundable?.total_payable },
    { Section: "Payable vs Refundable", Field: "Total Refundable", Value: summary.payable_vs_refundable?.total_refundable },

    // ---- Input vs Output ----
    { Section: "Input vs Output", Field: "Total Input Credit", Value: summary.input_vs_output?.total_input_credit },
    { Section: "Input vs Output", Field: "Total Output Debit", Value: summary.input_vs_output?.total_output_debit },
    { Section: "Input vs Output", Field: "Ratio (Input/Output)", Value: summary.input_vs_output?.ratio_input_output },

    // ---- Compliance Metrics ----
    { Section: "Compliance Metrics", Field: "Payment Delay Count", Value: summary.compliance_metrics?.payment_delay_count },
    { Section: "Compliance Metrics", Field: "Average Delay Days", Value: summary.compliance_metrics?.average_delay_days },

    // ---- Fraud Summary ----
    { Section: "Fraud Summary", Field: "Total Fraud Cases", Value: summary.fraud_summary?.total_fraud_cases },
    { Section: "Fraud Summary", Field: "Fraud Percentage", Value: summary.fraud_summary?.fraud_percentage },
    { Section: "Fraud Summary", Field: "Fraud Reasons", Value: summary.fraud_summary?.fraud_reasons || "N/A" },
  ];

  return (
    <DataTableExport
      data={exportData}
      filename={`Tax_Compliance_Report_TIN_${tin}`}
    />
  );
}
