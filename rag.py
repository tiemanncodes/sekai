"""RAG — busca semântica nos documentos que o usuário anexa.

Antes deste módulo, um PDF anexado era despejado inteiro no prompt (truncado
em 8000 caracteres). Isso não escala: documento grande estoura o contexto, e
o modelo recebe muito texto irrelevante para responder uma pergunta curta.

Aqui o documento é fatiado em trechos, cada trecho vira um vetor (embedding),
e a cada pergunta só os trechos mais parecidos com ela entram no prompt.

Duas decisões que valem explicação:

1. Embeddings rodam LOCALMENTE (fastembed/ONNX), não por API. Os embeddings
   da OpenRouter são pagos, e o projeto inteiro é construído sobre a premissa
   de custo zero — o mesmo motivo do guardrail em llm.py. Como bônus, não há
   limite de taxa nem chave para vazar.

2. O modelo é MULTILÍNGUE e treinado para RECUPERAÇÃO, e as duas coisas
   foram medidas, não supostas:

   - Em português, um modelo de inglês (bge-small-en) separava "o gato dorme
     no sofá" de "a bolsa de valores caiu" por só 0,096 — perto de inútil.
   - Trocar por um multilíngue resolveu a língua, mas não a tarefa: modelos
     "paraphrase-*" comparam frases parecidas entre si, e RAG é assimétrico
     (pergunta curta contra trecho longo). Num teste de 3 perguntas sobre um
     documento, ele acertou 1.
   - O multilingual-e5-large é treinado para recuperação e exige os prefixos
     "query:" e "passage:" — sem eles a qualidade cai. Com eles: 3 de 3.

   O preço é o tamanho (2,2GB, baixado uma vez e reutilizado do cache).
"""
import re
import threading

import chromadb
from chromadb.config import Settings

MODELO_EMBEDDING = "intfloat/multilingual-e5-large"
TAMANHO_TRECHO = 800       # caracteres por trecho
SOBREPOSICAO = 150         # caracteres repetidos entre trechos vizinhos
TRECHOS_RECUPERADOS = 4    # quantos trechos entram no prompt por pergunta

_modelo = None
_trava = threading.Lock()
_cliente = chromadb.Client(Settings(anonymized_telemetry=False))
_colecao = _cliente.get_or_create_collection("documentos")


def _carregar_modelo():
    """Carrega o modelo de embedding uma única vez (leva ~15s na primeira
    chamada). Fica preguiçoso de propósito: a maioria dos visitantes nunca
    anexa documento, e não faz sentido atrasar a subida do servidor por isso."""
    global _modelo
    if _modelo is None:
        with _trava:
            if _modelo is None:
                from fastembed import TextEmbedding

                _modelo = TextEmbedding(MODELO_EMBEDDING)
    return _modelo


def fatiar(texto, tamanho=TAMANHO_TRECHO, sobreposicao=SOBREPOSICAO):
    """Divide o texto em trechos com sobreposição.

    A sobreposição existe para não cortar uma ideia ao meio: se a resposta
    está exatamente na fronteira entre dois trechos, ela ainda aparece
    inteira em pelo menos um deles. O corte tenta cair no fim de uma frase.
    """
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if not texto:
        return []

    trechos = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            # recua até o fim de frase mais próximo, para não cortar no meio
            corte = max(texto.rfind(". ", inicio, fim), texto.rfind("\n", inicio, fim))
            if corte > inicio + tamanho // 2:
                fim = corte + 1
        trechos.append(texto[inicio:fim].strip())
        if fim >= len(texto):
            break
        inicio = fim - sobreposicao
    return [t for t in trechos if t]


def indexar(documento_id, texto):
    """Fatia, gera embeddings e guarda os trechos. Retorna quantos trechos."""
    trechos = fatiar(texto)
    if not trechos:
        return 0

    # "passage:" é exigido pelo e5 para o lado do documento (ver docstring)
    vetores = [v.tolist() for v in _carregar_modelo().embed([f"passage: {t}" for t in trechos])]
    _colecao.add(
        ids=[f"{documento_id}::{i}" for i in range(len(trechos))],
        embeddings=vetores,
        documents=trechos,
        metadatas=[{"documento_id": documento_id} for _ in trechos],
    )
    return len(trechos)


def buscar(documento_id, pergunta, k=TRECHOS_RECUPERADOS):
    """Retorna os k trechos do documento mais parecidos com a pergunta."""
    if not (pergunta or "").strip():
        return []

    # "query:" é o par do "passage:" usado na indexação
    vetor = next(iter(_carregar_modelo().embed([f"query: {pergunta}"]))).tolist()
    resultado = _colecao.query(
        query_embeddings=[vetor],
        n_results=k,
        where={"documento_id": documento_id},
    )
    return (resultado.get("documents") or [[]])[0]


def esquecer(documento_id):
    """Remove os trechos de um documento (usado ao encerrar a conversa)."""
    _colecao.delete(where={"documento_id": documento_id})
