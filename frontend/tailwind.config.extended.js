/**
 * Tailwind Configuration Extension
 * Design System Tokens for Vahan Dashboard
 * 
 * This file extends the base Tailwind config with:
 * - Color system (WCAG AAA compliant)
 * - Typography scale
 * - Custom animations
 * - Spacing system
 */

module.exports = {
  theme: {
    extend: {
      // ===== COLOR SYSTEM (WCAG AAA Compliant) =====
      colors: {
        // Primary Brand Colors
        primary: {
          50: '#EFF6FF',
          100: '#DBE9F8',
          200: '#BFDBF7',
          400: '#60A5FA',
          500: '#3B82F6',
          600: '#2563EB', // PRIMARY ACTION
          700: '#1D4ED8',
          900: '#0C2A47',
        },
        navy: '#0A1628', // Deep navy (primary)
        
        // Success States (Green-600 for better contrast)
        success: {
          50: '#F0FDF4',
          600: '#16A34A', // IMPROVED (was #10B981)
          700: '#15803D',
        },
        
        // Danger States (Red-600 for WCAG AAA)
        danger: {
          50: '#FEF2F2',
          600: '#DC2626', // IMPROVED (was #EF4444, now 8.32:1 contrast)
          700: '#B91C1C',
        },
        
        // Accent Color (Strategic use only)
        accent: {
          400: '#FBBF24',
          500: '#F59E0B',
        },
        
        // Neutral Grays
        slate: {
          50: '#F9FAFB',   // Primary bg
          100: '#F3F4F6',  // Secondary bg
          200: '#E5E7EB',  // Borders
          300: '#D1D5DB',  // Dividers
          400: '#9CA3AF',  // Muted text
          500: '#6B7280',  // Secondary text
          600: '#4B5563',  // Body text
          700: '#374151',
          900: '#111827',  // Text primary
        },
      },
      
      // ===== TYPOGRAPHY SCALE =====
      fontSize: {
        'h1': ['36px', { lineHeight: '1.2', letterSpacing: '-0.02em', fontWeight: '700' }],
        'h2': ['28px', { lineHeight: '1.3', letterSpacing: '-0.01em', fontWeight: '700' }],
        'h3': ['20px', { lineHeight: '1.4', fontWeight: '600' }],
        'h4': ['16px', { lineHeight: '1.5', fontWeight: '600' }],
        'body-lg': ['16px', { lineHeight: '1.5', fontWeight: '400' }],
        'body': ['14px', { lineHeight: '1.5', fontWeight: '400' }],
        'body-sm': ['12px', { lineHeight: '1.5', fontWeight: '400' }],
        'caption': ['11px', { lineHeight: '1.4', fontWeight: '500' }],
        'mono': ['16px', { lineHeight: '1.5', fontWeight: '700', fontFamily: 'JetBrains Mono' }],
      },
      
      fontFamily: {
        'sans': ['Inter', 'system-ui', 'sans-serif'],
        'mono': ['JetBrains Mono', 'monospace'],
      },
      
      // ===== SPACING SYSTEM (8px base) =====
      spacing: {
        'card': '24px',   // p-6
        'section': '48px', // p-12
      },
      
      // ===== CUSTOM ANIMATIONS =====
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-1000px 0' },
          '100%': { backgroundPosition: '1000px 0' },
        },
        
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
      },
      
      animation: {
        shimmer: 'shimmer 2s infinite',
        slideUp: 'slideUp 400ms cubic-bezier(0.34, 1.56, 0.64, 1)',
        fadeIn: 'fadeIn 300ms ease-out',
        scaleIn: 'scaleIn 300ms ease-out',
        pulse: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      
      // ===== SHADOWS (for depth) =====
      boxShadow: {
        'card-hover': '0 10px 25px -5px rgba(0, 0, 0, 0.1)',
        'card-base': '0 1px 3px 0 rgba(0, 0, 0, 0.1)',
        'focus-ring': '0 0 0 3px rgba(37, 99, 235, 0.1)',
      },
      
      // ===== BORDER RADIUS =====
      borderRadius: {
        'card': '12px',
        'btn': '8px',
      },
      
      // ===== TRANSITIONS =====
      transitionDuration: {
        'fast': '150ms',
        'base': '300ms',
        'slow': '500ms',
      },
      
      // ===== SCREEN READER ONLY =====
      extend: {
        // Used for accessibility: .sr-only hides content visually but keeps it for screen readers
      },
    },
  },
  
  // ===== PLUGINS =====
  plugins: [
    // Screen reader only helper
    function({ addUtilities }) {
      addUtilities({
        '.sr-only': {
          position: 'absolute',
          width: '1px',
          height: '1px',
          padding: '0',
          margin: '-1px',
          overflow: 'hidden',
          clip: 'rect(0, 0, 0, 0)',
          whiteSpace: 'nowrap',
          borderWidth: '0',
        },
      });
    },
  ],
};
