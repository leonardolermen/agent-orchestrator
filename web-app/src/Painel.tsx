import { useState } from "react";
import {
  CORES,
  type Ambiente,
  type AgenteDeclarado,
  type DominioInfo,
  type Regra,
  type Run,
  type WorkflowConstruido,
} from "./api";
import { classeDo, nomeDo, type DadosAgente, type DadosDoNo } from "./NoResolver";

/** Um nó, do ponto de vista do painel. Estrutural, para não importar o React
 *  Flow aqui só por causa de um tipo. */
export interface NoEscolhido {
  id: string;
  data: DadosDoNo;
}

interface Props {
  dominio: DominioInfo | null;
  escolhidos: NoEscolhido[];
  selecionado: NoEscolhido | null;
  erro: string | null;
  construido: WorkflowConstruido | null;
  run: Run | null;
  rodando: boolean;
  ambiente: Ambiente | null;
  onAcrescentarRegra: (r: Regra) => void;
  onAcrescentarAgente: (a: AgenteDeclarado) => void;
  onNovoAgente: () => void;
  onRemover: (id: string) => void;
  onMudarParametro: (id: string, param: string, valor: number) => void;
  onMudarAgente: (id: string, patch: Partial<AgenteDeclarado>) => void;
  onCompor: (id: string, nome: string) => void;
  onExecutar: () => void;
  onMudarAmbiente: (a: Ambiente) => void;
}

const CAMPO =
  "w-full rounded border border-borda bg-papel px-2 py-1.5 text-[12px] " +
  "dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta";

export function Painel(p: Props) {
  const [id, setId] = useState("");
  const [nome, setNome] = useState("");

  const usados = new Set(p.escolhidos.map((n) => nomeDo(n.data)));
  const temAgente = p.escolhidos.some((n) => classeDo(n.data) === "AGENTE");
  const paga =
    p.construido?.stages.some((s) => s.cascade.some((r) => r.cost_class === "AGENTE")) ?? false;

  return (
    <aside className="overflow-y-auto border-l border-borda bg-white px-4 py-4 dark:border-noite-borda dark:bg-noite-painel">
      {/* A PALETA, e a assimetria que a plataforma tem por dentro aparece aqui:
          regra é código com parâmetros expostos — você escolhe QUAL entra;
          agente é dado — você CRIA um. */}
      <Secao
        titulo="Regras do domínio"
        ajuda={
          p.dominio?.regras.length
            ? "Determinísticas e grátis. Rodam antes de qualquer modelo."
            : undefined
        }
      >
        {p.dominio && p.dominio.regras.length === 0 ? (
          // A lacuna DECLARADA. Um domínio sem regra é uma cascata que começa
          // direto no modelo — caro por construção, e é exatamente onde há
          // mais a ganhar promovendo trabalho para baixo.
          <p className="rounded-md bg-lacuna-fundo px-2.5 py-2 text-[11px] leading-snug text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew">
            Este domínio não declara regra nenhuma: 100% do trabalho passa pelo modelo.
          </p>
        ) : (
          <ul className="grid gap-1.5">
            {p.dominio?.regras.map((r) => (
              <li key={r.nome}>
                <BotaoDePaleta
                  nome={r.nome}
                  resumo={r.resumo}
                  classe={r.cost_class}
                  usado={usados.has(r.nome)}
                  onClick={() => p.onAcrescentarRegra(r)}
                />
              </li>
            ))}
          </ul>
        )}
      </Secao>

      <Secao
        titulo="Agentes"
        ajuda="Um agente é DADO: prompt, vocabulário e ferramentas são campos. Crie um."
      >
        <ul className="mb-2 grid gap-1.5">
          {p.dominio?.agentes.map((a) => (
            <li key={a.name}>
              <BotaoDePaleta
                nome={a.name}
                resumo={`${a.tipos.join(", ")} · ${a.ferramentas.length} ferramenta(s)`}
                classe="AGENTE"
                usado={usados.has(a.name)}
                onClick={() => p.onAcrescentarAgente(a)}
              />
            </li>
          ))}
        </ul>
        <button
          type="button"
          disabled={!p.dominio}
          onClick={p.onNovoAgente}
          className="w-full rounded-md border border-dashed border-borda px-2.5 py-2 text-[12px] text-neutral-500 transition hover:bg-neutral-50 disabled:opacity-40 dark:border-noite-borda dark:text-noite-fraca dark:hover:bg-noite-cartao"
        >
          + agente em branco
        </button>
      </Secao>

      {p.selecionado?.data.tipo === "regra" && (
        <Secao
          titulo={p.selecionado.data.regra.nome}
          ajuda={p.selecionado.data.regra.resumo}
        >
          {p.selecionado.data.regra.parametros.length === 0 ? (
            <p className="text-[11.5px] text-neutral-400 dark:text-noite-fraca">
              sem parâmetros.
            </p>
          ) : (
            p.selecionado.data.regra.parametros.map((spec) => (
              <label key={spec.nome} className="mb-2.5 block">
                <span className="flex items-center gap-2">
                  <span className="text-[11.5px] text-neutral-600 dark:text-noite-fraca">
                    {spec.nome}
                  </span>
                  <input
                    type="number"
                    value={
                      (p.selecionado!.data as { parametros: Record<string, number> }).parametros[
                        spec.nome
                      ]
                    }
                    onChange={(ev) =>
                      // `parseInt` e não `Number`: campo vazio vira NaN e o
                      // servidor recusa. Um 0 silencioso viraria `max_cents=0`,
                      // que é cascata legítima e não o que a pessoa quis.
                      p.onMudarParametro(
                        p.selecionado!.id,
                        spec.nome,
                        parseInt(ev.target.value, 10),
                      )
                    }
                    className={`ml-auto w-24 text-right font-mono ${CAMPO}`}
                  />
                </span>
                <span className="mt-0.5 block text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
                  {spec.descricao}
                </span>
              </label>
            ))
          )}
          <Remover onClick={() => p.onRemover(p.selecionado!.id)} />
        </Secao>
      )}

      {p.selecionado?.data.tipo === "agente" && p.dominio && (
        <EditorDeAgente
          key={p.selecionado.id}
          no={{ id: p.selecionado.id, data: p.selecionado.data }}
          dominio={p.dominio}
          onMudar={p.onMudarAgente}
          onRemover={p.onRemover}
        />
      )}

      {p.escolhidos.length > 0 && (
        // Âmbar e não vermelho: uma cascata com classe AGENTE não está errada —
        // ela custa, e a diferença entre "errado" e "caro" é a tese do produto.
        <div
          className={[
            "mb-5 rounded-md px-2.5 py-2 text-[11.5px] leading-snug",
            temAgente
              ? "bg-lacuna-fundo text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew"
              : "bg-emerald-50 text-regra dark:bg-emerald-950/30 dark:text-noite-regra",
          ].join(" ")}
        >
          {temAgente
            ? "Tem classe AGENTE: gasta dinheiro ao rodar, e a API não a executa."
            : "Nenhum bloco paga por token. Roda de graça."}
        </div>
      )}

      {/* O AMBIENTE. Não é "configuração do agente": é o que uma execução
          recebe. O modelo aparece porque decide o preço; a chave aparece como
          SIM/NÃO porque a tela precisa saber se o chat funciona e nunca precisa
          do valor. */}
      {p.ambiente && (
        <Secao titulo="Ambiente" ajuda="O que uma execução usa.">
          <div className="mb-2 flex items-center gap-2 text-[11.5px]">
            <span className="text-neutral-500 dark:text-noite-fraca">modelo</span>
            <span className="ml-auto font-mono text-[11px]">{p.ambiente.modelo_padrao}</span>
          </div>
          <div className="mb-3 flex items-center gap-2 text-[11.5px]">
            <span className="text-neutral-500 dark:text-noite-fraca">ANTHROPIC_API_KEY</span>
            <span
              className={`ml-auto text-[11px] ${
                p.ambiente.tem_chave
                  ? "text-regra dark:text-noite-regra"
                  : "text-lacuna dark:text-noite-crew"
              }`}
            >
              {p.ambiente.tem_chave ? "configurada" : "ausente"}
            </span>
          </div>
          {(
            [
              ["seed", "semente do benchmark sintético"],
              ["n", "quantos lançamentos gerar"],
            ] as const
          ).map(([campo, dica]) => (
            <label key={campo} className="mb-2 block">
              <span className="flex items-center gap-2">
                <span className="text-[11.5px] text-neutral-600 dark:text-noite-fraca">
                  {campo}
                </span>
                <input
                  type="number"
                  value={p.ambiente![campo]}
                  max={campo === "n" ? p.ambiente!.n_max : undefined}
                  onChange={(ev) =>
                    p.onMudarAmbiente({
                      ...p.ambiente!,
                      [campo]: parseInt(ev.target.value, 10),
                    })
                  }
                  className={`ml-auto w-24 text-right font-mono ${CAMPO}`}
                />
              </span>
              <span className="mt-0.5 block text-[10.5px] text-neutral-400 dark:text-noite-fraca">
                {dica}
              </span>
            </label>
          ))}
        </Secao>
      )}

      <Secao titulo="Identidade">
        <input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="triagem-de-issues"
          spellCheck={false}
          className={`mb-2 ${CAMPO}`}
        />
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="nome (opcional)"
          className={`mb-2.5 ${CAMPO}`}
        />
        <div className="flex gap-2">
          <button
            type="button"
            disabled={p.escolhidos.length === 0 || !id.trim()}
            onClick={() => p.onCompor(id.trim(), nome.trim())}
            className="flex-1 rounded border border-tinta bg-tinta px-3 py-1.5 text-[12.5px] text-white transition disabled:cursor-not-allowed disabled:border-neutral-300 disabled:bg-neutral-300 dark:border-noite-borda dark:bg-noite-cartao dark:text-noite-tinta dark:disabled:bg-noite-fundo dark:disabled:text-noite-fraca"
          >
            Compor e validar
          </button>
          {p.construido && (
            <button
              type="button"
              disabled={paga || p.rodando}
              onClick={p.onExecutar}
              // A tela desabilita, mas quem GARANTE é o servidor: a regra de
              // `api/app.py` é que executar pela web nunca gasta dinheiro, e ela
              // não é flag — é ausência de caminho de código. O botão existe
              // para a pessoa não descobrir isso num 409.
              title={
                paga
                  ? "esta cascata tem etapa paga; a API não executa nada que gaste dinheiro — rode pela CLI"
                  : "roda sobre o benchmark sintético, de graça"
              }
              className="rounded border border-regra bg-regra px-3 py-1.5 text-[12.5px] text-white transition disabled:cursor-not-allowed disabled:border-borda disabled:bg-white disabled:text-neutral-400 dark:disabled:border-noite-borda dark:disabled:bg-noite-fundo dark:disabled:text-noite-fraca"
            >
              {p.rodando ? "rodando…" : "▶ Run"}
            </button>
          )}
        </div>
        {p.erro && (
          <p className="mt-2 text-[11.5px] leading-snug text-red-700 dark:text-red-400">
            {p.erro}
          </p>
        )}
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
                  className={`rounded border border-borda border-l-[3px] px-2.5 py-1.5 dark:border-noite-borda ${CORES[r.cost_class].bordaEsq}`}
                >
                  <span className="flex items-baseline gap-2">
                    <span className="text-[12px] font-medium">{r.name}</span>
                    <span
                      className={`ml-auto text-[9.5px] tracking-wider ${CORES[r.cost_class].texto}`}
                    >
                      {r.cost_class}
                    </span>
                  </span>
                  <span className="block text-[11px] text-neutral-500 dark:text-noite-fraca">
                    {r.summary}
                  </span>
                </li>
              )),
            )}
          </ol>
        </Secao>
      )}

      {p.run && (
        <Secao
          titulo="Execução"
          ajuda={`benchmark sintético, semente ${p.run.seed}, ${p.run.n} lançamentos.`}
        >
          <p className="mb-2 flex items-baseline gap-2">
            <strong className="text-2xl font-semibold text-regra dark:text-noite-regra">
              {(100 * p.run.deterministic_rate).toFixed(1)}%
            </strong>
            <span className="text-[11px] text-neutral-500 dark:text-noite-fraca">
              resolvido sem gastar nada
            </span>
          </p>
          <ul className="mb-2">
            {p.run.by_resolver.map((l) => (
              <li
                key={l.name}
                className="flex items-baseline gap-2 border-b border-neutral-100 py-1 text-[11.5px] dark:border-noite-borda"
              >
                <span className="font-medium">{l.name}</span>
                <span className="ml-auto font-mono tabular-nums">{l.matches}</span>
                <span className="w-20 text-right font-mono text-[10.5px] text-neutral-400 dark:text-noite-fraca">
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
          <p className="rounded-md bg-lacuna-fundo px-2.5 py-2 text-[11.5px] text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew">
            {p.run.gap.items} item(ns) sem resolução ({(100 * p.run.gap.rate).toFixed(1)}%)
          </p>
        </Secao>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------

function BotaoDePaleta({
  nome,
  resumo,
  classe,
  usado,
  onClick,
}: {
  nome: string;
  resumo: string;
  classe: keyof typeof CORES;
  usado: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={usado}
      onClick={onClick}
      // O motivo de estar desabilitado fica no próprio botão:
      // `construir_composicao` recusa bloco repetido porque o segundo rodaria
      // sobre o pool que o primeiro esvaziou.
      title={
        usado
          ? "já está na cascata; o segundo rodaria sobre o pool que o primeiro esvaziou"
          : `acrescentar ${nome}`
      }
      className={[
        "w-full rounded-md border border-borda border-l-[3px] px-2.5 py-1.5 text-left transition",
        "dark:border-noite-borda",
        CORES[classe].bordaEsq,
        usado ? "cursor-not-allowed opacity-40" : "hover:bg-neutral-50 dark:hover:bg-noite-cartao",
      ].join(" ")}
    >
      <span className="flex items-baseline gap-2">
        <span className="text-[12.5px] font-medium">{nome}</span>
        <span className={`ml-auto text-[9.5px] tracking-wider ${CORES[classe].texto}`}>
          {classe}
        </span>
      </span>
      <span className="mt-0.5 block text-[11px] leading-snug text-neutral-500 dark:text-noite-fraca">
        {resumo}
      </span>
    </button>
  );
}

/**
 * O editor do agente. É esta caixa que tira a tela de cardápio.
 *
 * Nenhum campo aqui tem equivalente numa `Receita`: ela carrega nomes do
 * catálogo e um `dict[str, int]` de parâmetros, e um prompt não cabe num `int`.
 * Por isso a composição é um formato novo e não um campo a mais.
 *
 * **A tela não valida.** Quem recusa é `AgenteDeclarado.__post_init__`, e a
 * mensagem dele chega como o 422 que aparece em "Identidade". Uma segunda
 * validação aqui divergiria da primeira, e o sintoma seria a tela barrando algo
 * que o servidor aceita — ou, pior, deixando passar algo que ele recusa.
 */
function EditorDeAgente({
  no,
  dominio,
  onMudar,
  onRemover,
}: {
  no: { id: string; data: DadosAgente };
  dominio: DominioInfo;
  onMudar: (id: string, patch: Partial<AgenteDeclarado>) => void;
  onRemover: (id: string) => void;
}) {
  const a = no.data.declaracao;
  const mudar = (patch: Partial<AgenteDeclarado>) => onMudar(no.id, patch);

  // Os campos que o prompt pode interpolar dependem do payload do item, que só
  // existe na execução. O que a tela PODE dizer é qual erro isso dá: `_units`
  // levanta nomeando o campo que faltou, em vez de mandar um prompt furado.
  const semInterpolacao = a.prompt.length > 0 && !a.prompt.includes("{");

  return (
    <Secao titulo={a.name || "agente"} ajuda="Tudo aqui é dado. Nada vira código.">
      <Campo rotulo="nome">
        <input value={a.name} onChange={(e) => mudar({ name: e.target.value })} className={CAMPO} />
      </Campo>

      <Campo rotulo="kind" dica="que tipo de item este agente trabalha">
        <select
          value={a.kind}
          onChange={(e) => mudar({ kind: e.target.value })}
          className={CAMPO}
        >
          {dominio.kinds.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </Campo>

      <Campo rotulo="system" dica="a instrução permanente; é o que vai marcado para cache">
        <textarea
          value={a.system}
          onChange={(e) => mudar({ system: e.target.value })}
          rows={5}
          className={`${CAMPO} font-mono text-[11px] leading-snug`}
        />
      </Campo>

      <Campo
        rotulo="prompt"
        dica="template sobre o item: {campo} vira o valor do payload"
        alerta={
          semInterpolacao
            ? "não interpola nada: todo item receberia o MESMO texto, e o agente responderia sem ler o item"
            : null
        }
      >
        <textarea
          value={a.prompt}
          onChange={(e) => mudar({ prompt: e.target.value })}
          rows={3}
          placeholder="{titulo}&#10;&#10;{corpo}"
          className={`${CAMPO} font-mono text-[11px] leading-snug`}
        />
      </Campo>

      <Campo rotulo="tipos" dica="vocabulário FECHADO de saída, separado por vírgula">
        <input
          value={a.tipos.join(", ")}
          onChange={(e) =>
            mudar({
              tipos: e.target.value
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean),
            })
          }
          placeholder="BUG, FEATURE, DUVIDA"
          spellCheck={false}
          className={`${CAMPO} font-mono text-[11px]`}
        />
      </Campo>

      <Campo
        rotulo="abstem_com"
        dica="o rótulo de “não sei”. NÃO pode ser um dos tipos"
        alerta={
          a.tipos.includes(a.abstem_com)
            ? `“${a.abstem_com}” é tipo E abstenção: os casos com esse tipo esperado sairiam do denominador da precisão. Custou 16 de 50 casos uma vez`
            : null
        }
      >
        <input
          value={a.abstem_com}
          onChange={(e) => mudar({ abstem_com: e.target.value })}
          spellCheck={false}
          className={`${CAMPO} font-mono text-[11px]`}
        />
      </Campo>

      <Campo
        rotulo="ferramentas"
        dica={
          dominio.ferramentas.length
            ? "o agente recebe as que DECLARA, não as que existem no domínio"
            : "este domínio ainda não publica ferramenta nenhuma"
        }
      >
        <div className="grid gap-1">
          {dominio.ferramentas.map((f) => (
            <label key={f.nome} className="flex items-start gap-2 text-[11.5px]" title={f.descricao}>
              <input
                type="checkbox"
                checked={a.ferramentas.includes(f.nome)}
                onChange={(e) =>
                  mudar({
                    ferramentas: e.target.checked
                      ? [...a.ferramentas, f.nome]
                      : a.ferramentas.filter((n) => n !== f.nome),
                  })
                }
                className="mt-0.5"
              />
              <span className="font-mono text-[11px] text-neutral-600 dark:text-noite-fraca">
                {f.nome}
              </span>
            </label>
          ))}
        </div>
      </Campo>

      {/* O TETO, em duas escalas. `budget_microcents` é o campo porque a
          constraint de dinheiro do projeto proíbe float acumulando; o dólar ao
          lado é derivado, só para leitura. */}
      <Campo rotulo="teto por item (µ¢)" dica={`≈ US$ ${(a.budget_microcents / 1e8).toFixed(4)}`}>
        <input
          type="number"
          value={a.budget_microcents}
          onChange={(e) => mudar({ budget_microcents: parseInt(e.target.value, 10) })}
          className={`${CAMPO} text-right font-mono`}
        />
      </Campo>

      <Campo rotulo="max_turns" dica="quantas idas ao modelo por item, no máximo">
        <input
          type="number"
          value={a.max_turns}
          onChange={(e) => mudar({ max_turns: parseInt(e.target.value, 10) })}
          className={`${CAMPO} text-right font-mono`}
        />
      </Campo>

      <Remover onClick={() => onRemover(no.id)} />
    </Secao>
  );
}

function Campo({
  rotulo,
  dica,
  alerta,
  children,
}: {
  rotulo: string;
  dica?: string;
  alerta?: string | null;
  children: React.ReactNode;
}) {
  return (
    <label className="mb-2.5 block">
      <span className="mb-0.5 block text-[11.5px] text-neutral-600 dark:text-noite-fraca">
        {rotulo}
      </span>
      {children}
      {dica && (
        <span className="mt-0.5 block text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
          {dica}
        </span>
      )}
      {alerta && (
        <span className="mt-1 block rounded bg-lacuna-fundo px-2 py-1 text-[10.5px] leading-snug text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew">
          {alerta}
        </span>
      )}
    </label>
  );
}

function Remover({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-[11.5px] text-red-700 underline hover:text-red-800 dark:text-red-400"
    >
      remover da cascata
    </button>
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
      {ajuda && (
        <p className="mb-2 text-[11px] leading-snug text-neutral-500 dark:text-noite-fraca">
          {ajuda}
        </p>
      )}
      {children}
    </section>
  );
}
