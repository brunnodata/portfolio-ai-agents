# GastoZap — Assistente Financeiro via WhatsApp

Sistema completo de controle de gastos pessoais via WhatsApp, com agente de IA, persistência em PostgreSQL e dashboard web em tempo real.

## Arquitetura

```
WhatsApp → Evolution API → Backend (FastAPI) → PostgreSQL
                              ↓
                         OpenAI (GPT-4o + Whisper)
                              ↓
                      Dashboard (Next.js + SSE)
```

## Componentes

| Pasta | Descrição |
|-------|-----------|
| `backend/` | API FastAPI: webhooks, agente IA, fila assíncrona, jobs agendados |
| `dashboard/` | Frontend Next.js com KPIs, gráficos e atualização em tempo real |
| `docker-compose.yml` | Orquestração local (PostgreSQL + backend + dashboard) |

## Requisitos atendidos

- **RF-01 a RF-04:** Webhook Evolution API, whitelist, token de segurança, fila para áudio/imagem
- **RF-05 a RF-11:** Agente IA com extração estruturada, multimodal, memória de conversa
- **RF-12/13:** Cadastro de cartão no primeiro lançamento
- **RF-14 a RF-17:** Modo confirmação, persistência e resposta formatada
- **RF-18 a RF-19, RF-42:** Feedback visual (⏳, ✅, ⚠️)
- **RF-20/21:** Consultas e remoção de lançamentos
- **RF-22/23:** Normalização de estabelecimentos
- **RF-24 a RF-26:** Tipos de gasto, setores e projeções
- **RF-27/28:** Dashboard com KPIs, gráficos e SSE
- **RF-30:** Alerta de vencimento de cartão (3 meses)
- **RF-32 a RF-35:** HTTPS (via proxy), auth na API, logs de mensagens
- **RF-36 a RF-43:** Protocolo de dados faltantes e alerta diário às 20h
- **RF-44 a RF-46:** Docker + variáveis de ambiente (Easypanel)

## Configuração

1. Copie o arquivo de ambiente:

```bash
cp .env.example .env
```

2. Preencha as variáveis no `.env` (ou no Easypanel):

- `DATABASE_URL` — conexão PostgreSQL
- `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`
- `WEBHOOK_SECRET` — token do webhook
- `OPENAI_API_KEY` — chave OpenAI
- `ALLOWED_PHONE_NUMBERS` — números autorizados (separados por vírgula)
- `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`

## Execução local

```bash
docker compose up --build
```

- Backend: http://localhost:8000
- Dashboard: http://localhost:3000
- Health: http://localhost:8000/health

## Webhook Evolution API

Configure o webhook da instância para apontar para:

```
POST https://seu-dominio/webhook/evolution
Header: x-webhook-secret: <WEBHOOK_SECRET>
```

Eventos: `messages.upsert`

## Deploy no Easypanel

1. Crie um serviço **PostgreSQL** nativo
2. Crie um serviço **App** com o Dockerfile de `backend/`
3. Configure as variáveis de ambiente na aba Environment Variables
4. Use a connection string interna do PostgreSQL em `DATABASE_URL`
5. Exponha a porta 8000 para o webhook da Evolution API
6. (Opcional) Deploy do dashboard como serviço separado

## Desenvolvimento

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev
```

## Estrutura do banco

Tabelas: `lancamentos`, `setores`, `estabelecimentos`, `cartoes`, `faturas_importadas`, `historico_mensagens`, `conversa_contexto`, `transacoes_pendentes`.

As tabelas são criadas automaticamente na inicialização do backend.

## Fases futuras (já preparadas na arquitetura)

- RF-29: Importação PDF/CSV de faturas
- RF-31: Alertas configuráveis pelo usuário
- Fase 5: Integração Google Drive
