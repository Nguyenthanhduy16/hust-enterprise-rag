const API_BASE = "/api/v1";

const messagesEl = document.getElementById("messages");
const form = document.getElementById("chatForm");
const input = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const newChatBtn = document.getElementById("newChatBtn");
const historyList = document.getElementById("historyList");
const modelToggle = document.getElementById("modelToggle");
const modelLabel = document.getElementById("modelLabel");
const modelMenu = document.getElementById("modelMenu");

let streaming = false;
const history = [];
let activeHistoryId = null;
let selectedModel = null;

const WELCOME_HTML = messagesEl.innerHTML;

/* ---- Model selector ---- */
const FALLBACK_MODELS = [
  { id: "gpt-4o", label: "GPT-4o", tier: "Premium", default: true },
  { id: "gpt-4o-mini", label: "GPT-4o Mini", tier: "Fast", default: false },
];

function buildModelMenu(models) {
  modelMenu.innerHTML = models
    .map(
      (m) => `<li><button type="button" class="model-option${m.default ? " active" : ""}" data-id="${m.id}">
          <span class="opt-label">${escapeHtml(m.label)}</span>
          <span class="opt-tier" data-tier="${escapeHtml(m.tier)}">${escapeHtml(m.tier)}</span>
        </button></li>`
    )
    .join("");

  const defaultModel = models.find((m) => m.default) || models[0];
  if (defaultModel) {
    selectedModel = defaultModel.id;
    modelLabel.textContent = defaultModel.label;
  }

  modelMenu.querySelectorAll(".model-option").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedModel = btn.dataset.id;
      modelLabel.textContent = btn.querySelector(".opt-label").textContent;
      modelMenu.querySelectorAll(".model-option").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      closeModelMenu();
    });
  });
}

(async function loadModels() {
  try {
    const resp = await fetch(`${API_BASE}/chat/models`);
    const data = await resp.json();
    buildModelMenu(data.models || FALLBACK_MODELS);
  } catch {
    buildModelMenu(FALLBACK_MODELS);
  }
})();

function toggleModelMenu() {
  const open = modelMenu.style.display !== "none";
  if (open) {
    closeModelMenu();
  } else {
    modelMenu.style.display = "block";
    modelToggle.setAttribute("aria-expanded", "true");
  }
}

function closeModelMenu() {
  modelMenu.style.display = "none";
  modelToggle.setAttribute("aria-expanded", "false");
}

modelToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleModelMenu();
});

document.addEventListener("click", (e) => {
  if (!modelMenu.contains(e.target) && e.target !== modelToggle) {
    closeModelMenu();
  }
});


input.addEventListener("input", autoResize);
function autoResize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 200) + "px";
}

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

bindSuggestions();
function bindSuggestions() {
  document.querySelectorAll(".suggest").forEach((btn) => {
    btn.addEventListener("click", () => {
      const text = btn.querySelector(".s-text")?.textContent || btn.textContent;
      input.value = text.trim();
      autoResize();
      form.requestSubmit();
    });
  });
}

newChatBtn.addEventListener("click", () => {
  if (streaming) return;
  resetToWelcome();
});

function resetToWelcome() {
  messagesEl.innerHTML = WELCOME_HTML;
  bindSuggestions();
  activeHistoryId = null;
  refreshHistoryUI();
  input.focus();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (streaming) return;
  const query = input.value.trim();
  if (!query) return;

  const welcome = messagesEl.querySelector(".welcome");
  if (welcome) welcome.remove();

  appendUserMessage(query);
  recordHistory(query);
  input.value = "";
  input.style.height = "auto";

  const assistantNodes = appendAssistantSkeleton();
  await streamAnswer(query, assistantNodes);
});

function appendUserMessage(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="avatar" aria-hidden="true">SV</div><div class="bubble"></div>`;
  el.querySelector(".bubble").textContent = text;
  messagesEl.appendChild(el);
  scrollToBottom();
}

function appendAssistantSkeleton() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.innerHTML = `
    <div class="avatar" aria-hidden="true">AI</div>
    <div class="bubble">
      <div class="status" data-role="status">Đang tìm kiếm quy định liên quan</div>
      <div class="answer cursor" data-role="answer"></div>
      <div class="citations" data-role="citations" style="display:none;"></div>
    </div>`;
  messagesEl.appendChild(wrap);
  scrollToBottom();
  return {
    status: wrap.querySelector('[data-role="status"]'),
    answer: wrap.querySelector('[data-role="answer"]'),
    citations: wrap.querySelector('[data-role="citations"]'),
  };
}

async function streamAnswer(query, nodes) {
  streaming = true;
  sendBtn.disabled = true;

  let rawText = "";

  try {
    const resp = await fetch(`${API_BASE}/chat/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ query, top_k: 7, fetch_k: 12, decompose: true, model: selectedModel }),
    });

    if (!resp.ok || !resp.body) {
      throw new Error(`HTTP ${resp.status}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const event = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const line = event.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const data = line.slice(5).trim();
        if (!data) continue;
        let msg;
        try { msg = JSON.parse(data); } catch { continue; }

        if (msg.type === "status") {
          const subs = msg.sub_queries || [];
          if (subs.length > 1) {
            nodes.status.textContent = `Đã phân tích thành ${subs.length} câu truy vấn — đang truy xuất`;
          }
        } else if (msg.type === "citations") {
          renderCitations(nodes.citations, msg.citations || []);
          nodes.status.textContent = "Đang soạn câu trả lời";
        } else if (msg.type === "token") {
          if (nodes.status.parentNode) {
            nodes.status.style.display = "none";
          }
          rawText += msg.text;
          nodes.answer.innerHTML = marked.parse(rawText);
          scrollToBottom();
        } else if (msg.type === "error") {
          nodes.answer.innerHTML = `<em>Lỗi: ${escapeHtml(msg.message)}</em>`;
        } else if (msg.type === "done") {
          // stream over
        }
      }
    }
  } catch (err) {
    nodes.answer.innerHTML = `<em>Không thể kết nối máy chủ: ${escapeHtml(err.message)}</em>`;
  } finally {
    nodes.answer.classList.remove("cursor");
    streaming = false;
    sendBtn.disabled = false;
    scrollToBottom();
  }
}

function renderCitations(container, citations) {
  if (!citations.length) {
    container.style.display = "none";
    return;
  }
  container.style.display = "block";
  const items = citations.map((c) => {
    const locParts = [c.chapter, c.article, c.table_label, c.appendix].filter(Boolean);
    const loc = locParts.length ? locParts.join(" · ") : "";
    return `
      <div class="citation-item">
        <div class="src">[${c.index}] ${escapeHtml(c.document || "Tài liệu")}</div>
        ${loc ? `<div class="loc">${escapeHtml(loc)}</div>` : ""}
      </div>`;
  }).join("");
  container.innerHTML = `<h4>Nguồn tham khảo</h4>${items}`;
}

function recordHistory(query) {
  if (!activeHistoryId) {
    activeHistoryId = `c-${Date.now()}`;
    history.unshift({ id: activeHistoryId, title: truncate(query, 48) });
    refreshHistoryUI();
  }
}

function refreshHistoryUI() {
  if (!historyList) return;
  if (!history.length) {
    historyList.innerHTML = `<li class="history-empty">Chưa có cuộc trò chuyện nào.</li>`;
    return;
  }
  historyList.innerHTML = history
    .map((h) => `<li><button type="button" class="history-item ${h.id === activeHistoryId ? "active" : ""}" data-id="${h.id}" title="${escapeHtml(h.title)}">${escapeHtml(h.title)}</button></li>`)
    .join("");
}

function truncate(s, n) {
  s = String(s).trim();
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
