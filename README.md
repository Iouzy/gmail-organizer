# gmail-organizer

Organizador de Gmail baseado em regras. Sem IA, sem adivinhação: um porteiro com
uma lista colada à parede — olha para o remetente e o assunto, compara com a
lista, carimba. A mesma caixa de entrada dá sempre o mesmo resultado.

## Porquê não usar os filtros do Gmail

Os filtros nativos não têm ordem garantida, não têm `stop`, não fazem regex e
vivem trancados na interface web. Aqui as regras são um ficheiro YAML: versionado,
revisível, testável, e com `--apply` obrigatório para tocar na conta.

## Instalação

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Credenciais (uma vez)

1. Vai a https://console.cloud.google.com/ e cria um projeto.
2. *APIs & Services → Library* → ativa a **Gmail API**.
3. *APIs & Services → Credentials* → **Create credentials → OAuth client ID** →
   tipo **Desktop app**.
4. Descarrega o JSON e guarda-o como `credentials.json` na raiz do projeto.
5. Na primeira execução abre o browser para autorizares; o token fica em
   `token.json` (modo 600) e é renovado sozinho a partir daí.

Âmbito pedido: `gmail.modify` — mexe em etiquetas, nunca lê o corpo das mensagens
nem envia nada. O programa só pede os cabeçalhos (`From`, `To`, `Subject`,
`Date`, `List-Id`), nunca o conteúdo.

`credentials.json`, `token.json` e `rules.yaml` estão no `.gitignore`.

## Utilização

```bash
cp rules.example.yaml rules.yaml     # edita à tua medida

python -m gmail_organizer check      # valida o ficheiro, não toca no Gmail
python -m gmail_organizer run        # DRY RUN: mostra o que faria
python -m gmail_organizer run --apply  # aplica mesmo
python -m gmail_organizer labels     # lista as etiquetas da conta
```

Opções úteis do `run`:

| Flag | Efeito |
|---|---|
| `--apply` | sem isto, nada é alterado |
| `--limit N` | limita as mensagens analisadas |
| `--search "..."` | ignora o `search` do ficheiro (ex.: `"in:inbox is:unread"`) |
| `-v` | lista mensagem a mensagem |

Começa sempre por um dry run estreito:

```bash
python -m gmail_organizer run --search "in:inbox newer_than:7d" --limit 50
```

## O ficheiro de regras

```yaml
search: "in:inbox"      # que mensagens analisar (sintaxe de pesquisa do Gmail)
max_messages: 500       # travão por execução
allow_trash: false      # ações destrutivas são opt-in para o ficheiro inteiro

rules:
  - name: "Newsletters fora da caixa de entrada"
    match:
      is_list: true
    actions:
      add_labels: ["Newsletters"]
      archive: true
```

As regras correm **de cima para baixo** para cada mensagem. Todas as que
combinam acumulam ações; `stop: true` corta a cadeia ali. Por isso as exceções
("o chefe nunca é arquivado") vão no topo.

### Condições (`match`)

Dentro de um bloco `match` é tudo **E** — todas têm de ser verdade.

| Condição | Exemplo | Nota |
|---|---|---|
| `from` / `not_from` | `["chefe@empresa.com", "banco.pt"]` | endereço completo, domínio, ou parte |
| `to` / `cc` | `eu@exemplo.com` | `to` também procura no Cc |
| `from_regex` | `"^no-?reply@"` | sobre o cabeçalho `From` inteiro |
| `subject_contains` | `["fatura", "recibo"]` | qualquer um serve; ignora maiúsculas |
| `subject_regex` | `"^\\[ALERT\\]"` | ignora maiúsculas |
| `list_id` | `["github.com"]` | parte do cabeçalho `List-Id` |
| `is_list` | `true` | tem `List-Id` ou `List-Unsubscribe` |
| `has_label` / `not_label` | `["CATEGORY_PROMOTIONS"]` | IDs do sistema ou nomes de etiquetas |
| `is_unread`, `is_starred`, `in_inbox` | `true` | |
| `older_than_days` / `newer_than_days` | `7` | |
| `larger_than` | `10M` | aceita `500k`, `2.5m`, bytes |
| `any_of` | lista de blocos | **OU** entre blocos |

`any_of` é a válvula de escape quando precisas de "isto **ou** aquilo":

```yaml
match:
  any_of:
    - subject_contains: ["fatura", "recibo"]
    - from: ["no-reply@stripe.com"]
```

### Ações

| Ação | Efeito |
|---|---|
| `add_labels: ["Trabalho/Clientes"]` | cria a etiqueta (e as pais) se não existir |
| `remove_labels: [...]` | nunca cria uma etiqueta só para a tirar |
| `archive: true` | tira do `INBOX` |
| `mark_read` / `mark_unread` | |
| `star` / `unstar` | |
| `trash: true` | exige `allow_trash: true` no topo do ficheiro |
| `stop: true` | não corre mais nenhuma regra para esta mensagem |

Um `enabled: false` na regra desliga-a sem a apagares.

## Segurança

- **Dry run por omissão.** Só `--apply` escreve.
- **`trash` é opt-in duplo:** a flag no ficheiro *e* a ação na regra. Um erro de
  escrita num padrão não pode esvaziar uma caixa de entrada.
- **`max_messages`** limita o estrago de uma regra demasiado larga.
- Nada é apagado em definitivo: arquivar e etiquetar é reversível, e o lixo
  fica recuperável 30 dias.

## Testes

```bash
pip install pytest
python -m pytest
```

Os testes do motor de regras e do organizador correm sem rede e sem
credenciais — o cliente do Gmail é substituído por um duplo.

## Estrutura

```
gmail_organizer/
  message.py       normaliza a resposta da API numa view útil
  rules.py         YAML -> regras -> plano de alterações (lógica pura)
  gmail_client.py  pesquisa, hidratação em lote, batchModify, retries
  organizer.py     junta tudo, agrupa alterações iguais num só pedido
  cli.py           check / run / labels
  auth.py          OAuth de app desktop
```
