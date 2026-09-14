"""O investigador: uma divergência entra, uma proposta sai.

Nunca levanta por causa do modelo. Toda falha — JSON quebrado, tipo inventado,
ferramenta inexistente, orçamento estourado, turnos esgotados — vira abstenção
registrada. Um investigador que estoura no meio de um fechamento derruba o
processo inteiro por causa de um item.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from orchestrator.agent.llm import LLMClient
from orchestrator.agent.proposal import (
    Confidence,
    Cost,
    InvestigationOutput,
    Proposal,
    TraceEvent,
)
from orchestrator.agent.tools import TOOL_SCHEMAS, ToolContext
from orchestrator.models import Divergence
from orchestrator.taxonomy import DivergenceType

SYSTEM = """Você investiga divergências de conciliação bancária brasileira.

Recebe UMA divergência: lançamentos que as regras determinísticas não
conseguiram casar. Seu trabalho é explicar por quê, usando as ferramentas para
buscar contexto.

Regras:
- Use `calcular_retencao` para qualquer cálculo de imposto. Nunca calcule de cabeça.
- Cite evidência concreta: ids e valores que você de fato consultou.
- Não saber é resposta válida e esperada. Se não houver evidência que sustente
  uma hipótese, responda com tipo NAO_IDENTIFICADO e confiança BAIXA. Uma
  proposta errada com confiança alta custa mais caro que dez abstenções.

Quando tiver concluído, responda APENAS com um objeto JSON:
{"tipo": <um dos tipos>, "explicacao": <texto curto>, "evidencia": [<strings>],
 "confianca": "ALTA"|"MEDIA"|"BAIXA", "acao_sugerida": <texto>}

Tipos válidos: """ + ", ".join(t.value for t in DivergenceType)


@dataclass
class Investigator:
    client: LLMClient
    context: ToolContext
    max_turns: int = 6
    max_tentativas_formato: int = 2
    budget_microcents: int = 100_000  # ~US$ 0,001 por divergência
    name: str = field(default="investigador", init=False)

    def investigate(self, divergences: list[Divergence]) -> InvestigationOutput:
        propostas, total = [], Cost.zero()
        for d in divergences:
            p = self._uma(d)
            propostas.append(p)
            total = total + p.cost
        return InvestigationOutput(proposals=propostas, cost=total)

    def _uma(self, divergencia: Divergence) -> Proposal:
        entrada = self._descrever(divergencia)
        mensagens: list[dict[str, Any]] = [{"role": "user", "content": entrada}]
        custo, tentativas_formato = Cost.zero(), 0
        trace: list[TraceEvent] = [
            TraceEvent(kind="entrada", detail={"divergencia": divergencia.id})
        ]

        for turno in range(1, self.max_turns + 1):
            try:
                resposta = self.client.complete(
                    system=SYSTEM, messages=mensagens, tools=TOOL_SCHEMAS
                )

                custo = custo + resposta.cost
                trace.append(
                    TraceEvent(
                        kind="llm",
                        detail={
                            "turno": turno,
                            "tokens_entrada": resposta.cost.input_tokens,
                            "tokens_saida": resposta.cost.output_tokens,
                            "ferramentas_pedidas": [c.name for c in resposta.tool_calls],
                        },
                    )
                )

                if custo.microcents(self.client.model) > self.budget_microcents:
                    trace.append(TraceEvent(kind="outcome", detail={"motivo": "orçamento"}))
                    return Proposal.abstencao(
                        divergencia.id, "orçamento da divergência esgotado", custo, trace
                    )

                if resposta.tool_calls:
                    resultados = self._executar(resposta.tool_calls)
                    for c in resposta.tool_calls:
                        trace.append(
                            TraceEvent(
                                kind="tool", detail={"nome": c.name, "argumentos": c.arguments}
                            )
                        )
                    mensagens.append({"role": "assistant", "content": resposta.text or ""})
                    mensagens.append({"role": "user", "content": resultados})
                    continue

                proposta = self._interpretar(divergencia.id, resposta.text, custo, trace)
                if proposta is not None:
                    return proposta

                tentativas_formato += 1
                if tentativas_formato > self.max_tentativas_formato:
                    break
                mensagens.append({"role": "assistant", "content": resposta.text})
                mensagens.append(
                    {
                        "role": "user",
                        "content": "Resposta inválida. Responda APENAS o objeto JSON pedido.",
                    }
                )
            except AssertionError:
                # Sinal do FakeLLMClient de que o laço pediu mais turnos do
                # que o teste preparou — bug de teste ou laço descontrolado,
                # não falha "do modelo". Abafar isso esconderia o defeito que
                # o assert existe para denunciar (ver docstring de
                # FakeLLMClient), então deixa propagar.
                raise
            except Exception as erro:  # noqa: BLE001
                # Timeout, rede caída, 500 da API, modelo sem preço conhecido
                # na tabela de custo, ou qualquer outra falha ao processar a
                # resposta — nada disso pode escapar. O SDK já tenta de novo
                # por conta própria; se chegou aqui, acabou. Abster é a saída
                # certa: derrubar o processo inteiro (ou só esta divergência)
                # por causa de um item transformaria uma falha isolada em
                # conciliação não entregue.
                trace.append(
                    TraceEvent(kind="erro", detail={"turno": turno, "erro": str(erro)})
                )
                return Proposal.abstencao(
                    divergencia.id, f"falha ao investigar: {erro}", custo, trace
                )

        trace.append(TraceEvent(kind="outcome", detail={"motivo": "sem conclusão"}))
        return Proposal.abstencao(
            divergencia.id,
            "investigação encerrada sem conclusão utilizável",
            custo,
            trace,
        )

    def _descrever(self, d: Divergence) -> str:
        banco = [e for e in self.context.bank if e.id in d.bank_ids]
        contabil = [le for le in self.context.ledger if le.id in d.ledger_ids]
        return json.dumps(
            {
                "divergencia_id": d.id,
                "lancamentos_bancarios": [
                    {
                        "id": e.id,
                        "data": e.date.isoformat(),
                        "valor": e.amount,
                        "descricao": e.description,
                        "contraparte": e.counterparty,
                        "documento": e.document,
                    }
                    for e in banco
                ],
                "lancamentos_contabeis": [
                    ToolContext._ledger_dict(le) for le in contabil
                ],
            },
            ensure_ascii=False,
        )

    def _executar(self, chamadas: list[Any]) -> str:
        """Executa as ferramentas pedidas.

        Erro de ferramenta volta para o modelo como texto, nunca como exceção —
        o modelo consegue se corrigir, o processo não consegue se recuperar de
        um estouro.
        """
        resultados = []
        for c in chamadas:
            metodo = getattr(self.context, c.name, None)
            if metodo is None or c.name not in {s["name"] for s in TOOL_SCHEMAS}:
                resultados.append({"ferramenta": c.name, "erro": "ferramenta inexistente"})
                continue
            try:
                argumentos = {k: v for k, v in c.arguments.items() if v is not None}
                resultados.append({"ferramenta": c.name, "resultado": metodo(**argumentos)})
            except (ValueError, TypeError) as erro:
                resultados.append({"ferramenta": c.name, "erro": str(erro)})
        return json.dumps(resultados, ensure_ascii=False, default=str)

    def _interpretar(
        self, divergence_id: str, texto: str, custo: Cost, trace: list[TraceEvent]
    ) -> Proposal | None:
        """Devolve None quando o texto não é uma proposta utilizável."""
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            return None
        if not isinstance(dados, dict):
            return None
        try:
            tipo = DivergenceType(dados.get("tipo", ""))
            confianca = Confidence(dados.get("confianca", ""))
            evidencia = [str(e) for e in dados.get("evidencia", [])]
        except (ValueError, TypeError):
            # ValueError: tipo/confiança fora da taxonomia. TypeError: campo
            # "evidencia" veio como algo não iterável (um int, por exemplo) —
            # mesma categoria de "resposta não utilizável": o modelo ainda tem
            # chance de tentar de novo antes de virar abstenção.
            return None
        # Afirmar com confiança sem citar nada acontece. Rebaixar é mais útil
        # que descartar: a hipótese ainda ajuda o humano, com o peso certo.
        if confianca is Confidence.ALTA and not evidencia:
            confianca = Confidence.BAIXA

        return Proposal(
            divergence_id=divergence_id,
            tipo=tipo,
            explicacao=str(dados.get("explicacao", "")),
            evidencia=evidencia,
            confianca=confianca,
            acao_sugerida=str(dados.get("acao_sugerida", "investigar_manual")),
            cost=custo,
            trace=[*trace, TraceEvent(kind="outcome", detail={"tipo": tipo.value})],
        )
