import { create } from "zustand";
import {
  accountLogin,
  accountLogout,
  accountMe,
  accountRefresh,
  accountRegister,
  setAuthToken,
  AccountMe,
} from "../api/client";

interface AuthState {
  token: string | null;
  account: AccountMe | null;
  loading: boolean;
  error: string | null;
  initialized: boolean;

  initialize: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  account: null,
  loading: false,
  error: null,
  initialized: false,

  initialize: async () => {
    try {
      const result = await accountRefresh();
      if (result) {
        const account = await accountMe(result.access_token);
        setAuthToken(result.access_token);
        set({ token: result.access_token, account, initialized: true });
      } else {
        set({ initialized: true });
      }
    } catch {
      set({ initialized: true });
    }
  },

  login: async (email, password) => {
    set({ loading: true, error: null });
    try {
      const result = await accountLogin(email, password);
      const account = await accountMe(result.access_token);
      setAuthToken(result.access_token);
      set({ token: result.access_token, account, loading: false });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Login failed", loading: false });
    }
  },

  register: async (email, password) => {
    set({ loading: true, error: null });
    try {
      await accountRegister(email, password);
      const result = await accountLogin(email, password);
      const account = await accountMe(result.access_token);
      setAuthToken(result.access_token);
      set({ token: result.access_token, account, loading: false });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Registration failed", loading: false });
    }
  },

  logout: async () => {
    await accountLogout();
    setAuthToken(null);
    set({ token: null, account: null });
  },

  clearError: () => set({ error: null }),
}));
