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
from collections.abc import Callable, Mapping
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


class ToolRegistry:
    """As ferramentas de um agente. Uma fonte para schema e despacho."""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._por_nome: dict[str, ToolSpec] = {}
        for s in specs or []:
            self.register(s)

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
        self._por_nome[spec.name] = spec

    def __contains__(self, nome: str) -> bool:
        return nome in self._por_nome

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
        inicio = time.perf_counter()
        try:
            # `None` some dos argumentos: o schema declara os campos como
            # `["integer", "null"]` para que o modelo possa omitir logicamente
            # sem quebrar `strict`, e quem recebe é uma função Python com
            # defaults. Preservado de `Investigator._executar`.
            limpos = {k: v for k, v in arguments.items() if v is not None}
            valor, erro = spec.fn(**limpos), None
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
