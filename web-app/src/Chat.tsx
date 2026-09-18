import { useEffect, useRef, useState } from "react";
import type { Receita } from "./api";

type Papel = "voce" | "entrevistador" | "sistema";
interface Fala {
  papel: Papel;
  texto: string;
}

type Estado = "parado" | "conectando" | "esperando" | "perguntou" | "fim";

interface Props {
  aoPropor: (receita: Receita, custoUsd: number) => void;
  temChave: boolean;
}

/**
 * O chat que COMPÕE a cascata. Gasta dinheiro — ver `api/entrevista.py`.
 *
 * Ele não reimplementa nada: o laço da entrevista roda no servidor, no mesmo
 * `Entrevistador` que a CLI do grill usa, com o mesmo teto e os mesmos três
 * desfechos. Este componente é a ponta do cano.
 *
 * O custo aparece na tela em todo desfecho, e isso é guarda de projeto, não
 * enfeite: gasto que não aparece na tela é gasto que ninguém revisa.
 */
export function Chat({ aoPropor, temChave }: Props) {
  const [falas, setFalas] = useState<Fala[]>([]);
  const [rascunho, setRascunho] = useState("");
  const [id, setId] = useState("");
  const [estado, setEstado] = useState<Estado>("parado");
  const [custo, setCusto] = useState<number | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const fim = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fim.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [falas, estado]);

  // Fecha a conexão ao desmontar. Sem isto, a thread do servidor ficaria
  // bloqueada esperando uma resposta que não vem — uma por aba fechada.
  useEffect(() => () => ws.current?.close(), []);

  const dizer = (papel: Papel, texto: string) =>
    setFalas((f) => [...f, { papel, texto }]);

  const comecar = () => {
    if (!id.trim() || !rascunho.trim()) return;
    const descricao = rascunho.trim();
    setFalas([{ papel: "voce", texto: descricao }]);
    setRascunho("");
    setCusto(null);
    setEstado("conectando");

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const s = new WebSocket(`${proto}//${location.host}/api/entrevista`);
    ws.current = s;

    s.onopen = () => {
      s.send(JSON.stringify({ workflow_id: id.trim(), descricao }));
      setEstado("esperando");
    };
    s.onerror = () => {
      dizer("sistema", "a conexão com o servidor falhou.");
      setEstado("fim");
    };
    s.onmessage = (ev) => {
      const m = JSON.parse(ev.data as string);
      if (typeof m.custo_usd === "number") setCusto(m.custo_usd);

      switch (m.tipo) {
        case "pergunta":
          dizer("entrevistador", m.texto);
          setEstado("perguntou");
          return;
        case "proposta":
          dizer(
            "entrevistador",
            `Proponho: ${m.receita.resolvers.map((r: { nome: string }) => r.nome).join(" → ")}. ` +
              `${m.receita.justificativa}`,
          );
          aoPropor(m.receita, m.custo_usd);
          setEstado("fim");
          return;
        case "recusa":
          // Recusa NÃO é erro: é o entrevistador dizendo que o descrito não cabe
          // no catálogo. "O que faltaria" é a parte útil.
          dizer("entrevistador", `${m.motivo}\n\nO que faltaria: ${m.o_que_faltaria}`);
          setEstado("fim");
          return;
        case "falhou":
          dizer("sistema", m.motivo);
          setEstado("fim");
          return;
        default:
          dizer("sistema", m.motivo ?? "desfecho desconhecido");
          setEstado("fim");
      }
    };
  };

  const responder = () => {
    if (!rascunho.trim() || estado !== "perguntou") return;
    dizer("voce", rascunho.trim());
    ws.current?.send(JSON.stringify({ texto: rascunho.trim() }));
    setRascunho("");
    setEstado("esperando");
  };

  const ocupado = estado === "conectando" || estado === "esperando";
  const comecou = estado !== "parado";

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-borda px-4 py-2.5 dark:border-noite-borda">
        <h2 className="text-[12.5px] font-semibold">Descreva e eu componho</h2>
        <p className="mt-0.5 text-[11px] leading-snug text-neutral-500 dark:text-noite-fraca">
          O entrevistador pergunta o que faltar e propõe o workflow.{" "}
          <strong className="font-medium text-lacuna dark:text-noite-crew">
            Gasta dinheiro
          </strong>{" "}
          — com teto, e o custo aparece aqui.
        </p>
      </div>

      {!temChave && (
        <p className="m-4 rounded-md bg-lacuna-fundo px-2.5 py-2 text-[11.5px] leading-snug text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew">
          Sem <code>ANTHROPIC_API_KEY</code> no servidor. O chat fala com o modelo
          e não tem como começar.
        </p>
      )}

      <div className="flex-1 space-y-2 overflow-y-auto px-4 py-3">
        {falas.length === 0 && (
          <p className="text-[11.5px] leading-relaxed text-neutral-400 dark:text-noite-fraca">
            Ex.: <em>"recebo um extrato OFX e um razão em CSV; quero casar o que
            bate exato e mandar o resto para revisão"</em>
          </p>
        )}
        {falas.map((f, i) => (
          <div
            key={i}
            className={[
              "max-w-[92%] whitespace-pre-wrap rounded-lg px-2.5 py-1.5 text-[11.5px] leading-snug",
              f.papel === "voce"
                ? "ml-auto bg-tinta text-white dark:bg-noite-cartao dark:text-noite-tinta"
                : f.papel === "entrevistador"
                  ? "bg-neutral-100 dark:bg-noite-painel"
                  : "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-300",
            ].join(" ")}
          >
            {f.texto}
          </div>
        ))}
        {ocupado && (
          <p className="text-[11px] text-neutral-400 dark:text-noite-fraca">pensando…</p>
        )}
        <div ref={fim} />
      </div>

      <div className="border-t border-borda px-4 py-3 dark:border-noite-borda">
        {custo !== null && (
          <p className="mb-2 font-mono text-[10.5px] text-neutral-400 dark:text-noite-fraca">
            custo da entrevista: US$ {custo.toFixed(4)}
          </p>
        )}
        {!comecou && (
          <input
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="id do workflow: conciliacao-acme"
            spellCheck={false}
            className="mb-2 w-full rounded border border-borda bg-papel px-2 py-1.5 text-[12px] dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
          />
        )}
        <textarea
          value={rascunho}
          onChange={(e) => setRascunho(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              comecou ? responder() : comecar();
            }
          }}
          rows={2}
          disabled={!temChave || ocupado || estado === "fim"}
          placeholder={
            estado === "fim"
              ? "entrevista encerrada"
              : comecou
                ? "sua resposta…"
                : "o que você precisa resolver?"
          }
          className="w-full resize-none rounded border border-borda bg-papel px-2 py-1.5 text-[12px] disabled:opacity-50 dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
        />
        <button
          type="button"
          onClick={comecou ? responder : comecar}
          disabled={!temChave || ocupado || estado === "fim" || !rascunho.trim() || (!comecou && !id.trim())}
          className="mt-2 w-full rounded border border-tinta bg-tinta px-3 py-1.5 text-[12px] text-white transition disabled:cursor-not-allowed disabled:border-neutral-300 disabled:bg-neutral-300 dark:border-noite-borda dark:bg-noite-cartao dark:text-noite-tinta dark:disabled:bg-noite-painel dark:disabled:text-noite-fraca"
        >
          {comecou ? "Responder" : "Começar entrevista"}
        </button>
      </div>
    </div>
  );
}
