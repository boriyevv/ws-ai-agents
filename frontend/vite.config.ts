import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev`  -> http://localhost:5173 (API so'rovlari Python serverga, 8080 portga yo'naltiriladi)
// `npm run build` -> ../web papkaga tayyor fayllar (Python server ularni o'zi ko'rsatadi)
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../web", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/login": "http://127.0.0.1:8080",
    },
  },
});
