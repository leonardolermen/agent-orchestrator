import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  agenteEmBranco,
  api,
  CORES,
  ErroDaApi,
  ORDEM_CLASSE,
  type Ambiente,
  type AgenteDeclarado,
  type BlocoPedido,
  type DominioInfo,
  type Receita,
  type Regra,
  type Run,
  type WorkflowConstruido,
} from "./api";
import { Chat } from "./Chat";
import { NoResolver, classeDo, nomeDo, type DadosDoNo } from "./NoResolver";
import { Painel } from "./Painel";

function usarTema(): [boolean, () => void] {
  const [escuro, setEscuro] = useState(
    () => document.documentElement.classList.contains("dark"),
  );
  const alternar = () => {
    const novo = !escuro;
    setEscuro(novo);
    document.documentElement.classList.toggle("dark", novo);
    // `localStorage` pode levantar (janela privada, site data bloqueado). A
    // preferência é conveniência por visitante — perdê-la volta ao default
    // escuro, que é o comportamento certo.
    try {
      localStorage.setItem("tema", novo ? "dark" : "light");
    } catch {
      /* sem problema: o default volta a valer */
    }
  };
  return [escuro, alternar];
}

const TIPOS_DE_NO = { resolver: NoResolver };

// Espaçamento vertical do auto-layout. A altura NÃO é constante — o nó do
// agente tem kind, ferramentas, vocabulário e teto — então o layout soma a
// altura MEDIDA (`node.measured`) e só cai neste chute antes do primeiro render.
const ESPACO = 56;
const ALTURA_CHUTE = 150;

type NoDoCanvas = Node<DadosDoNo>;

const SEM_NOS: NoDoCanvas[] = [];

export default function App() {
  const [dominios, setDominios] = useState<DominioInfo[]>([]);
  const [dominioId, setDominioId] = useState("");

  // Os nós POR DOMÍNIO. Um dicionário e não uma lista só porque uma composição
  // é de um domínio só — blocos de domínios diferentes trabalham `WorkItem.kind`
  // diferentes, e a cascata misturada não é ruim, é vazia de sentido.
  //
  // Guardar por domínio em vez de limpar ao trocar é o que impede a troca de
  // descartar trabalho em silêncio: voltar ao domínio anterior devolve a
  // cascata que estava lá.
  const [nosPorDominio, setNosPorDominio] = useState<Record<string, NoDoCanvas[]>>({});
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [construido, setConstruido] = useState<WorkflowConstruido | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [rodando, setRodando] = useState(false);
  const [ambiente, setAmbiente] = useState<Ambiente | null>(null);
  const [escuro, alternarTema] = usarTema();

  // O id do nó NÃO é o nome do bloco: renomear um agente na tela mudaria a
  // identidade do nó, e o React Flow perderia posição, seleção e dimensões
  // medidas no meio da digitação.
  const proximoId = useRef(1);

  const nos = nosPorDominio[dominioId] ?? SEM_NOS;
  const dominio = dominios.find((d) => d.id === dominioId) ?? null;

  useEffect(() => {
    api
      .dominios()
      .then((ds) => {
        setDominios(ds);
        setDominioId((atual) => atual || ds[0]?.id || "");
      })
      .catch((e: ErroDaApi) => setErro(e.message));
    api.ambiente().then(setAmbiente).catch((e: ErroDaApi) => setErro(e.message));
  }, []);

  const mudarNos = useCallback(
    (f: (atuais: NoDoCanvas[]) => NoDoCanvas[]) =>
      setNosPorDominio((m) => ({ ...m, [dominioId]: f(m[dominioId] ?? []) })),
    [dominioId],
  );

  // Os NÓS são o estado, e `applyNodeChanges` é quem os move.
  //
  // A primeira versão guardava as posições num dicionário próprio e recriava os
  // objetos de nó a cada render, descartando o retorno de `applyNodeChanges`.
  // Funcionava para arrastar e QUEBRAVA o minimapa: as dimensões medidas
  // (`measured`) vivem no objeto do nó, e recriá-lo as apagava a cada render.
  // O minimapa desenhava zero retângulos — visto na tela, não em teste.
  const aoMudarNos = useCallback(
    (mudancas: NodeChange<NoDoCanvas>[]) =>
      mudarNos((atuais) => applyNodeChanges(mudancas, atuais)),
    [mudarNos],
  );

  const emOrdem = useMemo(
    () =>
      // `Array.prototype.sort` é estável desde o ES2019 e `sorted()` do Python
      // também é — os dois concordam sem ninguém combinar. Quem GARANTE a ordem
      // é o servidor; `test_a_ordem_enviada_e_IGNORADA` compara contra o que ele
      // devolve, nunca contra esta função.
      [...nos].sort(
        (a, b) => ORDEM_CLASSE.indexOf(classeDo(a.data)) - ORDEM_CLASSE.indexOf(classeDo(b.data)),
      ),
    [nos],
  );

  // As arestas ligam cada nó ao PRÓXIMO na ordem de execução, e são derivadas a
  // cada render. Por isso arrastar um nó nunca muda o sentido da seta: ela volta
  // a apontar para o mesmo lugar, agora para cima. A regra fica visível
  // exatamente quando alguém tenta furá-la.
  // O traço da aresta acompanha o tema: `#b3ada3` sobre `#16161a` é quase
  // invisível, e uma seta que não se vê não diz em que sentido a cascata corre.
  const traco = escuro ? "#4a4a56" : "#b3ada3";
  const arestas: Edge[] = useMemo(
    () =>
      emOrdem.slice(0, -1).map((a, i) => {
        const b = emOrdem[i + 1];
        const mudaDeClasse = classeDo(a.data) !== classeDo(b.data);
        return {
          id: `${a.id}->${b.id}`,
          source: a.id,
          target: b.id,
          type: "smoothstep",
          // A transição de classe é o momento em que a cascata age; dizer o
          // nome dela na aresta ensina a regra sem precisar de legenda.
          label: mudaDeClasse ? "o que sobrou" : undefined,
          labelStyle: { fontSize: 10, fill: escuro ? "#9a968f" : "#8f8880" },
          labelBgStyle: { fill: escuro ? "#16161a" : "#faf9f7" },
          labelBgPadding: [4, 2] as [number, number],
          style: { stroke: traco, strokeWidth: 1.6 },
          markerEnd: { type: "arrowclosed", color: traco, width: 16, height: 16 } as never,
        };
      }),
    [emOrdem, escuro, traco],
  );

  const invalidar = () => {
    setConstruido(null);
    setRun(null);
  };

  // O AUTO-LAYOUT, na ordem de EXECUÇÃO.
  //
  // Antes, um nó novo ia para baixo do mais baixo — ordem de clique. Numa tela
  // cuja tese é "as setas não são suas, elas seguem o custo", acrescentar o
  // agente antes da regra desenhava AGENTE em cima e a seta subindo: o desenho
  // contradizendo o cabeçalho, que é a falha de decoração ao contrário. Visto
  // na tela, e não em teste.
  //
  // A chave do efeito é a lista de ids MAIS as alturas medidas — nada mais.
  // Arrastar não muda nenhuma das duas, então arrastar continua livre; o
  // próximo bloco acrescentado reempilha tudo, que é o comportamento coerente
  // com "o arranjo é decoração, a ordem é derivada".
  const chaveDeLayout = nos.map((n) => `${n.id}:${n.measured?.height ?? 0}`).join("|");
  useEffect(() => {
    mudarNos((atuais) => {
      if (!atuais.length) return atuais;
      const alvo = new Map<string, number>();
      let y = 0;
      for (const n of [...atuais].sort(
        (a, b) => ORDEM_CLASSE.indexOf(classeDo(a.data)) - ORDEM_CLASSE.indexOf(classeDo(b.data)),
      )) {
        alvo.set(n.id, y);
        y += (n.measured?.height ?? ALTURA_CHUTE) + ESPACO;
      }
      // Sem esta comparação o efeito se realimenta: ele mudaria o estado a cada
      // render, para o mesmo valor, para sempre.
      if (atuais.every((n) => n.position.x === 0 && n.position.y === alvo.get(n.id))) {
        return atuais;
      }
      return atuais.map((n) => ({ ...n, position: { x: 0, y: alvo.get(n.id) ?? 0 } }));
    });
  }, [chaveDeLayout, mudarNos]);

  const acrescentar = (dados: DadosDoNo) => {
    const id = `n${proximoId.current++}`;
    mudarNos((atuais) => [
      ...atuais.map((n) => ({ ...n, selected: false })),
      // A posição é provisória: o efeito acima reempilha assim que o React Flow
      // mede o cartão novo.
      { id, type: "resolver", position: { x: 0, y: 0 }, data: dados, selected: true },
    ]);
    invalidar();
  };

  const acrescentarRegra = (r: Regra) => {
    const parametros: Record<string, number> = {};
    for (const p of r.parametros) parametros[p.nome] = p.default;
    acrescentar({ tipo: "regra", regra: r, parametros });
  };

  const acrescentarAgente = (a: AgenteDeclarado) =>
    acrescentar({ tipo: "agente", declaracao: { ...a } });

  // "Acrescente um agente", que é o que tira a tela de cardápio. O nome nasce
  // livre: `construir_composicao` recusa bloco repetido, e um `agente` chocando
  // com outro `agente` seria uma recusa por acidente de nomenclatura.
  const novoAgente = () => {
    if (!dominio) return;
    const usados = new Set(nos.map((n) => nomeDo(n.data)));
    let nome = "agente";
    for (let i = 2; usados.has(nome); i++) nome = `agente-${i}`;
    acrescentarAgente(agenteEmBranco(nome, dominio.kinds[0] ?? ""));
  };

  const remover = (id: string) => {
    mudarNos((atuais) => atuais.filter((n) => n.id !== id));
    invalidar();
  };

  const mudarParametro = (id: string, param: string, valor: number) =>
    mudarNos((atuais) =>
      atuais.map((n) =>
        n.id === id && n.data.tipo === "regra"
          ? { ...n, data: { ...n.data, parametros: { ...n.data.parametros, [param]: valor } } }
          : n,
      ),
    );

  // O editor do agente. `Partial<AgenteDeclarado>` e não campo a campo: o painel
  // edita seis campos de naturezas diferentes, e seis callbacks seriam seis
  // lugares para esquecer de invalidar a composição construída.
  const mudarAgente = (id: string, patch: Partial<AgenteDeclarado>) => {
    mudarNos((atuais) =>
      atuais.map((n) =>
        n.id === id && n.data.tipo === "agente"
          ? { ...n, data: { ...n.data, declaracao: { ...n.data.declaracao, ...patch } } }
          : n,
      ),
    );
    invalidar();
  };

  const compor = async (id: string, nome: string) => {
    setErro(null);
    setAviso(null);
    setRun(null);
    try {
      setConstruido(
        await api.criarComposicao({
          id,
          nome: nome || id,
          dominio: dominioId,
          justificativa: "",
          // A posição no canvas NÃO vai junto: é arranjo visual, não definição.
          // Uma composição que carregasse coordenadas mudaria de versão só
          // porque alguém arrastou um nó.
          blocos: emOrdem.map(
            (n): BlocoPedido =>
              n.data.tipo === "regra"
                ? { tipo: "regra", nome: n.data.regra.nome, parametros: n.data.parametros }
                : { tipo: "agente", declaracao: n.data.declaracao },
          ),
        }),
      );
    } catch (e) {
      setErro((e as ErroDaApi).message);
    }
  };

  const executar = async () => {
    if (!construido || !ambiente) return;
    setErro(null);
    setRodando(true);
    try {
      setRun(await api.rodar(construido.id, ambiente));
    } catch (e) {
      setErro((e as ErroDaApi).message);
    } finally {
      setRodando(false);
    }
  };

  // O chat propôs. Ele conduz o `Entrevistador` do grill, que compõe RECEITAS —
  // nomes do catálogo da conciliação. Por isso a proposta pousa no domínio
  // `conciliacao` e não em qualquer um.
  //
  // O que ele propõe e o canvas não sabe desenhar é DITO, não descartado em
  // silêncio: `revisor` é classe HUMANO, e o modelo de domínio de hoje só tem
  // regras e agentes. É uma lacuna real — a etapa humana não tem representação
  // em `Dominio` —, e esconder o descarte a tornaria invisível.
  const aceitarProposta = (receita: Receita) => {
    const alvo = dominios.find((d) => d.id === "conciliacao");
    if (!alvo) return;
    setDominioId(alvo.id);

    const novos: NoDoCanvas[] = [];
    const naoColocados: string[] = [];
    for (const r of receita.resolvers) {
      const regra = alvo.regras.find((x) => x.nome === r.nome);
      const agente = alvo.agentes.find((x) => x.name === r.nome);
      let dados: DadosDoNo | null = null;
      if (regra) {
        const parametros: Record<string, number> = {};
        for (const p of regra.parametros) parametros[p.nome] = p.default;
        dados = { tipo: "regra", regra, parametros: { ...parametros, ...(r.parametros ?? {}) } };
      } else if (agente) {
        dados = { tipo: "agente", declaracao: { ...agente } };
      }
      if (!dados) {
        naoColocados.push(r.nome);
        continue;
      }
      // Posição provisória: o auto-layout reempilha na ordem de execução assim
      // que o React Flow mede os cartões.
      novos.push({
        id: `n${proximoId.current++}`,
        type: "resolver",
        position: { x: 0, y: 0 },
        data: dados,
      });
    }
    setNosPorDominio((m) => ({ ...m, [alvo.id]: novos }));
    setAviso(
      naoColocados.length
        ? `o chat propôs ${naoColocados.join(", ")}, que o canvas ainda não sabe ` +
          `desenhar: a etapa humana não tem bloco em nenhum domínio`
        : null,
    );
    invalidar();
  };

  const selecionado = nos.find((n) => n.selected) ?? null;
  const classes = emOrdem.map((n) => classeDo(n.data));

  return (
    <div className="flex h-screen flex-col bg-papel font-sans text-tinta dark:bg-noite-fundo dark:text-noite-tinta">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-borda bg-white px-5 py-3 dark:border-noite-borda dark:bg-noite-painel">
        <div>
          <h1 className="text-[15px] font-semibold leading-tight">Compor cascata</h1>
          <p className="max-w-[36rem] text-[11.5px] leading-snug text-neutral-500 dark:text-noite-fraca">
            Arraste os nós onde quiser. As <strong className="font-semibold">setas</strong> não são
            suas: elas seguem a classe de custo, do mais barato ao mais caro.
          </p>
        </div>

        {/* A PRIMEIRA pergunta da tela: que trabalho você quer orquestrar. A
            paleta segue desta resposta. Antes ela não existia, e por isso o
            canvas só oferecia blocos de conciliação. */}
        <label className="flex items-center gap-2 text-[11.5px]">
          <span className="text-neutral-500 dark:text-noite-fraca">domínio</span>
          <select
            value={dominioId}
            onChange={(e) => {
              setDominioId(e.target.value);
              setAviso(null);
              invalidar();
            }}
            className="rounded border border-borda bg-papel px-2 py-1 text-[12px] dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta"
          >
            {dominios.map((d) => (
              <option key={d.id} value={d.id}>
                {d.nome}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={alternarTema}
          title={escuro ? "mudar para claro" : "mudar para escuro"}
          className="ml-auto rounded border border-borda px-2 py-1 text-[12px] text-neutral-500 transition hover:bg-neutral-50 dark:border-noite-borda dark:text-noite-fraca dark:hover:bg-noite-cartao"
        >
          {escuro ? "☀" : "☾"}
        </button>
        <a href="/" className="text-[12px] text-humano hover:underline dark:text-noite-humano">
          ← cascata em execução
        </a>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[19rem_1fr_20rem]">
        <aside className="min-h-0 border-r border-borda bg-white dark:border-noite-borda dark:bg-noite-painel">
          <Chat aoPropor={aceitarProposta} temChave={ambiente?.tem_chave ?? false} />
        </aside>

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
            className="bg-papel dark:bg-noite-fundo"
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={22}
              size={1}
              color={escuro ? "#32323c" : "#d8d4cd"}
            />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeStrokeWidth={0}
              // As MESMAS cores de classe de custo, do mesmo lugar. Uma
              // segunda tabela aqui divergiria no dia em que alguém ajustasse
              // um tom, e o minimapa passaria a mentir sobre a classe.
              nodeColor={(n) => CORES[classeDo(n.data as DadosDoNo)].minimapa}
              maskColor={escuro ? "rgba(22,22,26,.7)" : "rgba(250,249,247,.7)"}
              className="!border !border-borda !bg-white dark:!border-noite-borda dark:!bg-noite-painel"
            />
          </ReactFlow>

          {nos.length === 0 && (
            <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
              <p className="text-[14px] text-neutral-400 dark:text-noite-fraca">
                Canvas vazio. Acrescente um bloco pela paleta →
              </p>
              <p className="mt-1 text-[12px] text-neutral-300 dark:text-noite-fraca/70">
                {dominio && dominio.regras.length === 0
                  ? "Este domínio não tem regra nenhuma: tudo passa pelo modelo."
                  : "Uma cascata sem bloco não resolve nada."}
              </p>
            </div>
          )}

          {nos.length > 0 && (
            <p className="pointer-events-none absolute left-3 top-3 font-mono text-[10.5px] text-neutral-400 dark:text-noite-fraca">
              ordem: por classe de custo ({[...new Set(classes)].join(" → ")})
            </p>
          )}

          {aviso && (
            <p className="absolute bottom-3 left-3 right-3 rounded-md bg-lacuna-fundo px-2.5 py-2 text-[11px] leading-snug text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew">
              {aviso}
            </p>
          )}
        </div>

        <Painel
          dominio={dominio}
          escolhidos={emOrdem}
          selecionado={selecionado}
          erro={erro}
          construido={construido}
          run={run}
          rodando={rodando}
          onAcrescentarRegra={acrescentarRegra}
          onAcrescentarAgente={acrescentarAgente}
          onNovoAgente={novoAgente}
          onRemover={remover}
          onMudarParametro={mudarParametro}
          onMudarAgente={mudarAgente}
          onCompor={compor}
          onExecutar={executar}
          ambiente={ambiente}
          onMudarAmbiente={setAmbiente}
        />
      </div>
    </div>
  );
}
