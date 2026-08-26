import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const resolveBackendOrigin = (mode) => {
  const env = loadEnv(mode, process.cwd(), "");
  const configured = (env.VITE_API_BASE_URL || "http://localhost:5000/api").trim();

  try {
    const url = new URL(configured);
    return url.origin;
  } catch {
    return "http://localhost:5000";
  }
};

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    host: "localhost",
    proxy: {
      "/api": {
        target: resolveBackendOrigin(mode),
        changeOrigin: true,
        secure: false,
      },
      "/outputs": {
        target: resolveBackendOrigin(mode),
        changeOrigin: true,
        secure: false,
      },
    },
  },
}));
