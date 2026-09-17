import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// ESCURO por default, e a decisão é do produto.
//
// `localStorage` pode levantar (janela privada, cookies bloqueados) e pode
// voltar vazio — por isso a leitura é protegida e a AUSÊNCIA cai no escuro, não
// no claro. Um default que depende de `prefers-color-scheme` faria a tela
// abrir clara em metade das máquinas, que é o oposto do que foi pedido.
function temaInicial(): "dark" | "light" {
  try {
    return localStorage.getItem("tema") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

if (temaInicial() === "dark") document.documentElement.classList.add("dark");

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
