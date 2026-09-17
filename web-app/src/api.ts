// O contrato com a API. Os tipos espelham `api/schemas.py` — e espelhar é
// deliberado: um tipo inventado aqui divergiria do servidor sem sintoma, que é
// a mesma classe de erro que um `(e.ferramentas || [])` defensivo produziria.

export type CostClass = "REGRA" | "AGENTE" | "CREW" | "HUMANO";

// A ordem em que a cascata roda. É a MESMA de `CostClass` no kernel, onde o
// valor numérico do IntEnum É a semântica — aqui ela é um array porque o
// TypeScript não tem o enum, e há teste no servidor garantindo a ordem.
export const ORDEM_CLASSE: CostClass[] = ["REGRA", "AGENTE", "CREW", "HUMANO"];

export interface Parametro {
  nome: string;
  default: number;
  descricao: string;
}

export interface EntradaCatalogo {
  nome: string;
  cost_class: CostClass;
  resumo: string;
  parametros: Parametro[];
  ferramentas: string[];
  // `null` para resolver determinístico. A ausência é usada para NÃO desenhar
  // uma linha de modelo onde não houve escolha de modelo.
  modelo_padrao: string | null;
}

export interface Ferramenta {
  nome: string;
  descricao: string;
}

export interface Regra {
  nome: string;
  cost_class: CostClass;
  resumo: string;
  parametros: Parametro[];
}

export interface AgenteDeclarado {
  name: string;
  system: string;
  kind: string;
  prompt: string;
  tipos: string[];
  abstem_com: string;
  ferramentas: string[];
  max_turns: number;
  budget_microcents: number;
}

export interface DominioInfo {
  id: string;
  nome: string;
  kinds: string[];
  ferramentas: Ferramenta[];
  // Regra e agente em listas SEPARADAS: o que a tela edita em cada um é
  // diferente — regra tem parâmetros, agente tem prompt, vocabulário e
  // ferramentas. Uma lista só obrigaria a inspecionar o tipo em cada linha.
  regras: Regra[];
  agentes: AgenteDeclarado[];
}

export interface ResolverConstruido {
  name: string;
  cost_class: CostClass;
  summary: string;
}

export interface WorkflowConstruido {
  id: string;
  name: string;
  stages: { name: string; cascade: ResolverConstruido[] }[];
}

export interface LinhaDeRun {
  name: string;
  cost_class: CostClass;
  matches: number;
  rate: number;
  microcents: number;
}

export interface Run {
  seed: number;
  n: number;
  bank_total: number;
  deterministic_rate: number;
  by_resolver: LinhaDeRun[];
  gap: { items: number; rate: number };
}

export interface Receita {
  id: string;
  nome: string;
  justificativa: string;
  resolvers: { nome: string; parametros?: Record<string, number> }[];
}

// Um bloco de composição, como o servidor o recebe. UNIÃO DISCRIMINADA por
// `tipo`, espelhando `BlocoJSON` em `schemas.py` — um objeto com
// `parametros?` ao lado de `declaracao?` aceitaria os quatro cruzamentos, dois
// dos quais não significam nada.
export type BlocoPedido =
  | { tipo: "regra"; nome: string; parametros: Record<string, number> }
  | { tipo: "agente"; declaracao: AgenteDeclarado };

export interface ComposicaoResumo {
  id: string;
  nome: string;
  dominio: string;
  version: string;
  gerado_em: string;
  // NOMES e não contagem: "3 blocos" não distingue uma cascata que começa numa
  // regra barata de uma que começa direto no modelo.
  blocos: string[];
}

export interface Ambiente {
  modelo_padrao: string;
  // Booleano de propósito. A tela precisa saber se a entrevista vai funcionar,
  // e não precisa — nunca — do valor da chave.
  tem_chave: boolean;
  seed: number;
  n: number;
  n_max: number;
  taxa_divergencia: number;
}

export class ErroDaApi extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

// A mensagem do DOMÍNIO, não uma genérica. `construir` escreve erros para serem
// lidos — o grill depende disso para o modelo se corrigir, e a pessoa merece o
// mesmo texto.
async function erroDe(r: Response): Promise<ErroDaApi> {
  const corpo = await r.json().catch(() => ({}) as Record<string, unknown>);
  const d = (corpo as { detail?: unknown }).detail;
  if (typeof d === "string") return new ErroDaApi(d, r.status);
  if (Array.isArray(d) && d.length) {
    const primeiro = d[0] as { msg?: string };
    return new ErroDaApi(primeiro.msg ?? JSON.stringify(d[0]), r.status);
  }
  return new ErroDaApi(`erro ${r.status}`, r.status);
}

async function pedir<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw await erroDe(r);
  return (await r.json()) as T;
}

export const api = {
  catalogo: () => pedir<EntradaCatalogo[]>("/api/catalogo"),

  ambiente: () => pedir<Ambiente>("/api/ambiente"),

  // A PRIMEIRA pergunta da tela. Antes ela não existia: a paleta era o
  // catálogo do grill — o cardápio da conciliação — e por isso o canvas só
  // ofereceu blocos de conciliação até alguém perguntar por quê.
  dominios: () => pedir<DominioInfo[]>("/api/dominios"),

  criarReceita: (corpo: {
    id: string;
    nome: string;
    justificativa: string;
    resolvers: { nome: string; parametros: Record<string, number> }[];
  }) =>
    pedir<WorkflowConstruido>("/api/receitas", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(corpo),
    }),

  composicoes: () => pedir<ComposicaoResumo[]>("/api/composicoes"),

  // O irmão de `criarReceita` para o formato GERAL. A diferença que importa
  // está no corpo: uma receita é uma lista de nomes do catálogo; uma composição
  // carrega o agente INTEIRO, porque esse agente não existe em catálogo nenhum
  // até a pessoa criá-lo aqui.
  criarComposicao: (corpo: {
    id: string;
    nome: string;
    dominio: string;
    justificativa: string;
    blocos: BlocoPedido[];
  }) =>
    pedir<WorkflowConstruido>("/api/composicoes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(corpo),
    }),

  rodar: (workflowId: string, ambiente: Pick<Ambiente, "seed" | "n" | "taxa_divergencia">) =>
    pedir<Run>(`/api/workflows/${encodeURIComponent(workflowId)}/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        seed: ambiente.seed,
        n: ambiente.n,
        taxa_divergencia: ambiente.taxa_divergencia,
      }),
    }),
};

// Um agente em branco. É o que transforma a paleta de "escolha um pronto" em
// "crie um" — e é o pedido do dono: uma plataforma geral, não um cardápio.
//
// Os campos saem VAZIOS de propósito, e a tela mostra a recusa do servidor até
// serem preenchidos. Semear `tipos: ["TIPO_A", "TIPO_B"]` para a composição
// passar produziria um agente que compõe, roda, gasta e classifica em
// vocabulário inventado — a mesma classe de falha silenciosa que
// `ToolRegistry.ligado` existe para impedir.
//
// Os números NÃO saem vazios: `max_turns` e o orçamento têm default no
// servidor, e um agente sem teto é um agente que gasta até o fim da fila.
export function agenteEmBranco(nome: string, kind: string): AgenteDeclarado {
  return {
    name: nome,
    system: "",
    kind,
    prompt: "",
    tipos: [],
    abstem_com: "NAO_SEI",
    ferramentas: [],
    max_turns: 3,
    budget_microcents: 4_000_000,
  };
}

export function ordemDeExecucao<T extends { cost_class: CostClass }>(itens: T[]): T[] {
  // `Array.prototype.sort` é estável desde o ES2019 e `sorted()` do Python
  // também é — os dois concordam sem ninguém combinar. Mas quem garante a ordem
  // é o SERVIDOR: `test_a_ordem_enviada_e_IGNORADA` compara contra o que ele
  // devolve, nunca contra esta função.
  return [...itens].sort(
    (a, b) => ORDEM_CLASSE.indexOf(a.cost_class) - ORDEM_CLASSE.indexOf(b.cost_class),
  );
}

// As classes de cor, LITERAIS. O Tailwind varre o código-fonte procurando
// nomes de classe; montar `` `border-t-${cor}` `` em tempo de execução produz
// uma classe que ele nunca vê e portanto nunca gera. Já custou uma tela sem
// cor nenhuma em projeto que fez isso.
//
// `bordaTopo` e `bordaEsq` são campos separados em vez de um `.replace()`: com
// duas classes por tema (clara + `dark:`), a substituição de string trocaria só
// a primeira e a variante escura sairia na borda errada.
export const CORES: Record<
  CostClass,
  { bordaTopo: string; bordaEsq: string; texto: string; minimapa: string }
> = {
  REGRA: {
    bordaTopo: "border-t-regra dark:border-t-noite-regra",
    bordaEsq: "border-l-regra dark:border-l-noite-regra",
    texto: "text-regra dark:text-noite-regra",
    minimapa: "#5cc48a",
  },
  AGENTE: {
    bordaTopo: "border-t-agente dark:border-t-noite-agente",
    bordaEsq: "border-l-agente dark:border-l-noite-agente",
    texto: "text-agente dark:text-noite-agente",
    minimapa: "#e0a447",
  },
  CREW: {
    bordaTopo: "border-t-crew dark:border-t-noite-crew",
    bordaEsq: "border-l-crew dark:border-l-noite-crew",
    texto: "text-crew dark:text-noite-crew",
    minimapa: "#d4b256",
  },
  HUMANO: {
    bordaTopo: "border-t-humano dark:border-t-noite-humano",
    bordaEsq: "border-l-humano dark:border-l-noite-humano",
    texto: "text-humano dark:text-noite-humano",
    minimapa: "#6ba4e8",
  },
};
