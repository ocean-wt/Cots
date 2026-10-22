/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'Inter', 'SF Pro Display', '-apple-system', 'PingFang SC',
          'Microsoft YaHei', 'system-ui', 'sans-serif',
        ],
        mono: ['JetBrains Mono', 'SF Mono', 'Menlo', 'monospace'],
      },
      colors: {
        brand: {
          50: '#eef4ff', 100: '#d9e6ff', 200: '#bcd3ff', 300: '#8eb6ff',
          400: '#598dff', 500: '#3366ff', 600: '#1f47f5', 700: '#1735e1',
          800: '#192db6', 900: '#1a2c8f',
        },
      },
      boxShadow: {
        glass: '0 8px 32px rgba(2, 6, 23, 0.35)',
        glow: '0 0 24px rgba(51, 102, 255, 0.35)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-400px 0' },
          '100%': { backgroundPosition: '400px 0' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.45' },
        },
        dash: {
          to: { strokeDashoffset: '-20' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.6s linear infinite',
        pulseSoft: 'pulseSoft 1.8s ease-in-out infinite',
        dash: 'dash 1s linear infinite',
      },
    },
  },
  plugins: [],
}
