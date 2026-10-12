import { createContext, useState, useContext, useCallback } from 'react';
import type { ReactNode } from 'react';
import { setToken as setApiToken, logout as signOutOnServer } from './api';

interface Auth {
  token: string | null;
  username: string | null;
  isAuthenticated: boolean;
  login: (token: string, username: string) => void;
  logout: () => void;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children?: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);

  // Derived — no separate state needed
  const isAuthenticated = !!token;

  const login = useCallback((newToken: string, newUsername: string) => {
    setToken(newToken);
    setUsername(newUsername);
    setApiToken(newToken);
  }, []);

  // Also removes the server's refresh cookie, so a reload does not sign the user back in
  const logout = useCallback(() => {
    setToken(null);
    setUsername(null);
    setApiToken(null);
    signOutOnServer().catch(() => {});
  }, []);

  return (
    <AuthContext.Provider value={{ token, username, isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('useAuth must be used inside an AuthProvider');
  return auth;
}
