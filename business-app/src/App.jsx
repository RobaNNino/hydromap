import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import ApplyPage from "./pages/ApplyPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import OnboardingPage from "./pages/OnboardingPage.jsx";
import BusinessPage from "./pages/BusinessPage.jsx";
import AccountCreatePage from "./pages/AccountCreatePage.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/apply" replace />} />
      <Route path="/apply" element={<ApplyPage />} />
      <Route path="/admin/*" element={<AdminPage />} />
      <Route path="/onboarding/:token" element={<OnboardingPage />} />
      <Route path="/account/:token" element={<AccountCreatePage />} />
      <Route path="/dashboard/*" element={<BusinessPage />} />
      <Route path="*" element={<Navigate to="/apply" replace />} />
    </Routes>
  );
}
