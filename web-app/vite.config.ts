import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// O build sai em `../web/compor/`, que é a pasta que o FastAPI já serve por
// `StaticFiles`. `base` relativo porque a página é servida em `/compor/` e não
// na raiz — caminho absoluto quebraria os assets.
//
// `proxy` no dev: `npm run dev` fala com o uvicorn em 8111, então dá para
// desenvolver a tela sem rebuildar a cada mudança.
// O build sai em `../web/`, que é a pasta servida por `StaticFiles` na RAIZ.
// Antes saía em `../web/compor/`, ao lado de duas páginas estáticas que faziam
// o resto da tela — e foi essa convivência que produziu o defeito do modo
// escuro: o default foi implementado no app e nunca nas páginas ao lado.
// Agora o build É a tela, e `emptyOutDir` só pode apagar o próprio build.
//
// `base: "./"` continua relativo e continua certo: servido na raiz, `./assets/`
// resolve para `/assets/`.
//
// `proxy` no dev: `npm run dev` fala com o uvicorn em 8111, então dá para
// desenvolver a tela sem rebuildar a cada mudança.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "../web", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8111" },
  },
});
