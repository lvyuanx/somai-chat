import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  base: "/admin-assets/",
  build: {
    outDir: "../../src/somai_chat/admin_web/dist",
    emptyOutDir: true,
  },
});
