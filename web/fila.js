// A tela não decide nada: ela mostra o que a API mediu e manda de volta o que
// o humano escolheu. Nenhum número é escrito aqui.
const PARAMS = new URLSearchParams({ seed: 1, n: 30, taxa_divergencia: 0.15 });

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
  const evidencia = item.evidencia.map((e) => `<li>${e}</li>`).join("");

  el.innerHTML = `
    <h2>${item.divergence_id}</h2>
    <table class="lancamentos"><tbody>${lancamentos}</tbody></table>
    <p class="proposta">
      <span class="tipo">${item.tipo}</span>
      <span class="confianca conf-${item.confianca.toLowerCase()}">${item.confianca}</span>
      ${item.explicacao}
    </p>
    <ul class="evidencia">${evidencia}</ul>
    <div class="acoes">
      <button data-v="aceitar">Aceitar</button>
      <button data-v="corrigir">Corrigir</button>
      <button data-v="rejeitar">Rejeitar</button>
    </div>
    <div class="correcao" hidden>
      <select class="tipo-corrigido">${TIPOS.map((t) => `<option>${t}</option>`).join("")}</select>
      <input class="ids-corrigidos" placeholder="ids a conciliar, separados por vírgula">
    </div>`;

  const correcao = el.querySelector(".correcao");
  el.querySelectorAll(".acoes button").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.dataset.v === "corrigir" && correcao.hidden) {
        correcao.hidden = false;
        return;
      }
      decidir(item, b.dataset.v, correcao, el);
    });
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

  const r = await fetch(
    `/api/fila/conciliacao/${item.divergence_id}/decisao?${PARAMS}`,
    { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(corpo) });
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
