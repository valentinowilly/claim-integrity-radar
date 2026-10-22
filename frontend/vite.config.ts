import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  const backendTarget = env.VITE_BACKEND_URL ?? "http://127.0.0.1:8000";
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: "127.0.0.1",
      proxy: {
        "/health": backendTarget,
        "/api": backendTarget,
      },
    },
  };
});
