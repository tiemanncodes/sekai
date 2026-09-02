"""Conexão com o Postgres do Supabase.

Uma conexão por request, guardada no `g` do Flask e fechada no fim.
É o modelo mais simples e suficiente pro plano free.
"""
import os

import psycopg
from flask import g
from psycopg.rows import dict_row


def get_db():
    if "db" not in g:
        g.db = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_one(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql, params=()):
    """INSERT/UPDATE. Retorna a linha se o SQL tiver RETURNING."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() if cur.description else None
    db.commit()
    return row
