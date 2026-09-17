import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CORES, type AgenteDeclarado, type CostClass, type Regra } from "./api";

/**
 * Um nó do canvas. Duas naturezas, e a assimetria é a tese do produto.
 *
 * **Regra** é CÓDIGO com parâmetros expostos: o canvas escolhe QUAIS regras
 * entram e com que números, nunca o corpo delas. Casar por documento e valor é
 * lógica de domínio, e uma linguagem declarativa de regras ou fica pela metade
 * ou vira uma linguagem de programação com outro nome.
 *
 * **Agente** é DADO: prompt, vocabulário, ferramentas e orçamento são campos, e
 * é por isso que "acrescente um agente" não exige abrir um editor de Python.
 *
 * O tipo é uma união DISCRIMINADA e não um objeto com campos opcionais: um
 * `parametros?` ao lado de um `prompt?` aceitaria os quatro cruzamentos, dois
 * dos quais não significam nada, e recusá-los viraria validação escrita à mão.
 */
export interface DadosRegra extends Record<string, unknown> {
  tipo: "regra";
  regra: Regra;
  parametros: Record<string, number>;
}

export interface DadosAgente extends Record<string, unknown> {
  tipo: "agente";
  declaracao: AgenteDeclarado;
}

export type DadosDoNo = DadosRegra | DadosAgente;

export function nomeDo(d: DadosDoNo): string {
  return d.tipo === "regra" ? d.regra.nome : d.declaracao.name;
}

// A classe de custo de um agente é sempre AGENTE — `RegraDisponivel` RECUSA
// `cost_class=AGENTE` na construção, então a única fonte de AGENTE no canvas é
// um nó de agente. Isto ordena a PRÉVIA; quem decide de verdade é
// `Stage.ordered()`, e o painel mostra a resposta do servidor ao lado.
export function classeDo(d: DadosDoNo): CostClass {
  return d.tipo === "regra" ? d.regra.cost_class : "AGENTE";
}

const PONTA =
  "!h-1.5 !w-1.5 !border-0 !bg-borda dark:!bg-noite-borda";

/**
 * O cartão no canvas.
 *
 * Os `Handle` são `isConnectable={false}` de propósito, e é a decisão central
 * desta tela: **não há como desenhar uma aresta.** Num editor de fluxo de
 * agentes convencional você liga os nós e a execução tenta seguir o desenho;
 * aqui a seta é SAÍDA — ela vem de `Stage.ordered()`, por classe de custo.
 *
 * Os handles existem só para as arestas derivadas terem onde ancorar. Deixá-los
 * conectáveis daria à pessoa uma ferramenta que não faz nada, e uma ferramenta
 * que não faz nada é pior que ausência: ela promete.
 */
export function NoResolver({ data, selected }: NodeProps) {
  const d = data as DadosDoNo;
  const classe = classeDo(d);
  const cor = CORES[classe];

  return (
    <div
      className={[
        "w-[252px] rounded-lg border border-borda border-t-[3px] bg-white",
        "dark:border-noite-borda dark:bg-noite-cartao",
        "shadow-sm transition-shadow",
        cor.bordaTopo,
        selected ? "ring-2 ring-tinta/15 shadow-lg dark:ring-noite-tinta/20" : "hover:shadow-md",
      ].join(" ")}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} className={PONTA} />

      <div className="px-3 pt-2.5 pb-2">
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-semibold text-tinta dark:text-noite-tinta">
            {nomeDo(d)}
          </span>
          <span className={`ml-auto text-[10px] font-medium tracking-wider ${cor.texto}`}>
            {classe}
          </span>
        </div>
        {/* `line-clamp-2` no agente: o `system` é um prompt inteiro, e sem corte
            o cartão virava uma parede de texto de meia tela — visto na tela,
            não em teste. O texto completo fica no editor, que é onde ele se
            edita. O resumo de uma regra já é uma linha e não precisa de corte. */}
        <p
          className={[
            "mt-1 text-[11.5px] leading-snug text-neutral-600 dark:text-noite-fraca",
            d.tipo === "agente" ? "line-clamp-2" : "",
          ].join(" ")}
          title={d.tipo === "agente" ? d.declaracao.system : undefined}
        >
          {d.tipo === "regra" ? d.regra.resumo : d.declaracao.system || "sem instrução ainda"}
        </p>
      </div>

      {d.tipo === "regra" ? <CorpoRegra d={d} /> : <CorpoAgente d={d} />}

      <Handle type="source" position={Position.Bottom} isConnectable={false} className={PONTA} />
    </div>
  );
}

const LINHA =
  "flex items-center gap-2 border-t border-neutral-100 px-3 py-1.5 dark:border-noite-borda";

function CorpoRegra({ d }: { d: DadosRegra }) {
  if (d.regra.parametros.length === 0) return null;
  return (
    <div className="border-t border-neutral-100 px-3 py-1.5 dark:border-noite-borda">
      {d.regra.parametros.map((p) => (
        <div key={p.nome} className="flex items-baseline gap-2 font-mono text-[10.5px]">
          <span className="text-neutral-400 dark:text-noite-fraca">{p.nome}</span>
          <span className="ml-auto text-tinta dark:text-noite-tinta">{d.parametros[p.nome]}</span>
        </div>
      ))}
    </div>
  );
}

function CorpoAgente({ d }: { d: DadosAgente }) {
  const a = d.declaracao;
  return (
    <>
      <div className={LINHA} title="que tipo de item este agente trabalha">
        <span className="text-[11px] text-neutral-300 dark:text-noite-fraca">◇</span>
        {/* Um `kind` vazio é DITO, como "sem instrução ainda" acima. Ele nasce
            vazio desde que a paleta deixou de ser por domínio — não há mais de
            onde adivinhá-lo —, e um espaço em branco aqui seria o campo que
            falta escondido no lugar mais visível da tela. */}
        <span
          className={`font-mono text-[11px] ${
            a.kind ? "text-tinta dark:text-noite-tinta" : "text-lacuna dark:text-noite-crew"
          }`}
        >
          {a.kind || "sem kind ainda"}
        </span>
        <span className="ml-auto text-[9.5px] uppercase tracking-wide text-neutral-400 dark:text-noite-fraca">
          kind
        </span>
      </div>

      {a.ferramentas.map((f) => (
        <div key={f} className={LINHA}>
          <span className="text-[11px] text-neutral-300 dark:text-noite-fraca">⚒</span>
          <span className="text-[11px] text-neutral-600 dark:text-noite-fraca">{f}</span>
        </div>
      ))}

      {/* O VOCABULÁRIO fechado, com a abstenção destacada. Ela aparece separada
          porque a diferença entre "é uma dúvida" e "não sei classificar" já
          custou um terço de um conjunto de avaliação (P6.86) — e a tela é onde
          alguém está prestes a colidir os dois de novo. */}
      <div className="border-t border-neutral-100 px-3 py-1.5 dark:border-noite-borda">
        {a.tipos.length === 0 ? (
          <span className="text-[10.5px] text-lacuna dark:text-noite-crew">
            sem vocabulário — não compõe ainda
          </span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {a.tipos.map((t) => (
              <span
                key={t}
                className="rounded bg-neutral-100 px-1.5 py-px font-mono text-[9.5px] text-neutral-600 dark:bg-noite-fundo dark:text-noite-fraca"
              >
                {t}
              </span>
            ))}
            <span
              title="o rótulo de “não sei” deste agente; não é um tipo"
              className="rounded border border-dashed border-neutral-300 px-1.5 py-px font-mono text-[9.5px] text-neutral-400 dark:border-noite-borda dark:text-noite-fraca"
            >
              {a.abstem_com}
            </span>
          </div>
        )}
      </div>

      {/* O TETO. Um agente sem teto é um agente que gasta até o fim da fila, e
          essa é a linha que separa "caro" de "sem controle". */}
      <div className="flex items-baseline gap-2 border-t border-neutral-100 px-3 py-1.5 font-mono text-[10.5px] dark:border-noite-borda">
        <span className="text-neutral-400 dark:text-noite-fraca">teto/item</span>
        <span className="ml-auto text-tinta dark:text-noite-tinta">
          US$ {(a.budget_microcents / 1e8).toFixed(4)}
        </span>
        <span className="text-neutral-300 dark:text-noite-fraca">· {a.max_turns} turnos</span>
      </div>
    </>
  );
}
