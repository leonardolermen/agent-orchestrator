import { useEffect, useState } from "react";
import {
  api,
  type LinhaDeRun,
  type Run,
  type WorkflowConstruido,
  type WorkflowResumo,
} from "./api";
import { parametrosDaUrl } from "./Fila";
import { BotaoDeTema, usarTema } from "./tema";

/**
 * A cascata EM EXECUÇÃO: um workflow já salvo, com os números medidos.
 *
 * Portada de `web/canvas.js`, que era uma página estática. É a vista de
 * NAVEGAR — escolhe um workflow salvo e mostra o que ele custa —, distinta do
 * canvas de AUTORIA (`App.tsx`), que compõe uma cascata nova. As duas desenham
 * cascatas e não são a mesma ferramenta.
 *
 * **Por que ela não podia simplesmente sumir na migração.** A CLI do grill
 * imprime `→ http://localhost:8000/?workflow=<id>` como último passo da
 * entrevista (`grill/cli.py:122`). Quando a receita tem classe AGENTE a CLI
 * não pode executá-la, e esse link é a entrega: é nele que o parceiro clica.
 * Apagar esta vista quebraria esse fluxo em silêncio.
 *
 * **Nenhum número é escrito aqui.** Se a API não mediu, a tela diz "não
 * medido" em vez de inventar.
 */

const NAO_MEDIDO = "não medido";

/** Sempre USD: `microcents` nunca é reais, nem quando o valor é zero. */
function formatarCusto(m: LinhaDeRun | undefined): string {
  if (!m) return NAO_MEDIDO;
  return m.microcents === 0 ? "US$ 0" : `US$ ${(m.microcents / 1e8).toFixed(6)}`;
}

function formatarTaxa(m: LinhaDeRun | undefined): string {
  return m ? `${(m.rate * 100).toFixed(1)}%` : "—";
}

export function Execucao() {
  const [escuro, alternarTema] = usarTema();
  const [{ workflow, dataset }] = useState(parametrosDaUrl);
  const [lista, setLista] = useState<WorkflowResumo[]>([]);
  const [definicao, setDefinicao] = useState<WorkflowConstruido | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [erroDaLista, setErroDaLista] = useState<string | null>(null);

  useEffect(() => {
    // O seletor falha SOZINHO, e é deliberado: uma falha ao listar não pode
    // apagar a cascata que carregou bem. Na versão estática isso morria num
    // `console.error` e o `<select>` ficava vazio, sem sinal nenhum para quem
    // estava olhando a tela.
    api
      .workflows()
      .then(setLista)
      .catch((e) => setErroDaLista(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    let vivo = true;
    // A definição e a execução, em paralelo — e as DUAS precisam ter dado
    // certo. `pedir` levanta em `!ok`, então um 409 (cascata com etapa paga)
    // ou um 404 (id que não existe) chega aqui como erro em vez de virar uma
    // cascata desenhada a partir do corpo de um erro.
    Promise.all([api.workflow(workflow), api.rodar(workflow, dataset)])
      .then(([d, r]) => {
        if (!vivo) return;
        setDefinicao(d);
        setRun(r);
        setErro(null);
      })
      .catch((e) => {
        if (!vivo) return;
        setDefinicao(null);
        setRun(null);
        // `detail` é texto do servidor, mas carrega o id do workflow —
        // escolhido por quem gerou a receita a partir da prosa do parceiro.
        // Em JSX ele é escapado por construção.
        setErro(e instanceof Error ? e.message : String(e));
      });
    return () => {
      vivo = false;
    };
  }, [workflow, dataset]);

  const trocar = (id: string) => {
    const q = new URLSearchParams(location.search);
    q.set("workflow", id);
    location.search = q.toString();
  };

  const paraAFila = new URLSearchParams({
    vista: "fila",
    seed: String(dataset.seed),
    n: String(dataset.n),
    taxa_divergencia: String(dataset.taxa_divergencia),
    workflow,
  });

  const porNome = new Map((run?.by_resolver ?? []).map((r) => [r.name, r]));

  return (
    <div className="min-h-screen bg-papel text-tinta dark:bg-noite-fundo dark:text-noite-tinta">
      <header className="mx-auto flex max-w-3xl flex-wrap items-center gap-3 px-4 pb-4 pt-6">
        <div className="min-w-0">
          <h1 className="text-[17px] font-semibold">
            {erro ? "workflow indisponível" : (definicao?.name ?? "carregando…")}
          </h1>
          <p className="text-[12px] text-neutral-500 dark:text-noite-fraca">
            {erro ??
              (run
                ? `medido em ${run.bank_total} lançamentos sintéticos (semente ${run.seed}, n=${run.n})`
                : "")}
          </p>
        </div>

        <label className="ml-auto flex items-center gap-1.5 text-[12px] text-neutral-500 dark:text-noite-fraca">
          workflow
          <select
            value={workflow}
            onChange={(e) => trocar(e.target.value)}
            className="rounded border border-borda bg-white px-2 py-1 text-[12px] text-tinta dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
          >
            {erroDaLista && <option disabled>falha ao listar workflows</option>}
            {lista.map((w) => (
              // Uma opção desabilitada é o que impede escolher, pelo dropdown,
              // uma cascata com etapa paga e colher um 409. Protege só quem
              // troca PELO seletor — quem chega pelo link do grill é protegido
              // pelo servidor, e a mensagem dele aparece no cabeçalho.
              <option key={w.id} value={w.id} disabled={!w.executavel}>
                {w.executavel ? w.nome : `${w.nome} (etapa paga)`}
              </option>
            ))}
          </select>
        </label>

        <BotaoDeTema escuro={escuro} alternar={alternarTema} />
        <a
          href={`/?${paraAFila}`}
          className="text-[12px] text-humano hover:underline dark:text-noite-humano"
        >
          fila de revisão →
        </a>
        <a
          href="/?vista=compor"
          className="text-[12px] text-humano hover:underline dark:text-noite-humano"
        >
          compor →
        </a>
      </header>

      <main className="mx-auto grid max-w-3xl gap-4 px-4 pb-8">
        {definicao?.stages.map((stage) => (
          <section
            key={stage.name}
            className="rounded-lg border border-borda bg-white p-3 dark:border-noite-borda dark:bg-noite-cartao"
          >
            <h2 className="mb-2 text-[13px] font-medium">{stage.name}</h2>
            {stage.cascade.map((r, i) => (
              <Linha
                key={r.name}
                ordem={String(i + 1)}
                nome={r.name}
                titulo={r.summary}
                classe={r.cost_class}
                custo={formatarCusto(porNome.get(r.name))}
                taxa={formatarTaxa(porNome.get(r.name))}
              />
            ))}
            {/* A LACUNA sempre aparece, mesmo quando é zero. É o ponto mais
                valioso da tela: é onde o especialista diz "tem regra sim, é o
                código de retorno do CNAB". Esconder a linha faria o leitor não
                saber se ela foi medida. */}
            {run && (
              <Linha
                ordem="—"
                nome="sem resolver configurado"
                classe="LACUNA"
                custo="—"
                taxa={`${(run.gap.rate * 100).toFixed(1)}%`}
                lacuna
              />
            )}
          </section>
        ))}
      </main>
    </div>
  );
}

const COR_DA_CLASSE: Record<string, string> = {
  REGRA: "text-regra dark:text-noite-regra",
  AGENTE: "text-agente dark:text-noite-agente",
  CREW: "text-crew dark:text-noite-crew",
  HUMANO: "text-humano dark:text-noite-humano",
  LACUNA: "text-lacuna dark:text-noite-crew",
};

function Linha({
  ordem,
  nome,
  titulo,
  classe,
  custo,
  taxa,
  lacuna,
}: {
  ordem: string;
  nome: string;
  titulo?: string;
  classe: string;
  custo: string;
  taxa: string;
  lacuna?: boolean;
}) {
  return (
    <div
      className={`grid grid-cols-[1.5rem_1fr_5rem_8rem_4rem] items-center gap-2 border-t border-borda/60 py-1.5 text-[12px] dark:border-noite-borda/60 ${
        lacuna ? "bg-lacuna-fundo dark:bg-noite-lacuna-fundo" : ""
      }`}
    >
      <span className="text-neutral-400 dark:text-noite-fraca">{ordem}</span>
      <span title={titulo} className="truncate font-medium">
        {nome}
      </span>
      <span className={`font-medium ${COR_DA_CLASSE[classe] ?? ""}`}>{classe}</span>
      <span className="tabular-nums text-neutral-600 dark:text-noite-fraca">{custo}</span>
      <span className="text-right tabular-nums">{taxa}</span>
    </div>
  );
}
