import { defineConfig } from "vite";
export default defineConfig({
  base: "/studio/",
  build: {
    outDir: "../web/studio",
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/assets": "http://127.0.0.1:8080",
      "/media": "http://127.0.0.1:8080",
    },
  },
});
