Aqui está o documento Setup do Ambiente e Infraestrutura totalmente reformulado em Markdown. Ele foi adaptado para espelhar as variáveis de ambiente exatas do seu `.env.example` e a arquitetura real do projeto (Backend FastAPI + Dashboard Next.js + PostgreSQL).

---

## 3. Setup do Ambiente e Infraestrutura

Este documento detalha o provisionamento, mapeamento de rede e injeção de variáveis para o deploy do ecossistema GastoZap dentro do Easypanel.

---

## 3.1 Arquitetura de Containers (Easypanel)

O projeto será dividido em 3 serviços independentes dentro do mesmo projeto no Easypanel, utilizando a rede interna do painel para comunicação segura:

```unset
                  [ Evolution API ] 
                          |
                    (HTTPS / Webhook)
                          v
[ Dashboard ] ----> [ Backend ] <----> [ Redis ] (Opcional)
 (Next.js)           (FastAPI)
                          |
                   (Rede Interna)
                          v
                   [ PostgreSQL ]
```

1. Serviço 1 (App): `gastozap-backend` (Aponta para o subdiretório `/backend` do Git).
2. Serviço 2 (App): `gastozap-dashboard` (Aponta para o subdiretório `/dashboard` do Git).
3. Serviço 3 (Database): `gastozap-postgres` (Instância nativa PostgreSQL do Easypanel).
4. Serviço 4 (Cache/Fila - Opcional): `gastozap-redis` (Instância nativa Redis do Easypanel).

---

## 3.2 Passo a Passo para o Deploy no Easypanel

## Passo 1: Provisionar o Banco de Dados e Redis

1. No painel do Easypanel, crie um novo projeto chamado GastoZap.
2. Clique em Add Service > PostgreSQL. Nomeie o serviço como `postgres`.
3. _(Opcional)_ Clique em Add Service > Redis. Nomeie o serviço como `redis`.
4. Copie a string de conexão interna gerada pelo PostgreSQL. Ela será usada na variável `DATABASE_URL` substituindo o driver padrão por `postgresql+asyncpg://`.

## Passo 2: Configurar o Serviço do Backend (FastAPI)

1. Clique em Add Service > App. Nomeie como `backend`.
2. Na aba Source, insira a URL do seu repositório Git.
3. No campo Root Directory (Diretório Raiz), preencha obrigatoriamente com `/backend` para que o Easypanel execute o `Dockerfile` correto.
4. Acesse a aba Environment Variables e cole as variáveis descritas na seção 3.3.

## Passo 3: Configurar o Serviço do Dashboard (Next.js)

1. Clique em Add Service > App. Nomeie como `dashboard`.
2. Na aba Source, insira a URL do seu repositório Git.
3. No campo Root Directory, preencha com `/dashboard`.
4. Em Environment Variables, configure a URL pública do seu backend para a comunicação da interface.

---

## 3.3 Configuração de Variáveis de Ambiente (.env)

Copie a estrutura abaixo e insira na aba Environment Variables do serviço Backend no Easypanel, ajustando os valores reais:

```env
# ==========================================
# Configurações do App
# ==========================================
APP_NAME=GastoZap
DEBUG=false
API_SECRET_KEY=sua_chave_secreta_aleatoria_aqui
CORS_ORIGINS=http://localhost:3000
PORT=8000

# ==========================================
# Banco de Dados e Cache
# ==========================================
# Nota: O Easypanel gera postgres://, mas o FastAPI exige postgresql+asyncpg:// para o SQLAlchemy assíncrono
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/gastozap

REDIS_URL=redis://redis:6379/0
USE_REDIS_QUEUE=false

# ==========================================
# Integração Evolution API
# ==========================================
EVOLUTION_API_URL=http://evolution-api:8080
EVOLUTION_API_KEY=sua-chave-global-da-evolution
EVOLUTION_INSTANCE=gastozap
WEBHOOK_SECRET=seu-token-de-assinatura-do-webhook

# ==========================================
# Provedor de Inteligência Artificial (OpenAI)
# ==========================================
OPENAI_API_KEY=sk-proj-suachavedaopenai_xxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4o
WHISPER_MODEL=whisper-1

# ==========================================
# Segurança e Controle de Acesso
# ==========================================
ALLOWED_PHONE_NUMBERS=5511999999999
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=sua_senha_segura_do_painel

# ==========================================
# Regras de Negócio e Automações
# ==========================================
ALWAYS_CONFIRM_MODE=true
HIGH_VALUE_THRESHOLD=500.0
ALERT_TIME=20:00
RETRY_LIMIT=3
CARD_EXPIRY_ALERT_MONTHS=3
```

---

## 3.4 Configuração do Webhook da Evolution API

1. Acesse o gerenciador da sua Evolution API.
2. Na instância configurada (`gastozap`), ative a aba Webhooks.
3. No campo URL, cole o endereço gerado pelo Easypanel para o seu backend adicionando o endpoint (ex: `https://easypanel.host`).
4. No campo Secret, insira o mesmo valor definido em `WEBHOOK_SECRET`.
5. Ative o evento de recebimento de mensagens (`MESSAGES_UPSERT`).

---

O documento do Setup do Ambiente está atualizado e amarrado com o seu código. Quer que eu te dê as instruções de como subir o projeto para o GitHub pelo terminal do Cursor para o Easypanel conseguir ler as pastas?