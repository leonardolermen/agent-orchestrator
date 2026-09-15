// A tela não decide nada: ela mostra o que a API mediu e manda de volta o que
// o humano escolheu. Nenhum número é escrito aqui.
//
// `seed`/`n`/`taxa_divergencia` vêm da URL, não de uma constante local. Esta
// página e o canvas (`/`, `canvas.js`) precisam concordar sobre QUAL dataset
// estão olhando — a fila é escopada por `dataset_id(seed, n, taxa)` (ver
// `orchestrator/review/fila.py`), então uma decisão tomada aqui só aparece
// no canvas se as duas páginas apontarem para o MESMO dataset. Uma constante
// duplicada nos dois arquivos é uma promessa que já quebrou uma vez — ver
// DECISOES.md, P4.14 — porque nada além de lembrança humana as mantinha
// iguais. A URL é a única fonte que as duas podem compartilhar sem depender
// disso.
const QUERY = new URLSearchParams(location.search);

function parametro(nome, padrao) {
  const bruto = QUERY.get(nome);
  if (bruto === null || bruto === "") return padrao;
  const numero = Number(bruto);
  return Number.isFinite(numero) ? numero : padrao;
}

// Mesmos padrões de `RunRequest` (api/schemas.py) e de `canvas.js`.
const PARAMS = new URLSearchParams({
  seed: parametro("seed", 1),
  n: parametro("n", 300),
  taxa_divergencia: parametro("taxa_divergencia", 0.15),
});

// O link de volta ao canvas carrega o MESMO dataset.
document.getElementById("link-canvas").href = `/?${PARAMS}`;

// A taxonomia do <select> de "corrigir" vem de `corpo.tipos`, servido pela
// API — nunca de uma lista escrita aqui. Duplicar os valores no front seria
// exatamente o drift que este projeto existe para recusar.
let TIPOS = [];

function autor() {
  const campo = document.getElementById("autor");
  try {
    if (!campo.value) campo.value = localStorage.getItem("autor") || "";
  } catch (e) { /* armazenamento bloqueado: segue sem lembrar */ }
  return campo.value.trim();
}

async function carregar() {
  const r = await fetch(`/api/fila/conciliacao?${PARAMS}`);
  if (!r.ok) throw new Error(`${r.status} ao ler a fila`);
  const corpo = await r.json();

  TIPOS = corpo.tipos;

  document.getElementById("proveniencia").textContent =
    `${corpo.itens.length} pendente(s) — dataset ${corpo.dataset}`;

  const alvo = document.getElementById("itens");
  alvo.innerHTML = "";
  for (const item of corpo.itens) alvo.appendChild(desenhar(item));
}

function desenhar(item) {
  const el = document.createElement("section");
  el.className = "item";
  const lancamentos = item.lancamentos
    .map((l) => `<tr><td>${l.lado}</td><td>${l.id}</td><td>${l.data}</td>
                 <td class="num">${(l.valor / 100).toFixed(2)}</td>
                 <td>${l.contraparte}</td><td>${l.documento ?? "—"}</td></tr>`)
    .join("");
  el.innerHTML = `
    <h2>${item.divergence_id}</h2>
    <table class="lancamentos"><tbody>${lancamentos}</tbody></table>
    <p class="proposta">
      <span class="tipo">${item.tipo}</span>
      <span class="confianca conf-${item.confianca.toLowerCase()}">${item.confianca}</span>
      <span class="explicacao"></span>
    </p>
    <ul class="evidencia"></ul>
    <div class="acoes">
      <button data-v="aceitar">Aceitar</button>
      <button data-v="corrigir" class="btn-corrigir" type="button">Corrigir</button>
      <button data-v="rejeitar">Rejeitar</button>
    </div>
    <div class="correcao">
      <select class="tipo-corrigido">${TIPOS.map((t) => `<option>${t}</option>`).join("")}</select>
      <input class="ids-corrigidos" placeholder="ids a conciliar, separados por vírgula">
      <button class="confirmar-correcao" type="button">Confirmar correção</button>
    </div>`;

  // `explicacao` e `evidencia` são texto livre que o AGENTE (um LLM) produziu
  // a partir do dataset — a primeira vez que o projeto deixa saída de modelo
  // virar DOM. `innerHTML` os interpretaria como marcação; `textContent` os
  // trata como o que são, texto, e nada que a proposta escreva pode injetar
  // uma tag. O resto do template continua vindo de campos do próprio dataset
  // (`lado`, `id`, `data`, `contraparte`, `documento`), não do modelo.
  el.querySelector(".explicacao").textContent = item.explicacao;
  const listaEvidencia = el.querySelector(".evidencia");
  for (const e of item.evidencia) {
    const li = document.createElement("li");
    li.textContent = e;
    listaEvidencia.appendChild(li);
  }

  // "Corrigir" só abre/fecha a caixa — nunca decide nada sozinho. Um clique
  // perdido (ou dois seguidos por engano) nesse botão não pode gravar uma
  // correção vazia no log; só "Confirmar correção", dentro da caixa, chama
  // `decidir`. Antes os dois papéis estavam no mesmo botão: o 1º clique
  // abria, o 2º já caía direto em `decidir("corrigir", ...)` com o `<select>`
  // ainda no primeiro tipo da lista e nenhum id — um "corrigir" inventado
  // que o backend aceita de bom grado (lista vazia é abstenção legítima) e
  // grava como decisão humana de verdade.
  const correcao = el.querySelector(".correcao");
  el.querySelector(".btn-corrigir").addEventListener("click", () => {
    correcao.classList.toggle("aberta");
  });
  el.querySelectorAll('.acoes button:not(.btn-corrigir)').forEach((b) => {
    b.addEventListener("click", () => decidir(item, b.dataset.v, correcao, el));
  });
  correcao.querySelector(".confirmar-correcao").addEventListener("click", () => {
    decidir(item, "corrigir", correcao, el);
  });
  return el;
}

async function decidir(item, veredito, correcao, el) {
  const quem = autor();
  if (!quem) { alert("preencha seu identificador antes de decidir"); return; }
  try { localStorage.setItem("autor", quem); } catch (e) { /* segue */ }

  const corpo = { veredito, autor: quem };
  if (veredito === "corrigir") {
    corpo.tipo = correcao.querySelector(".tipo-corrigido").value;
    corpo.conciliar_com = correcao.querySelector(".ids-corrigidos").value
      .split(",").map((s) => s.trim()).filter(Boolean);
  }

  let r;
  try {
    r = await fetch(
      `/api/fila/conciliacao/${item.divergence_id}/decisao?${PARAMS}`,
      { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(corpo) });
  } catch (erroDeRede) {
    // `fetch` rejeita ANTES de existir uma resposta quando a rede cai, o DNS
    // falha ou o pedido é abortado — sem este catch essa rejeição não tem
    // handler, e a tela não diz nada: o clique parece ter sumido no vácuo,
    // sem alerta e sem mudança nenhuma na lista.
    alert(`falha de rede ao decidir: ${erroDeRede}`);
    return;
  }
  if (!r.ok) {
    // O corpo de um 422 carrega em `detail` a razão exata — "corrigir exige
    // `tipo`", ids inexistentes, ação malformada pedindo `corrigir` no lugar
    // de `aceitar`. Mostrar só o código deixaria o revisor sem saber o que
    // corrigir; por isso o corpo é lido antes do alerta, com um retrato
    // genérico como reserva caso a resposta não seja JSON.
    const erro = await r.json().catch(() => null);
    alert(`falhou (${r.status}): ${erro?.detail ?? "erro ao decidir"}`);
    return;
  }
  el.remove();
}

carregar().catch((erro) => {
  document.getElementById("proveniencia").textContent = `falhou ao carregar: ${erro}`;
});
