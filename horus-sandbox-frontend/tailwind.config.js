/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Manrope", "system-ui", "sans-serif"],
        serif: ["'Source Serif 4'", "Georgia", "serif"],
      },
      colors: {
        navy: {
          950: "#12122a",
          900: "#16162f",
          800: "#1c1c3a",
          700: "#26264c",
        },
        gold: {
          DEFAULT: "#d7a544",
          soft: "#f1dcae",
        },
        violet: {
          DEFAULT: "#6a5acd",
          deep: "#4b3f9e",
          soft: "#ece9fb",
        },
        ink: {
          DEFAULT: "#181828",
          muted: "#5c5c72",
          faint: "#8b8ba0",
        },
        paper: "#f6f5fb",
        line: "#e7e6f0",
        status: {
          green: "#1f9d6f",
          greenSoft: "#e4f7ee",
          red: "#d5504a",
          redSoft: "#fbe9e8",
          blue: "#3b6fd6",
          blueSoft: "#e8eefb",
        },
      },
      borderRadius: {
        card: "14px",
      },
    },
  },
  plugins: [],
};
