// Compositor de cascata. Vanilla, como o resto do web/ — a decisão de não ter
// build step é do projeto, não desta tela.
//
// A propriedade que torna este canvas honesto está no SERVIDOR: a ordem da
// cascata é `Stage.ordered()`, por classe de custo, e não existe entrada que a
// inverta. Esta tela não tem drag-and-drop de ordenação porque não HÁ ordem
// para arrastar — e essa ausência é o recurso, não a limitação.
//
// O §3.5 do spec chama de "decoração" uma tela que desenha uma coisa e executa
// outra. A defesa aqui é estrutural: depois de salvar, o que a tela mostra é a
// definição CONSTRUÍDA que voltou do servidor, não o que o usuário montou.

const ORDEM_CLASSE = ["REGRA", "AGENTE", "CREW", "HUMANO"];

const estado = {
  catalogo: [],
  escolhidos: [], // [{nome, parametros: {…}}]
};

const $ = (id) => document.getElementById(id);

async function carregar() {
  const r = await fetch("/api/catalogo");
  if (!r.ok) {
    $("erro").textContent = "não foi possível carregar o catálogo";
    return;
  }
  estado.catalogo = await r.json();
  desenharPaleta();
  desenharCascata();
}

function entrada(nome) {
  return estado.catalogo.find((e) => e.nome === nome);
}

function desenharPaleta() {
  const ul = $("catalogo");
  ul.textContent = "";
  for (const e of estado.catalogo) {
    const usado = estado.escolhidos.some((x) => x.nome === e.nome);
    const li = document.createElement("li");
    li.className = `cartao classe-${e.cost_class.toLowerCase()}${usado ? " usado" : ""}`;

    const b = document.createElement("button");
    b.type = "button";
    b.disabled = usado;
    // O motivo de estar desabilitado fica no próprio botão: `construir`
    // recusa resolver repetido porque o segundo rodaria sobre o pool que o
    // primeiro esvaziou. Dizer isso aqui evita que o usuário descubra no 422.
    b.title = usado
      ? "já está na cascata; o segundo rodaria sobre o pool que o primeiro esvaziou"
      : `acrescentar ${e.nome}`;
    b.innerHTML =
      `<span class="nome">${e.nome}</span>` +
      `<span class="classe">${e.cost_class}</span>` +
      `<span class="resumo">${e.resumo}</span>`;
    b.addEventListener("click", () => acrescentar(e.nome));
    li.appendChild(b);
    ul.appendChild(li);
  }
}

function acrescentar(nome) {
  const e = entrada(nome);
  const parametros = {};
  for (const p of e.parametros) parametros[p.nome] = p.default;
  estado.escolhidos.push({ nome, parametros });
  desenharPaleta();
  desenharCascata();
}

function remover(nome) {
  estado.escolhidos = estado.escolhidos.filter((x) => x.nome !== nome);
  desenharPaleta();
  desenharCascata();
}

// A ordem que a tela MOSTRA é a mesma que `Stage.ordered()` produz: ordenado
// por classe de custo, e ESTÁVEL dentro da classe — dois resolvers de classe
// REGRA rodam na ordem em que o autor os escreveu.
//
// `Array.prototype.sort` também é estável desde o ES2019, então esta função e
// `sorted()` do Python concordam sem que ninguém precise combinar. Se um dia
// deixassem de concordar, a tela desenharia uma execução que não acontece — e
// é por isso que `test_a_ordem_enviada_e_IGNORADA` compara contra o que o
// SERVIDOR devolve, não contra o que esta função produz.
function emOrdemDeExecucao() {
  return [...estado.escolhidos].sort((a, b) => {
    const ca = ORDEM_CLASSE.indexOf(entrada(a.nome).cost_class);
    const cb = ORDEM_CLASSE.indexOf(entrada(b.nome).cost_class);
    return ca - cb;
  });
}

function desenharCascata() {
  const ol = $("escolhidos");
  ol.textContent = "";
  const escolhidos = emOrdemDeExecucao();

  $("ajuda-cascata").textContent = escolhidos.length
    ? "Na ordem em que vão rodar. Entre classes, quem manda é o custo; dentro de uma classe, a ordem em que você acrescentou."
    : "Vazia. Uma cascata sem resolver não resolve nada.";

  for (const item of escolhidos) {
    const e = entrada(item.nome);
    const li = document.createElement("li");
    li.className = `cartao classe-${e.cost_class.toLowerCase()}`;

    const cab = document.createElement("div");
    cab.className = "cabecalho";
    cab.innerHTML =
      `<span class="nome">${e.nome}</span><span class="classe">${e.cost_class}</span>`;
    const x = document.createElement("button");
    x.type = "button";
    x.className = "remover";
    x.textContent = "remover";
    x.addEventListener("click", () => remover(item.nome));
    cab.appendChild(x);
    li.appendChild(cab);

    for (const p of e.parametros) {
      const label = document.createElement("label");
      label.className = "parametro";
      label.textContent = p.nome;
      const input = document.createElement("input");
      input.type = "number";
      input.value = item.parametros[p.nome];
      input.addEventListener("input", () => {
        // `parseInt` e não `Number`: campo vazio vira NaN em vez de 0, e o
        // servidor recusa. Um 0 silencioso aqui viraria `max_cents=0`, que é
        // uma cascata legítima e não o que a pessoa quis.
        item.parametros[p.nome] = parseInt(input.value, 10);
      });
      label.appendChild(input);
      const dica = document.createElement("small");
      dica.textContent = p.descricao;
      label.appendChild(dica);
      li.appendChild(label);
    }
    ol.appendChild(li);
  }

  const classes = escolhidos.map((i) => entrada(i.nome).cost_class);
  $("resumo-custo").textContent = classes.length
    ? (classes.includes("AGENTE")
        ? "Esta cascata tem classe AGENTE: ela gasta dinheiro ao rodar, e a API não a executa."
        : "Nenhum resolver paga por token. Esta cascata roda de graça.")
    : "";

  $("salvar").disabled = escolhidos.length === 0;
}

async function salvar() {
  $("erro").textContent = "";
  $("resultado").hidden = true;

  const corpo = {
    id: $("campo-id").value.trim(),
    nome: $("campo-nome").value.trim() || $("campo-id").value.trim(),
    justificativa: $("campo-justificativa").value.trim(),
    // Envia na ordem de execução por higiene, mas o servidor não depende disso
    // — ele reordena de qualquer jeito. Se um dia dependesse, a ordem viraria
    // um campo, e aí a tela poderia desenhar uma execução que não acontece.
    resolvers: emOrdemDeExecucao().map((i) => ({
      nome: i.nome,
      parametros: i.parametros,
    })),
  };

  const r = await fetch("/api/receitas", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(corpo),
  });

  if (!r.ok) {
    const dados = await r.json().catch(() => ({}));
    // A mensagem do domínio, não uma genérica. `construir` escreve erros para
    // serem lidos — o grill depende disso para o modelo se corrigir, e a
    // pessoa merece o mesmo texto.
    $("erro").textContent = mensagemDeErro(dados, r.status);
    return;
  }

  desenharConstruida(await r.json());
}

function mensagemDeErro(dados, status) {
  const d = dados.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) return d[0].msg || JSON.stringify(d[0]);
  return `erro ${status}`;
}

function desenharConstruida(workflow) {
  const alvo = $("construida");
  alvo.textContent = "";
  for (const stage of workflow.stages) {
    const h = document.createElement("h3");
    h.textContent = stage.name;
    alvo.appendChild(h);
    const ol = document.createElement("ol");
    ol.className = "cartoes";
    for (const r of stage.cascade) {
      const li = document.createElement("li");
      li.className = `cartao classe-${r.cost_class.toLowerCase()}`;
      li.innerHTML =
        `<span class="nome">${r.name}</span>` +
        `<span class="classe">${r.cost_class}</span>` +
        `<span class="resumo">${r.summary}</span>`;
      ol.appendChild(li);
    }
    alvo.appendChild(ol);
  }
  $("resultado").hidden = false;
  $("resultado").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

$("salvar").addEventListener("click", salvar);
carregar();
