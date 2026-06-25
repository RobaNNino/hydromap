import React, { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "./supabase.js";

const AuthCtx = createContext({ user: null, loading: true });

export function AuthProvider({ children }) {
  const [state, setState] = useState({ user: null, loading: true });

  useEffect(() => {
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (active) setState({ user: data?.session?.user || null, loading: false });
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      setState({ user: session?.user || null, loading: false });
    });
    return () => { active = false; sub?.subscription?.unsubscribe(); };
  }, []);

  const value = {
    ...state,
    signIn: (email, password) => supabase.auth.signInWithPassword({ email, password }),
    signUp: (email, password) => supabase.auth.signUp({ email, password }),
    signOut: () => supabase.auth.signOut(),
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
