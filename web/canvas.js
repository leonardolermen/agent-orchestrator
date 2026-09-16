// O canvas desenha o que a API mediu. Nenhum número é escrito aqui:
// se a API não mediu, a tela diz "não medido" em vez de inventar.
//
// `seed`/`n`/`taxa_divergencia`/`workflow` vêm da URL, não de uma constante
// local. Esta página e `fila.html` precisam concordar sobre QUAL fila estão
// olhando — e a fila é escopada em DUAS dimensões independentes:
// `caminho_da_fila(workflow_id, dataset)` (ver `orchestrator/review/fila.py`)
// toma o `workflow_id` como primeiro argumento, separado do
// `dataset_id(seed, n, taxa)`. Uma decisão tomada na fila só aparece aqui se
// as duas páginas apontarem para o MESMO workflow E o MESMO dataset. Uma
// constante duplicada nos dois arquivos é uma promessa que já quebrou uma
// vez — ver DECISOES.md, P4.14 — porque nada além de lembrança humana as
// mantinha iguais. A URL é a única fonte que as duas podem compartilhar sem
// depender disso.
const QUERY = new URLSearchParams(location.search);

function parametro(nome, padrao) {
  const bruto = QUERY.get(nome);
  if (bruto === null || bruto === "") return padrao;
  const numero = Number(bruto);
  return Number.isFinite(numero) ? numero : padrao;
}

// Os mesmos padrões de `RunRequest` (api/schemas.py) e de `fila.js` — os
// três arquivos concordam porque os três leem do mesmo lugar (a URL) com o
// mesmo valor de reserva, não porque alguém copiou o número três vezes.
const PEDIDO = {
  seed: parametro("seed", 1),
  n: parametro("n", 300),
  taxa_divergencia: parametro("taxa_divergencia", 0.15),
};

// O id do workflow ativo vem do MESMO `location.search` que `seed`/`n`, com
// o MESMO tipo de leitura — não uma constante local com default próprio,
// que foi exatamente o que fez canvas e fila apontarem para dados
// diferentes numa fatia anterior (ver o aviso no topo deste arquivo).
const WORKFLOW = QUERY.get("workflow") || "conciliacao";

// O link para a fila carrega o MESMO dataset E o MESMO workflow — sem o
// `workflow`, o revisor cairia sempre na fila do conciliador embutido
// (`fila.js` também lê `workflow` de `location.search`, com o mesmo
// default), tomando decisões que pareceriam ser sobre um workflow mas eram
// sobre outro, em silêncio. `PEDIDO` continua só com os três campos de
// `RunRequest` — é o corpo literal do POST /runs — então o `workflow` é
// acrescentado aqui, não lá.
document.getElementById("link-fila").href =
  `/fila.html?${new URLSearchParams({ ...PEDIDO, workflow: WORKFLOW })}`;

// `fetch` só rejeita em falha de rede — um 409, 404 ou 500 chegam com
// `ok === false` e (quando o servidor escreveu um) um corpo JSON
// `{"detail": "..."}` que `.then((r) => r.json())` sozinho ignoraria. A CLI
// do grill imprime `?workflow=<id>` como último passo do fluxo — se a
// receita tiver classe AGENTE, esse é o link que o parceiro clica, direto,
// sem passar pelo seletor (cuja opção desabilitada só protege quem troca de
// workflow PELO dropdown). Por isso a checagem de `ok` é obrigatória em todo
// fetch desta página, não só no de `carregar()`.
async function buscarJSON(url, opcoes) {
  const r = await fetch(url, opcoes);
  const corpo = await r.json().catch(() => null);
  return { ok: r.ok, status: r.status, corpo };
}

async function popularSeletor() {
  const resp = await buscarJSON("/api/workflows");
  const select = document.getElementById("workflow");
  select.innerHTML = "";
  if (!resp.ok) {
    // Sem isto, uma falha aqui morria num `console.error` (ver o `.catch`
    // no fim do arquivo) e o `<select>` ficava vazio sem nenhum sinal para
    // quem está olhando a tela — silêncio que, para o alvo desta task, é o
    // mesmo defeito do 409 desenhado como cascata.
    const opt = document.createElement("option");
    opt.textContent = "falha ao listar workflows";
    opt.disabled = true;
    select.appendChild(opt);
    throw new Error(resp.corpo?.detail ?? `falhou ao listar workflows (${resp.status})`);
  }
  for (const w of resp.corpo) {
    const opt = document.createElement("option");
    opt.value = w.id;
    // textContent, nunca innerHTML: `nome` vem de uma receita gerada por um
    // modelo a partir do texto do parceiro. Tratar como dado, não markup.
    opt.textContent = w.executavel ? w.nome : `${w.nome} (etapa paga)`;
    opt.disabled = !w.executavel;
    if (w.id === WORKFLOW) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener("change", () => {
    QUERY.set("workflow", select.value);
    location.search = QUERY.toString();
  });
}

async function carregar() {
  const [definicaoResp, execucaoResp] = await Promise.all([
    buscarJSON(`/api/workflows/${WORKFLOW}`),
    buscarJSON(`/api/workflows/${WORKFLOW}/runs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(PEDIDO),
    }),
  ]);

  const falha = !definicaoResp.ok
    ? definicaoResp
    : !execucaoResp.ok
      ? execucaoResp
      : null;
  if (falha) {
    // `detail` é texto do servidor, mas carrega o id do workflow — escolhido
    // por quem gerou a receita a partir da prosa do parceiro. `textContent`,
    // nunca `innerHTML`, pela mesma razão que `nome` em `popularSeletor`.
    document.getElementById("titulo").textContent = "workflow indisponível";
    document.getElementById("proveniencia").textContent =
      falha.corpo?.detail ?? `falhou ao carregar (${falha.status})`;
    document.getElementById("stages").innerHTML = "";
    return;
  }
  const definicao = definicaoResp.corpo;
  const execucao = execucaoResp.corpo;

  document.getElementById("titulo").textContent = definicao.name;
  document.getElementById("proveniencia").textContent =
    `medido em ${execucao.bank_total} lançamentos sintéticos ` +
    `(semente ${execucao.seed}, n=${execucao.n})`;

  const porNome = new Map(execucao.by_resolver.map((r) => [r.name, r]));
  const alvo = document.getElementById("stages");
  alvo.innerHTML = "";

  for (const stage of definicao.stages) {
    const caixa = document.createElement("section");
    caixa.className = "stage";
    // `textContent`, como em `popularSeletor` e no `detail` de erro: hoje
    // `stage.name` é fixo em `construir()` ("conciliar lançamentos"), mas era
    // o único ponto deste arquivo em que texto de um objeto gerado a partir
    // da prosa do parceiro virava markup. A exceção some antes de virar
    // regra.
    const titulo = document.createElement("h2");
    titulo.textContent = stage.name;
    caixa.appendChild(titulo);

    stage.cascade.forEach((resolver, i) => {
      const medida = porNome.get(resolver.name);
      const linha = document.createElement("div");
      linha.className = "resolver";
      linha.innerHTML = `
        <span class="ordem">${i + 1}</span>
        <span class="nome" title="${resolver.summary}">${resolver.name}</span>
        <span class="classe classe-${resolver.cost_class.toLowerCase()}">${resolver.cost_class}</span>
        <span class="custo">${formatarCusto(medida)}</span>
        <span class="taxa">${formatarTaxa(medida)}</span>`;
      caixa.appendChild(linha);
    });

    caixa.appendChild(lacuna(execucao.gap));
    alvo.appendChild(caixa);
  }
}

function formatarCusto(medida) {
  if (!medida) return "não medido";
  // Sempre USD: `microcents` nunca é reais, nem quando o valor é zero.
  return medida.microcents === 0
    ? "US$ 0"
    : `US$ ${(medida.microcents / 100000000).toFixed(6)}`;
}

function formatarTaxa(medida) {
  return medida ? `${(medida.rate * 100).toFixed(1)}%` : "—";
}

function lacuna(gap) {
  // A lacuna é o ponto mais valioso da tela: é onde o especialista diz
  // "tem regra sim, é o código de retorno do CNAB".
  const el = document.createElement("div");
  el.className = "resolver lacuna";
  el.innerHTML = `
    <span class="ordem">—</span>
    <span class="nome">sem resolver configurado</span>
    <span class="classe classe-lacuna">LACUNA</span>
    <span class="custo">—</span>
    <span class="taxa">${(gap.rate * 100).toFixed(1)}%</span>`;
  return el;
}

popularSeletor().catch((erro) => {
  console.error("falhou ao popular o seletor de workflows", erro);
});

carregar().catch((erro) => {
  document.getElementById("titulo").textContent = "falhou ao carregar";
  document.getElementById("proveniencia").textContent = String(erro);
});
