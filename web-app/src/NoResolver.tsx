import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  CORES,
  type AgenteDeclarado,
  type CostClass,
  type Regra,
  type TarefaDeclarada,
  type ValorParametro,
} from "./api";

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
  parametros: Record<string, ValorParametro>;
  // Em qual ETAPA este bloco roda. Indice, nao nome: renomear uma etapa nao
  // pode mover bloco nenhum.
  //
  // Mora no no e nao numa tabela `Map<noId, etapa>` ao lado porque a segunda
  // ficaria dessincronizada no dia em que um no fosse removido — e o sintoma
  // seria um bloco numa etapa que nao existe mais.
  etapa: number;
}

export interface DadosAgente extends Record<string, unknown> {
  tipo: "agente";
  declaracao: AgenteDeclarado;
  etapa: number;
}

/** Uma TRIPULACAO: varios agentes sobre o mesmo item, com politica de conflito.
 *
 *  Como `DadosAgente`, ela e DADO — o time e criado na tela, nao escolhido de
 *  um cardapio. Sem `abstem_com`: ele sai dos agentes, que ja o declaram cada
 *  um, e perguntar de novo faria o Crew chamar de desacordo duas abstencoes. */
export interface DadosCrew extends Record<string, unknown> {
  tipo: "crew";
  nome: string;
  agentes: AgenteDeclarado[];
  process: string;
  conflito: string;
  etapa: number;
}

/** Uma TAREFA: consome um kind e produz outro, e o texto do modelo vira o item
 *  do degrau seguinte.
 *
 *  Separada de `DadosAgente` e nao um `produz?` dentro dele, pelo mesmo motivo
 *  que o bloco e um quarto tipo no servidor: com `produz` preenchido, `tipos` e
 *  `abstem_com` deixam de significar qualquer coisa, e um no com os tres seria
 *  metade dos campos ignorada em silencio conforme outro campo. */
export interface DadosTarefa extends Record<string, unknown> {
  tipo: "tarefa";
  declaracao: TarefaDeclarada;
  etapa: number;
}

export type DadosDoNo = DadosRegra | DadosAgente | DadosCrew | DadosTarefa;

/** O que se LE no no. Diferente de `nomeDo`, que e IDENTIDADE.
 *
 *  A paleta chama o bloco de "Condition" e o no do canvas o chamava de
 *  "condicao" — o mesmo bloco com dois nomes na mesma tela. Duas funcoes
 *  separadas porque as duas perguntas sao diferentes: `usados` precisa saber se
 *  este bloco JA ESTA no workflow (identidade), e o no precisa saber como
 *  escreve-lo (rotulo). Uma funcao so, usada nos dois lugares, faria o
 *  `usados` comparar rotulos e deixaria passar o mesmo bloco duas vezes. */
export function rotuloDo(d: DadosDoNo): string {
  if (d.tipo === "regra") return d.regra.rotulo || d.regra.nome;
  if (d.tipo === "crew") return d.nome;
  // Agente e tarefa caem no mesmo `return`: as duas declaracoes chamam o campo
  // de `name`. Um ramo a mais para a tarefa seria a quarta copia da mesma
  // leitura.
  return d.declaracao.name;
}

export function nomeDo(d: DadosDoNo): string {
  if (d.tipo === "regra") return d.regra.nome;
  if (d.tipo === "crew") return d.nome;
  return d.declaracao.name;
}

// A classe de custo de um agente é sempre AGENTE — `RegraDisponivel` RECUSA
// `cost_class=AGENTE` na construção, então a única fonte de AGENTE no canvas é
// um nó de agente. Isto ordena a PRÉVIA; quem decide de verdade é
// `Stage.ordered()`, e o painel mostra a resposta do servidor ao lado.
export function classeDo(d: DadosDoNo): CostClass {
  if (d.tipo === "regra") return d.regra.cost_class;
  // CREW e MAIS caro que AGENTE, e por isso roda depois: sao varios agentes
  // sobre o mesmo item. Dizer "AGENTE" aqui poria a tripulacao antes de um
  // agente sozinho na previa, contradizendo o servidor.
  if (d.tipo === "crew") return "CREW";
  // Tarefa e classe AGENTE tambem, e nao uma classe propria: ela CHAMA O
  // MODELO, que e o que a classe mede. `Tarefa.cost_class` no kernel diz o
  // mesmo, e uma classe nova aqui poria a previa em desacordo com a ordem que
  // `Stage.ordered()` aplica de verdade.
  return "AGENTE";
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
            {rotuloDo(d)}
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
            d.tipo === "agente" || d.tipo === "tarefa" ? "line-clamp-2" : "",
          ].join(" ")}
          title={
            d.tipo === "agente" || d.tipo === "tarefa" ? d.declaracao.system : undefined
          }
        >
          {d.tipo === "regra"
            ? d.regra.resumo
            : d.tipo === "crew"
              ? `${d.agentes.length} agente(s) sobre o mesmo item`
              : d.declaracao.system || "sem instrução ainda"}
        </p>
      </div>

      {d.tipo === "regra" ? (
        <CorpoRegra d={d} />
      ) : d.tipo === "crew" ? (
        <CorpoCrew d={d} />
      ) : d.tipo === "tarefa" ? (
        <CorpoTarefa d={d} />
      ) : (
        <CorpoAgente d={d} />
      )}

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

function CorpoCrew({ d }: { d: DadosCrew }) {
  return (
    <div className="border-t border-neutral-100 px-3 py-1.5 text-[10.5px] leading-snug text-neutral-500 dark:border-noite-borda dark:text-noite-fraca">
      <div>{d.agentes.map((a) => a.name).join(", ") || "sem agente"}</div>
      <div className="mt-0.5 font-mono text-[10px]">
        {d.process} · conflito: {d.conflito}
      </div>
    </div>
  );
}

/** O corpo de uma TAREFA. A linha de cima e `kind -> produz`, e ela e a razao
 *  de este cartao existir separado do agente: e a UNICA informacao do bloco que
 *  diz a quem ele entrega. Num agente nao ha o que desenhar ali — ele propoe, e
 *  a proposta nao vira item de ninguem.
 *
 *  Vocabulario e abstencao nao aparecem porque nao existem: nao transformar e a
 *  ausencia de resolucao, e ausencia nao tem rotulo. */
function CorpoTarefa({ d }: { d: DadosTarefa }) {
  const t = d.declaracao;
  return (
    <>
      <div className={LINHA} title="o que esta tarefa consome e o que ela entrega ao degrau seguinte">
        <span className="text-[11px] text-neutral-300 dark:text-noite-fraca">◇</span>
        <span
          className={`font-mono text-[11px] ${
            t.kind ? "text-tinta dark:text-noite-tinta" : "text-lacuna dark:text-noite-crew"
          }`}
        >
          {t.kind || "sem kind"}
        </span>
        <span className="text-[11px] text-neutral-300 dark:text-noite-fraca">→</span>
        {/* `produz` vazio e DITO, como o kind: sem ele a tarefa consumiria o
            item sem entregar a ninguem — o item sumiria do run, e para
            descartar de proposito existe o `filtro`. O servidor recusa; a tela
            diz antes. */}
        <span
          className={`font-mono text-[11px] ${
            t.produz ? "text-tinta dark:text-noite-tinta" : "text-lacuna dark:text-noite-crew"
          }`}
        >
          {t.produz || "sem produz"}
        </span>
      </div>

      {t.ferramentas.map((f) => (
        <div key={f} className={LINHA}>
          <span className="text-[11px] text-neutral-300 dark:text-noite-fraca">⚒</span>
          <span className="text-[11px] text-neutral-600 dark:text-noite-fraca">{f}</span>
        </div>
      ))}

      <div className="flex items-baseline gap-2 border-t border-neutral-100 px-3 py-1.5 font-mono text-[10.5px] dark:border-noite-borda">
        <span className="text-neutral-400 dark:text-noite-fraca">teto/item</span>
        <span className="ml-auto text-tinta dark:text-noite-tinta">
          US$ {(t.budget_microcents / 1e8).toFixed(4)}
        </span>
        <span className="text-neutral-300 dark:text-noite-fraca">· {t.max_turns} turnos</span>
      </div>
    </>
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
