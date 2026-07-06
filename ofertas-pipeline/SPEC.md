# PROMPT-MESTRE — Pipeline de Ofertas (colar no Claude Code)

Construa um monorepo completo e funcional chamado `ofertas-pipeline` com a estrutura abaixo. Ao final, gere um `README.md` com o passo a passo de configuração (secrets, service account do Google, bot do Telegram, deploy no Vercel). Trabalhe em etapas e teste o que for testável localmente.

## Contexto do negócio

Grupo de WhatsApp de ofertas da Amazon Brasil com curadoria humana de descontos reais. Compliance com o Programa de Associados: o link de afiliado NUNCA vai direto ao grupo — o grupo recebe o link de uma página pública do meu site, e é na página que fica o botão com o link de afiliado. A postagem no WhatsApp é manual (eu encaminho); a automação prepara tudo e me entrega a mensagem pronta via Telegram.

## Estrutura do repo

```
ofertas-pipeline/
├── site/                     # Site Astro (deploy no Vercel)
│   ├── src/pages/index.astro         # home: lista de ofertas
│   ├── src/pages/oferta/[slug].astro # página de cada oferta
│   ├── src/pages/sobre.astro         # página institucional + disclosure
│   └── src/data/ofertas.json         # banco de dados (alimentado pelo bot)
├── automation/
│   ├── pipeline.py           # script principal
│   ├── requirements.txt
│   └── prompt_gemini.txt     # prompt do Gemini (editável sem tocar em código)
├── .github/workflows/pipeline.yml    # cron a cada 15 min
└── README.md
```

## Planilha Google Sheets (input humano)

Colunas, nesta ordem:

| Coluna | Quem preenche | Descrição |
|---|---|---|
| `link` | humano | URL completa do produto copiada da BARRA DO NAVEGADOR (contém o nome no caminho) |
| `preco` | humano | preço atual, ex: `3480,91` |
| `imagem_url` | humano (opcional) | URL da imagem do produto (botão direito → copiar endereço da imagem) |
| `obs` | humano (opcional) | fato verificado, ex: `menor preço em 6 meses (Keepa)` — só pode ir ao post se estiver aqui |
| `status` | bot | vazio/`novo` → `publicado` ou `erro: <motivo>` |
| `post_final` | bot | texto final da mensagem do WhatsApp |
| `url_pagina` | bot | URL da página publicada no site |

## Script `pipeline.py` — fluxo

1. Autentica no Google Sheets via service account (secret `GOOGLE_SERVICE_ACCOUNT_JSON`), abre a planilha `SHEET_ID`.
2. Seleciona linhas com `status` vazio ou `novo`.
3. Para cada linha:
   a. **Parse do link**: extrai o ASIN (regex `/dp/([A-Z0-9]{10})` e variantes `/gp/product/`) e o título a partir do slug do caminho (decodifica URL, troca hífens por espaços, capitaliza). Se não houver slug com nome legível, marca `status = erro: link sem nome do produto — cole o link completo da barra do navegador` e pula.
   b. **Link de afiliado**: monta `https://www.amazon.com.br/dp/{ASIN}?tag={AFFILIATE_TAG}`. Nunca usar encurtador de terceiros.
   c. **Gemini** (modelo flash mais recente disponível no free tier, via API key `GEMINI_API_KEY`): envia título, preço e `obs` e pede um JSON com dois campos: `post_whatsapp` e `descricao_pagina`. O prompt vive em `prompt_gemini.txt` — ver regras abaixo. Parsear com tolerância a cercas de código. **Fallback obrigatório**: se a chamada falhar (rate limit, erro), gerar o post por template fixo em Python e seguir o fluxo — a publicação nunca pode depender do LLM estar de pé.
   d. **Publica no site**: adiciona a oferta em `site/src/data/ofertas.json` (campos: slug, titulo, preco, imagem_url, descricao, obs, link_afiliado, data ISO). Slug: kebab-case do título + 4 últimos caracteres do ASIN. Ofertas mais novas primeiro. Commit + push no próprio repo (o Vercel publica sozinho).
   e. **Telegram**: envia para `TELEGRAM_CHAT_ID` via bot `TELEGRAM_BOT_TOKEN`. Se houver `imagem_url`, usar `sendPhoto` com o post como caption; senão `sendMessage`. O post contém o link da página do site, NÃO o link da Amazon.
   f. Atualiza a linha: `status = publicado`, `post_final`, `url_pagina`.
4. Erros de uma linha não podem derrubar as demais (try/except por linha, erro registrado na coluna `status`).
5. Flag `--dry-run`: executa tudo sem commit, sem Telegram e sem escrever na planilha; imprime o resultado no console.

## Regras do prompt do Gemini (`prompt_gemini.txt`)

- Persona: redator de ofertas para WhatsApp, português do Brasil, tom animado mas direto.
- **REGRA INEGOCIÁVEL**: usar SOMENTE as informações fornecidas (título, preço, obs). É PROIBIDO inventar especificações técnicas, benefícios, comparações de preço, percentuais de desconto ou expressões como "menor preço", salvo se constarem literalmente no campo `obs`.
- `post_whatsapp` (formato, ~6 linhas):
  - Linha 1: hook curto com 1 emoji, sem clickbait falso
  - Linha 2: *título do produto* em negrito do WhatsApp (asteriscos simples) + `por *R$ {preco}*`
  - Linha 3 (apenas se `obs` existir): `✅ {obs}`
  - Linha 4: `➡️ Ver oferta: {url_pagina}` (placeholder que o Python substitui)
  - Linha 5: `🔗 link de afiliado · #publi`
- `descricao_pagina`: 2–3 frases sobre o produto para a página do site, mesma regra de não inventar nada.
- Saída: apenas JSON válido, sem markdown, sem preâmbulo.

## Site Astro

- Estático, sem banco: lê `ofertas.json` no build.
- **Home**: grid de cards (imagem quando houver, título, preço, selo `✅ {obs}` quando houver, botão "Ver oferta").
- **Página da oferta** (`/oferta/[slug]`): imagem, título, preço em destaque, descrição do Gemini, selo de verificação quando houver `obs`, botão grande "Ver na Amazon →" apontando para o link de afiliado com `rel="sponsored nofollow noopener"`. Imediatamente abaixo do botão, em texto menor mas legível: `Você paga exatamente o mesmo preço — a comissão sai da Amazon, não do seu bolso.`
- **Disclosure (usar estes textos exatos):**
  - **Rodapé de TODAS as páginas**, em tamanho de fonte normal de rodapé (legível sem esforço, nunca escondido): `Como Associados da Amazon, recebemos comissões por compras qualificadas feitas pelos nossos links — sem nenhum custo extra para você: o preço é exatamente o mesmo. Os preços exibidos foram verificados na data da publicação e podem mudar sem aviso.`
  - **Página /sobre**, versão estendida: `Este site participa do Programa de Associados da Amazon. Quando você compra por um dos nossos links, recebemos uma pequena comissão — paga pela Amazon, sem custo extra nenhum para você: o preço é exatamente o mesmo que você pagaria entrando direto no site. É essa comissão que mantém a curadoria funcionando: cada oferta publicada aqui passa por verificação humana de preço, e só divulgamos descontos que consideramos reais. Os preços e condições exibidos foram verificados na data da publicação e podem mudar sem aviso.`
- Design: limpo, mobile-first (o tráfego vem do WhatsApp), rápido. Sem framework de UI pesado.
- Não indexar páginas de oferta expiradas por enquanto — manter simples.

## Workflow `.github/workflows/pipeline.yml`

- `schedule: cron '*/15 * * * *'` + `workflow_dispatch` (disparo manual para testes).
- `concurrency` para nunca rodar dois jobs em paralelo.
- Python 3.12, instala `requirements.txt`, roda `python automation/pipeline.py`.
- Commit do `ofertas.json` com usuário bot; usar `GITHUB_TOKEN` com permissão de escrita (`permissions: contents: write`).
- Passar todos os secrets como env: `GOOGLE_SERVICE_ACCOUNT_JSON`, `SHEET_ID`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `AFFILIATE_TAG`, `SITE_BASE_URL`.

## README

Passo a passo numerado e verificável de: criação da planilha com as colunas exatas; criação do service account no Google Cloud + compartilhar a planilha com o e-mail dele; criação do bot no @BotFather e descoberta do chat_id; obtenção da API key do Gemini (AI Studio, free tier); configuração dos secrets no GitHub; import do repo no Vercel apontando para a pasta `site/`; teste com `--dry-run`; primeiro run real via `workflow_dispatch`.

## Critérios de pronto (teste antes de encerrar)

1. `pipeline.py --dry-run` com uma linha de exemplo imprime post e entrada do JSON corretamente.
2. Link sem slug de nome gera `status = erro` sem quebrar o run.
3. Falha simulada do Gemini aciona o template de fallback.
4. Site builda localmente (`npm run build`) com um `ofertas.json` de exemplo contendo uma oferta com imagem e uma sem.
