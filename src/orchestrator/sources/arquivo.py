"""Um arquivo do usuário como pool de trabalho.

`kernel/source.py` prometeu isto no docstring: *"quem tiver o dado escreve um
`Source` de 40 linhas, e é essa a promessa do framework"*. Este é o segundo
`Source` do projeto — o primeiro foi o sintético, e enquanto ele era o único a
promessa não tinha sido cobrada.

**A leitura é a parte fácil. A CERCA é o trabalho.** `caminho` chega pela rede
e vira uma leitura de disco no servidor: sem raiz, este módulo é um leitor de
arquivos arbitrários. O alvo que importa não é `/etc/passwd` — é `data/fila/**`,
que devolveria a trilha de decisões humanas de OUTRO workflow.
"""

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.kernel.work import WorkItem, WorkSet

MAX_LINHAS_PADRAO = 5000


class RaizViolada(ValueError):
    """O caminho pedido não está sob a raiz de entradas."""


@dataclass(frozen=True)
class ArquivoSource:
    """CSV ou JSON, sob uma raiz, com `ref` por conteúdo.

    O formato sai da extensão e não de um campo declarado: quem escolhe `.csv`
    já disse o que é, e um campo `formato` que pudesse contradizer a extensão
    seria uma segunda fonte de verdade sobre a mesma coisa.
    """

    caminho: Path
    kind: str
    campo_id: str
    raiz: Path
    max_linhas: int = MAX_LINHAS_PADRAO
    _resolvido: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        raiz = self.raiz.resolve()
        alvo = self.caminho.resolve()
        # `resolve()` ANTES de comparar, e `is_relative_to` em vez de
        # `startswith`: um prefixo de string diz que `/dados-secretos` está
        # dentro de `/dados`, e um symlink que mora dentro da raiz fura
        # qualquer checagem feita antes de resolver.
        if not alvo.is_relative_to(raiz):
            raise RaizViolada(
                f"caminho fora da raiz de entradas: {self.caminho} não está sob {self.raiz}"
            )
        object.__setattr__(self, "_resolvido", alvo)

    @property
    def ref(self) -> str:
        """`file:<caminho relativo>@<sha256 do conteúdo>`.

        Do CONTEÚDO, nunca do `mtime`: copiar ou tocar um arquivo muda a data e
        não muda o trabalho, e o replay quebraria por nada. Relativo à raiz
        porque o caminho absoluto da máquina não é parte da identidade do
        trabalho — mover a raiz não deveria invalidar decisões já tomadas.
        """
        digest = hashlib.sha256(self._resolvido.read_bytes()).hexdigest()
        return f"file:{self._resolvido.relative_to(self.raiz.resolve())}@{digest}"

    def load(self) -> WorkSet:
        linhas = self._linhas()
        if len(linhas) > self.max_linhas:
            raise ValueError(
                f"{self.caminho.name} tem {len(linhas)} linhas, acima do teto de "
                f"{self.max_linhas}. Reduza o arquivo ou suba o teto."
            )
        itens = []
        for i, linha in enumerate(linhas, start=1):
            if self.campo_id not in linha:
                # Alto, com o número da linha. Pular em silêncio produziria um
                # pool menor que o arquivo, e ninguém saberia.
                raise ValueError(
                    f"linha {i} de {self.caminho.name} não tem o campo_id "
                    f"{self.campo_id!r}. campos: {sorted(linha)}"
                )
            itens.append(
                WorkItem(id=str(linha[self.campo_id]), kind=self.kind, payload=linha)
            )
        # `WorkSet.__post_init__` recusa id repetido — deixar a guarda dele
        # falar evita uma segunda mensagem para a mesma falha.
        return WorkSet(items=tuple(itens))

    def _linhas(self) -> list[dict]:
        texto = self._resolvido.read_text(encoding="utf-8")
        if self._resolvido.suffix.lower() == ".json":
            dados = json.loads(texto)
            if not isinstance(dados, list):
                raise ValueError(
                    f"{self.caminho.name}: o JSON precisa ser uma LISTA de objetos, "
                    f"e veio {type(dados).__name__}"
                )
            return dados
        return list(csv.DictReader(texto.splitlines()))
