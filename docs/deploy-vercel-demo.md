# Publicar o dashboard DEMO na Vercel

O código está pronto e testado. O que falta é uma credencial que não existe
nesta VPS, e por isso a publicação depende de alguns cliques da Bruna.

## Por que parou aqui

`VERCEL_TOKEN` e `VERCEL_SCOPE` existem no ambiente e nos arquivos `.env` da
operação, mas os dois estão **vazios** (`len=0`). A CLI da Vercel não está
instalada e nunca houve `vercel login` (não existe `auth.json` em
`~/.local/share/com.vercel.cli/`). A API responde `403 missing authentication
token`. Não há projeto Vercel vinculado a nenhum repositório da operação.

Ou seja: não é bug, é credencial ausente. Nada de deploy foi tentado às cegas.

## Antes de tudo: crie uma integração Notion separada

⚠️ **Não reaproveite o token que está na VPS.** Aquele token enxerga as bases
pessoais reais (`NOTION_DATABASE_ID`, cardápio, receitas, ingredientes). Colocar
ele num projeto público significa que um vazamento na Vercel daria leitura das
bases reais, mesmo que este código só consulte as três bases DEMO.

1. Abra <https://www.notion.so/profile/integrations> e clique em **New integration**.
2. Nome: `Sabia DEMO publico`. Capabilities: deixe **só "Read content"**.
   Desmarque "Update content" e "Insert content".
3. Copie o **Internal Integration Secret**.
4. Abra cada uma das três bases DEMO (Lançamentos, Custos fixos, Orçamento),
   menu `...` → **Connections** → **Connect to** → `Sabia DEMO publico`.
   Conecte **apenas essas três**. Nenhuma base real.

## Publicar

1. Entre em <https://vercel.com/new> com a conta do GitHub `brunarezerdev`.
2. **Import Git Repository** → `brunarezerdev/sabia-organizacao-pessoal`.
3. Framework Preset: **Other**. Root Directory: deixe a raiz (`./`).
   Não mude Build Command nem Output Directory: o `vercel.json` do repositório
   já define `outputDirectory: dashboard` e a função `api/dashboard.py`.
4. Abra **Environment Variables** e adicione as cinco abaixo, todas em
   **Production** (e em Preview, se quiser testar antes de promover):

   | Nome | Valor |
   | --- | --- |
   | `SABIA_DEMO` | `1` |
   | `NOTION_TOKEN` | o secret da integração `Sabia DEMO publico` |
   | `NOTION_LANCAMENTOS_DEMO_ID` | id da base Lançamentos DEMO |
   | `NOTION_CUSTOS_DEMO_ID` | id da base Custos fixos DEMO |
   | `NOTION_ORCAMENTO_DEMO_ID` | id da base Orçamento DEMO |

   Os três ids ficam guardados na VPS, no bloco `mcp.servers.nota-demo.env` da
   configuração do OpenClaw (`~/.openclaw/openclaw.json`). Peça para a Ária te
   passar os valores; eles não entram neste repositório de propósito.

5. **Deploy**. O primeiro build leva cerca de um minuto.

## Conferir depois do deploy

- Abra a URL e confirme o selo **AMBIENTE DEMO · DADOS FICTÍCIOS** no topo.
- `curl -sI https://<url>/api/dashboard | grep -i content-security-policy`
  precisa mostrar `frame-ancestors https://www.notion.so https://notion.so`.
- `curl -s -X POST https://<url>/api/dashboard` precisa responder **405**.
- Só depois disso o embed no Celeiro/Finanças faz sentido: no Notion, digite
  `/embed`, cole a URL e deixe os links das bases num toggle logo abaixo.

## O que o endpoint garante

Está em `api/dashboard.py` e coberto por `tests/test_api_dashboard.py`:

- Responde **só GET**. POST/PUT/PATCH/DELETE devolvem 405 sem tocar no Notion.
- Recusa a subir sem `SABIA_DEMO=1` e sem as três fontes configuradas.
- Descarta toda linha que não tenha `Dados de demonstração` marcado.
- Não devolve id de página, cursor de paginação nem erro cru do Notion (falha
  vira `503` com mensagem genérica).
- O token só existe na variável de ambiente do projeto. Nunca vai ao browser,
  nunca entra no repositório, nunca viaja na URL.
- Só biblioteca padrão: `api/requirements.txt` está vazio de propósito para o
  bundle público não arrastar `requests`, `google-auth` nem `mcp`.
