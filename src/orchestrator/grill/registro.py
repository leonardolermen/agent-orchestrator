"""Receitas e recusas em disco.

Nada aqui é versionado: a `justificativa` de uma receita carrega a descrição do
problema do parceiro — dado de terceiro, que o spec pai proíbe versionar. Ver o
`.gitignore`, que é allowlist sob `data/`.
"""

import dataclasses
import json
import sys
from pathlib import Path

from orchestrator.grill.receita import Receita, ResolverReceita, de_json, para_json, validar_id

_RAIZ_PADRAO = Path("data")

# Nomes que o CARDÁPIO do grill usava e que a Task 3 (catálogo plano) mudou.
# Um arquivo já gravado em `data/workflows/` fala o vocabulário de quando foi
# salvo — ele não pode ser reescrito para acompanhar um rename de código. Sem
# isto, `de_json` devolve a `Receita` intacta com o nome antigo, e
# `grill.receita.construir` recusa com "resolver desconhecido: 'agente'": o
# achado real foi `data/workflows/pago.json`, salvo com "agente", que passou a
# derrubar `GET /api/workflows/pago` e `POST /api/workflows/pago/runs` com 500
# — trabalho do dono quebrando em silêncio, não um caso de teste.
#
# Cresce só quando um rename de verdade acontecer — não é um mapa de
# compatibilidade permanente para nomes que ainda estão vivos.
_NOMES_LEGADOS: dict[str, str] = {"agente": "investigador"}


def _migrar_nomes_legados(receita: Receita, caminho: Path) -> Receita:
    """Traduz nomes de bloco antigos, avisando — nunca em silêncio.

    Não é o shim de compatibilidade que o plano da Task 3 proibiu: aquela
    regra era sobre ter DUAS fontes de verdade para o mesmo bloco vivo na API
    (o "agente" do grill E o "investigador" do catálogo plano, os dois
    propostos ao mesmo tempo). Isto é migração de DADO já gravado — o arquivo
    no disco é o único lugar onde o nome antigo ainda existe, e ele precisa de
    tradução exatamente uma vez, na leitura, para não quebrar o que o dono já
    salvou.
    """
    resolvers = []
    mudou = False
    for r in receita.resolvers:
        novo = _NOMES_LEGADOS.get(r.nome)
        if novo is None:
            resolvers.append(r)
            continue
        mudou = True
        print(
            f"receita {caminho}: bloco {r.nome!r} é nome legado do cardápio do "
            f"grill; migrado para {novo!r} do catálogo plano",
            file=sys.stderr,
        )
        resolvers.append(ResolverReceita(nome=novo, parametros=r.parametros))
    return dataclasses.replace(receita, resolvers=tuple(resolvers)) if mudou else receita


def _raiz(raiz: Path | None) -> Path:
    # `is None` e não `or`: defensivo, não corretivo — a mesma disciplina, e a
    # mesma honestidade sobre ela, que `receita.construir` já registra. Hoje
    # `or` se comportaria IDENTICAMENTE: `Path` não define `__bool__` nem
    # `__len__`, e tanto `Path("")` quanto `Path(".")` normalizam para `.` e
    # são truthy. A disciplina existe para o dia em que o parâmetro deixar de
    # ser `Path | None` — uma string vazia vinda de config, por exemplo, é
    # falsy, e um `or` a trocaria em silêncio pelo default em vez de falhar.
    return _RAIZ_PADRAO if raiz is None else raiz


def caminho_da_receita(workflow_id: str, raiz: Path | None = None) -> Path:
    return _raiz(raiz) / "workflows" / f"{workflow_id}.json"


def caminho_da_recusa(workflow_id: str, raiz: Path | None = None) -> Path:
    return _raiz(raiz) / "grill" / "recusas" / f"{workflow_id}.json"


def _escrever(caminho: Path, dados: dict) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def gravar_receita(receita: Receita, raiz: Path | None = None) -> Path:
    # ANTES de montar o caminho: um id com `../` escreveria fora de `data/`.
    validar_id(receita.id)
    caminho = caminho_da_receita(receita.id, raiz)
    if caminho.exists():
        raise ValueError(
            f"já existe uma receita com id {receita.id!r} em {caminho}. "
            f"sobrescrever mudaria o significado das decisões já gravadas na "
            f"fila desse workflow — escolha outro id"
        )
    return _escrever(caminho, para_json(receita))


def ler_receita(workflow_id: str, raiz: Path | None = None) -> Receita:
    caminho = caminho_da_receita(workflow_id, raiz)
    receita = de_json(json.loads(caminho.read_text(encoding="utf-8")))
    return _migrar_nomes_legados(receita, caminho)


def listar_receitas(raiz: Path | None = None) -> list[Receita]:
    pasta = _raiz(raiz) / "workflows"
    if not pasta.is_dir():
        return []
    achadas = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            receita = de_json(json.loads(caminho.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, ValueError) as erro:
            # Um arquivo corrompido não pode derrubar a listagem inteira — mas
            # também não pode sumir em silêncio.
            print(f"receita ignorada, ilegível: {caminho} ({erro})", file=sys.stderr)
            continue
        achadas.append(_migrar_nomes_legados(receita, caminho))
    return achadas


def gravar_recusa(workflow_id: str, recusa, raiz: Path | None = None) -> Path:
    validar_id(workflow_id)
    return _escrever(
        caminho_da_recusa(workflow_id, raiz),
        {
            "id": workflow_id,
            "motivo": recusa.motivo,
            "o_que_faltaria": recusa.o_que_faltaria,
            "transcricao": list(recusa.transcricao),
        },
    )
