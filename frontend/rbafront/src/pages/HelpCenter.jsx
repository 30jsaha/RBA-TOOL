import { useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import { Button } from "@mui/material";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import "./css/HelpCenter.css";

export default function HelpCenter() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);

  const publicBase = import.meta.env.BASE_URL || "/";
  const PDF_PATH = `${publicBase}Tax_Fraud_Detection_UserGuide_v2.pdf`;
  const DOCX_PATH = `${publicBase}Tax_Fraud_Detection_UserGuide_v2.docx`;

  const triggerDownload = (url, filename) => {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const handleDownload = async () => {
    try {
      const res = await fetch(PDF_PATH, { method: "HEAD" });
      if (res.ok) {
        triggerDownload(PDF_PATH, "Tax_Fraud_Detection_UserGuide_v2.pdf");
        return;
      }
    } catch (error) {
      // Fall back to DOCX when PDF is not available.
    }

    triggerDownload(DOCX_PATH, "Tax_Fraud_Detection_UserGuide_v2.docx");
  };

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

          <main className="main-content mt-5 help-center-main">
            <div className="help-center-scroll">
              <div className="help-center-card">
                <div className="help-center-title-row">
                  <div>
                    <div className="help-center-title">Help Centre</div>
                    <div className="help-center-subtitle">
                      Tax Fraud Detection System - User Help Guide (Version 1.0, April 2026)
                    </div>
                  </div>
                  <Button
                    variant="contained"
                    startIcon={<FileDownloadIcon />}
                    onClick={handleDownload}
                    style={{ backgroundColor: "#6A00FF" }}
                  >
                    Download PDF
                  </Button>
                </div>

                <div className="help-section">
                  <h2>Table of Contents</h2>
                  <ul className="help-list">
                    <li>1. Introduction</li>
                    <li>2. Sidebar Navigation</li>
                    <li>3. Upload Sheet</li>
                    <li>4. Dashboard</li>
                    <li>5. Analytics</li>
                    <li>6. Reports</li>
                    <li>7. Upload History</li>
                    <li>8. Error Handling</li>
                    <li>9. Best Practices</li>
                    <li>10. Complete Workflow Summary</li>
                    <li>11. Conclusion</li>
                  </ul>
                </div>

                <hr className="help-divider" />

                <div className="help-section">
                  <h2>1. Introduction</h2>
                  <p>
                    The Tax Fraud Detection System (RBA Tool) is a web-based platform designed to
                    help tax authorities identify fraudulent tax records using machine learning algorithms.
                    It processes three types of tax data (GST, SWT, and CIT) and flags suspicious submissions
                    automatically.
                  </p>

                  <h3>1.1 What You Can Do</h3>
                  <ul className="help-list">
                    <li>Upload tax data files in CSV format (GST, SWT, CIT).</li>
                    <li>Preview and validate records before processing.</li>
                    <li>Detect fraudulent or suspicious entries using ML algorithms.</li>
                    <li>View analytics dashboards by tax parameter.</li>
                    <li>Perform risk assessment and taxpayer risk profiling.</li>
                    <li>Generate taxpayer segmentation reports.</li>
                    <li>Track all upload activity in Upload History.</li>
                  </ul>

                  <h3>1.2 Supported Tax Parameters</h3>
                  <ul className="help-list">
                    <li>GST - Goods and Services Tax</li>
                    <li>SWT - Salary and Wages Tax</li>
                    <li>CIT - Company Income Tax</li>
                  </ul>
                </div>

                <div className="help-section">
                  <h2>2. Sidebar Navigation</h2>
                  <p>The left sidebar is the primary navigation element. Click any item to navigate directly.</p>
                  <table className="help-table">
                    <thead>
                      <tr>
                        <th>Menu Item</th>
                        <th>Sub-Items</th>
                        <th>Purpose</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>Dashboard</td>
                        <td>Dashboard, GST, SWT, CIT</td>
                        <td>High-level analytics and fraud summaries per tax type</td>
                      </tr>
                      <tr>
                        <td>Upload Sheets</td>
                        <td>-</td>
                        <td>Upload, validate, and process GST/SWT/CIT CSV files</td>
                      </tr>
                      <tr>
                        <td>Analytics</td>
                        <td>Risk Assessment, Risk Profiling, Compliance</td>
                        <td>In-depth risk analytics and taxpayer profiling</td>
                      </tr>
                      <tr>
                        <td>Reports</td>
                        <td>Recent Uploads, Taxpayer Profile, Risk Profiling</td>
                        <td>Detailed reports on processed records and fraud findings</td>
                      </tr>
                      <tr>
                        <td>Upload History</td>
                        <td>-</td>
                        <td>Full log of all uploaded files with metadata</td>
                      </tr>
                      <tr>
                        <td>Help Centre</td>
                        <td>-</td>
                        <td>User documentation and support</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="help-section">
                  <h2>3. Upload Sheet</h2>
                  <p>
                    The Upload Sheet module is the core feature of the RBA Tool. It allows analysts to upload
                    tax data files, validate records, run ML-based fraud detection, and generate segmentation.
                    All three tax types (GST, SWT, CIT) must be uploaded and processed before segmentation can be created.
                  </p>
                  <div className="help-note">
                    Important: Always upload all three tax files (GST, SWT, CIT) before clicking Create Segmentation.
                  </div>

                  <h3>3.1 Accessing the Upload Sheet</h3>
                  <ul className="help-list">
                    <li>Log in to the RBA Tool.</li>
                    <li>Click Upload Sheets in the left sidebar.</li>
                    <li>The Upload Sheet page opens with GST selected by default.</li>
                  </ul>

                  <h3>3.2 Downloading Sample Files</h3>
                  <ul className="help-list">
                    <li>Sample CSV templates are available at the top-right corner of the page.</li>
                    <li>Download the samples to understand the required column structure.</li>
                    <li>SAMPLE GST, SAMPLE SWT, and SAMPLE CIT templates are provided.</li>
                  </ul>

                  <h3>3.3 Uploading GST Data</h3>
                  <ul className="help-list">
                    <li>
                      Step 1 - Select Tax Parameter and Date Range.<br />
                      Choose GST from the dropdown and set the assessed dates.
                    </li>
                    <li>
                      Step 2 - Upload the CSV File.<br />
                      Drag and drop the GST CSV file or click inside the upload area. Only CSV files are accepted.
                    </li>
                    <li>
                      Step 3 - Preview the File.<br />
                      Click Show Preview to review the first 10 rows.
                    </li>
                    <li>
                      Step 4 - Upload and Validate.<br />
                      Click Upload & Validate. The system checks missing TINs and duplicates and shows totals.
                    </li>
                    <li>
                      Step 5 - Download Invalid Records (if applicable).<br />
                      If invalid records are detected, download the invalid rows for correction.
                    </li>
                    <li>
                      Step 6 - Process the Data.<br />
                      Click Process to run the ML algorithm. A progress bar shows the current step.
                    </li>
                    <li>
                      Step 7 - Processing Complete.<br />
                      A success dialog confirms GST processing completion.
                    </li>
                  </ul>

                  <h3>3.4 Uploading SWT Data</h3>
                  <ul className="help-list">
                    <li>Select SWT from the tax parameter dropdown.</li>
                    <li>Set assessed dates, upload the SWT CSV, and preview the first 10 rows.</li>
                    <li>Click Upload & Validate, review invalid records if any, then click Process.</li>
                  </ul>

                  <h3>3.5 Uploading CIT Data</h3>
                  <ul className="help-list">
                    <li>Select CIT from the tax parameter dropdown.</li>
                    <li>Set assessed dates, upload, preview, validate, and process the CIT CSV file.</li>
                  </ul>

                  <h3>3.6 Creating Segmentation</h3>
                  <ul className="help-list">
                    <li>GST, SWT, and CIT must all be processed before the Create Segmentation button becomes active.</li>
                    <li>Click Create Segmentation (purple button at the top of the page).</li>
                    <li>When segmentation completes, click View to open the Final Merged Audit Summary.</li>
                  </ul>

                  <h3>3.7 Final Merged Audit Summary</h3>
                  <p>The Final Merged Audit Summary table displays combined fraud detection results for all processed records.</p>
                  <ul className="help-list">
                    <li>TIN - Tax Identification Number</li>
                    <li>Taxpayer Name - Entity name</li>
                    <li>Type - Taxpayer category</li>
                    <li>Segmentation - Large, Medium, Small</li>
                    <li>Total Sales - Reported total sales</li>
                    <li>GST Payable / GST Refund - GST amounts</li>
                    <li>Fraud - Valid or Fraud Detected</li>
                  </ul>
                  <p>
                    Fraud Flags: Valid records passed ML checks. Fraud Detected records are flagged for investigation.
                  </p>
                </div>

                <div className="help-section">
                  <h2>4. Dashboard</h2>
                  <p>
                    The Dashboard module provides analytics and fraud detection summaries. It is divided into the Common
                    Dashboard and GST, SWT, and CIT dashboards.
                  </p>

                  <h3>4.1 Common Dashboard</h3>
                  <ul className="help-list">
                    <li>Key Metrics: Total Income, Total Profit, Total CIT Tax, Effective Tax Rate.</li>
                    <li>Charts: Tax Flow, Top Sectors by Income, Fraud Cases by Year, Fraud Distribution.</li>
                    <li>Tables: Top Financial TINs and Consolidated Records.</li>
                    <li>Filtering: Use Select TIN dropdown to filter all charts and tables.</li>
                    <li>Export: Download PDF to export the dashboard view.</li>
                  </ul>

                  <h3>4.2 GST Dashboard</h3>
                  <ul className="help-list">
                    <li>Summary Cards: Total Tax Payers, Total Sales Income, Total GST Payable, Total GST Refundable.</li>
                    <li>Charts: Sales Comparison, GST Payable vs Refundable, Segmentation Distribution, Risk Flagged vs Non-Risk.</li>
                    <li>Map: Fraud TIN Distribution by Province with a risk scale (0-100%).</li>
                    <li>Export: Download PDF for GST dashboard view.</li>
                  </ul>

                  <h3>4.3 SWT Dashboard</h3>
                  <ul className="help-list">
                    <li>Summary Cards: Total Employers, Total Wages Paid, Total SWT Deducted, Effective SWT Rate.</li>
                    <li>Charts: Salary vs SWT Deducted, Fraud Cases (Monthly), Segmentation Distribution.</li>
                    <li>Map: Fraud TIN Distribution by Province with risk shading.</li>
                    <li>Table: Latest SWT Records with pagination.</li>
                  </ul>

                  <h3>4.4 CIT Dashboard</h3>
                  <ul className="help-list">
                    <li>Tables: Top 50 Net Profit and Top 50 Net Loss taxpayers.</li>
                    <li>Charts: Segmentation Distribution, Risk Flagged vs Non-Risk.</li>
                    <li>Tables: Superannuation PNG vs Foreign, Interest PNG vs Foreign.</li>
                    <li>Map: Fraud TIN Distribution by Province with risk color coding.</li>
                    <li>Table: Gross Sales vs COGS by year.</li>
                  </ul>
                </div>

                <div className="help-section">
                  <h2>5. Analytics</h2>
                  <p>
                    The Analytics module provides advanced risk analysis tools including Risk Assessment, Risk Profiling,
                    and Compliance.
                  </p>

                  <h3>5.1 Risk Assessment Dashboard</h3>
                  <ul className="help-list">
                    <li>Risk Breakdown by Category (Segment) - Total vs Flagged records.</li>
                    <li>Sector-based Risk - Taxpayers vs Risk Flagged by industry sector.</li>
                    <li>Total Taxpayers vs Risk Flagged by month.</li>
                    <li>Frequency of Risk Anomalies pie chart.</li>
                    <li>List of Risk Assessment Companies with export to CSV.</li>
                  </ul>
                  <p>How to use: Select a sector and use Download CSV to export widget data.</p>

                  <h3>5.2 Risk Profiling Dashboard</h3>
                  <ul className="help-list">
                    <li>Frequency of Risk Anomalies (Flagged vs Not Flagged).</li>
                    <li>Risk Breakdown by Category across segments.</li>
                    <li>Payable vs Refundable by industry.</li>
                    <li>Input Credits vs Output Debits by industry.</li>
                    <li>Sales Comparison Table with Excel/CSV export.</li>
                  </ul>
                  <p>Industry filtering: Use the industry dropdown to compare financial metrics across sectors.</p>
                </div>

                <div className="help-section">
                  <h2>6. Reports</h2>
                  <p>
                    The Reports module provides detailed data tables and taxpayer-specific fraud reports: Recent Uploads,
                    Taxpayer Profile, and Risk Profiling.
                  </p>

                  <h3>6.1 Recent Uploads</h3>
                  <ul className="help-list">
                    <li>Filter by tax type using the Category dropdown.</li>
                    <li>Search by TIN, Company Name, or Year.</li>
                    <li>Export using Excel or CSV buttons.</li>
                  </ul>
                  <p>Table Columns: TIN, Company Name, Type, Tax Account Number, Month/Year, Fraud Status, Fraud Reason.</p>
                  <p>
                    Viewing Fraud Reasons: Click View Reason for Fraud Detected records to open the details popup.
                  </p>

                  <h3>6.2 Taxpayer Profile</h3>
                  <ul className="help-list">
                    <li>Filter by Tax Type and date range.</li>
                    <li>Use Search taxpayer box for specific entities.</li>
                    <li>Export results using Excel or CSV.</li>
                  </ul>
                  <p>Table Columns: TIN, Taxpayer Name, Risk Score, Risk Type, Flagged, Fraud Reason.</p>
                  <p>Pagination shows up to 100 records per page by default.</p>

                  <h3>6.3 Risk Profiling Report</h3>
                  <ul className="help-list">
                    <li>Select a specific TIN/Taxpayer and date range.</li>
                    <li>Export the report using Excel, CSV, or PDF buttons.</li>
                  </ul>
                  <p>Report Sections:</p>
                  <ul className="help-list">
                    <li>GST Analysis: Overview, Payable vs Refundable, Input vs Output, Compliance Metrics, Fraud Summary.</li>
                    <li>SWT Analysis: Overview, Fraud Metrics, Fraud Patterns, Compliance Metrics.</li>
                  </ul>
                </div>

                <div className="help-section">
                  <h2>7. Upload History</h2>
                  <ul className="help-list">
                    <li>Click Upload History in the left sidebar to view all uploaded files.</li>
                    <li>Use Search to filter by file name, date, or tax parameter.</li>
                    <li>Pagination shows 10 rows per page and total upload count.</li>
                  </ul>
                  <p>Table Columns: Date, File Name, Tax Parameter, Uploaded By, Role.</p>
                </div>

                <div className="help-section">
                  <h2>8. Error Handling</h2>
                  <table className="help-table">
                    <thead>
                      <tr>
                        <th>Error Type</th>
                        <th>Description</th>
                        <th>Resolution</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>Missing TIN</td>
                        <td>Record has no Tax Identification Number.</td>
                        <td>Add the correct TIN and re-upload.</td>
                      </tr>
                      <tr>
                        <td>Duplicate TIN</td>
                        <td>Same TIN with identical tax year and month.</td>
                        <td>Remove duplicate rows before re-uploading.</td>
                      </tr>
                      <tr>
                        <td>Invalid File Format</td>
                        <td>File is not CSV or does not match column structure.</td>
                        <td>Use the sample file as a template and re-upload.</td>
                      </tr>
                      <tr>
                        <td>Upload Failure</td>
                        <td>File upload was interrupted or rejected by the server.</td>
                        <td>Check file size and format. Refresh and try again.</td>
                      </tr>
                      <tr>
                        <td>Processing Error</td>
                        <td>ML processing failed during execution.</td>
                        <td>Refresh the page and re-initiate processing. Contact admin if repeated.</td>
                      </tr>
                    </tbody>
                  </table>

                  <h3>8.1 Downloading Invalid Records</h3>
                  <ul className="help-list">
                    <li>If Invalid Records count is greater than 0, a download link appears next to the count.</li>
                    <li>Download the CSV of invalid rows, correct the errors, and re-upload.</li>
                  </ul>
                </div>

                <div className="help-section">
                  <h2>9. Best Practices</h2>
                  <h3>9.1 Before Uploading</h3>
                  <ul className="help-list">
                    <li>Use the sample CSV template to prepare data.</li>
                    <li>Ensure all records contain a valid TIN.</li>
                    <li>Remove duplicate rows before uploading.</li>
                    <li>Confirm the correct financial period dates.</li>
                  </ul>

                  <h3>9.2 During Upload</h3>
                  <ul className="help-list">
                    <li>Use Show Preview to confirm column mapping.</li>
                    <li>Review the first 10 rows for accuracy.</li>
                    <li>Click Upload & Validate before clicking Process.</li>
                    <li>Download and correct invalid records if needed.</li>
                  </ul>

                  <h3>9.3 Processing Order</h3>
                  <ul className="help-list">
                    <li>Upload and process GST first, then SWT, then CIT.</li>
                    <li>Do not click Create Segmentation until all three are processed.</li>
                    <li>Wait for success confirmation before moving to the next step.</li>
                  </ul>

                  <h3>9.4 General</h3>
                  <ul className="help-list">
                    <li>Check Upload History before re-uploading to avoid duplicates.</li>
                    <li>Use the TIN filter on dashboards to investigate specific taxpayers.</li>
                    <li>Use Download CSV and Download PDF on dashboards and reports.</li>
                    <li>Review Fraud Reason details for all Fraud Detected records.</li>
                  </ul>
                </div>

                <div className="help-section">
                  <h2>10. Complete Workflow Summary</h2>
                  <table className="help-table">
                    <thead>
                      <tr>
                        <th>Step</th>
                        <th>Action</th>
                        <th>Where</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>1</td>
                        <td>Log in to the RBA Tool</td>
                        <td>Login Page</td>
                      </tr>
                      <tr>
                        <td>2</td>
                        <td>Download sample CSV templates</td>
                        <td>Upload Sheet - Sample buttons</td>
                      </tr>
                      <tr>
                        <td>3</td>
                        <td>Upload and process GST data</td>
                        <td>Upload Sheet - Select GST - Upload - Validate - Process</td>
                      </tr>
                      <tr>
                        <td>4</td>
                        <td>Upload and process SWT data</td>
                        <td>Upload Sheet - Select SWT - Upload - Validate - Process</td>
                      </tr>
                      <tr>
                        <td>5</td>
                        <td>Upload and process CIT data</td>
                        <td>Upload Sheet - Select CIT - Upload - Validate - Process</td>
                      </tr>
                      <tr>
                        <td>6</td>
                        <td>Create Segmentation</td>
                        <td>Upload Sheet - Create Segmentation button</td>
                      </tr>
                      <tr>
                        <td>7</td>
                        <td>View Final Audit Summary</td>
                        <td>Upload Sheet - View button after segmentation</td>
                      </tr>
                      <tr>
                        <td>8</td>
                        <td>Review dashboards</td>
                        <td>Dashboard - GST / SWT / CIT</td>
                      </tr>
                      <tr>
                        <td>9</td>
                        <td>Perform risk analysis</td>
                        <td>Analytics - Risk Assessment / Risk Profiling</td>
                      </tr>
                      <tr>
                        <td>10</td>
                        <td>Review flagged records</td>
                        <td>Reports - Recent Uploads - View Reason</td>
                      </tr>
                      <tr>
                        <td>11</td>
                        <td>Generate taxpayer reports</td>
                        <td>Reports - Taxpayer Profile / Risk Profiling</td>
                      </tr>
                      <tr>
                        <td>12</td>
                        <td>Export and share findings</td>
                        <td>Dashboard / Reports - Download PDF / CSV / Excel</td>
                      </tr>
                      <tr>
                        <td>13</td>
                        <td>Verify upload log</td>
                        <td>Upload History</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="help-section">
                  <h2>11. Conclusion</h2>
                  <p>
                    The Tax Fraud Detection System provides a structured, ML-powered approach to identifying fraudulent
                    tax submissions across GST, SWT, and CIT. By combining automated data validation, machine learning
                    fraud detection, risk profiling, and geographic visualization, the system reduces manual review effort
                    and improves detection accuracy.
                  </p>
                  <p>
                    The complete workflow - Upload - Validate - Process - Segmentation - Dashboard Review - Risk Analysis
                    - Report Export - ensures all data is verified, cleaned, and analyzed before findings are acted upon.
                    For further assistance, contact your system administrator or navigate to Help Centre from the left sidebar.
                  </p>
                </div>
              </div>
            </div>
          </main>
        </div>

        <Footer />
      </div>
    </div>
  );
}
