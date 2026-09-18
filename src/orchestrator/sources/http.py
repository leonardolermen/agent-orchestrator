"""Uma API HTTP como pool de trabalho — uma página, com token por nome.

Fecha o R7 que o spec de agentes-rodando adiou: `ref` = `http:<url pública>@
<sha256 do corpo>`, SEMPRE. Paginação e cursor ficam FORA (o `ref` de várias
páginas é desenho próprio) e estão escritos como fora no spec.

**A url pode carregar segredo; o que ela NÃO pode é levá-lo consigo.** Duas
formas, e cada uma com o tratamento que merece: userinfo (`user:senha@`) é
sempre credencial e é RECUSADO; a query (`?api_key=…`) às vezes é credencial e
às vezes é `?since=2026-01-01`, então ela é REDIGIDA — o que entra no `ref`, no
log e nas mensagens é a url sem query mais o digest dela (`_url_publica`). A
promessa desta fatia é sobre o que a plataforma faz, não sobre o que a pessoa
consegue digitar: **um segredo escrito na url não chega ao `ref`, ao run
persistido, à resposta nem a nenhum log NOSSO** — e o que sobra de fora está
dito no docstring de `_url_publica` (um segredo em segmento de CAMINHO não é
coberto).

**O log do `httpx` não é nosso, e ele imprime a url inteira.** Em nível INFO, o
logger `httpx` escreve `HTTP Request: GET <url com query> "HTTP/1.1 200 OK"` a
cada requisição. Sob o `uvicorn` documentado isto está desligado — a config de
log dele mexe só em `uvicorn*`, e a raiz fica em WARNING —, mas um
`basicConfig(level=INFO)` acrescentado para ver os logs da aplicação liga junto,
e aí o `api_key` vai para o log do servidor, que é exatamente o que
`_url_publica` existe para evitar. Quem ligar INFO na raiz precisa silenciar o
logger `httpx` ou aceitar isso de olhos abertos.

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
from urllib.parse import urlsplit, urlunsplit

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


def _partes(url: str) -> Any:
    """`urlsplit`, com o `ValueError` dele dentro da hierarquia desta camada.

    `urlsplit("https://[::1/x")` levanta `ValueError("Invalid IPv6 URL")` — um
    `ValueError` PURO, de fora de `sources/erros.py`. Pela borda ele virava 422
    por sorte (`ErroDeFonte` é subclasse de `ValueError`, e `_ler` captura os
    dois); por qualquer outro chamador da biblioteca ele rompia o contrato do
    `Source`, que promete erro desta hierarquia. A mensagem não ecoa a url: ela
    pode carregar segredo, e aqui ainda não sabemos o que há dentro.
    """
    try:
        return urlsplit(url)
    except ValueError as erro:
        raise FonteFalhou(f"a url não é analisável: {type(erro).__name__}") from erro


def _url_publica(url: str) -> str:
    """A url sem o que pode ser segredo — a forma que PODE viajar.

    **O que sai: a query e o fragmento.** A query é o outro lugar onde uma API
    pede credencial (`?api_key=…`, `?token=…`), e o campo `url` da tela é texto
    livre: quem tem uma API assim vai escrever exatamente isso. Recusar a query
    inteira seria caro e errado — `?since=2026-01-01` é comum e legítimo —,
    então em vez de proibir que o segredo seja ESCRITO, esta função impede que
    ele VIAJE: o que entra no `ref`, no log e nas mensagens é a url sem query,
    mais o digest dela. Duas urls que diferem só na query continuam com `ref`
    diferentes, que é a propriedade que a query estava ali para dar. O fragmento
    nem chega ao servidor, então some sem custo.

    O userinfo também é removido, e não por defesa em profundidade: esta função
    é chamada DENTRO do `_guarda_url`, para a mensagem da primeira recusa, antes
    de a guarda de userinfo ter rodado.

    O caminho continua inteiro. Um segredo em path (`/v1/<token>/itens`) não é
    coberto — dito aqui em voz alta em vez de fingido: não há como distinguir um
    segmento de caminho secreto de um id, e apagar o caminho apagaria a
    identidade do recurso, que é a razão de a url entrar no `ref`.
    """
    partes = _partes(url)
    try:
        porta = partes.port
    except ValueError:
        porta = None
    autoridade = (partes.hostname or "") + (f":{porta}" if porta else "")
    base = urlunsplit((partes.scheme, autoridade, partes.path, "", ""))
    if not partes.query:
        return base
    return f"{base}?{hashlib.sha256(partes.query.encode('utf-8')).hexdigest()[:12]}"


def _guarda_url(url: str) -> None:
    partes = _partes(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise FonteFalhou(f"a url precisa ser http(s) com host: {_url_publica(url)!r}")
    if partes.username or partes.password:
        # `https://usuario:senha@host/x` FUNCIONA como autenticação — httpx
        # transforma o userinfo em `Authorization: Basic …` —, e é por isso que
        # alguém com uma API de Basic Auth escreveria exatamente isto no campo
        # `url` da tela.
        #
        # RECUSAR aqui, e não só redigir como se faz com a query, porque as duas
        # não são o mesmo caso: uma query legítima é comum (`?since=…`) e recusá-la
        # custaria caro, enquanto userinfo numa url de fonte é sempre uma credencial
        # — não existe `user:senha@` inocente. Recusar diz à pessoa que existe
        # `token_env`; redigir em silêncio a deixaria achando que autenticou.
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
                        # Só status e a url PÚBLICA. O corpo pode ecoar o token;
                        # a mensagem, nunca — e aqui ele nem chega a ser lido.
                        raise FonteFalhou(
                            f"GET {_url_publica(self.url)} devolveu {resposta.status_code}"
                        )
                    corpo = _ler_com_teto(resposta, self.max_bytes)
        except ErroDeFonte:
            # As recusas desta fonte já estão escritas para o cliente. Sem esta
            # cláusula o `except` de baixo as engoliria e devolveria
            # "requisição falhou: FonteFalhou", perdendo o motivo.
            raise
        except Exception as erro:
            # A url PÚBLICA, nunca `self.url`: o userinfo é recusado pela guarda,
            # mas a query não é — ela pode ser `?api_key=…`, e o log do servidor
            # é persistente.
            #
            # `erro` vai INTEIRO, e é a mesma regra do gêmeo de Postgres, que
            # manda o DSN com senha para cá: o log é o lugar DESIGNADO para o
            # texto do driver, e reduzi-lo aqui seria perder a única cópia que
            # quem opera tem. O que esta linha promete é não ACRESCENTAR segredo
            # nosso ao que o driver já disser.
            _log.error("fonte http:%s — requisição falhou: %s", _url_publica(self.url), erro)
            raise FonteFalhou(f"requisição falhou: {type(erro).__name__}") from erro
        object.__setattr__(self, "_corpo", corpo)
        return corpo

    @property
    def ref(self) -> str:
        # A url PÚBLICA (query redigida a digest — ver `_url_publica`) e SEMPRE
        # o hash do corpo — ver o cabeçalho do módulo sobre o ETag. Este `ref`
        # volta no corpo da resposta e é persistido em `data/runs/*.jsonl`: é a
        # razão de a redação morar aqui e não numa camada acima.
        return f"http:{_url_publica(self.url)}@{hashlib.sha256(self._buscar()).hexdigest()}"

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
