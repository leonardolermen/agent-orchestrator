// O contrato com a API. Os tipos espelham `api/schemas.py` — e espelhar é
// deliberado: um tipo inventado aqui divergiria do servidor sem sintoma, que é
// a mesma classe de erro que um `(e.ferramentas || [])` defensivo produziria.

export type CostClass = "REGRA" | "AGENTE" | "CREW" | "HUMANO";

// A ordem em que a cascata roda. É a MESMA de `CostClass` no kernel, onde o
// valor numérico do IntEnum É a semântica — aqui ela é um array porque o
// TypeScript não tem o enum, e há teste no servidor garantindo a ordem.
export const ORDEM_CLASSE: CostClass[] = ["REGRA", "AGENTE", "CREW", "HUMANO"];

// O que um parametro de regra pode valer. Era `number`, e o `number` era o teto
// de quanto uma regra podia ser configurada: com ele a tela ajusta folga e
// limite, e nada mais. Um bloco GENERICO recebe NOME DE CAMPO — em quais campos
// ele casa —, e nome de campo e texto, quando nao uma lista deles.
export type ValorParametro = number | string | string[];

export interface Parametro {
  nome: string;
  default: ValorParametro;
  descricao: string;
  // Sem isto, um bloco generico apareceria igual a um ja configurado por um
  // dominio, e so recusaria na hora de compor.
  obrigatorio: boolean;
}

export interface Ferramenta {
  nome: string;
  descricao: string;
}

export interface Regra {
  // A IDENTIDADE: e o que a composicao manda e o que o catalogo indexa.
  nome: string;
  cost_class: CostClass;
  resumo: string;
  // Como a paleta chama o bloco e em que secao o poe. Vem do CATALOGO — um
  // de-para aqui seria a segunda fonte de verdade, e um bloco novo entraria sem
  // categoria ou com um rotulo velho.
  rotulo: string;
  categoria: string;
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

// Tudo que dá para compor, SEM agrupamento. Espelha `CatalogoJSON`.
//
// Não há mais partição por domínio: a paleta é o catálogo inteiro, e a garantia
// que o domínio dava — blocos que trabalham o mesmo `kind` — é do grafo, que
// recusa degraus cujos kinds não conectam.
//
// Regra e agente em listas SEPARADAS: o que a tela edita em cada um é
// diferente — regra tem parâmetros, agente tem prompt, vocabulário e
// ferramentas. Uma lista só obrigaria a inspecionar o tipo em cada linha.
export interface Catalogo {
  ferramentas: Ferramenta[];
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

// O que só existe quando a fonte carrega gabarito. Espelha `MedidoJSON`.
export interface Medido {
  seed: number;
  n: number;
  bank_total: number;
  deterministic_rate: number;
}

// Espelha `RunJSON`. Os quatro últimos campos (estado, propostas_por_tipo,
// falhas, teto_atingido) existem para que "não achei nada", "parei no teto" e
// "a API falhou" deixem de ser respostas byte a byte idênticas — a tela que os
// ignorasse recolapsaria os três estados que a Task 4 separou.
export interface Run {
  input_ref: string;
  itens: number;
  resolvidos: number;
  por_resolver: LinhaDeRun[];
  gap: { items: number; rate: number };
  custo_microcents: number;
  estado: string;
  propostas_por_tipo: Record<string, number>;
  falhas: number;
  teto_atingido: boolean;
  // `null` quando a fonte não tem gabarito. A tela DIZ isso — não desenha uma
  // barra vazia nem um zero.
  contra_gabarito: Medido | null;
}

// A fonte de um pedido de execução. Espelha `FonteSintetica`/`FonteArquivo`
// em `schemas.py` — união discriminada por `tipo`, como `BlocoPedido`.
export type FontePedido =
  | { tipo: "sintetica"; seed: number; n: number; taxa_divergencia: number }
  | { tipo: "arquivo"; caminho: string; kind: string; campo_id: string }
  | { tipo: "postgres"; dsn_env: string; query: string; kind: string; campo_id: string }
  | { tipo: "http"; url: string; token_env: string | null; kind: string; campo_id: string; caminho: string };

export interface Receita {
  id: string;
  nome: string;
  justificativa: string;
  resolvers: { nome: string; parametros?: Record<string, ValorParametro> }[];
}

// Um bloco de composição, como o servidor o recebe. UNIÃO DISCRIMINADA por
// `tipo`, espelhando `BlocoJSON` em `schemas.py` — um objeto com
// `parametros?` ao lado de `declaracao?` aceitaria os quatro cruzamentos, dois
// dos quais não significam nada.
export type BlocoPedido =
  | { tipo: "regra"; nome: string; parametros: Record<string, ValorParametro> }
  | { tipo: "agente"; declaracao: AgenteDeclarado }
  // Sem `abstem_com`: o servidor o DERIVA dos agentes, que ja o declaram cada
  // um. Mandar daqui seria a segunda fonte de verdade, e o sintoma seria o
  // Crew chamando de desacordo duas abstencoes.
  | {
      tipo: "crew";
      nome: string;
      agentes: AgenteDeclarado[];
      process: string;
      conflito: string;
    };

export interface ComposicaoResumo {
  id: string;
  nome: string;
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
  // A ÚNICA fonte da paleta. Antes eram duas — esta rota servia o cardápio do
  // grill (só conciliação) e `/api/dominios` servia a paleta particionada, o
  // que obrigava a tela a perguntar o domínio antes de mostrar qualquer bloco.
  catalogo: () => pedir<Catalogo>("/api/catalogo"),

  ambiente: () => pedir<Ambiente>("/api/ambiente"),

  criarReceita: (corpo: {
    id: string;
    nome: string;
    justificativa: string;
    resolvers: { nome: string; parametros: Record<string, ValorParametro> }[];
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
    justificativa: string;
    // ETAPAS, nao uma lista plana. A ordem DENTRO de cada uma e ignorada pelo
    // servidor (ele ordena por custo); a ordem ENTRE elas e significativa.
    //
    // `blocos` continua aceito pelo servidor como o acucar de uma etapa so — a
    // tela nao usa mais, e o grill usa.
    etapas: { nome: string; blocos: BlocoPedido[] }[];
    // Os kinds que SAO a saida do workflow. Declaracao, nao degrau.
    entrega: string[];
  }) =>
    pedir<WorkflowConstruido>("/api/composicoes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(corpo),
    }),

  // `tetoMicrocents` é `null` quando a pessoa não digitou nada — NUNCA um
  // default inventado no cliente. Para workflow pago o servidor recusa com
  // 422 dizendo por quê; é essa mensagem que a tela mostra, não uma própria.
  rodar: (workflowId: string, fonte: FontePedido, tetoMicrocents: number | null) =>
    pedir<Run>(`/api/workflows/${encodeURIComponent(workflowId)}/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ fonte, teto_microcents: tetoMicrocents }),
    }),

  // Os workflows JÁ SALVOS. É o que a vista de execução navega, e é o que a
  // CLI do grill entrega: ela imprime `/?workflow=<id>` como último passo,
  // então esta listagem é o outro lado daquele link.
  workflows: () => pedir<WorkflowResumo[]>("/api/workflows"),

  workflow: (workflowId: string) =>
    pedir<WorkflowConstruido>(`/api/workflows/${encodeURIComponent(workflowId)}`),

  fila: (workflowId: string, dataset: ParametrosDaFila) =>
    pedir<Fila>(
      `/api/fila/${encodeURIComponent(workflowId)}?${queryDoDataset(dataset)}`,
    ),

  // `workflow_id` é segmento de PATH e o dataset é query — a rota é
  // `/api/fila/{workflow_id}`, e a fila é escopada nas DUAS dimensões:
  // `caminho_da_fila(workflow_id, dataset)` toma o workflow primeiro e o
  // `dataset_id(seed, n, taxa)` depois. Mandar uma sem a outra decide na fila
  // errada em silêncio.
  decidir: (
    workflowId: string,
    divergenceId: string,
    dataset: ParametrosDaFila,
    corpo: Decisao,
  ) =>
    pedir<ItemDaFila>(
      `/api/fila/${encodeURIComponent(workflowId)}/${encodeURIComponent(divergenceId)}/decisao?${queryDoDataset(dataset)}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(corpo),
      },
    ),
};

export interface WorkflowResumo {
  id: string;
  nome: string;
  classes: string[];
  gerado_em: string | null;
  // Falso quando a cascata tem classe AGENTE. A tela desabilita a opção em vez
  // de deixar a pessoa colher um 409 — mas quem GARANTE é o servidor.
  executavel: boolean;
}

/** Os três campos que escopam um dataset. Os MESMOS de `RunRequest`. */
export interface ParametrosDaFila {
  seed: number;
  n: number;
  taxa_divergencia: number;
}

function queryDoDataset(d: ParametrosDaFila): string {
  return new URLSearchParams({
    seed: String(d.seed),
    n: String(d.n),
    taxa_divergencia: String(d.taxa_divergencia),
  }).toString();
}

export interface Lancamento {
  id: string;
  lado: string;
  data: string;
  valor: number; // centavos, sempre int — ver `money.py`
  descricao: string;
  contraparte: string;
  documento: string | null;
}

export interface ItemDaFila {
  divergence_id: string;
  tipo: string;
  confianca: string;
  explicacao: string;
  evidencia: string[];
  acao_sugerida: string;
  conciliar_com: string[];
  lancamentos: Lancamento[];
  decidido: boolean;
}

export interface Fila {
  workflow: string;
  dataset: string;
  itens: ItemDaFila[];
  // A taxonomia vem da API, NUNCA de uma lista escrita aqui. Duplicar os
  // valores no front cria drift silencioso no dia em que a taxonomia crescer —
  // o mesmo defeito que a fatia da fila existiu para tornar impossível.
  tipos: string[];
}

export interface Decisao {
  veredito: "aceitar" | "rejeitar" | "corrigir";
  autor: string;
  tipo?: string;
  conciliar_com?: string[];
}

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
//
// O `kind` também nasce VAZIO, e é a mudança do quadro em branco: antes ele
// vinha do domínio escolhido (`dominio.kinds[0]`), que decidia pela pessoa
// sobre que tipo de item o agente trabalha. É o grafo que liga os degraus por
// `kind` — quem monta precisa dizer qual é, e o painel pede.
export function agenteEmBranco(nome: string): AgenteDeclarado {
  return {
    name: nome,
    system: "",
    kind: "",
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
