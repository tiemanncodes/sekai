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
| Embeddings | `fastembed` (ONNX, local) | Custo zero, sem chave e sem limite de taxa |
| Banco vetorial | ChromaDB | Busca por similaridade sem subir mais infraestrutura |
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

**RAG com embeddings locais, e o modelo escolhido por medição.** A primeira
versão despejava o PDF inteiro no prompt, truncado em 8.000 caracteres — não
escala e enche o contexto de texto irrelevante. Hoje o documento é fatiado em
trechos com sobreposição, indexado, e só os quatro trechos mais próximos da
pergunta entram no prompt (economia medida de ~56% de contexto num teste).

A escolha do modelo de embedding foi feita medindo, não por intuição, e as duas
tentativas erradas ensinaram mais que a certa:

| Modelo | Resultado |
|---|---|
| `bge-small-en` (inglês) | Separação de 0,096 entre frases não relacionadas em português — inútil |
| `paraphrase-multilingual-MiniLM` | Resolveu a língua, mas acertou só 1 de 3 perguntas: modelos *paraphrase* comparam frases parecidas **entre si**, e RAG é assimétrico (pergunta curta contra trecho longo) |
| `multilingual-e5-large` | Treinado para recuperação e com os prefixos `query:`/`passage:` obrigatórios: **4 de 4** |

Os embeddings rodam **localmente**: os da OpenRouter são pagos, e o projeto
inteiro parte da premissa de custo zero — a mesma razão do guardrail de modelos.

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

## Limitações conhecidas

- O índice vetorial é **em memória**: reiniciar o servidor apaga os documentos
  já indexados. Aceitável para uma demonstração de 5 mensagens por sessão;
  para produção, o caminho é `pgvector` no Postgres que o projeto já usa.
- O modelo de embedding tem 2,2GB e leva ~15s para carregar na primeira vez.
  O carregamento é preguiçoso — quem nunca anexa um documento nunca paga esse
  custo.

## Próximos passos

- Tabela `agents` — um agente personalizado por usuário
- Fluxo de solicitação de chatbots sob medida, com pagamento via Pix
- Testes automatizados e deploy no Render
