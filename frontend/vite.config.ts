import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "^/$": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/new": "http://127.0.0.1:8000",
      "/job": "http://127.0.0.1:8000",
      "/song": "http://127.0.0.1:8000",
    },
  },
});
