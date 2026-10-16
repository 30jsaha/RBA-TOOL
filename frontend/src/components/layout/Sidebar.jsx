import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { createPortal } from "react-dom";
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
  const sidebarRef = useRef(null);
  const groupRefs = useRef({});
  const flyoutRef = useRef(null);
  const [flyoutPosition, setFlyoutPosition] = useState(null);
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

    setOpenMenu((currentMenu) => {
      const routeMenu = collapsed ? null : nextOpenMenu;
      return currentMenu === routeMenu ? currentMenu : routeMenu;
    });
  }, [location.pathname, permissionSignature, collapsed, menuMap]);

  useEffect(() => {
    if (location.pathname.startsWith("/settings/conflicts")) {
      setOpenMenu("settings");
      setOpenSettingsSub("conflicts");
      return;
    }

    setOpenSettingsSub(null);
  }, [location.pathname]);

  useEffect(() => {
    if (!collapsed || (!openMenu && !openSettingsSub)) return undefined;

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setOpenMenu(null);
        setOpenSettingsSub(null);
      }
    };

    const handlePointerDown = (event) => {
      if (!sidebarRef.current?.contains(event.target) && !flyoutRef.current?.contains(event.target)) {
        setOpenMenu(null);
        setOpenSettingsSub(null);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [collapsed, openMenu, openSettingsSub]);

  useLayoutEffect(() => {
    if (!collapsed || !openMenu) {
      setFlyoutPosition(null);
      return undefined;
    }

    const updateFlyoutPosition = () => {
      const anchor = groupRefs.current[openMenu];
      if (!anchor) return;

      const anchorRect = anchor.getBoundingClientRect();
      const panelWidth = Math.min(220, Math.max(0, window.innerWidth - 24));
      const panelHeight = flyoutRef.current?.offsetHeight || 320;
      const left = Math.min(anchorRect.right + 8, Math.max(12, window.innerWidth - panelWidth - 12));
      const top = Math.min(Math.max(12, anchorRect.top), Math.max(12, window.innerHeight - panelHeight - 12));

      setFlyoutPosition((currentPosition) => {
        if (currentPosition?.left === left && currentPosition?.top === top) return currentPosition;
        return { left, top, width: panelWidth };
      });
    };

    updateFlyoutPosition();
    window.addEventListener("resize", updateFlyoutPosition);
    window.addEventListener("scroll", updateFlyoutPosition, true);
    return () => {
      window.removeEventListener("resize", updateFlyoutPosition);
      window.removeEventListener("scroll", updateFlyoutPosition, true);
    };
  }, [collapsed, openMenu, openSettingsSub]);

  const toggleMenu = (menu) => {
    setOpenMenu((currentMenu) => (currentMenu === menu ? null : menu));
  };

  const toggleSettingsSub = () => {
    setOpenSettingsSub((currentSubmenu) => (currentSubmenu === "conflicts" ? null : "conflicts"));
  };

  const menuIsActive = (menu) => menuMap[menu]?.includes(location.pathname);
  const setGroupRef = (menu) => (node) => {
    if (node) groupRefs.current[menu] = node;
    else delete groupRefs.current[menu];
  };

  const renderMenuLinks = (items) => items.map((item) => (
    <Link key={item.path} to={item.path} className={`nav-link submenu-item text-white ${location.pathname === item.path ? "active" : ""}`}>
      <ChevronRight /> {item.label}
    </Link>
  ));

  const renderSubmenu = (menu, items) => {
    if (collapsed) {
      if (openMenu !== menu || !flyoutPosition) return null;
      return createPortal(
        <div ref={flyoutRef} className="sidebar-flyout submenu-container submenu-overlay" style={flyoutPosition}>
          <div className="submenu flyout-menu">{renderMenuLinks(items)}</div>
        </div>,
        document.body
      );
    }

    return (
      <div className="submenu-container">
        <div className="submenu ms-3">{renderMenuLinks(items)}</div>
      </div>
    );
  };

  const renderSettingsSubmenu = () => {
    if (collapsed && (!flyoutPosition || openMenu !== "settings")) return null;

    const content = (
      <div className={`submenu ${collapsed ? "flyout-menu" : "ms-3"}`}>
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
              aria-label="Conflicts"
              aria-haspopup="true"
              aria-expanded={openSettingsSub === "conflicts"}
            >
              <span>
                <Info className="me-2" color="#347ae2" />
                <span className="label">Conflicts</span>
              </span>
              <ChevronDown className={`arrow ${openSettingsSub === "conflicts" ? "open" : ""}`} aria-hidden="true" />
            </button>

            {openSettingsSub === "conflicts" && (
              <div className={`submenu-container ${collapsed ? "nested-submenu" : ""}`}>
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
    );

    if (collapsed) {
      return createPortal(
        <div ref={flyoutRef} className="sidebar-flyout submenu-container submenu-overlay" style={flyoutPosition}>
          {content}
        </div>,
        document.body
      );
    }

    return <div className="submenu-container">{content}</div>;
  };

  const showSettings = settingsItems.length > 0 || conflictItems.length > 0;

  return (
    <div ref={sidebarRef} className={`sidebar ${collapsed ? "collapsed" : ""}`}>
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
          <div ref={setGroupRef("dashboard")} className="nav-group">
            <button
              className={`nav-link text-white d-flex align-items-center justify-content-between w-100 ${menuIsActive("dashboard") ? "active" : ""}`}
              onClick={() => toggleMenu("dashboard")}
              aria-label="Dashboard"
              aria-haspopup="true"
              aria-expanded={openMenu === "dashboard"}
              title={collapsed && openMenu !== "dashboard" ? "Dashboard" : undefined}
            >
              <span>
                <BarChart3 className="me-2" color="#347ae2" /> <span className="label">Dashboard</span>
              </span>
              <ChevronDown className={`arrow ${openMenu === "dashboard" ? "open" : ""}`} aria-hidden="true" />
            </button>

            {openMenu === "dashboard" && renderSubmenu("dashboard", dashboardItems)}
          </div>
        )}

        {canAccess("upload_sheets") && (
          <Link to="/upload-sheets" title="Upload Sheets" aria-label="Upload Sheets" className={`nav-link text-white ${location.pathname === "/upload-sheets" ? "active" : ""}`}>
            <Upload className="me-2" color="#347ae2" />
            <span className="label">Upload Sheets</span>
          </Link>
        )}

        {analyticsItems.length > 0 && (
          <div ref={setGroupRef("analytics")} className="nav-group">
            <button className={`nav-link text-white d-flex align-items-center justify-content-between w-100 ${menuIsActive("analytics") ? "active" : ""}`} onClick={() => toggleMenu("analytics")} aria-label="Analytics" aria-haspopup="true" aria-expanded={openMenu === "analytics"} title={collapsed && openMenu !== "analytics" ? "Analytics" : undefined}>
              <span>
                <PieChart className="me-2" color="#347ae2" /> <span className="label">Analytics</span>
              </span>
              <ChevronDown className={`arrow ${openMenu === "analytics" ? "open" : ""}`} aria-hidden="true" />
            </button>

            {openMenu === "analytics" && renderSubmenu("analytics", analyticsItems)}
          </div>
        )}

        {reportItems.length > 0 && (
          <div ref={setGroupRef("reports")} className="nav-group">
            <button
              className={`nav-link text-white d-flex align-items-center justify-content-between w-100 ${menuIsActive("reports") ? "active" : ""}`}
              onClick={() => toggleMenu("reports")}
              aria-label="Reports"
              aria-haspopup="true"
              aria-expanded={openMenu === "reports"}
              title={collapsed && openMenu !== "reports" ? "Reports" : undefined}
            >
              <span>
                <FileSpreadsheet className="me-2" color="#347ae2" /> <span className="label">Reports</span>
              </span>
              <ChevronDown className={`arrow ${openMenu === "reports" ? "open" : ""}`} aria-hidden="true" />
            </button>

            {openMenu === "reports" && renderSubmenu("reports", reportItems)}
          </div>
        )}

        {canAccess("upload_history") && (
          <Link to="/upload-history" title="Upload History" aria-label="Upload History" className={`nav-link text-white ${location.pathname === "/upload-history" ? "active" : ""}`}>
            <Eye className="me-2" color="#347ae2" /> <span className="label">Upload History</span>
          </Link>
        )}

        {canAccess("upload_tin_registration") && (
          <Link to="/upload-tin-registration" title="TIN Master" aria-label="TIN Master" className={`nav-link text-white ${location.pathname === "/upload-tin-registration" ? "active" : ""}`}>
            <Upload className="me-2" color="#347ae2" /> <span className="label">TIN Master</span>
          </Link>
        )}

        <Link to="/help-centre" title="Help Centre" aria-label="Help Centre" className={`nav-link text-white ${location.pathname === "/help-centre" ? "active" : ""}`}>
          <Info className="me-2" color="#347ae2" /> <span className="label">Help Centre</span>
        </Link>

        {showSettings && (
          <div ref={setGroupRef("settings")} className="nav-group">
            <button
              className={`nav-link text-white d-flex align-items-center justify-content-between w-100 ${menuIsActive("settings") ? "active" : ""}`}
              onClick={() => toggleMenu("settings")}
              aria-label="Settings"
              aria-haspopup="true"
              aria-expanded={openMenu === "settings"}
              title={collapsed && openMenu !== "settings" ? "Settings" : undefined}
            >
              <span>
                <FileSpreadsheet className="me-2" color="#347ae2" /> <span className="label">Settings</span>
              </span>
              <ChevronDown className={`arrow ${openMenu === "settings" ? "open" : ""}`} aria-hidden="true" />
            </button>

            {openMenu === "settings" && renderSettingsSubmenu()}
          </div>
        )}
      </div>
    </div>
  );
}

