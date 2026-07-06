# ofertas-pipeline

Pipeline de ofertas da Amazon Brasil: lê uma planilha Google Sheets, gera posts com Gemini (com fallback), publica no site estático e entrega a mensagem pronta via Telegram.

```
ofertas-pipeline/
├── site/                          # Site Astro — deploy no Vercel
│   └── src/data/ofertas.json      # banco de dados (alimentado pelo bot)
├── automation/
│   ├── pipeline.py                # script principal
│   ├── requirements.txt
│   └── prompt_gemini.txt          # prompt do Gemini (editável)
└── .github/workflows/pipeline.yml # executa a cada 15 minutos
```

---

## Pré-requisitos

- Conta Google (para Sheets e Service Account)
- Conta Telegram
- Conta Google AI Studio (Gemini free tier)
- Repositório no GitHub
- Conta Vercel

---

## Passo 1 — Criar a planilha Google Sheets

1. Acesse [sheets.google.com](https://sheets.google.com) e crie uma nova planilha.
2. Na **linha 1**, adicione exatamente estes cabeçalhos (um por coluna, sem espaços extras):

   | A | B | C | D | E | F | G |
   |---|---|---|---|---|---|---|
   | `link` | `preco` | `imagem_url` | `obs` | `status` | `post_final` | `url_pagina` |

3. Anote o **ID da planilha** — é a sequência de letras e números na URL:
   `https://docs.google.com/spreadsheets/d/**SEU_SHEET_ID**/edit`

4. Salve o ID; ele será o secret `SHEET_ID`.

**Dica de uso:** Cole o link completo copiado da barra do navegador na coluna `link` (ex.: `https://www.amazon.com.br/Echo-Dot-5a-Geracao/dp/B09B8VVHJB/ref=...`). Links curtos do tipo `/dp/ASIN` sem o nome no caminho geram um erro registrado na coluna `status`.

---

## Passo 2 — Criar Service Account no Google Cloud

1. Acesse o [Google Cloud Console](https://console.cloud.google.com) e crie um projeto (ou selecione um existente).

2. Ative as APIs necessárias — no menu **APIs e Serviços → Biblioteca**, pesquise e ative:
   - **Google Sheets API**
   - **Google Drive API**

3. Crie a Service Account:
   - **APIs e Serviços → Credenciais → Criar credenciais → Conta de serviço**
   - Nome sugerido: `ofertas-bot`
   - Clique em **Concluído** (sem precisar atribuir papel no projeto)

4. Gere a chave JSON:
   - Clique na conta de serviço criada → aba **Chaves** → **Adicionar chave → Criar nova chave → JSON**
   - Baixe o arquivo `.json` gerado

5. Anote o e-mail da conta de serviço (formato `ofertas-bot@SEU-PROJETO.iam.gserviceaccount.com`).

6. **Compartilhe a planilha** com esse e-mail:
   - Abra a planilha → **Compartilhar** → cole o e-mail → permissão **Editor** → **Enviar**

7. O conteúdo completo do arquivo `.json` será o secret `GOOGLE_SERVICE_ACCOUNT_JSON`.

---

## Passo 3 — Criar o bot do Telegram e descobrir o chat_id

### Criar o bot

1. No Telegram, inicie uma conversa com **@BotFather**.
2. Digite `/newbot` e siga as instruções (escolha nome e username).
3. Ao final, o BotFather fornece o **token** no formato `123456789:AABBccDDee...` — esse é o secret `TELEGRAM_BOT_TOKEN`.

### Descobrir o chat_id

**Opção A — grupo de WhatsApp equivalente no Telegram:**
1. Crie um grupo no Telegram e adicione o seu bot.
2. Envie qualquer mensagem no grupo.
3. Acesse no navegador:
   `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`
4. Localize o campo `"chat": {"id": -100XXXXXXXXX}` — o número (incluindo o sinal negativo) é o `TELEGRAM_CHAT_ID`.

**Opção B — conversa direta com o bot (para testes):**
1. Inicie uma conversa com seu bot no Telegram.
2. Envie `/start`.
3. Acesse a mesma URL de `getUpdates` acima; o `chat.id` será um número positivo.

---

## Passo 4 — Obter a API key do Gemini (free tier)

1. Acesse [aistudio.google.com](https://aistudio.google.com).
2. Faça login com sua conta Google.
3. Clique em **Get API key → Create API key in new project**.
4. Copie a chave gerada — esse é o secret `GEMINI_API_KEY`.

> O script usa o modelo `gemini-2.0-flash`. Se a chamada falhar por qualquer motivo (rate limit, quota esgotada), o pipeline usa o template fixo de fallback e segue publicando normalmente.

---

## Passo 5 — Configurar os secrets no GitHub

1. No repositório GitHub, acesse **Settings → Secrets and variables → Actions → New repository secret**.
2. Crie os seguintes secrets (um a um):

   | Secret | Valor |
   |--------|-------|
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | Conteúdo completo do arquivo `.json` da Service Account |
   | `SHEET_ID` | ID da planilha (somente o ID, sem a URL) |
   | `GEMINI_API_KEY` | Chave do Google AI Studio |
   | `TELEGRAM_BOT_TOKEN` | Token do @BotFather |
   | `TELEGRAM_CHAT_ID` | ID do chat/grupo (pode ser negativo) |
   | `AFFILIATE_TAG` | Sua tag de afiliado Amazon, ex: `seusite-20` |
   | `SITE_BASE_URL` | URL do seu site no Vercel, ex: `https://ofertas.vercel.app` |

3. Verifique que todos os 7 secrets aparecem na lista antes de continuar.

---

## Passo 6 — Fazer o deploy no Vercel

1. Acesse [vercel.com](https://vercel.com) e faça login.
2. Clique em **Add New Project → Import Git Repository** e selecione este repositório.
3. Na tela de configuração do projeto, **expanda "Build and Output Settings"** e altere:
   - **Root Directory:** `site`
   - Framework Preset será detectado automaticamente como **Astro**
4. Clique em **Deploy**.
5. Após o deploy, anote a URL gerada (ex.: `https://ofertas-pipeline.vercel.app`) e use-a no secret `SITE_BASE_URL`.

> A cada push que altere `site/src/data/ofertas.json`, o Vercel rebuilda e publica automaticamente.

---

## Passo 7 — Testar localmente com `--dry-run`

### Testar sem credenciais (linhas de exemplo embutidas no script)

```bash
cd automation
pip install -r requirements.txt
python pipeline.py --test
```

Saída esperada:
- Linha 1: JSON da oferta + mensagem Telegram formatada
- Linha 2: `erro: link sem nome do produto — cole o link completo da barra do navegador`

### Testar com suas credenciais reais (sem publicar nada)

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON='{ ... conteúdo do json ... }'
export SHEET_ID='seu_sheet_id'
export GEMINI_API_KEY='sua_chave'
export TELEGRAM_BOT_TOKEN='seu_token'
export TELEGRAM_CHAT_ID='seu_chat_id'
export AFFILIATE_TAG='seutag-20'
export SITE_BASE_URL='https://ofertas.vercel.app'

python automation/pipeline.py --dry-run
```

Com `--dry-run`, o script:
- Lê a planilha normalmente
- Processa as linhas pendentes
- **Não** commita, **não** envia Telegram, **não** escreve na planilha
- Imprime no console o JSON da oferta e a mensagem que seria enviada

### Buildar o site localmente

```bash
cd site
npm install
npm run build
```

Resultado esperado: `4 page(s) built` (ou mais, conforme o `ofertas.json` crescer).

---

## Passo 8 — Primeiro run real via `workflow_dispatch`

1. No GitHub, acesse **Actions → Pipeline de Ofertas**.
2. Clique em **Run workflow → Run workflow** (branch `main`).
3. Acompanhe o log em tempo real.
4. Ao final, verifique:
   - A linha na planilha tem `status = publicado`
   - A coluna `url_pagina` tem a URL da página
   - O Telegram recebeu a mensagem
   - O commit `oferta: <slug>` aparece no histórico do repo
   - O Vercel fez o rebuild e a página está no ar

---

## Fluxo completo

```
Você preenche a planilha (link + preco + obs opcional)
        ↓
GitHub Actions (a cada 15 min ou manual)
        ↓
pipeline.py lê linhas com status vazio/novo
        ↓
Extrai ASIN e título do link → monta link de afiliado
        ↓
Gemini gera post + descrição  ←→  [fallback template se Gemini falhar]
        ↓
Adiciona oferta em ofertas.json → commit + push
        ↓
Vercel rebuilda o site automaticamente
        ↓
Telegram recebe a mensagem pronta com o link da PÁGINA (não da Amazon)
        ↓
Você encaminha manualmente para o grupo de WhatsApp
```

---

## Ciclo de vida das ofertas

O estado é calculado no cliente (JavaScript) a partir do campo `data`:

| Estado | Regra | Comportamento |
|--------|-------|---------------|
| **Ativa** | menos de 48h desde a publicação | Aparece na home; página normal com botão "Ver na Amazon →" |
| **Encerrada** | 48h ou mais | Some da home; a página permanece no ar com banner "⏰ Oferta encerrada" e botão "Ver preço atual na Amazon →". Página continua indexável. |

O `ofertas.json` nunca perde entradas — o histórico serve de conteúdo e SEO.

---

## Compliance com o Programa de Associados Amazon

- O link de afiliado **nunca** vai direto para o grupo de WhatsApp
- O grupo recebe o link da **página do site**; o botão com o afiliado está na página
- O disclosure obrigatório aparece no **rodapé de todas as páginas** e na página `/sobre`
- Cada link de afiliado usa `rel="sponsored nofollow noopener"`
- O script nunca usa encurtadores de URL de terceiros

---

## Solução de problemas

| Sintoma | Causa provável | Solução |
|---------|---------------|---------|
| `status = erro: link sem nome do produto` | Link curto ou copiado do app | Copie o link da **barra do navegador** no desktop |
| Gemini não gera post | API key inválida ou quota esgotada | O fallback é ativado automaticamente; verifique a key no AI Studio |
| `git push` falha no Actions | Token sem permissão de escrita | Confirme `permissions: contents: write` no workflow e que não há proteção de branch bloqueando bots |
| Vercel não rebuilda | Push foi feito com `[skip ci]` | O passo de segurança usa `[skip ci]`; o push do script (sem esse sufixo) deve disparar o Vercel normalmente |
| Telegram não recebe | `TELEGRAM_CHAT_ID` errado | Reconfirme via `getUpdates`; IDs de grupo são negativos |
