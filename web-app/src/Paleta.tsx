import { useState } from "react";
import type { AgenteDeclarado, Catalogo, Regra } from "./api";

/**
 * A paleta de blocos, agrupada e recolhivel.
 *
 * **Por que os blocos que NAO existem aparecem.** Eles aparecem DESABILITADOS,
 * com o motivo no tooltip, e nao sao clicaveis. A alternativa era mostrar so os
 * sete que funcionam — mais honesto por omissao, e pior: some a forma do
 * produto, e ninguem sabe se `Loop` nao existe ou se esta escondido em algum
 * lugar. Um bloco cinza dizendo "ainda nao construido: <motivo>" responde as
 * duas coisas.
 *
 * O que nao pode e um bloco planejado PARECER clicavel. Por isso eles nao tem
 * hover, nao tem borda de classe de custo, e o `disabled` e real e nao visual.
 *
 * **A categoria vem do SERVIDOR.** `Regra.categoria` e `Regra.rotulo` sao
 * campos do catalogo. Uma tabela de-para aqui seria a segunda fonte de verdade
 * de sempre, e o sintoma dela e um bloco novo aparecendo sem categoria — ou
 * com um rotulo que envelheceu.
 */

/** Um bloco que nao esta na paleta, e a razao disso.
 *
 *  Duas razoes MUITO diferentes, e confundi-las seria mentir nas duas direcoes:
 *
 *    "soon"  — nao foi construido. O tooltip diz o que falta.
 *    "ja"    — EXISTE, em outra forma. `Parallel` e `Merge` nao sao blocos
 *              neste motor: sao a FORMA do grafo (um bloco que ramifica mais um
 *              degrau por ramo), e ha teste provando que funcionam hoje. Um
 *              "bloco Parallel" nao teria o que fazer alem de existir no
 *              desenho, que e a definicao de decoracao. */
interface Planejado {
  rotulo: string;
  icone: string;
  porque: string;
  marca?: "soon" | "ja";
}

interface Grupo {
  id: string;
  titulo: string;
  ajuda?: string;
  planejados: Planejado[];
}

// A ordem e a do desenho do dono, com duas secoes que o motor exige e o desenho
// nao tinha:
//
//   MATCHING — casar dois lados e o que este runtime faz de diferente. Nao cabe
//              em CONTROL (nao ramifica) nem em COMPUTE (nao transforma): ele
//              RESOLVE, que e o verbo que o pool entende.
//   DOMAIN   — os blocos ja configurados por um dominio (L1/L2/L3, compras).
//              Sao exemplos vivos, e misturados com as pecas genericas fariam
//              a paleta parecer um cardapio de novo.
const GRUPOS: Grupo[] = [
  {
    id: "WORKFLOW",
    titulo: "Workflow",
    planejados: [
      { rotulo: "Trigger", icone: "⚡", porque: "não há porta de entrada por evento: um run começa pela API ou pela CLI" },
      { rotulo: "Input", icone: "📥", porque: "a fonte é escolhida na tela de execução, não aqui" },
      {
        rotulo: "Output",
        icone: "📤",
        marca: "ja",
        porque:
          "é o campo `entrega`, em Identidade. Nada roda nele, então não é um nó — e com mais de uma etapa ele só é preciso quando o último ramo não tem degrau depois",
      },
    ],
  },
  {
    id: "CONTROL",
    titulo: "Control",
    ajuda: "Ramificar é produzir um kind; o degrau que o consome só roda quando houver item dele.",
    planejados: [
      {
        rotulo: "Parallel",
        icone: "⇉",
        marca: "ja",
        porque:
          "não é um bloco: é a forma do grafo. Um bloco que ramifica produz dois kinds, e um degrau por ramo consome um cada — os dois rodam. Há teste",
      },
      {
        rotulo: "Merge",
        icone: "⊕",
        marca: "ja",
        porque:
          "também não é bloco: é um degrau cujo `consome` tem os dois lados. Os itens que vieram por caminhos diferentes se encontram nele. Há teste",
      },
      {
        rotulo: "Loop",
        icone: "↻",
        marca: "ja",
        porque:
          "é o campo `rondas`, em Identidade. Nada roda dentro dele: é quantas vezes a SEQUÊNCIA de etapas pode rodar, para aresta de volta. E é teto — o motor para sozinho quando uma ronda não muda nada",
      },
      { rotulo: "Wait", icone: "⏸", porque: "não há suspensão: uma execução roda até o fim" },
    ],
  },
  {
    id: "COMPUTE",
    titulo: "Compute",
    planejados: [
      { rotulo: "Code", icone: "ƒ", porque: "executar código da tela no servidor é RCE por desenho. Precisa de sandbox, e isso é decisão própria" },
      { rotulo: "Transform", icone: "⇄", porque: "payload é dataclass congelada: enriquecer obriga a virar dict, e todo bloco tipado depois quebraria em silêncio" },
    ],
  },
  {
    id: "MATCHING",
    titulo: "Matching",
    ajuda: "Casar dois lados. É o que este runtime faz antes de chamar qualquer modelo.",
    planejados: [],
  },
  { id: "AI", titulo: "AI", planejados: [
      { rotulo: "Agent Router", icone: "🧠", porque: "não construído" },
  ] },
  {
    id: "INTEGRATIONS",
    titulo: "Integrations",
    planejados: [
      { rotulo: "Tool", icone: "🔧", porque: "ferramenta hoje só existe dentro de um agente, não como bloco solto" },
      { rotulo: "HTTP", icone: "🌐", porque: "existe como FONTE de entrada, não como degrau no meio" },
      { rotulo: "Database", icone: "🗄", porque: "idem: Postgres é fonte, ainda não é bloco" },
      { rotulo: "MCP", icone: "🔌", porque: "não construído" },
    ],
  },
  {
    id: "HUMAN",
    titulo: "Human",
    ajuda: "O agente propõe; quem decide é aqui.",
    planejados: [
      { rotulo: "Human Input", icone: "👤", porque: "não construído" },
      { rotulo: "Decision", icone: "⚖", porque: "existe como tipo (`Decision`) e como fila, mas não como bloco da paleta" },
    ],
  },
  {
    id: "DATA",
    titulo: "Data",
    planejados: [
      { rotulo: "Context", icone: "📦", porque: "o pool é o estado: não há variável compartilhada" },
      { rotulo: "Variable", icone: "💾", porque: "idem" },
      { rotulo: "Memory", icone: "🧠", porque: "não construído" },
      { rotulo: "Artifact", icone: "📄", porque: "não construído" },
    ],
  },
  { id: "COMPOSITE", titulo: "Composite", planejados: [
      { rotulo: "Subworkflow", icone: "🧩", porque: "o `Stage` já aninha por dentro; falta expor" },
  ] },
  {
    id: "DOMAIN",
    titulo: "Domain",
    ajuda: "Blocos já configurados por um domínio. Exemplos vivos, não peças genéricas.",
    planejados: [],
  },
];

// Um icone por bloco do catalogo, pelo NOME de identidade. Mora aqui e nao no
// servidor porque e puramente visual — e porque um bloco sem icone cai no
// neutro sem quebrar nada, diferente de um bloco sem categoria.
const ICONES: Record<string, string> = {
  condicao: "◆",
  tabela: "◇",
  filtro: "⊂",
  validacao: "✓",
  igualdade: "=",
  tolerancia: "≈",
  agrupamento: "Σ",
  revisor: "✅",
  L1: "=",
  L2: "≈",
  L3: "Σ",
  preferido: "★",
  anteriores: "↩",
};

const CLASSE_COR: Record<string, string> = {
  REGRA: "text-regra dark:text-noite-regra",
  AGENTE: "text-agente dark:text-noite-agente",
  CREW: "text-crew dark:text-noite-crew",
  HUMANO: "text-humano dark:text-noite-humano",
};

function Bloco({
  icone,
  rotulo,
  resumo,
  classe,
  usado,
  onClick,
}: {
  icone: string;
  rotulo: string;
  resumo: string;
  classe: string;
  usado: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={usado}
      onClick={onClick}
      title={
        usado
          ? "já está no workflow; o segundo rodaria sobre o pool que o primeiro esvaziou"
          : resumo
      }
      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12.5px] transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-noite-cartao"
    >
      <span className={`w-4 shrink-0 text-center text-[12px] ${CLASSE_COR[classe] ?? ""}`}>
        {icone}
      </span>
      <span className="truncate">{rotulo}</span>
    </button>
  );
}

function BlocoPlanejado({ b }: { b: Planejado }) {
  const ja = b.marca === "ja";
  return (
    <div
      title={ja ? `já existe — ${b.porque}` : `ainda não construído — ${b.porque}`}
      className={[
        "flex w-full cursor-help items-center gap-2 rounded px-2 py-1.5 text-left text-[12.5px]",
        // Quem JA EXISTE nao fica tao apagado quanto quem nao foi construido: a
        // diferenca entre "nao da" e "da, de outro jeito" precisa se ver sem
        // passar o mouse.
        ja
          ? "text-neutral-400 dark:text-noite-fraca"
          : "text-neutral-300 dark:text-noite-fraca/50",
      ].join(" ")}
    >
      <span className="w-4 shrink-0 text-center text-[12px]">{b.icone}</span>
      <span className="truncate">{b.rotulo}</span>
      <span className="ml-auto shrink-0 text-[9.5px] uppercase tracking-wide">
        {ja ? "existe" : "soon"}
      </span>
    </div>
  );
}

export function Paleta({
  catalogo,
  usados,
  onAcrescentarRegra,
  onAcrescentarAgente,
  onNovoAgente,
  onNovoTime,
}: {
  catalogo: Catalogo | null;
  usados: Set<string>;
  onAcrescentarRegra: (r: Regra) => void;
  onAcrescentarAgente: (a: AgenteDeclarado) => void;
  onNovoAgente: () => void;
  onNovoTime: () => void;
}) {
  // Aberto por default so onde ha bloco utilizavel: a paleta inteira aberta
  // seria uma parede de cinza, e a maioria do que existe hoje esta em quatro
  // secoes.
  const comBlocos = new Set(
    (catalogo?.regras ?? []).map((r) => r.categoria).concat(catalogo?.agentes.length ? ["AI"] : []),
  );

  // O estado guarda o que a PESSOA alternou, nao o que esta aberto.
  //
  // Guardar "fechados" com um inicializador de `useState` parecia mais simples
  // e estava errado: o inicializador roda no PRIMEIRO render, quando o catalogo
  // ainda e `null` porque a busca nao voltou — entao nenhuma secao tinha bloco,
  // todas nasciam fechadas, e a paleta abria como uma lista de titulos. O
  // default precisa ser DERIVADO a cada render, para acompanhar o catalogo
  // chegando.
  const [alternados, setAlternados] = useState<Set<string>>(new Set());
  const aberto = (id: string) => comBlocos.has(id) !== alternados.has(id);

  const alternar = (id: string) =>
    setAlternados((atuais) => {
      const novo = new Set(atuais);
      if (!novo.delete(id)) novo.add(id);
      return novo;
    });

  return (
    <div className="mb-5">
      {GRUPOS.map((g) => {
        const regras = (catalogo?.regras ?? []).filter((r) => r.categoria === g.id);
        const agentes = g.id === "AI" ? (catalogo?.agentes ?? []) : [];
        const quantos = regras.length + agentes.length;

        return (
          <section key={g.id} className="border-b border-neutral-100 last:border-0 dark:border-noite-borda">
            <button
              type="button"
              onClick={() => alternar(g.id)}
              className="flex w-full items-center gap-2 py-2 text-left"
            >
              <span className="text-[9px] text-neutral-400 dark:text-noite-fraca">
                {aberto(g.id) ? "▾" : "▸"}
              </span>
              <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-neutral-500 dark:text-noite-fraca">
                {g.titulo}
              </span>
              {quantos > 0 && (
                <span className="ml-auto text-[10px] text-neutral-400 dark:text-noite-fraca">
                  {quantos}
                </span>
              )}
            </button>

            {aberto(g.id) && (
              <div className="pb-2">
                {g.ajuda && (
                  <p className="mb-1.5 px-2 text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
                    {g.ajuda}
                  </p>
                )}
                {regras.map((r) => (
                  <Bloco
                    key={r.nome}
                    icone={ICONES[r.nome] ?? "▪"}
                    rotulo={r.rotulo || r.nome}
                    resumo={r.resumo}
                    classe={r.cost_class}
                    usado={usados.has(r.nome)}
                    onClick={() => onAcrescentarRegra(r)}
                  />
                ))}
                {agentes.map((a) => (
                  <Bloco
                    key={a.name}
                    icone="🤖"
                    rotulo={a.name}
                    resumo={`${a.tipos.join(", ")} · ${a.ferramentas.length} ferramenta(s)`}
                    classe="AGENTE"
                    usado={usados.has(a.name)}
                    onClick={() => onAcrescentarAgente(a)}
                  />
                ))}
                {g.id === "AI" && (
                  <button
                    type="button"
                    disabled={!catalogo}
                    onClick={onNovoAgente}
                    className="mt-1 flex w-full items-center gap-2 rounded border border-dashed border-borda px-2 py-1.5 text-left text-[12px] text-neutral-500 transition hover:bg-neutral-50 disabled:opacity-40 dark:border-noite-borda dark:text-noite-fraca dark:hover:bg-noite-cartao"
                  >
                    <span className="w-4 shrink-0 text-center">+</span>
                    <span>New agent</span>
                  </button>
                )}
                {g.id === "AI" && (
                  <button
                    type="button"
                    disabled={!catalogo || catalogo.agentes.length < 2}
                    onClick={onNovoTime}
                    title={
                      catalogo && catalogo.agentes.length < 2
                        ? "uma tripulação sequencial com um agente só É um agente — e pagaria classe CREW por isso"
                        : "vários agentes sobre o mesmo item, com política de conflito"
                    }
                    className="mt-1 flex w-full items-center gap-2 rounded border border-dashed border-borda px-2 py-1.5 text-left text-[12px] text-neutral-500 transition hover:bg-neutral-50 disabled:opacity-40 dark:border-noite-borda dark:text-noite-fraca dark:hover:bg-noite-cartao"
                  >
                    <span className="w-4 shrink-0 text-center">👥</span>
                    <span>New team</span>
                  </button>
                )}
                {g.planejados.map((b) => (
                  <BlocoPlanejado key={b.rotulo} b={b} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
