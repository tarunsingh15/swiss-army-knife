/**
 * Email Parser UI — upload, live processing, results browsing.
 * All email-derived text is set via textContent (never innerHTML).
 */
(function () {
  "use strict";

  /** @typedef {'upload' | 'processing' | 'results'} AppState */
  /** @typedef {'pending' | 'running' | 'ok' | 'warning' | 'failed'} ItemStatus */

  /**
   * @typedef {Object} MessageItem
   * @property {string} id
   * @property {File} file
   * @property {string} containerName
   * @property {number} messageIndex
   * @property {string} sender
   * @property {string} date
   * @property {string} subject
   * @property {ItemStatus} status
   * @property {string|null} docId
   * @property {number} jobIndex
   */

  const $ = (sel) => document.querySelector(sel);

  const stateUpload = $("#state-upload");
  const stateProcessing = $("#state-processing");
  const stateResults = $("#state-results");
  const dropzone = $("#dropzone");
  const fileInput = $("#file-input");
  const fileList = $("#file-list");
  const fileListEmpty = $("#file-list-empty");
  const processingList = $("#processing-list");
  const btnClear = $("#btn-clear");
  const btnSubmit = $("#btn-submit");
  const btnCancel = $("#btn-cancel");
  const btnGolden = $("#btn-golden");
  const progressText = $("#progress-text");
  const progressFill = $("#progress-fill");
  const jobIdLabel = $("#job-id-label");
  const emailList = $("#email-list");
  const detail = $("#detail");
  const breadcrumb = $("#breadcrumb");
  const metricsView = $("#metrics-view");
  const toast = $("#toast");

  /** @type {MessageItem[]} */
  let messages = [];
  /** @type {string|null} */
  let currentJobId = null;
  /** @type {EventSource|null} */
  let eventSource = null;
  /** @type {boolean} */
  let serverContainerized = false;
  /** @type {string|null} */
  let selectedEmailDocId = null;
  /** @type {{ docId: string, label: string }[]} */
  let detailStack = [];

  /**
   * Create a DOM element with optional class and text content.
   * @param {string} tag
   * @param {string|null} className
   * @param {string|null} text
   * @returns {HTMLElement}
   */
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  /**
   * Remove all child nodes from an element.
   * @param {HTMLElement} parent
   */
  function clear(parent) {
    while (parent.firstChild) parent.removeChild(parent.firstChild);
  }

  /**
   * Show a short toast message.
   * @param {string} message
   */
  function showToast(message) {
    toast.textContent = message;
    toast.classList.remove("hidden");
    window.setTimeout(() => toast.classList.add("hidden"), 3200);
  }

  /**
   * Switch visible UI state panel.
   * @param {AppState} next
   */
  function setAppState(next) {
    stateUpload.classList.toggle("hidden", next !== "upload");
    stateProcessing.classList.toggle("hidden", next !== "processing");
    stateResults.classList.toggle("hidden", next !== "results");
  }

  /**
   * Generate a unique id for a message row.
   * @returns {string}
   */
  function uid() {
    return "msg-" + Math.random().toString(36).slice(2, 10);
  }

  /**
   * Return file extension lowercased.
   * @param {string} name
   * @returns {string}
   */
  function ext(name) {
    const dot = name.lastIndexOf(".");
    return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
  }

  /**
   * Format PostalMime address object to a display string.
   * @param {object|null|undefined} addr
   * @returns {string}
   */
  function formatAddress(addr) {
    if (!addr) return "(unknown sender)";
    const name = addr.name || addr.address || "";
    const address = addr.address || "";
    if (name && address && name !== address) return name + " <" + address + ">";
    return name || address || "(unknown sender)";
  }

  /**
   * Parse one .eml file client-side with PostalMime.
   * @param {File} file
   * @returns {Promise<{sender: string, date: string, subject: string}>}
   */
  async function peekEmlClient(file) {
    const buffer = await file.arrayBuffer();
    const PostalMime = window.PostalMime;
    if (!PostalMime) throw new Error("PostalMime not loaded");
    const parser = new PostalMime();
    const parsed = await parser.parse(buffer);
    return {
      sender: formatAddress(parsed.from),
      date: parsed.date || "",
      subject: parsed.subject || "(no subject)",
    };
  }

  /**
   * Server-side header peek for non-.eml files.
   * @param {File} file
   * @returns {Promise<{sender: string, date: string, subject: string}[]>}
   */
  async function peekServer(file) {
    const form = new FormData();
    form.append("files", file);
    const resp = await fetch("/peek", { method: "POST", body: form });
    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(errText || "Peek failed (" + resp.status + ")");
    }
    const data = await resp.json();
    if (!Array.isArray(data)) return [];
    return data.map((row) => ({
      sender: row.sender || row.from || "(unknown sender)",
      date: row.date || "",
      subject: row.subject || "(no subject)",
    }));
  }

  /**
   * Add message items from one uploaded file.
   * @param {File} file
   */
  async function addFile(file) {
    const extension = ext(file.name);
    try {
      if (extension === "eml") {
        const header = await peekEmlClient(file);
        messages.push({
          id: uid(),
          file,
          containerName: file.name,
          messageIndex: 0,
          sender: header.sender,
          date: header.date,
          subject: header.subject,
          status: "pending",
          docId: null,
          jobIndex: messages.length,
        });
      } else {
        const headers = await peekServer(file);
        if (headers.length === 0) {
          messages.push({
            id: uid(),
            file,
            containerName: file.name,
            messageIndex: 0,
            sender: "(peek unavailable)",
            date: "",
            subject: file.name,
            status: "pending",
            docId: null,
            jobIndex: messages.length,
          });
        } else {
          headers.forEach((header, idx) => {
            messages.push({
              id: uid(),
              file,
              containerName: file.name,
              messageIndex: idx,
              sender: header.sender,
              date: header.date,
              subject: header.subject,
              status: "pending",
              docId: null,
              jobIndex: messages.length,
            });
          });
        }
      }
    } catch (err) {
      messages.push({
        id: uid(),
        file,
        containerName: file.name,
        messageIndex: 0,
        sender: "(parse error)",
        date: "",
        subject: String(err instanceof Error ? err.message : err),
        status: "pending",
        docId: null,
        jobIndex: messages.length,
      });
    }
    renderMessageList(fileList, messages, false);
    updateUploadControls();
  }

  /**
   * Handle multiple dropped or selected files.
   * @param {FileList|File[]} files
   */
  async function handleFiles(files) {
    for (const file of files) {
      await addFile(file);
    }
  }

  /**
   * Build one message row element.
   * @param {MessageItem} item
   * @param {boolean} showStatus
   * @returns {HTMLElement}
   */
  function buildMessageRow(item, showStatus) {
    const row = el("div", "message-row");
    const header = el("div", "row-header");
    if (showStatus) header.appendChild(el("span", "badge " + item.status, item.status));
    header.appendChild(el("span", "sender", item.sender));
    header.appendChild(el("span", "date", item.date));
    row.appendChild(header);
    row.appendChild(el("div", "subject", item.subject));
    if (item.containerName !== item.file.name || item.messageIndex > 0) {
      row.appendChild(el("div", "filename", item.containerName));
    }
    return row;
  }

  /**
   * Render the upload or processing message list, grouping .mbox containers.
   * @param {HTMLElement} container
   * @param {MessageItem[]} items
   * @param {boolean} showStatus
   */
  function renderMessageList(container, items, showStatus) {
    clear(container);
    if (items.length === 0) {
      fileListEmpty.classList.remove("hidden");
      return;
    }
    fileListEmpty.classList.add("hidden");

    /** @type {Map<string, MessageItem[]>} */
    const groups = new Map();
    const singles = [];

    items.forEach((item) => {
      const isMulti = ext(item.containerName) === "mbox" && items.filter((m) => m.containerName === item.containerName).length > 1;
      if (isMulti) {
        if (!groups.has(item.containerName)) groups.set(item.containerName, []);
        groups.get(item.containerName).push(item);
      } else {
        singles.push(item);
      }
    });

    singles.forEach((item) => container.appendChild(buildMessageRow(item, showStatus)));

    groups.forEach((groupItems, name) => {
      const details = el("details", "container-group");
      details.open = true;
      const summary = el("summary", null, name + " (" + groupItems.length + " messages)");
      details.appendChild(summary);
      const inner = el("div", "group-messages");
      groupItems.forEach((item) => inner.appendChild(buildMessageRow(item, showStatus)));
      details.appendChild(inner);
      container.appendChild(details);
    });
  }

  /**
   * Enable or disable upload action buttons.
   */
  function updateUploadControls() {
    const hasItems = messages.length > 0;
    btnClear.disabled = !hasItems;
    btnSubmit.disabled = !hasItems;
  }

  /**
   * Update progress bar and counter.
   * @param {number} done
   * @param {number} total
   */
  function updateProgress(done, total) {
    progressText.textContent = done + " / " + total;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    progressFill.style.width = pct + "%";
  }

  /**
   * Set location hash for job reattachment.
   * @param {string} jobId
   */
  function setJobHash(jobId) {
    location.hash = "job/" + jobId;
  }

  /**
   * Parse job id from location hash.
   * @returns {string|null}
   */
  function jobIdFromHash() {
    const match = location.hash.match(/^#job\/([^/?#]+)/);
    return match ? match[1] : null;
  }

  /**
   * Close SSE connection if open.
   */
  function closeEventSource() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  /**
   * Apply one SSE event payload to message statuses.
   * @param {object} evt
   */
  function applyJobEvent(evt) {
    const type = evt.type || evt.event || evt.kind || "";
    const index = evt.index ?? evt.file_index ?? evt.item_index;
    const status = evt.status;
    const docId = evt.doc_id || evt.docId;

    if (typeof index === "number" && messages[index]) {
      if (type.includes("start") || type === "running") {
        messages[index].status = "running";
      }
      if (status) {
        const normalized = String(status).toLowerCase();
        if (["ok", "warning", "failed", "pending", "running"].includes(normalized)) {
          messages[index].status = /** @type {ItemStatus} */ (normalized);
        }
      }
      if (docId) messages[index].docId = docId;
    }

    if (type === "progress" || evt.done != null) {
      const done = evt.done ?? evt.completed ?? 0;
      const total = evt.total ?? messages.length;
      updateProgress(done, total);
    }

    if (type === "job_done" || type === "complete" || type === "finished") {
      closeEventSource();
      enterResults(currentJobId);
    }

    renderMessageList(processingList, messages, true);
  }

  /**
   * Subscribe to job SSE stream; fall back to polling if EventSource fails.
   * @param {string} jobId
   */
  function subscribeJobEvents(jobId) {
    closeEventSource();
    const url = "/jobs/" + encodeURIComponent(jobId) + "/events";

    try {
      eventSource = new EventSource(url);
      eventSource.onmessage = (ev) => {
        try {
          applyJobEvent(JSON.parse(ev.data));
        } catch {
          applyJobEvent({ type: "message", raw: ev.data });
        }
      };
      eventSource.addEventListener("progress", (ev) => {
        try {
          applyJobEvent(Object.assign({ type: "progress" }, JSON.parse(ev.data)));
        } catch { /* ignore malformed */ }
      });
      eventSource.addEventListener("item", (ev) => {
        try {
          applyJobEvent(JSON.parse(ev.data));
        } catch { /* ignore malformed */ }
      });
      eventSource.addEventListener("done", () => {
        closeEventSource();
        enterResults(jobId);
      });
      eventSource.onerror = () => {
        closeEventSource();
        pollJobEvents(jobId);
      };
    } catch {
      pollJobEvents(jobId);
    }
  }

  /**
   * Poll job events when EventSource is unavailable.
   * @param {string} jobId
   */
  async function pollJobEvents(jobId) {
    let finished = false;
    while (!finished && currentJobId === jobId) {
      try {
        const resp = await fetch("/jobs/" + encodeURIComponent(jobId) + "/events");
        if (resp.ok) {
          const text = await resp.text();
          text.split("\n").forEach((line) => {
            if (line.startsWith("data:")) {
              const payload = line.slice(5).trim();
              if (payload) {
                try {
                  applyJobEvent(JSON.parse(payload));
                } catch { /* ignore */ }
              }
            }
          });
        }
        const statusResp = await fetch("/jobs/" + encodeURIComponent(jobId));
        if (statusResp.ok) {
          const job = await statusResp.json();
          if (job.status === "complete" || job.status === "done" || job.finished) {
            finished = true;
            enterResults(jobId);
          }
        }
      } catch { /* retry */ }
      if (!finished) await new Promise((r) => setTimeout(r, 1200));
    }
  }

  /**
   * Submit files for parsing.
   */
  async function submitJob() {
    if (messages.length === 0) return;

    const form = new FormData();
    const seenFiles = new Set();
    messages.forEach((item) => {
      const key = item.file.name + ":" + item.file.size;
      if (!seenFiles.has(key)) {
        form.append("files", item.file);
        seenFiles.add(key);
      }
    });

    btnSubmit.disabled = true;
    try {
      const resp = await fetch("/jobs", { method: "POST", body: form });
      if (!resp.ok) throw new Error(await resp.text() || "Job submit failed");
      const data = await resp.json();
      const jobId = data.job_id || data.id;
      if (!jobId) throw new Error("No job_id in response");

      currentJobId = jobId;
      setJobHash(jobId);
      jobIdLabel.textContent = "Job: " + jobId;
      messages.forEach((m) => {
        m.status = "pending";
      });
      updateProgress(0, messages.length);
      renderMessageList(processingList, messages, true);
      setAppState("processing");
      subscribeJobEvents(jobId);
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err));
      btnSubmit.disabled = false;
    }
  }

  /**
   * Cancel the current job.
   */
  async function cancelJob() {
    if (!currentJobId) return;
    try {
      await fetch("/jobs/" + encodeURIComponent(currentJobId) + "/cancel", { method: "POST" });
      showToast("Cancel requested");
      closeEventSource();
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err));
    }
  }

  /**
   * Fetch server health for containerized flag.
   */
  async function loadHealth() {
    try {
      const resp = await fetch("/health");
      if (resp.ok) {
        const data = await resp.json();
        serverContainerized = Boolean(data.containerized);
      }
    } catch {
      serverContainerized = false;
    }
  }

  /**
   * Transition to results state and load email list + metrics.
   * @param {string} jobId
   */
  async function enterResults(jobId) {
    currentJobId = jobId;
    setJobHash(jobId);
    setAppState("results");
    await loadEmailList(jobId);
    await loadJobMetrics(jobId);
  }

  /**
   * Load processed email list for a job.
   * @param {string} jobId
   */
  async function loadEmailList(jobId) {
    clear(emailList);
    try {
      const resp = await fetch("/jobs/" + encodeURIComponent(jobId) + "/emails");
      if (!resp.ok) throw new Error("Failed to load emails");
      const emails = await resp.json();
      if (!Array.isArray(emails) || emails.length === 0) {
        emailList.appendChild(el("p", "empty-hint", "No processed emails yet."));
        return;
      }
      emails.forEach((row) => {
        const docId = row.doc_id || row.docId;
        const item = el("div", "email-row");
        if (docId === selectedEmailDocId) item.classList.add("selected");
        const header = el("div", "row-header");
        const badgeStatus = (row.status || "ok").toLowerCase();
        header.appendChild(el("span", "badge " + badgeStatus, badgeStatus));
        header.appendChild(el("span", "sender", row.sender || "(unknown)"));
        header.appendChild(el("span", "date", row.date || ""));
        item.appendChild(header);
        item.appendChild(el("div", "subject", row.subject || "(no subject)"));
        const meta = el("div", "filename", "");
        meta.textContent = (row.attachment_count != null ? row.attachment_count + " attachments" : "");
        item.appendChild(meta);
        item.addEventListener("click", () => {
          selectedEmailDocId = docId;
          detailStack = [];
          loadDetail(docId, row.subject || docId);
          document.querySelectorAll(".email-row").forEach((n) => n.classList.remove("selected"));
          item.classList.add("selected");
        });
        emailList.appendChild(item);
      });
    } catch (err) {
      emailList.appendChild(el("p", "empty-hint", err instanceof Error ? err.message : String(err)));
    }
  }

  /**
   * Load and display job metrics.
   * @param {string} jobId
   */
  async function loadJobMetrics(jobId) {
    try {
      const resp = await fetch("/jobs/" + encodeURIComponent(jobId));
      if (!resp.ok) {
        metricsView.textContent = "(metrics unavailable)";
        return;
      }
      const data = await resp.json();
      const metrics = data.metrics || data;
      metricsView.textContent = JSON.stringify(metrics, null, 2);
    } catch {
      metricsView.textContent = "(metrics unavailable)";
    }
  }

  /**
   * Run golden corpus job and show returned metrics.
   */
  async function runGoldenCorpus() {
    btnGolden.disabled = true;
    try {
      const resp = await fetch("/jobs/golden", { method: "POST" });
      if (!resp.ok) throw new Error(await resp.text() || "Golden run failed");
      const data = await resp.json();
      metricsView.textContent = JSON.stringify(data.metrics || data, null, 2);
      showToast("Golden corpus complete");
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err));
    } finally {
      btnGolden.disabled = false;
    }
  }

  /**
   * Render breadcrumb navigation for detail drill-down.
   */
  function renderBreadcrumb() {
    clear(breadcrumb);
    if (detailStack.length === 0) {
      breadcrumb.classList.add("hidden");
      return;
    }
    breadcrumb.classList.remove("hidden");
    detailStack.forEach((crumb, idx) => {
      if (idx > 0) breadcrumb.appendChild(el("span", "sep", "›"));
      const btn = el("button", null, crumb.label);
      btn.addEventListener("click", () => {
        detailStack = detailStack.slice(0, idx + 1);
        loadDetail(crumb.docId, crumb.label, false);
      });
      breadcrumb.appendChild(btn);
    });
  }

  /**
   * Format recipient list from native metadata.
   * @param {object[]} entries
   * @returns {string}
   */
  function formatRecipients(entries) {
    if (!entries || !entries.length) return "";
    return entries
      .map((e) => {
        const name = e.name || "";
        const addr = e.addr || e.address || "";
        if (name && addr) return name + " <" + addr + ">";
        return name || addr;
      })
      .join(", ");
  }

  /**
   * Load document detail view.
   * @param {string} docId
   * @param {string} label
   * @param {boolean} pushStack
   */
  async function loadDetail(docId, label, pushStack = true) {
    if (pushStack) {
      const existing = detailStack.findIndex((c) => c.docId === docId);
      if (existing >= 0) {
        detailStack = detailStack.slice(0, existing + 1);
      } else {
        detailStack.push({ docId, label });
      }
    }
    renderBreadcrumb();
    clear(detail);
    detail.appendChild(el("p", "empty-hint", "Loading…"));

    try {
      const [detailResp, contextResp] = await Promise.all([
        fetch("/documents/" + encodeURIComponent(docId) + "/detail"),
        fetch("/documents/" + encodeURIComponent(docId) + "/context"),
      ]);
      if (!detailResp.ok) throw new Error("Detail load failed");
      const payload = await detailResp.json();
      const doc = payload.document || payload;
      const children = payload.children || [];
      const storagePaths = payload.storage_paths || payload.storagePaths || {};

      clear(detail);
      detail.appendChild(buildHeaderCard(doc));
      detail.appendChild(buildBodyPreview(doc));
      detail.appendChild(await buildPreviewColumns(doc, contextResp));
      detail.appendChild(buildAttachmentsTable(children, doc.doc_id || docId));
    } catch (err) {
      clear(detail);
      detail.appendChild(el("p", "empty-hint", err instanceof Error ? err.message : String(err)));
    }
  }

  /**
   * Build header card for document metadata.
   * @param {object} doc
   * @returns {HTMLElement}
   */
  function buildHeaderCard(doc) {
    const native = (doc.metadata && doc.metadata.native) || {};
    const card = el("div", "detail-card");
    card.appendChild(el("h3", null, "Header"));
    const grid = el("dl", "field-grid");
    const addField = (label, value) => {
      grid.appendChild(el("dt", null, label));
      grid.appendChild(el("dd", null, value || "—"));
    };
    const fromParts = [];
    if (native.from_name) fromParts.push(native.from_name);
    if (native.from_addr) fromParts.push("<" + native.from_addr + ">");
    addField("From", fromParts.join(" ") || native.from_addr);
    addField("To", formatRecipients(native.to));
    addField("Cc", formatRecipients(native.cc));
    addField("Date", native.date_original || native.date_utc || "");
    addField("Subject", native.subject || (doc.metadata && doc.metadata.common && doc.metadata.common.title));
    addField("Message-ID", native.message_id || "");
    card.appendChild(grid);
    return card;
  }

  /**
   * Build body preview with quoted/signature toggle.
   * @param {object} doc
   * @returns {HTMLElement}
   */
  function buildBodyPreview(doc) {
    const section = el("div", "body-preview");
    section.appendChild(el("h3", null, "Body preview"));
    const toggleLabel = el("label", "body-toggle");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "show-quoted";
    toggleLabel.appendChild(checkbox);
    toggleLabel.appendChild(document.createTextNode(" Show quoted / signature"));
    section.appendChild(toggleLabel);

    const blocksEl = el("div", "body-blocks");
    const blocks = doc.blocks || [];

    const renderBlocks = () => {
      clear(blocksEl);
      const showQuoted = checkbox.checked;
      blocks.forEach((block) => {
        const type = block.type || "";
        if (!showQuoted && (type === "quoted_history" || type === "signature")) return;
        const text = block.text || "";
        if (!text && !(block.rows && block.rows.length)) return;
        const p = el("p", null, text);
        if (type === "quoted_history") p.classList.add("block-quoted");
        if (type === "signature") p.classList.add("block-signature");
        blocksEl.appendChild(p);
      });
      if (!blocksEl.childNodes.length) {
        blocksEl.appendChild(el("p", null, "(no body blocks)"));
      }
    };

    checkbox.addEventListener("change", renderBlocks);
    renderBlocks();
    section.appendChild(blocksEl);
    return section;
  }

  /**
   * Build JSON and context preview columns.
   * @param {object} doc
   * @param {Response} contextResp
   * @returns {Promise<HTMLElement>}
   */
  async function buildPreviewColumns(doc, contextResp) {
    const wrap = el("div", "preview-columns");

    const jsonPanel = el("div", "preview-panel");
    jsonPanel.appendChild(el("h3", null, "Document JSON"));
    const jsonBody = el("div", "preview-body");
    const jsonView = el("div", null);
    jsonView.id = "json-view";
    if (window.renderjson) {
      window.renderjson.set_show_to_level(2);
      jsonView.appendChild(window.renderjson(doc));
    } else {
      jsonView.textContent = JSON.stringify(doc, null, 2);
    }
    jsonBody.appendChild(jsonView);
    jsonPanel.appendChild(jsonBody);
    wrap.appendChild(jsonPanel);

    const ctxPanel = el("div", "preview-panel");
    ctxPanel.appendChild(el("h3", null, "Context view"));
    const ctxBody = el("div", "preview-body");
    const ctxPre = el("pre", null);
    ctxPre.id = "context-view";
    if (contextResp.ok) {
      const contentType = contextResp.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const ctxData = await contextResp.json();
        ctxPre.textContent = ctxData.markdown || ctxData.context || ctxData.text || JSON.stringify(ctxData, null, 2);
      } else {
        ctxPre.textContent = await contextResp.text();
      }
    } else {
      ctxPre.textContent = "(context unavailable)";
    }
    ctxBody.appendChild(ctxPre);
    ctxPanel.appendChild(ctxBody);
    wrap.appendChild(ctxPanel);

    return wrap;
  }

  /**
   * Copy text to clipboard.
   * @param {string} text
   */
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      showToast("Copied to clipboard");
    } catch {
      showToast("Copy failed");
    }
  }

  /**
   * POST reveal file in Finder (desktop only).
   * @param {string} docId
   */
  async function revealFile(docId) {
    try {
      const resp = await fetch("/files/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_id: docId }),
      });
      if (!resp.ok) showToast(await resp.text() || "Reveal failed");
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err));
    }
  }

  /**
   * Build attachments table with drill-down and file actions.
   * @param {object[]} children
   * @param {string} parentDocId
   * @returns {HTMLElement}
   */
  function buildAttachmentsTable(children, parentDocId) {
    const section = el("div", "attachments-section");
    section.appendChild(el("h3", null, "Attachments"));
    if (!children || children.length === 0) {
      section.appendChild(el("p", "empty-hint", "No attachments."));
      return section;
    }

    const wrap = el("div", "attachments-table-wrap");
    const table = el("table", "attachments-table");
    const thead = el("thead");
    const headRow = el("tr");
    ["Ord", "Filename", "MIME", "Relation", "Depth", "Size", "Pages", "Status", "Path / Actions"].forEach((h) => {
      headRow.appendChild(el("th", null, h));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = el("tbody");
    const sorted = [...children].sort((a, b) => (a.ordinal || 0) - (b.ordinal || 0));

    sorted.forEach((child) => {
      const docId = child.doc_id || child.docId;
      const meta = child.metadata || {};
      const common = meta.common || child;
      const filename = common.filename || child.filename || "—";
      const mime = child.mime_type || child.mime || "—";
      const relation = child.relation_to_parent || child.relation || "—";
      const depth = child.depth != null ? child.depth : 0;
      const byteSize = common.byte_size != null ? common.byte_size : child.byte_size;
      const pageCount = common.page_count != null ? common.page_count : child.page_count;
      const status = (child.provenance && child.provenance.status) || child.status || "—";
      const paths = child.storage_paths || child.storagePaths || {};
      const displayPath = paths.display_blob || paths.displayBlob || "";

      const tr = el("tr", "clickable depth-" + Math.min(depth, 3));
      tr.appendChild(el("td", null, String(child.ordinal != null ? child.ordinal : "")));
      tr.appendChild(el("td", null, filename));
      tr.appendChild(el("td", null, mime));
      tr.appendChild(el("td", null, String(relation)));
      tr.appendChild(el("td", null, String(depth)));
      tr.appendChild(el("td", null, byteSize != null ? String(byteSize) : "—"));
      tr.appendChild(el("td", null, pageCount != null ? String(pageCount) : "—"));
      tr.appendChild(el("td", null, String(status)));

      const actionsCell = el("td");
      const pathCell = el("div", "path-cell");
      const code = el("code", null, displayPath);
      pathCell.appendChild(code);
      const copyBtn = el("button", "btn small", "Copy");
      copyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        copyText(displayPath);
      });
      pathCell.appendChild(copyBtn);
      actionsCell.appendChild(pathCell);

      const links = el("div", "action-links");
      const openFile = el("a", "btn small", "Open file");
      openFile.href = "/files/blob/" + encodeURIComponent(docId);
      openFile.target = "_blank";
      openFile.rel = "noopener";
      links.appendChild(openFile);

      const openJson = el("a", "btn small", "Open JSON");
      openJson.href = "/files/json/" + encodeURIComponent(docId);
      openJson.target = "_blank";
      openJson.rel = "noopener";
      links.appendChild(openJson);

      if (!serverContainerized) {
        const revealBtn = el("button", "btn small", "Reveal");
        revealBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          revealFile(docId);
        });
        links.appendChild(revealBtn);
      }

      actionsCell.appendChild(links);
      tr.appendChild(actionsCell);

      tr.addEventListener("click", () => {
        loadDetail(docId, filename);
      });

      tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    wrap.appendChild(table);
    section.appendChild(wrap);
    return section;
  }

  /**
   * Reattach to an in-progress or completed job from URL hash.
   * @param {string} jobId
   */
  async function reattachJob(jobId) {
    currentJobId = jobId;
    jobIdLabel.textContent = "Job: " + jobId;
    try {
      const resp = await fetch("/jobs/" + encodeURIComponent(jobId));
      if (!resp.ok) return;
      const job = await resp.json();
      if (job.status === "complete" || job.status === "done" || job.finished) {
        await enterResults(jobId);
      } else {
        setAppState("processing");
        updateProgress(job.completed || 0, job.total || messages.length || 1);
        subscribeJobEvents(jobId);
      }
    } catch {
      setAppState("processing");
      subscribeJobEvents(jobId);
    }
  }

  /**
   * Clear all queued messages.
   */
  function clearMessages() {
    messages = [];
    renderMessageList(fileList, messages, false);
    updateUploadControls();
  }

  /* --- Event wiring --- */

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer && e.dataTransfer.files.length) {
      handleFiles(e.dataTransfer.files);
    }
  });
  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files) handleFiles(fileInput.files);
    fileInput.value = "";
  });

  btnClear.addEventListener("click", clearMessages);
  btnSubmit.addEventListener("click", submitJob);
  btnCancel.addEventListener("click", cancelJob);
  btnGolden.addEventListener("click", runGoldenCorpus);

  window.addEventListener("hashchange", () => {
    const id = jobIdFromHash();
    if (id && id !== currentJobId) reattachJob(id);
  });

  /* --- Init --- */
  loadHealth();
  const hashJob = jobIdFromHash();
  if (hashJob) reattachJob(hashJob);
})();
