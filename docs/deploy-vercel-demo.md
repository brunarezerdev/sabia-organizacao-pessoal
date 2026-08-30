# Dashboard DEMO na Vercel

**No ar:** <https://sabia-dashboard-demo.vercel.app>

Publicado em 30/08/2026 com o token que a Bruna mandou. O painel está público,
embutido no Celeiro › Finanças, e roda em **modo snapshot** — dados fictícios
que vêm do arquivo, sem tocar no Notion. É o suficiente para o vídeo pitch.

A leitura ao vivo das bases DEMO continua desligada de propósito: falta a
integração Notion separada, que só a Bruna pode criar. Passo a passo em
[Ligar a leitura ao vivo](#ligar-a-leitura-ao-vivo).

## O que está no ar

| | |
| --- | --- |
| URL pública | <https://sabia-dashboard-demo.vercel.app> |
| Projeto Vercel | `sabia-dashboard-demo`, escopo `brunarezerdevs-projects` |
| Variáveis em Production | só `SABIA_DEMO=1` |
| Origem dos dados | `dashboard/data.json` (snapshot fictício) |
| Selo no topo | `AMBIENTE DEMO · DADOS FICTÍCIOS`, permanente |

O canto direito do cabeçalho mostra **`Modo offline · snapshot`**. Hoje isso é o
estado esperado, não um defeito: sem `NOTION_TOKEN` a função responde 503 e a
página cai no snapshot de reserva. Quando a leitura ao vivo for ligada, esse
texto vira `Última atualização: <hora>`.

O projeto `sabia-app`, que já existia na mesma conta, **não foi tocado**. Este é
um projeto novo e separado.

As URLs por deploy (`sabia-dashboard-demo-<hash>-…vercel.app`) ficam atrás do
login da Vercel; a que é pública, e a que deve ser usada em qualquer lugar, é a
URL limpa acima.

### Sobre o que sobe para a Vercel

A raiz do repositório tem `.env` com credenciais reais em uso (Telegram, Notion
das bases pessoais, OpenAI, Anthropic) e `backups/` com dumps do Notion. O
`.vercelignore` é uma **lista de permissão**: tudo na raiz fica de fora e só
voltam `api/`, `dashboard/` e `vercel.json`. Arquivo sensível novo na raiz já
nasce excluído, sem ninguém precisar lembrar de adicionar.

## Ligar a leitura ao vivo

Faltam dois passos: um da Bruna, outro da Ária.

### Passo 1 — Bruna: criar a integração (5 minutos)

⚠️ **Não reaproveite o token que está na VPS.** Aquele token enxerga as bases
pessoais reais (`NOTION_DATABASE_ID`, cardápio, receitas, ingredientes). Colocar
ele num projeto público significa que um vazamento na Vercel daria leitura das
bases reais, mesmo que este código só consulte as três bases DEMO.

1. Abra <https://www.notion.so/profile/integrations> e clique em **New integration**.
2. Nome: `Sabia DEMO publico`. Em Capabilities deixe **só "Read content"**.
   Desmarque "Update content" e "Insert content".
3. Copie o **Internal Integration Secret**.
4. Abra cada uma das três bases DEMO (Lançamentos, Custos fixos, Orçamento),
   menu `...` → **Connections** → **Connect to** → `Sabia DEMO publico`.
   Conecte **apenas essas três**. Nenhuma base real.
5. Mande o secret para a Ária. Os três ids ela levanta sozinha; se preferir
   mandar, abra a base → `...` → **Copy link**: o id é a sequência de 32
   caracteres depois da última barra e antes do `?`.

### Passo 2 — Ária: publicar as variáveis e redeployar

Com o secret em mãos, é isto, na raiz do repositório. Os valores entram por
`stdin` para não ficarem no histórico do shell.

Os caminhos concretos do token da Vercel e da CLI **não moram neste arquivo**:
este repositório pode se tornar público, e caminho absoluto de host entrega a
estrutura da VPS sem servir para mais nada. Eles estão nas notas de operação da
Ária, em `data/vercel-sabia-demo.md`, fora do repositório.

```bash
export VERCEL_TOKEN="$(cat "$CAMINHO_DO_TOKEN")"
VC="vercel --token $VERCEL_TOKEN --scope brunarezerdevs-projects"

printf '%s' '<SECRET_DA_INTEGRACAO>' | $VC env add NOTION_TOKEN production
printf '%s' '<ID_LANCAMENTOS>'       | $VC env add NOTION_LANCAMENTOS_DEMO_ID production
printf '%s' '<ID_CUSTOS>'            | $VC env add NOTION_CUSTOS_DEMO_ID production
printf '%s' '<ID_ORCAMENTO>'         | $VC env add NOTION_ORCAMENTO_DEMO_ID production

# Variável nova só vale no build seguinte. Sem este passo, nada muda.
$VC deploy --prod --yes
```

Conferir se pegou:

```bash
curl -s https://sabia-dashboard-demo.vercel.app/api/dashboard | head -c 200
```

Tem que sair o JSON com `"ambiente":"DEMO"` e a lista de lançamentos, **não**
`{"erro":"Dados temporariamente indisponíveis."}`. Na página, o cabeçalho troca
`Modo offline · snapshot` por `Última atualização: <hora>`.

Se continuar em 503, o motivo está no log da função (`$VC logs`): a função nunca
devolve detalhe de erro para o browser, de propósito.

## Conferir o que está no ar

```bash
U=https://sabia-dashboard-demo.vercel.app

# selo permanente
curl -s $U/ | grep -o 'AMBIENTE DEMO · DADOS FICTÍCIOS'

# frame-ancestors, necessário para o embed abrir dentro do Notion
curl -s -D- -o /dev/null $U/ | grep -i content-security-policy

# escrita recusada
curl -s -o /dev/null -w '%{http_code}\n' -X POST $U/api/dashboard   # 405
```

Use GET: `curl -I` manda HEAD, que a função não implementa.

No navegador, confira que as barras dos dois gráficos têm **tamanhos diferentes
entre si**. Se todas aparecerem iguais (ou todas vazias), a CSP voltou a
descartar a largura — veja a nota sobre CSSOM em `dashboard/app.js`.

## Embed no Celeiro › Finanças

Já feito. Quem refaz é o script, nunca na mão:

```bash
python3 scripts/embutir_dashboard_notion.py https://sabia-dashboard-demo.vercel.app
python3 scripts/embutir_dashboard_notion.py --conferir https://sabia-dashboard-demo.vercel.app
```

Ele faz backup da página em `backups/` antes de tocar em qualquer coisa, insere
o dashboard como bloco `embed` logo abaixo do título, move os links diretos das
bases para um toggle discreto chamado **Abrir as bases direto no Notion**,
arquiva a lista seca antiga e no fim relê a página para conferir. Rodar de novo
não duplica nada, e rodar com URL nova só atualiza o embed. Não toca em ícone,
capa, imagem nem nas três bases DEMO.

A lista antiga foi **arquivada**, não apagada: continua recuperável na lixeira do
Notion, e os mesmos links seguem na página dentro do toggle.

Estado atual da página, conferido pela API:

```
heading_2 › embed › toggle › paragraph › child_database × 3 › callout
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

## Pendências

- **Deploy automático no push está desligado.** O projeto não está conectado ao
  repositório do GitHub, porque conectar exige a Bruna autorizar o app da Vercel
  na conta dela. Hoje todo deploy é manual (`vercel deploy --prod --yes`). Para
  ligar: <https://vercel.com/brunarezerdevs-projects/sabia-dashboard-demo/settings/git>
  → **Connect Git Repository** → `brunarezerdev/sabia-organizacao-pessoal`.
- **Leitura ao vivo**, conforme a seção acima.
