import React, { createContext, useState, useContext, useCallback } from 'react';
import { setToken as setApiToken, logout as signOutOnServer } from './api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null);
  const [username, setUsername] = useState(null);

  // Derived — no separate state needed
  const isAuthenticated = !!token;

  const login = useCallback((newToken, newUsername) => {
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

export function useAuth() {
  return useContext(AuthContext);
}
