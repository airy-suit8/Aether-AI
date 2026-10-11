import React, { createContext, useState, useContext, useCallback } from 'react';
import { setToken as setApiToken } from './api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null);

  // Derived — no separate state needed
  const isAuthenticated = !!token;

  const login = useCallback((newToken) => {
    setToken(newToken);
    setApiToken(newToken);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setApiToken(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
