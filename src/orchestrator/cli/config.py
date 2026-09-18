"""`orchestrator.toml` — configuração de projeto, com precedência testada.

**TOML e não YAML, ao contrário do que o plano pedia.** `tomllib` é stdlib desde
o Python 3.11, que é exatamente o piso declarado em `requires-python`. YAML
custaria `pyyaml` como dependência de RUNTIME num pacote que tem uma
(`anthropic`), e a superfície mínima de dependência é o que torna a extração
barata — está no §2.4 da auditoria como ativo, não como acaso.

De brinde, o projeto já fala TOML: `pyproject.toml` está na raiz, e quem edita
um sabe editar o outro.

**Precedência, do mais forte ao mais fraco:**

    argumento de CLI  ->  variável de ambiente  ->  orchestrator.toml  ->  default do código

A última linha é a que importa. O default mora NO DATACLASS, junto da guarda que
o valida e da derivação que o justifica — `budget_microcents` tem 25 linhas de
conta comentada ao lado dele. Mover o valor para um arquivo separaria o número
da prova de onde ele veio, e do teste que o pina em todo modelo precificado.
Ver ADR-11.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NOME = "orchestrator.toml"


@dataclass(frozen=True)
class Config:
    """O que um projeto configura. Tudo opcional: sem arquivo, tudo é default."""

    raiz_dados: Path = Path("data")
    model: str = "claude-opus-5"
    workflow_padrao: str | None = None
    raiz_receitas: Path | None = None
    # Ao lado de `raiz_receitas`, e pelo mesmo motivo: composições entram no
    # `registry()` como as receitas entram. Sem esta raiz, a CLI passava só a
    # de receitas e lia `data/composicoes` relativo ao CWD — `orch workflows
    # <composição>` dizia "workflow desconhecido" para um workflow que a API
    # roda, que é exatamente a divergência contra a qual o docstring de
    # `registry()` existe. `None` é a MESMA raiz real que a API usa.
    raiz_composicoes: Path | None = None
    spans: bool = True
    bruto: dict[str, Any] = field(default_factory=dict)

    def secao(self, *caminho: str) -> dict[str, Any]:
        """Uma seção do TOML cru, para quem precisa do que este dataclass não
        modela. Devolve `{}` em vez de levantar: seção ausente é config ausente,
        não erro."""
        atual: Any = self.bruto
        for parte in caminho:
            if not isinstance(atual, dict):
                return {}
            atual = atual.get(parte, {})
        return atual if isinstance(atual, dict) else {}


def procurar(inicio: Path | None = None) -> Path | None:
    """Sobe do diretório atual até a raiz procurando `orchestrator.toml`.

    Subir é o que permite rodar a CLI de dentro de uma subpasta do projeto, que
    é onde alguém está na maior parte do tempo. Para na primeira ocorrência: um
    projeto aninhado noutro é caso que não existe hoje, e resolver por
    precedência de profundidade seria inventar semântica.
    """
    atual = (inicio or Path.cwd()).resolve()
    for pasta in (atual, *atual.parents):
        candidato = pasta / NOME
        if candidato.is_file():
            return candidato
    return None


def carregar(caminho: Path | None = None) -> Config:
    """Lê o arquivo (se houver) e aplica o ambiente por cima.

    Arquivo malformado LEVANTA, com o caminho na mensagem. Não é a mesma
    política de `listar_receitas` (que ignora receita ilegível e segue): uma
    receita ruim é um workflow a menos, e um `orchestrator.toml` ruim é toda a
    execução rodando com defaults que ninguém pediu — silenciosamente.
    """
    achado = caminho or procurar()
    bruto: dict[str, Any] = {}
    if achado is not None:
        try:
            bruto = tomllib.loads(achado.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as erro:
            raise ValueError(f"{achado} não é TOML válido: {erro}") from erro

    base = achado.parent if achado else Path.cwd()
    storage = bruto.get("storage", {})
    providers = bruto.get("providers", {}).get("anthropic", {})
    obs = bruto.get("observability", {})

    def _caminho(valor: Any, default: Path) -> Path:
        if not valor:
            return default
        p = Path(str(valor))
        # Relativo ao ARQUIVO, não ao CWD: rodar de uma subpasta não pode
        # mudar onde os dados são gravados.
        return p if p.is_absolute() else base / p

    return Config(
        raiz_dados=_caminho(storage.get("raiz"), base / "data" if achado else Path("data")),
        # Ambiente vence o arquivo. `ANTHROPIC_MODEL` existe para trocar o
        # modelo numa execução sem editar o projeto — o caso de quem está
        # comparando dois.
        model=(
            os.environ.get("ANTHROPIC_MODEL")
            or providers.get("default_model")
            or "claude-opus-5"
        ),
        workflow_padrao=bruto.get("workflow"),
        raiz_receitas=_caminho(storage.get("receitas"), None) if storage.get("receitas") else None,
        raiz_composicoes=(
            _caminho(storage.get("composicoes"), None)
            if storage.get("composicoes")
            else None
        ),
        spans=bool(obs.get("spans", True)),
        bruto=bruto,
    )
