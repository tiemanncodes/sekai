# Sekai

Plataforma de chat com IA construída do zero em Python/Flask — sem framework de
autenticação pronto, sem SDK de chat pronto, sem ORM. O objetivo era entender
cada camada, então cada parte foi escrita e testada à mão.

**Demonstração pública:** qualquer visitante conversa com um agente sem criar
conta. Ao esbarrar no limite de mensagens, é convidado a se cadastrar.

## O que já funciona

- **Chat com IA** com anexo de **PDF** (texto extraído e enviado como contexto)
  e de **imagem** (roteado para modelos com visão computacional)
- **Autenticação própria**: hash de senha com `scrypt`, sessão assinada,
  proteção contra fixação de sessão e enumeração de contas
- **Limite de uso por IP/dia** persistido no banco — não reseta ao limpar
  cookie ou abrir aba anônima
- **Cadeia de fallback entre modelos**: se um modelo está indisponível ou com
  limite de taxa, o próximo assume sem o usuário perceber
- **Guardrail de custo**: nenhuma chamada sai sem que o modelo termine em
  `:free` — é impossível gerar custo por engano de configuração

## Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Backend | Python 3 + Flask | Sem mágica: cada rota é explícita |
| Banco | PostgreSQL (Supabase) via `psycopg` | SQL direto, sem ORM, para exercitar o SQL |
| Modelos | OpenRouter (SDK `openai`) | Um único endpoint para vários provedores |
| Frontend | HTML + CSS + JS puro | Sem build step, sem dependência de framework |

## Decisões de engenharia

Estas são as escolhas que valem uma conversa — cada uma resolveu um problema
real encontrado durante o desenvolvimento:

**Senha nunca em texto puro.** `generate_password_hash` usa scrypt (custoso em
CPU *e* em memória, o que atrapalha ataque com GPU). O login errado devolve
sempre a mesma mensagem genérica — dizer "esse e-mail não existe" permitiria
descobrir quais contas existem.

**O limite de mensagens vive no banco, não na sessão.** A primeira versão
contava na sessão do navegador: bastava limpar o cookie para ganhar mensagens
grátis de novo. Hoje a contagem é por IP e por dia, em `chat_publico_mensagens`.

**Histórico da conversa fora do cookie.** Cinco trocas de mensagem estouram o
limite de 4KB do cookie — e como o contador morava no mesmo cookie, o navegador
o descartava silenciosamente e o limite parava de funcionar. O histórico foi
para o Postgres; o cookie guarda apenas um token opaco.

**Cadeia de fallback entre modelos gratuitos.** O catálogo gratuito da
OpenRouter muda sem aviso: entre julho e setembro de 2026, dois dos quatro
modelos da cadeia saíram do ar — e o chat continuou funcionando, sem
intervenção, porque o próximo da fila assumiu.

**Raciocínio desligado explicitamente.** Modelos de raciocínio devolviam o
próprio "pensamento em inglês" como resposta ao usuário. O parâmetro
`reasoning: {enabled: false}` da OpenRouter resolve isso de forma unificada,
enquanto o truque específico de cada modelo não funcionava para todos.

**Markdown convertido no servidor e no cliente.** Mesmo instruído a não usar
markdown, o modelo insiste em `**negrito**`. A conversão escapa todo o HTML
primeiro e só então aplica a formatação — resposta de modelo é entrada não
confiável, e HTML vindo dali nunca é executado.

## Rodando localmente

**1. Banco.** Crie um projeto no [Supabase](https://supabase.com) (plano free)
e rode o conteúdo de `schema.sql` em *SQL Editor → New query → Run*.

**2. Chave de IA.** Crie uma chave em [openrouter.ai](https://openrouter.ai)
(gratuita, sem cartão — o guardrail impede o uso de modelos pagos).

**3. Configuração.** Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

**4. Instale e rode:**

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```

Acesse http://127.0.0.1:5000

## Organização

| Arquivo | Responsabilidade |
|---|---|
| `app.py` | Rotas e configuração do Flask |
| `auth.py` | Hash de senha, sessão, decorator de rota protegida |
| `chat.py` | Chat público: limites, histórico, anexos |
| `llm.py` | Cliente da OpenRouter: guardrail `:free` e cadeia de fallback |
| `db.py` | Conexão com o Postgres (uma por request) |
| `schema.sql` | Tabelas |

## Próximos passos

- Tabela `agents` — um agente personalizado por usuário
- Fluxo de solicitação de chatbots sob medida, com pagamento via Pix
- Testes automatizados e deploy no Render
