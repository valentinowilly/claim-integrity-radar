import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiClientError, getCurrentUser, login as apiLogin, logout as apiLogout, type AuthSession } from "../api/client";

/** Set at sign-in; the overview shows the facility warning once and then clears it. */
export const LOGIN_ALERT_KEY = "cir:login-alert-pending";

type AuthState = { loading: true } | { loading: false; session: AuthSession | null; issue?: "expired" | "network" };
interface AuthContextValue {
  state: AuthState;
  signIn(username: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  expire(): void;
}
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ loading: true });
  const expire = useCallback(() => setState({ loading: false, session: null, issue: "expired" }), []);

  useEffect(() => {
    let active = true;
    void getCurrentUser().then(session => {
      if (active) setState({ loading: false, session });
    }).catch((error: unknown) => {
      if (active) {
        const unauthorized = error instanceof ApiClientError && error.status === 401;
        setState({ loading: false, session: null, ...(unauthorized ? {} : { issue: "network" as const }) });
      }
    });
    const onExpired = () => expire();
    window.addEventListener("cir:session-expired", onExpired);
    return () => { active = false; window.removeEventListener("cir:session-expired", onExpired); };
  }, [expire]);

  const signIn = useCallback(async (username: string, password: string) => {
    const session = await apiLogin(username, password);
    // The overview shows the facility warning once after each sign-in (per tab; storage may be unavailable).
    try { window.sessionStorage.setItem(LOGIN_ALERT_KEY, "1"); } catch { /* warning stays reachable on the overview */ }
    setState({ loading: false, session });
  }, []);
  const signOut = useCallback(async () => {
    try { await apiLogout(); setState({ loading: false, session: null }); }
    catch (error) {
      if (error instanceof ApiClientError && error.status === 401) setState({ loading: false, session: null });
      throw error;
    }
  }, [expire]);
  const value = useMemo(() => ({ state, signIn, signOut, expire }), [state, signIn, signOut, expire]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
