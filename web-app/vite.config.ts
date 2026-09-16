import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// O build sai em `../web/compor/`, que é a pasta que o FastAPI já serve por
// `StaticFiles`. `base` relativo porque a página é servida em `/compor/` e não
// na raiz — caminho absoluto quebraria os assets.
//
// `proxy` no dev: `npm run dev` fala com o uvicorn em 8111, então dá para
// desenvolver a tela sem rebuildar a cada mudança.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "../web/compor", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8111" },
  },
});
