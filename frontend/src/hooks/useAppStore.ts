import { create } from 'zustand';

interface AppState {
  selectedYear: number;
  selectedMonth: number | null;
  selectedState: string | null;
  selectedCategory: string | null;
  fuelGroup: string | null;
  selectedMaker: string | null;
  comparisonYearA: number;
  comparisonYearB: number;
  /** YoY page's own State / Category (kept here so sidebar navigation, whose
   * links are bare /yoy, comes back to them; the URL wins when it has them). */
  yoyState: string | null;
  yoyCategory: string | null;
  setYoyFilters: (state: string | null, category: string | null) => void;
  sidebarCollapsed: boolean;
  /** Below the md breakpoint the sidebar is an off-canvas drawer. */
  mobileNavOpen: boolean;
  setMobileNavOpen: (open: boolean) => void;
  setSelectedYear: (year: number) => void;
  setSelectedMonth: (month: number | null) => void;
  setSelectedState: (state: string | null) => void;
  setSelectedCategory: (cat: string | null) => void;
  setFuelGroup: (group: string | null) => void;
  setSelectedMaker: (maker: string | null) => void;
  setComparisonYears: (a: number, b: number) => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedYear: new Date().getFullYear(),
  selectedMonth: null,
  selectedState: null,
  selectedCategory: null,
  fuelGroup: null,
  selectedMaker: null,
  comparisonYearA: new Date().getFullYear() - 1,
  comparisonYearB: new Date().getFullYear(),
  yoyState: null,
  yoyCategory: null,
  setYoyFilters: (yoyState, yoyCategory) => set({ yoyState, yoyCategory }),
  sidebarCollapsed: false,
  mobileNavOpen: false,
  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
  setSelectedYear: (year) => set({ selectedYear: year }),
  setSelectedMonth: (month) => set({ selectedMonth: month }),
  setSelectedState: (state) => set({ selectedState: state }),
  setSelectedCategory: (cat) => set({ selectedCategory: cat }),
  setFuelGroup: (group) => set({ fuelGroup: group }),
  setSelectedMaker: (maker) => set({ selectedMaker: maker }),
  setComparisonYears: (a, b) => set({ comparisonYearA: a, comparisonYearB: b }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}))