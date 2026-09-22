"""O bloco que busca, para CADA item, o detalhe que a lista não trouxe.

**Por que ele existe.** `Input` traz uma lista de uma API; os blocos de decisão
julgam o que está no item. Entre os dois faltava a operação mais comum de
automação, e sem ela a única saída era pagar um turno de modelo para executar um
`GET` cujo resultado não depende de julgamento nenhum — exatamente o que o §2 do
README proíbe. Medido no caso que motivou este bloco: a fila da mesa do Barrier
devolve `assessmentId`, fila e SLA, e nada disso classifica risco; o que
classifica está em `/v1/assessments/{id}`, uma chamada por item.

**Por que ele mora em `sources/` e não em `regras/`.** `regras` importa só
`kernel`, por decisão de arquitetura: uma regra determinística casa por nome de
campo e não conhece o mundo. Este bloco precisa da guarda de host, do cliente e
do teto de bytes, que moram aqui. O precedente é exato — `sources/bloco.py` é o
`Input`, um resolver que mora em `sources` pela mesma razão.

**Consome e produz**, como `condicao` e `Tarefa`: o kernel não tem alteração em
lugar — resolução consome, produção cria. É isso que põe o bloco no grafo, faz
a aresta aparecer no canvas e mantém a recusa de beco sem saída viva.

**Uma REGRA que faz I/O.** Até aqui toda regra era pura. A classe continua
medindo DINHEIRO — o bloco custa 0 µ¢, e isso é verdade —; o que ele ganha é
latência e um modo de falha. Ele nunca entra no caminho do golden
(`--seed 1 --n 500`), que é determinístico porque a cascata de conciliação é
pura.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from orchestrator.kernel.cost import CostClass
from orchestrator.kernel.resolution import Resolution
from orchestrator.kernel.resolver import ResolverDescription, ResolverOutput
from orchestrator.kernel.work import WorkItem, WorkSet, campos_de
from orchestrator.sources.erros import (
    ErroDeFonte,
    ExtraAusente,
    FonteFalhou,
    VariavelAusente,
)
from orchestrator.sources.http import (
    MAX_BYTES_PADRAO,
    _guarda_url,
    _ler_com_teto,
    _seguir,
    _transporte_padrao,
    _url_publica,
)

_log = logging.getLogger("orchestrator.sources")


@dataclass(frozen=True)
class Enriquecimento:
    """Consome `kind`, busca `url` por item, funde a resposta, produz `produz`."""

    kind: str
    produz: str
    url: str
    token_env: str | None = None
    caminho: str = ""
    max_bytes: int = MAX_BYTES_PADRAO
    transporte: Any = field(default=None, compare=False)

    name: str = field(default="enriquecer", init=False)
    cost_class: CostClass = field(default=CostClass.REGRA, init=False)

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("enriquecer: diga sobre qual kind ele roda")
        if not self.produz.strip():
            raise ValueError(
                "enriquecer: `produz` vazio. o item seria consumido sem ser "
                "entregue a ninguém — para descartar de propósito existe o `filtro`"
            )
        if self.produz == self.kind:
            raise ValueError(
                f"enriquecer: produz o mesmo kind que consome ({self.kind!r}). "
                f"o ramo alimentaria a si mesmo"
            )
        if "{" not in self.url:
            raise ValueError(
                f"enriquecer: a url não interpola campo nenhum do item "
                f"({_url_publica(self.url)}). todo item buscaria o MESMO recurso, "
                f"e uma chamada por item que devolve sempre a mesma coisa é uma "
                f"fonte, não um enriquecimento"
            )

    def describe(self) -> ResolverDescription:
        return ResolverDescription(
            name=self.name,
            cost_class=self.cost_class,
            # ESTÁTICO, e igual ao `resumo` do catálogo: há um teste que os
            # compara, para a paleta e o grafo não contarem duas histórias sobre
            # o mesmo bloco. A url não se perde — ela é um PARÂMETRO, e o nó do
            # canvas mostra os parâmetros.
            summary="busca numa API o detalhe de cada item e funde no payload",
            consome=frozenset({self.kind}),
            produz=frozenset({self.produz}),
        )

    def resolve(self, work: WorkSet) -> ResolverOutput:
        """Uma requisição por item. Falha de UM item não derruba o run.

        Toda desistência é registrada no LOG, e não no trace: `ResolverOutput`
        não tem canal por item para "pulei este e eis por quê" — é a mesma
        lacuna que `agent/tarefa.py` declara sobre o teto de orçamento. O sinal
        visível de um item pulado é ele aparecer na lacuna, que é a notícia
        certa: um payload pela metade seria lido como fato pelo degrau seguinte.
        """
        resolucoes: list[Resolution] = []
        produzidos: list[WorkItem] = []
        for item in work.of_kind(self.kind):
            try:
                campos = campos_de(item.payload)
            except TypeError:
                _log.warning("enriquecer: item %s tem payload sem campos; pulado", item.id)
                continue
            try:
                url = self.url.format_map(campos)
            except KeyError as erro:
                # NOMEIA o campo, como `_prompt_do_item` faz: sem isto quem monta
                # o workflow vê só a lacuna e não sabe se errou o nome do campo
                # ou se a API caiu.
                _log.warning(
                    "enriquecer: a url cita %s e o item %s não tem esse campo; "
                    "disponíveis: %s",
                    erro,
                    item.id,
                    sorted(campos),
                )
                continue
            # A guarda de host roda AQUI, fora do `try` que abstém, e isso é
            # uma decisão: uma url de loopback é CONFIGURAÇÃO, não falha de
            # item. Todo item falharia igual, e abster na fila inteira para não
            # fazer nada é exatamente o que `VariavelAusente` já recusa fazer.
            # Falha alto, no primeiro item, com o texto da guarda.
            _guarda_url(url)
            try:
                dados = self._buscar(url)
            except VariavelAusente:
                # Credencial é CONFIGURAÇÃO: falha alto, uma vez. Abster item a
                # item por falta de token gastaria a fila inteira para não fazer
                # nada.
                raise
            except ErroDeFonte as erro:
                _log.warning("enriquecer: item %s não enriquecido — %s", item.id, erro)
                continue
            if not isinstance(dados, dict):
                _log.warning(
                    "enriquecer: item %s — a resposta em %r não é objeto (%s); não "
                    "há campos para fundir",
                    item.id,
                    self.caminho or "(corpo)",
                    type(dados).__name__,
                )
                continue
            # O ORIGINAL vence: uma resposta de fora não reescreve o campo que
            # identifica o item — se reescrevesse, o id do run, a chave da fila e
            # a decisão humana passariam a apontar para coisas diferentes. É a
            # regra OPOSTA à do `BlocoTarefa`, onde o texto novo vence, e a
            # assimetria é deliberada: lá o campo novo é a saída do trabalho.
            descartados = sorted(set(dados) & set(campos))
            if descartados:
                _log.info(
                    "enriquecer: item %s — campos da resposta descartados por "
                    "colisão com o item: %s",
                    item.id,
                    descartados,
                )
            produzidos.append(
                WorkItem(
                    id=f"{item.id}+{self.produz}",
                    kind=self.produz,
                    payload={**dados, **campos},
                    origem=self.name,
                )
            )
            resolucoes.append(
                Resolution(
                    item_ids=frozenset({item.id}),
                    produced_by=self.name,
                    rule=self.name,
                    # A url PÚBLICA: a query pode ser `?api_key=…`, e esta
                    # evidência é persistida com o run.
                    evidence={"url": _url_publica(url)},
                )
            )
        return ResolverOutput(resolutions=resolucoes, produced=tuple(produzidos))

    def _buscar(self, url: str) -> Any:
        """Uma requisição, com as MESMAS guardas da fonte HTTP.

        Importadas de `http.py`, nunca copiadas: userinfo recusado, query
        redigida no que a gente registra, host de loopback/link-local barrado e
        teto de bytes. Cada uma delas custou uma vez; a segunda cópia divergiria.
        """
        import json

        # `_guarda_url` já rodou em `resolve`, fora do `try` que abstém — ver o
        # comentário de lá. Repeti-la aqui daria duas respostas para "o que
        # acontece com um host recusado", e a que divergisse seria a que
        # ninguém testa.
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
                # `stream` e não `get`, como na fonte: `resposta.content`
                # bufferiza o corpo INTEIRO antes de qualquer linha nossa rodar,
                # e então o teto chegaria tarde demais para servir de teto.
                with cliente.stream("GET", url, headers=cabecalhos) as resposta:
                    if not 200 <= resposta.status_code < 300:
                        # Só status e a url PÚBLICA: o corpo pode ecoar o token.
                        raise FonteFalhou(
                            f"GET {_url_publica(url)} devolveu {resposta.status_code}"
                        )
                    corpo = _ler_com_teto(resposta, self.max_bytes)
        except ErroDeFonte:
            raise
        except Exception as erro:
            _log.error("enriquecer:%s — requisição falhou: %s", _url_publica(url), erro)
            raise FonteFalhou(f"requisição falhou: {type(erro).__name__}") from erro
        try:
            dados = json.loads(corpo)
        except ValueError as erro:
            raise FonteFalhou("a resposta não é JSON") from erro
        return _seguir(dados, self.caminho)
