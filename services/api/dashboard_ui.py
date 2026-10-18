"""Web UI Dashboard template for Mumbai Air Quality (UN SDG 3).

Renders a self-contained, responsive HTML5 + Tailwind CSS dashboard with
real-time metrics, station comparison, 24-hour historical trends, and SRE status.
"""

from __future__ import annotations


def get_dashboard_html() -> str:
    """Return the complete standalone HTML string for the SDG dashboard."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SENTINEL — Mumbai Air Quality Dashboard (SDG 3)</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @keyframes pulse-slow {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.85; transform: scale(1.03); }
    }
    .pulse-dot {
      animation: pulse-slow 2s infinite ease-in-out;
    }
    .gauge-bg {
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans antialiased">
  <!-- Top Navigation & SDG Header -->
  <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex flex-wrap items-center justify-between gap-4">
      <div class="flex items-center space-x-3">
        <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
          <svg class="h-6 w-6 text-slate-950" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 10V3L4 14h7v7l9-11h-7z"/>
          </svg>
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-lg font-bold tracking-tight text-white">SENTINEL Air Sentinel</h1>
            <span class="text-xs px-2 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">UN SDG 3</span>
          </div>
          <p class="text-xs text-slate-400">Mumbai Air Quality & Public Health Monitoring</p>
        </div>
      </div>

      <!-- Action status & Refresh -->
      <div class="flex items-center gap-3">
        <div id="mode-badge" class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs">
          <span id="mode-dot" class="h-2.5 w-2.5 rounded-full bg-emerald-400 pulse-dot"></span>
          <span id="mode-text" class="text-slate-300 font-medium">Connecting...</span>
        </div>
        <button id="refresh-btn" onclick="loadData(true)" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-xs font-semibold text-white transition flex items-center gap-1.5 shadow-sm shadow-emerald-900/30">
          <svg id="refresh-icon" class="h-3.5 w-3.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          <span id="refresh-label">Refresh</span>
        </button>
      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

    <!-- SDG 3 Target Banner -->
    <section class="rounded-2xl border border-emerald-500/20 bg-gradient-to-r from-emerald-950/40 via-slate-900/80 to-slate-900/80 p-5 shadow-lg relative overflow-hidden">
      <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div class="space-y-1">
          <div class="flex items-center gap-2">
            <span class="text-xs uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300">Sustainable Development Goal 3</span>
            <span class="text-xs text-slate-400">Target 3.9 — Air Pollution & Health Risk Reduction</span>
          </div>
          <h2 class="text-xl font-bold text-white tracking-tight">Real-Time Atmospheric Health Telemetry for Greater Mumbai</h2>
          <p class="text-sm text-slate-300 max-w-3xl">
            Continuously tracking breathable particulate matter ($PM_{2.5}, PM_{10}$) and toxic gaseous pollutants across 8 municipal zones. Integrated into SENTINEL SRE observability via Prometheus & Grafana.
          </p>
        </div>
        <div class="text-right flex flex-col items-start md:items-end text-xs text-slate-400 space-y-0.5">
          <div class="flex items-center gap-1.5">
            <span class="text-slate-400">Observation Time:</span>
            <span id="obs-timestamp" class="text-sm font-semibold text-emerald-400 font-mono">--:--</span>
          </div>
          <div class="flex items-center gap-1.5 text-[11px]">
            <span class="text-slate-400">Last Synced:</span>
            <span id="last-updated" class="font-mono text-slate-300">--:--</span>
          </div>
          <div id="obs-source" class="text-[10px] text-slate-400">Open-Meteo / Copernicus CAMS Grid</div>
        </div>
      </div>
    </section>

    <!-- Error State Container (Hidden by default) -->
    <div id="error-banner" class="hidden rounded-xl border border-red-500/30 bg-red-950/40 p-4 text-red-200 text-sm flex items-center justify-between">
      <div class="flex items-center gap-3">
        <svg class="h-5 w-5 text-red-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
        </svg>
        <span id="error-message">Unable to reach air quality API. Using verified historical fallback data.</span>
      </div>
      <button onclick="loadData()" class="px-2.5 py-1 rounded bg-red-800 hover:bg-red-700 text-xs font-medium text-white transition">Retry</button>
    </div>

    <!-- Loading State Skeleton -->
    <div id="loading-state" class="py-12 flex flex-col items-center justify-center space-y-3">
      <div class="h-10 w-10 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin"></div>
      <p class="text-sm text-slate-400">Querying Mumbai atmospheric monitoring stations...</p>
    </div>

    <!-- Content Section (Shown once loaded) -->
    <div id="content-section" class="hidden space-y-6">
      
      <!-- Key KPI Metric Cards -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- Average City AQI -->
        <div class="gauge-bg rounded-2xl border border-slate-800 p-5 shadow-lg relative">
          <div class="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Mumbai Average AQI</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">US AQI</span>
          </div>
          <div class="flex items-baseline gap-3">
            <span id="kpi-avg-aqi" class="text-4xl font-extrabold font-mono text-white">--</span>
            <span id="kpi-avg-badge" class="text-xs px-2.5 py-1 rounded-full font-semibold bg-slate-800 text-slate-300">--</span>
          </div>
          <p id="kpi-advisory" class="text-xs text-slate-400 mt-3 line-clamp-2">Loading health advisory...</p>
        </div>

        <!-- Dominant Pollutant (PM2.5) -->
        <div class="gauge-bg rounded-2xl border border-slate-800 p-5 shadow-lg">
          <div class="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Primary Health Hazard ($PM_{2.5}$)</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">μg/m³</span>
          </div>
          <div class="flex items-baseline gap-3">
            <span id="kpi-avg-pm25" class="text-4xl font-extrabold font-mono text-amber-400">--</span>
            <span class="text-xs text-slate-400">Fine inhalable particles</span>
          </div>
          <p class="text-xs text-slate-400 mt-3">WHO annual safety guideline: 5 μg/m³</p>
        </div>

        <!-- Coarse Particulate (PM10) -->
        <div class="gauge-bg rounded-2xl border border-slate-800 p-5 shadow-lg">
          <div class="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Coarse Dust & Smoke ($PM_{10}$)</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">μg/m³</span>
          </div>
          <div class="flex items-baseline gap-3">
            <span id="kpi-avg-pm10" class="text-4xl font-extrabold font-mono text-orange-400">--</span>
            <span class="text-xs text-slate-400">Respirable dust</span>
          </div>
          <p class="text-xs text-slate-400 mt-3">CPCB 24h standard: 100 μg/m³</p>
        </div>

        <!-- Cleanest vs Most Polluted -->
        <div class="gauge-bg rounded-2xl border border-slate-800 p-5 shadow-lg flex flex-col justify-between">
          <div class="text-xs text-slate-400 mb-2">Spatial Contrast</div>
          <div class="space-y-2">
            <div class="flex items-center justify-between text-xs">
              <span class="text-slate-400">Highest AQI:</span>
              <span id="kpi-highest-station" class="font-semibold text-red-400 font-mono">--</span>
            </div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-slate-400">Lowest AQI:</span>
              <span id="kpi-lowest-station" class="font-semibold text-emerald-400 font-mono">--</span>
            </div>
          </div>
          <div class="text-[11px] text-slate-400 mt-2">Active Stations: 8</div>
        </div>
      </div>

      <!-- Station Comparison & Grid Section -->
      <section class="space-y-3">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h3 class="text-base font-bold text-white tracking-tight">Monitoring Stations Breakdown</h3>
            <p class="text-xs text-slate-400">Station-level AQI indices and pollutant concentrations across 8 municipal zones</p>
          </div>
          <span class="text-xs font-mono text-slate-400">8 Stations Monitored</span>
        </div>

        <!-- CAMS Model Grid Transparency Note -->
        <div class="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5 text-xs text-slate-400 flex items-start gap-3">
          <svg class="h-5 w-5 text-cyan-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <div class="space-y-1">
            <div class="font-semibold text-slate-300">Spatial Grid Modeling Transparency (Copernicus CAMS / ECMWF)</div>
            <p class="leading-relaxed">
              Open-Meteo integrates European CAMS global atmospheric dispersion models at ~0.1° (~11 km) spatial resolution. Central and inland Mumbai stations share regional aerosol grid cells ($PM_{2.5}, PM_{10}$), while coastal Colaba captures distinct maritime boundary layer dynamics and localized gaseous emissions ($CO$) vary across municipal zones.
            </p>
          </div>
        </div>

        <div id="stations-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <!-- Dynamically populated station cards -->
        </div>
      </section>

      <!-- 24-Hour Historical Trend Section -->
      <section class="gauge-bg rounded-2xl border border-slate-800 p-6 shadow-xl space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div class="flex items-center gap-2">
              <h3 class="text-base font-bold text-white tracking-tight">24-Hour Historical Trend</h3>
              <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-cyan-400 font-mono">Hourly Series</span>
            </div>
            <p class="text-xs text-slate-400">Diurnal evolution of US AQI and Particulate Matter ($PM_{2.5}$)</p>
          </div>
          <div class="flex items-center gap-2">
            <label for="station-select" class="text-xs text-slate-400">Select Station:</label>
            <select id="station-select" onchange="loadTrend(this.value)" class="bg-slate-900 border border-slate-700 text-xs text-white rounded-lg px-3 py-1.5 focus:outline-none focus:border-emerald-500">
              <option value="Bandra">Bandra (West)</option>
              <option value="Colaba">Colaba (South)</option>
              <option value="Kurla">Kurla (Central)</option>
              <option value="Worli">Worli (South-Central)</option>
              <option value="BKC">BKC (Central)</option>
              <option value="Andheri">Andheri (North-West)</option>
              <option value="Borivali">Borivali (North)</option>
              <option value="Navi Mumbai">Navi Mumbai (East)</option>
            </select>
          </div>
        </div>

        <!-- Interactive SVG Trend Chart -->
        <div id="chart-container" class="w-full bg-slate-900/90 rounded-xl p-4 border border-slate-800 overflow-x-auto">
          <svg id="trend-svg" class="w-full min-w-[600px] h-48" viewBox="0 0 800 200" preserveAspectRatio="none">
            <!-- Dynamic SVG elements -->
          </svg>
        </div>

        <div class="flex items-center justify-between text-xs text-slate-400 pt-1">
          <div class="flex items-center gap-4">
            <div class="flex items-center gap-1.5">
              <span class="h-2.5 w-2.5 rounded-full bg-emerald-400"></span>
              <span>AQI Trend</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="h-2.5 w-2.5 rounded-full bg-amber-400"></span>
              <span>$PM_{2.5}$ (μg/m³)</span>
            </div>
          </div>
          <span id="trend-source-label" class="font-mono text-[11px] text-slate-400">Live hourly series from Open-Meteo</span>
        </div>
      </section>

      <!-- SRE & DevOps Integration Panel -->
      <section class="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-sm uppercase tracking-wider font-bold text-slate-300">DevOps & SRE Integration Links</h3>
            <p class="text-xs text-slate-400">Direct production endpoints used by Prometheus scrapers, ArgoCD, and automated incident remediators</p>
          </div>
          <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">Production Endpoints</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          <!-- Card 1: /metrics -->
          <div class="rounded-xl bg-slate-900/80 border border-slate-800 p-4 flex flex-col justify-between hover:border-slate-700 transition space-y-3">
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-xs font-semibold text-emerald-400">Prometheus Telemetry</span>
                <span class="text-[10px] font-mono bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">Scrape Target</span>
              </div>
              <p class="text-xs text-slate-400 leading-relaxed">
                Exposes raw Prometheus exposition text formatted for metric scrapers (AQI gauges, HTTP latency, daemon counters).
              </p>
            </div>
            <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between">
              <code class="text-xs text-slate-300 font-mono">/metrics</code>
              <a href="/metrics" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-emerald-300 hover:text-emerald-200 border border-slate-700 transition inline-flex items-center gap-1">
                View Raw Metrics
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
              </a>
            </div>
          </div>

          <!-- Card 2: /api/v1/air-quality -->
          <div class="rounded-xl bg-slate-900/80 border border-slate-800 p-4 flex flex-col justify-between hover:border-slate-700 transition space-y-3">
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-xs font-semibold text-cyan-400">Air Quality JSON API</span>
                <span class="text-[10px] font-mono bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">REST API</span>
              </div>
              <p class="text-xs text-slate-400 leading-relaxed">
                Delivers live Mumbai air quality telemetry across all 8 zones, with pollutant concentrations, CAMS attribution, and health categories.
              </p>
            </div>
            <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between">
              <code class="text-xs text-slate-300 font-mono">/api/v1/air-quality</code>
              <a href="/api/v1/air-quality" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-300 hover:text-cyan-200 border border-slate-700 transition inline-flex items-center gap-1">
                Inspect JSON API
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
              </a>
            </div>
          </div>

          <!-- Card 3: /incidents/latest -->
          <div class="rounded-xl bg-slate-900/80 border border-slate-800 p-4 flex flex-col justify-between hover:border-slate-700 transition space-y-3">
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-xs font-semibold text-amber-400">Incident Gateway</span>
                <span class="text-[10px] font-mono bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">SRE Loop</span>
              </div>
              <p class="text-xs text-slate-400 leading-relaxed">
                Exposes the latest automated SRE incident record, Ollama LLM root-cause diagnosis, runbook execution, and Phase 7 health verification.
              </p>
            </div>
            <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between">
              <code class="text-xs text-slate-300 font-mono">/incidents/latest</code>
              <a href="/incidents/latest" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-amber-300 hover:text-amber-200 border border-slate-700 transition inline-flex items-center gap-1">
                View Incidents
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
              </a>
            </div>
          </div>

          <!-- Card 4: /healthz -->
          <div class="rounded-xl bg-slate-900/80 border border-slate-800 p-4 flex flex-col justify-between hover:border-slate-700 transition space-y-3">
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-xs font-semibold text-blue-400">Service Health Probe</span>
                <span class="text-[10px] font-mono bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">K8s Probe</span>
              </div>
              <p class="text-xs text-slate-400 leading-relaxed">
                Kubernetes liveness and readiness probe endpoint reporting API gateway daemon status and database connectivity.
              </p>
            </div>
            <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between">
              <code class="text-xs text-slate-300 font-mono">/healthz</code>
              <a href="/healthz" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-blue-300 hover:text-blue-200 border border-slate-700 transition inline-flex items-center gap-1">
                Check Health
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
              </a>
            </div>
          </div>
        </div>
      </section>

    </div>
  </main>

  <!-- Footer with Full Attribution & Limitations -->
  <footer class="border-t border-slate-800 bg-slate-950/80 py-6 text-xs text-slate-400 mt-auto">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-2">
      <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
        <p><strong class="text-slate-300">Data Source Attribution:</strong> Atmospheric telemetry provided by <a href="https://open-meteo.com/en/docs/air-quality-api" target="_blank" class="underline hover:text-emerald-400">Open-Meteo Air Quality API</a> utilizing European Copernicus Atmosphere Monitoring Service (CAMS) and ECMWF global atmospheric dispersion models.</p>
        <span class="font-mono text-slate-400">SENTINEL Platform v0.1.0</span>
      </div>
      <p><strong class="text-slate-300">Data Limitations & Transparency:</strong> Real-time station observations represent spatial grid assimilation. If the external API is unreachable or rate-limited, the system automatically falls back to verified historical reference data with explicit indicator badges.</p>
    </div>
  </footer>

  <script>
    let currentStationsData = [];

    async function loadData(force = false) {
      const loading = document.getElementById('loading-state');
      const content = document.getElementById('content-section');
      const errBanner = document.getElementById('error-banner');
      const modeText = document.getElementById('mode-text');
      const modeDot = document.getElementById('mode-dot');
      const modeBadge = document.getElementById('mode-badge');
      const obsTimestamp = document.getElementById('obs-timestamp');
      const obsSource = document.getElementById('obs-source');
      const lastUpdated = document.getElementById('last-updated');
      const refreshBtn = document.getElementById('refresh-btn');
      const refreshLabel = document.getElementById('refresh-label');
      const refreshIcon = document.getElementById('refresh-icon');

      if (force && refreshLabel && refreshIcon) {
        refreshLabel.textContent = 'Updating...';
        refreshIcon.classList.add('animate-spin');
        refreshBtn.disabled = true;
      }

      try {
        const url = force ? '/api/v1/air-quality?force_refresh=true' : '/api/v1/air-quality';
        const res = await fetch(url);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        currentStationsData = data.stations || [];

        // Update mode badge
        if (data.data_mode === 'live' && !data.is_stale) {
          modeDot.className = 'h-2.5 w-2.5 rounded-full bg-emerald-400 pulse-dot';
          modeText.textContent = 'Live CAMS Grid Data';
          modeBadge.className = 'flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-950/40 border border-emerald-500/30 text-xs';
          errBanner.classList.add('hidden');
        } else if (data.is_stale) {
          modeDot.className = 'h-2.5 w-2.5 rounded-full bg-amber-400 pulse-dot';
          modeText.textContent = 'Cached Data (Stale)';
          modeBadge.className = 'flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-950/40 border border-amber-500/30 text-xs';
          document.getElementById('error-message').textContent = data.stale_reason || 'Upstream API issue: serving cached telemetry.';
          errBanner.classList.remove('hidden');
        } else {
          modeDot.className = 'h-2.5 w-2.5 rounded-full bg-amber-400';
          modeText.textContent = 'Verified Historical Baseline';
          modeBadge.className = 'flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-950/40 border border-amber-500/30 text-xs';
          document.getElementById('error-message').textContent = 'Displaying verified historical baseline snapshot (' + (data.attribution || 'CAMS reference') + ')';
          errBanner.classList.remove('hidden');
        }

        obsTimestamp.textContent = data.observation_time || data.timestamp || '--:--';
        if (lastUpdated) {
          lastUpdated.textContent = data.last_updated || new Date().toLocaleTimeString();
        }
        obsSource.textContent = data.data_type || data.data_source || 'Open-Meteo / CAMS';

        // Update KPIs
        document.getElementById('kpi-avg-aqi').textContent = data.city_average_aqi;
        const avgCat = data.city_category || { level: 'Moderate', color: '#f59e0b', advisory: '' };
        const badge = document.getElementById('kpi-avg-badge');
        badge.textContent = avgCat.level;
        badge.style.backgroundColor = avgCat.color + '25';
        badge.style.color = avgCat.color;
        badge.style.borderColor = avgCat.color + '60';
        document.getElementById('kpi-advisory').textContent = avgCat.advisory;

        // Calculate Average PM2.5 and PM10
        if (currentStationsData.length > 0) {
          const pm25Sum = currentStationsData.reduce((acc, s) => acc + (s.pollutants?.pm2_5?.value || 0), 0);
          const pm10Sum = currentStationsData.reduce((acc, s) => acc + (s.pollutants?.pm10?.value || 0), 0);
          document.getElementById('kpi-avg-pm25').textContent = (pm25Sum / currentStationsData.length).toFixed(1);
          document.getElementById('kpi-avg-pm10').textContent = (pm10Sum / currentStationsData.length).toFixed(1);

          // Find Highest and Lowest stations
          const sorted = [...currentStationsData].sort((a, b) => b.aqi - a.aqi);
          document.getElementById('kpi-highest-station').textContent = sorted[0].station + ' (' + sorted[0].aqi + ')';
          document.getElementById('kpi-lowest-station').textContent = sorted[sorted.length - 1].station + ' (' + sorted[sorted.length - 1].aqi + ')';
        }

        // Render station cards
        renderStations(currentStationsData);

        // Render initial trend
        const selectedStation = document.getElementById('station-select').value || 'Bandra';
        loadTrend(selectedStation, force);

        loading.classList.add('hidden');
        content.classList.remove('hidden');
      } catch (err) {
        console.error('Data load error:', err);
        document.getElementById('error-message').textContent = 'Error querying telemetry: ' + err.message + '. Retrying with fallback.';
        errBanner.classList.remove('hidden');
      } finally {
        if (refreshLabel && refreshIcon) {
          refreshLabel.textContent = 'Refresh';
          refreshIcon.classList.remove('animate-spin');
          refreshBtn.disabled = false;
        }
      }
    }

    function renderStations(stations) {
      const container = document.getElementById('stations-grid');
      container.innerHTML = '';

      stations.forEach(st => {
        const cat = st.category || { level: 'Moderate', color: '#f59e0b' };
        const card = document.createElement('div');
        card.className = 'gauge-bg rounded-xl border border-slate-800 p-4 shadow-md space-y-3 hover:border-slate-700 transition flex flex-col justify-between';

        const gridCoord = (st.grid_latitude && st.grid_longitude)
          ? `${Number(st.grid_latitude).toFixed(1)}°N, ${Number(st.grid_longitude).toFixed(1)}°E`
          : '--';
        const stCoord = (st.latitude && st.longitude)
          ? `${Number(st.latitude).toFixed(3)}°N, ${Number(st.longitude).toFixed(3)}°E`
          : '';

        card.innerHTML = `
          <div>
            <div class="flex items-start justify-between">
              <div>
                <h4 class="font-bold text-white text-sm">${st.station}</h4>
                <p class="text-[11px] text-slate-400">${st.zone}</p>
                <div class="text-[10px] text-slate-400 font-mono mt-0.5" title="Station Coordinates vs CAMS Grid Coordinates">
                  <span>Coord: ${stCoord}</span>
                  <span class="block text-cyan-400/80">Grid: ${gridCoord}</span>
                </div>
              </div>
              <span class="text-xs px-2 py-0.5 rounded-full font-bold font-mono" style="background-color: ${cat.color}25; color: ${cat.color}; border: 1px solid ${cat.color}50;">
                AQI ${st.aqi}
              </span>
            </div>

            <div class="space-y-1 mt-3">
              <div class="flex justify-between text-[11px] text-slate-400">
                <span>Category: <strong style="color: ${cat.color}">${cat.level}</strong></span>
              </div>
              <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div class="h-1.5 rounded-full" style="width: ${Math.min(100, (st.aqi / 300) * 100)}%; background-color: ${cat.color}"></div>
              </div>
            </div>
          </div>

          <div class="grid grid-cols-4 gap-1 pt-1 text-center">
            <div class="bg-slate-900/80 rounded p-1 border border-slate-800/80">
              <div class="text-[9px] text-slate-400 font-mono">PM2.5</div>
              <div class="text-xs font-semibold text-slate-200 font-mono">${st.pollutants?.pm2_5?.value ?? '--'}</div>
            </div>
            <div class="bg-slate-900/80 rounded p-1 border border-slate-800/80">
              <div class="text-[9px] text-slate-400 font-mono">PM10</div>
              <div class="text-xs font-semibold text-slate-200 font-mono">${st.pollutants?.pm10?.value ?? '--'}</div>
            </div>
            <div class="bg-slate-900/80 rounded p-1 border border-slate-800/80">
              <div class="text-[9px] text-slate-400 font-mono">NO₂</div>
              <div class="text-xs font-semibold text-slate-200 font-mono">${st.pollutants?.nitrogen_dioxide?.value ?? '--'}</div>
            </div>
            <div class="bg-slate-900/80 rounded p-1 border border-slate-800/80">
              <div class="text-[9px] text-slate-400 font-mono">CO</div>
              <div class="text-xs font-semibold text-cyan-300 font-mono">${st.pollutants?.carbon_monoxide?.value ?? '--'}</div>
            </div>
          </div>
        `;
        container.appendChild(card);
      });
    }

    async function loadTrend(station, force = false) {
      try {
        const url = '/api/v1/air-quality/history?station=' + encodeURIComponent(station) + (force ? '&force_refresh=true' : '');
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();
        renderChart(data.trend || []);
      } catch (e) {
        console.error('Trend load error:', e);
      }
    }

    function renderChart(points) {
      const svg = document.getElementById('trend-svg');
      if (!points || points.length === 0) return;

      const w = 800;
      const h = 200;
      const padL = 40;
      const padR = 20;
      const padT = 20;
      const padB = 30;

      const maxAQI = Math.max(250, ...points.map(p => p.aqi || 0));
      const n = points.length;
      const stepX = (w - padL - padR) / (n - 1 || 1);

      // Coordinates generator
      const getCoords = (val) => {
        return padT + (1 - (val / maxAQI)) * (h - padT - padB);
      };

      let aqiPath = '';
      let pm25Path = '';
      let dots = '';

      points.forEach((p, i) => {
        const x = padL + i * stepX;
        const yAqi = getCoords(p.aqi || 0);
        const yPm = getCoords(p.pm2_5 || 0);

        if (i === 0) {
          aqiPath += `M ${x} ${yAqi}`;
          pm25Path += `M ${x} ${yPm}`;
        } else {
          aqiPath += ` L ${x} ${yAqi}`;
          pm25Path += ` L ${x} ${yPm}`;
        }

        // Draw circles every 3 points to avoid clutter
        if (i % 3 === 0 || i === n - 1) {
          dots += `<circle cx="${x}" cy="${yAqi}" r="3" fill="#34d399"/>`;
          dots += `<text x="${x}" y="${h - 10}" fill="#94a3b8" font-size="10" font-family="monospace" text-anchor="middle">${p.hour || ''}</text>`;
        }
      });

      // Grid lines
      let grid = `
        <line x1="${padL}" y1="${padT}" x2="${w - padR}" y2="${padT}" stroke="#334155" stroke-dasharray="2,2"/>
        <line x1="${padL}" y1="${(padT + h - padB)/2}" x2="${w - padR}" y2="${(padT + h - padB)/2}" stroke="#334155" stroke-dasharray="2,2"/>
        <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="#475569"/>
        <text x="${padL - 6}" y="${padT + 4}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end">${maxAQI}</text>
        <text x="${padL - 6}" y="${(padT + h - padB)/2 + 4}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end">${Math.round(maxAQI/2)}</text>
        <text x="${padL - 6}" y="${h - padB}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end">0</text>
      `;

      svg.innerHTML = `
        ${grid}
        <path d="${aqiPath}" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="${pm25Path}" fill="none" stroke="#fbbf24" stroke-width="2" stroke-dasharray="3,3" stroke-linecap="round"/>
        ${dots}
      `;
    }

    // Auto-load on page ready & periodic refresh every 60s
    document.addEventListener('DOMContentLoaded', () => {
      loadData(false);
      setInterval(() => loadData(false), 60000);
    });
  </script>
</body>
</html>
"""
