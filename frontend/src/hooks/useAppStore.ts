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
  sidebarCollapsed: boolean;
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
  sidebarCollapsed: false,
  setSelectedYear: (year) => set({ selectedYear: year }),
  setSelectedMonth: (month) => set({ selectedMonth: month }),
  setSelectedState: (state) => set({ selectedState: state }),
  setSelectedCategory: (cat) => set({ selectedCategory: cat }),
  setFuelGroup: (group) => set({ fuelGroup: group }),
  setSelectedMaker: (maker) => set({ selectedMaker: maker }),
  setComparisonYears: (a, b) => set({ comparisonYearA: a, comparisonYearB: b }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}))