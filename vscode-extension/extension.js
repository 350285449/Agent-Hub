"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");

let serverProcess = null;
let output;
let chatPanel = null;

function activate(context) {
  output = vscode.window.createOutputChannel("Agent Hub");
  context.subscriptions.push(output);

  context.subscriptions.push(
    vscode.commands.registerCommand("agentHub.chat", () => openChat(context)),
    vscode.commands.registerCommand("agentHub.startServer", startServer),
    vscode.commands.registerCommand("agentHub.stopServer", stopServer),
    vscode.commands.registerCommand("agentHub.status", showStatus),
    vscode.commands.registerCommand("agentHub.ask", askAgent),
    vscode.commands.registerCommand("agentHub.codeAgent", runCodingAgent),
    vscode.commands.registerCommand("agentHub.research", researchWeb),
    vscode.commands.registerCommand("agentHub.explainSelection", explainSelection),
    vscode.commands.registerCommand("agentHub.explainFile", explainFile),
    vscode.commands.registerCommand("agentHub.openOutput", () => output.show())
  );
}

function deactivate() {
  stopServerProcess();
}

function openChat(context) {
  if (chatPanel) {
    chatPanel.reveal(vscode.ViewColumn.Beside);
    return;
  }

  chatPanel = vscode.window.createWebviewPanel(
    "agentHubCodexChat",
    "Agent Hub Codex Chat",
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      retainContextWhenHidden: true
    }
  );

  chatPanel.webview.html = chatHtml();
  chatPanel.onDidDispose(() => {
    chatPanel = null;
  });
  chatPanel.webview.onDidReceiveMessage(
    (message) => handleChatMessage(chatPanel, message),
    undefined,
    context.subscriptions
  );
}

async function handleChatMessage(panel, message) {
  if (!panel || !message || typeof message !== "object") {
    return;
  }

  if (message.type === "ready" || message.type === "status") {
    const online = await isServerOnline();
    panel.webview.postMessage({
      type: "serverStatus",
      online,
      text: online ? "Agent Hub is online" : "Agent Hub is offline"
    });
    return;
  }

  if (message.type === "startServer") {
    await startServer();
    const online = await isServerOnline();
    panel.webview.postMessage({
      type: "serverStatus",
      online,
      text: online ? "Agent Hub is online" : "Agent Hub is offline"
    });
    return;
  }

  if (message.type === "send") {
    await sendChatTurn(panel, message);
  }
}

async function sendChatTurn(panel, message) {
  const text = typeof message.text === "string" ? message.text.trim() : "";
  if (!text) {
    return;
  }

  const requestId = message.requestId || `${Date.now()}`;
  panel.webview.postMessage({ type: "typing", requestId });

  if (!(await ensureServerReady())) {
    panel.webview.postMessage({
      type: "chatError",
      requestId,
      text: "Agent Hub is not running. Start the server or check the Agent Hub output."
    });
    return;
  }

  const config = settings();
  const workspace = workspaceRoot();
  const context = message.includeSelection ? selectedEditorContext() : "";
  const body = {
    session_id: message.sessionId || `vscode-chat-${Date.now()}`,
    mode: "agent",
    route: codingAgentRoute(config),
    task: codexChatTask(text),
    context,
    use_session_history: true,
    max_tokens: config.maxTokens,
    allow_shell_tools: config.allowShellTools,
    agent_max_steps: config.agentMaxSteps,
    workspace_dir: workspace || ".",
    metadata: {
      source: "vscode-codex-chat"
    }
  };

  output.appendLine("");
  output.appendLine(`[Codex Chat] ${text}`);
  try {
    const response = await requestJson("POST", "/v1/agent", body);
    const reply = responseText(response);
    output.appendLine(reply || "(empty response)");
    appendAgentTrace(response);
    appendResearchMetadata(response);
    panel.webview.postMessage({
      type: "chatResponse",
      requestId,
      text: reply || "(empty response)",
      tools: agentToolSteps(response),
      sources: sourceLines(response)
    });
  } catch (error) {
    output.appendLine(`Codex chat failed: ${error.message}`);
    panel.webview.postMessage({
      type: "chatError",
      requestId,
      text: error.message
    });
  }
}

function codexChatTask(text) {
  return [
    "Chat with the user as a careful Codex-style local coding assistant.",
    "Be conversational and concise. Use workspace tools when inspection or edits are useful.",
    "",
    text
  ].join("\n");
}

function responseText(response) {
  if (response && response.message && typeof response.message.content === "string") {
    return response.message.content;
  }
  return response ? JSON.stringify(response, null, 2) : "";
}

function agentToolSteps(response) {
  const metadata = response && response.agent_hub;
  if (!metadata || !Array.isArray(metadata.steps)) {
    return [];
  }
  return metadata.steps
    .filter((step) => step && typeof step === "object")
    .map((step) => {
      const result = step.result || {};
      return {
        step: step.step || "?",
        tool: step.tool || "unknown",
        ok: result.ok !== false,
        error: result.error || ""
      };
    });
}

function chatHtml() {
  const nonce = getNonce();
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Hub Codex Chat</title>
  <style nonce="${nonce}">
    :root {
      color-scheme: light dark;
      --border: var(--vscode-panel-border);
      --muted: var(--vscode-descriptionForeground);
      --input: var(--vscode-input-background);
      --input-border: var(--vscode-input-border);
      --button: var(--vscode-button-background);
      --button-fg: var(--vscode-button-foreground);
      --button-hover: var(--vscode-button-hoverBackground);
      --bubble: var(--vscode-editor-inactiveSelectionBackground);
      --error: var(--vscode-errorForeground);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
    }

    .shell {
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: 100vh;
      min-height: 420px;
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
    }

    h1 {
      margin: 0;
      font-size: 15px;
      font-weight: 600;
    }

    .status {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }

    .transcript {
      overflow-y: auto;
      padding: 14px;
    }

    .message {
      display: grid;
      gap: 6px;
      max-width: 920px;
      margin: 0 0 14px;
    }

    .message.user {
      margin-left: auto;
    }

    .role {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
    }

    .bubble {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: transparent;
    }

    .user .bubble {
      background: var(--bubble);
    }

    .error .bubble {
      color: var(--error);
    }

    details {
      color: var(--muted);
      font-size: 12px;
    }

    ul {
      margin: 6px 0 0;
      padding-left: 18px;
    }

    form {
      display: grid;
      gap: 8px;
      padding: 12px 14px 14px;
      border-top: 1px solid var(--border);
      background: var(--vscode-editor-background);
    }

    textarea {
      width: 100%;
      min-height: 84px;
      max-height: 220px;
      resize: vertical;
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 9px 10px;
      color: var(--vscode-input-foreground);
      background: var(--input);
      font: inherit;
      line-height: 1.45;
    }

    .actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }

    .left,
    .right {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    button {
      border: 0;
      border-radius: 6px;
      padding: 6px 10px;
      color: var(--button-fg);
      background: var(--button);
      font: inherit;
      cursor: pointer;
    }

    button:hover {
      background: var(--button-hover);
    }

    button.secondary {
      color: var(--vscode-button-secondaryForeground);
      background: var(--vscode-button-secondaryBackground);
    }

    button.secondary:hover {
      background: var(--vscode-button-secondaryHoverBackground);
    }

    button:disabled,
    textarea:disabled {
      opacity: 0.65;
      cursor: default;
    }

    label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      user-select: none;
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <h1>Codex Chat</h1>
      <div class="status" id="status">Checking Agent Hub...</div>
    </header>
    <main class="transcript" id="transcript" aria-live="polite"></main>
    <form id="form">
      <textarea id="prompt" placeholder="Ask Codex to inspect, explain, or change this workspace"></textarea>
      <div class="actions">
        <div class="left">
          <label><input id="includeSelection" type="checkbox"> Include selection</label>
          <button class="secondary" id="startServer" type="button">Start Server</button>
          <button class="secondary" id="checkStatus" type="button">Status</button>
          <button class="secondary" id="clear" type="button">Clear</button>
        </div>
        <div class="right">
          <button id="send" type="submit">Send</button>
        </div>
      </div>
    </form>
  </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const transcript = document.getElementById("transcript");
    const form = document.getElementById("form");
    const prompt = document.getElementById("prompt");
    const send = document.getElementById("send");
    const status = document.getElementById("status");
    const includeSelection = document.getElementById("includeSelection");
    const pending = new Map();
    let sessionId = "vscode-chat-" + Date.now().toString(36);

    function setBusy(value) {
      prompt.disabled = value;
      send.disabled = value;
    }

    function appendMessage(role, text, options = {}) {
      const item = document.createElement("section");
      item.className = "message " + role + (options.error ? " error" : "");

      const roleLabel = document.createElement("div");
      roleLabel.className = "role";
      roleLabel.textContent = role === "user" ? "You" : "Codex";

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;

      item.append(roleLabel, bubble);
      if (options.tools && options.tools.length) {
        item.append(detailsBlock("Tools", options.tools.map((tool) => {
          const status = tool.ok ? "ok" : "failed";
          return "#" + tool.step + " " + tool.tool + " (" + status + ")" + (tool.error ? ": " + tool.error : "");
        })));
      }
      if (options.sources && options.sources.length) {
        item.append(detailsBlock("Sources", options.sources));
      }
      transcript.append(item);
      transcript.scrollTop = transcript.scrollHeight;
      return item;
    }

    function detailsBlock(summaryText, lines) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      const list = document.createElement("ul");
      summary.textContent = summaryText;
      for (const line of lines) {
        const item = document.createElement("li");
        item.textContent = line;
        list.append(item);
      }
      details.append(summary, list);
      return details;
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = prompt.value.trim();
      if (!text) {
        return;
      }
      const requestId = Date.now().toString(36) + Math.random().toString(36).slice(2);
      appendMessage("user", text);
      pending.set(requestId, true);
      prompt.value = "";
      setBusy(true);
      status.textContent = "Codex is working...";
      vscode.postMessage({
        type: "send",
        requestId,
        sessionId,
        text,
        includeSelection: includeSelection.checked
      });
    });

    document.getElementById("startServer").addEventListener("click", () => {
      status.textContent = "Starting Agent Hub...";
      vscode.postMessage({ type: "startServer" });
    });

    document.getElementById("checkStatus").addEventListener("click", () => {
      status.textContent = "Checking Agent Hub...";
      vscode.postMessage({ type: "status" });
    });

    document.getElementById("clear").addEventListener("click", () => {
      transcript.textContent = "";
      sessionId = "vscode-chat-" + Date.now().toString(36);
      status.textContent = "Started a new chat";
      prompt.focus();
    });

    window.addEventListener("message", (event) => {
      const message = event.data;
      if (!message || typeof message !== "object") {
        return;
      }
      if (message.type === "serverStatus") {
        status.textContent = message.text;
        return;
      }
      if (message.type === "typing") {
        status.textContent = "Codex is working...";
        return;
      }
      if (message.type === "chatResponse") {
        pending.delete(message.requestId);
        appendMessage("assistant", message.text, {
          tools: message.tools || [],
          sources: message.sources || []
        });
        setBusy(false);
        status.textContent = "Ready";
        prompt.focus();
        return;
      }
      if (message.type === "chatError") {
        pending.delete(message.requestId);
        appendMessage("assistant", message.text, { error: true });
        setBusy(false);
        status.textContent = "Request failed";
        prompt.focus();
      }
    });

    prompt.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        form.requestSubmit();
      }
    });

    vscode.postMessage({ type: "ready" });
    prompt.focus();
  </script>
</body>
</html>`;
}

function getNonce() {
  let text = "";
  const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let index = 0; index < 32; index += 1) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

async function startServer() {
  if (await isServerOnline()) {
    vscode.window.showInformationMessage("Agent Hub is already running.");
    return;
  }
  if (serverProcess) {
    vscode.window.showInformationMessage("Agent Hub is starting.");
    return;
  }

  const workspace = workspaceRoot();
  if (!workspace) {
    vscode.window.showErrorMessage("Open a workspace folder before starting Agent Hub.");
    return;
  }

  const config = settings();
  const args = [
    "-m",
    "agent_hub",
    "--config",
    resolveConfigPath(config.configPath, workspace),
    "serve",
    "--watch-inbox"
  ];
  const url = new URL(config.serverUrl);
  if (url.hostname) {
    args.push("--host", url.hostname);
  }
  if (url.port) {
    args.push("--port", url.port);
  }

  output.appendLine(`Starting Agent Hub: ${config.pythonPath} ${args.join(" ")}`);
  serverProcess = cp.spawn(config.pythonPath, args, {
    cwd: workspace,
    shell: false
  });

  serverProcess.stdout.on("data", (data) => output.append(data.toString()));
  serverProcess.stderr.on("data", (data) => output.append(data.toString()));
  serverProcess.on("exit", (code) => {
    output.appendLine(`Agent Hub server exited with code ${code}.`);
    serverProcess = null;
  });
  serverProcess.on("error", (error) => {
    output.appendLine(`Failed to start Agent Hub: ${error.message}`);
    vscode.window.showErrorMessage(`Failed to start Agent Hub: ${error.message}`);
    serverProcess = null;
  });

  const online = await waitForServer(7000);
  if (online) {
    vscode.window.showInformationMessage(`Agent Hub started at ${config.serverUrl}.`);
  } else {
    output.show();
    vscode.window.showWarningMessage("Agent Hub did not respond yet. Check the Agent Hub output.");
  }
}

function stopServer() {
  if (stopServerProcess()) {
    vscode.window.showInformationMessage("Agent Hub server stopped.");
  } else {
    vscode.window.showInformationMessage("Agent Hub server was not started by this VS Code window.");
  }
}

function stopServerProcess() {
  if (!serverProcess) {
    return false;
  }
  const processToStop = serverProcess;
  serverProcess = null;
  processToStop.kill();
  return true;
}

async function showStatus() {
  try {
    const health = await requestJson("GET", "/health");
    const agents = Array.isArray(health.agents) ? health.agents.join(", ") : "unknown";
    const freeOnly = health.free_only === undefined ? "unknown" : String(health.free_only);
    vscode.window.showInformationMessage(`Agent Hub online. Agents: ${agents}. free_only: ${freeOnly}.`);
    output.appendLine(JSON.stringify(health, null, 2));
  } catch (error) {
    vscode.window.showWarningMessage(`Agent Hub is offline or unhealthy: ${error.message}`);
  }
}

async function askAgent() {
  const task = await vscode.window.showInputBox({
    title: "Ask Agent Hub",
    prompt: "What should the agent do?",
    ignoreFocusOut: true
  });
  if (!task) {
    return;
  }
  await sendAgentRequest({ task, context: editorContext({ preferSelection: true }) });
}

async function runCodingAgent() {
  const task = await vscode.window.showInputBox({
    title: "Run Local Coding Agent",
    prompt: "What should the local agent change or investigate in this workspace?",
    ignoreFocusOut: true
  });
  if (!task) {
    return;
  }
  const config = settings();
  const workspace = workspaceRoot();
  const route = codingAgentRoute(config);
  await sendAgentRequest({
    task: [
      "Work as a local coding agent in this workspace.",
      "Inspect files before editing, keep changes scoped, and verify if possible.",
      "",
      task
    ].join("\n"),
    context: selectedEditorContext(),
    route,
    agentMode: true,
    extra: {
      allow_shell_tools: config.allowShellTools,
      agent_max_steps: config.agentMaxSteps,
      workspace_dir: workspace || "."
    }
  });
}

async function researchWeb() {
  const query = await vscode.window.showInputBox({
    title: "Research with Agent Hub",
    prompt: "What should Agent Hub research?",
    ignoreFocusOut: true
  });
  if (!query) {
    return;
  }
  const config = settings();
  await sendAgentRequest({
    task: [
      "Answer this as a concise web research assistant.",
      "Use current sources, cite key claims, and include links when available.",
      "",
      query
    ].join("\n"),
    context: selectedEditorContext(),
    route: config.researchRoute,
    agentMode: false,
    extra: {
      query,
      max_sources: 5
    }
  });
}

async function explainSelection() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.selection.isEmpty) {
    vscode.window.showWarningMessage("Select some text first.");
    return;
  }
  const selected = editor.document.getText(editor.selection);
  await sendAgentRequest({
    task: "Explain this selected code or text clearly and point out anything important.",
    context: contextForDocument(editor.document, selected)
  });
}

async function explainFile() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("Open a file first.");
    return;
  }
  await sendAgentRequest({
    task: "Explain this file clearly. Describe what it does, important functions/classes, and any likely gotchas.",
    context: contextForDocument(editor.document, editor.document.getText())
  });
}

async function sendAgentRequest({ task, context, route, agentMode = true, extra = {} }) {
  const config = settings();
  if (!(await ensureServerReady())) {
    vscode.window.showErrorMessage("Agent Hub is not running. Use 'Agent Hub: Start Server' or check the output.");
    return;
  }

  const body = {
    ...extra,
    session_id: `vscode-${Date.now()}`,
    mode: agentMode ? "agent" : "route",
    route: route || config.route,
    task,
    context,
    max_tokens: config.maxTokens,
    metadata: {
      source: "vscode"
    }
  };

  output.show(true);
  output.appendLine("");
  output.appendLine(`> ${task}`);
  try {
    const response = await requestJson("POST", agentMode ? "/v1/agent" : "/v1/route", body);
    const text = response && response.message ? response.message.content : JSON.stringify(response, null, 2);
    output.appendLine("");
    output.appendLine(text || "(empty response)");
    appendAgentTrace(response);
    appendResearchMetadata(response);
    output.appendLine("");
    if (Array.isArray(response.failover) && response.failover.length) {
      output.appendLine("Failover:");
      for (const event of response.failover) {
        output.appendLine(`- ${event.agent}: ${event.reason}`);
      }
    }
  } catch (error) {
    output.appendLine(`Agent request failed: ${error.message}`);
    vscode.window.showErrorMessage(`Agent Hub request failed: ${error.message}`);
  }
}

async function ensureServerReady() {
  const config = settings();
  if (await isServerOnline()) {
    return true;
  }
  if (config.autoStart) {
    await startServer();
  }
  return isServerOnline();
}

function editorContext({ preferSelection }) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return "";
  }
  const text = preferSelection && !editor.selection.isEmpty
    ? editor.document.getText(editor.selection)
    : editor.document.getText();
  return contextForDocument(editor.document, text);
}

function selectedEditorContext() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.selection.isEmpty) {
    return "";
  }
  return contextForDocument(editor.document, editor.document.getText(editor.selection));
}

function contextForDocument(document, text) {
  const relative = vscode.workspace.asRelativePath(document.uri, false);
  const language = document.languageId || "plaintext";
  return [
    `File: ${relative}`,
    `Language: ${language}`,
    "",
    text
  ].join("\n");
}

function settings() {
  const config = vscode.workspace.getConfiguration("agentHub");
  return {
    serverUrl: config.get("serverUrl", "http://127.0.0.1:8787").replace(/\/+$/, ""),
    pythonPath: resolvePythonPath(config.get("pythonPath", "python")),
    configPath: config.get("configPath", "agent-hub.config.json"),
    route: config.get("route", "coding"),
    researchRoute: config.get("researchRoute", "research"),
    codingAgentRoute: config.get("codingAgentRoute", "local-agent"),
    agentProviderMode: config.get("agentProviderMode", "local"),
    agentMaxSteps: config.get("agentMaxSteps", 20),
    allowShellTools: config.get("allowShellTools", true),
    maxTokens: config.get("maxTokens", 1200),
    autoStart: config.get("autoStart", true)
  };
}

function resolvePythonPath(value) {
  if (value && value !== "python") {
    return value;
  }
  const workspace = workspaceRoot();
  if (!workspace) {
    return value || "python";
  }
  const candidates = [
    path.join(workspace, ".venv", "Scripts", "python.exe"),
    path.join(workspace, ".venv", "bin", "python")
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return value || "python";
}

function codingAgentRoute(config) {
  if (config.agentProviderMode === "cloud") {
    return "cloud-agent";
  }
  if (config.agentProviderMode === "hybrid") {
    return "hybrid-agent";
  }
  return config.codingAgentRoute || "local-agent";
}

function appendAgentTrace(response) {
  const metadata = response && response.agent_hub;
  if (!metadata || !Array.isArray(metadata.steps) || !metadata.steps.length) {
    return;
  }
  output.appendLine("");
  output.appendLine("Tools:");
  for (const step of metadata.steps) {
    if (!step || typeof step !== "object") {
      continue;
    }
    const tool = step.tool || "unknown";
    const result = step.result || {};
    const status = result.ok === false ? "failed" : "ok";
    output.appendLine(`- ${step.step || "?"}: ${tool} (${status})`);
    if (result.ok === false && result.error) {
      output.appendLine(`  ${result.error}`);
    }
  }
}

function appendResearchMetadata(response) {
  if (!response || typeof response !== "object") {
    return;
  }
  const sources = sourceLines(response);
  if (sources.length) {
    output.appendLine("");
    output.appendLine("Sources:");
    for (const line of sources) {
      output.appendLine(line);
    }
  }
  if (Array.isArray(response.related_questions) && response.related_questions.length) {
    output.appendLine("");
    output.appendLine("Related questions:");
    for (const question of response.related_questions) {
      if (typeof question === "string" && question.trim()) {
        output.appendLine(`- ${question}`);
      }
    }
  }
}

function sourceLines(response) {
  const seen = new Set();
  const lines = [];
  if (Array.isArray(response.search_results)) {
    for (const result of response.search_results) {
      if (!result || typeof result !== "object" || !result.url || seen.has(result.url)) {
        continue;
      }
      seen.add(result.url);
      const title = typeof result.title === "string" && result.title.trim()
        ? result.title.trim()
        : result.url;
      lines.push(`- ${title}: ${result.url}`);
    }
  }
  if (Array.isArray(response.citations)) {
    for (const url of response.citations) {
      if (typeof url !== "string" || !url.trim() || seen.has(url)) {
        continue;
      }
      seen.add(url);
      lines.push(`- ${url}`);
    }
  }
  return lines;
}

function workspaceRoot() {
  const folder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  return folder ? folder.uri.fsPath : undefined;
}

function resolveConfigPath(configPath, workspace) {
  if (path.isAbsolute(configPath)) {
    return configPath;
  }
  return path.join(workspace, configPath);
}

async function isServerOnline() {
  try {
    await requestJson("GET", "/health");
    return true;
  } catch (_error) {
    return false;
  }
}

async function waitForServer(timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isServerOnline()) {
      return true;
    }
    await delay(300);
  }
  return false;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function requestJson(method, pathname, body) {
  const config = settings();
  const url = new URL(pathname, config.serverUrl);
  const client = url.protocol === "https:" ? https : http;
  const data = body ? JSON.stringify(body) : undefined;

  return new Promise((resolve, reject) => {
    const request = client.request(
      url,
      {
        method,
        headers: {
          "Content-Type": "application/json",
          "Content-Length": data ? Buffer.byteLength(data) : 0
        },
        timeout: 120000
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let parsed;
          try {
            parsed = text ? JSON.parse(text) : {};
          } catch (error) {
            reject(new Error(`Invalid JSON response: ${error.message}`));
            return;
          }
          if (response.statusCode < 200 || response.statusCode >= 300) {
            const message = parsed.error && parsed.error.message
              ? parsed.error.message
              : text || `HTTP ${response.statusCode}`;
            reject(new Error(message));
            return;
          }
          resolve(parsed);
        });
      }
    );
    request.on("timeout", () => {
      request.destroy(new Error("Request timed out"));
    });
    request.on("error", reject);
    if (data) {
      request.write(data);
    }
    request.end();
  });
}

module.exports = {
  activate,
  deactivate
};
