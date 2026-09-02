import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()  # precisa rodar antes de importar chat/llm, que lêem env na importação

from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from auth import (
    autenticar,
    carregar_usuario,
    criar_usuario,
    login_obrigatorio,
    login_sessao,
    validar_credenciais,
)
from chat import enviar_mensagem, formatar_bolha, historico, restantes_disponiveis, texto_plano
from db import close_db

app = Flask(__name__)
app.add_template_filter(formatar_bolha, "bolha")
app.add_template_filter(texto_plano, "plano")
app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"],
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_COOKIE_HTTPONLY=True,  # JS da página não lê o cookie
    SESSION_COOKIE_SAMESITE="Lax",  # não vai junto em requests de outros sites
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",  # só HTTPS no Render
    MAX_CONTENT_LENGTH=7 * 1024 * 1024,  # 7MB — cobre o limite de 6MB do chat.py + folga
)

app.teardown_appcontext(close_db)
app.before_request(carregar_usuario)


@app.route("/")
def index():
    if g.usuario:
        return redirect(url_for("painel"))
    return render_template(
        "chat.html",
        mensagens=historico(),
        restantes=restantes_disponiveis(request),
    )


@app.post("/api/chat")
def api_chat():
    if g.usuario:
        return jsonify({"erro": "Use o painel para falar com seu agente."}), 400
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        mensagem = request.form.get("mensagem", "")
        arquivo = request.files.get("arquivo")
    else:
        dados = request.get_json(silent=True) or {}
        mensagem = dados.get("mensagem", "")
        arquivo = None
    return jsonify(enviar_mensagem(request, mensagem, arquivo))


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if g.usuario:
        return redirect(url_for("painel"))

    erro = None
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        senha = request.form.get("senha", "")

        erro = validar_credenciais(email, senha)
        if erro is None:
            usuario, erro = criar_usuario(email, senha)
            if erro is None:
                login_sessao(usuario)
                return redirect(url_for("painel"))

    return render_template("cadastro.html", erro=erro, email=email)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario:
        return redirect(url_for("painel"))

    erro = None
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        usuario, erro = autenticar(email, request.form.get("senha", ""))
        if erro is None:
            login_sessao(usuario)
            return redirect(url_for("painel"))

    return render_template("login.html", erro=erro, email=email)


@app.post("/sair")
def sair():
    from flask import session

    session.clear()
    return redirect(url_for("login"))


@app.route("/painel")
@login_obrigatorio
def painel():
    return render_template("painel.html")


if __name__ == "__main__":
    app.run(debug=True)
