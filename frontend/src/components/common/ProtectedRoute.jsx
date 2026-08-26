import { Navigate } from "react-router-dom";

import { useAuth } from "../../context/useAuth";

const hasRoleAccess = (user, requiredRoles) => {
  if (!Array.isArray(requiredRoles) || requiredRoles.length === 0) return true;
  const roles = Array.isArray(user?.roles) ? user.roles : [];
  return requiredRoles.some((role) => roles.includes(role));
};

const hasPermissionAccess = (user, permission) => {
  if (!permission) return true;
  const permissions = Array.isArray(user?.permissions) ? user.permissions : [];

  if (Array.isArray(permission)) {
    return permission.every((code) => permissions.includes(code));
  }

  return permissions.includes(permission);
};

export default function ProtectedRoute({ children, requiredRoles, permission, redirectTo = "/common-dashboard" }) {
  const { authStatus, user } = useAuth();

  if (authStatus === "initializing") {
    return null;
  }

  if (authStatus !== "authenticated" || !user) {
    return <Navigate to="/" replace />;
  }

  if (!hasRoleAccess(user, requiredRoles) || !hasPermissionAccess(user, permission)) {
    return <Navigate to={redirectTo} replace />;
  }

  return children;
}

