"""As propostas e decisões de um workflow sobre um dataset.

Um JSONL append-only por `(workflow, dataset)`. Append-only NÃO é economia de
esforço: é a trilha de auditoria que o Tier 1 do spec pai pede, saindo como
subproduto do formato em vez de funcionalidade construída depois.

Escrita concorrente de dois processos não tem lock. Uma máquina, um usuário,
`open("a")` por linha é seguro o bastante; multiusuário é multi-tenant, Tier 4.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from orchestrator.kernel.resolution import Proposal
from orchestrator.review.decision import Decision
from orchestrator.review.serial import (
    decisao_de_dict,
    decisao_para_dict,
    proposta_de_dict,
    proposta_para_dict,
)

_RAIZ_PADRAO = Path("data")


def dataset_id(seed: int, n: int, taxa: float) -> str:
    """A identidade do conjunto sobre o qual uma decisão foi tomada.

    `d-b-b00003` existe em toda semente. Sem este escopo, uma decisão tomada
    olhando a semente 1 se aplicaria a um lançamento diferente na semente 7.
    """
    return f"s{seed}-n{n}-t{taxa}"


# O que pode virar nome de arquivo sem surpresa em nenhum dos dois sistemas de
# arquivos que este projeto roda (Windows no desenvolvimento, Linux no CI).
_NOME_SEGURO = re.compile(r"[A-Za-z0-9._-]+")

# A forma EXATA que `dataset_id` produz, e a única que o esquema `synth:` tem
# permissão de perder ao virar chave de fila. É a compatibilidade com o que já
# está escrito em `data/fila/**`, escrita como exceção estreita em vez de como
# regra geral — ver `dataset_de_ref`.
#
# Duas expressões que precisam concordar sobre o mesmo formato são o join
# frágil de sempre; `test_a_forma_legada_descreve_o_que_dataset_id_produz`
# fecha o par.
_FORMA_LEGADA = re.compile(r"s\d+-n\d+-t[\d.]+")
_ESQUEMA_LEGADO = "synth"


def dataset_de_ref(ref: str) -> str:
    """A identidade do conjunto, a partir do `ref` da fonte.

    A fila é chaveada por `(workflow, dataset)`, e até aqui o `dataset` saía de
    `dataset_id(seed, n, taxa)`. Com uma fonte de ARQUIVO não existe seed, nem
    n, nem taxa — então a chave passa a sair do `ref`, uniformemente, para toda
    fonte. O `ref` sempre foi a identidade do conjunto; `dataset_id` era a
    versão dele sem o esquema.

    Precisa servir de NOME DE ARQUIVO — `caminho_da_fila` o interpola em
    `{dataset}.jsonl`.

    **O ESQUEMA faz parte da chave, com uma exceção nomeada.** Jogá-lo fora
    sempre que o resto fosse seguro faria `synth:X` e `db:X` colidirem numa
    fila só — dois conjuntos diferentes compartilhando a trilha de decisões
    humanas. Ele só é descartado para `synth:` com um resto na forma exata que
    `dataset_id` produz, porque é essa a chave das filas JÁ ESCRITAS em disco,
    e perdê-la tornaria toda decisão humana existente invisível. Nenhuma outra
    string pode alcançar esse ramo: `_FORMA_LEGADA` não casa com `db-x`, nem
    com um caminho, nem com um hash.

    Um ref `file:` carrega `/`, `@` e o `:` do esquema — diretório acidental no
    Linux, nome ilegal no Windows — e por isso vira hash.

    `dataset_id` FICA: a CLI e o grill chamam, e lá seed/n/taxa existem de
    verdade.
    """
    esquema, _, resto = ref.partition(":")
    if esquema == _ESQUEMA_LEGADO and _FORMA_LEGADA.fullmatch(resto):
        return resto
    if _NOME_SEGURO.fullmatch(esquema) and _NOME_SEGURO.fullmatch(resto):
        return f"{esquema}-{resto}"
    # O esquema também passa pela peneira antes de virar prefixo. Num ref sem
    # `:` ele é o ref INTEIRO, que pode carregar barra — e um prefixo com barra
    # transformaria `{dataset}.jsonl` num diretório, que é a mesma falha
    # silenciosa que esta função existe para impedir.
    prefixo = esquema if _NOME_SEGURO.fullmatch(esquema) else "ref"
    return f"{prefixo}-{hashlib.sha256(ref.encode()).hexdigest()[:16]}"


def caminho_da_fila(workflow_id: str, dataset: str, raiz: Path | None = None) -> Path:
    return (raiz or _RAIZ_PADRAO) / "fila" / workflow_id / f"{dataset}.jsonl"


class Fila:
    def __init__(self, caminho: Path | None) -> None:
        self._caminho = caminho
        self._propostas: dict[str, Proposal] = {}
        self._decisoes: dict[str, Decision] = {}
        self._ordem: list[str] = []
        if caminho is not None and caminho.exists():
            linhas = caminho.read_text(encoding="utf-8").splitlines()
            for numero, linha in enumerate(linhas, start=1):
                if not linha.strip():
                    continue
                try:
                    self._aplicar(json.loads(linha))
                except Exception as erro:
                    # A fila é a trilha de auditoria. Um KeyError mudo diz
                    # "faltou um campo" sem dizer QUAL registro — e quem lê
                    # isso é um humano investigando por que uma decisão
                    # sumiu, não um dev com o traceback do parser na cabeça.
                    raise ValueError(
                        f"registro inválido em {caminho} na linha {numero}: {erro}"
                    ) from erro

    @staticmethod
    def vazia() -> "Fila":
        """Uma fila em memória que nunca toca o disco.

        É o que `default_definition()` usa quando ninguém passa fila: o
        revisor existe na cascata, não emite nada, e o golden segue idêntico.
        """
        return Fila(None)

    def _aplicar(self, registro: dict[str, Any]) -> None:
        if registro["kind"] == "proposta":
            p = proposta_de_dict(registro["dados"])
            # PRIMEIRA vence: o agente não se repete, e uma segunda proposta
            # apagaria o que o revisor já leu.
            if p.item_id not in self._propostas:
                self._propostas[p.item_id] = p
                self._ordem.append(p.item_id)
        else:
            # ÚLTIMA vence: um humano muda de ideia, e o estado é a decisão
            # mais recente. O log guarda todas — é ele a auditoria.
            d = decisao_de_dict(registro["dados"])
            self._decisoes[d.divergence_id] = d

    def _acrescentar(self, kind: str, dados: dict[str, Any]) -> None:
        if self._caminho is None:
            return
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._caminho.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "dados": dados}, ensure_ascii=False) + "\n")

    def proposta(self, divergence_id: str) -> Proposal | None:
        return self._propostas.get(divergence_id)

    def decisao(self, divergence_id: str) -> Decision | None:
        return self._decisoes.get(divergence_id)

    def pendentes(self) -> list[Proposal]:
        return [self._propostas[i] for i in self._ordem if i not in self._decisoes]

    def decididas(self) -> list[tuple[Proposal, Decision]]:
        return [
            (self._propostas[i], self._decisoes[i]) for i in self._ordem if i in self._decisoes
        ]

    def gravar_proposta(self, p: Proposal) -> None:
        """Ignora proposta para id que já tem uma — ver `_aplicar`."""
        if p.item_id in self._propostas:
            return
        self._acrescentar("proposta", proposta_para_dict(p))
        self._propostas[p.item_id] = p
        self._ordem.append(p.item_id)

    def gravar_decisao(self, d: Decision) -> None:
        self._acrescentar("decisao", decisao_para_dict(d))
        self._decisoes[d.divergence_id] = d
