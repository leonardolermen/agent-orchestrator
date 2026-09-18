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
3. `ref` = `pg:<dsn_env>/<sha(query guardada)>@<sha(linhas ordenadas)>`. O
   hash das linhas é o que faz duas execuções sobre os mesmos dados casarem
   as decisões humanas já tomadas — e uma linha mudada mudar o `ref`. As duas
   palavras difíceis dessa fórmula são "guardada" e "ordenadas", e cada uma
   tem um comentário no `ref` explicando de que defeito ela é o conserto.

A conexão é INJETÁVEL (`conectar`) para que os testes não abram socket: o
default importa `psycopg` dentro do `load()`, e é isso que torna o extra
`[fontes]` opcional para quem só usa arquivo.
"""

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente

MAX_LINHAS_PADRAO = 5000
# Os dois relógios da conexão. A irmã HTTP põe `timeout=30.0` explícito; a que
# fala com o banco do PARCEIRO era a única sem relógio nenhum, e
# `_guarda_select` deixa passar `SELECT pg_sleep(60)` e qualquer SELECT caro
# sobre uma tabela grande — por uma rota sem autenticação.
CONEXAO_TIMEOUT_S = 10
STATEMENT_TIMEOUT_MS = 30_000
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
    # `SELECT … INTO <tabela>` é a única forma de SELECT que escreve no
    # Postgres — cria e popula uma tabela. `INSERT INTO` já é barrado pela
    # primeira palavra; este é o caso que sobra. Não tenta distinguir de um
    # literal de string: sobre-recusar é a direção seguro.
    if re.search(r"\bINTO\b", sem_final, re.IGNORECASE):
        raise FonteFalhou("a query precisa ser um SELECT só — `INTO` escreve numa tabela")
    return sem_final


def _canonico(valor: Any) -> list:
    """A forma canônica de um valor, TIPO junto, recursivamente.

    **A propriedade, dita inteira: dois valores diferentes nunca produzem a
    mesma forma canônica.** É ela que o `ref` precisa; sem ela, duas tabelas
    diferentes dividem o `dataset` de `data/fila/**` e uma decisão humana tomada
    sobre uma é casada com os itens da outra — a falha do ETag fraco na fonte
    HTTP, deste lado do espelho.

    Duas tentativas anteriores, e por que as duas falharam:

    1. `json.dumps(..., default=str)` colapsava `Decimal("1")` com a string
       `"1"`, e `date(2026, 9, 20)` com `"2026-09-20"`.
    2. marcar só o valor NÃO-nativo, com uma chave prefixada por `\\x00`.
       Fechava o `jsonb` (que recusa `\\u0000` dentro de strings) e **não**
       fechava o tipo `json`, que guarda o texto verbatim: o loader do psycopg
       roda `json.loads`, o escape vira um `\\x00` de verdade, e uma coluna
       `json` com `{"\\u0000Decimal": "1"}` dentro forjava a marca de um
       `Decimal("1")`. Fechava por PROBABILIDADE, que é exatamente o que eu
       tinha dito que não queria. E deixava de fora, de qualquer forma, os tipos
       nativos entre si: `default=` nunca é chamado para eles, então uma `tuple`
       (um composto `ROW(1,2)`) e uma `list` (um `int[]`) caíam no mesmo texto.

    O que fecha de verdade é não deixar dado NENHUM aparecer sem marca. Aqui
    **todo** valor vira `[<nome do tipo>, <conteúdo já canônico>]`, inclusive
    `str`, `int`, `list` e `dict`. Um objeto vindo de uma coluna `json` é emitido
    como `["dict", …]` e não tem como se passar por uma marca, porque marca não é
    uma forma que dado possa ter: é a POSIÇÃO no par, e a posição é nossa. A
    recursão é o que estende isso a qualquer profundidade.

    Detalhes que não são detalhe:

    - `dict` é ordenado por `(tipo da chave, texto da chave)`, não por `<`: duas
      chaves de tipos diferentes não são comparáveis em Python 3, e o digest não
      pode depender da ordem de iteração.
    - `bytes`/`bytearray`/`memoryview` viram hex, e não `str(...)`: o texto de um
      `memoryview` embute o ENDEREÇO de memória, e isso seria um `ref` que muda
      entre duas leituras idênticas.
    - o resto dos não-nativos usa `str(valor)`. **O limite que sobra**, dito em
      voz alta: dois valores DO MESMO tipo cujo `str()` coincide ainda colapsam,
      e um tipo cujo texto embute endereço dá `ref` instável. Nenhum tipo que
      `psycopg` devolve é assim; a alternativa — recusar o que não sabemos
      serializar — trocaria um `ref` errado por uma fonte que não roda.
    """
    tipo = type(valor).__name__
    if isinstance(valor, dict):
        return [
            tipo,
            [
                [_canonico(chave), _canonico(v)]
                for chave, v in sorted(
                    valor.items(), key=lambda par: (type(par[0]).__name__, str(par[0]))
                )
            ],
        ]
    if isinstance(valor, (list, tuple, set, frozenset)):
        itens = [_canonico(v) for v in valor]
        # Um conjunto não tem ordem; a lista e a tupla têm, e ela é conteúdo.
        if isinstance(valor, (set, frozenset)):
            itens = sorted(itens, key=json.dumps)
        return [tipo, itens]
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return [tipo, bytes(valor).hex()]
    if valor is None or isinstance(valor, (str, bool, int, float)):
        return [tipo, valor]
    return [tipo, str(valor)]


def _conectar_padrao(dsn: str) -> Any:
    """A conexão de verdade, COM relógio nos dois lados.

    Os dois relógios moram aqui, e não no `_consultar`, por duas razões: são
    propriedade da CONEXÃO (não da consulta), e assim as conexões falsas que os
    testes injetam continuam valendo sem saber que eles existem.

    `connect_timeout` limita o aperto de mão; `statement_timeout`, passado nas
    `options` da conexão, limita o servidor — é o único dos dois que interrompe
    um `pg_sleep(60)` que já começou, porque quem o cancela é o Postgres.

    Estes dois valores VENCEM o que o DSN disser (kwargs ganham do conninfo em
    `psycopg.connect`): o DSN vem de uma variável de ambiente do servidor, mas
    a query vem de um campo de texto na tela, e o relógio existe por causa da
    segunda. Quem precisar de mais tempo muda a constante deste módulo, onde a
    mudança fica visível.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as erro:
        raise ExtraAusente("psycopg") from erro
    return psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=CONEXAO_TIMEOUT_S,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


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
            # `fetchmany(teto + 1)` e não `fetchall()`, e é importante ser
            # honesto sobre o QUE isto limita.
            #
            # O que ele limita: quantos dicts Python são construídos. Com
            # `fetchall()` uma tabela de 50 M de linhas viram 50 M de dicts —
            # o custo mais caro do caminho, e o `+ 1` é o mínimo para distinguir
            # "encheu" de "estourou" sem materializar a linha seguinte.
            #
            # **O que ele NÃO limita, dito em voz alta: a transferência.** O
            # cursor padrão do psycopg3 é do lado do CLIENTE, então quando
            # `execute()` retorna o resultado INTEIRO já veio pela rede e está
            # no buffer da libpq. Contra uma tabela de 40 GB, o que segura o
            # processo hoje é o `statement_timeout` de `_conectar_padrao` — não
            # este teto. O conserto de verdade é um cursor NOMEADO (server-side,
            # `conexao.cursor(name=…)`), que traz por lotes; ele não entrou aqui
            # porque `psycopg` não está instalado neste venv e uma mudança não
            # testável no caminho de conexão, no fim da branch, é um trade pior
            # do que um limite conhecido e escrito.
            brutas = cursor.fetchmany(self.max_linhas + 1)
        except Exception as erro:
            _log.error("fonte pg:%s — consulta falhou: %s", self.dsn_env, erro)
            raise FonteFalhou(f"consulta falhou: {type(erro).__name__}") from erro
        finally:
            conexao.close()
        # A recusa por teto sai DAQUI, fora do `try` acima — que a viraria em
        # "consulta falhou: FonteFalhou" — e fora do `load()`, porque `ref` não
        # passa por `load()`. É a razão escrita em `ArquivoSource._bytes()`: o
        # teto só é teto se as DUAS vistas passarem por ele.
        if len(brutas) > self.max_linhas:
            raise FonteFalhou(
                f"a query devolveu mais de {self.max_linhas} linhas, o teto desta "
                f"fonte — a leitura foi interrompida. estreite o `WHERE` ou o `LIMIT`"
            )
        linhas = tuple(dict(linha) for linha in brutas)
        object.__setattr__(self, "_linhas", linhas)
        return linhas

    @property
    def ref(self) -> str:
        linhas = self._consultar()
        # A query GUARDADA, que é a que executa. Hashear `self.query` crua fazia
        # um `;` a mais ou um comentário `--` mudarem o `ref` sem mudar o
        # statement nem uma linha do resultado — conteúdo idêntico, chave de
        # fila diferente, decisão humana invisível.
        q = hashlib.sha256(_guarda_select(self.query).encode("utf-8")).hexdigest()[:12]
        # **O `sorted` é a correção, não uma arrumação — não o tire.** Um
        # `SELECT` sem `ORDER BY` não promete ordem nenhuma, e ela muda na
        # prática por troca de plano, por `VACUUM` movendo tuplas, por
        # autovacuum entre duas execuções. Hashear as linhas na ordem em que o
        # cursor as devolveu fazia a MESMA tabela, sem uma alteração sequer,
        # produzir dois `ref` — e cada `ref` novo é um `data/fila/<wf>/pg-*.jsonl`
        # novo e vazio, com toda decisão humana já tomada fora de alcance.
        # Serializa cada linha, ordena os TEXTOS, hasheia isso: o digest deixa
        # de depender da ordem de chegada. A ordem do POOL não é tocada —
        # `load()` continua entregando as linhas como vieram.
        #
        # `_canonico` e não `json.dumps(linha, default=…)`: ver o docstring de
        # lá. Em uma frase, `Decimal("1")` e `"1"` são conteúdos diferentes e
        # precisam de `ref` diferentes, e nenhum valor que uma linha possa
        # carregar pode imitar a marca de outro. `sort_keys` não é mais preciso:
        # `_canonico` já ordena as chaves de todo dicionário, em qualquer
        # profundidade.
        serializadas = sorted(
            json.dumps(_canonico(linha), ensure_ascii=False) for linha in linhas
        )
        d = hashlib.sha256("\n".join(serializadas).encode("utf-8")).hexdigest()
        return f"pg:{self.dsn_env}/{q}@{d}"

    def load(self) -> WorkSet:
        linhas = self._consultar()
        # Segunda tranca. Hoje ela não dispara — `_consultar` nunca traz mais do
        # que o teto —, e continua aqui de propósito: é a única que sabe o
        # NÚMERO exato, e é quem pega o dia em que alguém alimentar `_linhas`
        # por outro caminho que não o `fetchmany`.
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
