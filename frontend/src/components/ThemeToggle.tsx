// frontend/src/components/ThemeToggle.tsx
import { useTheme } from '../hooks/useTheme';
import { Sun, Moon } from './Icons';

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      onClick={toggleTheme}
      aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
      className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-[var(--bg-card-hover)] text-[var(--text-secondary)]"
    >
      {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
}
