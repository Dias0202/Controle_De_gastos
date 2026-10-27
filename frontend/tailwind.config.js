/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        santander: {
          DEFAULT: '#EC0000',
          dark: '#B80000',
        }
      }
    },
  },
  plugins: [],
}
