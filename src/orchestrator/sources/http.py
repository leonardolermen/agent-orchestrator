"""Uma API HTTP como pool de trabalho — uma página, com token por nome.

Fecha o R7 que o spec de agentes-rodando adiou: `ref` = `http:<url>@<etag>`
quando o servidor manda ETag, senão `@<sha256 do corpo>`. Paginação e cursor
ficam FORA (o `ref` de várias páginas é desenho próprio) e estão escritos
como fora no spec.

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
from orchestrator.sources.erros import ExtraAusente, FonteFalhou, VariavelAusente

MAX_LINHAS_PADRAO = 5000
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
    transporte: Any = field(default=None, compare=False)
    _resposta: tuple[str | None, bytes] | None = field(
        default=None, init=False, repr=False, compare=False
    )  # (etag, corpo) — memo: ref e load são UMA requisição

    def _buscar(self) -> tuple[str | None, bytes]:
        if self._resposta is not None:
            return self._resposta
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
                resposta = cliente.get(self.url, headers=cabecalhos)
        except Exception as erro:
            _log.error("fonte http:%s — requisição falhou: %s", self.url, erro)
            raise FonteFalhou(f"requisição falhou: {type(erro).__name__}") from erro
        if not 200 <= resposta.status_code < 300:
            # Só status e URL. O corpo pode ecoar o token; a mensagem, nunca.
            raise FonteFalhou(f"GET {self.url} devolveu {resposta.status_code}")
        memo = (resposta.headers.get("ETag"), resposta.content)
        object.__setattr__(self, "_resposta", memo)
        return memo

    @property
    def ref(self) -> str:
        etag, corpo = self._buscar()
        marca = etag if etag else hashlib.sha256(corpo).hexdigest()
        return f"http:{self.url}@{marca}"

    def load(self) -> WorkSet:
        import json

        _, corpo = self._buscar()
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
