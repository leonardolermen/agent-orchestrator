import { useEffect, useState } from "react";
import {
  api,
  type FontePedido,
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
 * medido" em vez de inventar — e quando a fonte não tem gabarito, ela diz
 * isso mesmo, no lugar da taxa.
 *
 * **A execução GASTA quando a cascata tem agente.** Por isso ela não é mais
 * automática: a pessoa escolhe a fonte, diz o teto ANTES, e só então clica em
 * "rodar". `definicao` (a cascata desenhada) continua carregando sozinha —
 * ela não gasta nada.
 */

const NAO_MEDIDO = "não medido";

/** Sempre USD: `microcents` nunca é reais, nem quando o valor é zero. */
function formatarUSD(microcents: number): string {
  return microcents === 0 ? "US$ 0" : `US$ ${(microcents / 1e8).toFixed(6)}`;
}

function formatarCusto(m: LinhaDeRun | undefined): string {
  if (!m) return NAO_MEDIDO;
  return formatarUSD(m.microcents);
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
  const [rodando, setRodando] = useState(false);

  // A fonte. Sintética por default — o mesmo comportamento de antes desta
  // fatia — mas agora é uma ESCOLHA visível, não a única opção.
  const [fonteTipo, setFonteTipo] = useState<"sintetica" | "arquivo">("sintetica");
  const [seed, setSeed] = useState(dataset.seed);
  const [n, setN] = useState(dataset.n);
  const [taxaDivergencia, setTaxaDivergencia] = useState(dataset.taxa_divergencia);
  const [caminho, setCaminho] = useState("");
  const [kind, setKind] = useState("");
  const [campoId, setCampoId] = useState("");

  // O teto, "dito antes". Texto cru e não número: um campo vazio precisa
  // virar `null`, nunca `0` nem `NaN` — um default inventado no cliente é
  // exatamente o que a guarda do servidor existe para recusar.
  const [tetoTexto, setTetoTexto] = useState("");
  const tetoMicrocents = tetoTexto.trim() === "" ? null : Number(tetoTexto);
  const tetoValido = tetoTexto.trim() === "" || Number.isFinite(tetoMicrocents);

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
    // SÓ a definição — ela não gasta nada. A execução é um clique à parte
    // (ver `rodar` abaixo): a cascata pode ter agente, e carregar a tela não
    // pode ser o que dispara a cobrança.
    let vivo = true;
    api
      .workflow(workflow)
      .then((d) => {
        if (!vivo) return;
        setDefinicao(d);
        setErro(null);
      })
      .catch((e) => {
        if (!vivo) return;
        setDefinicao(null);
        setErro(e instanceof Error ? e.message : String(e));
      });
    return () => {
      vivo = false;
    };
  }, [workflow]);

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

  const escolhido = lista.find((w) => w.id === workflow);
  // Falso quando o servidor não tem `ANTHROPIC_API_KEY` OU quando a lista
  // ainda não carregou — o botão fica desabilitado até se PROVAR executável,
  // nunca o contrário.
  const executavel = escolhido?.executavel ?? false;
  const pago = escolhido?.classes.includes("AGENTE") ?? false;
  const podeRodar =
    !rodando && executavel && tetoValido && (!pago || tetoMicrocents !== null);

  async function rodar() {
    setRodando(true);
    setErro(null);
    try {
      const fonte: FontePedido =
        fonteTipo === "sintetica"
          ? { tipo: "sintetica", seed, n, taxa_divergencia: taxaDivergencia }
          : { tipo: "arquivo", caminho, kind, campo_id: campoId };
      const r = await api.rodar(workflow, fonte, tetoMicrocents);
      setRun(r);
    } catch (e) {
      setRun(null);
      setErro(e instanceof Error ? e.message : String(e));
    } finally {
      setRodando(false);
    }
  }

  const porNome = new Map((run?.por_resolver ?? []).map((r) => [r.name, r]));

  // Estados que não são "terminou bem". `ESTADOS_CONHECIDOS` só existe para a
  // tela ter um TEXTO amigável — o valor renderizado é sempre o do servidor;
  // um estado que a tela não conhece cai no `default` e mostra o string cru.
  const ESTADOS_CONHECIDOS: Record<string, string> = {
    concluido: "concluído",
    limite_de_custo: "parou no teto — o pedido proibiu de continuar gastando",
    limite_de_rondas: "parou no limite de rondas, sem convergir",
    aguardando_humano: "aguardando decisão humana",
    pendente: "pendente",
    executando: "executando",
    falhou: "falhou",
    cancelado: "cancelado",
  };
  const naoConcluido = !!run && run.estado !== "concluido";
  const textoEstado = run ? (ESTADOS_CONHECIDOS[run.estado] ?? run.estado) : "";

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
                ? run.contra_gabarito
                  ? `contra gabarito: ${(run.contra_gabarito.deterministic_rate * 100).toFixed(1)}% determinístico, medido em ${run.contra_gabarito.bank_total} lançamentos sintéticos (semente ${run.contra_gabarito.seed}, n=${run.contra_gabarito.n})`
                  : "sem gabarito: não há com o que comparar"
                : "")}
          </p>
          {run && (
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px]">
              <span className="tabular-nums text-neutral-600 dark:text-noite-fraca">
                custo desta execução: {formatarUSD(run.custo_microcents)}
              </span>
              {naoConcluido && (
                <span className="font-medium text-lacuna dark:text-noite-crew">
                  {textoEstado}
                  {run.teto_atingido && " (teto desta execução atingido)"}
                </span>
              )}
              {run.falhas > 0 && (
                <span className="font-medium text-lacuna dark:text-noite-crew">
                  {run.falhas} chamada(s) de API falharam
                </span>
              )}
            </p>
          )}
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
              // uma cascata que este servidor não consegue rodar (sem chave,
              // se ela tiver etapa paga). Protege só quem troca PELO seletor —
              // quem chega pelo link do grill é protegido pelo servidor, e a
              // mensagem dele aparece no cabeçalho.
              <option key={w.id} value={w.id} disabled={!w.executavel}>
                {w.executavel ? w.nome : `${w.nome} (não executável aqui)`}
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
        {/* A fonte e o teto — DITOS ANTES do botão de rodar. Rodar uma cascata
            paga sem teto declarado herdaria em silêncio o do agente; a tela
            não inventa um número, manda `null` e deixa o servidor recusar. */}
        <section className="rounded-lg border border-borda bg-white p-3 dark:border-noite-borda dark:bg-noite-cartao">
          <div className="mb-3 flex flex-wrap items-center gap-4 text-[12px]">
            <label className="flex items-center gap-1.5">
              fonte
              <select
                value={fonteTipo}
                onChange={(e) => setFonteTipo(e.target.value as "sintetica" | "arquivo")}
                className="rounded border border-borda bg-white px-2 py-1 text-tinta dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
              >
                <option value="sintetica">sintética (com gabarito)</option>
                <option value="arquivo">arquivo (sem gabarito)</option>
              </select>
            </label>

            {fonteTipo === "sintetica" ? (
              <>
                <CampoNumero rotulo="seed" valor={seed} definir={setSeed} />
                <CampoNumero rotulo="n" valor={n} definir={setN} />
                <CampoNumero
                  rotulo="taxa de divergência"
                  valor={taxaDivergencia}
                  definir={setTaxaDivergencia}
                  passo="0.01"
                />
              </>
            ) : (
              <>
                <CampoTexto rotulo="caminho" valor={caminho} definir={setCaminho} />
                <CampoTexto rotulo="kind" valor={kind} definir={setKind} />
                <CampoTexto rotulo="campo id" valor={campoId} definir={setCampoId} />
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-[12px]">
            <label className="flex items-center gap-1.5">
              teto desta execução (µ¢)
              <input
                type="text"
                inputMode="numeric"
                placeholder={pago ? "obrigatório" : "opcional"}
                value={tetoTexto}
                onChange={(e) => setTetoTexto(e.target.value)}
                className="w-32 rounded border border-borda bg-white px-2 py-1 text-tinta tabular-nums dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
              />
            </label>
            <span className="text-neutral-500 dark:text-noite-fraca">
              {tetoMicrocents !== null && tetoValido
                ? `= ${formatarUSD(tetoMicrocents)}`
                : "limita só esta requisição — não é orçamento agregado"}
            </span>

            <button
              type="button"
              onClick={rodar}
              disabled={!podeRodar}
              className="ml-auto rounded bg-humano px-3 py-1 font-medium text-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-noite-humano"
            >
              {rodando ? "rodando…" : "rodar"}
            </button>
          </div>
          {pago && !executavel && (
            <p className="mt-2 text-[12px] text-lacuna dark:text-noite-crew">
              {erro ?? "esta cascata tem etapa paga e não é executável neste servidor"}
            </p>
          )}
        </section>

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

function CampoNumero({
  rotulo,
  valor,
  definir,
  passo,
}: {
  rotulo: string;
  valor: number;
  definir: (v: number) => void;
  passo?: string;
}) {
  return (
    <label className="flex items-center gap-1.5">
      {rotulo}
      <input
        type="number"
        step={passo}
        value={valor}
        onChange={(e) => definir(Number(e.target.value))}
        className="w-20 rounded border border-borda bg-white px-2 py-1 text-tinta tabular-nums dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
      />
    </label>
  );
}

function CampoTexto({
  rotulo,
  valor,
  definir,
}: {
  rotulo: string;
  valor: string;
  definir: (v: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5">
      {rotulo}
      <input
        type="text"
        value={valor}
        onChange={(e) => definir(e.target.value)}
        className="w-40 rounded border border-borda bg-white px-2 py-1 text-tinta dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
      />
    </label>
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
