import { Routes, Route } from "react-router-dom";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ProtectedRoute from "./components/common/ProtectedRoute";
import SwtDashboard from "./pages/SwtDashboard";
import CitDashboard from "./pages/CitDashboard";
import UploadSheet from "./pages/UploadSheet";
import UploadTinRegistration from "./pages/UploadTinRegistration";
import UploadHistory from "./pages/UploadHistory";
import RecentUpload from "./pages/RecentUpload";
import RiskAssessment from "./pages/RiskAssessment";
import RiskProfiling from "./pages/RiskProfiling";
import Compliance from "./pages/Compliance";
import TaxpayerProfile from "./pages/TaxpayerProfile";
import TaxpayerReportRiskProfiling from "./pages/TaxpayerReportRiskProfiling";
import CommonDashboard from "./pages/CommonDashboard";
import Users from "./pages/Users";
import Roles from "./pages/Roles";
import RolePermissions from "./pages/RolePermissions";
import InvalidTins from "./pages/InvalidTins";
import ConflictList from "./pages/ConflictList";
import ConflictHistory from "./pages/ConflictHistory";
import AuditLogs from "./pages/AuditLogs";
import DataChangeApproval from "./pages/DataChangeApproval";
import HelpCenter from "./pages/HelpCenter";
import ResetDB from "./pages/ResetDB";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />

      <Route
        path="/gst"
        element={
          <ProtectedRoute permission="dashboard.gst">
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/swt"
        element={
          <ProtectedRoute permission="dashboard.swt">
            <SwtDashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/cit"
        element={
          <ProtectedRoute permission="dashboard.cit">
            <CitDashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/common-dashboard"
        element={
          <ProtectedRoute permission="dashboard.dashboard">
            <CommonDashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/upload-sheets"
        element={
          <ProtectedRoute permission="upload_sheets">
            <UploadSheet />
          </ProtectedRoute>
        }
      />
      <Route
        path="/upload-tin-registration"
        element={
          <ProtectedRoute permission="upload_tin_registration">
            <UploadTinRegistration />
          </ProtectedRoute>
        }
      />
      <Route
        path="/upload-history"
        element={
          <ProtectedRoute permission="upload_history">
            <UploadHistory />
          </ProtectedRoute>
        }
      />
      <Route
        path="/recent-uploads"
        element={
          <ProtectedRoute permission="reports.recent_uploads">
            <RecentUpload />
          </ProtectedRoute>
        }
      />
      <Route
        path="/risk-assessment"
        element={
          <ProtectedRoute permission="analytics.risk_assessment">
            <RiskAssessment />
          </ProtectedRoute>
        }
      />
      <Route
        path="/risk-profiling"
        element={
          <ProtectedRoute permission="reports.risk_profiling">
            <RiskProfiling />
          </ProtectedRoute>
        }
      />
      <Route
        path="/compliance"
        element={
          <ProtectedRoute permission="analytics.compliance">
            <Compliance />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tax-payer-profile"
        element={
          <ProtectedRoute permission="reports.taxpayer_profile">
            <TaxpayerProfile />
          </ProtectedRoute>
        }
      />
      <Route
        path="/taxpayer-report-risk-profiling"
        element={
          <ProtectedRoute permission="reports.risk_profiling">
            <TaxpayerReportRiskProfiling />
          </ProtectedRoute>
        }
      />
      <Route
        path="/data-change-approval"
        element={
          <ProtectedRoute requiredRoles={["ADMIN", "SUPERVISOR"]}>
            <DataChangeApproval />
          </ProtectedRoute>
        }
      />
      <Route
        path="/help-centre"
        element={
          <ProtectedRoute>
            <HelpCenter />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/users"
        element={
          <ProtectedRoute permission="settings.users">
            <Users />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/roles"
        element={
          <ProtectedRoute permission="settings.roles">
            <Roles />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/role-permissions"
        element={
          <ProtectedRoute permission="settings.role_permissions">
            <RolePermissions />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/invalid-tins"
        element={
          <ProtectedRoute permission="settings.invalid_tins">
            <InvalidTins />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/conflicts"
        element={
          <ProtectedRoute permission="settings.conflicts.list">
            <ConflictList />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/conflicts/list"
        element={
          <ProtectedRoute permission="settings.conflicts.list">
            <ConflictList />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/conflicts/history"
        element={
          <ProtectedRoute permission="settings.conflicts.history">
            <ConflictHistory />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/conflicts/audit-logs"
        element={
          <ProtectedRoute permission="settings.conflicts.audit_logs">
            <AuditLogs />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/reset-db"
        element={
          <ProtectedRoute permission="settings.reset_db">
            <ResetDB />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<Login />} />
    </Routes>
  );
}

export default App;
