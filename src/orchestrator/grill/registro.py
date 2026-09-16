"""Receitas e recusas em disco.

Nada aqui é versionado: a `justificativa` de uma receita carrega a descrição do
problema do parceiro — dado de terceiro, que o spec pai proíbe versionar. Ver o
`.gitignore`, que é allowlist sob `data/`.
"""

import json
import sys
from pathlib import Path

from orchestrator.grill.receita import Receita, de_json, para_json, validar_id

_RAIZ_PADRAO = Path("data")


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
    return de_json(json.loads(caminho.read_text(encoding="utf-8")))


def listar_receitas(raiz: Path | None = None) -> list[Receita]:
    pasta = _raiz(raiz) / "workflows"
    if not pasta.is_dir():
        return []
    achadas = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            achadas.append(de_json(json.loads(caminho.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError, ValueError) as erro:
            # Um arquivo corrompido não pode derrubar a listagem inteira — mas
            # também não pode sumir em silêncio.
            print(f"receita ignorada, ilegível: {caminho} ({erro})", file=sys.stderr)
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
