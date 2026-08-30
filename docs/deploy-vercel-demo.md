# Publicar o dashboard DEMO na Vercel

O código está pronto e verificado contra as bases DEMO de verdade. O que falta é
uma credencial que não existe nesta VPS, e por isso a publicação depende de
alguns cliques da Bruna.

## Por que parou aqui

`VERCEL_TOKEN` e `VERCEL_SCOPE` existem no ambiente e nos arquivos `.env` da
operação, mas os dois estão **vazios** (`len=0`). A CLI da Vercel não está
instalada e nunca houve `vercel login` (não existe `auth.json` em
`~/.local/share/com.vercel.cli/`). A API responde `403 missing authentication
token`. Não há projeto Vercel vinculado a nenhum repositório da operação.

Ou seja: não é bug, é credencial ausente. Nada de deploy foi tentado às cegas.

## O que já foi verificado por aqui

Sem a URL pública dá para provar quase tudo, e foi provado: um servidor local
espelha os cabeçalhos do `vercel.json` e roda o mesmo `api/dashboard.py` que vai
para produção.

- O endpoint lê as três bases DEMO reais e devolve 5 lançamentos, 2 custos e
  2 orçamentos, todos rotulados `DEMO —` e datados em 2035.
- `POST`, `PUT`, `PATCH` e `DELETE` respondem **405** com `Allow: GET`.
- Sem `SABIA_DEMO=1` o endpoint responde **503** com mensagem genérica, sem
  vazar token, id de base ou erro cru do Notion.
- Linha com `Dados de demonstração` desmarcado, nulo ou ausente é descartada.
- Num Chromium de verdade, com a CSP de produção aplicada, uma página servida
  na origem `https://www.notion.so` **carrega o dashboard dentro de um iframe**;
  uma origem não autorizada leva `ERR_BLOCKED_BY_RESPONSE`. O `frame-ancestors`
  está correto para o embed.

Duas correções saíram dessa verificação e já estão no repositório:

1. As barras dos dois gráficos usavam `style="width:…"`. A CSP de produção tem
   `style-src 'self'` sem `'unsafe-inline'`, que **descarta estilo inline** — em
   produção toda barra apareceria do mesmo tamanho. A largura passou a ser
   aplicada via CSSOM, que a CSP permite. Sob a CSP de produção o console agora
   registra zero violações.
2. `.track i` ganhou `width:0` no CSS. Se a largura falhar de novo, a barra
   aparece vazia em vez de aparecer cheia — num gráfico financeiro, falhar
   visível é melhor que falhar mentindo.

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
   O repositório é privado: na primeira vez a Vercel vai pedir para você
   autorizar o app do GitHub e liberar o acesso a ele.
3. Framework Preset: **Other**. Root Directory: deixe a raiz (`./`).
   Não mude Build Command nem Output Directory: o `vercel.json` do repositório
   já define `outputDirectory: dashboard` e a função `api/dashboard.py`.
4. Abra **Environment Variables** e adicione as cinco abaixo, todas em
   **Production** (e em Preview, se quiser testar antes de promover):

   | Nome | Valor |
   | --- | --- |
   | `SABIA_DEMO` | `1` |
   | `NOTION_TOKEN` | o secret da integração `Sabia DEMO publico` |
   | `NOTION_LANCAMENTOS_DEMO_ID` | id da base `DEMO — Lançamentos financeiros` |
   | `NOTION_CUSTOS_DEMO_ID` | id da base `DEMO — Custos fixos e assinaturas` |
   | `NOTION_ORCAMENTO_DEMO_ID` | id da base `DEMO — Orçamento por categoria` |

   Os três ids não entram neste repositório de propósito — ele pode se tornar
   público. Peça para a Ária te mandar os valores, ou pegue você mesma: abra a
   base no Notion, `...` → **Copy link**, e o id é a sequência de 32 caracteres
   depois da última barra e antes do `?`.

5. **Deploy**. O primeiro build leva cerca de um minuto.

## Conferir depois do deploy

Trocando `<url>` pela URL que a Vercel devolver:

- Abra a URL e confirme o selo **AMBIENTE DEMO · DADOS FICTÍCIOS** no topo, e
  que as barras dos dois gráficos têm tamanhos diferentes entre si.
- Se o canto direito do cabeçalho disser `Modo offline · snapshot`, a função não
  está alcançando o Notion: revise as cinco variáveis de ambiente. A página
  continua abrindo porque existe um snapshot fictício de reserva, então esse
  aviso é o único sinal de que a leitura ao vivo falhou.
- Cabeçalhos (use GET; `curl -I` manda `HEAD`, que a função não implementa):

  ```bash
  curl -s -D- -o /dev/null https://<url>/api/dashboard | grep -i content-security-policy
  ```

  Precisa conter `frame-ancestors https://www.notion.so https://notion.so`.
  O cabeçalho aparece duas vezes, uma posta pelo `vercel.json` e outra pela
  função. Os dois valores são idênticos, então a política vale igual.

- Escrita recusada:

  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<url>/api/dashboard
  ```

  Precisa responder `405`.

## Incorporar no Celeiro › Finanças

Com a URL no ar, quem fecha é o script — não faça na mão:

```bash
python3 scripts/embutir_dashboard_notion.py https://<url>
```

Ele faz backup da página em `backups/` antes de tocar em qualquer coisa, insere
o dashboard como bloco `embed` logo abaixo do título, move os links diretos das
bases para um toggle discreto chamado **Abrir as bases direto no Notion**,
arquiva a lista seca antiga e no fim relê a página para conferir o resultado.
Rodar de novo não duplica nada, e rodar com uma URL nova só atualiza o embed.

Para só auditar o estado, sem alterar:

```bash
python3 scripts/embutir_dashboard_notion.py --conferir https://<url>
```

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
