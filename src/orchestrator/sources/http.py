"""Uma API HTTP como pool de trabalho — uma página, com token por nome.

Fecha o R7 que o spec de agentes-rodando adiou: `ref` = `http:<url>@<sha256 do
corpo>`, SEMPRE. Paginação e cursor ficam FORA (o `ref` de várias páginas é
desenho próprio) e estão escritos como fora no spec.

**O ETag NÃO entra no `ref`, e isto contraria a linha do spec que o mandava
entrar.** O ETag é escolhido pelo servidor do parceiro e não tem relação
garantida com os bytes: um ETag fraco (`W/"v1"`) significa por definição
"equivalente, não idêntico", então dois pools DIFERENTES podiam compartilhar um
`ref` — e uma decisão humana tomada sobre o pool A seria casada com itens do
pool B. O inverso também mordia: ETag derivado de inode ou variado por nó de
CDN muda para bytes IDÊNTICOS, e cada mudança de `ref` órfã toda a fila de
revisão daquele conjunto. A garantia de content-addressing do protocolo
`Source` é mais funda do que aquela linha do spec, e é ela que vence. O ETag
volta a ter uso no dia em que houver cache — como `If-None-Match`, que é para
o que ele serve.

**O servidor passa a fazer requisições para URLs que vêm da tela.** Recusar
loopback e link-local antes de qualquer requisição é o mínimo contra usar a
plataforma para alcançar o que só o servidor alcança. A guarda olha o HOST
literal e recusa: `localhost` (e `*.localhost`), loopback/link-local/
unspecified em notação canônica (`127.0.0.1`, `169.254.x.x`, `0.0.0.0`,
`::`, `::ffff:127.0.0.1`), e host numérico em forma NÃO canônica que todo
stack HTTP resolve para uma máquina (`127.1`, `2130706433`, `0x7f000001`,
`0177.0.0.1`). O que fica de fora, dito em voz alta em vez de fingido: um
nome DNS que resolva para loopback (`meu-loopback.example.com`) não é
pego — isso exige resolver o nome — nem faixas privadas (`10.x`, `192.168.x`)
que não são loopback/link-local.

O token é um NOME de variável; o cabeçalho de autorização não entra em `ref`,
mensagem de erro nem log. O transporte é INJETÁVEL (`httpx.MockTransport`
nos testes); o default importa `httpx` dentro do `load()`.
"""

import hashlib
import ipaddress
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from orchestrator.kernel.work import WorkItem, WorkSet
from orchestrator.sources.erros import ErroDeFonte, ExtraAusente, FonteFalhou, VariavelAusente

MAX_LINHAS_PADRAO = 5000
# O teto de BYTES do corpo. Irmão do `max_linhas`, e mora numa camada abaixo:
# `max_linhas` conta itens DEPOIS do `json.loads`, e para chegar lá o corpo
# inteiro já teve que caber na memória. Sem este teto, `GET` numa URL que
# devolve 2 GB derruba o processo antes de qualquer guarda falar — por uma rota
# sem autenticação.
MAX_BYTES_PADRAO = 32 * 1024 * 1024
_log = logging.getLogger("orchestrator.sources")


_HOST_NUMERICO = re.compile(
    r"^(0x[0-9a-f]+|[0-9]+)(\.(0x[0-9a-f]+|[0-9]+))*$", re.IGNORECASE
)


def _ip_perigoso(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return True
    mapeado = getattr(ip, "ipv4_mapped", None)
    return mapeado is not None and _ip_perigoso(mapeado)


def _guarda_url(url: str) -> None:
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise FonteFalhou(f"a url precisa ser http(s) com host: {url!r}")
    if partes.username or partes.password:
        # `https://usuario:senha@host/x` FUNCIONA como autenticação — httpx
        # transforma o userinfo em `Authorization: Basic …` —, e é por isso que
        # alguém com uma API de Basic Auth escreveria exatamente isto no campo
        # `url` da tela. Só que a url inteira vai para o `ref`, e o `ref` volta
        # no corpo da resposta e é persistido em `data/runs/*.jsonl`: a senha
        # viajaria por todos os lugares que esta fatia existe para manter
        # limpos. Recusar, e não limpar: uma url "saneada" ainda seria a url que
        # a pessoa acha que está usando, e o `ref` deixaria de nomear o pedido.
        #
        # A mensagem NÃO ecoa a url — ela contém o segredo que estamos recusando.
        raise FonteFalhou(
            "url com usuário/senha embutidos recusada: o segredo entraria no "
            "`ref` e no run persistido. use `token_env` — o NOME de uma variável "
            "de ambiente deste servidor — para autenticar"
        )
    host = partes.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise FonteFalhou("url de loopback recusada: o servidor não faz requisição a si mesmo")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if _HOST_NUMERICO.match(host):
            raise FonteFalhou(f"host numérico em forma não canônica recusado: {host}") from None
        return  # nome DNS: aceito (ver o cabeçalho sobre o limite)
    if _ip_perigoso(ip):
        raise FonteFalhou(f"url de loopback/link-local/unspecified recusada: {host}")


def _transporte_padrao() -> Any:
    try:
        import httpx
    except ImportError as erro:
        raise ExtraAusente("httpx") from erro
    return httpx.HTTPTransport()


def _ler_com_teto(resposta: Any, teto: int) -> bytes:
    """Os bytes do corpo, parando NO teto — não depois dele.

    Acumular e conferir no fim seria o teto que não protege de nada: o estrago
    do corpo grande é ter cabido na memória, e ele já teria cabido.
    """
    pedacos: list[bytes] = []
    total = 0
    for pedaco in resposta.iter_bytes():
        total += len(pedaco)
        if total > teto:
            raise FonteFalhou(
                f"a resposta passou de {teto} bytes, o teto desta fonte — "
                f"a leitura foi interrompida"
            )
        pedacos.append(pedaco)
    return b"".join(pedacos)


def _seguir(corpo: Any, caminho: str) -> Any:
    for chave in (c for c in caminho.split(".") if c):
        if not isinstance(corpo, dict) or chave not in corpo:
            raise FonteFalhou(f"o caminho {caminho!r} não leva a uma lista: parou em {chave!r}")
        corpo = corpo[chave]
    return corpo


@dataclass(frozen=True)
class HttpSource:
    url: str
    token_env: str | None
    kind: str
    campo_id: str
    caminho: str = ""
    max_linhas: int = MAX_LINHAS_PADRAO
    max_bytes: int = MAX_BYTES_PADRAO
    transporte: Any = field(default=None, compare=False)
    # O CORPO, e mais nada: o ETag saiu do memo junto com o `ref` que o usava.
    # Memo: `ref` e `load()` são UMA requisição.
    _corpo: bytes | None = field(default=None, init=False, repr=False, compare=False)

    def _buscar(self) -> bytes:
        """O corpo, com o teto de bytes aplicado AQUI.

        O teto mora nesta função, e não no `load()`, pelo motivo que
        `ArquivoSource._bytes()` escreve: `ref` não passa por `load()`. Um teto
        conferido só lá deixaria `fonte.ref` baixar 2 GB em silêncio e só então
        ter um teto consultado sobre outra coisa.
        """
        if self._corpo is not None:
            return self._corpo
        _guarda_url(self.url)
        cabecalhos = {}
        if self.token_env is not None:
            token = os.environ.get(self.token_env)
            if token is None:
                raise VariavelAusente(self.token_env)
            cabecalhos["Authorization"] = f"Bearer {token}"
        try:
            import httpx
        except ImportError as erro:
            raise ExtraAusente("httpx") from erro
        transporte = self.transporte or _transporte_padrao()
        try:
            with httpx.Client(transport=transporte, timeout=30.0) as cliente:
                # `stream` e não `get`: `resposta.content` bufferiza o corpo
                # INTEIRO antes de qualquer linha nossa rodar, e então o teto
                # chegaria tarde demais para servir de teto.
                with cliente.stream("GET", self.url, headers=cabecalhos) as resposta:
                    if not 200 <= resposta.status_code < 300:
                        # Só status e URL. O corpo pode ecoar o token; a
                        # mensagem, nunca — e aqui ele nem chega a ser lido.
                        raise FonteFalhou(f"GET {self.url} devolveu {resposta.status_code}")
                    corpo = _ler_com_teto(resposta, self.max_bytes)
        except ErroDeFonte:
            # As recusas desta fonte já estão escritas para o cliente. Sem esta
            # cláusula o `except` de baixo as engoliria e devolveria
            # "requisição falhou: FonteFalhou", perdendo o motivo.
            raise
        except Exception as erro:
            # A url já passou por `_guarda_url`, que recusa userinfo: não há
            # segredo nela para o log carregar.
            _log.error("fonte http:%s — requisição falhou: %s", self.url, erro)
            raise FonteFalhou(f"requisição falhou: {type(erro).__name__}") from erro
        object.__setattr__(self, "_corpo", corpo)
        return corpo

    @property
    def ref(self) -> str:
        # SEMPRE o hash do corpo — ver o cabeçalho do módulo sobre o ETag.
        return f"http:{self.url}@{hashlib.sha256(self._buscar()).hexdigest()}"

    def load(self) -> WorkSet:
        import json

        corpo = self._buscar()
        try:
            dados = json.loads(corpo)
        except ValueError as erro:
            raise FonteFalhou("a resposta não é JSON") from erro
        lista = _seguir(dados, self.caminho)
        if not isinstance(lista, list):
            raise FonteFalhou(
                f"a resposta precisa ser uma lista de objetos, e veio {type(lista).__name__}"
            )
        if len(lista) > self.max_linhas:
            raise FonteFalhou(
                f"a resposta tem {len(lista)} itens, acima do teto de {self.max_linhas}"
            )
        itens = []
        for i, obj in enumerate(lista, start=1):
            if not isinstance(obj, dict):
                raise FonteFalhou(f"item {i} não é um objeto: {type(obj).__name__}")
            valor = obj.get(self.campo_id)
            if valor is None or (isinstance(valor, str) and valor.strip() == ""):
                raise FonteFalhou(
                    f"item {i} não tem o campo_id {self.campo_id!r} (ou ele está vazio). "
                    f"campos: {sorted(obj)}"
                )
            itens.append(WorkItem(id=str(valor), kind=self.kind, payload=obj))
        return WorkSet(items=tuple(itens))
