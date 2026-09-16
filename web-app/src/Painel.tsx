import { useState } from "react";
import { CORES, type EntradaCatalogo, type Run, type WorkflowConstruido } from "./api";
import type { DadosDoNo } from "./NoResolver";

interface Props {
  catalogo: EntradaCatalogo[];
  escolhidos: DadosDoNo[];
  selecionado: string | null;
  erro: string | null;
  construido: WorkflowConstruido | null;
  run: Run | null;
  rodando: boolean;
  onAcrescentar: (e: EntradaCatalogo) => void;
  onRemover: (nome: string) => void;
  onMudarParametro: (nome: string, param: string, valor: number) => void;
  onCompor: (id: string, nome: string) => void;
  onExecutar: () => void;
}

export function Painel(p: Props) {
  const [id, setId] = useState("");
  const [nome, setNome] = useState("");

  const atual = p.escolhidos.find((d) => d.entrada.nome === p.selecionado);
  const temAgente = p.escolhidos.some((d) => d.entrada.cost_class === "AGENTE");
  const paga =
    p.construido?.stages.some((s) => s.cascade.some((r) => r.cost_class === "AGENTE")) ?? false;

  return (
    <aside className="overflow-y-auto border-l border-borda bg-white px-4 py-4">
      <Secao titulo="Cascata" ajuda="Clique para acrescentar. Cada um entra uma vez só.">
        <ul className="grid gap-1.5">
          {p.catalogo.map((e) => {
            const usado = p.escolhidos.some((d) => d.entrada.nome === e.nome);
            return (
              <li key={e.nome}>
                <button
                  type="button"
                  disabled={usado}
                  onClick={() => p.onAcrescentar(e)}
                  // O motivo de estar desabilitado fica no próprio botão:
                  // `construir` recusa resolver repetido porque o segundo
                  // rodaria sobre o pool que o primeiro esvaziou.
                  title={
                    usado
                      ? "já está na cascata; o segundo rodaria sobre o pool que o primeiro esvaziou"
                      : `acrescentar ${e.nome}`
                  }
                  className={[
                    "w-full rounded-md border border-borda border-l-[3px] px-2.5 py-1.5 text-left transition",
                    CORES[e.cost_class].borda.replace("border-t-", "border-l-"),
                    usado ? "opacity-40 cursor-not-allowed" : "hover:bg-neutral-50",
                  ].join(" ")}
                >
                  <span className="flex items-baseline gap-2">
                    <span className="text-[12.5px] font-medium">{e.nome}</span>
                    <span
                      className={`ml-auto text-[9.5px] tracking-wider ${CORES[e.cost_class].texto}`}
                    >
                      {e.cost_class}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-snug text-neutral-500">
                    {e.resumo}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </Secao>

      {atual && (
        <Secao titulo={atual.entrada.nome} ajuda={atual.entrada.resumo}>
          {atual.entrada.parametros.length === 0 ? (
            <p className="text-[11.5px] text-neutral-400">sem parâmetros.</p>
          ) : (
            atual.entrada.parametros.map((spec) => (
              <label key={spec.nome} className="mb-2.5 block">
                <span className="flex items-center gap-2">
                  <span className="text-[11.5px] text-neutral-600">{spec.nome}</span>
                  <input
                    type="number"
                    value={atual.parametros[spec.nome]}
                    onChange={(ev) =>
                      // `parseInt` e não `Number`: campo vazio vira NaN e o
                      // servidor recusa. Um 0 silencioso viraria `max_cents=0`,
                      // que é cascata legítima e não o que a pessoa quis.
                      p.onMudarParametro(
                        atual.entrada.nome,
                        spec.nome,
                        parseInt(ev.target.value, 10),
                      )
                    }
                    className="ml-auto w-24 rounded border border-borda bg-papel px-1.5 py-1 text-right font-mono text-[11.5px]"
                  />
                </span>
                <span className="mt-0.5 block text-[10.5px] leading-snug text-neutral-400">
                  {spec.descricao}
                </span>
              </label>
            ))
          )}
          <button
            type="button"
            onClick={() => p.onRemover(atual.entrada.nome)}
            className="text-[11.5px] text-red-700 underline hover:text-red-800"
          >
            remover da cascata
          </button>
        </Secao>
      )}

      {p.escolhidos.length > 0 && (
        // Âmbar e não vermelho: uma cascata com classe AGENTE não está errada —
        // ela custa, e a diferença entre "errado" e "caro" é a tese do produto.
        <div
          className={[
            "mb-5 rounded-md px-2.5 py-2 text-[11.5px] leading-snug",
            temAgente ? "bg-lacuna-fundo text-lacuna" : "bg-emerald-50 text-regra",
          ].join(" ")}
        >
          {temAgente
            ? "Tem classe AGENTE: gasta dinheiro ao rodar, e a API não a executa."
            : "Nenhum resolver paga por token. Roda de graça."}
        </div>
      )}

      <Secao titulo="Identidade">
        <input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="conciliacao-cliente-x"
          spellCheck={false}
          className="mb-2 w-full rounded border border-borda bg-papel px-2 py-1.5 text-[12.5px]"
        />
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="nome (opcional)"
          className="mb-2.5 w-full rounded border border-borda bg-papel px-2 py-1.5 text-[12.5px]"
        />
        <div className="flex gap-2">
          <button
            type="button"
            disabled={p.escolhidos.length === 0 || !id.trim()}
            onClick={() => p.onCompor(id.trim(), nome.trim())}
            className="flex-1 rounded border border-tinta bg-tinta px-3 py-1.5 text-[12.5px] text-white transition disabled:cursor-not-allowed disabled:border-neutral-300 disabled:bg-neutral-300"
          >
            Compor e validar
          </button>
          {p.construido && (
            <button
              type="button"
              disabled={paga || p.rodando}
              onClick={p.onExecutar}
              // A tela desabilita, mas quem GARANTE é o servidor: a regra de
              // `api/app.py` é que nenhum endpoint gasta dinheiro, e ela não é
              // flag — é ausência de caminho de código. O botão existe para a
              // pessoa não descobrir isso num 409.
              title={
                paga
                  ? "esta cascata tem etapa paga; a API não executa nada que gaste dinheiro — rode pela CLI"
                  : "roda sobre o benchmark sintético, de graça"
              }
              className="rounded border border-regra bg-regra px-3 py-1.5 text-[12.5px] text-white transition disabled:cursor-not-allowed disabled:border-borda disabled:bg-white disabled:text-neutral-400"
            >
              {p.rodando ? "rodando…" : "▶ Run"}
            </button>
          )}
        </div>
        {p.erro && <p className="mt-2 text-[11.5px] leading-snug text-red-700">{p.erro}</p>}
      </Secao>

      {p.construido && (
        <Secao
          titulo="Como ela vai rodar"
          ajuda="A definição construída pelo servidor — não o que você desenhou."
        >
          <ol className="grid gap-1">
            {p.construido.stages.flatMap((s) =>
              s.cascade.map((r) => (
                <li
                  key={r.name}
                  className={`rounded border border-borda border-l-[3px] px-2.5 py-1.5 ${CORES[
                    r.cost_class
                  ].borda.replace("border-t-", "border-l-")}`}
                >
                  <span className="flex items-baseline gap-2">
                    <span className="text-[12px] font-medium">{r.name}</span>
                    <span
                      className={`ml-auto text-[9.5px] tracking-wider ${CORES[r.cost_class].texto}`}
                    >
                      {r.cost_class}
                    </span>
                  </span>
                  <span className="block text-[11px] text-neutral-500">{r.summary}</span>
                </li>
              )),
            )}
          </ol>
        </Secao>
      )}

      {p.run && (
        <Secao titulo="Execução" ajuda={`benchmark sintético, semente ${p.run.seed}, ${p.run.n} lançamentos.`}>
          <p className="mb-2 flex items-baseline gap-2">
            <strong className="text-2xl font-semibold text-regra">
              {(100 * p.run.deterministic_rate).toFixed(1)}%
            </strong>
            <span className="text-[11px] text-neutral-500">resolvido sem gastar nada</span>
          </p>
          <ul className="mb-2">
            {p.run.by_resolver.map((l) => (
              <li
                key={l.name}
                className="flex items-baseline gap-2 border-b border-neutral-100 py-1 text-[11.5px]"
              >
                <span className="font-medium">{l.name}</span>
                <span className="ml-auto font-mono tabular-nums">{l.matches}</span>
                <span className="w-20 text-right font-mono text-[10.5px] text-neutral-400">
                  {/* µ¢ de dólar, inteiro — a constraint de dinheiro do projeto
                      proíbe ponto flutuante acumulando. Aqui só é dividido para
                      exibir. */}
                  {l.microcents > 0 ? `US$ ${(l.microcents / 1e8).toFixed(4)}` : "grátis"}
                </span>
              </li>
            ))}
          </ul>
          {/* A LACUNA, sempre declarada — inclusive quando é zero. É invariante
              do §1.5, e esconder a linha faria o leitor não saber se foi medida. */}
          <p className="rounded-md bg-lacuna-fundo px-2.5 py-2 text-[11.5px] text-lacuna">
            {p.run.gap.items} item(ns) sem resolução ({(100 * p.run.gap.rate).toFixed(1)}%)
          </p>
        </Secao>
      )}
    </aside>
  );
}

function Secao({
  titulo,
  ajuda,
  children,
}: {
  titulo: string;
  ajuda?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-5">
      <h2 className="mb-0.5 text-[12.5px] font-semibold tracking-wide">{titulo}</h2>
      {ajuda && <p className="mb-2 text-[11px] leading-snug text-neutral-500">{ajuda}</p>}
      {children}
    </section>
  );
}
