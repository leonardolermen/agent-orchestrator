import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  api,
  ErroDaApi,
  ORDEM_CLASSE,
  type EntradaCatalogo,
  type Run,
  type WorkflowConstruido,
} from "./api";
import { NoResolver, type DadosDoNo } from "./NoResolver";
import { Painel } from "./Painel";

const TIPOS_DE_NO = { resolver: NoResolver };

// Espaçamento vertical do auto-layout. A altura NÃO é constante — o nó do
// agente tem modelo e cinco ferramentas — então o layout soma a altura MEDIDA
// (`node.measured`) e só cai neste chute antes do primeiro render.
const ESPACO = 56;
const ALTURA_CHUTE = 120;

type NoDoCanvas = Node<DadosDoNo>;

export default function App() {
  const [catalogo, setCatalogo] = useState<EntradaCatalogo[]>([]);
  // Os NÓS são o estado, e `applyNodeChanges` é quem os move.
  //
  // A primeira versão guardava as posições num dicionário próprio e recriava os
  // objetos de nó a cada render, descartando o retorno de `applyNodeChanges`.
  // Funcionava para arrastar e QUEBRAVA o minimapa: as dimensões medidas
  // (`measured`) vivem no objeto do nó, e recriá-lo as apagava a cada render.
  // O minimapa desenhava zero retângulos — visto na tela, não em teste.
  const [nos, setNos] = useState<NoDoCanvas[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [construido, setConstruido] = useState<WorkflowConstruido | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [rodando, setRodando] = useState(false);

  useEffect(() => {
    api
      .catalogo()
      .then(setCatalogo)
      .catch((e: ErroDaApi) => setErro(e.message));
  }, []);

  const aoMudarNos = useCallback(
    (mudancas: NodeChange<NoDoCanvas>[]) =>
      setNos((atuais) => applyNodeChanges(mudancas, atuais)),
    [],
  );

  const emOrdem = useMemo(
    () =>
      // `Array.prototype.sort` é estável desde o ES2019 e `sorted()` do Python
      // também é — os dois concordam sem ninguém combinar. Quem GARANTE a ordem
      // é o servidor; `test_a_ordem_enviada_e_IGNORADA` compara contra o que ele
      // devolve, nunca contra esta função.
      [...nos].sort(
        (a, b) =>
          ORDEM_CLASSE.indexOf(a.data.entrada.cost_class) -
          ORDEM_CLASSE.indexOf(b.data.entrada.cost_class),
      ),
    [nos],
  );

  // As arestas ligam cada nó ao PRÓXIMO na ordem de execução, e são derivadas a
  // cada render. Por isso arrastar um nó nunca muda o sentido da seta: ela volta
  // a apontar para o mesmo lugar, agora para cima. A regra fica visível
  // exatamente quando alguém tenta furá-la.
  const arestas: Edge[] = useMemo(
    () =>
      emOrdem.slice(0, -1).map((a, i) => {
        const b = emOrdem[i + 1];
        const mudaDeClasse = a.data.entrada.cost_class !== b.data.entrada.cost_class;
        return {
          id: `${a.id}->${b.id}`,
          source: a.id,
          target: b.id,
          type: "smoothstep",
          // A transição de classe é o momento em que a cascata age; dizer o
          // nome dela na aresta ensina a regra sem precisar de legenda.
          label: mudaDeClasse ? "o que sobrou" : undefined,
          labelStyle: { fontSize: 10, fill: "#8f8880" },
          labelBgStyle: { fill: "#faf9f7" },
          labelBgPadding: [4, 2] as [number, number],
          style: { stroke: "#b3ada3", strokeWidth: 1.6 },
          markerEnd: { type: "arrowclosed", color: "#b3ada3", width: 16, height: 16 } as never,
        };
      }),
    [emOrdem],
  );

  const acrescentar = (e: EntradaCatalogo) => {
    const parametros: Record<string, number> = {};
    for (const p of e.parametros) parametros[p.nome] = p.default;

    // Abaixo do nó mais baixo, na coluna. Usa a altura MEDIDA de quem já está
    // desenhado — assumir uma altura fixa punha o nó do agente (268px) por cima
    // do vizinho.
    const abaixo = nos.length
      ? Math.max(...nos.map((n) => n.position.y + (n.measured?.height ?? ALTURA_CHUTE)))
      : -ESPACO;

    setNos((atuais) => [
      ...atuais.map((n) => ({ ...n, selected: false })),
      {
        id: e.nome,
        type: "resolver",
        position: { x: 0, y: abaixo + ESPACO },
        data: { entrada: e, parametros },
        selected: true,
      },
    ]);
    setConstruido(null);
    setRun(null);
  };

  const remover = (nome: string) => {
    setNos((atuais) => atuais.filter((n) => n.id !== nome));
    setConstruido(null);
    setRun(null);
  };

  const mudarParametro = (nome: string, param: string, valor: number) =>
    setNos((atuais) =>
      atuais.map((n) =>
        n.id === nome
          ? { ...n, data: { ...n.data, parametros: { ...n.data.parametros, [param]: valor } } }
          : n,
      ),
    );

  const compor = async (id: string, nome: string) => {
    setErro(null);
    setRun(null);
    try {
      setConstruido(
        await api.criarReceita({
          id,
          nome: nome || id,
          justificativa: "",
          // A posição no canvas NÃO vai junto: é arranjo visual, não definição.
          // Uma `Receita` que carregasse coordenadas mudaria de versão só porque
          // alguém arrastou um nó.
          resolvers: emOrdem.map((n) => ({
            nome: n.data.entrada.nome,
            parametros: n.data.parametros,
          })),
        }),
      );
    } catch (e) {
      setErro((e as ErroDaApi).message);
    }
  };

  const executar = async () => {
    if (!construido) return;
    setErro(null);
    setRodando(true);
    try {
      setRun(await api.rodar(construido.id));
    } catch (e) {
      setErro((e as ErroDaApi).message);
    } finally {
      setRodando(false);
    }
  };

  const selecionado = nos.find((n) => n.selected)?.id ?? null;
  const classes = emOrdem.map((n) => n.data.entrada.cost_class);

  return (
    <div className="flex h-screen flex-col bg-papel font-sans text-tinta">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-borda bg-white px-5 py-3">
        <div>
          <h1 className="text-[15px] font-semibold leading-tight">Compor cascata</h1>
          <p className="max-w-[40rem] text-[11.5px] leading-snug text-neutral-500">
            Arraste os nós onde quiser. As <strong className="font-semibold">setas</strong> não são
            suas: elas seguem a classe de custo, do mais barato ao mais caro.
          </p>
        </div>
        <a href="/" className="ml-auto text-[12px] text-humano hover:underline">
          ← cascata em execução
        </a>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_20rem]">
        <div className="relative">
          <ReactFlow<NoDoCanvas>
            nodes={nos}
            edges={arestas}
            nodeTypes={TIPOS_DE_NO}
            onNodesChange={aoMudarNos}
            // Sem `onConnect`: não existe como criar uma aresta. Ver `NoResolver`.
            nodesConnectable={false}
            edgesFocusable={false}
            fitView
            fitViewOptions={{ padding: 0.35, maxZoom: 1 }}
            className="bg-papel"
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#d8d4cd" />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeStrokeWidth={0}
              nodeColor={(n) =>
                ({
                  REGRA: "#2f7a4d",
                  AGENTE: "#a86a10",
                  CREW: "#8a6d1f",
                  HUMANO: "#2a5d9c",
                })[(n.data as DadosDoNo).entrada.cost_class]
              }
              className="!border !border-borda !bg-white"
            />
          </ReactFlow>

          {nos.length === 0 && (
            <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
              <p className="text-[14px] text-neutral-400">
                Canvas vazio. Acrescente um resolver pela paleta →
              </p>
              <p className="mt-1 text-[12px] text-neutral-300">
                Uma cascata sem resolver não resolve nada.
              </p>
            </div>
          )}

          {nos.length > 0 && (
            <p className="pointer-events-none absolute left-3 top-3 font-mono text-[10.5px] text-neutral-400">
              ordem: por classe de custo ({[...new Set(classes)].join(" → ")})
            </p>
          )}
        </div>

        <Painel
          catalogo={catalogo}
          escolhidos={emOrdem.map((n) => n.data)}
          selecionado={selecionado}
          erro={erro}
          construido={construido}
          run={run}
          rodando={rodando}
          onAcrescentar={acrescentar}
          onRemover={remover}
          onMudarParametro={mudarParametro}
          onCompor={compor}
          onExecutar={executar}
        />
      </div>
    </div>
  );
}
