import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";

import { ensureCurrentUser, getToken, getUser } from "../../services/auth";

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
  const token = getToken();
  const [user, setUser] = useState(() => getUser());
  const [loading, setLoading] = useState(Boolean(token));

  useEffect(() => {
    let active = true;

    if (!token) {
      setLoading(false);
      return undefined;
    }

    ensureCurrentUser()
      .then((resolvedUser) => {
        if (!active) return;
        setUser(resolvedUser);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [token, user]);

  if (!token) {
    return <Navigate to="/" replace />;
  }

  if (loading) {
    return null;
  }

  if (!hasRoleAccess(user, requiredRoles) || !hasPermissionAccess(user, permission)) {
    return <Navigate to={redirectTo} replace />;
  }

  return children;
}
