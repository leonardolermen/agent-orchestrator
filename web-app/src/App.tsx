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
  type Catalogo,
  type Receita,
  type Regra,
  type Run,
  type WorkflowConstruido,
} from "./api";
import { Chat } from "./Chat";
import { NoResolver, classeDo, nomeDo, type DadosDoNo } from "./NoResolver";
import { Painel } from "./Painel";
import { BotaoDeTema, usarTema } from "./tema";

const TIPOS_DE_NO = { resolver: NoResolver };

// Espaçamento vertical do auto-layout. A altura NÃO é constante — o nó do
// agente tem kind, ferramentas, vocabulário e teto — então o layout soma a
// altura MEDIDA (`node.measured`) e só cai neste chute antes do primeiro render.
const ESPACO = 56;
const ALTURA_CHUTE = 150;

type NoDoCanvas = Node<DadosDoNo>;

export default function App() {
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);

  // Os nós do canvas ÚNICO. Eram um dicionário indexado pelo domínio, porque
  // trocar de domínio trocava de cascata e limpar a lista teria descartado
  // trabalho em silêncio. Sem domínio não há troca: existe um quadro só.
  const [nos, setNos] = useState<NoDoCanvas[]>([]);
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

  useEffect(() => {
    api.catalogo().then(setCatalogo).catch((e: ErroDaApi) => setErro(e.message));
    api.ambiente().then(setAmbiente).catch((e: ErroDaApi) => setErro(e.message));
  }, []);

  // Havia aqui um `mudarNos` que aplicava a função ao balde do domínio atual.
  // Sem domínio não há balde: quem muda os nós chama `setNos` direto.

  // Os NÓS são o estado, e `applyNodeChanges` é quem os move.
  //
  // A primeira versão guardava as posições num dicionário próprio e recriava os
  // objetos de nó a cada render, descartando o retorno de `applyNodeChanges`.
  // Funcionava para arrastar e QUEBRAVA o minimapa: as dimensões medidas
  // (`measured`) vivem no objeto do nó, e recriá-lo as apagava a cada render.
  // O minimapa desenhava zero retângulos — visto na tela, não em teste.
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
    setNos((atuais) => {
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
  }, [chaveDeLayout]);

  const acrescentar = (dados: DadosDoNo) => {
    const id = `n${proximoId.current++}`;
    setNos((atuais) => [
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
  //
  // O `kind` nasce VAZIO, e não no primeiro kind de um domínio: é a pessoa que
  // diz sobre que tipo de item o agente trabalha, porque é por `kind` que o
  // grafo liga um degrau ao outro. O painel mostra o campo vazio como o que
  // falta preencher.
  const novoAgente = () => {
    const usados = new Set(nos.map((n) => nomeDo(n.data)));
    let nome = "agente";
    for (let i = 2; usados.has(nome); i++) nome = `agente-${i}`;
    acrescentarAgente(agenteEmBranco(nome));
  };

  const remover = (id: string) => {
    setNos((atuais) => atuais.filter((n) => n.id !== id));
    invalidar();
  };

  const mudarParametro = (id: string, param: string, valor: number) =>
    setNos((atuais) =>
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
    setNos((atuais) =>
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
  // nomes do catálogo. A proposta pousa no canvas único: não há mais um domínio
  // para escolher antes, que era o que fazia a proposta cair sempre na
  // conciliação independentemente do que se tinha pedido.
  //
  // O que ele propõe e o canvas não sabe desenhar continua sendo DITO, não
  // descartado em silêncio. O caso que motivou o aviso era o `revisor`, que o
  // canvas não achava em `Dominio` nenhum; o catálogo plano publica o revisor,
  // então ele agora POUSA — mas um nome que não esteja nem nas regras nem nos
  // agentes ainda sai, e sair sem dizer seria a cascata mentindo sobre o que
  // foi proposto.
  const aceitarProposta = (receita: Receita) => {
    if (!catalogo) {
      setAviso("o catálogo ainda não carregou; a proposta do chat não pôde pousar");
      return;
    }

    const novos: NoDoCanvas[] = [];
    const naoColocados: string[] = [];
    for (const r of receita.resolvers) {
      const regra = catalogo.regras.find((x) => x.nome === r.nome);
      const agente = catalogo.agentes.find((x) => x.name === r.nome);
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
    setNos(novos);
    setAviso(
      naoColocados.length
        ? `o chat propôs ${naoColocados.join(", ")}, que o canvas não sabe ` +
          `desenhar: não há bloco com esse nome no catálogo`
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

        {/* Não há pergunta antes do quadro. Havia um `<select>` de domínio
            aqui, e era ele que decidia a paleta: quem quisesse triar issues
            escolhia entre três domínios prontos e recebia blocos bancários. A
            paleta agora é o catálogo inteiro, e a única pergunta é o que você
            monta. */}

        <span className="ml-auto">
          <BotaoDeTema escuro={escuro} alternar={alternarTema} />
        </span>
        {/* As outras DUAS VISTAS da mesma aplicação, não outras páginas.
            Enquanto eram `index.html` e `fila.html` separados, estes links
            precisavam carregar a query string inteira para as três telas
            concordarem sobre qual dataset estavam olhando — e o P4.14 do
            DECISOES registra que essa promessa já quebrou. */}
        <a href="/" className="text-[12px] text-humano hover:underline dark:text-noite-humano">
          ← cascata em execução
        </a>
        <a
          href="/?vista=fila"
          className="text-[12px] text-humano hover:underline dark:text-noite-humano"
        >
          fila →
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
                {catalogo && catalogo.regras.length === 0
                  ? "O catálogo não tem regra nenhuma: tudo passa pelo modelo."
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
          catalogo={catalogo}
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
