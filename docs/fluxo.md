# Fluxo de integração

Diagramas do caminho que uma mensagem percorre. Renderizam direto no GitHub.

---

## 1. Visão geral das integrações

```mermaid
graph LR
    P([Pessoa]) -->|escreve uma frase| TG[Telegram Bot API]
    TG -->|long polling| CAP[Captura]
    CAP --> FILA[(Fila durável<br/>em disco)]
    FILA --> ORQ{Orquestradora}
    ORQ <-->|classifica| IA[Anthropic<br/>Messages API]
    ORQ --> NOT[Notion API<br/>banco no-code]
    ORQ -->|só se tiver data| GC[Google Calendar API]
    ORQ -->|confirmação| TG

    style ORQ fill:#fff3cd,stroke:#856404,stroke-width:2px
    style FILA fill:#e2e3e5,stroke:#383d41
    style IA fill:#d1ecf1,stroke:#0c5460
    style NOT fill:#d4edda,stroke:#155724
    style GC fill:#d4edda,stroke:#155724
    style TG fill:#cce5ff,stroke:#004085
```

---

## 2. Caminho completo de uma mensagem

```mermaid
sequenceDiagram
    autonumber
    actor P as Pessoa
    participant TG as Telegram
    participant C as Captura
    participant F as Fila
    participant O as Orquestradora
    participant IA as Camada de IA
    participant N as Notion
    participant G as Google Agenda

    P->>TG: "Reunião com o cliente na quinta às 14h"
    TG-->>C: getUpdates (long polling)

    C->>C: chat_id é o autorizado?
    Note over C: origem estranha é<br/>descartada em silêncio

    C->>F: enfileirar(mensagem)
    F-->>C: id da tarefa
    C-->>P: recebido

    Note over F,O: captura e processamento são<br/>independentes daqui em diante

    O->>F: reservar()
    F-->>O: tarefa (rename atômico)

    O->>IA: classificar(texto, catálogo de agentes, hoje)
    IA-->>O: {agente, categoria, título, data, hora}
    Note right of IA: validado por JSON Schema<br/>na própria API

    O->>O: o agente existe? a categoria é dele?

    alt falta informação essencial
        O->>O: prepara pergunta curta e específica
        Note right of O: não grava item incompleto
    else pedido executável
        O->>N: criar_item(item)
        N-->>O: id da página
        opt falta detalhe secundário
            O->>O: inclui na confirmação o que ficou sem preencher
        end
        opt tem data e o agente trabalha com agenda
            O->>G: renovar access token
            G-->>O: token temporário
            O->>G: criar_evento(título, data, hora)
            G-->>O: id do evento
        end
    end

    O->>F: concluir(tarefa)
    O->>TG: pergunta ou confirmação do que foi entendido
    TG-->>P: "Antes de registrar: em que horário devo avisar?"
```

---

## 3. Decisão de roteamento

```mermaid
flowchart TD
    M[Mensagem] --> IA{Camada de IA<br/>disponível?}
    IA -->|com chave| ANT[Anthropic<br/>structured output]
    IA -->|sem chave| HEU[Heurística local<br/>palavras-chave]

    ANT --> VAL{Agente existe<br/>no registro?}
    HEU --> VAL

    VAL -->|sim| CAT{Categoria<br/>pertence a ele?}
    VAL -->|não| RESG{Resgatar pela<br/>categoria?}

    RESG -->|achou| CAT
    RESG -->|não achou| PAD[beija-flor<br/>+ pedir confirmação]

    CAT -->|sim| LAC{Falta dado<br/>essencial?}
    CAT -->|não| AJU[Usa 1ª categoria do agente<br/>+ pedir confirmação]

    PAD --> PERG
    AJU --> PERG
    LAC -->|sim| PERG[Pergunta objetiva<br/>não grava]
    LAC -->|não| OK[Classificação válida]
    PERG --> FIM
    OK --> ITEM[Monta o Item]

    ITEM --> NOT[(Notion)]
    ITEM --> EV{Tem data E o agente<br/>cria evento?}
    EV -->|sim| GC[(Google Agenda)]
    EV -->|não| FIM([Fim])
    NOT --> FIM
    GC --> FIM

    style ANT fill:#d1ecf1,stroke:#0c5460
    style HEU fill:#e2e3e5,stroke:#383d41
    style PAD fill:#f8d7da,stroke:#721c24
    style AJU fill:#fff3cd,stroke:#856404
```

---

## 4. Estados da fila durável

```mermaid
stateDiagram-v2
    [*] --> pendente: enfileirar()
    pendente --> processando: reservar()<br/>(rename atômico)
    processando --> concluida: concluir()
    processando --> pendente: falhar()<br/>ainda tem tentativa
    processando --> falha: falhar()<br/>esgotou as tentativas
    processando --> pendente: recuperar_orfas()<br/>processo morreu
    concluida --> [*]
    falha --> [*]

    note right of processando
        O rename é a trava.
        Dois workers nunca pegam
        a mesma tarefa.
    end note
```

---

## 5. Autenticação por API

```mermaid
flowchart LR
    subgraph TG[Telegram]
        T1[TELEGRAM_BOT_TOKEN] --> T2[token no<br/>caminho da URL]
    end

    subgraph NO[Notion]
        N1[NOTION_TOKEN] --> N2[Authorization:<br/>Bearer]
        N3[integração compartilhada<br/>com a database] --> N2
    end

    subgraph AN[Anthropic]
        A1[ANTHROPIC_API_KEY] --> A2[header x-api-key<br/>pelo SDK]
    end

    subgraph GO[Google — OAuth 2.0]
        G1[consentimento<br/>no navegador] -->|uma vez| G2[refresh_token<br/>em disco, chmod 600]
        G2 -->|a cada sessão| G3[access_token<br/>só em memória]
        G3 --> G4[Authorization:<br/>Bearer]
    end

    style G2 fill:#fff3cd,stroke:#856404
    style G3 fill:#d4edda,stroke:#155724
```

---

## 6. Camadas do código

```mermaid
flowchart TB
    subgraph CAPTURA
        A[integracoes/telegram.py]
    end
    subgraph DECISAO
        B[orquestradora.py]
        C[integracoes/ia.py]
    end
    subgraph EXECUCAO
        D[agentes/*.md]
        E[fila.py]
        F[automacao.py]
    end
    subgraph REGISTRO
        G[integracoes/notion.py]
        H[integracoes/google_calendar.py]
    end

    A --> B
    B <--> C
    B --> D
    B --> E
    B --> F
    F --> G
    F --> H

    style B fill:#fff3cd,stroke:#856404,stroke-width:2px
```

A orquestradora é a única peça que conhece todas as outras. As integrações não
se conhecem entre si — trocar o Notion por outro banco no-code é escrever uma
classe com o método `criar_item` e passar na construção da automação.

---

## 7. Ciclo semanal: do compromisso à tarefa derivada

O fluxo acima resolve uma mensagem. Este resolve uma semana. É o mesmo sistema
olhando para um horizonte maior: em vez de perguntar "o que é isso", pergunta
"o que isso exige que aconteça antes".

```mermaid
flowchart TD
    A[Domingo, 19h<br/>cron ou comando] --> B[ritual.py]

    B --> C[Google Agenda<br/>semana que terminou]
    B --> D[Google Agenda<br/>semana que começa]
    B --> E[Notion<br/>base de Regras]

    C --> F[FECHAR<br/>compromissos em checkbox<br/>+ pergunta de balanço]

    D --> G[motor de regras<br/>regras.py]
    E --> G
    H[lista de essenciais<br/>o que está acabando] --> G

    G --> I[tarefa de efeito direto<br/>prazo = dia - antecedência]
    G --> J[tarefa de efeito de 2ª ordem<br/>frase iniciada por Se]

    I --> K[ABRIR<br/>compromissos + efeitos<br/>+ checklist + 3 prioridades]
    J --> K

    F --> L[PacoteRitual]
    K --> L
    L --> M[texto do Telegram]
    L --> N[blocos do Notion<br/>to_do de verdade]

    style G fill:#e7d3f5,stroke:#6b3fa0,stroke-width:2px
    style J fill:#fff3cd,stroke:#856404,stroke-width:2px
```

O nó roxo é o único que decide alguma coisa, e mesmo ele não decide sozinho:
todo o comportamento vem das linhas da base de Regras, que é editada no Notion
por quem usa o sistema.

O nó amarelo é o efeito borboleta propriamente dito, a tarefa que só existe se
uma condição for verdadeira. Ela nasce junto com a tarefa direta e espera uma
checagem humana, porque é a única parte da corrente que o sistema não tem como
verificar sozinho.
