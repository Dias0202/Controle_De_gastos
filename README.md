# Controle Financeiro Pessoal & Open Finance (Cartão Santander / Pluggy)

Plataforma Full-Stack de acompanhamento financeiro ativo e passivo para cartão de crédito e contas bancárias via **Open Finance Brasil (Pluggy API)**, projetada com foco em **orçamentos mensais por categoria (ex.: limite de R$ 500,00 no iFood)**, categorização determinística com regras priorizadas e **relatórios automáticos diários e semanais** por E-mail, Telegram e Discord.

---

## 1. Arquitetura do Sistema

A solução é dividida em camadas desacopladas para garantir precisão contábil, segurança das credenciais bancárias e facilidade de manutenção:

- **Backend (`c:\projetos\Cartao_bruno\backend`)**:
  - **FastAPI + SQLModel (SQLAlchemy) + Pydantic**: API REST estruturada em 6 módulos de domínio.
  - **Motor Financeiro (`app/services/financial_engine.py`)**: Aritmética monetária estritamente em **centavos inteiros (`amount_cents`)**, eliminando imprecisões de ponto flutuante binário (`float`). Normalização de datas para `America/Sao_Paulo`, extração de parcelas (`installment_number` / `total_installments`), reconciliação `PENDING` → `POSTED` e exclusão automática de pagamentos da própria fatura (`BILL_PAYMENT`) e transferências entre contas próprias (`SELF_TRANSFER`) para jamais duplicar despesas já contabilizadas compra a compra.
  - **Classificador Determinístico (`app/services/categorizer_service.py`)**: Avalia transações na ordem: (1) Classificação manual do usuário (`manual_reviewed=True`), (2) Regras criadas pelo usuário ordenadas por `priority DESC`, (3) Mapeamento de categorias da Pluggy (`pluggy_category`), ou (4) `Não Categorizado` para revisão transparente.
  - **Conector Pluggy (`app/services/pluggy_service.py` & `app/services/sync_service.py`)**: Autenticação server-to-server (`POST /auth`), emissão de `connectToken` efêmero (`POST /connect_token`), paginação por cursor via `GET /v2/transactions`, faturas (`GET /bills`) e sincronização idempotente com trava de concorrência (`SyncRun`) e trilha de auditoria (`AuditEvent`).
  - **Motor de Relatórios e Alertas (`app/services/report_service.py`)**: Geração de relatórios diários (20:00 `America/Sao_Paulo`), semanais (domingo à noite com comparativo contra os 7 dias anteriores) e alertas de orçamento (`50%`, `75%`, `90%`, `100%`) com envio via **E-mail (Resend API / SMTP TLS)**, **Telegram Bot** e **Discord Webhook**.
- **Frontend (`c:\projetos\Cartao_bruno\frontend`)**:
  - **React 18 + TypeScript + Tailwind CSS + Recharts + Widget Oficial `react-pluggy-connect`**.
  - 6 páginas completas: **Visão Geral (Dashboard)**, **Transações**, **Orçamentos e Categorias**, **Relatórios Diários e Semanais**, **Conexões Bancárias (Open Finance)** e **Configurações & LGPD**.

---

## 2. Relatório de Viabilidade Técnica: Pluggy & Santander Open Finance

A auditoria técnica realizada diretamente na API da Pluggy (`https://api.pluggy.ai`) com as credenciais do projeto confirmou:

1. **Autenticação e Permissão de API**:
   - `POST https://api.pluggy.ai/auth` e `POST https://api.pluggy.ai/connect_token` operam com sucesso (`HTTP 200`).
2. **Conector Santander (Open Finance Brasil)**:
   - **Conector principal**: **Santander (`id: 608`)** — Tipo `PERSONAL_BANK`, Open Finance regulamentado pelo Banco Central, status `ONLINE`.
   - **Produtos suportados**: `ACCOUNTS`, `CREDIT_CARDS`, `TRANSACTIONS`, `IDENTITY`, `PAYMENT_DATA`.
   - **Conector complementar**: **Santander Cartões (`id: 604`)** — Tipo `CREDIT_CARD` (`ONLINE`).
3. **Descoberta Crítica sobre o Endpoint de Transações (`/v2/transactions`)**:
   - O endpoint legado `GET /transactions` retorna `410 Gone` (`"This endpoint is deprecated. Use GET /v2/transactions with cursor pagination instead."`).
   - O endpoint `GET /v2/transactions` utiliza paginação por cursor (`cursor` / `next`) e não aceita `pageSize` arbitrário. O cliente em `app/services/pluggy_service.py` foi implementado nativamente sobre `GET /v2/transactions` com paginação automática até o fim do cursor.
4. **Validação Real em Sandbox vs. Conta Real Santander**:
   - **Validado ao vivo (Sandbox Pluggy Bank `connectorId: 2`)**: Conexão real criada e sincronizada (`Item ID: d0d7dddd-40e1-44c8-9a32-68aa1e8dc167`), importando Conta Corrente (`fb050a4f-30b8-4720-b4bb-15878aaf3253`) e Cartão de Crédito **Mastercard Black** (`91722b6a-1bf5-4596-a840-5a68ee6469b7`, limite de R$ 20.000,00 / disponível R$ 17.400,00) com 41 transações reais processadas, categorizadas e deduplicadas.
   - **Conexão com Cartão Santander Real (`connectorId: 608`)**: O fluxo via widget oficial `PluggyConnect` já está integrado na interface. Para conectar o cartão real do titular, basta clicar em **"Abrir Pluggy Connect Oficial"** na aba **Conexões Bancárias**, selecionar **Santander** e autorizar o redirecionamento OAuth no aplicativo Santander do celular do titular (sujeito à política do plano Trial/Produção da conta Pluggy na criação de Items fora do Sandbox).

---

## 3. Modelo de Dados Relacional (14 Tabelas)

Definido em `backend/migrations/0001_initial_schema.sql` e `backend/app/models.py`:

| Tabela | Responsabilidade |
| :--- | :--- |
| `users` | Dados do titular e fuso horário padrão (`America/Sao_Paulo`), pronto para multiusuário (`user_id`). |
| `bank_connections` | Vínculo com `pluggy_item_id`, status do consentimento, `is_sandbox`, `last_sync_at` e erros de provedor. |
| `financial_accounts` | Contas correntes e cartões de crédito (`CREDIT`), limites total/disponível em centavos e datas de fechamento/vencimento. |
| `categories` | 14 categorias iniciais (Delivery, Alimentação e Restaurantes, Transporte, Supermercado, Assinaturas, Saúde, etc.). |
| `categorization_rules` | Regras determinísticas (`CONTAINS`, `EXACT`, `STARTS_WITH`, `REGEX`) com campo alvo e `priority`. |
| `budgets` | Orçamentos mensais por categoria em centavos (`limit_cents`), flag `include_pending` e limiares de alerta (`50,75,90,100`). |
| `budget_alerts` | Histórico idempotente de alertas disparados por ciclo (`budget_id + period_key + threshold_pct`). |
| `transactions` | Transações normalizadas em centavos (`amount_cents`), `tx_type` (`EXPENSE`, `REFUND`, `BILL_PAYMENT`, `SELF_TRANSFER`, `INCOME`), `status` (`POSTED`, `PENDING`, `CANCELLED`), `manual_reviewed` e metadados de parcelas. |
| `report_preferences` | Configuração de horários e ativação dos relatórios diário e semanal. |
| `notification_preferences` | Configuração de canais de entrega (E-mail Resend/SMTP, Telegram Bot e Discord Webhook). |
| `report_runs` | Histórico imutável de relatórios diários e semanais gerados (`content_markdown` e `content_html`). |
| `notification_deliveries` | Log auditável de cada tentativa de envio (`SENT`, `SIMULATED_NO_CREDENTIALS`, `FAILED`). |
| `sync_runs` | Histórico de sincronizações com contadores de inserções, atualizações e deduplicações. |
| `audit_events` | Trilha de auditoria e conformidade LGPD (sincronizações, reclassificações, revogações de conexão). |

---

## 4. Instalação e Execução Local

### Pré-requisitos
- **Python 3.11+** (ambiente virtual em `backend/.venv`)
- **Node.js 18+**

### 1. Configurar Variáveis de Ambiente
Crie ou verifique o arquivo `.env` na raiz `c:\projetos\Cartao_bruno\.env` (baseado em `.env.example`):
```env
PLUGGY_CLIENT_ID=seu_client_id
PLUGGY_CLIENT_SECRET=seu_client_secret
```

### 2. Iniciar o Backend (FastAPI na porta 8000)
```powershell
cd c:\projetos\Cartao_bruno\backend
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Iniciar o Frontend (React + Vite na porta 5173)
```powershell
cd c:\projetos\Cartao_bruno\frontend
npm install
npm run dev
```
Acesse no navegador: **http://localhost:5173**

---

## 5. Executando a Suíte de Testes (Unitários + Integração + E2E)

Para rodar os testes automatizados que validam a matemática em centavos, o caso do orçamento de R$ 500,00 no iFood (compras de R$ 100,00 e R$ 50,00), estornos, exclusão de pagamento de fatura, deduplicação `PENDING` → `POSTED`, sincronização real com a Pluggy Sandbox e geração de relatórios:

```powershell
cd c:\projetos\Cartao_bruno\backend
.\.venv\Scripts\python.exe -m pytest -v
```

---

## 6. Configuração de E-mail, Telegram e Discord para Relatórios Passivos

1. **E-mail (Canal Prioritário no MVP)**:
   - Configure `RESEND_API_KEY` no `.env` **ou** preencha `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` e `SMTP_PASSWORD` no `.env` / na aba **Configurações & LGPD**.
   - Caso nenhuma credencial SMTP/Resend esteja configurada, o sistema gera o relatório completo normalmente, exibe o conteúdo formatado na aba **Relatórios Diários e Semanais** e registra o status transparente `SIMULATED_NO_CREDENTIALS` no log de entregas (sem fingir um envio externo).
2. **Telegram Bot**:
   - Crie um bot via `@BotFather`, obtenha o token e seu `Chat ID`, e informe-os na aba **Configurações & LGPD** (ou via `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no `.env`).
3. **Discord Webhook**:
   - Informe a URL do Webhook do canal no `.env` (`DISCORD_WEBHOOK_URL`) ou via API `PUT /api/settings`.

---

## 7. Checklist de Segurança e Conformidade LGPD

- [x] **Segredos restritos ao Backend**: `PLUGGY_CLIENT_ID` e `PLUGGY_CLIENT_SECRET` nunca são enviados ao navegador nem expostos em variáveis `VITE_*`.
- [x] **Zero armazenamento de senhas bancárias**: A autorização ocorre exclusivamente via OAuth/Open Finance no ambiente da Pluggy e do banco detentor da conta.
- [x] **Revogação e Exclusão (Direito de Eliminação LGPD)**: Na aba **Conexões Bancárias**, o botão **Desconectar** revoga o Item na Pluggy (`DELETE /items/{id}`) e remove todas as contas e transações associadas no banco local, registrando o evento em `audit_events`.
- [x] **Portabilidade LGPD**: Endpoint `GET /api/lgpd/export` disponível para exportação estruturada dos dados do titular.
