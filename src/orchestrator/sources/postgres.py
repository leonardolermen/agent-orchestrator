"""Uma query Postgres como pool de trabalho.

**Ler é fácil. Não escrever, não vazar e ter `ref` é o trabalho.** Três
compromissos, e cada um tem um teste que o prova:

1. A query é LEITURA: `SELECT` ou `WITH`, uma instrução só — conferido antes
   de conectar. A plataforma lê o banco do parceiro; escrever nele a partir
   de um campo de texto na tela não é uma feature, é um incidente.
2. O DSN é um NOME de variável de ambiente, lido no `load()`. Ele não entra no
   `ref`, na mensagem de erro, nem em nada que a fonte emita. O erro do driver
   — que ecoa host e usuário — é reduzido à classe; a mensagem inteira vai
   para o log do servidor, o lugar designado.
3. `ref` = `pg:<dsn_env>/<sha(query)>@<sha(linhas)>`. O hash das linhas é o
   que faz duas execuções sobre os mesmos dados casarem as decisões humanas
   já tomadas — e uma linha mudada mudar o `ref`.

A conexão é INJETÁVEL (`conectar`) para que os testes não abram socket: o
default importa `psycopg` dentro do `load()`, e é isso que torna o extra
`[fontes]` opcional para quem só usa arquivo.
"""

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente

MAX_LINHAS_PADRAO = 5000
_LEITURA = ("SELECT", "WITH")
_log = logging.getLogger("orchestrator.sources")


def _guarda_select(query: str) -> str:
    """A primeira palavra é SELECT/WITH e há UMA instrução. Conservadora de
    propósito: um SELECT legítimo recusado é bug a corrigir; um DELETE que
    passasse seria um desastre. Um `;` final é tolerado; um no meio, não."""
    corpo = "\n".join(
        linha for linha in query.strip().splitlines() if not linha.lstrip().startswith("--")
    ).strip()
    sem_final = corpo.rstrip().rstrip(";").rstrip()
    if ";" in sem_final:
        raise FonteFalhou("a query precisa ser um SELECT só — há mais de uma instrução")
    primeira = sem_final.split(None, 1)[0].upper() if sem_final else ""
    if primeira not in _LEITURA:
        raise FonteFalhou(
            "a query precisa ser um SELECT só (ou WITH … SELECT); "
            f"começa com {primeira or 'nada'!r}"
        )
    return sem_final


def _conectar_padrao(dsn: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as erro:
        raise ExtraAusente("psycopg") from erro
    return psycopg.connect(dsn, row_factory=dict_row)


@dataclass(frozen=True)
class PostgresSource:
    dsn_env: str
    query: str
    kind: str
    campo_id: str
    max_linhas: int = MAX_LINHAS_PADRAO
    # Injetável para os testes. `None` = o de verdade, importado no `load()`.
    conectar: Callable[[str], Any] | None = field(default=None, compare=False)
    # Memo das linhas: `ref` e `load()` são UMA consulta, como os bytes do
    # `ArquivoSource`. `compare=False` pelo mesmo motivo de lá — um frozen
    # dataclass não pode mudar de hash depois de ler.
    _linhas: tuple[dict, ...] | None = field(default=None, init=False, repr=False, compare=False)

    def _consultar(self) -> tuple[dict, ...]:
        if self._linhas is not None:
            return self._linhas
        query = _guarda_select(self.query)
        dsn = os.environ.get(self.dsn_env)
        if dsn is None:
            raise VariavelAusente(self.dsn_env)
        conectar = self.conectar or _conectar_padrao
        try:
            conexao = conectar(dsn)
        except ExtraAusente:
            raise
        except Exception as erro:
            # NUNCA `str(erro)`: o driver ecoa host e usuário. A classe vai ao
            # cliente; o texto inteiro, ao log do servidor.
            _log.error("fonte pg:%s — conexão falhou: %s", self.dsn_env, erro)
            raise FonteFalhou(f"conexão falhou: {type(erro).__name__}") from erro
        try:
            cursor = conexao.cursor()
            cursor.execute(query)
            linhas = tuple(dict(linha) for linha in cursor.fetchall())
        except Exception as erro:
            _log.error("fonte pg:%s — consulta falhou: %s", self.dsn_env, erro)
            raise FonteFalhou(f"consulta falhou: {type(erro).__name__}") from erro
        finally:
            conexao.close()
        object.__setattr__(self, "_linhas", linhas)
        return linhas

    @property
    def ref(self) -> str:
        linhas = self._consultar()
        q = hashlib.sha256(self.query.encode("utf-8")).hexdigest()[:12]
        canonico = json.dumps(linhas, sort_keys=True, default=str, ensure_ascii=False)
        d = hashlib.sha256(canonico.encode("utf-8")).hexdigest()
        return f"pg:{self.dsn_env}/{q}@{d}"

    def load(self) -> WorkSet:
        linhas = self._consultar()
        if len(linhas) > self.max_linhas:
            raise FonteFalhou(
                f"a query devolveu {len(linhas)} linhas, acima do teto de {self.max_linhas}"
            )
        itens = []
        for i, linha in enumerate(linhas, start=1):
            valor = linha.get(self.campo_id)
            if valor is None or (isinstance(valor, str) and valor.strip() == ""):
                raise FonteFalhou(
                    f"linha {i} não tem o campo_id {self.campo_id!r} (ou ele está vazio). "
                    f"colunas: {sorted(linha)}"
                )
            itens.append(WorkItem(id=str(valor), kind=self.kind, payload=linha))
        return WorkSet(items=tuple(itens))
