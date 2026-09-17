"""O registro de ferramentas: schema, permissão, timeout e custo num lugar só.

Antes deste módulo havia DUAS listas paralelas: `ToolContext`, um objeto com
cinco métodos, e `TOOL_SCHEMAS`, uma lista literal ao lado. O despacho era
`getattr(self.context, c.name)` cruzado com `{s["name"] for s in TOOL_SCHEMAS}` —
uma ferramenta podia existir num lado e não no outro, e só uma chamada do modelo
descobriria.

É o mesmo join frágil que o `CATALOGO` do grill já resolveu para resolvers, e o
comentário de lá diz por quê: "um resolver que o grill consegue propor é, por
construção, um resolver que o motor consegue rodar — não porque alguém valida,
mas porque não há de onde vir". Aqui vale igual: o schema que o modelo vê sai da
mesma estrutura que o despacho usa.

**O que é novo além de juntar as duas listas:** permissão, timeout e custo por
ferramenta. Nenhum dos três tinha onde morar, e os três são pré-requisito de
coisas já agendadas — `ToolPermission` é o que contém uma ferramenta MCP de
terceiro (§18.2), e `cost_microcents` é o que permite uma ferramenta paga
aparecer na conta.
"""

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ToolPermission(StrEnum):
    """O que uma ferramenta pode fazer. Ordem crescente de risco."""

    READ_ONLY = "read_only"
    WRITE = "write"
    EXTERNAL = "external"


@dataclass(frozen=True)
class ToolSpec:
    """Uma ferramenta: o que o modelo vê e o que o runtime executa, juntos."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    # `fn(contexto, **argumentos)`. O CONTEXTO É O PRIMEIRO ARGUMENTO, sempre,
    # inclusive nas ferramentas que o ignoram.
    #
    # Antes ele vinha ligado por closure (`getattr(contexto, nome)`), e isso
    # fazia o registro carregar DADOS além de ferramentas. A consequência só
    # apareceu ao tentar listar o catálogo de um domínio sem ter os dados: um
    # registro construído com contexto vazio LISTAVA certo e EXECUTAVA errado,
    # devolvendo zero resultados sem erro nenhum. Silencioso e sobre dados — a
    # pior combinação que este projeto conhece.
    #
    # Assinatura UNIFORME, mesmo nas que ignoram o contexto: variável exigiria
    # introspecção para saber o que passar, e é esse padrão que já deu um
    # defeito silencioso no `_construir_definicao` da API (ver
    # `agent.declarado.RegraDisponivel.construir` e `workflows.WorkflowFactory`,
    # que tomaram a mesma decisão pela mesma razão).
    fn: Callable[..., Any]
    permission: ToolPermission = ToolPermission.READ_ONLY
    timeout_s: float = 10.0
    # Ferramenta que chama API paga. Zero para as locais, que é o caso de todas
    # as de conciliação — e é por isso que o custo do agente hoje é só token.
    cost_microcents: int = 0
    # Obrigatória quando `permission is WRITE`: o nome da ferramenta que desfaz
    # esta. Ver §6.5 — enquanto toda ferramenta for read-only não há o que
    # compensar, e o registry é onde essa condição deixa de ser promessa.
    compensates: str | None = None

    def schema(self) -> dict[str, Any]:
        """O que vai para a API do modelo. Derivado, nunca escrito à mão."""
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": dict(self.input_schema),
        }


@dataclass(frozen=True)
class ToolResult:
    """O resultado de uma chamada, com o que a observabilidade precisa.

    `error` não é exceção: erro de ferramenta volta ao modelo como texto,
    sempre. Preservado de `Investigator._executar`, que documenta a razão — o
    modelo se corrige sozinho, o processo não se recupera de um estouro.
    """

    name: str
    value: Any
    duration_ms: int
    cost_microcents: int = 0
    error: str | None = None

    def para_modelo(self) -> Any:
        """O que volta no bloco `tool_result`."""
        return {"erro": self.error} if self.error else self.value


# As palavras de JSON Schema que a Messages API aceita dentro de um
# `input_schema` de ferramenta. LISTA BRANCA, e a escolha é deliberada.
#
# Medido em 2026-09-16: `"minimum": 1` num campo `integer` fez a API recusar a
# requisição INTEIRA com `tools.0.custom: For 'integer' type, property
# 'minimum' is not supported`. Nenhum dos 620 testes viu — o `FakeLLMClient`
# não valida schema, então a primeira notícia foi uma avaliação inteira
# falhando 2/2 com dinheiro real na mesa.
#
# Lista NEGRA envelheceria: teria de adivinhar todas as palavras recusadas e
# ficaria desatualizada a cada mudança da API, em silêncio, que é exatamente o
# modo de falha de agora. A branca falha alto no sentido seguro — palavra nova
# é recusada até alguém conferir contra a API e adicioná-la aqui.
_PALAVRAS_DE_SCHEMA = frozenset(
    {"type", "description", "properties", "required", "additionalProperties",
     "items", "enum"}
)


def _validar_palavras(ferramenta: str, schema: Mapping[str, Any], onde: str) -> None:
    """Recusa palavra de schema que a API não aceita, recursivamente."""
    desconhecidas = sorted(set(schema) - _PALAVRAS_DE_SCHEMA)
    if desconhecidas:
        raise ValueError(
            f"{ferramenta!r}: {onde} usa {desconhecidas} — palavra de JSON "
            f"Schema fora da lista branca. A Messages API recusa a requisição "
            f"inteira por causa de uma ferramenta malformada, e o erro só "
            f"aparece gastando dinheiro. Se a API aceita, some a "
            f"`_PALAVRAS_DE_SCHEMA` com a evidência"
        )
    # As CHAVES de `properties` são nomes de campo, não palavras-chave; quem é
    # schema são os valores.
    for campo, sub in (schema.get("properties") or {}).items():
        if isinstance(sub, Mapping):
            _validar_palavras(ferramenta, sub, f"{onde}.properties.{campo}")
    itens = schema.get("items")
    if isinstance(itens, Mapping):
        _validar_palavras(ferramenta, itens, f"{onde}.items")


# Distingue "contexto ainda não ligado" de "contexto é None de propósito". Sem
# a sentinela, um domínio cujas ferramentas não precisam de dados (`swe`) seria
# indistinguível de um que esqueceu de ligar (`conciliacao`) — e o segundo
# executaria devolvendo nada.
_NAO_LIGADO = object()


class ToolRegistry:
    """As ferramentas de um agente. Uma fonte para schema e despacho.

    Um registro tem duas vidas. **Sem contexto** ele é um CATÁLOGO: serve para
    listar, validar declaração e montar schema, e recusa executar. **Com
    contexto** (`com_contexto`) ele executa.

    Separar as duas é o que permite um domínio publicar o que sabe fazer sem
    ter dados em mãos — que é a pergunta que a tela de composição faz.
    """

    def __init__(
        self,
        specs: list[ToolSpec] | None = None,
        *,
        contexto: Any = _NAO_LIGADO,
    ) -> None:
        self._por_nome: dict[str, ToolSpec] = {}
        self._contexto = contexto
        for s in specs or []:
            self.register(s)

    @property
    def ligado(self) -> bool:
        return self._contexto is not _NAO_LIGADO

    def com_contexto(self, contexto: Any) -> "ToolRegistry":
        """As MESMAS ferramentas, agora ligadas a dados.

        Devolve um registro novo em vez de mutar: o catálogo de um domínio é
        compartilhado, e ligá-lo a um contexto no lugar mudaria o que todo mundo
        vê por causa de uma execução.
        """
        novo = ToolRegistry(contexto=contexto)
        for s in self._por_nome.values():
            novo.register(s)
        return novo

    def recortar(self, nomes: Iterable[str]) -> "ToolRegistry":
        """Um sub-registro com as ferramentas escolhidas, **mesmo contexto**.

        Existe porque a alternativa — `ToolRegistry([reg.spec(n) for n in ...])`
        — perde o contexto em silêncio, e o sintoma é caro: o agente construído
        recebe um registro DESLIGADO, toda chamada de ferramenta volta como
        `ToolResult.error`, e como `call` nunca levanta, o laço continua, o
        modelo insiste, e a conta cresce. "Não achei nada" indistinguível de
        "não procurei", agora em cima de um orçamento.

        Era exatamente o que `construir_agente` fazia. Foi encontrado lendo, não
        por teste, porque todo teste de composição usava `FakeLLMClient`, que
        nunca pede ferramenta.

        O recorte é do registro e não de quem chama: um segundo dicionário fora
        daqui é o join frágil de sempre — e foi ele que perdeu o contexto.
        """
        novo = ToolRegistry(contexto=self._contexto)
        for n in nomes:
            novo.register(self.spec(n))
        return novo

    def register(self, spec: ToolSpec) -> None:
        """Valida registrando. Se registrou, dá para chamar.

        Mesma disciplina de `Receita.construir` ("validar é construir"): o que
        passa daqui é executável, e o schema que o modelo vê saiu da mesma
        entrada que o despacho vai usar.
        """
        if spec.name in self._por_nome:
            raise ValueError(
                f"ferramenta repetida no registro: {spec.name!r}. duas com o "
                f"mesmo nome fariam o despacho depender da ordem de registro"
            )
        if spec.permission is ToolPermission.WRITE and not spec.compensates:
            raise ValueError(
                f"{spec.name!r} é WRITE e não declara compensadora. enquanto "
                f"toda ferramenta for somente-leitura não há o que compensar "
                f"(§6.5); a primeira que escrever precisa dizer como desfazer"
            )
        if spec.timeout_s <= 0:
            raise ValueError(
                f"timeout de {spec.name!r} precisa ser positivo: {spec.timeout_s}"
            )
        _validar_palavras(spec.name, spec.input_schema, "input_schema")
        self._por_nome[spec.name] = spec

    def __contains__(self, nome: str) -> bool:
        return nome in self._por_nome

    def spec(self, nome: str) -> ToolSpec:
        """A ferramenta pelo nome. Levanta se não existe.

        Existe para o RECORTE: um agente declarado recebe as ferramentas que
        declara, não as que por acaso estão no registro do domínio. Sem poder
        pegar uma por nome, o recorte seria feito por quem chama, com uma
        segunda cópia do dicionário.

        `KeyError` e não `None`: quem pede uma ferramenta pelo nome já checou a
        lista, e um `None` silencioso viraria um registro com um buraco.
        """
        if nome not in self._por_nome:
            raise KeyError(
                f"ferramenta desconhecida: {nome!r}. disponíveis: "
                f"{sorted(self._por_nome)}"
            )
        return self._por_nome[nome]

    def names(self) -> tuple[str, ...]:
        return tuple(self._por_nome)

    def schemas(self, names: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        """Os schemas que vão para o modelo, na ordem de registro.

        Ordem estável porque o system prompt e os schemas são marcados para
        cache (`anthropic_client`), e cache com ordem instável é cache que
        nunca acerta.
        """
        escolhidos = self._por_nome if names is None else {n: self._por_nome[n] for n in names}
        return [s.schema() for s in escolhidos.values()]

    def call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        """Executa e mede. NUNCA levanta por causa da ferramenta.

        Ferramenta inexistente e ferramenta que estourou produzem o mesmo tipo
        de saída: um `ToolResult` com `error`. É a política de
        `Investigator._executar` preservada — a captura larga aqui É o
        requisito, e é a inversão exata da captura estreita em volta de
        `client.complete()`.
        """
        import time

        spec = self._por_nome.get(name)
        if spec is None:
            return ToolResult(
                name=name, value=None, duration_ms=0, error="ferramenta inexistente"
            )
        if not self.ligado:
            # Recusa ALTA em vez de executar com dados ausentes. Uma ferramenta
            # de conciliação chamada sem `ToolContext` devolveria lista vazia —
            # e "não achei nada" é indistinguível de "não procurei".
            return ToolResult(
                name=name,
                value=None,
                duration_ms=0,
                error=(
                    "registro não ligado a dados: este é o catálogo do domínio, "
                    "não um registro executável. use `com_contexto(...)`"
                ),
            )
        inicio = time.perf_counter()
        try:
            # `None` some dos argumentos: o schema declara os campos como
            # `["integer", "null"]` para que o modelo possa omitir logicamente
            # sem quebrar `strict`, e quem recebe é uma função Python com
            # defaults. Preservado de `Investigator._executar`.
            limpos = {k: v for k, v in arguments.items() if v is not None}
            valor, erro = spec.fn(self._contexto, **limpos), None
        except Exception as e:  # noqa: BLE001
            valor, erro = None, str(e)
        return ToolResult(
            name=name,
            value=valor,
            duration_ms=int((time.perf_counter() - inicio) * 1000),
            cost_microcents=spec.cost_microcents,
            error=erro,
        )


def tool_schema(
    nome: str, descricao: str, props: Mapping[str, Any], obrigatorios: list[str]
) -> dict[str, Any]:
    """Monta um `input_schema` JSON Schema no formato que a API exige."""
    return {
        "type": "object",
        "properties": dict(props),
        "required": list(obrigatorios),
        "additionalProperties": False,
    }


def overhead_de_schemas(registry: ToolRegistry) -> int:
    """Tamanho em caracteres dos schemas, para a derivação de orçamento.

    Existe porque `Investigator.budget_microcents` é derivado de
    `len(json.dumps(TOOL_SCHEMAS))` e há um teste que reproduz a conta. Com o
    registry, a conta continua reproduzível a partir da MESMA fonte que o
    modelo vê — e `ensure_ascii=False` não é detalhe: sem ele os acentos viram
    `\\uXXXX` e a conta dá outro número (ver a derivação em
    `grill/entrevistador.py`).
    """
    return len(json.dumps(registry.schemas(), ensure_ascii=False))


__all__ = [
    "ToolPermission",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "overhead_de_schemas",
    "tool_schema",
]
