import React, { useState } from "react";
import { Box, Card, CardContent, Typography, Stack, ToggleButton, ToggleButtonGroup, CircularProgress, Chip } from "@mui/material";
import { LineChart } from "@mui/x-charts/LineChart";
import { BarChart } from "@mui/x-charts/BarChart";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { EVENT_LABELS } from "../lib/constants.js";

function delta(cur, prev) {
  if (!prev) return cur ? "+100%" : "0%";
  const d = Math.round(((cur - prev) / prev) * 100);
  return (d >= 0 ? "+" : "") + d + "%";
}

export default function AnalyticsView({ fetchPath, queryKey }) {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: [...queryKey, days], queryFn: () => api(`${fetchPath}?days=${days}`) });

  if (q.isLoading) return <Box sx={{ display: "grid", placeItems: "center", py: 6 }}><CircularProgress /></Box>;
  const d = q.data || { series: [], totals: {}, prev_totals: {} };
  const labels = d.series.map((s) => s.day.slice(5));
  const clickTypes = Object.keys(EVENT_LABELS).filter((e) => e.startsWith("click_"));
  const clickVals = clickTypes.map((e) => d.totals[e] || 0);

  const kpis = [
    ["view", "Visualizzazioni"], ["open_map", "Aperture mappa"],
    ["click_phone", "Click telefono"], ["click_website", "Click sito"],
  ];

  return (
    <Stack spacing={2}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
        <Typography variant="h6">Andamento</Typography>
        <ToggleButtonGroup size="small" exclusive value={days} onChange={(_e, v) => v && setDays(v)}>
          <ToggleButton value={7}>7g</ToggleButton>
          <ToggleButton value={30}>30g</ToggleButton>
          <ToggleButton value={90}>90g</ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4,1fr)" }, gap: 2 }}>
        {kpis.map(([k, l]) => (
          <Card key={k}><CardContent>
            <Typography variant="h5" sx={{ fontWeight: 800 }}>{d.totals[k] || 0}</Typography>
            <Typography variant="body2" color="text.secondary">{l}</Typography>
            <Chip size="small" label={delta(d.totals[k] || 0, d.prev_totals[k] || 0)}
              color={(d.totals[k] || 0) >= (d.prev_totals[k] || 0) ? "success" : "default"} sx={{ mt: 0.5 }} />
          </CardContent></Card>
        ))}
      </Box>

      <Card><CardContent>
        <Typography variant="subtitle1" gutterBottom>Visualizzazioni & interazioni</Typography>
        {labels.length ? (
          <LineChart height={260}
            xAxis={[{ scaleType: "point", data: labels }]}
            series={[
              { data: d.series.map((s) => s.view || 0), label: "Visualizzazioni", area: true, color: "#0492cf", showMark: false },
              { data: d.series.map((s) => clickTypes.reduce((a, e) => a + (s[e] || 0), 0)), label: "Click", color: "#1bb2bd", showMark: false },
            ]}
            margin={{ left: 40, right: 16, top: 16, bottom: 24 }} />
        ) : <Typography color="text.secondary">Nessun dato nel periodo.</Typography>}
      </CardContent></Card>

      <Card><CardContent>
        <Typography variant="subtitle1" gutterBottom>Click per tipo</Typography>
        {clickVals.some(Boolean) ? (
          <BarChart height={260}
            xAxis={[{ scaleType: "band", data: clickTypes.map((e) => EVENT_LABELS[e].replace("Click ", "")) }]}
            series={[{ data: clickVals, color: "#0492cf" }]}
            margin={{ left: 40, right: 16, top: 16, bottom: 40 }} />
        ) : <Typography color="text.secondary">Ancora nessun click registrato.</Typography>}
      </CardContent></Card>
    </Stack>
  );
}
