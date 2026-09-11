# Gmail Organizer

Arruma a caixa de entrada por **regras fixas**, não por adivinhação. É um
porteiro com uma lista colada à parede: olha para o remetente e o assunto,
compara com a lista, carimba. A mesma caixa de entrada dá sempre o mesmo
resultado.

Tudo se faz a clicar, numa página que corre no teu computador.

```
┌───────────────────────────────┬────────────────────────────────────────┐
│  Regras                       │  Pré-visualizar                        │
│  1. Chefe → estrela, parar    │  ☑ noticias@jornal.pt                  │
│  2. Newsletters → arquivar    │     Edição de hoje   + Newsletters −📥  │
│  3. Recibos → Finanças        │  ☑ faturas@edp.pt                      │
│  [+ Nova regra]               │     Fatura de julho  + Finanças  −📥   │
│                               │            [ Aplicar a 2 ]             │
└───────────────────────────────┴────────────────────────────────────────┘
```

## Abrir

1. Descarrega ou clona esta pasta.
2. **Duplo-clique** em `Abrir Gmail Organizer.command` (macOS/Linux) ou
   `Abrir Gmail Organizer.bat` (Windows).
3. Na primeira vez prepara sozinho o ambiente (um minuto) e depois abre o
   browser em `http://127.0.0.1:8765`.

Precisas de ter o [Python 3.10+](https://www.python.org/downloads/) instalado.
No Windows, marca **Add Python to PATH** durante a instalação.

## Ligar a conta (só na primeira vez)

A própria página explica os passos, mas em resumo:

1. [Consola da Google Cloud](https://console.cloud.google.com/projectcreate) → cria um projeto.
2. *APIs & Services → Library* → ativa a **Gmail API**.
3. *Credentials → Create credentials → OAuth client ID* → tipo **Desktop app**.
4. Descarrega o JSON e **larga-o na página**.
5. Clica em **Autorizar no Google** e dá permissão na janela que abre.

Fica tudo no teu computador: o `credentials.json` e o `token.json` ao lado do
programa, e o servidor só aceita ligações de `127.0.0.1`. O programa pede o
âmbito `gmail.modify` (mexer em etiquetas) e lê apenas os cabeçalhos
`From`, `To`, `Subject`, `Date` e `List-Id` — nunca o corpo das mensagens.

## Usar

**Regras** (coluna esquerda) — `+ Nova regra` abre um formulário:

- **Aplicar quando…** escolhes se têm de bater *todas* as condições ou
  *qualquer uma* delas, e acrescentas as condições que quiseres.
- **Então…** etiquetas a pôr ou tirar, arquivar, marcar lida, estrela, lixo.
- **Parar aqui** fecha a porta às regras seguintes para aquela mensagem.

As regras correm de cima para baixo — usa as setas ↑↓ para as ordenares. As
exceções ("o chefe nunca é arquivado") vão no topo, com *parar aqui*.

**Pré-visualizar** (coluna direita) — mostra, mensagem a mensagem, o que ia
acontecer. Nada muda enquanto não carregares em **Aplicar**, e podes
desmarcar as que não queres.

Tudo o que fizeres é guardado em `rules.yaml`, ao lado do programa.

### Condições disponíveis

| Condição | Exemplo |
|---|---|
| Remetente é ou contém / NÃO é | `chefe@empresa.com`, `banco.pt` |
| Para (ou em cópia), Em cópia | `eu@exemplo.com` |
| Remetente (regex) | `^no-?reply@` |
| Assunto contém | `fatura, recibo, encomenda` |
| Assunto (regex) | `^\[ALERT\]` |
| List-Id contém | `github.com` |
| É newsletter ou lista | sim / não |
| Tem / não tem a etiqueta | `CATEGORY_PROMOTIONS` |
| Está por ler, tem estrela, está na caixa de entrada | sim / não |
| Mais antiga / mais recente que (dias) | `7` |
| Maior que | `10M` |

### Segurança

- **Nada acontece sem confirmação.** Pré-visualizas, escolhes, aplicas.
- **O lixo é opt-in duplo:** tens de ligar *Permitir enviar para o lixo* nas
  definições *e* escolher essa ação na regra. Um erro num padrão não pode
  esvaziar uma caixa de entrada.
- **Limite por execução** trava uma regra demasiado larga.
- Arquivar e etiquetar é sempre reversível; o lixo fica recuperável 30 dias.

## Linha de comandos (opcional)

O motor é o mesmo; a página é só uma casca por cima.

```bash
python -m gmail_organizer ui       # abre a app no browser
python -m gmail_organizer check    # valida o rules.yaml, não toca no Gmail
python -m gmail_organizer run      # dry run: mostra o que faria
python -m gmail_organizer run --apply
python -m gmail_organizer labels   # lista as etiquetas da conta
```

O `run` aceita `--limit N`, `--search "in:inbox is:unread"` e `-v`.

Um `rules.yaml` é simplesmente:

```yaml
search: "in:inbox"
max_messages: 500
allow_trash: false

rules:
  - name: "Newsletters fora da caixa de entrada"
    match:
      is_list: true
    actions:
      add_labels: ["Newsletters"]
      archive: true
```

Vê o `rules.example.yaml` para o conjunto completo de condições e ações.

## Testes

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium   # só para os testes de browser
python -m pytest
```

48 testes, todos sem rede e sem credenciais — o Gmail é substituído por um
duplo. Oito deles abrem a página num Chromium a sério e clicam nela: é o que
apanha os erros que nenhum teste de API vê, como uma regra de CSS a anular o
atributo `hidden` e deixar o véu de carregamento por cima da página. Os testes
de browser saltam-se sozinhos se o Playwright não estiver instalado.

## Estrutura

```
Abrir Gmail Organizer.command   arranque com duplo-clique (macOS/Linux)
Abrir Gmail Organizer.bat       idem, Windows
gmail_organizer/
  message.py       normaliza a resposta da API numa view útil
  rules.py         YAML <-> regras -> plano de alterações (lógica pura)
  gmail_client.py  pesquisa, hidratação em lote, batchModify, retries
  organizer.py     junta tudo, agrupa alterações iguais num só pedido
  webapp.py        servidor local: só 127.0.0.1, token por sessão
  web/             a interface (HTML, CSS, JS — sem dependências)
  cli.py           ui / check / run / labels
  auth.py          OAuth de app desktop
tests/             motor de regras, API da app, e a página num browser real
```
