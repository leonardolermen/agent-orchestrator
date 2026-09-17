import { Handle, Position, type NodeProps } from "@xyflow/react";
import { CORES, type EntradaCatalogo } from "./api";

export interface DadosDoNo extends Record<string, unknown> {
  entrada: EntradaCatalogo;
  parametros: Record<string, number>;
}

/**
 * O cartão de um resolver no canvas.
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
  const { entrada, parametros } = data as DadosDoNo;
  const cor = CORES[entrada.cost_class];

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
      <Handle type="target" position={Position.Top} isConnectable={false} className="!h-1.5 !w-1.5 !border-0 !bg-borda dark:!bg-noite-borda" />

      <div className="px-3 pt-2.5 pb-2">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-[13px] text-tinta dark:text-noite-tinta">{entrada.nome}</span>
          <span className={`ml-auto text-[10px] tracking-wider font-medium ${cor.texto}`}>
            {entrada.cost_class}
          </span>
        </div>
        <p className="mt-1 text-[11.5px] leading-snug text-neutral-600 dark:text-noite-fraca">{entrada.resumo}</p>
      </div>

      {/* Modelo e ferramentas só aparecem em quem os TEM. Desenhar "modelo: —"
          num resolver de regra sugeriria que houve uma escolha; não houve, e
          não há modelo nenhum no caminho. */}
      {entrada.modelo_padrao && (
        <div
          className="flex items-center gap-2 border-t border-neutral-100 px-3 py-1.5 dark:border-noite-borda"
          title="o modelo é escolhido na execução (--model); este é o padrão"
        >
          <span className="text-neutral-300 text-[11px] dark:text-noite-fraca">◇</span>
          <span className="font-mono text-[11px] text-tinta dark:text-noite-tinta">{entrada.modelo_padrao}</span>
          <span className="ml-auto text-[9.5px] uppercase tracking-wide text-neutral-400 dark:text-noite-fraca">
            padrão
          </span>
        </div>
      )}

      {entrada.ferramentas.map((f) => (
        <div key={f} className="flex items-center gap-2 border-t border-neutral-100 px-3 py-1.5 dark:border-noite-borda">
          <span className="text-neutral-300 text-[11px] dark:text-noite-fraca">⚒</span>
          <span className="text-[11px] text-neutral-600 dark:text-noite-fraca">{f}</span>
        </div>
      ))}

      {entrada.parametros.length > 0 && (
        <div className="border-t border-neutral-100 px-3 py-1.5 dark:border-noite-borda">
          {entrada.parametros.map((p) => (
            <div key={p.nome} className="flex items-baseline gap-2 font-mono text-[10.5px]">
              <span className="text-neutral-400 dark:text-noite-fraca">{p.nome}</span>
              <span className="ml-auto text-tinta dark:text-noite-tinta">{parametros[p.nome]}</span>
            </div>
          ))}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} isConnectable={false} className="!h-1.5 !w-1.5 !border-0 !bg-borda dark:!bg-noite-borda" />
    </div>
  );
}
