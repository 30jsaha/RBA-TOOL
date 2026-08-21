import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  ChevronDown,
  BarChart3,
  Upload,
  PieChart,
  FileSpreadsheet,
  Eye,
  Info,
  ChevronRight,
} from "lucide-react";
import MenuIcon from "@mui/icons-material/Menu";
import MenuOpenIcon from "@mui/icons-material/MenuOpen";

import "./css/Sidebar.css";
import Logo from "../../assets/img/logo.png";
import { getUser } from "../../services/auth";

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState(null);
  const [openSettingsSub, setOpenSettingsSub] = useState(null);
  const location = useLocation();
  const user = getUser();
  const permissions = Array.isArray(user?.permissions) ? user.permissions : [];
  const permissionSignature = [...permissions].sort().join("|");

  const canAccess = (permission) => !permission || permissions.includes(permission);
  const canAccessAll = (permissionCodes) => (permissionCodes || []).every((code) => canAccess(code));

  const dashboardItems = useMemo(
    () => [
      { label: "Dashboard", path: "/common-dashboard", permission: "dashboard.dashboard" },
      { label: "GST", path: "/gst", permission: "dashboard.gst" },
      { label: "SWT", path: "/swt", permission: "dashboard.swt" },
      { label: "CIT", path: "/cit", permission: "dashboard.cit" },
    ].filter((item) => Array.isArray(item.permission) ? canAccessAll(item.permission) : canAccess(item.permission)),
    [permissionSignature]
  );

  const analyticsItems = useMemo(
    () => [
      { label: "Risk Assessment", path: "/risk-assessment", permission: "analytics.risk_assessment" },
      { label: "Compliance", path: "/compliance", permission: "analytics.compliance" },
    ].filter((item) => Array.isArray(item.permission) ? canAccessAll(item.permission) : canAccess(item.permission)),
    [permissionSignature]
  );

  const reportItems = useMemo(
    () => [
      { label: "Recent Uploads", path: "/recent-uploads", permission: "reports.recent_uploads" },
      { label: "Taxpayer Profile", path: "/tax-payer-profile", permission: "reports.taxpayer_profile" },
      { label: "Risk Profiling", path: "/taxpayer-report-risk-profiling", permission: "reports.risk_profiling" },
    ].filter((item) => Array.isArray(item.permission) ? canAccessAll(item.permission) : canAccess(item.permission)),
    [permissionSignature]
  );

  const conflictItems = useMemo(
    () => [
      { label: "List", path: "/settings/conflicts/list", permission: "settings.conflicts.list" },
      { label: "History", path: "/settings/conflicts/history", permission: "settings.conflicts.history" },
      { label: "Audit Logs", path: "/settings/conflicts/audit-logs", permission: "settings.conflicts.audit_logs" },
    ].filter((item) => Array.isArray(item.permission) ? canAccessAll(item.permission) : canAccess(item.permission)),
    [permissionSignature]
  );

  const settingsItems = useMemo(
    () => [
      { label: "Users", path: "/settings/users", permission: "settings.users" },
      { label: "Roles", path: "/settings/roles", permission: "settings.roles" },
      { label: "Permissions", path: "/settings/role-permissions", permission: "settings.role_permissions" },
      { label: "Invalid TINs", path: "/settings/invalid-tins", permission: "settings.invalid_tins" },
      { label: "Reset DB", path: "/settings/reset-db", permission: "settings.reset_db" },
    ].filter((item) => Array.isArray(item.permission) ? canAccessAll(item.permission) : canAccess(item.permission)),
    [permissionSignature]
  );

  const menuMap = useMemo(
    () => ({
      dashboard: dashboardItems.map((item) => item.path),
      analytics: analyticsItems.map((item) => item.path),
      reports: reportItems.map((item) => item.path),
      settings: [
        ...settingsItems.map((item) => item.path),
        ...conflictItems.map((item) => item.path),
      ],
    }),
    [dashboardItems, analyticsItems, reportItems, settingsItems, conflictItems]
  );

  useEffect(() => {
    const nextOpenMenu = Object.entries(menuMap).find(([, paths]) => paths.includes(location.pathname))?.[0] || null;

    setOpenMenu((currentMenu) => (currentMenu === nextOpenMenu ? currentMenu : nextOpenMenu));
  }, [location.pathname, permissionSignature]);

  useEffect(() => {
    if (location.pathname.startsWith("/settings/conflicts")) {
      setOpenMenu("settings");
      setOpenSettingsSub("conflicts");
      return;
    }

    if (!location.pathname.startsWith("/settings/conflicts") && openSettingsSub === "conflicts") {
      setOpenSettingsSub(null);
    }
  }, [location.pathname, openSettingsSub]);

  const toggleMenu = (menu) => {
    if (collapsed) return;
    setOpenMenu((currentMenu) => (currentMenu === menu ? null : menu));
  };

  const toggleSettingsSub = () => {
    if (collapsed) return;
    setOpenSettingsSub((currentSubmenu) => (currentSubmenu === "conflicts" ? null : "conflicts"));
  };

  const showSettings = settingsItems.length > 0 || conflictItems.length > 0;

  return (
    <div className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebar-header d-flex align-items-center justify-content-between">
        {!collapsed && (
          <div className="d-flex align-items-center gap-2">
            <img src={Logo} alt="Logo" className="sidebar-logo" width="28" />
            <span className="fw-bold fs-6 label">RBA Tool</span>
          </div>
        )}

        <button
          className="collapse-btn"
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? <MenuOpenIcon /> : <MenuIcon />}
        </button>
      </div>

      <div className="nav flex-column mt-4 px-2">
        {dashboardItems.length > 0 && (
          <div>
            <button
              className="nav-link text-white d-flex align-items-center justify-content-between w-100"
              onClick={() => toggleMenu("dashboard")}
            >
              <span>
                <BarChart3 className="me-2" color="#347ae2" /> <span className="label">Dashboard</span>
              </span>
              {!collapsed && <ChevronDown className={`arrow ${openMenu === "dashboard" ? "open" : ""}`} />}
            </button>

            {openMenu === "dashboard" && (
              <div className={`submenu-container ${collapsed ? "submenu-overlay" : ""}`}>
                <div className="submenu ms-3">
                  {dashboardItems.map((item) => (
                    <Link key={item.path} to={item.path} className={`nav-link submenu-item text-white ${location.pathname === item.path ? "active" : ""}`}>
                      <ChevronRight /> {item.label}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {canAccess("upload_sheets") && (
          <Link to="/upload-sheets" className={`nav-link text-white ${location.pathname === "/upload-sheets" ? "active" : ""}`}>
            <Upload className="me-2" color="#347ae2" />
            <span className="label">Upload Sheets</span>
          </Link>
        )}

        {analyticsItems.length > 0 && (
          <div>
            <button className="nav-link text-white d-flex align-items-center justify-content-between w-100" onClick={() => toggleMenu("analytics")}>
              <span>
                <PieChart className="me-2" color="#347ae2" /> <span className="label">Analytics</span>
              </span>
              {!collapsed && <ChevronDown className={`arrow ${openMenu === "analytics" ? "open" : ""}`} />}
            </button>

            {openMenu === "analytics" && (
              <div className={`submenu-container ${collapsed ? "submenu-overlay" : ""}`}>
                <div className="submenu ms-3">
                  {analyticsItems.map((item) => (
                    <Link key={item.path} to={item.path} className={`nav-link submenu-item text-white ${location.pathname === item.path ? "active" : ""}`}>
                      <ChevronRight /> {item.label}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {reportItems.length > 0 && (
          <div>
            <button
              className="nav-link text-white d-flex align-items-center justify-content-between w-100"
              onClick={() => toggleMenu("reports")}
            >
              <span>
                <FileSpreadsheet className="me-2" color="#347ae2" /> <span className="label">Reports</span>
              </span>
              {!collapsed && <ChevronDown className={`arrow ${openMenu === "reports" ? "open" : ""}`} />}
            </button>

            {openMenu === "reports" && (
              <div className={`submenu-container ${collapsed ? "submenu-overlay" : ""}`}>
                <div className="submenu ms-3">
                  {reportItems.map((item) => (
                    <Link key={item.path} to={item.path} className={`nav-link submenu-item text-white ${location.pathname === item.path ? "active" : ""}`}>
                      <ChevronRight /> {item.label}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {canAccess("upload_history") && (
          <Link to="/upload-history" className={`nav-link text-white ${location.pathname === "/upload-history" ? "active" : ""}`}>
            <Eye className="me-2" color="#347ae2" /> <span className="label">Upload History</span>
          </Link>
        )}

        {canAccess("upload_tin_registration") && (
          <Link to="/upload-tin-registration" className={`nav-link text-white ${location.pathname === "/upload-tin-registration" ? "active" : ""}`}>
            <Upload className="me-2" color="#347ae2" /> <span className="label">Upload TIN Registration</span>
          </Link>
        )}

        <Link to="/help-centre" className={`nav-link text-white ${location.pathname === "/help-centre" ? "active" : ""}`}>
          <Info className="me-2" color="#347ae2" /> <span className="label">Help Centre</span>
        </Link>

        {showSettings && (
          <div>
            <button
              className="nav-link text-white d-flex align-items-center justify-content-between w-100"
              onClick={() => toggleMenu("settings")}
            >
              <span>
                <FileSpreadsheet className="me-2" color="#347ae2" /> <span className="label">Settings</span>
              </span>
              {!collapsed && <ChevronDown className={`arrow ${openMenu === "settings" ? "open" : ""}`} />}
            </button>

            {openMenu === "settings" && (
              <div className={`submenu-container ${collapsed ? "submenu-overlay" : ""}`}>
                <div className="submenu ms-3">
                  {settingsItems.map((item) => (
                    <Link key={item.path} to={item.path} className={`nav-link text-white ${location.pathname === item.path ? "active" : ""}`}>
                      <Info className="me-2" color="#347ae2" /> <span className="label">{item.label}</span>
                    </Link>
                  ))}

                  {conflictItems.length > 0 && (
                    <>
                      <button
                        className="nav-link text-white d-flex align-items-center justify-content-between w-100"
                        onClick={toggleSettingsSub}
                      >
                        <span>
                          <Info className="me-2" color="#347ae2" />
                          <span className="label">Conflicts</span>
                        </span>
                        {!collapsed && <ChevronDown className={`arrow ${openSettingsSub === "conflicts" ? "open" : ""}`} />}
                      </button>

                      {openSettingsSub === "conflicts" && (
                        <div className={`submenu-container ${collapsed ? "submenu-overlay" : ""}`}>
                          <div className="submenu ms-3">
                            {conflictItems.map((item) => (
                              <Link key={item.path} to={item.path} className={`nav-link submenu-item text-white ${location.pathname === item.path ? "active" : ""}`}>
                                <ChevronRight /> {item.label}
                              </Link>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
