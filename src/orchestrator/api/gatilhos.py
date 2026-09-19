"""Gatilhos: uma URL que dispara um workflow. O `Trigger` do canvas.

Até aqui um run começava porque alguém apertou "rodar" ou chamou a CLI. Um
gatilho é o contrário: o mundo bate numa URL e a execução acontece sozinha.

**Isto é uma URL que GASTA DINHEIRO, e o desenho inteiro sai disso.**

1. **Segredo por gatilho.** Nasce um por gatilho, é mostrado UMA vez e o disco
   guarda só o sha256. Quem perder recria o gatilho. Guardar o segredo em claro
   transformaria um `data/` vazado numa chave para gastar a conta de quem
   hospeda.

2. **Teto obrigatório na CRIAÇÃO, não no disparo.** O disparo não tem corpo que
   se possa confiar — ele vem de fora. Um teto que viesse no disparo seria um
   teto que o atacante escolhe. Ele é fixado quando o gatilho nasce e o disparo
   não pode mudá-lo.

3. **Só workflow que carrega a própria entrada.** Um disparo não tem ninguém
   para escolher a fonte. Recusar isso na CRIAÇÃO — e não no disparo — é o que
   impede um gatilho que existe, parece pronto e falha toda vez que alguém o
   chama.

**O que este desenho NÃO resolve, dito em voz alta.** Quem tiver o segredo pode
disparar em laço. Cada disparo respeita o teto DELE, e nada limita quantos
disparos acontecem por minuto: dez mil chamadas são dez mil tetos. Limite de
frequência exige estado compartilhado que este servidor não guarda — é a mesma
decisão que o `/runs` adiou, e aqui ela pesa mais, porque ninguém descobre o
`/runs` por acaso e uma URL de webhook circula. Está no README também.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_RAIZ_PADRAO = Path("data") / "gatilhos"

# Quanto do segredo entra na URL/listagem como IDENTIFICADOR. O resto nunca sai
# daqui. São dois valores distintos de propósito: o id é público e serve para
# endereçar e revogar; o segredo é o que autoriza.
_TAMANHO_ID = 12


@dataclass(frozen=True)
class Gatilho:
    """Um disparador. O segredo NÃO mora aqui — só o hash dele."""

    id: str
    workflow_id: str
    # Em micro-centavos de USD. Fixado na criação; o disparo não pode mudá-lo.
    teto_microcents: int
    segredo_hash: str
    criado_em: datetime

    def __post_init__(self) -> None:
        if self.teto_microcents < 1:
            raise ValueError(
                f"gatilho {self.id!r} sem teto: uma URL que dispara execução "
                f"precisa de um limite de gasto POR DISPARO, e ele é dito na "
                f"criação porque o disparo vem de fora e não é confiável"
            )
        if not self.workflow_id.strip():
            raise ValueError("gatilho sem workflow")


def _hash(segredo: str) -> str:
    return hashlib.sha256(segredo.encode("utf-8")).hexdigest()


def criar(workflow_id: str, teto_microcents: int, raiz: Path | None = None) -> tuple[Gatilho, str]:
    """Um gatilho novo e o segredo em claro — a ÚNICA vez que ele existe.

    Devolve os dois porque o chamador precisa mostrar o segredo uma vez e
    guardar o gatilho. Devolver só o `Gatilho` obrigaria quem chama a extraí-lo
    de algum lugar, e não há lugar: ele não é gravado.
    """
    segredo = secrets.token_urlsafe(32)
    gatilho = Gatilho(
        id=secrets.token_urlsafe(_TAMANHO_ID),
        workflow_id=workflow_id,
        teto_microcents=teto_microcents,
        segredo_hash=_hash(segredo),
        criado_em=datetime.now(UTC),
    )
    gravar(gatilho, raiz)
    return gatilho, segredo


def autoriza(gatilho: Gatilho, segredo: str) -> bool:
    """O segredo bate?

    `compare_digest` e não `==`: a comparação ingênua de strings sai no primeiro
    byte diferente, e o tempo dela vaza quantos bytes iniciais o atacante
    acertou. Com um segredo de 32 bytes isso é atacável em minutos.
    """
    return secrets.compare_digest(_hash(segredo), gatilho.segredo_hash)


# -- disco ------------------------------------------------------------------


def caminho(gatilho_id: str, raiz: Path | None = None) -> Path:
    return (raiz or _RAIZ_PADRAO) / f"{gatilho_id}.json"


def gravar(g: Gatilho, raiz: Path | None = None) -> Path:
    destino = caminho(g.id, raiz)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(
            {
                "id": g.id,
                "workflow_id": g.workflow_id,
                "teto_microcents": g.teto_microcents,
                "segredo_hash": g.segredo_hash,
                "criado_em": g.criado_em.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return destino


def ler(gatilho_id: str, raiz: Path | None = None) -> Gatilho | None:
    """O gatilho, ou `None` quando não existe.

    `None` e não exceção: quem chama devolve 404, e um id inexistente é o caso
    COMUM numa rota pública — inclusive quando alguém está sondando ids.
    """
    arquivo = caminho(gatilho_id, raiz)
    if not arquivo.exists():
        return None
    d = json.loads(arquivo.read_text(encoding="utf-8"))
    return Gatilho(
        id=d["id"],
        workflow_id=d["workflow_id"],
        teto_microcents=d["teto_microcents"],
        segredo_hash=d["segredo_hash"],
        criado_em=datetime.fromisoformat(d["criado_em"]),
    )


def listar(raiz: Path | None = None) -> list[Gatilho]:
    pasta = raiz or _RAIZ_PADRAO
    if not pasta.exists():
        return []
    achados = [ler(a.stem, raiz) for a in sorted(pasta.glob("*.json"))]
    return [g for g in achados if g is not None]


def revogar(gatilho_id: str, raiz: Path | None = None) -> bool:
    """Apaga o gatilho. `True` se existia.

    Revogar é APAGAR e não marcar como inativo: um gatilho inativo no disco é um
    segredo que continua existindo, e a razão de revogar costuma ser justamente
    que ele vazou.
    """
    arquivo = caminho(gatilho_id, raiz)
    if not arquivo.exists():
        return False
    arquivo.unlink()
    return True


__all__ = ["Gatilho", "autoriza", "criar", "listar", "ler", "revogar"]
