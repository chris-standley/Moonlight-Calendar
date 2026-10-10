import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// `vite build` -> dist/ for the add-on. `vite build --mode demo` -> one self-contained HTML file for the preview.
export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: [react(), ...(mode === "demo" ? [viteSingleFile()] : [])],
  build: { outDir: mode === "demo" ? "dist-demo" : "dist", assetsInlineLimit: mode === "demo" ? 100_000_000 : 4096 },
  server: { proxy: { "/api": { target: "http://localhost:8099", ws: true } } },
}));
