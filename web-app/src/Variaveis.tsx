import { useEffect, useState } from "react";
import { api, type ErroDaApi, type Variavel } from "./api";

/**
 * As variaveis que um cliente configura para o workflow alcancar os sistemas
 * dele — o `token_env` de uma API, o `dsn_env` de um Postgres.
 *
 * **O valor entra e nunca mais sai.** Nenhuma rota o devolve, nem mascarado: um
 * valor mascarado ainda vaza o COMPRIMENTO, e o comprimento de um token
 * identifica o provedor. Depois de definida, a variavel aparece como "definida"
 * e o campo volta a ficar vazio — se a pessoa precisar trocar, ela digita de
 * novo. Nao ha "editar", porque nao ha o que carregar para editar.
 *
 * **So nomes com prefixo `WF_`.** A cerca e do servidor e a recusa vem de la; a
 * tela apenas ja sugere o prefixo no campo, para a pessoa nao descobrir a regra
 * por erro.
 */

const CAMPO =
  "w-full rounded border border-borda bg-papel px-2 py-1.5 text-[12px] " +
  "dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta";

export function Variaveis() {
  const [lista, setLista] = useState<Variavel[]>([]);
  const [nome, setNome] = useState("WF_");
  const [valor, setValor] = useState("");
  const [erro, setErro] = useState<string | null>(null);

  const recarregar = () =>
    api
      .variaveis()
      .then(setLista)
      .catch((e: ErroDaApi) => setErro(e.message));

  useEffect(() => {
    void recarregar();
  }, []);

  const salvar = async () => {
    setErro(null);
    try {
      await api.definirVariavel(nome.trim(), valor);
      // O valor sai da tela assim que vai para o servidor. Deixa-lo no campo o
      // manteria no DOM, no autofill do navegador e num print de tela.
      setValor("");
      await recarregar();
    } catch (e) {
      setErro((e as ErroDaApi).message);
    }
  };

  const remover = async (n: string) => {
    setErro(null);
    try {
      await api.removerVariavel(n);
      await recarregar();
    } catch (e) {
      setErro((e as ErroDaApi).message);
    }
  };

  return (
    <div>
      <p className="mb-2 text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
        O que um bloco <span className="font-mono">Input</span> usa para
        alcançar o sistema do cliente: aponte{" "}
        <span className="font-mono">token_env</span> ou{" "}
        <span className="font-mono">dsn_env</span> para um destes nomes. O valor
        entra aqui e nunca mais é mostrado.
      </p>

      {lista.length > 0 && (
        <ul className="mb-2.5 grid gap-1">
          {lista.map((v) => (
            <li
              key={v.nome}
              className="flex items-center gap-2 rounded border border-borda px-2 py-1.5 text-[11.5px] dark:border-noite-borda"
            >
              <span className="truncate font-mono">{v.nome}</span>
              <span
                className={`ml-auto shrink-0 text-[10px] ${
                  v.definida
                    ? "text-regra dark:text-noite-regra"
                    : "text-lacuna dark:text-noite-crew"
                }`}
              >
                {v.definida ? "definida" : "ausente"}
              </span>
              <button
                type="button"
                onClick={() => void remover(v.nome)}
                title="apaga do processo e do disco"
                className="shrink-0 text-[10.5px] text-red-700 underline hover:text-red-800 dark:text-red-400"
              >
                remover
              </button>
            </li>
          ))}
        </ul>
      )}

      <input
        value={nome}
        onChange={(e) => setNome(e.target.value.toUpperCase())}
        placeholder="WF_TOKEN_ERP"
        spellCheck={false}
        className={`mb-1.5 font-mono ${CAMPO}`}
      />
      <input
        type="password"
        value={valor}
        onChange={(e) => setValor(e.target.value)}
        placeholder="o valor — some daqui ao salvar"
        spellCheck={false}
        className={`mb-1.5 ${CAMPO}`}
      />
      <button
        type="button"
        disabled={!nome.trim() || !valor}
        onClick={() => void salvar()}
        className="w-full rounded border border-tinta bg-tinta px-3 py-1.5 text-[12px] text-white transition disabled:cursor-not-allowed disabled:border-neutral-300 disabled:bg-neutral-300 dark:border-noite-borda dark:bg-noite-cartao dark:text-noite-tinta dark:disabled:bg-noite-fundo dark:disabled:text-noite-fraca"
      >
        Salvar variável
      </button>

      {erro && (
        <p className="mt-2 rounded bg-red-50 px-2 py-1.5 text-[11px] leading-snug text-red-700 dark:bg-red-950/30 dark:text-red-400">
          {erro}
        </p>
      )}
    </div>
  );
}
