# MeghDrishti — Frontend Product Requirements Document (PRD)

**Document type:** Frontend PRD / Build Spec for AI coding agents
**Product:** MeghDrishti — Cloudburst & Flash-Flood Early Warning System
**Scope of this document:** Frontend only (Admin Tactical Dashboard + Citizen Survival Portal, Online & Offline PWA modes)
**Intended reader:** An AI vibe-coding agent (or human dev) building the frontend from scratch, with zero prior context beyond this file.

---

## 0. How to Use This Document

This PRD is written so that a coding agent can:
1. Scaffold the monorepo and both apps (Section 1–2).
2. Apply the exact design system/tokens (Section 3) to every component it builds.
3. Build each page section-by-section, panel-by-panel (Sections 4–6), using the specified layout regions, components, and interaction contracts.
4. Wire every clickable element to its exact behavior (interaction tables in each section — "Trigger → Action → Result").
5. Implement state management and data flow exactly as specified (Section 7).
6. Handle offline/PWA behavior exactly as specified (Section 6).
7. Validate against the acceptance checklist (Section 9).

Do not invent new pages, panels, or flows not described here. Where an implementation detail is left open (e.g., exact color hex), the agent should choose a value consistent with Section 3's design tokens and note the choice in code comments.

---

## 1. Product Overview

MeghDrishti is a disaster-response platform for cloudburst and flash-flood prediction (piloted for Chamoli District). The frontend has **one core mission: minimize cognitive load during a crisis**, served through two audiences with opposite needs:

| Audience | App | Cognitive Mode | Network Assumption |
| :--- | :--- | :--- | :--- |
| NDRF Commander / Admin Operator | Admin Tactical Command Dashboard (`/admin`) | High information density, expert operator, sustained attention | Stable connection (command center) |
| Citizen in/near disaster zone | Citizen Survival Portal (`/portal`) — Online Mode | Simple, reassuring, action-first | Full bandwidth |
| Citizen in/near disaster zone | Citizen Survival Portal (`/portal`) — Offline PWA | Extreme panic, near-zero cognitive bandwidth | No/degraded network |

These are **two distinct Next.js applications** in a single monorepo, sharing one design system and a set of common utilities/types, but never sharing page-level UI code.

---

## 2. Monorepo & App Structure

```
meghdrishti/
├── apps/
│   ├── admin/                  # Next.js app — Tactical Command Dashboard
│   │   ├── app/
│   │   │   ├── (auth)/login/
│   │   │   ├── admin/           # main SPA shell + map + panels
│   │   │   └── layout.tsx
│   │   └── ...
│   └── portal/                  # Next.js app — Citizen Survival Portal
│       ├── app/
│       │   ├── portal/          # online mode
│       │   ├── offline/         # PWA fallback shell (precompiled, static)
│       │   └── layout.tsx
│       ├── public/
│       │   └── sw.js            # service worker
│       └── ...
├── packages/
│   ├── ui/                      # shared Tailwind-based design system components
│   ├── map-core/                # shared Mapbox GL wrapper utilities, layer factories
│   ├── stores/                  # shared Zustand store factories/types
│   ├── api-client/               # React Query hooks + FastAPI client (typed)
│   └── config/                  # shared Tailwind config, ESLint, TS config
├── turbo.json  (or nx.json)
└── package.json
```

**Build tool:** TurboRepo (preferred) or Nx.
**Rule:** No cross-imports between `apps/admin` and `apps/portal`. All sharing goes through `packages/*`.

---

## 3. Design System (Applies to Both Apps)

### 3.1 Two Visual Themes

The two apps are visually distinct on purpose — they signal "which mode am I in" instantly.

| Token | Admin (Tactical Theme) | Citizen Online (Trust Theme) | Citizen Offline (Brutalist Theme) |
| :--- | :--- | :--- | :--- |
| Base mode | Dark mode, always on | Light, airy, high-trust | Forced high-contrast |
| Background | `#0B0F14` (near-black slate) | `#FFFFFF` / `#F5F7FA` | `#000000` |
| Primary text | `#E6EDF3` | `#0B0F14` | `#FFFFFF` |
| Accent / brand | `#22D3EE` (cyan — "signal") | `#2563EB` (calm blue) | `#FF0000` (red only) |
| Success / Safe | `#22C55E` | `#22C55E` | n/a (offline UI avoids color-coding beyond R/B/W) |
| Warning | `#F59E0B` | `#F59E0B` | n/a |
| Critical / Evacuate | `#EF4444` | `#EF4444` | `#FF0000` solid fill |
| Panel surface | `rgba(17,24,32,0.65)` + `backdrop-blur-md` (glassmorphism) | `#FFFFFF` with soft shadow | `#000000` flat, no blur, no shadow |
| Border radius | `rounded-xl` (12px) | `rounded-2xl` (16px) | `rounded-none` (0px — brutalist) |
| Font | Inter / IBM Plex Sans (tactical, monospace for coordinates/timestamps) | Inter (rounded, friendly weight usage) | System sans-serif stack only (`-apple-system, Roboto, Arial, sans-serif`) — no custom font loading (must work with zero network) |
| Motion | Subtle (150–250ms ease), map transitions eased | Gentle, reassuring (200–300ms) | **Zero animation** — instant state changes only |
| Iconography | `lucide-react`, thin-line tactical icon set | `lucide-react`, rounded/friendly | Minimal — text labels preferred over icons |

### 3.2 Tailwind Config Notes
- Single shared `tailwind.config` in `packages/config`, extended per-app with theme-specific token overrides via CSS variables (`--color-bg`, `--color-accent`, etc.) so both apps consume the same utility classes but resolve different values.
- Offline PWA shell must **not** depend on any Tailwind JIT class not present in a precompiled static bundle — it is built once and cached; no runtime class generation.
- Mobile-first breakpoints throughout: `sm` (portal target), `lg`+ (admin target, assumes large tactical displays/tablets).

### 3.3 Glassmorphism Panel Spec (Admin only)
```
background: rgba(17,24,32,0.65);
backdrop-filter: blur(12px);
border: 1px solid rgba(255,255,255,0.08);
box-shadow: 0 8px 32px rgba(0,0,0,0.35);
```
Used for all floating tactical panels over the map (Section 4.4).

### 3.4 Status Color Semantics (used across both apps)
| Status | Color | Meaning | Triggers |
| :--- | :--- | :--- | :--- |
| Green | `#22C55E` | Normal | Risk score < threshold A |
| Orange | `#F59E0B` | Warning | Risk score between threshold A–B |
| Red | `#EF4444` / `#FF0000` | Critical / Evacuate | Risk score ≥ threshold B, or Admin manual override |

This 3-tier status is the single source of truth driving: the Admin status bar, the Citizen alert banner, and the offline cached banner. All three read from the same backend "current alert status" field.

---

## 4. Sitemap / Information Architecture

```
/                     → Landing/redirect (role selection: Admin Login vs Citizen Portal)
/admin
  /login              → Admin auth
  /admin              → Main Tactical Dashboard (SPA, single route, panel-driven)
/portal
  /portal             → Citizen Portal home (online mode; also PWA install entry point)
  /portal/feed        → (optional deep link) Citizen CrowdFeed full view
  /offline             → Precompiled offline fallback shell (served by Service Worker when navigator.onLine === false or fetch fails)
```

Both `/admin` and `/portal` are effectively **single full-screen app shells**, not traditional multi-page scrolling sites. Navigation within them is panel-based (show/hide/expand), not route-based, except where explicitly noted.

---

## 5. Admin Tactical Command Dashboard (`/admin`)

### 5.1 Page Layout Regions

Full-viewport SPA (`h-screen w-screen overflow-hidden`), z-index layered as follows (bottom → top):

1. **Layer 0 — Map Canvas** (full-bleed, fills entire viewport behind everything)
2. **Layer 1 — Top Header Bar** (fixed top, full width, height ~64px, glassmorphism)
3. **Layer 2 — Floating Tactical Panels** (absolutely positioned over the map: left rail, right rail, bottom drawer)
4. **Layer 3 — Modals/Toasts** (verification confirmations, connection-loss alerts)

```
┌─────────────────────────────────────────────────────────────┐
│  [Logo/NDRF]     MeghDrishti Admin        [●Connected] [EN▾] │ ← Top Header (fixed)
├─────────────────────────────────────────────────────────────┤
│ ┌───────────────┐                          ┌────────────────┐│
│ │ Water-Rise     │                          │ Ground Truth   ││
│ │ Simulator      │        MAP CANVAS         │ Feed           ││
│ │ Panel          │      (Mapbox GL 3D)        │ (Community     ││
│ │ (left rail)    │                          │  Validation)   ││
│ └───────────────┘                          └────────────────┘│
│                                                                 │
│              ┌───────────────────────────────┐                │
│              │ LSTM Forecast Panel (bottom)   │                │
│              └───────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Top Header Bar

| Component | Description | Behavior |
| :--- | :--- | :--- |
| Logo/NDRF Section | Indian Govt emblem + "MeghDrishti Admin" wordmark, left-aligned | Static; clicking logo resets map to default bearing/pitch/zoom (home view) |
| Real-time Status Bar | Pill badge: `● Connected` (green dot) / `● Offline` (red dot) | Bound to a `navigator.onLine` listener + a heartbeat ping to the backend (poll every 10s via React Query). On transition to offline, badge turns red and a non-blocking toast appears: "Connection lost — data may be stale." |
| Vernacular Selector Dropdown | Dropdown: Hindi / English (extensible) | On change: (a) updates Zustand `locale` state, (b) re-renders all Admin UI copy via i18n, (c) sets the language used for **auto-generated citizen dispatch templates** (alert banner text, SMS templates) |

### 5.3 The Full-Screen Map Engine

**Library:** Mapbox GL JS via `react-map-gl`.

| Element | Spec |
| :--- | :--- |
| Base layer | 3D topographical mesh via `terrain-rgb` tiles; `pitch` and `bearing` are React state (`useState` or Zustand), initialized to a tactical oblique view (e.g., `pitch: 55, bearing: -20`) |
| Initial camera | Centered on Chamoli District bounding box; zoom level tuned so entire monitored basin is visible |
| Coordinate state | Managed centrally (Zustand `mapStore`: `{ lng, lat, zoom, pitch, bearing }`) so any panel/alert can programmatically move the camera |
| Auto-snap / focus zoom | When a new critical alert fires (via React Query poll detecting status change), the map camera **flies to** (`flyTo`) the alert's epicenter coordinate automatically, with an eased transition (~1.5s) |

### 5.4 Dynamic Map Overlays (GeoJSON layers, client-rendered)

All overlays are **live GeoJSON sources** polled by React Query and pushed into Zustand, which the Mapbox layer components subscribe to and re-render on change (no manual DOM manipulation).

| Layer | Render Type | Data Source | Update Trigger |
| :--- | :--- | :--- | :--- |
| Blue Inundation Polygons | `fill-extrusion`, translucent blue, extrusion height mapped to simulated water depth | Simulator endpoint (`POST /simulate`) response | Fires when "Run Simulation" button (Section 5.5) is clicked |
| ML Risk Zone Polygons | `fill` layer, color-ramp interpolation (Green→Yellow→Red) driven by `risk_score` property | `GET /risk-zones` (XGBoost output), polled every ~30s | React Query polling interval |
| Cloudburst Vector | Custom marker: large circle (radius scaled to confidence) + directional arrow (rotation = predicted advection bearing) | `GET /cloudburst-vector` (OpenCV advection model) | Polled every ~30s; arrow rotates via CSS transform bound to bearing value |
| Logistics Nodes | Mapbox `Marker` components with custom SVG icons: green "H" (Helipad), blue shield (Safe Haven) | `GET /logistics-nodes` (PostGIS) | Loaded once on mount, refreshed every 5 min. **Must render only nodes whose elevation is above the current max predicted inundation line** (filtered client-side against simulator output) |

**Interaction contract — clicking any overlay feature:**
- Click on a Risk Zone polygon → opens a small popup with `{risk_score, last_updated, affected_population_estimate}`.
- Click on a Logistics Node marker → opens popup with `{name, type, capacity, status}` and a "Dispatch Resource" button (posts to `/dispatch`).
- Click on Cloudburst Vector circle → opens popup with `{confidence, predicted_impact_time, predicted_impact_coordinate}`.

### 5.5 Floating Tactical Panels

All panels: glassmorphism style (Section 3.3), draggable is optional (not required for MVP), collapsible via a chevron in the panel header. Positioned absolutely; do not block map center by default.

#### Panel A1 — 3D Water-Rise Simulator (left rail, top)

| Element | Type | Behavior |
| :--- | :--- | :--- |
| Header | Text: "Water-Rise Simulator" + collapse chevron | Click chevron → collapses panel to header-only strip |
| Slider | Custom range input, `0–300 mm/hr`, step `5` | `onChange` updates local/Zustand `simulatedRainfallRate` state live; label above slider shows current value in real time (no lag) |
| "Run Simulation" Button | Primary CTA button, full-width, accent color | **onClick:** (1) sets button to loading state, (2) `useEffect`/mutation calls `POST /simulate` via React Query `useMutation` with `{ rate: simulatedRainfallRate }`, (3) on success, updates Zustand `inundationLayer` GeoJSON, which re-renders the Blue Inundation Polygon layer (5.4), (4) on error, shows inline error text below button and reverts loading state |
| Reset Button | Secondary/ghost button | **onClick:** resets slider to 0, clears simulated inundation layer from map |

#### Panel A2 — LSTM Prediction Forecast Panel (bottom drawer)

| Element | Type | Behavior |
| :--- | :--- | :--- |
| Chart | Recharts (or Chart.js) line graph, two series: rainfall index + soil moisture, shared X-axis (time) | Data fetched via React Query (`GET /forecast-timeseries`), polled every ~60s |
| Point interaction | Hover/tap on any point on the line | **onClick/onTap:** sets Zustand `selectedForecastTimestamp = T`; this is read by the Risk Zone layer and other panels to **filter/recompute the displayed risk forecast for time T** (i.e., other components subscribe to `selectedForecastTimestamp` and re-fetch or re-filter their own data scoped to `T`) |
| "Live" toggle | Small pill toggle top-right of panel | When ON (default): `selectedForecastTimestamp = now`, chart auto-scrolls with new data. When OFF (i.e., user has clicked a historical point): chart freezes on selected `T` until toggle is clicked again |

#### Panel B1 — Citizen Ground Truth Feed (right rail)

| Element | Type | Behavior |
| :--- | :--- | :--- |
| Header | "Community Validation — Unverified Reports (N)" where N = live count | Count bound to React Query data length |
| List | Scrollable vertical list of report cards (`overflow-y-auto`, fixed panel height) | Each card: thumbnail (compressed image), report type tag, timestamp, geotag coordinates (mono font), submitter reliability score (if available) |
| Image handling | Client-side compression **before** rendering raw MinIO images | Use `browser-image-compression` (or equivalent) to downscale/compress thumbnails on the fly so large MinIO-hosted images don't block the UI thread |
| "Verify" Button | Per-card button | **onClick:** fires `POST /reports/{id}/verify` via React Query mutation → on success, (1) removes card from unverified list (optimistic update), (2) if verified report escalates risk, may trigger a status re-poll, (3) shows a small success toast ("Report verified") |
| "Reject" Button | Per-card secondary button | **onClick:** `POST /reports/{id}/reject`, removes card with optimistic update |
| Card click (non-button area) | — | Clicking the card body (not the buttons) flies the map camera to that report's geotagged coordinate and opens its full-size image in a lightbox modal |

### 5.6 Admin Interaction Summary Table (Trigger → Action → Result)

| Trigger | Action Fired | Result |
| :--- | :--- | :--- |
| Click logo | Reset camera state | Map flies to home view |
| Toggle vernacular dropdown | Update `locale` state | UI copy + dispatch templates switch language |
| Move Water-Rise slider | Update local state only | Label updates live; no network call yet |
| Click "Run Simulation" | `POST /simulate` | Blue inundation polygon layer updates on map |
| Click chart point | Set `selectedForecastTimestamp` | Risk layer + forecast panels re-scope to time T |
| Click "Verify" on report card | `POST /reports/{id}/verify` | Card removed, toast shown, feed count decremented |
| Click "Reject" on report card | `POST /reports/{id}/reject` | Card removed, toast shown |
| Click report card body | Camera flyTo + open lightbox | Map recenters, image modal opens |
| Click Logistics Node marker | Open popup | Shows node info + "Dispatch Resource" button |
| Click "Dispatch Resource" | `POST /dispatch` | Confirmation toast; node status updates (e.g., "Dispatched") |
| Connection drops | `navigator.onLine` listener fires | Status badge → red, toast: "Connection lost" |
| New critical alert detected (poll) | Zustand `alertStatus` changes to Red | Map auto flyTo epicenter; status bar pulses red |

---

## 6. Citizen Survival Portal — Online Mode (`/portal`)

### 6.1 Design Intent

Shifts tone entirely from "tactical operator" to "empathetic public safety." Light theme, large tap targets (min 44×44px), minimal jargon, generous whitespace, reassuring color use except when status is Red (deliberately alarming).

### 6.2 Page Layout Regions (top → bottom, single scrollable mobile-first column, but map section is viewport-height on load)

```
┌─────────────────────────────┐
│   DYNAMIC ALERT BANNER       │ ← full-width, sticky top
├─────────────────────────────┤
│                               │
│    LIVE INTERACTIVE MAP      │ ← ~60vh on mobile
│    (user's pulsing dot)      │
│                               │
├─────────────────────────────┤
│ [Route to Safe Haven] [View  │ ← 2-button grid
│                Helipads]     │
├─────────────────────────────┤
│   CITIZEN CROWDFEED          │ ← scroll section
│   (submit + browse reports)  │
└─────────────────────────────┘
```

### 6.3 Dynamic Alert Banner ("The Smart Hero")

| State | Visual | Behavior |
| :--- | :--- | :--- |
| Green (Normal) | Blue-tinted calm banner: "All Clear — Normal Conditions" | Default state; low visual weight |
| Orange (Warning) | Orange banner with caution icon: "Elevated Risk — Stay Alert" | Medium visual weight; may include a "View Safety Tips" link |
| Red (Critical) | **Full-width, massive RED banner takeover**: "EVACUATE NOW" in large bold type, covers significant vertical space, possibly pushes map down | Highest priority; on entering Red state, banner may also trigger a device vibration (if supported) and a prominent "Get Directions Now" button that jumps straight to the navigation flow (6.5) |

**Data binding:** Zustand store polls the same `GET /alert-status` endpoint the Admin dashboard uses (React Query, ~15–20s interval — more frequent than Admin since citizen safety is time-critical). Banner re-renders instantly on state change; no page reload.

### 6.4 Live Interactive Map (Mobile)

| Element | Spec |
| :--- | :--- |
| Base | Mapbox GL JS, mobile-optimized interaction (pinch-zoom, single-finger pan) |
| User location | Mapbox `GeolocateControl` / custom pulsing blue dot marker, tracks `navigator.geolocation.watchPosition` |
| Overlays | Same heatmap / predicted flood zone layers as Admin (read-only subset — no simulator controls, no ground-truth verification UI), synced via React Query |
| Permission handling | On first load, request geolocation permission with a friendly inline explainer ("We need your location to show the nearest safe route"); if denied, map still loads centered on district default, with a persistent small banner: "Enable location for personalized routing" |

### 6.5 PostGIS Traffic-Aware Navigation ("The Intelligent Route")

| Element | Type | Behavior |
| :--- | :--- | :--- |
| "Route to Nearest Safe Haven" | Large green tap-friendly button (grid left) | **onClick:** calls FastAPI backend route engine (`POST /route/safe-haven` with user's current lat/lng) — **not** the raw Mapbox Directions API. Backend filters out roads currently predicted to be flooded, then returns a topographical-safe geodesic LineString. Frontend draws this line on the map and auto-fits camera bounds to show full route + zooms/pans to follow user movement. Shows ETA and distance text below the map. |
| "View Logistical Helipads" | Large blue tap-friendly button (grid right) | **onClick:** fetches `GET /logistics-nodes?type=helipad`, plots helipad markers on the map, and pans/fits camera to show all helipads relative to user location. Does **not** draw a route — informational only. |
| Route drawn state | Line layer on map | Line uses distinct color from other overlays (e.g., solid green with white outline) so it reads clearly against heatmap layers |

### 6.6 High-Resolution "Citizen CrowdFeed" (Bidirectional)

| Element | Type | Behavior |
| :--- | :--- | :--- |
| "Report What You See" button | Prominent CTA, opens submission flow (modal or bottom sheet) | Opens camera capture UI using the phone's native camera API (`<input type="file" accept="image/*" capture="environment">` or `getUserMedia` for a custom capture UI) |
| Photo capture | Native camera integration | On capture: (1) client-side compresses image (same compression utility as Admin panel B1, shared via `packages/ui` or a shared hook), (2) extracts EXIF geotag if present, else falls back to current `navigator.geolocation` reading, (3) shows preview with a short caption/report-type field before submit |
| "Submit Report" button | Primary CTA in the capture flow | **onClick:** `POST /reports` (multipart, compressed image + geotag + caption) to MinIO-backed backend endpoint. On success: confirmation toast + the new report appears (as "pending verification") in a browsable feed list below the map. On failure (e.g., no network): **this is the trigger point that should route the user to Offline Mode behavior** if genuinely offline (see Section 7) — otherwise show retry option |
| Feed list | Scrollable card list below map | Shows community-submitted reports (verified ones shown with a checkmark badge; unverified shown as "Pending review") — read-only browsing for citizens, no verify/reject controls (those exist only in Admin) |
| Map integration | Auto-pin | Every submitted (and verified) report is automatically plotted on the live map at its EXIF/GPS coordinate as a small marker citizens can tap to view |

### 6.7 Citizen Online — Interaction Summary Table

| Trigger | Action Fired | Result |
| :--- | :--- | :--- |
| Alert status changes (poll) | Zustand `alertStatus` updates | Banner color/text/urgency changes instantly |
| Click "Get Directions Now" (Red banner) | Same as "Route to Nearest Safe Haven" | Jumps to navigation section, auto-triggers route call |
| Click "Route to Nearest Safe Haven" | `POST /route/safe-haven` | Safe geodesic route drawn on map, ETA/distance shown |
| Click "View Logistical Helipads" | `GET /logistics-nodes?type=helipad` | Helipad markers plotted, camera fits bounds |
| Click "Report What You See" | Opens capture UI | Native camera opens |
| Capture photo | Client-side compression + EXIF read | Preview shown with caption field |
| Click "Submit Report" | `POST /reports` (multipart) | Toast confirmation; report appears in feed as "Pending"; auto-pinned on map |
| Geolocation permission denied | Fallback state set | Map centers on district default; persistent reminder banner shown |

---

## 7. Citizen Survival Portal — Offline Mode (PWA Fallback)

### 7.1 Design Principle: Brutal Minimalism

This is a **separate, pre-compiled static route/shell** (not a degraded version of the online portal rendered dynamically) — it must be buildable and cacheable as a standalone static bundle so the Service Worker can serve it with zero network dependency.

| Rule | Enforcement |
| :--- | :--- |
| Font stack | System fonts only — no Google Fonts / custom `@font-face` (would require network) |
| Color palette | RED / BLACK / WHITE only | No gradients, no color-ramp heatmaps, no glassmorphism |
| Animation | **None.** All state changes are instant (no CSS transitions, no framer-motion) |
| Layout | Single column, large text, huge tap targets, zero decorative imagery |
| Map | Precached **vector tiles only** (roads + shelter points) — no satellite/3D terrain, since those tiles are far larger and weren't pre-downloaded |

### 7.2 Dynamic Hero Action Banner (Offline)

| State | Behavior |
| :--- | :--- |
| Cached status = Normal/Warning | Standard black background, white text, status message (last-synced timestamp shown, e.g., "Last updated: 12 min ago") |
| Cached status = Critical (>80% cached severity score) | Page loads **immediately** with a full-viewport solid RED banner: **"EVACUATE NOW"** — this is rendered from the Service Worker's last-cached status **before any other content**, so it appears instantly even on a fully offline load |

**Mechanism:** Service Worker (`sw.js`) intercepts navigation requests, checks its cache for the last-synced status object (stored via `caches` API or IndexedDB), and the offline shell's first paint reads directly from that cached value — no waiting on any fetch.

### 7.3 Offline Navigation (IndexedDB + PWA)

| Step | Detail |
| :--- | :--- |
| Pre-download (while online) | App proactively downloads a lightweight (~15MB) offline Mapbox vector tile set (roads-only, no satellite) covering Chamoli District + all PostGIS-verified safe haven coordinates. Stored in IndexedDB. This download is triggered automatically on first successful online load of `/portal`, with a small non-blocking progress indicator ("Downloading offline map… 40%") |
| "NAVIGATE TO NEAREST SAFE SPOT" button | Large, single, unmissable tap-friendly button — the primary (often only) interactive element on the offline shelter screen | **onClick:** (1) opens the cached vector map (roads only, no satellite), (2) reads phone's native GPS via `navigator.geolocation.getCurrentPosition` (works without any data connection, uses satellite/GPS hardware only), (3) runs a **client-side KNN check** comparing current coordinates against all cached shelter coordinates in IndexedDB, (4) draws user's position dot + a simple straight green geodesic line to the nearest shelter, (5) displays distance text: **"Nearest Safe Haven: 1.8km"** below the map |
| No live rerouting | Explicitly out of scope offline — this is a straight-line distance/bearing indicator, not turn-by-turn, since road-flood-filtering requires the backend route engine which is unavailable offline |

### 7.4 Low-Bandwidth Submit Form

| Element | Type | Behavior |
| :--- | :--- | :--- |
| Report Type | Native `<select>` dropdown (brutalist styled) | Simple enumerated list (e.g., "Flooding," "Blocked Road," "Person Needs Help," "Other") |
| Description | `<textarea maxLength={140}>` | Live character counter shown ("42/140") |
| Geotag | Automatic, silent | Captured via `navigator.geolocation.getCurrentPosition` at submit time — no map UI needed for this form |
| "Submit" button | Large brutalist button | **onClick:** does **not** attempt a network call. Payload `{type, description, geotag, timestamp}` is written directly to an IndexedDB "Sync Queue" object store. UI immediately shows confirmation: "Saved. Will send when connection returns." (No spinner, no network wait — this must feel instantaneous even fully offline) |

### 7.5 Automated Sync Queue

| Mechanism | Detail |
| :--- | :--- |
| Listeners | Service Worker registers both a `sync` event (Background Sync API where supported) and a `navigator.onLine`/`window.addEventListener('online', ...)` fallback listener |
| Trigger | The moment any network connectivity is detected (even degraded 2G) |
| Action | Service Worker reads all queued reports from IndexedDB and **POSTs them sequentially** (not in parallel, to avoid overwhelming a weak connection) to the FastAPI `/reports` endpoint |
| On each successful POST | Remove that item from the IndexedDB queue; if the user has the app foregrounded, show a toast: "1 offline report synced" |
| On failure mid-queue | Leave remaining items queued, retry on next `online` event or next `sync` event firing |
| Transition back to full online UI | Once connectivity is confirmed stable (not just one ping), the app should offer/allow navigation back to the full `/portal` online experience (e.g., a small non-intrusive banner: "Connection restored — tap to view live map") rather than forcing an immediate reload, to avoid jarring the user mid-crisis |

### 7.6 Offline Mode — Interaction Summary Table

| Trigger | Action Fired | Result |
| :--- | :--- | :--- |
| App loses connectivity / fetch fails | Service Worker serves cached offline shell | Brutalist UI loads instantly from cache; banner reflects last-synced status |
| Click "NAVIGATE TO NEAREST SAFE SPOT" | Local GPS read + client-side KNN against IndexedDB shelter list | Straight-line route + distance text rendered, no network call |
| Fill + submit low-bandwidth form | Write to IndexedDB Sync Queue | Instant local confirmation, no network wait |
| Connectivity restored | Service Worker `sync`/`online` event fires | Queued reports POST sequentially to `/reports`; synced items removed from queue; toast per success |
| Stable connection confirmed | Non-intrusive banner offered | User can tap to return to full online `/portal` experience |

---

## 8. State Management Architecture (Shared Pattern, Both Apps)

### 8.1 Division of Responsibility

| Concern | Tool | Examples |
| :--- | :--- | :--- |
| Lightweight global/client state | **Zustand** | `authStore` (Admin user/session), `alertStatusStore`, `mapStore` (camera position), `localeStore`, `simulatorStore` (slider value, selected timestamp) |
| Server state (fetch/cache/poll/sync) | **React Query** | All `GET` polling (risk zones, forecast timeseries, ground-truth feed, alert status), all `POST` mutations (simulate, verify/reject, dispatch, submit report, route request) |
| Persistent offline state | **IndexedDB** (via a thin wrapper, e.g., `idb-keyval` or `Dexie`) | Cached shelter coordinates, cached vector tiles, offline Sync Queue |
| Ephemeral offline cache (network responses, static shell) | **Service Worker Cache API** | Precompiled offline PWA shell HTML/CSS/JS, last-known alert status snapshot |

### 8.2 Data Flow Pattern (applies to every live-updating map layer)

```
Backend (FastAPI/PostGIS/XGBoost/OpenCV)
        │  (REST endpoint, polled or triggered)
        ▼
React Query (cache + polling interval + mutation)
        │  onSuccess → writes derived GeoJSON/state
        ▼
Zustand store (single source of truth for that layer)
        │  subscribed by
        ▼
Map layer component (react-map-gl <Source>/<Layer>)
        │
        ▼
Re-render (Mapbox GL diffs and updates WebGL layer — no full remount)
```

**Rule for the coding agent:** Never let a map layer component call `fetch`/React Query directly and also hold its own local state for the same data — always route through the Zustand store so multiple consumers (map layer + side panels + popups) stay in sync from one source of truth.

### 8.3 Polling Interval Reference

| Data | Interval | App |
| :--- | :--- | :--- |
| Alert status (`GET /alert-status`) | 10s | Admin |
| Alert status (`GET /alert-status`) | 15–20s | Citizen Online |
| Risk zone polygons | 30s | Admin, Citizen Online (read-only) |
| Cloudburst vector | 30s | Admin, Citizen Online |
| Forecast timeseries | 60s (or on-demand when "Live" toggle is on) | Admin |
| Ground-truth feed | 15s or WebSocket if available (poll fallback) | Admin |
| Logistics nodes | 5 min | Admin, Citizen Online |
| Connectivity heartbeat | 10s | Admin |

---

## 9. Cross-Cutting Requirements

### 9.1 Responsiveness
- **Admin**: designed for large tactical displays / tablets (`lg:` and up). Below `lg`, degrade gracefully to a stacked panel view (map on top, panels as swipeable/collapsible drawers) — but Admin is not the primary mobile use case.
- **Citizen Online**: mobile-first (`sm:` base), scales up cleanly to tablet/desktop but every layout decision is made for a one-handed phone in a stressful moment.
- **Citizen Offline**: mobile-first only, assume worst-case low-end device and small viewport; layout must not depend on JS-heavy responsive libraries — plain CSS/Tailwind utility classes only, minimal JS.

### 9.2 Accessibility
- All interactive elements meet WCAG AA contrast, especially critical given the Red/Black/White offline theme (already high-contrast by design).
- Tap targets ≥ 44×44px on Citizen apps (online and offline).
- Map-based information (heatmaps, risk zones) must have a non-visual/text equivalent available (e.g., risk zone popup text, banner text) — never convey status via color alone.
- All icons paired with text labels or `aria-label`s.

### 9.3 Performance
- Admin map layers must use GPU-composited Mapbox layers (`fill-extrusion`, `fill`, `symbol`) — avoid re-mounting the map component on state changes; update data sources in place.
- Image compression (Admin ground-truth feed thumbnails, Citizen crowdfeed submissions) happens **client-side before render/upload** in both apps, using a shared utility.
- Citizen Offline shell bundle size budget: keep the precompiled shell + critical JS minimal (target < 200KB gzipped for the shell itself, excluding the separately-managed ~15MB map tile cache).

### 9.4 Internationalization
- Admin vernacular selector (Hindi/English) drives both UI copy (via an i18n library, e.g., `next-intl` or `react-i18next`) and the language used to generate citizen-facing dispatch templates.
- Citizen-facing apps (online + offline) should also respect a locale setting (can default to device locale) for banner text and form labels, since citizens are the end recipients of dispatches.

### 9.5 Security/Auth Notes (Frontend-Relevant Only)
- `/admin` routes require authenticated session (NDRF operator login) — unauthenticated access redirects to `/admin/login`.
- `/portal` and `/offline` are public, no auth required.
- Any write action from Citizen apps (report submission) should be rate-limited/friction-checked client-side (e.g., disable resubmit button for a few seconds after submit) to reduce spam, though final enforcement is backend's responsibility.

---

## 10. Acceptance Checklist (For the Building Agent)

Before considering the frontend "done," verify:

- [ ] Monorepo scaffolded with `apps/admin`, `apps/portal`, and shared `packages/*` exactly as in Section 2.
- [ ] Design tokens for all three themes (Admin dark tactical, Citizen light trust, Citizen offline brutalist) implemented as CSS variables consumed by shared Tailwind config.
- [ ] Admin: top header, full-screen 3D map, all four dynamic overlay layers, and all tactical panels (Water-Rise Simulator, LSTM Forecast, Ground Truth Feed) implemented with the exact interaction contracts in Section 5.6.
- [ ] Citizen Online: dynamic alert banner (3 states), live map with pulsing user location, PostGIS-backed safe-route navigation (via backend, not raw Mapbox Directions), and bidirectional CrowdFeed with client-side image compression — per Section 6.7.
- [ ] Citizen Offline: brutalist theme with zero animation, instant-loading cached hero banner, IndexedDB-backed KNN nearest-shelter navigation, low-bandwidth submit form writing to a Sync Queue, and a working Service Worker that auto-syncs the queue on reconnect — per Section 7.6.
- [ ] All map layer data flows follow the Backend → React Query → Zustand → Map Component pattern (Section 8.2) — no component-local data silos for shared map state.
- [ ] Polling intervals match Section 8.3.
- [ ] Accessibility, responsiveness, and performance requirements in Section 9 are met, especially the offline shell's zero-network first paint and bundle size budget.
- [ ] No cross-imports between `apps/admin` and `apps/portal`.

---

*End of MeghDrishti Frontend PRD.*
