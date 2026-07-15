import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#0A0A0F",
        surface: "#16161F",
        raised: "#1D1D28",
        hairline: "#2A2A38",
        primary: "#F1F0F5",
        muted: "#9694A6",
        azure: "#5B7FFF",
        violet: "#9C6BFF",
        aqua: "#2DD9C4",
      },
      fontFamily: {
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        body: ["Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      fontWeight: {
        "400": "400",
        "500": "500",
        "600": "600",
        "700": "700",
      },
      keyframes: {
        "glow-rotate": {
          "0%": { "--glow-angle": "0deg" } as any,
          "100%": { "--glow-angle": "360deg" } as any,
        },
        "blob-drift": {
          "0%,100%": { transform: "translate(0,0) scale(1)" },
          "33%": { transform: "translate(3%,-4%) scale(1.06)" },
          "66%": { transform: "translate(-3%,3%) scale(0.97)" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "blob-drift": "blob-drift 18s ease-in-out infinite",
        "fade-in": "fade-in 0.28s ease both",
      },
    },
  },
  plugins: [],
} satisfies Config;
