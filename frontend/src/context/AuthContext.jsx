import { createContext, useEffect, useMemo, useState } from "react";

import {
  clearSession,
  getUser,
  login as loginRequest,
  logout as logoutRequest,
  restoreSession,
} from "../services/auth";
import { AuthContext } from "./auth-context";

export function AuthProvider({ children }) {
  const [authStatus, setAuthStatus] = useState("initializing");
  const [user, setUser] = useState(() => getUser());

  useEffect(() => {
    let active = true;

    const bootstrap = async () => {
      setAuthStatus("initializing");
      try {
        const restoredUser = await restoreSession();
        if (!active) return;

        if (restoredUser) {
          setUser(restoredUser);
          setAuthStatus("authenticated");
          return;
        }
      } catch {
        // Fall through to the unauthenticated state below.
      }

      if (!active) return;
      clearSession();
      setUser(null);
      setAuthStatus("unauthenticated");
    };

    bootstrap();

    return () => {
      active = false;
    };
  }, []);

  const login = async (email, password) => {
    const result = await loginRequest(email, password);
    const nextUser = result?.user || getUser();

    if (nextUser) {
      setUser(nextUser);
      setAuthStatus("authenticated");
    } else {
      setUser(null);
      setAuthStatus("unauthenticated");
    }

    return result;
  };

  const logout = async () => {
    await logoutRequest();
    setUser(null);
    setAuthStatus("unauthenticated");
  };

  const refreshSession = async () => {
    setAuthStatus("initializing");
    try {
      const restoredUser = await restoreSession();
      if (restoredUser) {
        setUser(restoredUser);
        setAuthStatus("authenticated");
        return restoredUser;
      }
    } catch {
      // Fall through to unauthenticated state below.
    }

    clearSession();
    setUser(null);
    setAuthStatus("unauthenticated");
    return null;
  };

  const value = useMemo(
    () => ({
      authStatus,
      isInitializing: authStatus === "initializing",
      isAuthenticated: authStatus === "authenticated",
      user,
      login,
      logout,
      refreshSession,
    }),
    [authStatus, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
