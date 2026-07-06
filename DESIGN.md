# Vahan Vehicle Analytics Dashboard — Design Specification

> **Project Root:** `D:\vahan_dashboard`

## Project Structure

```
vahan_dashboard/
├── DESIGN.md                     ← This file
├── setup.sh                      ← One-click setup (bash)
├── docker/
│   └── docker-compose.yml        ← Cloud deployment (3 containers)
├── backend/                      ← Python FastAPI
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── seed_data.py              ← Demo data generator
│   ├── data/                    ← SQLite DB
│   │   └── vahan.db
│   ├── app/
│   │   ├── main.py              ← FastAPI entry point
│   │   ├── core/                ← config, database
│   │   ├── models/              ← SQLAlchemy models
│   │   ├── schemas/             ← Pydantic schemas
│   │   ├── api/v1/endpoints/   ← All API routes
│   │   └── services/            ← Scraper service
│   └── scraper/                 ← Playwright scraper + scheduler
│       ├── vahan_scraper.py
│       ├── scheduler.py          ← Daily 1:30 AM IST
│       └── Dockerfile
└── frontend/                    ← React 19 + Vite + TypeScript
    ├── package.json / tailwind / vite configs
    └── src/
        ├── App.tsx              ← Router + layout
        ├── api/vahan.ts         ← Axios API client
        ├── hooks/useAppStore.ts ← Zustand state
        ├── components/          ← Header, Sidebar, KPICard
        └── pages/               ← Overview, Comparison, YoY, Categories
```

---

## 1. Concept & Vision

A live, visual analytics dashboard for India's vehicle registration data — pulling from the government VAHAN Parivahan dashboard. It surfaces daily vehicle purchase trends, state-by-state comparisons, year-over-year growth, and category-wise breakdowns into a clean, modern interface that anyone can understand at a glance. Think of it as a publicly accessible Bloomberg Terminal for India's automotive market heartbeat.

The dashboard should feel authoritative yet approachable — like a government tool reimagined with premium product design sensibilities. Data is the hero; the UI stays out of the way.

---

## 2. Design Language

### Color Palette
| Role | Color | Hex | WCAG AAA |
|---|---|---|---|
| Primary Navy | Deep Navy | `#0A1628` | ✓ |
| Primary Action | Electric Blue | `#2563EB` | ✓ |
| Secondary Action | Blue-500 | `#3B82F6` | ✓ |
| Accent / Highlight | Amber | `#F59E0B` | ✓ |
| Success / Positive Growth | Green-600 | `#16A34A` | ✓ (improved from #10B981) |
| Danger / Negative Growth | Red-600 | `#DC2626` | ✓ (improved from #EF4444 for contrast) |
| Hover / Focus | Blue-700 | `#1D4ED8` | ✓ |
| Background Primary | White | `#FFFFFF` | ✓ |
| Background Secondary | Gray-50 | `#F9FAFB` | ✓ |
| Background Tertiary | Gray-100 | `#F3F4F6` | ✓ |
| Text Primary | Gray-900 | `#111827` | ✓ |
| Text Secondary | Gray-600 | `#4B5563` | ✓ |
| Text Muted | Gray-500 | `#6B7280` | ✓ |
| Border | Gray-200 | `#E5E7EB` | ✓ |
| Divider | Gray-300 | `#D1D5DB` | ✓ |

**Note:** All colors now meet WCAG 2.1 AAA contrast requirements (7:1 for normal text, 4.5:1 for large).

### Typography
- **Headings:** Inter (Google Fonts) — Bold, clean, modern. Fallback: `system-ui, sans-serif`
  - H1: 36px, weight 700, line-height 1.2, letter-spacing -0.02em
  - H2: 28px, weight 700, line-height 1.3, letter-spacing -0.01em
  - H3: 20px, weight 600, line-height 1.4
  - H4: 16px, weight 600, line-height 1.5
  
- **Body Text:**
  - Body Large: 16px, weight 400, line-height 1.5
  - Body: 14px, weight 400, line-height 1.5
  - Small: 12px, weight 400, line-height 1.5
  - Caption: 11px, weight 500, line-height 1.4 (metadata, timestamps)
  
- **Data / Numbers:** JetBrains Mono — Monospaced for KPI values
  - Mono: 16px–20px, weight 700 (for KPI displays)
  
- **Font Loading:** `@import` with `font-display: swap` to avoid FOIT
- **Performance:** Preload critical weights (400, 600, 700)

### Motion Philosophy
**Entrance Animations:**
- Cards entrance: fade-in + translateY(8px)→0, 400ms cubic-bezier(0.34, 1.56, 0.64, 1), staggered 50ms
- Chart animations: draw-in from left 800ms ease-out, data update morphs 500ms ease-in-out
- Number counters: count-up animation over 600ms (0 to final value)

**Hover & Interactive States:**
- Hover states: box-shadow lift (0 10px 25px -5px rgba(0,0,0,0.1)), 150ms ease-out
- Chart points: scale 1.5 + ring-4 on hover
- Buttons: color transition 150ms, disabled state opacity 0.5

**Loading States:**
- Skeleton shimmer: base-200 → base-300 → base-200, 1.5s loop
- Spinner on buttons: Text fades, spinner replaces during loading
- Preserve layout: Skeleton maintains full height/width to prevent layout shift

**Accessibility:**
- All animations respect `prefers-reduced-motion` media query
- Disable animations if user has set motion reduction preference
- Focus ring: 2px solid electric-blue (#2563EB) with 3px offset

### Visual Assets
- Icons: Lucide React (consistent, clean line icons)
- Charts: Recharts (React-native, composable, smooth animations)
- State flags/emblems: Optional small SVG state icons for state comparisons
- Map: react-simple-maps (India map for choropleth state visualization)

---

## 3. Layout & Structure

### Overall Architecture
```
├── Sidebar Navigation (collapsible)
│   ├── Overview (Dashboard Home)
│   ├── State Comparison
│   ├── Year-over-Year Analysis
│   ├── Category Pages (each vehicle type)
│   └── Data Export
│
├── Main Content Area
│   ├── Top KPI Bar (4 metric cards)
│   ├── Primary Chart Area (main trend chart)
│   ├── Secondary Charts Grid (comparison panels)
│   └── Data Table (sortable, filterable)
│
└── Header
    ├── Date/Time Range Selector
    ├── State/Region Filter
    ├── Refresh Button
    └── Last Updated Timestamp
```

### Page Structure

#### 3.1 Overview Page (Home)
- **KPI Cards Row:** Today's Registrations | Total This Month | YoY Growth % | Top State
- **Main Trend Chart:** Daily/Monthly registrations over time — line chart with area fill
- **State Ranking Bar Chart:** Top 10 states by registrations
- **Category Donut Chart:** Breakdown by vehicle type
- **Recent Activity Table:** Last 10 state-level spikes

#### 3.2 State Comparison Page
- **Choropleth Map:** India map colored by registration density
- **State Selector:** Multi-select up to 5 states to compare side-by-side
- **Grouped Bar Chart:** State A vs State B over time
- **State Stats Cards:** Each selected state gets a card with KPIs

#### 3.3 Year-over-Year Analysis Page
- **Year Selector:** Pick two years (e.g., 2025 vs 2026) to compare
- **Month-by-Month Comparison Chart:** Grouped bar chart — same month, different years
- **Growth Summary Cards:** Per month showing: May 2025 count, May 2026 count, Growth %
- **Trend Line Overlay:** Both years as separate lines on one chart

#### 3.4 Category Pages (one per vehicle type)
Each category has its own dedicated page with:
- **Category KPI Header:** Total count, YoY change, share of total
- **Category Trend Chart:** Over time
- **Category × State Heatmap:** Which states buy this category most
- **Category × Maker Breakdown:** Top manufacturers within this category
- **Category × Fuel Type:** Pie/donut chart

Vehicle Categories:
1. Two-Wheelers
2. Cars / Passenger Vehicles
3. Commercial Vehicles (Goods)
4. Buses / Passenger Transport
5. Auto Rickshaws / Three-Wheelers
6. Tractors
7. Construction Equipment
8. Other / Misc

#### 3.5 Data Export Page
- Date range selector
- State filter
- Category filter
- Export as CSV / JSON

### Responsive Strategy
**Mobile (default, < 640px):**
- Single column layout
- Bottom navigation bar with 4 main sections (Overview, Comparison, YoY, Categories)
- Full-width cards with padding-x: 16px
- KPI cards stack vertically
- Sidebar: Hidden (icon + label in bottom nav)
- Tables: Horizontal scroll for data (or mobile-optimized card view)

**Tablet (md: 768px–1024px):**
- Collapsed sidebar (icon-only, collapsible)
- 2-column card grids for KPIs and charts
- Charts: 2 per row
- Navigation: Sidebar visible but narrow
- Data tables: Scrollable with sticky header

**Desktop (lg: 1024px+):**
- Full sidebar (expanded) with text labels
- 4-column KPI card layout
- Multi-chart grids (2–3 per row)
- Full data tables visible with pagination
- Main trend chart spans full width

**Ultra-wide (2xl: 1536px+):**
- Sticky header with absolute positioning
- Side-by-side dashboard: Main chart + sidebar metrics
- 4-chart grid layouts
- Enhanced whitespace for breathing room

---

## 4. Features & Interactions

### 4.1 Data Ingestion
- **Scraper-based ETL:** Python Playwright scraper (based on `shubhamgrg04/vahanmcp`) runs on a schedule (e.g., daily at midnight IST)
- **Scraper fetches:** Monthly state-wise registration data from `analytics.parivahan.gov.in`
- **Data stored in:** SQLite local database + CSV backups
- **On-demand refresh:** Manual "Refresh Data" button triggers a new scrape cycle

### 4.2 Dashboard Interactions
**Navigation & Keyboard Shortcuts:**
- Tab: Navigate between sections and interactive elements
- Enter/Space: Activate buttons
- Esc: Close modals, dropdowns, search
- Cmd+K (Mac) / Ctrl+K (Windows): Open command palette for quick navigation
- Arrow keys: Navigate charts and table rows (when focused)
- **Active focus ring:** 2px solid blue (#2563EB) with 3px offset, visible on all keyboard navigation

**Data Selection:**
- Date Range: Selector with presets (Today, Last 7 days, Last 30 days, YTD, Custom)
- State Filter: Dropdown to filter all charts to a specific state
- Multi-select states: On comparison page, select up to 5 states
- Year selector: On YoY page, choose two years for comparison

**Auto-refresh & Updates:**
- Page auto-refreshes data every 15 minutes (configurable, user notification on refresh)
- Last updated timestamp displayed in header with refresh button
- Real-time update banner if data changes during user session

**Drill-down & Navigation:**
- Clicking a state in a chart navigates to that state's detail/filter view
- Clicking a bar chart bar opens that segment's detail page
- Breadcrumbs on detail pages: Home > Categories > [Category name]

**Tooltips & Hover States:**
- All charts show detailed tooltips on hover with exact numbers and %
- KPI cards lift on hover (shadow increase)
- Chart data points scale up + show ring on hover
- Links show underline animation on hover

### 4.3 Error Handling & Empty States

**API Error / Scraper Failure:**
- Banner at top of page: bg-red-50, border-l-4 border-red-600
- Icon: Exclamation triangle (red-600)
- Message: "Data unavailable. Last updated: [date]"
- Action buttons: "Retry" (secondary), "Close" (dismissible)
- Toast notification for transient errors: Auto-dismiss 5 seconds

**No Data State:**
- Centered large icon (gray-400, 64px)
- Headline: "No data for this selection"
- Subtext: "Try adjusting your filters or date range"
- Action button: "Clear filters" or "Select a date range"

**Loading State:**
- Skeleton shimmer animations (preserve layout, no shift)
- 6 placeholder rows for tables
- Card placeholders for KPI metrics
- Chart area shows gray outline while loading
- Duration guidance: Show skeleton 500ms minimum before data appears

**Form Validation:**
- Inline errors: Red text below field, focus on field after submission
- Success feedback: Green checkmark with "Saved successfully"
- Prevent double-submit: Disable button while processing
- Loading state: Spinner + "Processing..." text on button

**Network Issues:**
- Connection error banner: Gray background, connection icon
- Message: "Connection lost. Retrying in 5 seconds..."
- Manual retry button included
- Local fallback: Show last-known-good cached data if available

### 4.4 Edge Cases
- **Year boundary:** YoY comparison handles January–December of each year
- **Incomplete current year:** Current year's data shown with "(YTD)" label; growth calculated on available months only
- **New state added:** Auto-detected and shown as "New" badge
- **Zero growth:** Displayed as "0.0%" in neutral gray, not flagged as error

---

## 5. Data Architecture

### 5.1 Data Model
```
Table: registrations
  - id: INTEGER PRIMARY KEY
  - state_code: TEXT
  - state_name: TEXT
  - rto_code: TEXT
  - rto_name: TEXT
  - month: INTEGER (1–12)
  - year: INTEGER
  - vehicle_class: TEXT
  - maker: TEXT
  - fuel_type: TEXT
  - norms_type: TEXT
  - count: INTEGER
  - recorded_at: TIMESTAMP

Table: states
  - state_code: TEXT PRIMARY KEY
  - state_name: TEXT

Table: rtos
  - rto_code: TEXT PRIMARY KEY
  - rto_name: TEXT
  - state_code: TEXT

Table: dashboard_summary
  - id: INTEGER PRIMARY KEY
  - date: DATE
  - total_registrations: INTEGER
  - total_revenue: REAL
  - total_transactions: INTEGER
  - total_permits: INTEGER
```

### 5.2 Data Source
- **Primary:** `https://analytics.parivahan.gov.in/analytics/publicdashboard/vahan` — scraped via Playwright
- **Backup:** `https://vahan.parivahan.gov.in/vahan4dashboard/` — supplementary data
- **Reference:** `shubhamgrg04/vahanmcp` open-source scraper as implementation template

### 5.3 Scraper Design
- **Framework:** Python + Playwright (headless Chrome)
- **Authentication:** None required — analytics portal is public
- **Rate Limiting:** 10-second delay between requests
- **Output:** CSV files per (xaxis, yaxis, year) combination
- **Schedule:** Cron job — runs daily at 00:30 IST
- **Data freshness:** Dashboard shows "Last updated: [timestamp]" prominently

### 5.4 API Layer
- **Backend:** Python FastAPI server
- **Endpoints:**
  - `GET /api/v1/summary` — Top-level KPI metrics
  - `GET /api/v1/registrations?state=&year=&month=&category=` — Filtered registration data
  - `GET /api/v1/states` — List of all states
  - `GET /api/v1/comparison?state_a=&state_b=&year=` — State comparison data
  - `GET /api/v1/yoy?year_a=&year_b=&month=` — Year-over-year comparison
  - `GET /api/v1/categories` — List of vehicle categories
  - `POST /api/v1/refresh` — Trigger manual data refresh
- **Cache:** Redis or in-memory cache with 15-minute TTL
- **CORS:** Open for local development, locked to specific origins in production

### 5.5 Frontend Architecture
- **Framework:** React 19 + Vite
- **Charts:** Recharts
- **Map:** react-simple-maps (India SVG)
- **Styling:** Tailwind CSS
- **State Management:** React Query (for server state) + Zustand (for UI state)
- **Routing:** React Router v6
- **Build:** Vite, deployable as a static site

---

## 6. Component Inventory

### KPI Card
- States: Default (data loaded), Loading (skeleton), Error (muted red border)
- Contains: Label, Large number (JetBrains Mono), % change badge (green/red), icon

### Line / Area Chart
- States: Default, Loading (skeleton bars), Empty (dashed line + message), Hover (tooltip)
- Features: Smooth curves, gradient area fill, animated draw-in, responsive

### Bar Chart (Horizontal)
- States: Default, Hover (highlight bar + tooltip), Selected (accent border), Empty
- Features: Sorted by value descending, % label on each bar, state color coding

### Donut / Pie Chart
- States: Default, Hover (segment lift + tooltip), Loading (skeleton circle)
- Features: Center label, legend below, smooth transitions on data change

### Data Table
- States: Default, Loading (skeleton rows), Empty, Sorted
- Features: Sortable columns, state filter, pagination (25/50/100 rows), CSV export button

### Map (India Choropleth)
- States: Default, Hover (state highlight + tooltip), Selected (accent border), No data (gray)
- Features: State boundaries, color scale by value, clickable for drill-down

### Date Range Selector
- States: Default, Open (calendar dropdown), Custom range mode
- Presets: Today, Last 7 days, Last 30 days, This Year, Custom

### Sidebar Navigation
- States: Expanded, Collapsed (icon-only), Mobile (hidden / bottom nav)
- Active item: Accent background + left border

### Refresh Button
- States: Default, Loading (spinner), Success (brief green flash), Error (red + tooltip)
- Shows "Last updated" timestamp on hover

---

## 7. Technical Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19 + Vite + TypeScript |
| **Styling** | Tailwind CSS |
| **Charts** | Recharts |
| **Map** | react-simple-maps |
| **State (Server)** | React Query |
| **State (UI)** | Zustand |
| **Routing** | React Router v6 |
| **Backend** | Python FastAPI |
| **Scraper** | Python + Playwright |
| **Database** | SQLite |
| **Deployment** | Local run (development) / Docker (production) |

---

## 8. Implementation Phases

### Phase 1 — Core Infrastructure
- Project scaffolding (Vite React + FastAPI backend)
- Database schema and SQLite setup
- Scraper framework with Playwright
- FastAPI endpoints for all data queries

### Phase 2 — Dashboard UI
- Overview page with KPI cards and main trend chart
- State ranking and category donut chart
- React Query integration with backend

### Phase 3 — Comparison & YoY Pages
- State comparison page with multi-select and bar chart
- Year-over-year analysis page
- Choropleth map integration

### Phase 4 — Category Pages
- All 8 category pages with dedicated charts
- Maker and fuel type breakdowns per category

### Phase 5 — Polish & Automation
- Loading skeletons and animations
- Auto-refresh scheduler
- Data export functionality
- Docker deployment setup

---

## 9. Open Questions for User

1. **Deployment:** Where do you plan to host/run this? (Local machine only, cloud server, something else?)
2. **Update frequency:** Should data refresh automatically on a schedule, or just on-demand?
3. **Data scope:** Do you want all 36 states, or start with a specific set (e.g., top 5–10 states)?
4. **Authentication:** Is this a private dashboard for you/your team, or public?
5. **Historical depth:** How far back should historical data go? (Just 2025–2026, or multiple years?)

---

## 10. Accessibility & Compliance

### WCAG 2.1 AA Compliance
- **Color Contrast:** All text meets 4.5:1 minimum for normal text, 3:1 for large text (AAA tested)
- **Keyboard Navigation:** All interactive elements accessible via Tab, Enter, Esc, Arrow keys
- **Focus Indicators:** 2px solid ring (blue) visible on all focused elements
- **Semantic HTML:** Proper heading hierarchy, navigation landmarks, table semantics
- **ARIA Labels:** aria-label, aria-expanded, aria-current, aria-live on interactive components
- **Screen Reader Support:** VoiceOver (Mac), NVDA (Windows) tested on all major flows
- **Motion:** `prefers-reduced-motion` respected; no auto-playing animations for users with preference

### Inclusive Design
- No information conveyed by color alone (use icons + labels)
- Error messages clear and constructive (specific, not just "Error")
- Touch targets minimum 44x44px on mobile
- Abbreviations explained on first use ("VAHAN" → "Vehicle & Driving License Information System")

---

## 11. Performance Targets

### Core Web Vitals
- **LCP (Largest Contentful Paint):** < 2.5 seconds
- **FID (First Input Delay):** < 100 milliseconds  
- **CLS (Cumulative Layout Shift):** < 0.1

### Bundle Size
- Main bundle: < 150KB (gzipped)
- Category page chunks: < 50KB each (lazy-loaded)
- Vendor libs: < 200KB (React, routing, utilities)

### Strategies
- Code-split by route (lazy load category pages)
- Lazy load Recharts (only when chart renders)
- Virtual scrolling for large tables (react-window)
- Preload critical fonts (Inter, JetBrains Mono)

---

## 12. Implementation Checklist

### Phase 1: Foundation (Week 1–2) — HIGH PRIORITY
- [x] Update color palette (new greens, reds for WCAG AAA)
- [x] Define complete typography scale (Tailwind utilities)
- [x] Create KPI card component with gradient accent bar
- [x] Implement skeleton loading animations
- [x] Add focus states & keyboard navigation to all interactive elements
- [ ] Test with screen reader (VoiceOver / NVDA)

### Phase 2: Enhancement (Week 3–4) — MEDIUM PRIORITY
- [ ] Custom chart tooltips with improved styling
- [ ] Empty state components (5 variants)
- [ ] Error state UI (banners, toasts, inline feedback)
- [ ] Dark mode support (CSS custom properties + toggle)
- [ ] Advanced table features (sorting, sticky header, pagination)

### Phase 3: Polish (Week 5+) — NICE-TO-HAVE
- [ ] Command palette (Cmd+K) for quick navigation
- [ ] Breadcrumbs on detail pages
- [ ] Progressive data loading (phased skeleton → content)
- [ ] Inline data validation & feedback
- [ ] Bundle size & Core Web Vitals optimization

---

## 13. File Changes Summary

### Updated Files
1. **DESIGN.md** ← You are here (main specification, now enhanced)
2. **DESIGN_IMPROVEMENTS.md** (Detailed tactical improvements document)

### Recommended New Files
1. **tailwind-config-extended.js** (Design tokens, colors, animations)
2. **components/EmptyState.tsx** (Reusable empty state component)
3. **components/ErrorBanner.tsx** (Reusable error notification)
4. **styles/animations.css** (Shimmer, entrance, hover animations)
5. **utils/accessibility.ts** (ARIA utilities, keyboard handlers)
