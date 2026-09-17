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
# Teto de bytes, não de linhas: `max_linhas` só se aplica DEPOIS de o arquivo
# inteiro estar em memória e parseado. Sem um teto anterior, um arquivo de 4
# GB é lido e hasheado por inteiro antes de qualquer contagem de linha ter
# chance de recusar — a defesa chegaria tarde demais para o próprio `ref`.
MAX_BYTES_PADRAO = 10 * 1024 * 1024  # 10 MiB

# Sentinelas para as duas formas de uma linha de CSV não bater com o
# cabeçalho. `csv.DictReader` usa `restval`/`restkey` para isso, e o padrão de
# ambos é `None` — o que apaga a diferença entre "o campo faltou" e "o campo
# tem o valor None de propósito". Foi exatamente essa ambiguidade que deixava
# uma linha truncada virar `WorkItem(id="None")` em silêncio.
_FALTA = object()  # restval: linha mais CURTA que o cabeçalho
_EXTRA = object()  # restkey: linha mais LONGA que o cabeçalho


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
    max_bytes: int = MAX_BYTES_PADRAO
    # `compare=False` nos dois campos derivados: um dataclass `frozen=True`
    # promete hash estável, e os dois participariam do `__eq__`/`__hash__`
    # gerados por padrão. `_conteudo` é populado PREGUIÇOSAMENTE por `.ref` —
    # sem `compare=False`, o mesmo objeto hasheia diferente antes e depois de
    # `.ref` ser lido, e some silenciosamente de um `set` do qual já era
    # membro. `_resolvido` não tem esse problema (é determinístico a partir
    # de `caminho`/`raiz`), mas um valor DERIVADO não tem por que participar
    # de identidade de qualquer forma.
    _resolvido: Path = field(init=False, repr=False, compare=False)
    # `None` até a primeira leitura. Fica de fora do `__post_init__` de
    # propósito: construir um `ArquivoSource` não deve tocar o disco, e o
    # teto de bytes (abaixo, em `_bytes()`) precisa poder recusar ANTES de
    # qualquer leitura acontecer.
    _conteudo: bytes | None = field(
        init=False, repr=False, compare=False, default=None
    )

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

    def _bytes(self) -> bytes:
        """O conteúdo do arquivo, lido do disco uma única vez.

        `ref` e `load()` liam o disco em duas chamadas separadas
        (`read_bytes()` e `read_text()`); nada garantia que os bytes hasheados
        por `ref` eram os mesmos que `load()` transformava em `WorkItem` — um
        arquivo trocado entre as duas chamadas faria o `ref` nomear um
        conteúdo que nunca virou trabalho. Memoizado aqui, as duas views
        compartilham a mesma leitura.

        O teto de tamanho mora aqui, e não em `load()`, porque `stat()` é
        barato e roda ANTES de qualquer byte entrar em memória — é a única
        forma de o teto proteger `ref` também, que não passa por `load()`.
        """
        if self._conteudo is None:
            tamanho = self._resolvido.stat().st_size
            if tamanho > self.max_bytes:
                raise ValueError(
                    f"{self.caminho.name} tem {tamanho} bytes, acima do teto de "
                    f"{self.max_bytes}. Reduza o arquivo ou suba o teto."
                )
            object.__setattr__(self, "_conteudo", self._resolvido.read_bytes())
        return self._conteudo

    @property
    def ref(self) -> str:
        """`file:<caminho relativo, com `/`>@<sha256 do conteúdo>`.

        Do CONTEÚDO, nunca do `mtime`: copiar ou tocar um arquivo muda a data e
        não muda o trabalho, e o replay quebraria por nada. Relativo à raiz
        porque o caminho absoluto da máquina não é parte da identidade do
        trabalho — mover a raiz não deveria invalidar decisões já tomadas.

        `.as_posix()`, nunca a formatação padrão de `Path`: em Windows um
        `Path` relativo imprime com `\\`, em Linux com `/` — o MESMO arquivo
        produziria dois `ref` diferentes conforme onde o processo roda, e
        "estável" deixaria de valer entre a máquina de quem gerou o `ref` e o
        CI que faz o replay.
        """
        digest = hashlib.sha256(self._bytes()).hexdigest()
        relativo = self._resolvido.relative_to(self.raiz.resolve()).as_posix()
        return f"file:{relativo}@{digest}"

    def load(self) -> WorkSet:
        linhas = self._linhas()
        if len(linhas) > self.max_linhas:
            raise ValueError(
                f"{self.caminho.name} tem {len(linhas)} linhas, acima do teto de "
                f"{self.max_linhas}. Reduza o arquivo ou suba o teto."
            )
        itens = [self._item(linha, i) for i, linha in enumerate(linhas, start=1)]
        # `WorkSet.__post_init__` recusa id repetido — deixar a guarda dele
        # falar evita uma segunda mensagem para a mesma falha.
        return WorkSet(items=tuple(itens))

    def _item(self, linha: dict, i: int) -> WorkItem:
        """Uma linha vira `WorkItem`, ou a razão de não virar, com o número da
        linha. As quatro formas de uma linha ser inutilizável são distintas de
        propósito — cada uma aponta para um defeito diferente no arquivo."""
        if _EXTRA in linha:
            # Checado ANTES de `campo_id not in linha`: com o restkey sobrando
            # no dict, `sorted(linha)` da mensagem abaixo misturaria `str` com
            # o objeto sentinela e o `TypeError` da comparação escondia o erro
            # que a mensagem deveria explicar.
            raise ValueError(
                f"linha {i} de {self.caminho.name} tem mais campos que o "
                f"cabeçalho (sobra {linha[_EXTRA]!r}) — o arquivo não bate com "
                f"a própria primeira linha"
            )
        if self.campo_id not in linha:
            # Campo ausente de verdade: no JSON, a chave não existe; no CSV,
            # nem o cabeçalho tem essa coluna. Alto, com o número da linha —
            # pular em silêncio produziria um pool menor que o arquivo, e
            # ninguém saberia.
            raise ValueError(
                f"linha {i} de {self.caminho.name} não tem o campo_id "
                f"{self.campo_id!r}. campos: {sorted(linha)}"
            )
        valor = linha[self.campo_id]
        if valor is _FALTA:
            # A chave existe (o `DictReader` a preencheu com o restval), mas a
            # linha era mais curta que o cabeçalho — é o caso que virava
            # `WorkItem(id="None")` quando o sentinela era `None` em vez de um
            # objeto que não se confunde com um valor real.
            raise ValueError(
                f"linha {i} de {self.caminho.name} está truncada: falta o "
                f"valor de {self.campo_id!r} (linha mais curta que o cabeçalho)"
            )
        if isinstance(valor, str) and valor.strip() == "":
            # Vazio OU só espaço — mesma classe de "None" fabricado: algo com
            # a FORMA de um dado que não identifica nada, e que atravessa
            # CSV/JSON invisível a olho nu. `WorkItem` já recusa id vazio
            # sozinho, mas não sabe de qual arquivo ou linha veio — é isso
            # que esta guarda diz e o `WorkItem` não pode.
            #
            # `valor.strip() == ""` decide se RECUSA; o valor aceito nunca é
            # `.strip()`-ado. Normalizar " a " para "a" em silêncio seria o
            # mesmo defeito de transformação silenciosa que criava o id
            # "None" fabricado, só que na direção de aceitar — cortar espaço
            # de um id real é tão errado quanto fabricar um id falso.
            #
            # `isinstance(valor, str)`: só string tem noção de "espaço". Um id
            # JSON `0` ou `False` não entra aqui — nem deveria, os dois são
            # ids legítimos.
            raise ValueError(
                f"linha {i} de {self.caminho.name} tem {self.campo_id!r} em "
                f"branco (vazio ou só espaço) — isso não identifica um item"
            )
        return WorkItem(id=str(valor), kind=self.kind, payload=linha)

    def _linhas(self) -> list[dict]:
        texto = self._bytes().decode("utf-8")
        if self._resolvido.suffix.lower() == ".json":
            dados = json.loads(texto)
            if not isinstance(dados, list):
                raise ValueError(
                    f"{self.caminho.name}: o JSON precisa ser uma LISTA de objetos, "
                    f"e veio {type(dados).__name__}"
                )
            return dados
        return list(
            csv.DictReader(texto.splitlines(), restval=_FALTA, restkey=_EXTRA)
        )
