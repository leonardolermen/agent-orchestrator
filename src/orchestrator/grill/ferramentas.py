"""As três ferramentas. Todo turno do modelo termina em exatamente uma.

`perguntar` é FERRAMENTA, e não texto livre, de propósito: se a pergunta fosse
prosa solta, "isto é uma pergunta ou o modelo pensando alto?" viraria
heurística, e um turno em que ele apenas comenta travaria o laço esperando
resposta a nada. Como ferramenta, o fim da entrevista é evento tipado.
"""

from dataclasses import dataclass
from typing import Any

from orchestrator.agent.declarado import (
    AgenteDeclarado,
    TarefaDeclarada,
    ValorDeParametro,
)
from orchestrator.agent.llm import ToolCall
from orchestrator.authoring.composicao import (
    Bloco,
    BlocoAgente,
    BlocoCrew,
    BlocoRegra,
    BlocoTarefa,
    Etapa,
)
from orchestrator.domains.registro import CATALOGO

NOMES = ("perguntar", "propor_workflow", "fora_do_catalogo")


@dataclass(frozen=True)
class Pergunta:
    texto: str


@dataclass(frozen=True)
class PropostaBruta:
    """Ainda não é `Composicao`: falta o id (que vem da CLI ou do WebSocket) e
    o relógio.

    Os BLOCOS já são os do `authoring`, construídos aqui — e é essa construção
    que recusa declaração inválida antes de a composição existir. A recusa
    chega ao modelo como `is_error` e ele corrige no turno seguinte, que é o
    laço que `entrevistador.py` já roda.
    """

    nome: str
    justificativa: str
    etapas: tuple[Etapa, ...]
    # Os kinds que SÃO a saída. Sem eles, um kind produzido e não consumido é
    # recusado como beco sem saída — e a recusa acontece na construção, com
    # texto escrito para ser lido.
    entrega: tuple[str, ...] = ()
    max_rondas: int = 1


@dataclass(frozen=True)
class Recusa:
    motivo: str
    o_que_faltaria: str


def _nomes_de_regra() -> list[str]:
    """Os nomes que o modelo pode escolher para um bloco de REGRA.

    Era `_nomes_disponiveis`, e trazia os agentes junto — porque agente era
    item de cardápio: o modelo escolhia um dos três prontos do catálogo e não
    tinha como declarar o seu. Com a declaração inline, o `enum` de agente
    deixou de existir; sobra o de regra, que continua sendo derivado do
    catálogo pelo mesmo motivo de sempre: uma lista literal aqui divergiria, e
    o modelo proporia o que `construir_composicao` não conhece — ou nunca
    ficaria sabendo de uma regra nova.
    """
    return sorted(r.nome for r in CATALOGO.regras)


def _nomes_disponiveis() -> list[str]:
    """Tudo que dá para compor POR NOME — regras e os agentes prontos.

    Não é o mesmo que `_nomes_de_regra`, e a diferença é de pergunta. Esta
    responde "o que existe no catálogo com nome?", e quem pergunta é
    `receita.construir`, para dizer o que HÁ quando uma `Receita` cita um
    resolver que não existe. `Receita` compõe por nome, inclusive agente, e
    continua carregando do disco.

    A outra responde "o que o modelo pode escolher num bloco de REGRA?" — e
    ali agente não entra, porque no formato novo ele é declarado, não
    escolhido. Fundir as duas faria a mensagem de erro da receita esconder os
    agentes, ou o `enum` da ferramenta ressuscitar o cardápio.
    """
    return sorted([r.nome for r in CATALOGO.regras] + [a.name for a in CATALOGO.agentes])


def _catalogo_em_texto() -> str:
    """As REGRAS, com seus parâmetros. Só elas.

    Os agentes saíram desta listagem quando deixaram de ser escolhidos de um
    cardápio: um agente agora é declarado, e listá-lo aqui ensinaria o modelo a
    escolher em vez de declarar.

    O `(int, ...)` também saiu, e ele era uma mentira com custo: `ValorDeParametro`
    é `int | str | tuple[str, ...]` desde que as regras genéricas passaram a
    receber NOME DE CAMPO, e dizer "int" informava o modelo de que ele não podia
    escrever `campo: "documento"` num bloco que exige exatamente isso.
    """
    linhas = []
    for r in sorted(CATALOGO.regras, key=lambda x: x.nome):
        if r.parametros:
            params = "; ".join(
                f"{p.nome} (default {p.default!r}) — {p.descricao}" for p in r.parametros
            )
        else:
            params = "sem parâmetros"
        linhas.append(f"- {r.nome} [{r.cost_class.name}]: {r.resumo}. Parâmetros: {params}")
    return "\n".join(linhas)


# As declarações que o modelo PREENCHE, em vez de escolher de uma lista.
#
# Objetos SEPARADOS por tipo, e não um bloco com campos soltos: um `agente` tem
# `tipos`/`abstem_com`, uma `tarefa` tem `produz`, e nenhum dos dois oferece o
# campo do outro. É o mais perto da união discriminada de `api/schemas.py` que
# cabe aqui — `oneOf` está fora de `_PALAVRAS_DE_SCHEMA`, a lista branca medida
# contra a Messages API, e usá-lo derrubaria a requisição inteira por
# ferramenta malformada. O que a união faria sozinha, `_objeto` confere no
# código, com uma recusa que volta ao modelo.
_DECL_AGENTE = {
    "type": "object",
    "description": "um agente que JULGA o item e propõe um tipo. Nunca resolve.",
    "properties": {
        "name": {"type": "string"},
        "system": {"type": "string", "description": "o papel, em uma ou duas frases"},
        "kind": {"type": "string", "description": "o kind de item que ele lê"},
        "prompt": {
            "type": "string",
            "description": (
                "template sobre os CAMPOS do item, ex.: 'Classifique: {titulo}'. "
                "Só cite campo que o parceiro disse existir — campo inventado "
                "não falha aqui, falha na execução, com a conta paga."
            ),
        },
        "tipos": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "o vocabulário FECHADO de saída",
        },
        "abstem_com": {
            "type": "string",
            "description": "o rótulo de 'não sei'. NUNCA um dos `tipos`",
        },
        "ferramentas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "system", "kind", "prompt", "tipos", "abstem_com"],
}

_DECL_TAREFA = {
    "type": "object",
    "description": (
        "um agente que TRANSFORMA: consome um kind e produz outro, e o texto "
        "dele vira o item do degrau seguinte."
    ),
    "properties": {
        "name": {"type": "string"},
        "system": {"type": "string", "description": "o papel, em uma ou duas frases"},
        "kind": {"type": "string", "description": "o kind que ela consome"},
        "produz": {
            "type": "string",
            "description": (
                "o kind que sai, diferente de `kind`. O degrau seguinte lê o "
                "texto no campo com ESTE nome: produz 'rascunho' e o próximo "
                "interpola '{rascunho}'"
            ),
        },
        "prompt": {"type": "string", "description": "template sobre os campos do item"},
        "ferramentas": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "system", "kind", "produz", "prompt"],
}

_BLOCO = {
    "type": "object",
    "description": (
        "UM bloco. `tipo` manda, e você preenche o objeto de mesmo nome: tipo "
        "'regra' pede o objeto `regra`, tipo 'agente' pede `agente`, e assim "
        "por diante. Os outros ficam de fora."
    ),
    "properties": {
        "tipo": {"type": "string", "enum": ["regra", "agente", "tarefa", "crew"]},
        "regra": {
            "type": "object",
            "description": "um bloco determinístico do catálogo, com os parâmetros ajustados",
            "properties": {
                # Do catálogo, nunca literal: ver o teste que trava isto.
                "nome": {"type": "string", "enum": _nomes_de_regra()},
                "parametros": {"type": "object"},
            },
            "required": ["nome"],
        },
        "agente": _DECL_AGENTE,
        "tarefa": _DECL_TAREFA,
        "crew": {
            "type": "object",
            "description": "vários agentes sobre o MESMO item, com política de conflito",
            "properties": {
                "nome": {"type": "string"},
                "agentes": {"type": "array", "items": _DECL_AGENTE, "minItems": 2},
                "process": {"type": "string", "enum": ["sequential", "hierarchical"]},
                "conflito": {"type": "string", "enum": ["abster", "maioria", "sintetizar"]},
            },
            "required": ["nome", "agentes"],
        },
    },
    "required": ["tipo"],
}


def esquemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "perguntar",
            "description": "Faz UMA pergunta ao parceiro e espera a resposta.",
            "input_schema": {
                "type": "object",
                "properties": {"texto": {"type": "string"}},
                "required": ["texto"],
            },
        },
        {
            "name": "propor_workflow",
            "description": (
                "Encerra a entrevista propondo a automação. Regras disponíveis "
                "para blocos de tipo 'regra':\n"
                + _catalogo_em_texto()
                + "\n\nAgente e tarefa NÃO saem de lista: você os declara. "
                "Omita um parâmetro de regra para usar o default. Não repita "
                "um bloco na mesma automação."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "nome": {
                        "type": "string",
                        "description": "rótulo legível, ex.: 'Triagem Acme'",
                    },
                    "justificativa": {
                        "type": "string",
                        "description": "por que esta automação resolve o caso descrito",
                    },
                    "etapas": {
                        "type": "array",
                        "minItems": 1,
                        "description": (
                            "os degraus, em ordem. DENTRO de um degrau a ordem é "
                            "por custo e quem ordena é o motor — regra, depois "
                            "agente, depois humano. ENTRE degraus a ordem é por "
                            "DADO: o seguinte só enxerga o que o anterior produziu."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "nome": {"type": "string"},
                                "blocos": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": _BLOCO,
                                },
                            },
                            "required": ["nome", "blocos"],
                        },
                    },
                    "entrega": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "os kinds que SÃO a saída: o que ninguém consome, de "
                            "propósito. Sem isto, um kind produzido e não "
                            "consumido é recusado como beco sem saída."
                        ),
                    },
                    "max_rondas": {
                        "type": "integer",
                        "description": (
                            "quantas vezes a sequência de etapas pode rodar. 1 é "
                            "uma passada; mais que isso só para aresta de volta — "
                            "o revisor reprova e o rascunho volta ao escritor."
                        ),
                    },
                },
                "required": ["nome", "justificativa", "etapas"],
            },
        },
        {
            "name": "fora_do_catalogo",
            "description": (
                "Encerra a entrevista declarando que o caso não cabe no catálogo. "
                "Desfecho legítimo, não erro."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string"},
                    "o_que_faltaria": {
                        "type": "string",
                        "description": "que resolver precisaria existir",
                    },
                },
                "required": ["motivo", "o_que_faltaria"],
            },
        },
    ]


def _texto(args: dict[str, Any], chave: str) -> str:
    valor = args.get(chave)
    if not isinstance(valor, str):
        raise ValueError(f"argumento {chave!r} ausente ou não é texto")
    if not valor.strip():
        raise ValueError(f"argumento {chave!r} veio vazio")
    return valor


def _valor_de_parametro(nome_do_bloco: str, chave: str, v: Any) -> ValorDeParametro:
    """Um parâmetro como `ValorDeParametro`: inteiro, texto ou lista de textos.

    A versão anterior exigia INTEIRO, e ela foi escrita quando o catálogo era o
    cardápio da conciliação — folga em centavos, janela em dias. As regras
    genéricas recebem NOME DE CAMPO (`campos`, `kind`, `teste`), então aquela
    exigência impedia o modelo de propor `filtro`, `condicao`, `tabela` e
    `entrada`: exatamente os blocos que fazem a plataforma ser geral.

    Float continua recusado: dinheiro e janelas são int, e um 10.5 aqui viraria
    float silencioso no centavo.
    """
    # `isinstance(True, int)` é True em Python: sem esta linha, `max_cents=true`
    # viraria 1 em silêncio.
    if isinstance(v, bool):
        raise ValueError(
            f"parâmetro {chave!r} de {nome_do_bloco!r} veio booleano ({v!r}); "
            f"use inteiro, texto ou lista de textos"
        )
    if isinstance(v, (int, str)):
        return v
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return tuple(v)
    raise ValueError(
        f"parâmetro {chave!r} de {nome_do_bloco!r} precisa ser inteiro, texto "
        f"ou lista de textos, veio {v!r}"
    )


def _objeto(bloco: dict[str, Any], chave: str) -> dict[str, Any]:
    """O objeto que o `tipo` promete.

    É a conferência que a união discriminada faria sozinha no schema, e que
    aqui precisa ser código: `oneOf` está fora da lista branca de JSON Schema
    medida contra a Messages API. A mensagem é escrita para o MODELO, porque é
    ele quem a lê — ela volta como `is_error` e ele corrige no turno seguinte.
    """
    valor = bloco.get(chave)
    if not isinstance(valor, dict):
        raise ValueError(
            f"bloco de tipo {chave!r} sem o objeto {chave!r}: mande "
            f'{{"tipo": "{chave}", "{chave}": {{...}}}}'
        )
    return valor


def _agente_de(d: dict[str, Any]) -> AgenteDeclarado:
    """`AgenteDeclarado.__post_init__` recusa vocabulário vazio, prompt que não
    interpola nada e `abstem_com` colidindo com um tipo. Construir aqui é o que
    faz essas recusas chegarem ao modelo."""
    return AgenteDeclarado(
        name=_texto(d, "name"),
        system=_texto(d, "system"),
        kind=_texto(d, "kind"),
        prompt=_texto(d, "prompt"),
        tipos=tuple(d.get("tipos") or ()),
        abstem_com=_texto(d, "abstem_com"),
        ferramentas=tuple(d.get("ferramentas") or ()),
    )


def _tarefa_de(d: dict[str, Any]) -> TarefaDeclarada:
    return TarefaDeclarada(
        name=_texto(d, "name"),
        system=_texto(d, "system"),
        kind=_texto(d, "kind"),
        produz=_texto(d, "produz"),
        prompt=_texto(d, "prompt"),
        ferramentas=tuple(d.get("ferramentas") or ()),
    )


def _bloco_de(bloco: Any) -> Bloco:
    if not isinstance(bloco, dict):
        raise ValueError(f"bloco malformado: {bloco!r}")
    tipo = bloco.get("tipo")
    if tipo == "regra":
        r = _objeto(bloco, "regra")
        nome = _texto(r, "nome")
        params = r.get("parametros")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError(f"'parametros' de {nome!r} não é objeto")
        return BlocoRegra(
            nome=nome,
            parametros={k: _valor_de_parametro(nome, k, v) for k, v in params.items()},
        )
    if tipo == "agente":
        return BlocoAgente(declaracao=_agente_de(_objeto(bloco, "agente")))
    if tipo == "tarefa":
        return BlocoTarefa(declaracao=_tarefa_de(_objeto(bloco, "tarefa")))
    if tipo == "crew":
        c = _objeto(bloco, "crew")
        agentes = c.get("agentes")
        if not isinstance(agentes, list) or not agentes:
            raise ValueError("tripulação sem agentes: declare pelo menos dois")
        return BlocoCrew(
            nome=_texto(c, "nome"),
            agentes=tuple(_agente_de(a) for a in agentes),
            process=c.get("process") or "sequential",
            conflito=c.get("conflito") or "abster",
        )
    raise ValueError(
        f"tipo de bloco desconhecido: {tipo!r}. use 'regra', 'agente', "
        f"'tarefa' ou 'crew'"
    )


def interpretar(chamada: ToolCall) -> Pergunta | PropostaBruta | Recusa:
    args = chamada.arguments
    if chamada.name == "perguntar":
        return Pergunta(texto=_texto(args, "texto"))
    if chamada.name == "fora_do_catalogo":
        return Recusa(
            motivo=_texto(args, "motivo"),
            o_que_faltaria=_texto(args, "o_que_faltaria"),
        )
    if chamada.name == "propor_workflow":
        etapas_cruas = args.get("etapas")
        if not isinstance(etapas_cruas, list) or not etapas_cruas:
            raise ValueError("argumento 'etapas' ausente ou vazio")
        etapas = []
        for e in etapas_cruas:
            if not isinstance(e, dict):
                raise ValueError(f"etapa malformada: {e!r}")
            blocos = e.get("blocos")
            if not isinstance(blocos, list) or not blocos:
                raise ValueError(f"etapa {e.get('nome')!r} sem bloco")
            # `Etapa.__post_init__` recusa etapa sem nome e sem bloco, com o
            # texto de lá. Construir aqui faz a recusa chegar ao modelo agora,
            # em vez de esperar a composição inteira.
            etapas.append(
                Etapa(nome=_texto(e, "nome"), blocos=tuple(_bloco_de(b) for b in blocos))
            )
        entrega = args.get("entrega")
        if entrega is None:
            entrega = []
        if not isinstance(entrega, list) or not all(isinstance(x, str) for x in entrega):
            raise ValueError("'entrega' precisa ser uma lista de kinds")
        rondas = args.get("max_rondas", 1)
        if isinstance(rondas, bool) or not isinstance(rondas, int):
            raise ValueError(f"'max_rondas' precisa ser inteiro, veio {rondas!r}")
        return PropostaBruta(
            nome=_texto(args, "nome"),
            justificativa=_texto(args, "justificativa"),
            etapas=tuple(etapas),
            entrega=tuple(entrega),
            max_rondas=rondas,
        )
    raise ValueError(f"ferramenta desconhecida: {chamada.name!r}. use uma de {list(NOMES)}")
