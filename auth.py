"""Autenticação escrita à mão: hash, sessão e o decorator de rota protegida.

A senha nunca é guardada nem comparada em texto puro. O que vai pro banco é o
resultado de generate_password_hash (PBKDF2 + salt aleatório por usuário), e a
conferência é feita por check_password_hash, que compara em tempo constante.
"""
import functools
import re

from flask import g, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import execute, query_one

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validar_credenciais(email, senha):
    """Retorna uma mensagem de erro, ou None se estiver tudo certo."""
    if not EMAIL_RE.match(email or ""):
        return "Digite um e-mail válido."
    if len(senha or "") < 8:
        return "A senha precisa de pelo menos 8 caracteres."
    return None


def criar_usuario(email, senha):
    """Cria o usuário. Retorna (usuario, erro)."""
    if query_one("select id from users where email = %s", (email,)):
        return None, "Esse e-mail já está cadastrado."

    usuario = execute(
        "insert into users (email, senha_hash) values (%s, %s) returning id, email",
        (email, generate_password_hash(senha)),
    )
    return usuario, None


def autenticar(email, senha):
    """Confere as credenciais. Retorna (usuario, erro)."""
    usuario = query_one(
        "select id, email, senha_hash from users where email = %s", (email,)
    )
    # Mensagem genérica de propósito: dizer "e-mail não existe" entregaria a
    # quem está tentando adivinhar quais contas existem.
    if usuario is None or not check_password_hash(usuario["senha_hash"], senha):
        return None, "E-mail ou senha incorretos."
    return usuario, None


def login_sessao(usuario):
    session.clear()  # evita fixação de sessão
    session["user_id"] = usuario["id"]
    session.permanent = True


def carregar_usuario():
    """Roda antes de cada request e deixa o usuário logado em g.usuario."""
    user_id = session.get("user_id")
    g.usuario = (
        query_one("select id, email from users where id = %s", (user_id,))
        if user_id
        else None
    )


def login_obrigatorio(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if g.usuario is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapper
