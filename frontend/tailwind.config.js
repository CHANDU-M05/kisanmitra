/** @type {import('tailwindcss').Config} */
import colors from 'tailwindcss/colors';

export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Redefining 'slate' to be a high-contrast pure light / pitch dark scale
        slate: {
          50: '#ffffff',     // Pure white for light mode backgrounds
          100: '#f4f4f5',    // Very light grey for secondary bg
          200: '#e4e4e7',    // Light borders
          300: '#d4d4d8',
          400: '#a1a1aa',
          500: '#71717a',
          600: '#52525b',
          700: '#27272a',
          800: '#18181b',    // Very dark grey for cards in dark mode
          900: '#09090b',    // Near black
          950: '#000000',    // Pitch black for dark mode backgrounds
        },
        // Redefining 'emerald' to a punchy, vibrant "modern tech" green
        emerald: {
          50: '#ecfdf5',
          100: '#d1fae5',
          200: '#a7f3d0',
          300: '#6ee7b7',
          400: '#34d399',
          500: '#00e676',    // Vibrant spring green (material style)
          600: '#00c853',    // Darker vibrant green
          700: '#047857',
          800: '#065f46',
          900: '#064e3b',
          950: '#022c22',
        }
      }
    },
  },
  plugins: [],
}
