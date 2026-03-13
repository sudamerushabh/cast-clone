"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import type { UserResponse } from "./types";
import { getMe, getSetupStatus, login as apiLogin } from "./api";

interface AuthContextValue {
  user: UserResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const PUBLIC_PATHS = ["/login", "/setup"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const isPublicPath = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        const { needs_setup } = await getSetupStatus();
        if (needs_setup) {
          if (!cancelled) {
            setIsLoading(false);
            if (pathname !== "/setup") router.replace("/setup");
          }
          return;
        }

        const token = localStorage.getItem("auth_token");
        if (!token) {
          if (!cancelled) {
            setIsLoading(false);
            if (!isPublicPath) router.replace("/login");
          }
          return;
        }

        const me = await getMe();
        if (!cancelled) setUser(me);
      } catch {
        localStorage.removeItem("auth_token");
        if (!cancelled && !isPublicPath) router.replace("/login");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loginFn = useCallback(
    async (username: string, password: string) => {
      const { access_token } = await apiLogin(username, password);
      localStorage.setItem("auth_token", access_token);
      const me = await getMe();
      setUser(me);
      router.replace("/");
    },
    [router]
  );

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token");
    setUser(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user,
      login: loginFn,
      logout,
    }),
    [user, isLoading, loginFn, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
