import React, { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Box, CircularProgress, Typography, Button } from "@mui/material";

// Code-splitting: ogni pagina è un chunk separato (admin/dashboard non pesano
// sul primo load della pagina pubblica /apply).
const ApplyPage = lazy(() => import("./pages/ApplyPage.jsx"));
const AdminPage = lazy(() => import("./pages/AdminPage.jsx"));
const OnboardingPage = lazy(() => import("./pages/OnboardingPage.jsx"));
const BusinessPage = lazy(() => import("./pages/BusinessPage.jsx"));
const AccountCreatePage = lazy(() => import("./pages/AccountCreatePage.jsx"));

function PageLoader() {
  return (
    <Box sx={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}>
      <CircularProgress size={34} />
    </Box>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Box sx={{ minHeight: "100dvh", display: "grid", placeItems: "center", p: 3 }}>
        <Box sx={{ textAlign: "center", maxWidth: 420 }}>
          <Typography variant="h5" sx={{ mb: 1 }}>Qualcosa è andato storto</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {String(this.state.error?.message || this.state.error)}
          </Typography>
          <Button variant="contained" onClick={() => location.reload()}>Ricarica</Button>
        </Box>
      </Box>
    );
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/" element={<Navigate to="/apply" replace />} />
          <Route path="/apply" element={<ApplyPage />} />
          <Route path="/admin/*" element={<AdminPage />} />
          <Route path="/onboarding/:token" element={<OnboardingPage />} />
          <Route path="/account/:token" element={<AccountCreatePage />} />
          <Route path="/dashboard/*" element={<BusinessPage />} />
          <Route path="*" element={<Navigate to="/apply" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
