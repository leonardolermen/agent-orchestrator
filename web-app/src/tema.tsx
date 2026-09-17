/** O tema, num lugar só.
 *
 * **Por que este módulo existe.** O escuro por default foi implementado uma
 * vez, dentro do app React, e as duas páginas estáticas que existiam ao lado
 * dele nunca souberam disso — a tela que o README mandava abrir primeiro abria
 * clara. O conserto de verdade não foi copiar o CSS para a terceira página: foi
 * deixar de ter três páginas. Este arquivo é onde a decisão passa a morar, e a
 * única coisa que a aplica é o script inline do `index.html`.
 *
 * **O que NÃO está aqui, e é deliberado.** A aplicação INICIAL da classe. Ela
 * mora num `<script>` inline no `<head>`, porque um módulo é adiado por
 * especificação: ele roda depois de o CSS já ter pintado, e o default escuro
 * viraria um flash claro em toda visita. Um default que aparece tarde não é um
 * default — é um conserto, e o usuário vê o conserto acontecendo.
 *
 * Duplicar a regra "ausência cai no escuro" entre o script inline e este
 * módulo seria a mesma armadilha de outra forma, então aqui ela não é
 * reimplementada: `usarTema` LÊ a classe que o inline já pôs.
 */

import { useState } from "react";

/** O estado do tema e o alternador. Lê a classe que o script inline aplicou. */
export function usarTema(): [boolean, () => void] {
  const [escuro, setEscuro] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );
  const alternar = () => {
    const novo = !escuro;
    setEscuro(novo);
    document.documentElement.classList.toggle("dark", novo);
    // `localStorage` pode levantar (janela privada, site data bloqueado). A
    // preferência é conveniência por visitante — perdê-la volta ao default
    // escuro, que é o comportamento certo.
    try {
      localStorage.setItem("tema", novo ? "dark" : "light");
    } catch {
      /* sem problema: o default volta a valer */
    }
  };
  return [escuro, alternar];
}

/** O botão de alternar, para as duas vistas usarem o MESMO.
 *
 * Um botão por vista seria duas cópias de um controle que precisa parecer e
 * agir igual nas duas — e foi exatamente esse tipo de cópia que produziu o
 * defeito que este módulo existe para fechar.
 */
export function BotaoDeTema({
  escuro,
  alternar,
}: {
  escuro: boolean;
  alternar: () => void;
}) {
  return (
    <button
      type="button"
      onClick={alternar}
      title={escuro ? "mudar para claro" : "mudar para escuro"}
      className="rounded border border-borda px-2 py-1 text-[12px] text-neutral-500 transition hover:bg-neutral-50 dark:border-noite-borda dark:text-noite-fraca dark:hover:bg-noite-cartao"
    >
      {escuro ? "☀" : "☾"}
    </button>
  );
}
