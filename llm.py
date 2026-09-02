"""Cliente de LLM para o chat público — via OpenRouter, só modelos :free.

Portado do projeto orlog. A ideia central é o guardrail em validar_modelo:
nenhuma chamada sai sem que o modelo termine em ":free". Isso torna
fisicamente impossível gastar dinheiro por engano de configuração — a
validação acontece antes da requisição, não depois.
"""
import os
import time

from openai import APIStatusError, OpenAI, RateLimitError

# Verificados ao vivo em 2026-09-02 (GET /api/v1/models, pricing prompt==0
# e completion==0). Esse catálogo muda com o tempo — a OpenRouter promove e
# aposenta modelos gratuitos sem aviso: entre julho e setembro de 2026, dois
# dos quatro modelos de texto originais saíram do ar. Foi a cadeia de
# fallback abaixo que manteve o chat funcionando sem nenhuma intervenção.
# Se a cadeia inteira começar a falhar, consulte o catálogo ao vivo antes
# de mexer aqui:
#   GET https://openrouter.ai/api/v1/models  (filtrar pricing == 0)
#
# Nem todo modelo gratuito serve: o minimax-m2.7, por exemplo, devolve 400
# ("Reasoning is mandatory") porque exige raciocínio ligado, e este cliente
# desliga o raciocínio de propósito (ver extra_body em _completar).
MODELOS_PERMITIDOS = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "z-ai/glm-5.2:free",
    "google/gemma-4-26b-a4b-it:free",
    "minimax/minimax-m3:free",
)

# Ordem de fallback: do mais capaz pro mais leve/rápido.
CADEIA_FALLBACK = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "z-ai/glm-5.2:free",
)

# Nem todo modelo lê imagem — só os que declaram "image" em
# architecture.input_modalities. Por isso uma cadeia separada entra em ação
# quando a mensagem tem uma imagem anexada.
CADEIA_FALLBACK_VISAO = (
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "minimax/minimax-m3:free",
)

_client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)


class ModeloNaoPermitidoError(Exception):
    """Tentativa de usar um modelo fora da lista :free aprovada."""


class RespostaVaziaError(Exception):
    """O modelo respondeu, mas sem conteúdo utilizável."""


class TodosModelosFalharamError(Exception):
    """A cadeia inteira de fallback esgotou (todos rate-limited ou vazios)."""


def validar_modelo(modelo):
    if not modelo or ":free" not in modelo:
        raise ModeloNaoPermitidoError(f"Modelo pago bloqueado: {modelo!r}")
    if modelo not in MODELOS_PERMITIDOS:
        raise ModeloNaoPermitidoError(f"Modelo não aprovado: {modelo!r}")


def _completar(modelo, mensagens, max_tokens=800, max_tentativas=2):
    validar_modelo(modelo)

    for tentativa in range(max_tentativas + 1):
        try:
            resposta = _client.chat.completions.create(
                model=modelo,
                messages=mensagens,
                max_tokens=max_tokens,
                temperature=0.7,
                # Parâmetro unificado da OpenRouter: desliga o "pensar alto"
                # em qualquer modelo de raciocínio, não só nos que entendem
                # chat_template_kwargs. Sem isso, modelos como o Nemotron
                # devolvem o raciocínio interno (em inglês) como resposta.
                extra_body={"reasoning": {"enabled": False}},
            )
            break
        except RateLimitError:
            if tentativa < max_tentativas:
                time.sleep(2**tentativa)
                continue
            raise

    msg = resposta.choices[0].message
    texto = (msg.content or "").strip()
    if not texto:
        texto = (getattr(msg, "reasoning", None) or "").strip()
    if not texto:
        raise RespostaVaziaError("Modelo retornou resposta vazia.")
    return texto


def completar_com_fallback(mensagens, max_tokens=800, cadeia=CADEIA_FALLBACK):
    """Tenta cada modelo da cadeia até um responder.

    Retorna (resposta, modelo_que_respondeu).
    """
    ultimo_erro = None
    for modelo in cadeia:
        try:
            return _completar(modelo, mensagens, max_tokens), modelo
        # RateLimitError/RespostaVaziaError: modelo temporariamente indisponível.
        # APIStatusError (ex.: 404): a OpenRouter tirou o modelo do catálogo
        # grátis — o catálogo muda com o tempo, então tratamos como "pula
        # pro próximo" em vez de derrubar o chat inteiro.
        except (RateLimitError, RespostaVaziaError, APIStatusError) as e:
            ultimo_erro = e
            continue

    raise TodosModelosFalharamError(f"Todos os modelos falharam: {ultimo_erro}")
