import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  ChevronDown,
  ChevronLeft,
  BarChart3,
  Upload,
  PieChart,
  FileSpreadsheet,
  Eye,
  Info,
  ChevronRight,
} from "lucide-react";

import "./css/Sidebar.css";
import Logo from "../../assets/img/logo.png";
import MenuIcon from '@mui/icons-material/Menu';
import MenuOpenIcon from '@mui/icons-material/MenuOpen';

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null); // track which parent is open
  const location = useLocation();

  // Map child paths to their parent
  const menuMap = {
    dashboard: ["/gst", "/swt", "/cit"],
    analytics: ["/risk-assessment", "/risk-profiling", "/compliance"],
    reports: ["/recent-uploads", "/tax-payer-profile", "/taxpayer-report-risk-profiling"],
  };

  // Auto-open parent based on current location
  useEffect(() => {
    for (const [menu, paths] of Object.entries(menuMap)) {
      if (paths.includes(location.pathname)) {
        setOpenMenu(menu);
        return;
      }
    }
    // if no child matched, do not auto-close, keep manual toggle
  }, [location.pathname]);

  const toggleMenu = (menu) => {
    setOpenMenu(openMenu === menu ? null : menu);
  };

  return (
    <div
        className={`sidebar bg-dark text-white position-fixed top-0 start-0 vh-100 ${
          collapsed ? "collapsed" : "expanded"
        }`}
      >
        <div className="sidebar-header d-flex justify-content-between align-items-center w-100">
          {/* Logo + Title */}
          <div className="d-flex align-items-center gap-2">
            <img src={Logo} alt="Logo" className="sidebar-logo" width="30" />
            <span className="fw-bold fs-5 text-light">RBA Tool</span>
          </div>

          {/* Collapse Button */}
          <button
            className="btn btn-sm btn-outline-light text-dark"
            onClick={() => setCollapsed(!collapsed)}
          >
            <MenuIcon color="primary" />
          </button>
        </div>




      <div className="nav flex-column mt-5 px-2">
        {/* Dashboard with children */}
        <div>
          <button
            className="nav-link text-white d-flex align-items-center justify-content-between w-100"
            onClick={() => toggleMenu("dashboard")}
          >
            <span>
              <BarChart3 className="me-2" color="#347ae2" /> Dashboard
            </span>
            <span className={`arrow ${openMenu === "dashboard" ? "open" : ""}`}>
              <ChevronDown />
            </span>
          </button>
          {openMenu === "dashboard" && (
            <div className="submenu ms-3">
              <Link
                to="/gst"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/gst" ? "active" : ""
                }`}
              >
                <ChevronRight /> GST
              </Link>
              <Link
                to="/swt"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/swt" ? "active" : ""
                }`}
              >
                <ChevronRight /> SWT
              </Link>
              <Link
                to="/cit"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/cit" ? "active" : ""
                }`}
              >
                <ChevronRight /> CIT
              </Link>
            </div>
          )}
        </div>

        {/* Upload Sheets */}
        <Link
          to="/upload-sheets"
          className={`nav-link text-white ${
            location.pathname === "/upload-sheets" ? "active" : ""
          }`}
        >
          <Upload className="me-2" color="#347ae2" /> Upload Sheets
        </Link>

        {/* Analytics with children */}
        <div>
          <button
            className="nav-link text-white d-flex align-items-center justify-content-between w-100"
            onClick={() => toggleMenu("analytics")}
          >
            <span>
              <PieChart className="me-2" color="#347ae2" /> Analytics
            </span>
            <span className={`arrow ${openMenu === "analytics" ? "open" : ""}`}>
              <ChevronDown />
            </span>
          </button>
          {openMenu === "analytics" && (
            <div className="submenu ms-3">
              <Link
                to="/risk-assessment"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/risk-assessment" ? "active" : ""
                }`}
              >
                <ChevronRight /> Risk Assessment
              </Link>
              <Link
                to="/risk-profiling"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/risk-profiling" ? "active" : ""
                }`}
              >
                <ChevronRight /> Risk Profiling
              </Link>
              <Link
                to="/compliance"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/compliance" ? "active" : ""
                }`}
              >
                <ChevronRight /> Compliance
              </Link>
            </div>
          )}
        </div>

        {/* Reports with children */}
        <div>
          <button
            className="nav-link text-white d-flex align-items-center justify-content-between w-100"
            onClick={() => toggleMenu("reports")}
          >
            <span>
              <FileSpreadsheet className="me-2" color="#347ae2" /> Reports
            </span>
            <span className={`arrow ${openMenu === "reports" ? "open" : ""}`}>
              <ChevronDown />
            </span>
          </button>
          {openMenu === "reports" && (
            <div className="submenu ms-3">
              <Link
                to="/recent-uploads"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/recent-uploads" ? "active" : ""
                }`}
              >
                <ChevronRight /> Recent Uploads
              </Link>
              <Link
                to="/tax-payer-profile"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/tax-payer-profile" ? "active" : ""
                }`}
              >
                <ChevronRight /> Tax Payer Profile
              </Link>
              <Link
                to="/taxpayer-report-risk-profiling"
                className={`nav-link submenu-item text-white ${
                  location.pathname === "/taxpayer-report-risk-profiling" ? "active" : ""
                }`}
              >
                <ChevronRight /> Taxpayer Report Risk Profiling
              </Link>
            </div>
          )}
        </div>

        {/* Upload History */}
        <Link
          to="/upload-history"
          className={`nav-link text-white ${
            location.pathname === "/upload-history" ? "active" : ""
          }`}
        >
          <Eye className="me-2" color="#347ae2" /> Upload History
        </Link>

        {/* Help Centre */}
        <Link
          to="/help-centre"
          className={`nav-link text-white ${
            location.pathname === "/help-centre" ? "active" : ""
          }`}
        >
          <Info className="me-2" color="#347ae2" /> Help Centre
        </Link>
      </div>
    </div>
  );
}