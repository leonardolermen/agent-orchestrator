// O canvas desenha o que a API mediu. Nenhum número é escrito aqui:
// se a API não mediu, a tela diz "não medido" em vez de inventar.
const PEDIDO = { seed: 1, n: 300, taxa_divergencia: 0.15 };

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
  return medida.microcents === 0
    ? "R$ 0"
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
