import { useCallback, useEffect, useState } from "react";
import {
  api,
  ErroDaApi,
  type Decisao,
  type Fila as FilaDaApi,
  type ItemDaFila,
  type Lancamento,
  type ParametrosDaFila,
} from "./api";
import { BotaoDeTema, usarTema } from "./tema";

/**
 * A fila de revisão humana. Portada de `web/fila.js`, que era uma página
 * estática separada.
 *
 * **A tela não decide nada:** ela mostra o que a API mediu e manda de volta o
 * que o humano escolheu. Nenhum número é escrito aqui.
 *
 * **O que a migração ELIMINOU, e não é detalhe.** Enquanto a fila e o canvas
 * eram duas páginas, as duas precisavam concordar sobre QUAL fila estavam
 * olhando — a fila é escopada em duas dimensões independentes
 * (`caminho_da_fila(workflow_id, dataset)` toma o workflow, e o
 * `dataset_id(seed, n, taxa)` vem separado) — e a coordenação dependia de as
 * duas lerem a mesma query string com os mesmos defaults. O `DECISOES.md`
 * registra, no P4.14, que essa promessa JÁ QUEBROU uma vez, porque nada além
 * de lembrança humana mantinha as duas listas de defaults iguais.
 *
 * Com uma aplicação só, não há com quem discordar: os parâmetros são lidos uma
 * vez e as duas vistas leem o mesmo estado.
 */

const PADROES: ParametrosDaFila = { seed: 1, n: 300, taxa_divergencia: 0.15 };

function numeroDaQuery(q: URLSearchParams, nome: string, padrao: number): number {
  const bruto = q.get(nome);
  if (bruto === null || bruto === "") return padrao;
  const numero = Number(bruto);
  return Number.isFinite(numero) ? numero : padrao;
}

/** Os mesmos defaults de `RunRequest` (api/schemas.py). */
export function parametrosDaUrl(): { workflow: string; dataset: ParametrosDaFila } {
  const q = new URLSearchParams(location.search);
  return {
    workflow: q.get("workflow") || "conciliacao",
    dataset: {
      seed: numeroDaQuery(q, "seed", PADROES.seed),
      n: numeroDaQuery(q, "n", PADROES.n),
      taxa_divergencia: numeroDaQuery(q, "taxa_divergencia", PADROES.taxa_divergencia),
    },
  };
}

/** O identificador de quem decide. Lembrado por visitante, nunca exigido dele
 *  duas vezes — mas `localStorage` pode levantar, e aí ele digita de novo. */
function autorLembrado(): string {
  try {
    return localStorage.getItem("autor") || "";
  } catch {
    return "";
  }
}

export function Fila() {
  const [escuro, alternarTema] = usarTema();
  const [{ workflow, dataset }] = useState(parametrosDaUrl);
  const [fila, setFila] = useState<FilaDaApi | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [autor, setAutor] = useState(autorLembrado);

  const carregar = useCallback(async () => {
    try {
      setFila(await api.fila(workflow, dataset));
      setErro(null);
    } catch (e) {
      setErro(`falhou ao carregar: ${e instanceof Error ? e.message : e}`);
    }
  }, [workflow, dataset]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  const decidir = async (item: ItemDaFila, corpo: Decisao) => {
    if (!corpo.autor) {
      setErro("preencha seu identificador antes de decidir");
      return;
    }
    try {
      localStorage.setItem("autor", corpo.autor);
    } catch {
      /* armazenamento bloqueado: segue sem lembrar */
    }
    try {
      await api.decidir(workflow, item.divergence_id, dataset, corpo);
    } catch (e) {
      // DOIS modos de falha, e eles precisam de mensagens diferentes. Um 422
      // carrega em `detail` a razão exata — "corrigir exige tipo", ids
      // inexistentes — e `ErroDaApi.message` já traz esse texto; mostrar só o
      // código deixaria o revisor sem saber o que corrigir. Uma falha de REDE
      // nem chega a ter resposta: `fetch` rejeita antes, e sem este ramo o
      // clique sumiria no vácuo, sem alerta e sem mudança na lista.
      setErro(
        e instanceof ErroDaApi
          ? `falhou (${e.status}): ${e.message}`
          : `falha de rede ao decidir: ${e instanceof Error ? e.message : e}`,
      );
      return;
    }
    setErro(null);
    // O item decidido sai da lista pendente. Recarregar a fila inteira seria
    // uma volta ao servidor por clique; o estado local basta porque a decisão
    // já foi gravada — e o append-only da fila é a fonte, não esta tela.
    setFila((f) =>
      f ? { ...f, itens: f.itens.filter((i) => i.divergence_id !== item.divergence_id) } : f,
    );
  };

  const paraOCanvas = new URLSearchParams({
    seed: String(dataset.seed),
    n: String(dataset.n),
    taxa_divergencia: String(dataset.taxa_divergencia),
    workflow,
  });

  return (
    <div className="flex min-h-screen flex-col bg-papel text-tinta dark:bg-noite-fundo dark:text-noite-tinta">
      <header className="flex items-center gap-3 border-b border-borda px-4 py-2 dark:border-noite-borda">
        <h1 className="text-[15px] font-semibold">Fila de revisão</h1>
        <p className="text-[12px] text-neutral-500 dark:text-noite-fraca">
          {fila
            ? `${fila.itens.length} pendente(s) — dataset ${fila.dataset}`
            : erro ?? "carregando…"}
        </p>
        <label className="ml-auto flex items-center gap-1.5 text-[12px] text-neutral-500 dark:text-noite-fraca">
          quem decide
          <input
            value={autor}
            onChange={(e) => setAutor(e.target.value)}
            placeholder="seu identificador"
            className="rounded border border-borda bg-white px-2 py-1 text-[12px] text-tinta dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
          />
        </label>
        <BotaoDeTema escuro={escuro} alternar={alternarTema} />
        <a
          href={`/?${paraOCanvas}`}
          className="text-[12px] text-humano hover:underline dark:text-noite-humano"
        >
          ← workflow
        </a>
      </header>

      {erro && fila && (
        <p className="border-b border-borda bg-lacuna-fundo px-4 py-2 text-[12px] text-lacuna dark:border-noite-borda dark:bg-noite-lacuna-fundo dark:text-noite-crew">
          {erro}
        </p>
      )}

      <main className="mx-auto grid w-full max-w-4xl gap-4 p-4">
        {fila?.itens.length === 0 && (
          <p className="text-[13px] text-neutral-500 dark:text-noite-fraca">
            Nada pendente neste dataset.
          </p>
        )}
        {fila?.itens.map((item) => (
          <ItemPendente
            key={item.divergence_id}
            item={item}
            tipos={fila.tipos}
            autor={autor.trim()}
            aoDecidir={decidir}
          />
        ))}
      </main>
    </div>
  );
}

function ItemPendente({
  item,
  tipos,
  autor,
  aoDecidir,
}: {
  item: ItemDaFila;
  tipos: string[];
  autor: string;
  aoDecidir: (item: ItemDaFila, corpo: Decisao) => void;
}) {
  const [corrigindo, setCorrigindo] = useState(false);
  const [tipoCorrigido, setTipoCorrigido] = useState(tipos[0] ?? "");
  const [ids, setIds] = useState("");

  return (
    <section className="rounded-lg border border-borda bg-white p-3 dark:border-noite-borda dark:bg-noite-cartao">
      <h2 className="mb-2 font-mono text-[12px] text-neutral-500 dark:text-noite-fraca">
        {item.divergence_id}
      </h2>

      <table className="mb-2 w-full text-[12px]">
        <tbody>
          {item.lancamentos.map((l) => (
            <LinhaDoLancamento key={`${l.lado}-${l.id}`} l={l} />
          ))}
        </tbody>
      </table>

      <p className="mb-1 flex flex-wrap items-center gap-2 text-[12px]">
        <span className="rounded bg-neutral-100 px-1.5 py-0.5 font-medium dark:bg-noite-painel">
          {item.tipo}
        </span>
        <span className={confiancaClasse(item.confianca)}>{item.confianca}</span>
        {/* `explicacao` e `evidencia` são texto livre que o AGENTE produziu.
            Em JSX, um filho de texto é escapado por construção — o equivalente
            do `textContent` que a versão estática precisava usar à mão para
            impedir que a saída do modelo virasse marcação. Nada aqui pode
            injetar uma tag, e é por isso que não existe `dangerouslySetInnerHTML`
            em lugar nenhum desta tela. */}
        <span className="text-neutral-600 dark:text-noite-fraca">{item.explicacao}</span>
      </p>

      {item.evidencia.length > 0 && (
        <ul className="mb-2 ml-4 list-disc text-[11px] text-neutral-500 dark:text-noite-fraca">
          {item.evidencia.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <Acao rotulo="Aceitar" aoClicar={() => aoDecidir(item, { veredito: "aceitar", autor })} />
        {/* "Corrigir" só ABRE a caixa — nunca decide sozinho. Os dois papéis
            já estiveram no mesmo botão: o 1º clique abria, o 2º caía direto em
            `decidir("corrigir")` com o select no primeiro tipo da lista e
            nenhum id — um "corrigir" inventado que o backend aceita de bom
            grado (lista vazia é abstenção legítima) e grava como decisão
            humana de verdade. */}
        <Acao rotulo="Corrigir" aoClicar={() => setCorrigindo((v) => !v)} />
        <Acao rotulo="Rejeitar" aoClicar={() => aoDecidir(item, { veredito: "rejeitar", autor })} />
      </div>

      {corrigindo && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-borda bg-neutral-50 p-2 dark:border-noite-borda dark:bg-noite-painel">
          {/* Os tipos vêm de `fila.tipos`, servido pela API. Uma lista escrita
              aqui viraria drift silencioso no dia em que a taxonomia crescer. */}
          <select
            value={tipoCorrigido}
            onChange={(e) => setTipoCorrigido(e.target.value)}
            className="rounded border border-borda bg-white px-2 py-1 text-[12px] dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
          >
            {tipos.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            value={ids}
            onChange={(e) => setIds(e.target.value)}
            placeholder="ids a conciliar, separados por vírgula"
            className="min-w-[18rem] flex-1 rounded border border-borda bg-white px-2 py-1 text-[12px] dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
          />
          <Acao
            rotulo="Confirmar correção"
            aoClicar={() =>
              aoDecidir(item, {
                veredito: "corrigir",
                autor,
                tipo: tipoCorrigido,
                conciliar_com: ids
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>
      )}
    </section>
  );
}

function LinhaDoLancamento({ l }: { l: Lancamento }) {
  return (
    <tr className="border-t border-borda/60 dark:border-noite-borda/60">
      <td className="py-1 pr-2 text-neutral-500 dark:text-noite-fraca">{l.lado}</td>
      <td className="pr-2 font-mono text-[11px]">{l.id}</td>
      <td className="pr-2">{l.data}</td>
      {/* Centavos int, formatados só na exibição. O valor NUNCA vira float no
          caminho de dado — ver `money.py`. */}
      <td className="pr-2 text-right tabular-nums">{(l.valor / 100).toFixed(2)}</td>
      <td className="pr-2">{l.contraparte}</td>
      <td className="text-neutral-500 dark:text-noite-fraca">{l.documento ?? "—"}</td>
    </tr>
  );
}

function Acao({ rotulo, aoClicar }: { rotulo: string; aoClicar: () => void }) {
  return (
    <button
      type="button"
      onClick={aoClicar}
      className="rounded border border-borda px-2.5 py-1 text-[12px] transition hover:bg-neutral-50 dark:border-noite-borda dark:hover:bg-noite-painel"
    >
      {rotulo}
    </button>
  );
}

function confiancaClasse(c: string): string {
  const base = "rounded px-1.5 py-0.5 text-[11px] font-medium";
  if (c === "ALTA") return `${base} text-regra dark:text-noite-regra`;
  if (c === "MEDIA") return `${base} text-agente dark:text-noite-agente`;
  return `${base} text-neutral-500 dark:text-noite-fraca`;
}
