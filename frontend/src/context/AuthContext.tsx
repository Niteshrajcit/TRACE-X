import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { UserRole } from "../types/domain";

interface AuthState {
  token: string;
  role: UserRole;
  jurisdictionId: string | null;
}

interface AuthContextValue {
  auth: AuthState | null;
  setAuth: (auth: AuthState | null) => void;
  logout: () => void;
}

const STORAGE_KEY = "tracex.auth";

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<AuthState | null>(() => {
    // docs/SECURITY_AND_GOVERNANCE.md §3 / PRODUCT_EXPERIENCE.md §8.2: a
    // single moderate-TTL token, no refresh flow this phase. Persisting it
    // in localStorage just survives a page reload during a demo - it is
    // not a security boundary (the backend's JWT expiry is).
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? (JSON.parse(raw) as AuthState) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (auth) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [auth]);

  const setAuth = (next: AuthState | null) => setAuthState(next);
  const logout = () => setAuthState(null);

  return (
    <AuthContext.Provider value={{ auth, setAuth, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
