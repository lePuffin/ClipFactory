/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#101313",
        panel: "#171c1c",
        line: "#2b3433",
        paper: "#e7ece8",
        muted: "#9aa6a0",
        acid: "#c7f36b",
        coral: "#f48d73",
      },
      fontFamily: {
        display: ["'Space Grotesk'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};