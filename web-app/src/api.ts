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

  rodar: (workflowId: string, seed = 1, n = 300) =>
    pedir<Run>(`/api/workflows/${encodeURIComponent(workflowId)}/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ seed, n }),
    }),
};

export function ordemDeExecucao<T extends { cost_class: CostClass }>(itens: T[]): T[] {
  // `Array.prototype.sort` é estável desde o ES2019 e `sorted()` do Python
  // também é — os dois concordam sem ninguém combinar. Mas quem garante a ordem
  // é o SERVIDOR: `test_a_ordem_enviada_e_IGNORADA` compara contra o que ele
  // devolve, nunca contra esta função.
  return [...itens].sort(
    (a, b) => ORDEM_CLASSE.indexOf(a.cost_class) - ORDEM_CLASSE.indexOf(b.cost_class),
  );
}

export const CORES: Record<CostClass, { borda: string; texto: string; fundo: string }> = {
  REGRA: { borda: "border-t-regra", texto: "text-regra", fundo: "bg-regra" },
  AGENTE: { borda: "border-t-agente", texto: "text-agente", fundo: "bg-agente" },
  CREW: { borda: "border-t-crew", texto: "text-crew", fundo: "bg-crew" },
  HUMANO: { borda: "border-t-humano", texto: "text-humano", fundo: "bg-humano" },
};
