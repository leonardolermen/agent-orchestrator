import { useState } from "react";
import {
  CORES,
  type Ambiente,
  type AgenteDeclarado,
  type Catalogo,
  type Parametro,
  type Regra,
  type ValorParametro,
  type WorkflowConstruido,
} from "./api";
import {
  classeDo,
  nomeDo,
  type DadosAgente,
  type DadosCrew,
  type DadosDoNo,
} from "./NoResolver";
import { Paleta } from "./Paleta";
import { Variaveis } from "./Variaveis";

/** Um nó, do ponto de vista do painel. Estrutural, para não importar o React
 *  Flow aqui só por causa de um tipo. */
export interface NoEscolhido {
  id: string;
  data: DadosDoNo;
}

interface Props {
  catalogo: Catalogo | null;
  escolhidos: NoEscolhido[];
  selecionado: NoEscolhido | null;
  erro: string | null;
  construido: WorkflowConstruido | null;
  ambiente: Ambiente | null;
  onAcrescentarRegra: (r: Regra) => void;
  onAcrescentarAgente: (a: AgenteDeclarado) => void;
  onNovoAgente: () => void;
  onNovoTime: () => void;
  onMudarTime: (id: string, patch: Partial<DadosCrew>) => void;
  onRemover: (id: string) => void;
  onMudarParametro: (id: string, param: string, valor: ValorParametro) => void;
  onMudarAgente: (id: string, patch: Partial<AgenteDeclarado>) => void;
  onCompor: (id: string, nome: string, entrega: string[], maxRondas: number) => void;
  // Quantas etapas existem, como se chamam, e como mover um bloco entre elas.
  quantasEtapas: number;
  nomeDaEtapa: (i: number) => string;
  onRenomearEtapa: (i: number, nome: string) => void;
  onMudarEtapa: (id: string, etapa: number) => void;
  onMudarAmbiente: (a: Ambiente) => void;
}

const CAMPO =
  "w-full rounded border border-borda bg-papel px-2 py-1.5 text-[12px] " +
  "dark:border-noite-borda dark:bg-noite-fundo dark:text-noite-tinta";

/** O editor de UM parametro, escolhido pelo TIPO do valor.
 *
 *  Um so `<input type="number">` servia enquanto todo bloco vinha de um dominio
 *  ja configurado — o L2 sabe que casa por documento, e o que restava ajustar
 *  era a folga. Um bloco generico ("igualdade") recebe NOME DE CAMPO, e nome de
 *  campo e texto, quando nao uma lista deles.
 *
 *  O tipo vem do `default` e nao de um campo `tipo` ao lado: dois campos
 *  descrevendo a mesma coisa divergiriam no primeiro parametro novo, que e a
 *  razao que `ParametroDeRegra` ja da no servidor.
 *
 *  Lista entra separada por virgula. E o editor mais simples que existe e o
 *  servidor valida a forma de cada campo ("valor=total") com mensagem propria —
 *  um editor de linhas com botao de adicionar viria depois, sem mudar o
 *  contrato. */
function CampoDeParametro({
  spec,
  valor,
  onMudar,
}: {
  spec: Parametro;
  valor: ValorParametro;
  onMudar: (v: ValorParametro) => void;
}) {
  const lista = Array.isArray(spec.default);
  const texto = typeof spec.default === "string";
  // Obrigatorio ainda vazio: o bloco NAO existe sem isto, e o servidor recusa
  // ao compor. Dizer aqui poupa a viagem — e a borda vermelha e o unico jeito
  // de a pessoa ver qual dos campos falta sem ler a mensagem de erro inteira.
  const faltando =
    spec.obrigatorio &&
    (Array.isArray(valor) ? valor.length === 0 : !String(valor ?? "").trim());
  const borda = faltando ? " border-red-400 dark:border-red-500" : "";

  return (
    <label className="mb-2.5 block">
      <span className="flex items-center gap-2">
        <span className="text-[11.5px] text-neutral-600 dark:text-noite-fraca">
          {spec.nome}
          {spec.obrigatorio && <span className="ml-0.5 text-red-500">*</span>}
        </span>
        {lista || texto ? (
          <input
            type="text"
            value={Array.isArray(valor) ? valor.join(", ") : String(valor ?? "")}
            placeholder={lista ? "documento, valor=total" : ""}
            onChange={(ev) =>
              onMudar(
                lista
                  ? ev.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean)
                  : ev.target.value,
              )
            }
            className={`ml-auto w-44 font-mono ${CAMPO}${borda}`}
          />
        ) : (
          <input
            type="number"
            value={typeof valor === "number" ? valor : ""}
            onChange={(ev) =>
              // `parseInt` e nao `Number`: campo vazio vira NaN e o servidor
              // recusa. Um 0 silencioso viraria `max_cents=0`, que e workflow
              // legitimo e nao o que a pessoa quis.
              onMudar(parseInt(ev.target.value, 10))
            }
            className={`ml-auto w-24 text-right font-mono ${CAMPO}${borda}`}
          />
        )}
      </span>
      <span className="mt-0.5 block text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
        {spec.descricao}
      </span>
    </label>
  );
}

/** Em qual degrau este bloco roda, e o botao que abre o proximo.
 *
 *  "+ etapa" move o bloco para um degrau NOVO — ele nao cria etapa vazia,
 *  porque o numero de etapas e derivado do que os blocos dizem. Sem isso
 *  haveria um estado "etapa vazia" na tela que o servidor recusa, e a pessoa
 *  veria um degrau que a composicao nao tem. */
function SeletorDeEtapa({
  atual,
  quantas,
  nomeDaEtapa,
  onEscolher,
}: {
  atual: number;
  quantas: number;
  nomeDaEtapa: (i: number) => string;
  onEscolher: (i: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {Array.from({ length: quantas }, (_, i) => (
        <button
          key={i}
          type="button"
          onClick={() => onEscolher(i)}
          className={[
            "rounded border px-2 py-1 text-[11.5px] transition",
            i === atual
              ? "border-tinta bg-tinta text-white dark:border-noite-tinta dark:bg-noite-cartao dark:text-noite-tinta"
              : "border-borda hover:bg-neutral-50 dark:border-noite-borda dark:hover:bg-noite-cartao",
          ].join(" ")}
        >
          {nomeDaEtapa(i)}
        </button>
      ))}
      <button
        type="button"
        onClick={() => onEscolher(quantas)}
        title="move este bloco para um degrau novo"
        className="rounded border border-dashed border-borda px-2 py-1 text-[11.5px] text-neutral-500 transition hover:bg-neutral-50 dark:border-noite-borda dark:text-noite-fraca dark:hover:bg-noite-cartao"
      >
        + etapa
      </button>
    </div>
  );
}

/** Quem esta no time, como ele roda, e o que fazer quando discordam.
 *
 *  O `abstem_com` NAO aparece aqui: ele sai dos agentes escolhidos, e oferece-lo
 *  seria oferecer um campo que o servidor ignora. */
function EditorDeTime({
  time,
  catalogo,
  onMudar,
  onRemover,
}: {
  time: DadosCrew;
  catalogo: Catalogo;
  onMudar: (patch: Partial<DadosCrew>) => void;
  onRemover: () => void;
}) {
  const dentro = new Set(time.agentes.map((a) => a.name));
  const alternar = (nome: string) => {
    const novo = dentro.has(nome)
      ? time.agentes.filter((a) => a.name !== nome)
      : [...time.agentes, catalogo.agentes.find((a) => a.name === nome)!];
    onMudar({ agentes: novo });
  };

  return (
    <Secao titulo={time.nome} ajuda="Vários agentes sobre o MESMO item, e uma política para o desacordo.">
      <label className="mb-2.5 block">
        <span className="text-[11px] text-neutral-500 dark:text-noite-fraca">nome</span>
        <input
          value={time.nome}
          onChange={(e) => onMudar({ nome: e.target.value })}
          className={`mt-1 ${CAMPO}`}
        />
      </label>

      <span className="mb-1 block text-[11px] text-neutral-500 dark:text-noite-fraca">
        quem está no time
      </span>
      <div className="mb-2.5 grid gap-1">
        {catalogo.agentes.map((a) => (
          <label key={a.name} className="flex items-center gap-2 text-[12px]">
            <input
              type="checkbox"
              checked={dentro.has(a.name)}
              onChange={() => alternar(a.name)}
            />
            <span>{a.name}</span>
            <span className="ml-auto font-mono text-[10px] text-neutral-400 dark:text-noite-fraca">
              {a.abstem_com}
            </span>
          </label>
        ))}
      </div>
      {/* A recusa de verdade e do servidor — `Crew.__post_init__` explica por que
          um time de um agente so nao e um time. Isto aqui so poupa a viagem. */}
      {time.agentes.length < 2 && (
        <p className="mb-2.5 rounded bg-lacuna-fundo px-2 py-1.5 text-[11px] leading-snug text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew">
          Um time sequencial com um agente só É um agente — e pagaria classe CREW
          por isso. Escolha pelo menos dois.
        </p>
      )}

      <label className="mb-2 block">
        <span className="text-[11px] text-neutral-500 dark:text-noite-fraca">processo</span>
        <select
          value={time.process}
          onChange={(e) => onMudar({ process: e.target.value })}
          className={`mt-1 ${CAMPO}`}
        >
          <option value="sequential">sequential — todos opinam</option>
          <option value="hierarchical">hierarchical — precisa de gerente</option>
        </select>
      </label>

      <label className="mb-2.5 block">
        <span className="text-[11px] text-neutral-500 dark:text-noite-fraca">
          quando discordam
        </span>
        <select
          value={time.conflito}
          onChange={(e) => onMudar({ conflito: e.target.value })}
          className={`mt-1 ${CAMPO}`}
        >
          <option value="abster">abster — o desacordo vira informação</option>
          <option value="maioria">maioria — precisa de 3+</option>
          <option value="sintetizar">sintetizar — precisa de sintetizador</option>
        </select>
      </label>

      <Remover onClick={onRemover} />
    </Secao>
  );
}

export function Painel(p: Props) {
  const [id, setId] = useState("");
  const [nome, setNome] = useState("");
  const [entrega, setEntrega] = useState("");
  const [rondas, setRondas] = useState(1);

  const usados = new Set(p.escolhidos.map((n) => nomeDo(n.data)));
  const temAgente = p.escolhidos.some((n) => classeDo(n.data) === "AGENTE");

  return (
    <aside className="overflow-y-auto border-l border-borda bg-white px-4 py-4 dark:border-noite-borda dark:bg-noite-painel">
      {/* A PALETA. A assimetria que a plataforma tem por dentro continua aqui:
          regra é código com parâmetros expostos — você escolhe QUAL entra;
          agente é dado — você CRIA um, e por isso "New agent" fica em AI. */}
      <Paleta
        catalogo={p.catalogo}
        usados={usados}
        onAcrescentarRegra={p.onAcrescentarRegra}
        onAcrescentarAgente={p.onAcrescentarAgente}
        onNovoAgente={p.onNovoAgente}
        onNovoTime={p.onNovoTime}
      />

      {/* A ETAPA do bloco selecionado. Vale para regra E para agente, entao
          mora fora dos dois blocos de edicao abaixo. */}
      {p.selecionado && (
        <Secao titulo="Etapa" ajuda="Dentro de uma etapa a ordem e por CUSTO; entre etapas, por DADO.">
          <SeletorDeEtapa
            atual={p.selecionado.data.etapa}
            quantas={p.quantasEtapas}
            nomeDaEtapa={p.nomeDaEtapa}
            onEscolher={(i) => p.onMudarEtapa(p.selecionado!.id, i)}
          />
          <label className="mt-2 block">
            <span className="text-[11px] text-neutral-500 dark:text-noite-fraca">
              nome desta etapa
            </span>
            <input
              value={p.nomeDaEtapa(p.selecionado.data.etapa)}
              onChange={(e) => p.onRenomearEtapa(p.selecionado!.data.etapa, e.target.value)}
              className={`mt-1 ${CAMPO}`}
            />
          </label>
        </Secao>
      )}

      {p.selecionado?.data.tipo === "regra" && (
        <Secao
          titulo={p.selecionado.data.regra.nome}
          ajuda={p.selecionado.data.regra.resumo}
        >
          {p.selecionado.data.regra.parametros.length === 0 ? (
            <p className="text-[11.5px] text-neutral-400 dark:text-noite-fraca">
              sem parâmetros.
            </p>
          ) : (
            p.selecionado.data.regra.parametros.map((spec) => (
              <CampoDeParametro
                key={spec.nome}
                spec={spec}
                valor={
                  (p.selecionado!.data as { parametros: Record<string, ValorParametro> })
                    .parametros[spec.nome]
                }
                onMudar={(valor) =>
                  p.onMudarParametro(p.selecionado!.id, spec.nome, valor)
                }
              />
            ))
          )}
          <Remover onClick={() => p.onRemover(p.selecionado!.id)} />
        </Secao>
      )}

      {p.selecionado?.data.tipo === "crew" && p.catalogo && (
        <EditorDeTime
          time={p.selecionado.data}
          catalogo={p.catalogo}
          onMudar={(patch) => p.onMudarTime(p.selecionado!.id, patch)}
          onRemover={() => p.onRemover(p.selecionado!.id)}
        />
      )}

      {p.selecionado?.data.tipo === "agente" && p.catalogo && (
        <EditorDeAgente
          key={p.selecionado.id}
          no={{ id: p.selecionado.id, data: p.selecionado.data }}
          catalogo={p.catalogo}
          onMudar={p.onMudarAgente}
          onRemover={p.onRemover}
        />
      )}

      {p.escolhidos.length > 0 && (
        // Âmbar e não vermelho: uma cascata com classe AGENTE não está errada —
        // ela custa, e a diferença entre "errado" e "caro" é a tese do produto.
        <div
          className={[
            "mb-5 rounded-md px-2.5 py-2 text-[11.5px] leading-snug",
            temAgente
              ? "bg-lacuna-fundo text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew"
              : "bg-emerald-50 text-regra dark:bg-emerald-950/30 dark:text-noite-regra",
          ].join(" ")}
        >
          {temAgente
            ? "Tem classe AGENTE: gasta dinheiro ao rodar — a execução pede teto e chave no servidor."
            : "Nenhum bloco paga por token. Roda de graça."}
        </div>
      )}

      {/* O AMBIENTE. Não é "configuração do agente": é o que uma execução
          recebe. O modelo aparece porque decide o preço; a chave aparece como
          SIM/NÃO porque a tela precisa saber se o chat funciona e nunca precisa
          do valor. */}
      {/* As VARIAVEIS do cliente, antes do Ambiente: a secao de baixo diz o que
          o SERVIDOR tem (modelo, chave); esta diz o que o CLIENTE configurou
          para o workflow dele alcancar os sistemas dele. */}
      <Secao titulo="Variáveis" ajuda="O que um bloco Input usa para alcançar o sistema do cliente.">
        <Variaveis />
      </Secao>

      {p.ambiente && (
        <Secao titulo="Ambiente" ajuda="O que uma execução usa.">
          <div className="mb-2 flex items-center gap-2 text-[11.5px]">
            <span className="text-neutral-500 dark:text-noite-fraca">modelo</span>
            <span className="ml-auto font-mono text-[11px]">{p.ambiente.modelo_padrao}</span>
          </div>
          <div className="mb-3 flex items-center gap-2 text-[11.5px]">
            <span className="text-neutral-500 dark:text-noite-fraca">ANTHROPIC_API_KEY</span>
            <span
              className={`ml-auto text-[11px] ${
                p.ambiente.tem_chave
                  ? "text-regra dark:text-noite-regra"
                  : "text-lacuna dark:text-noite-crew"
              }`}
            >
              {p.ambiente.tem_chave ? "configurada" : "ausente"}
            </span>
          </div>
          {(
            [
              ["seed", "semente do benchmark sintético"],
              ["n", "quantos lançamentos gerar"],
            ] as const
          ).map(([campo, dica]) => (
            <label key={campo} className="mb-2 block">
              <span className="flex items-center gap-2">
                <span className="text-[11.5px] text-neutral-600 dark:text-noite-fraca">
                  {campo}
                </span>
                <input
                  type="number"
                  value={p.ambiente![campo]}
                  max={campo === "n" ? p.ambiente!.n_max : undefined}
                  onChange={(ev) =>
                    p.onMudarAmbiente({
                      ...p.ambiente!,
                      [campo]: parseInt(ev.target.value, 10),
                    })
                  }
                  className={`ml-auto w-24 text-right font-mono ${CAMPO}`}
                />
              </span>
              <span className="mt-0.5 block text-[10.5px] text-neutral-400 dark:text-noite-fraca">
                {dica}
              </span>
            </label>
          ))}
        </Secao>
      )}

      <Secao titulo="Identidade">
        <input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="triagem-de-issues"
          spellCheck={false}
          className={`mb-2 ${CAMPO}`}
        />
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          placeholder="nome (opcional)"
          className={`mb-2 ${CAMPO}`}
        />
        {/* A ENTREGA. Nao e um no do canvas de proposito: nada roda aqui, e um
            no que nao executa sugere que executa. E uma afirmacao sobre o
            workflow — "estes kinds SAO a saida" —, e o kernel exige que ela
            seja escrita: sem ela, um bloco que ramifica produz um kind que
            ninguem consome e a composicao e recusada por beco sem saida. */}
        <input
          value={entrega}
          onChange={(e) => setEntrega(e.target.value)}
          placeholder="entrega: suspeito, aprovado"
          spellCheck={false}
          className={`mb-1 font-mono ${CAMPO}`}
        />
        <p className="mb-2.5 text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
          os kinds que SÃO a saída. Um bloco que ramifica precisa declarar aqui
          o ramo que ninguém mais consome — senão o item ficaria no pool para
          sempre.
        </p>
        {/* O LOOP. Tambem nao e um no: nada roda "dentro" dele. E quantas vezes
            a SEQUENCIA de etapas pode rodar, e existe para ARESTA DE VOLTA — o
            revisor reprova e o rascunho volta ao escritor. E TETO, nao
            contagem: o motor para sozinho no ponto fixo. */}
        <label className="mb-1 flex items-center gap-2">
          <span className="text-[11.5px] text-neutral-600 dark:text-noite-fraca">
            rondas
          </span>
          <input
            type="number"
            min={1}
            value={rondas}
            onChange={(e) => setRondas(Math.max(1, parseInt(e.target.value, 10) || 1))}
            className={`ml-auto w-20 text-right font-mono ${CAMPO}`}
          />
        </label>
        <p className="mb-2.5 text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
          quantas vezes a sequência de etapas pode rodar. 1 é uma passada; mais
          existe para aresta de volta — o revisor reprova e o item volta. É teto:
          o motor para sozinho quando uma ronda não muda nada.
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={p.escolhidos.length === 0 || !id.trim()}
            onClick={() =>
              p.onCompor(
                id.trim(),
                nome.trim(),
                entrega
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
                rondas,
              )
            }
            className="flex-1 rounded border border-tinta bg-tinta px-3 py-1.5 text-[12.5px] text-white transition disabled:cursor-not-allowed disabled:border-neutral-300 disabled:bg-neutral-300 dark:border-noite-borda dark:bg-noite-cartao dark:text-noite-tinta dark:disabled:bg-noite-fundo dark:disabled:text-noite-fraca"
          >
            Compor e validar
          </button>
          {p.construido && (
            // Hand-off, não execução: fonte, teto e resultado moram na vista
            // de execução, e é lá que o servidor exige o teto ANTES de gastar.
            // O mesmo idioma do link "fila de revisão →" e a mesma URL que o
            // grill imprime na CLI. Só existe DEPOIS de salvo: uma composição
            // validada e não gravada não está no registry.
            <a
              href={`/?workflow=${encodeURIComponent(p.construido.id)}`}
              className="rounded border border-regra bg-regra px-3 py-1.5 text-[12.5px] text-white transition hover:opacity-90"
            >
              abrir na execução →
            </a>
          )}
        </div>
        {p.erro && (
          <p className="mt-2 text-[11.5px] leading-snug text-red-700 dark:text-red-400">
            {p.erro}
          </p>
        )}
      </Secao>

      {p.construido && (
        <Secao
          titulo="Como ela vai rodar"
          ajuda="A definição construída pelo servidor — não o que você desenhou."
        >
          <ol className="grid gap-1">
            {p.construido.stages.flatMap((s) =>
              s.cascade.map((r) => (
                <li
                  key={r.name}
                  className={`rounded border border-borda border-l-[3px] px-2.5 py-1.5 dark:border-noite-borda ${CORES[r.cost_class].bordaEsq}`}
                >
                  <span className="flex items-baseline gap-2">
                    <span className="text-[12px] font-medium">{r.name}</span>
                    <span
                      className={`ml-auto text-[9.5px] tracking-wider ${CORES[r.cost_class].texto}`}
                    >
                      {r.cost_class}
                    </span>
                  </span>
                  <span className="block text-[11px] text-neutral-500 dark:text-noite-fraca">
                    {r.summary}
                  </span>
                </li>
              )),
            )}
          </ol>
        </Secao>
      )}

    </aside>
  );
}

// ---------------------------------------------------------------------------


/**
 * O editor do agente. É esta caixa que tira a tela de cardápio.
 *
 * Nenhum campo aqui tem equivalente numa `Receita`: ela carrega nomes do
 * catálogo e um `dict[str, int]` de parâmetros, e um prompt não cabe num `int`.
 * Por isso a composição é um formato novo e não um campo a mais.
 *
 * **A tela não valida.** Quem recusa é `AgenteDeclarado.__post_init__`, e a
 * mensagem dele chega como o 422 que aparece em "Identidade". Uma segunda
 * validação aqui divergiria da primeira, e o sintoma seria a tela barrando algo
 * que o servidor aceita — ou, pior, deixando passar algo que ele recusa.
 */
function EditorDeAgente({
  no,
  catalogo,
  onMudar,
  onRemover,
}: {
  no: { id: string; data: DadosAgente };
  catalogo: Catalogo;
  onMudar: (id: string, patch: Partial<AgenteDeclarado>) => void;
  onRemover: (id: string) => void;
}) {
  const a = no.data.declaracao;
  const mudar = (patch: Partial<AgenteDeclarado>) => onMudar(no.id, patch);

  // Os campos que o prompt pode interpolar dependem do payload do item, que só
  // existe na execução. O que a tela PODE dizer é qual erro isso dá: `_units`
  // levanta nomeando o campo que faltou, em vez de mandar um prompt furado.
  const semInterpolacao = a.prompt.length > 0 && !a.prompt.includes("{");

  return (
    <Secao titulo={a.name || "agente"} ajuda="Tudo aqui é dado. Nada vira código.">
      <Campo rotulo="nome">
        <input value={a.name} onChange={(e) => mudar({ name: e.target.value })} className={CAMPO} />
      </Campo>

      {/* O `kind` é DIGITADO, não escolhido numa lista.
          Era um `<select>` sobre `Dominio.kinds`, e um agente em branco já
          nascia com o primeiro kind do domínio — a tela decidia sobre que tipo
          de item ele trabalha, e a pessoa nunca via a decisão. Num quadro em
          branco não há lista de onde tirar: é por `kind` que `Stage.consome`/
          `produz` liga um degrau ao outro, então quem monta precisa dizer qual
          é. O `<datalist>` oferece os que já existem sem fechar a lista — um
          kind NOVO é o caso normal aqui, não a exceção. */}
      <Campo
        rotulo="kind"
        dica="que tipo de item este agente trabalha; é por ele que o grafo liga os degraus"
        alerta={
          a.kind.trim()
            ? null
            : "em branco: diga que tipo de item este agente consome, senão não há como ligá-lo a degrau nenhum"
        }
      >
        <input
          value={a.kind}
          onChange={(e) => mudar({ kind: e.target.value })}
          list="kinds-conhecidos"
          placeholder="lancamento, issue… ou um kind novo"
          spellCheck={false}
          className={`${CAMPO} font-mono text-[11px]`}
        />
        <datalist id="kinds-conhecidos">
          {[...new Set(catalogo.agentes.map((x) => x.kind))].sort().map((k) => (
            <option key={k} value={k} />
          ))}
        </datalist>
      </Campo>

      <Campo rotulo="system" dica="a instrução permanente; é o que vai marcado para cache">
        <textarea
          value={a.system}
          onChange={(e) => mudar({ system: e.target.value })}
          rows={5}
          className={`${CAMPO} font-mono text-[11px] leading-snug`}
        />
      </Campo>

      <Campo
        rotulo="prompt"
        dica="template sobre o item: {campo} vira o valor do payload"
        alerta={
          semInterpolacao
            ? "não interpola nada: todo item receberia o MESMO texto, e o agente responderia sem ler o item"
            : null
        }
      >
        <textarea
          value={a.prompt}
          onChange={(e) => mudar({ prompt: e.target.value })}
          rows={3}
          placeholder="{titulo}&#10;&#10;{corpo}"
          className={`${CAMPO} font-mono text-[11px] leading-snug`}
        />
      </Campo>

      <Campo rotulo="tipos" dica="vocabulário FECHADO de saída, separado por vírgula">
        <input
          value={a.tipos.join(", ")}
          onChange={(e) =>
            mudar({
              tipos: e.target.value
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean),
            })
          }
          placeholder="BUG, FEATURE, DUVIDA"
          spellCheck={false}
          className={`${CAMPO} font-mono text-[11px]`}
        />
      </Campo>

      <Campo
        rotulo="abstem_com"
        dica="o rótulo de “não sei”. NÃO pode ser um dos tipos"
        alerta={
          a.tipos.includes(a.abstem_com)
            ? `“${a.abstem_com}” é tipo E abstenção: os casos com esse tipo esperado sairiam do denominador da precisão. Custou 16 de 50 casos uma vez`
            : null
        }
      >
        <input
          value={a.abstem_com}
          onChange={(e) => mudar({ abstem_com: e.target.value })}
          spellCheck={false}
          className={`${CAMPO} font-mono text-[11px]`}
        />
      </Campo>

      <Campo
        rotulo="ferramentas"
        dica={
          catalogo.ferramentas.length
            ? "o agente recebe as que DECLARA, não as que existem no catálogo"
            : "o catálogo ainda não publica ferramenta nenhuma"
        }
      >
        <div className="grid gap-1">
          {catalogo.ferramentas.map((f) => (
            <label key={f.nome} className="flex items-start gap-2 text-[11.5px]" title={f.descricao}>
              <input
                type="checkbox"
                checked={a.ferramentas.includes(f.nome)}
                onChange={(e) =>
                  mudar({
                    ferramentas: e.target.checked
                      ? [...a.ferramentas, f.nome]
                      : a.ferramentas.filter((n) => n !== f.nome),
                  })
                }
                className="mt-0.5"
              />
              <span className="font-mono text-[11px] text-neutral-600 dark:text-noite-fraca">
                {f.nome}
              </span>
            </label>
          ))}
        </div>
      </Campo>

      {/* O TETO, em duas escalas. `budget_microcents` é o campo porque a
          constraint de dinheiro do projeto proíbe float acumulando; o dólar ao
          lado é derivado, só para leitura. */}
      <Campo rotulo="teto por item (µ¢)" dica={`≈ US$ ${(a.budget_microcents / 1e8).toFixed(4)}`}>
        <input
          type="number"
          value={a.budget_microcents}
          onChange={(e) => mudar({ budget_microcents: parseInt(e.target.value, 10) })}
          className={`${CAMPO} text-right font-mono`}
        />
      </Campo>

      <Campo rotulo="max_turns" dica="quantas idas ao modelo por item, no máximo">
        <input
          type="number"
          value={a.max_turns}
          onChange={(e) => mudar({ max_turns: parseInt(e.target.value, 10) })}
          className={`${CAMPO} text-right font-mono`}
        />
      </Campo>

      <Remover onClick={() => onRemover(no.id)} />
    </Secao>
  );
}

function Campo({
  rotulo,
  dica,
  alerta,
  children,
}: {
  rotulo: string;
  dica?: string;
  alerta?: string | null;
  children: React.ReactNode;
}) {
  return (
    <label className="mb-2.5 block">
      <span className="mb-0.5 block text-[11.5px] text-neutral-600 dark:text-noite-fraca">
        {rotulo}
      </span>
      {children}
      {dica && (
        <span className="mt-0.5 block text-[10.5px] leading-snug text-neutral-400 dark:text-noite-fraca">
          {dica}
        </span>
      )}
      {alerta && (
        <span className="mt-1 block rounded bg-lacuna-fundo px-2 py-1 text-[10.5px] leading-snug text-lacuna dark:bg-noite-lacuna-fundo dark:text-noite-crew">
          {alerta}
        </span>
      )}
    </label>
  );
}

function Remover({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-[11.5px] text-red-700 underline hover:text-red-800 dark:text-red-400"
    >
      remover do workflow
    </button>
  );
}

function Secao({
  titulo,
  ajuda,
  children,
}: {
  titulo: string;
  ajuda?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-5">
      <h2 className="mb-0.5 text-[12.5px] font-semibold tracking-wide">{titulo}</h2>
      {ajuda && (
        <p className="mb-2 text-[11px] leading-snug text-neutral-500 dark:text-noite-fraca">
          {ajuda}
        </p>
      )}
      {children}
    </section>
  );
}
