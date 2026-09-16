// Canvas de composição: nós arrastáveis, arestas DERIVADAS.
//
// A diferença para um editor de fluxograma comum — e é a tese da tela inteira:
// num canvas de agentes convencional você DESENHA as setas, e a execução tenta
// seguir o que você desenhou. Aqui a seta é saída, não entrada. Você posiciona
// os nós onde quiser; a flecha aponta sempre na ordem em que a cascata roda,
// que é `Stage.ordered()` — por classe de custo, estável dentro da classe.
//
// Arrastar um nó para "antes" de outro não muda nada, e a seta volta a apontar
// no mesmo sentido. Isso não é limitação: é a regra ficando visível toda vez
// que alguém tenta furá-la. O §3.5 chama de DECORAÇÃO uma tela que desenha uma
// coisa e executa outra; aqui a tela é incapaz de desenhar a outra.

const ORDEM_CLASSE = ["REGRA", "AGENTE", "CREW", "HUMANO"];
const NO_L = 230; // largura do nó, em px — casada com `.no` no CSS
const NO_H = 104;

const estado = {
  catalogo: [],
  nos: [], // [{nome, parametros, x, y}]
  selecionado: null,
};

const $ = (id) => document.getElementById(id);
const entrada = (nome) => estado.catalogo.find((e) => e.nome === nome);

// ---------------------------------------------------------------------------
// carga
// ---------------------------------------------------------------------------

async function carregar() {
  const r = await fetch("/api/catalogo");
  if (!r.ok) {
    $("erro").textContent = "não foi possível carregar o catálogo";
    return;
  }
  estado.catalogo = await r.json();
  desenharPaleta();
  redesenhar();
}

// ---------------------------------------------------------------------------
// ordem de execução — a única fonte das arestas
// ---------------------------------------------------------------------------

// `Array.prototype.sort` é estável desde o ES2019, e `sorted()` do Python
// também é. Os dois concordam sem ninguém combinar — mas o teste que garante a
// ordem compara contra o que o SERVIDOR devolve, nunca contra esta função.
function emOrdemDeExecucao() {
  return [...estado.nos].sort(
    (a, b) =>
      ORDEM_CLASSE.indexOf(entrada(a.nome).cost_class) -
      ORDEM_CLASSE.indexOf(entrada(b.nome).cost_class),
  );
}

// ---------------------------------------------------------------------------
// paleta
// ---------------------------------------------------------------------------

function desenharPaleta() {
  const ul = $("catalogo");
  ul.textContent = "";
  for (const e of estado.catalogo) {
    const usado = estado.nos.some((n) => n.nome === e.nome);
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = `item classe-${e.cost_class.toLowerCase()}${usado ? " usado" : ""}`;
    b.disabled = usado;
    // O motivo de estar desabilitado no próprio botão: `construir` recusa
    // resolver repetido porque o segundo rodaria sobre o pool que o primeiro
    // esvaziou. Dizer aqui evita descobrir no 422.
    b.title = usado
      ? "já está na cascata; o segundo rodaria sobre o pool que o primeiro esvaziou"
      : `acrescentar ${e.nome}`;
    b.innerHTML =
      `<span class="nome">${e.nome}</span>` +
      `<span class="tag">${e.cost_class}</span>` +
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
  // `fixado` vira true quando alguém ARRASTA. Enquanto for false, o nó se
  // reorganiza sozinho na ordem de execução a cada mudança — é o que faz o
  // grafo nascer legível sem obrigar ninguém a arrumar nada.
  estado.nos.push({ nome, parametros, x: 0, y: 0, fixado: false });
  estado.selecionado = nome;
  autoLayout();
  desenharPaleta();
  redesenhar();
}

function remover(nome) {
  estado.nos = estado.nos.filter((n) => n.nome !== nome);
  if (estado.selecionado === nome) estado.selecionado = null;
  autoLayout();
  desenharPaleta();
  redesenhar();
}

// Reflui os nós NÃO FIXADOS na ordem de execução; quem foi arrastado fica onde
// está.
//
// A primeira versão posicionava por índice só quem ainda não tinha posição — e
// isso colidia: acrescentar `revisor` (índice 0) e depois `L1` (que vira índice
// 0) dava a mesma coordenada aos dois, e um sumia atrás do outro. Visto na
// tela, não num teste: o nó não estava ausente, estava escondido, e nenhuma
// asserção sobre "existe no DOM" teria falhado.
function autoLayout() {
  const canvas = $("canvas");
  const centro = Math.max(40, (canvas.clientWidth - NO_L) / 2);
  let i = 0;
  for (const n of emOrdemDeExecucao()) {
    if (!n.fixado) {
      n.x = centro;
      n.y = 48 + i * (NO_H + 64);
    }
    i++;
  }
}

// ---------------------------------------------------------------------------
// desenho
// ---------------------------------------------------------------------------

function redesenhar() {
  desenharNos();
  desenharArestas();
  desenharInspetor();
  desenharResumo();
  $("vazio").hidden = estado.nos.length > 0;
  $("salvar").disabled = estado.nos.length === 0;
}

function desenharNos() {
  const alvo = $("nos");
  alvo.textContent = "";
  for (const n of emOrdemDeExecucao()) {
    const e = entrada(n.nome);
    const div = document.createElement("div");
    div.className =
      `no classe-${e.cost_class.toLowerCase()}` +
      (estado.selecionado === n.nome ? " selecionado" : "");
    div.style.left = `${n.x}px`;
    div.style.top = `${n.y}px`;
    div.dataset.nome = n.nome;
    div.tabIndex = 0;

    const params = e.parametros
      .map((p) => `${p.nome}=${n.parametros[p.nome]}`)
      .join("  ");
    div.innerHTML =
      `<div class="no-topo"><span class="nome">${e.nome}</span>` +
      `<span class="tag">${e.cost_class}</span></div>` +
      `<p class="no-resumo">${e.resumo}</p>` +
      (params ? `<p class="no-params">${params}</p>` : "");

    div.addEventListener("pointerdown", (ev) => comecarArraste(ev, n, div));
    div.addEventListener("click", () => {
      estado.selecionado = n.nome;
      redesenhar();
    });
    alvo.appendChild(div);
  }
}

// As arestas ligam cada nó ao PRÓXIMO na ordem de execução. Elas são
// recalculadas a cada arraste — por isso arrastar nunca muda o sentido.
function desenharArestas() {
  const svg = $("arestas");
  for (const antigo of [...svg.querySelectorAll("path, text")]) antigo.remove();

  const ordem = emOrdemDeExecucao();
  for (let i = 0; i < ordem.length - 1; i++) {
    const a = ordem[i];
    const b = ordem[i + 1];
    const x1 = a.x + NO_L / 2;
    const y1 = a.y + NO_H;
    const x2 = b.x + NO_L / 2;
    const y2 = b.y;
    const meio = (y1 + y2) / 2;

    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", `M ${x1} ${y1} C ${x1} ${meio}, ${x2} ${meio}, ${x2} ${y2}`);
    p.setAttribute("class", "aresta");
    p.setAttribute("marker-end", "url(#seta)");
    svg.appendChild(p);

    // A transição de classe é o momento em que a regra age; dizer o nome dela
    // na aresta é o que ensina a regra sem uma legenda.
    const ca = entrada(a.nome).cost_class;
    const cb = entrada(b.nome).cost_class;
    if (ca !== cb) {
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", (x1 + x2) / 2 + 8);
      t.setAttribute("y", meio);
      t.setAttribute("class", "rotulo-aresta");
      t.textContent = "o que sobrou";
      svg.appendChild(t);
    }
  }
}

function desenharInspetor() {
  const n = estado.nos.find((x) => x.nome === estado.selecionado);
  $("inspetor").hidden = !n;
  if (!n) return;
  const e = entrada(n.nome);
  $("inspetor-nome").textContent = e.nome;
  $("inspetor-resumo").textContent = e.resumo;

  const alvo = $("inspetor-parametros");
  alvo.textContent = "";
  if (!e.parametros.length) {
    const p = document.createElement("p");
    p.className = "ajuda";
    p.textContent = "sem parâmetros.";
    alvo.appendChild(p);
  }
  for (const spec of e.parametros) {
    const label = document.createElement("label");
    label.className = "parametro";
    label.textContent = spec.nome;
    const input = document.createElement("input");
    input.type = "number";
    input.value = n.parametros[spec.nome];
    input.addEventListener("input", () => {
      // `parseInt` e não `Number`: campo vazio vira NaN e o servidor recusa. Um
      // 0 silencioso viraria `max_cents=0`, que é uma cascata legítima e não o
      // que a pessoa quis.
      n.parametros[spec.nome] = parseInt(input.value, 10);
      desenharNos();
      desenharArestas();
    });
    label.appendChild(input);
    const dica = document.createElement("small");
    dica.textContent = spec.descricao;
    label.appendChild(dica);
    alvo.appendChild(label);
  }
}

function desenharResumo() {
  const classes = estado.nos.map((n) => entrada(n.nome).cost_class);
  const caixa = $("resumo-custo");
  if (!classes.length) {
    caixa.textContent = "";
    caixa.hidden = true;
    return;
  }
  caixa.hidden = false;
  caixa.textContent = classes.includes("AGENTE")
    ? "Tem classe AGENTE: gasta dinheiro ao rodar, e a API não a executa."
    : "Nenhum resolver paga por token. Roda de graça.";
  caixa.className = `bloco custo ${classes.includes("AGENTE") ? "paga" : "gratis"}`;

  // O "Process Type" desta tela. Fixo, e explicado — não é um seletor porque
  // não há o que selecionar.
  $("processo").textContent =
    `ordem: por classe de custo (${[...new Set(emOrdemDeExecucao()
      .map((n) => entrada(n.nome).cost_class))].join(" → ")})`;
}

// ---------------------------------------------------------------------------
// arraste
// ---------------------------------------------------------------------------

function comecarArraste(ev, no, div) {
  if (ev.button !== 0) return;
  const canvas = $("canvas");
  const rect = canvas.getBoundingClientRect();
  const dx = ev.clientX - rect.left - no.x;
  const dy = ev.clientY - rect.top - no.y;
  div.setPointerCapture(ev.pointerId);
  div.classList.add("arrastando");
  // A partir daqui o nó é da pessoa: o refluxo automático não mexe mais nele.
  no.fixado = true;

  const mover = (e) => {
    no.x = Math.max(0, e.clientX - rect.left - dx);
    no.y = Math.max(0, e.clientY - rect.top - dy);
    div.style.left = `${no.x}px`;
    div.style.top = `${no.y}px`;
    // Só as arestas: redesenhar os nós no meio do arraste trocaria o elemento
    // que está capturando o ponteiro e o arraste morreria no primeiro pixel.
    desenharArestas();
  };
  const soltar = () => {
    div.classList.remove("arrastando");
    div.removeEventListener("pointermove", mover);
    div.removeEventListener("pointerup", soltar);
  };
  div.addEventListener("pointermove", mover);
  div.addEventListener("pointerup", soltar);
}

// ---------------------------------------------------------------------------
// salvar
// ---------------------------------------------------------------------------

async function salvar() {
  $("erro").textContent = "";
  $("resultado").hidden = true;

  const corpo = {
    id: $("campo-id").value.trim(),
    nome: $("campo-nome").value.trim() || $("campo-id").value.trim(),
    justificativa: "",
    // A posição no canvas NÃO vai junto. É arranjo visual, não definição — e
    // uma `Receita` que carregasse coordenadas passaria a ter versão diferente
    // só porque alguém arrastou um nó.
    resolvers: emOrdemDeExecucao().map((n) => ({
      nome: n.nome,
      parametros: n.parametros,
    })),
  };

  const r = await fetch("/api/receitas", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(corpo),
  });

  if (!r.ok) {
    const dados = await r.json().catch(() => ({}));
    // A mensagem do DOMÍNIO. `construir` escreve erros para serem lidos — o
    // grill depende disso para o modelo se corrigir, e a pessoa merece o mesmo.
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
    for (const r of stage.cascade) {
      const li = document.createElement("li");
      li.innerHTML =
        `<span class="item classe-${r.cost_class.toLowerCase()}">` +
        `<span class="nome">${r.name}</span>` +
        `<span class="tag">${r.cost_class}</span>` +
        `<span class="resumo">${r.summary}</span></span>`;
      alvo.appendChild(li);
    }
  }
  $("resultado").hidden = false;
}

$("salvar").addEventListener("click", salvar);
$("remover").addEventListener("click", () => remover(estado.selecionado));
window.addEventListener("resize", () => {
  desenharArestas();
});
carregar();
