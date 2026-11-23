// Builds the Statement Analyser as a library: npm run build:module  ->  dist-module/statement-analyser.js
// React, MUI and emotion are NOT bundled; the host app provides them (one copy of React is required).
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const external = [/^react($|\/)/, /^react-dom($|\/)/, /^@mui\//, /^@emotion\//];

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist-module",
    emptyOutDir: true,
    lib: { entry: "src/module.jsx", formats: ["es"], fileName: () => "statement-analyser.js" },
    rollupOptions: { external },
  },
});
