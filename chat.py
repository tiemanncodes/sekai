"""Chat público (sem login).

O limite de mensagens é contado a partir do banco (chat_publico_mensagens,
por IP e por dia) — não da sessão do navegador. Um cookie limpo, uma aba
anônima ou um F5 não devolvem mensagens grátis; só muda depois da meia-noite.

O histórico da conversa (pra continuidade visual, não pro limite) mora em
chat_sessoes, indexado por um token opaco guardado no cookie de sessão —
ele não guarda o arquivo em si (só tipo + nome, em "anexo"), pra não inchar
o banco com base64 de imagem ou texto de PDF a cada mensagem. Por isso,
depois de recarregar a página, uma foto anexada aparece como um chip com
nome (não a foto de novo) — só na mensagem ao vivo, antes do reload, é que
a pré-visualização real da imagem aparece.
"""
import io
import re
import secrets

from flask import g, session
from markupsafe import Markup, escape
from psycopg.types.json import Jsonb
from pypdf import PdfReader

from db import execute, query_one
from llm import (
    CADEIA_FALLBACK_VISAO,
    RespostaVaziaError,
    TodosModelosFalharamError,
    completar_com_fallback,
)

LIMITE_MENSAGENS_DIA = 5  # por IP, por dia — é o convite pro cadastro
TAMANHO_MAXIMO_ARQUIVO = 6 * 1024 * 1024  # 6MB
TIPOS_IMAGEM = {"image/png", "image/jpeg", "image/webp"}
TIPO_PDF = "application/pdf"
LIMITE_CARACTERES_PDF = 8000

SYSTEM_PROMPT = (
    "Você é o assistente de demonstração do Sekai, uma plataforma onde cada "
    "pessoa pode ter seu próprio agente de IA personalizado. Seja útil, "
    "direto e simpático. Se perguntarem como contratar um agente "
    "personalizado, diga que é só clicar em 'Criar conta'. "
    "Nunca use markdown (sem **negrito**, #títulos, listas com - ou *): a "
    "resposta é exibida como texto puro, então markdown apareceria com os "
    "símbolos literais na tela."
)


_REGEX_NEGRITO = re.compile(r"\*\*(.+?)\*\*")


def formatar_bolha(texto):
    """Escapa o texto (nunca confie em HTML vindo do modelo) e converte
    **negrito** markdown em <strong> de verdade — o system prompt pede pro
    modelo não usar markdown, mas modelos gratuitos nem sempre obedecem."""
    escapado = str(escape(texto))
    return Markup(_REGEX_NEGRITO.sub(r"<strong>\1</strong>", escapado))


def texto_plano(texto):
    """Versão sem marcação — usada no botão de copiar, pra não colar os
    asteriscos literais do markdown que o modelo às vezes insiste em usar."""
    return _REGEX_NEGRITO.sub(r"\1", texto or "")


def ip_da_requisicao(request):
    encaminhado = request.headers.get("X-Forwarded-For", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.remote_addr or "desconhecido"


def mensagens_do_ip_hoje(ip):
    row = query_one(
        """
        select count(*) as total
        from chat_publico_mensagens
        where ip = %s and criado_em >= date_trunc('day', now())
        """,
        (ip,),
    )
    return row["total"]


def restantes_disponiveis(request):
    ip = ip_da_requisicao(request)
    return max(0, LIMITE_MENSAGENS_DIA - mensagens_do_ip_hoje(ip))


def registrar_mensagem_do_ip(ip):
    execute("insert into chat_publico_mensagens (ip) values (%s)", (ip,))


def _estado():
    """Carrega (uma vez por request, via g) o histórico do visitante atual,
    criando o token de sessão na primeira visita. Só guarda o histórico —
    o limite de mensagens vem do banco por IP, não daqui."""
    if not hasattr(g, "_chat_estado"):
        token = session.setdefault("chat_token", secrets.token_urlsafe(24))
        row = query_one("select historico from chat_sessoes where token = %s", (token,))
        g._chat_estado = {"token": token, "historico": row["historico"] if row else []}
    return g._chat_estado


def historico():
    return _estado()["historico"]


def _salvar_historico(historico_novo):
    estado = _estado()
    estado["historico"] = historico_novo
    execute(
        """
        insert into chat_sessoes (token, historico)
        values (%s, %s)
        on conflict (token) do update set historico = excluded.historico
        """,
        (estado["token"], Jsonb(historico_novo)),
    )


def _ler_arquivo(arquivo):
    """Valida e processa o arquivo anexado. Retorna (tipo, dado, erro).

    tipo é 'imagem' | 'pdf'; dado é a data-URL base64 (imagem) ou o texto
    extraído (pdf). Em caso de erro, tipo e dado vêm None.
    """
    if arquivo is None or not arquivo.filename:
        return None, None, None

    bytes_arquivo = arquivo.read()
    if len(bytes_arquivo) > TAMANHO_MAXIMO_ARQUIVO:
        return None, None, "Arquivo muito grande (máximo 6MB)."

    tipo_mime = arquivo.mimetype

    if tipo_mime in TIPOS_IMAGEM:
        import base64

        b64 = base64.b64encode(bytes_arquivo).decode("ascii")
        return "imagem", f"data:{tipo_mime};base64,{b64}", None

    if tipo_mime == TIPO_PDF:
        try:
            leitor = PdfReader(io.BytesIO(bytes_arquivo))
            texto = "\n".join(pagina.extract_text() or "" for pagina in leitor.pages).strip()
        except Exception:
            return None, None, "Não consegui ler esse PDF. Ele pode estar corrompido ou protegido."
        if not texto:
            return None, None, "Esse PDF não tem texto legível (pode ser um scan sem OCR)."
        if len(texto) > LIMITE_CARACTERES_PDF:
            texto = texto[:LIMITE_CARACTERES_PDF] + "\n[...texto truncado...]"
        return "pdf", texto, None

    return None, None, "Tipo de arquivo não aceito. Envie imagem (PNG/JPEG/WEBP) ou PDF."


def enviar_mensagem(request, texto_usuario, arquivo=None):
    """Processa uma mensagem do chat público. Retorna um dict pronto pra JSON."""
    texto_usuario = (texto_usuario or "").strip()

    ip = ip_da_requisicao(request)
    ja_enviadas = mensagens_do_ip_hoje(ip)
    if ja_enviadas >= LIMITE_MENSAGENS_DIA:
        return {"limite_sessao_atingido": True}

    tipo_arquivo, dado_arquivo, erro_arquivo = _ler_arquivo(arquivo)
    if erro_arquivo:
        return {"erro": erro_arquivo}

    if not texto_usuario and not tipo_arquivo:
        return {"erro": "Digite uma mensagem."}

    msgs = list(historico())

    # O que vai pro modelo nesta chamada (pode incluir imagem/texto de PDF)
    # e o que fica salvo no histórico (nunca o arquivo em si, só um marcador
    # — evita inchar o banco e reenviar o mesmo arquivo em todo turno futuro).
    nome_arquivo = arquivo.filename if arquivo and arquivo.filename else None
    if tipo_arquivo == "imagem":
        conteudo_modelo = [
            {"type": "text", "text": texto_usuario or "Descreva esta imagem."},
            {"type": "image_url", "image_url": {"url": dado_arquivo}},
        ]
        cadeia = CADEIA_FALLBACK_VISAO
    elif tipo_arquivo == "pdf":
        conteudo_modelo = (
            f'Conteúdo do arquivo "{nome_arquivo}":\n\n{dado_arquivo}\n\n---\n\n'
            + (texto_usuario or "Resuma esse documento.")
        )
        cadeia = None
    else:
        conteudo_modelo = texto_usuario
        cadeia = None

    msgs.append({"role": "user", "content": conteudo_modelo})

    kwargs = {"cadeia": cadeia} if cadeia else {}
    try:
        resposta, _modelo = completar_com_fallback(
            [{"role": "system", "content": SYSTEM_PROMPT}] + msgs, **kwargs
        )
    except (TodosModelosFalharamError, RespostaVaziaError):
        return {"erro": "O assistente está sobrecarregado agora. Tente de novo em instantes."}

    # No histórico, o conteúdo do usuário vira texto simples de novo — nunca
    # o array multimodal nem o texto extraído do PDF. O arquivo em si não é
    # guardado, só tipo + nome, pra render mostrar um chip/ícone depois.
    entrada_usuario = {"role": "user", "content": texto_usuario}
    if nome_arquivo:
        entrada_usuario["anexo"] = {"tipo": tipo_arquivo, "nome": nome_arquivo}
    msgs[-1] = entrada_usuario
    msgs.append({"role": "assistant", "content": resposta})
    _salvar_historico(msgs)

    registrar_mensagem_do_ip(ip)

    restantes = LIMITE_MENSAGENS_DIA - (ja_enviadas + 1)
    return {
        "resposta": resposta,
        "restantes": restantes,
        "limite_sessao_atingido": restantes <= 0,
    }
