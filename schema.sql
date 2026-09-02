-- Rode isto no Supabase: SQL Editor > New query > Run
-- citext deixa o email case-insensitive (Joao@x.com == joao@x.com)
create extension if not exists citext;

create table if not exists users (
    id         bigserial primary key,
    email      citext      not null unique,
    senha_hash text        not null,
    criado_em  timestamptz not null default now()
);

-- Uma linha por mensagem enviada no chat público (sem login). Contar as
-- linhas de um IP no dia é o limite anti-abuso — sobrevive a reinício do
-- servidor, diferente de um contador em memória.
create table if not exists chat_publico_mensagens (
    id        bigserial primary key,
    ip        text        not null,
    criado_em timestamptz not null default now()
);

create index if not exists idx_chat_publico_ip_data
    on chat_publico_mensagens (ip, criado_em);

-- Histórico da conversa por visitante (só pra continuidade visual — o
-- limite de mensagens é contado em chat_publico_mensagens, por IP, não
-- aqui). O cookie de sessão guarda só o token, poucos bytes; um histórico
-- de 5 trocas de mensagem passaria fácil dos 4KB que o cookie aceita.
create table if not exists chat_sessoes (
    token     text        primary key,
    historico jsonb       not null default '[]',
    criado_em timestamptz not null default now()
);
