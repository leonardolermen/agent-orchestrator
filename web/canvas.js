// O canvas desenha o que a API mediu. Nenhum número é escrito aqui:
// se a API não mediu, a tela diz "não medido" em vez de inventar.
//
// `seed`/`n`/`taxa_divergencia` vêm da URL, não de uma constante local. Esta
// página e `fila.html` precisam concordar sobre QUAL dataset estão olhando —
// a fila é escopada por `dataset_id(seed, n, taxa)` (ver
// `orchestrator/review/fila.py`), então uma decisão tomada na fila só
// aparece aqui se as duas páginas apontarem para o MESMO dataset. Uma
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

// O link para a fila carrega o MESMO dataset — é o que permite ao revisor
// sair do canvas, decidir, e voltar sem perder de vista o que estava vendo.
document.getElementById("link-fila").href =
  `/fila.html?${new URLSearchParams(PEDIDO)}`;

async function carregar() {
  const [definicao, execucao] = await Promise.all([
    fetch("/api/workflows/conciliacao").then((r) => r.json()),
    fetch("/api/workflows/conciliacao/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(PEDIDO),
    }).then((r) => r.json()),
  ]);

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
    caixa.innerHTML = `<h2>${stage.name}</h2>`;

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

carregar().catch((erro) => {
  document.getElementById("titulo").textContent = "falhou ao carregar";
  document.getElementById("proveniencia").textContent = String(erro);
});
