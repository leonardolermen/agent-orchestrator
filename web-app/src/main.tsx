import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Execucao } from "./Execucao";
import { Fila } from "./Fila";
import "./index.css";

// TRÊS vistas, UMA aplicação — e sem `react-router`.
//
//   execucao  um workflow SALVO, com os números medidos   (era `index.html`)
//   fila      a revisão humana que fecha a cascata        (era `fila.html`)
//   compor    o canvas de AUTORIA                         (era `/compor/`)
//
// A escolha de não usar roteador não é economia de dependência, embora seja
// isso também. Enquanto eram três PÁGINAS, elas precisavam concordar sobre qual
// dataset estavam olhando, e a coordenação dependia de todas lerem a mesma
// query string com os mesmos defaults. O `DECISOES.md` registra, no P4.14, que
// essa promessa já quebrou — nada além de lembrança humana mantinha as listas
// de defaults iguais. Com uma aplicação, não há com quem discordar.
//
// `?vista=` basta para o que existe: três vistas, sem rotas aninhadas e sem
// histórico próprio.
//
// A regra abaixo PRESERVA o significado que `/` sempre teve.
//
// `/` era o canvas de execução — um workflow salvo, com os números medidos — e
// a CLI do grill entrega `→ /?workflow=<id>` como último passo da entrevista.
// Se `compor` virasse o default, esse link abriria a tela errada em silêncio.
// Então: o default é EXECUÇÃO, e compor é uma vista nomeada.
const q = new URLSearchParams(location.search);
const vista = q.get("vista") ?? "execucao";

// O TEMA não é aplicado aqui, e é deliberado: ele já foi, pelo script inline do
// `index.html`, antes da primeira pintura. Este módulo é adiado por
// especificação — aplicar a classe daqui faria toda visita começar clara e
// escurecer depois, que é um conserto visível, não um default. Ver `tema.tsx`.

function vistaAtual() {
  if (vista === "fila") return <Fila />;
  if (vista === "compor") return <App />;
  return <Execucao />;
}

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>{vistaAtual()}</StrictMode>,
);
