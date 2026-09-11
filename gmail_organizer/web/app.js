"use strict";

const TOKEN = document.body.dataset.token;

/* --- condições disponíveis no editor -------------------------------- */

const CONDITIONS = {
  from:             { label: "Remetente é ou contém",   type: "list",   hint: "chefe@empresa.com, banco.pt" },
  not_from:         { label: "Remetente NÃO é",         type: "list",   hint: "chefe@empresa.com" },
  to:               { label: "Para (ou em cópia)",      type: "list",   hint: "eu@exemplo.com" },
  cc:               { label: "Em cópia",                type: "list",   hint: "equipa@exemplo.com" },
  from_regex:       { label: "Remetente (regex)",       type: "text",   hint: "^no-?reply@" },
  subject_contains: { label: "Assunto contém",          type: "list",   hint: "fatura, recibo, encomenda" },
  subject_regex:    { label: "Assunto (regex)",         type: "text",   hint: "^\\[ALERT\\]" },
  list_id:          { label: "List-Id contém",          type: "list",   hint: "github.com" },
  is_list:          { label: "É newsletter ou lista",   type: "bool" },
  has_label:        { label: "Tem a etiqueta",          type: "list",   labels: true },
  not_label:        { label: "Não tem a etiqueta",      type: "list",   labels: true },
  is_unread:        { label: "Está por ler",            type: "bool" },
  is_starred:       { label: "Tem estrela",             type: "bool" },
  in_inbox:         { label: "Está na caixa de entrada", type: "bool" },
  older_than_days:  { label: "Mais antiga que (dias)",  type: "number", hint: "7" },
  newer_than_days:  { label: "Mais recente que (dias)", type: "number", hint: "30" },
  larger_than:      { label: "Maior que",               type: "text",   hint: "10M" },
};

const ACTION_FLAGS = {
  archive:     "Arquivar",
  mark_read:   "Marcar como lida",
  mark_unread: "Marcar como não lida",
  star:        "Pôr estrela",
  unstar:      "Tirar estrela",
  trash:       "Lixo",
  stop:        "Parar aqui",
};

/* --- estado ---------------------------------------------------------- */

const state = {
  status: null,
  rules: { search: "in:inbox", max_messages: 500, allow_trash: false, rules: [] },
  messages: [],
  editingIndex: null,
};

const $ = (id) => document.getElementById(id);

/* --- comunicação com o servidor -------------------------------------- */

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "X-Organizer-Token": TOKEN,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `erro ${response.status}`);
  return payload;
}

const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2500);
}

function blocking(text) {
  $("blocker-text").textContent = text;
  $("blocker").hidden = false;
  return () => { $("blocker").hidden = true; };
}

/* --- arranque -------------------------------------------------------- */

async function refreshStatus() {
  state.status = await api("/api/status");
  const chip = $("account-chip");
  const connected = state.status.connected;

  chip.className = "chip " + (connected ? "chip--ok" : "chip--warn");
  chip.textContent = connected ? (state.status.email || "conta ligada") : "conta por ligar";
  $("btn-disconnect").hidden = !connected;
  $("setup").hidden = connected;
  $("app").hidden = !connected;
  $("btn-connect").disabled = !state.status.hasCredentials;
  $("dropzone").classList.toggle("done", state.status.hasCredentials);
  if (state.status.hasCredentials) {
    $("dropzone").querySelector("strong").textContent = "credentials.json pronto";
  }

  if (connected) {
    state.rules = await api("/api/rules");
    renderSettings();
    renderRules();
    loadLabels();
  }
}

async function loadLabels() {
  try {
    const { labels } = await api("/api/labels");
    $("label-list").innerHTML = labels.map((name) => `<option value="${escapeHtml(name)}">`).join("");
  } catch (err) {
    /* a lista de etiquetas é uma comodidade, não um bloqueio */
  }
}

/* --- definições ------------------------------------------------------- */

function renderSettings() {
  $("search").value = state.rules.search || "in:inbox";
  $("max-messages").value = state.rules.max_messages || 500;
  $("allow-trash").checked = !!state.rules.allow_trash;
}

function collectSettings() {
  state.rules.search = $("search").value.trim() || "in:inbox";
  state.rules.max_messages = Number($("max-messages").value) || 500;
  state.rules.allow_trash = $("allow-trash").checked;
}

/* --- lista de regras --------------------------------------------------- */

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function describeCondition(key, value) {
  if (key === "any_of") return "qualquer uma de várias condições";
  const meta = CONDITIONS[key];
  const name = meta ? meta.label : key;
  if (meta && meta.type === "bool") return value ? name : `NÃO ${name.toLowerCase()}`;
  return `${name}: ${Array.isArray(value) ? value.join(", ") : value}`;
}

function describeRule(rule) {
  const match = rule.match || {};
  const conditions = [];
  if (Array.isArray(match.any_of)) {
    for (const block of match.any_of) {
      for (const [key, value] of Object.entries(block)) conditions.push(describeCondition(key, value));
    }
  }
  for (const [key, value] of Object.entries(match)) {
    if (key !== "any_of") conditions.push(describeCondition(key, value));
  }

  const actions = rule.actions || {};
  const doing = [];
  for (const label of actions.add_labels || []) doing.push({ text: `+ ${label}`, kind: "do" });
  for (const label of actions.remove_labels || []) doing.push({ text: `− ${label}`, kind: "do" });
  for (const [flag, text] of Object.entries(ACTION_FLAGS)) {
    if (!actions[flag]) continue;
    doing.push({ text, kind: flag === "trash" ? "danger" : flag === "stop" ? "stop" : "do" });
  }
  return { conditions, doing, joiner: Array.isArray(match.any_of) ? "ou" : "e" };
}

function renderRules() {
  const list = $("rules-list");
  list.innerHTML = "";
  const rules = state.rules.rules || [];
  $("rules-empty").hidden = rules.length > 0;

  rules.forEach((rule, index) => {
    const { conditions, doing, joiner } = describeRule(rule);
    const node = document.createElement("div");
    node.className = "rule" + (rule.enabled === false ? " disabled" : "");
    node.innerHTML = `
      <div class="rule-top">
        <div>
          <div class="rule-name">${index + 1}. ${escapeHtml(rule.name)}</div>
          <div class="muted small">${conditions.map(escapeHtml).join(` <em>${joiner}</em> `) || "sem condições"}</div>
        </div>
        <div class="rule-order">
          <button class="btn btn--ghost btn--icon" data-act="up" ${index === 0 ? "disabled" : ""} title="subir">↑</button>
          <button class="btn btn--ghost btn--icon" data-act="down" ${index === rules.length - 1 ? "disabled" : ""} title="descer">↓</button>
        </div>
      </div>
      <div class="rule-meta">${doing.map((d) => `<span class="tag tag--${d.kind}">${escapeHtml(d.text)}</span>`).join("")}</div>
      <div class="rule-foot">
        <label class="toggle"><input type="checkbox" data-act="toggle" ${rule.enabled === false ? "" : "checked"}><span>ativa</span></label>
        <span>
          <button class="btn btn--ghost btn--icon" data-act="edit">Editar</button>
          <button class="btn btn--ghost btn--icon" data-act="delete">Apagar</button>
        </span>
      </div>`;

    node.addEventListener("click", (event) => {
      const action = event.target.dataset ? event.target.dataset.act : null;
      if (!action) return;
      if (action === "up") moveRule(index, -1);
      if (action === "down") moveRule(index, 1);
      if (action === "edit") openRuleDialog(index);
      if (action === "delete") deleteRule(index);
      if (action === "toggle") {
        rule.enabled = event.target.checked;
        saveRules();
      }
    });
    list.appendChild(node);
  });
}

function moveRule(index, delta) {
  const rules = state.rules.rules;
  const target = index + delta;
  if (target < 0 || target >= rules.length) return;
  [rules[index], rules[target]] = [rules[target], rules[index]];
  renderRules();
  saveRules();
}

function deleteRule(index) {
  const rule = state.rules.rules[index];
  if (!confirm(`Apagar a regra "${rule.name}"?`)) return;
  state.rules.rules.splice(index, 1);
  renderRules();
  saveRules();
}

async function saveRules() {
  collectSettings();
  try {
    const result = await post("/api/rules", state.rules);
    state.rules = result.rules;
    renderRules();
    renderSettings();
    toast("Guardado");
  } catch (err) {
    toast(err.message, true);
    await refreshStatus();
  }
}

/* --- editor de regra ---------------------------------------------------- */

function conditionRow(key = "from", value = "") {
  const row = document.createElement("div");
  row.className = "condition";

  const select = document.createElement("select");
  for (const [name, meta] of Object.entries(CONDITIONS)) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = meta.label;
    select.appendChild(option);
  }
  select.value = CONDITIONS[key] ? key : "from";

  const holder = document.createElement("div");
  holder.className = "value";

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn--ghost btn--icon drop";
  remove.textContent = "✕";
  remove.addEventListener("click", () => row.remove());

  const buildInput = (initial) => {
    const meta = CONDITIONS[select.value];
    holder.innerHTML = "";
    let input;
    if (meta.type === "bool") {
      input = document.createElement("select");
      input.innerHTML = `<option value="true">sim</option><option value="false">não</option>`;
      input.value = initial === false ? "false" : "true";
    } else {
      input = document.createElement("input");
      input.type = meta.type === "number" ? "number" : "text";
      input.placeholder = meta.hint || "";
      if (meta.labels) input.setAttribute("list", "label-list");
      input.value = Array.isArray(initial) ? initial.join(", ") : (initial ?? "");
    }
    holder.appendChild(input);
  };

  buildInput(value);
  select.addEventListener("change", () => buildInput(""));

  row.append(select, holder, remove);
  row.readValue = () => {
    const key = select.value;
    const meta = CONDITIONS[key];
    const input = holder.firstChild;
    if (meta.type === "bool") return [key, input.value === "true"];
    const raw = input.value.trim();
    if (!raw) return null;
    if (meta.type === "number") return [key, Number(raw)];
    if (meta.type === "list") return [key, raw.split(",").map((s) => s.trim()).filter(Boolean)];
    return [key, raw];
  };
  return row;
}

function openRuleDialog(index = null) {
  state.editingIndex = index;
  const rule = index === null
    ? { name: "", match: {}, actions: {}, enabled: true }
    : JSON.parse(JSON.stringify(state.rules.rules[index]));

  $("rule-dialog-title").textContent = index === null ? "Nova regra" : "Editar regra";
  $("rule-name").value = rule.name || "";
  $("rule-error").hidden = true;

  const match = rule.match || {};
  const otherKeys = Object.keys(match).filter((k) => k !== "any_of");
  const anyBlocks = Array.isArray(match.any_of) ? match.any_of : null;
  const simpleAny = anyBlocks && otherKeys.length === 0 && anyBlocks.every((b) => Object.keys(b).length === 1);
  const advanced = anyBlocks && !simpleAny;

  document.querySelector(`input[name="match-mode"][value="${simpleAny ? "any" : "all"}"]`).checked = true;
  $("advanced-warning").hidden = !advanced;

  const box = $("conditions");
  box.innerHTML = "";
  const pairs = simpleAny
    ? anyBlocks.map((block) => Object.entries(block)[0])
    : otherKeys.map((key) => [key, match[key]]);
  if (pairs.length === 0) pairs.push(["from", ""]);
  for (const [key, value] of pairs) box.appendChild(conditionRow(key, value));

  const actions = rule.actions || {};
  $("act-add-labels").value = (actions.add_labels || []).join(", ");
  $("act-remove-labels").value = (actions.remove_labels || []).join(", ");
  for (const flag of Object.keys(ACTION_FLAGS)) $(`act-${flag}`).checked = !!actions[flag];

  $("rule-dialog").showModal();
}

function readRuleDialog() {
  const name = $("rule-name").value.trim();
  if (!name) throw new Error("Dá um nome à regra.");

  const rows = [...$("conditions").querySelectorAll(".condition")];
  const pairs = rows.map((row) => row.readValue()).filter(Boolean);
  if (pairs.length === 0) throw new Error("Acrescenta pelo menos uma condição com valor.");

  const mode = document.querySelector('input[name="match-mode"]:checked').value;
  const match = mode === "any"
    ? { any_of: pairs.map(([key, value]) => ({ [key]: value })) }
    : Object.fromEntries(pairs);

  const actions = {};
  const add = $("act-add-labels").value.split(",").map((s) => s.trim()).filter(Boolean);
  const remove = $("act-remove-labels").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (add.length) actions.add_labels = add;
  if (remove.length) actions.remove_labels = remove;
  for (const flag of Object.keys(ACTION_FLAGS)) if ($(`act-${flag}`).checked) actions[flag] = true;

  const effective = Object.keys(actions).filter((k) => k !== "stop");
  if (effective.length === 0) throw new Error("Escolhe pelo menos uma ação além de «parar aqui».");
  if (actions.trash && !$("allow-trash").checked) {
    throw new Error("Para usar o lixo, liga primeiro «Permitir enviar para o lixo» nas definições.");
  }

  const previous = state.editingIndex === null ? {} : state.rules.rules[state.editingIndex];
  return { name, enabled: previous.enabled !== false, match, actions };
}

/* --- pré-visualização --------------------------------------------------- */

function renderPreview(result) {
  state.messages = result.messages;

  $("preview-summary").hidden = false;
  $("preview-summary").innerHTML = `
    <div><b>${result.scanned}</b><span>analisadas</span></div>
    <div><b>${result.changed}</b><span>com alterações</span></div>
    ${result.trashed ? `<div><b>${result.trashed}</b><span>para o lixo</span></div>` : ""}
    <div><b>${result.scanned - result.changed}</b><span>ficam como estão</span></div>`;

  const table = $("preview-table");
  if (!result.messages.length) {
    table.innerHTML = "";
    $("preview-actions").hidden = true;
    $("preview-empty").hidden = false;
    $("preview-empty").textContent = result.scanned
      ? "Nenhuma mensagem corresponde às regras. Nada a fazer."
      : "A pesquisa não devolveu mensagens nenhumas.";
    return;
  }

  $("preview-empty").hidden = true;
  $("preview-actions").hidden = false;
  $("select-all").checked = true;

  table.innerHTML = `
    <table>
      <thead><tr><th></th><th>De</th><th>Assunto</th><th>O que acontece</th></tr></thead>
      <tbody>
        ${result.messages.map((message) => `
          <tr data-id="${escapeHtml(message.id)}">
            <td class="pick"><input type="checkbox" checked></td>
            <td class="cell-from">${escapeHtml(message.from)}</td>
            <td class="cell-subject">${escapeHtml(message.subject)}
              <div class="cell-rules">${escapeHtml(message.rules.join(" · "))}</div></td>
            <td>${[
              ...message.add.map((l) => `<span class="tag tag--do">+ ${escapeHtml(l)}</span>`),
              ...message.remove.map((l) => `<span class="tag">− ${escapeHtml(l === "INBOX" ? "caixa de entrada" : l)}</span>`),
              message.trash ? `<span class="tag tag--danger">lixo</span>` : "",
            ].join(" ")}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;

  table.querySelectorAll("tbody tr").forEach((row) => {
    const box = row.querySelector("input");
    box.addEventListener("change", () => {
      row.classList.toggle("off", !box.checked);
      updateApplyButton();
    });
  });
  updateApplyButton();
}

function selectedIds() {
  return [...$("preview-table").querySelectorAll("tbody tr")]
    .filter((row) => row.querySelector("input").checked)
    .map((row) => row.dataset.id);
}

function updateApplyButton() {
  const count = selectedIds().length;
  $("btn-apply").disabled = count === 0;
  $("btn-apply").textContent = count === state.messages.length
    ? `Aplicar a todas (${count})`
    : `Aplicar a ${count}`;
}

/* --- ligações da interface ---------------------------------------------- */

function wireSetup() {
  const zone = $("dropzone");
  const input = $("file-credentials");

  const upload = async (file) => {
    const done = blocking("A guardar as credenciais…");
    try {
      await post("/api/credentials", { content: await file.text() });
      await refreshStatus();
      toast("Credenciais guardadas. Agora autoriza no Google.");
    } catch (err) {
      toast(err.message, true);
    } finally {
      done();
    }
  };

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => { if (input.files[0]) upload(input.files[0]); });

  $("btn-connect").addEventListener("click", async () => {
    $("connect-hint").hidden = false;
    const done = blocking("À espera da autorização no browser…");
    try {
      await post("/api/connect");
      await refreshStatus();
      toast("Conta ligada.");
    } catch (err) {
      toast(err.message, true);
    } finally {
      done();
    }
  });

  $("btn-disconnect").addEventListener("click", async () => {
    if (!confirm("Desligar a conta? As regras ficam guardadas.")) return;
    await post("/api/disconnect");
    await refreshStatus();
  });
}

function wireRules() {
  $("btn-new-rule").addEventListener("click", () => openRuleDialog(null));
  $("btn-cancel-rule").addEventListener("click", () => $("rule-dialog").close());
  $("btn-add-condition").addEventListener("click", () => $("conditions").appendChild(conditionRow()));

  $("rule-form").addEventListener("submit", (event) => {
    let rule;
    try {
      rule = readRuleDialog();
    } catch (err) {
      event.preventDefault();
      $("rule-error").textContent = err.message;
      $("rule-error").hidden = false;
      return;
    }
    if (state.editingIndex === null) state.rules.rules.push(rule);
    else state.rules.rules[state.editingIndex] = rule;
    renderRules();
    saveRules();
  });

  for (const id of ["search", "max-messages", "allow-trash"]) {
    $(id).addEventListener("change", saveRules);
  }
}

function wirePreview() {
  $("btn-preview").addEventListener("click", async () => {
    collectSettings();
    const done = blocking("A analisar a caixa de correio…");
    try {
      renderPreview(await post("/api/preview", {
        rules: state.rules,
        search: state.rules.search,
        limit: state.rules.max_messages,
      }));
    } catch (err) {
      toast(err.message, true);
    } finally {
      done();
    }
  });

  $("select-all").addEventListener("change", (event) => {
    $("preview-table").querySelectorAll("tbody tr").forEach((row) => {
      row.querySelector("input").checked = event.target.checked;
      row.classList.toggle("off", !event.target.checked);
    });
    updateApplyButton();
  });

  $("btn-apply").addEventListener("click", async () => {
    const ids = selectedIds();
    if (!confirm(`Aplicar as alterações a ${ids.length} mensagem(ns)?`)) return;
    const done = blocking("A aplicar…");
    try {
      const result = await post("/api/apply", { ids });
      toast(`${result.applied} mensagem(ns) organizada(s).`);
      $("preview-table").innerHTML = "";
      $("preview-actions").hidden = true;
      $("preview-summary").hidden = true;
      $("preview-empty").hidden = false;
      $("preview-empty").textContent = "Feito. Pré-visualiza outra vez para ver o que sobra.";
      state.messages = [];
    } catch (err) {
      toast(err.message, true);
    } finally {
      done();
    }
  });
}

wireSetup();
wireRules();
wirePreview();
refreshStatus().catch((err) => toast(err.message, true));
