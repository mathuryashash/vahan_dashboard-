export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: '#0A1628', light: '#1E293B' },
        blue: { DEFAULT: '#2563EB', light: '#3B82F6' },
        amber: { DEFAULT: '#F59E0B' },
        emerald: { DEFAULT: '#10B981' },
        rose: { DEFAULT: '#EF4444' },
        slate: { 50: '#F8FAFC', 100: '#F1F5F9', 200: '#E2E8F0', 400: '#94A3B8', 600: '#475569', 800: '#1E293B', 900: '#0F172A' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}