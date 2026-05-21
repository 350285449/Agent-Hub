"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");

let serverProcess = null;
let modelPullProcess = null;
let output;
let chatPanel = null;
let extensionContext = null;
let lastActiveTextEditor = null;
const EXTENSION_VERSION = "0.5.0";
const CHAT_PARTICIPANT_ID = "agent-hub.agent-hub-vscode.agenthub";
const DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b";
const DEFAULT_LM_STUDIO_MODEL = "local-model";
const DEFAULT_OPENAI_MODEL = "gpt-4o-mini";
const DEFAULT_CODEX_MODEL = DEFAULT_OPENAI_MODEL;
const DEFAULT_CLAUDE_MODEL = "claude-3-5-haiku-latest";
const DEFAULT_GEMINI_MODEL = "gemini-2.0-flash";
const DEFAULT_CHATGPT_MODEL = DEFAULT_OPENAI_MODEL;
const OLLAMA_BASE_URL = "http://127.0.0.1:11434";
const LM_STUDIO_BASE_URL = "http://127.0.0.1:1234";
const HOSTED_CLOUD_AGENT_NAMES = ["codex", "claude", "gemini", "chatgpt"];
const OLLAMA_CLOUD_AGENT_NAMES = [
  "ollama-kimi-cloud",
  "ollama-glm-cloud",
  "ollama-qwen-cloud",
  "ollama-nemotron-cloud",
  "ollama-gemma-cloud"
];
const OLLAMA_CLOUD_MODELS = [
  {
    name: "ollama-kimi-cloud",
    label: "Kimi K2.6 Cloud",
    model: "kimi-k2.6:cloud"
  },
  {
    name: "ollama-glm-cloud",
    label: "GLM 5.1 Cloud",
    model: "glm-5.1:cloud"
  },
  {
    name: "ollama-qwen-cloud",
    label: "Qwen 3.5 Cloud",
    model: "qwen3.5:cloud"
  },
  {
    name: "ollama-nemotron-cloud",
    label: "Nemotron 3 Super Cloud",
    model: "nemotron-3-super:cloud"
  },
  {
    name: "ollama-gemma-cloud",
    label: "Gemma 4 31B Cloud",
    model: "gemma4:31b-cloud"
  }
];
const OLLAMA_INSTALL_OPTIONS = [
  {
    model: DEFAULT_OLLAMA_MODEL,
    label: "Qwen2.5 Coder 7B",
    size: "about 4.7 GB",
    detail: "Balanced local coding model for Agent Hub."
  },
  {
    model: "qwen3:8b",
    label: "Qwen3 8B",
    size: "about 5.2 GB",
    detail: "General chat and coding fallback."
  },
  {
    model: "llama3.2:3b",
    label: "Llama 3.2 3B",
    size: "about 2.0 GB",
    detail: "Small, quick local model for lighter machines."
  },
  {
    model: "gemma3:4b",
    label: "Gemma 3 4B",
    size: "about 3.3 GB",
    detail: "Compact general local model."
  }
];
const API_KEY_SECRETS = [
  {
    id: "openai",
    label: "OpenAI / Codex",
    env: "OPENAI_API_KEY",
    secret: "agentHub.openaiApiKey"
  },
  {
    id: "anthropic",
    label: "Claude",
    env: "ANTHROPIC_API_KEY",
    secret: "agentHub.anthropicApiKey"
  },
  {
    id: "gemini",
    label: "Gemini",
    env: "GEMINI_API_KEY",
    secret: "agentHub.geminiApiKey"
  }
];
const REQUIRED_BACKEND_FEATURES = [
  "native_agent_streaming",
  "native_agent_tool_schemas",
  "agent_progress_v2",
  "workspace_edit_events",
  "active_file_context_resolution",
  "current_folder_context",
  "workspace_shell_commands",
  "file_write_tools",
  "fast_write_finalize"
];

function activate(context) {
  extensionContext = context;
  output = vscode.window.createOutputChannel("Agent Hub");
  context.subscriptions.push(output);
  lastActiveTextEditor = vscode.window.activeTextEditor || null;
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor) {
        lastActiveTextEditor = editor;
      }
    })
  );

  registerChatParticipant(context);

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

function registerChatParticipant(context) {
  if (!vscode.chat || typeof vscode.chat.createChatParticipant !== "function") {
    output.appendLine("VS Code Chat Participant API is unavailable in this VS Code version.");
    return;
  }

  const participant = vscode.chat.createChatParticipant(
    CHAT_PARTICIPANT_ID,
    async (request, chatContext, stream, token) => handleParticipantRequest(request, chatContext, stream, token)
  );
  participant.iconPath = vscode.Uri.file(path.join(context.extensionPath, "assets", "agent-hub-icon.png"));

  if (typeof participant.followupProvider !== "undefined") {
    participant.followupProvider = {
      provideFollowups() {
        return [
          { prompt: "Inspect this workspace and suggest the next useful improvement", label: "Inspect workspace" },
          { prompt: "/explain Explain the current selection or open file", label: "Explain code" },
          { prompt: "/research Find current context for this problem", label: "Research" }
        ];
      }
    };
  }

  context.subscriptions.push(participant);
}

async function handleParticipantRequest(request, chatContext, stream, token) {
  const prompt = (request && typeof request.prompt === "string" ? request.prompt : "").trim();
  if (!prompt) {
    stream.markdown("Tell Agent Hub what to inspect, explain, research, or change.");
    return {};
  }

  const config = settings();
  const workspace = workspaceRoot();
  const command = request.command || "agent";
  const agentMode = command !== "research";
  const route = command === "research" ? config.researchRoute : codingAgentRoute(config);
  const context = participantContext(command, request);
  const task = participantTask(command, prompt, chatContext);

  stream.progress("Checking Agent Hub server...");
  if (!(await ensureServerReady())) {
    stream.markdown("Agent Hub is not running. Start it with `Agent Hub: Start Server` and try again.");
    return { metadata: { command, ok: false } };
  }
  if (token && token.isCancellationRequested) {
    return { metadata: { command, cancelled: true } };
  }

  const body = {
    session_id: "vscode-agenthub-chat",
    mode: agentMode ? "agent" : "route",
    route,
    task,
    context,
    use_session_history: true,
    max_tokens: config.maxTokens,
    metadata: {
      source: "vscode-chat-participant",
      command
    }
  };

  if (agentMode) {
    body.allow_shell_tools = config.allowShellTools;
    body.agent_max_steps = config.agentMaxSteps;
    body.workspace_dir = workspace || ".";
  } else {
    body.query = prompt;
    body.max_sources = 5;
  }

  output.appendLine("");
  output.appendLine(`[Agent Hub Chat /${command}] ${prompt}`);

  try {
    stream.progress(command === "research" ? "Researching..." : "Running the workspace agent...");
    const response = agentMode
      ? await requestEventStream("POST", "/v1/agent", { ...body, stream: true }, (event) => {
        const progress = progressTextFromEvent(event);
        if (progress) {
          output.appendLine(`[progress] ${progress}`);
          stream.progress(progress);
        }
      })
      : await requestJson("POST", "/v1/route", body);
    const reply = responseText(response) || "(empty response)";
    output.appendLine(reply);
    appendAgentTrace(response);
    appendResearchMetadata(response);

    stream.markdown(reply);
    const tools = agentToolSteps(response);
    const sources = sourceLines(response);
    if (tools.length) {
      stream.markdown(toolSummaryMarkdown(tools));
    }
    if (sources.length) {
      stream.markdown(sourceSummaryMarkdown(sources));
    }
    if (stream.button) {
      stream.button({ command: "agentHub.openOutput", title: "Open Agent Hub Output" });
    }

    return {
      metadata: {
        command,
        ok: true,
        tools: tools.length,
        sources: sources.length
      }
    };
  } catch (error) {
    output.appendLine(`Agent Hub chat participant failed: ${error.message}`);
    stream.markdown(formatAgentHubError(error));
    return { metadata: { command, ok: false, error: error.message } };
  }
}

function participantTask(command, prompt, chatContext) {
  const history = participantHistory(chatContext);
  const base = [
    "You are Agent Hub, a practical coding agent inside VS Code.",
    "Inspect workspace files before making claims about code.",
    "Use the current file path from context when the user refers to an open file by basename.",
    "Use the current folder path and file list from context when the request is about the open folder.",
    "Use Agent Hub file tools when you need to inspect or edit files; do not show tool-call JSON to the user.",
    "You can create files with write_file and edit files with replace_in_file. If the user asks to create, edit, fix, update, or implement, do the file change before finalizing.",
    "Shell tools are enabled for agent requests; use run_command for fast inspection, tests, builds, and commands the user asks you to run.",
    "When using a tool, reply with one raw JSON object, no Markdown fences, and quote every string value such as \"README.md\".",
    "For direct replies, use the final action; never invent other action names.",
    "When edits are needed, keep them scoped and verify when practical.",
    "Be concise, direct, and include file paths for code changes."
  ];

  if (command === "explain") {
    base.push("Explain the selected code or current file clearly, including purpose and important details.");
  } else if (command === "research") {
    base.push("Answer as a concise research assistant. Use current sources and include citations when available.");
  } else {
    base.push("Act as an autonomous workspace agent for this request.");
  }

  if (history) {
    base.push("", "Recent chat history:", history);
  }

  base.push("", prompt);
  return base.join("\n");
}

function participantContext(command, request) {
  const selected = selectedEditorContext();
  if (selected) {
    return selected;
  }
  if (command === "explain") {
    const editor = currentTextEditor();
    if (editor) {
      return contextForDocument(editor.document, editor.document.getText());
    }
  }
  return [
    activeEditorReferenceContext(),
    participantReferences(request)
  ].filter(Boolean).join("\n\n");
}

function participantHistory(chatContext) {
  if (!chatContext || !Array.isArray(chatContext.history)) {
    return "";
  }
  return chatContext.history
    .slice(-6)
    .map((turn) => {
      if (turn && typeof turn.prompt === "string") {
        return `User: ${turn.prompt}`;
      }
      if (turn && Array.isArray(turn.response)) {
        const response = Array.isArray(turn.response)
          ? turn.response.map((part) => part && part.value ? String(part.value) : "").join("")
          : "";
        return response ? `Agent Hub: ${response}` : "";
      }
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

function participantReferences(request) {
  if (!request || !Array.isArray(request.references) || !request.references.length) {
    return "";
  }
  return request.references
    .map((reference) => {
      if (!reference || !reference.value) {
        return "";
      }
      const value = reference.value;
      if (value instanceof vscode.Uri) {
        return `Reference: ${vscode.workspace.asRelativePath(value, false)}`;
      }
      if (typeof value === "string") {
        return value;
      }
      return "";
    })
    .filter(Boolean)
    .join("\n\n");
}

function toolSummaryMarkdown(tools) {
  const lines = tools.map((tool) => {
    const status = tool.ok ? "ok" : "failed";
    return `- #${tool.step} ${tool.tool} (${status})${tool.error ? `: ${tool.error}` : ""}`;
  });
  return ["", "<details><summary>Tools</summary>", "", ...lines, "", "</details>"].join("\n");
}

function sourceSummaryMarkdown(sources) {
  return ["", "<details><summary>Sources</summary>", "", ...sources, "", "</details>"].join("\n");
}

function deactivate() {
  stopServerProcess();
}

function openChat(context) {
  if (chatPanel) {
    chatPanel.reveal(vscode.ViewColumn.Beside);
    return;
  }

  const assetsRoot = vscode.Uri.file(path.join(context.extensionPath, "assets"));
  const logoUri = vscode.Uri.file(path.join(context.extensionPath, "assets", "agent-hub-icon.png"));
  chatPanel = vscode.window.createWebviewPanel(
    "agentHubChat",
    "Agent Hub",
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [assetsRoot]
    }
  );

  chatPanel.iconPath = logoUri;
  chatPanel.webview.html = chatHtml(chatPanel.webview, logoUri, settings());
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
    postChatSettings(panel);
    await postApiKeyStatus(panel);
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

  if (message.type === "restartServer") {
    await restartServerFromWebview(panel);
    return;
  }

  if (message.type === "saveApiKeys") {
    await saveApiKeysFromWebview(panel, message.keys);
    return;
  }

  if (message.type === "clearApiKeys") {
    await clearApiKeysFromWebview(panel);
    return;
  }

  if (message.type === "saveChatSettings") {
    await saveChatSettingsFromWebview(panel, message.settings);
    return;
  }

  if (message.type === "openSettings") {
    await vscode.commands.executeCommand("workbench.action.openSettings", "Agent Hub");
    return;
  }

  if (message.type === "openOutput") {
    output.show(true);
    return;
  }

  if (message.type === "chooseLocalModel") {
    await chooseLocalModel(panel);
    return;
  }

  if (message.type === "send") {
    await sendChatTurn(panel, message);
  }
}

async function saveApiKeysFromWebview(panel, keys) {
  if (!extensionContext || !extensionContext.secrets) {
    await postApiKeyStatus(panel, "VS Code secret storage is unavailable.");
    return;
  }

  const values = keys && typeof keys === "object" ? keys : {};
  const saved = [];
  for (const spec of API_KEY_SECRETS) {
    const value = typeof values[spec.id] === "string" ? values[spec.id].trim() : "";
    if (!value) {
      continue;
    }
    await extensionContext.secrets.store(spec.secret, value);
    saved.push(spec.label);
  }

  if (!saved.length) {
    await postApiKeyStatus(panel, "No new keys entered.");
    return;
  }

  const online = await isServerOnline();
  const suffix = serverProcess
    ? " Restart Agent Hub to use the updated keys."
    : (online
      ? " Restart the running server to use the saved keys."
      : " Start Agent Hub to use the saved keys.");
  await postApiKeyStatus(panel, `Saved ${saved.join(", ")}.${suffix}`, { clearInputs: true });
}

async function clearApiKeysFromWebview(panel) {
  if (!extensionContext || !extensionContext.secrets) {
    await postApiKeyStatus(panel, "VS Code secret storage is unavailable.");
    return;
  }

  for (const spec of API_KEY_SECRETS) {
    await extensionContext.secrets.delete(spec.secret);
  }
  await postApiKeyStatus(panel, "Saved API keys cleared.", { clearInputs: true });
}

async function postApiKeyStatus(panel, text = "", options = {}) {
  if (!panel || !panel.webview) {
    return;
  }
  panel.webview.postMessage({
    type: "apiKeyStatus",
    text,
    clearInputs: !!options.clearInputs,
    keys: await apiKeyStatusRows()
  });
}

function postChatSettings(panel, text = "") {
  if (!panel || !panel.webview) {
    return;
  }
  panel.webview.postMessage({
    type: "chatSettings",
    settings: chatSettingsPayload(settings()),
    text
  });
}

function chatSettingsPayload(config) {
  return {
    serverUrl: config.serverUrl,
    pythonPath: config.pythonPath,
    configPath: config.configPath,
    route: config.route,
    researchRoute: config.researchRoute,
    codingAgentRoute: config.codingAgentRoute,
    agentProviderMode: config.agentProviderMode,
    agentMaxSteps: config.agentMaxSteps,
    allowShellTools: config.allowShellTools,
    maxTokens: config.maxTokens,
    autoStart: config.autoStart,
    ...cloudModelSettingsPayload(config)
  };
}

async function saveChatSettingsFromWebview(panel, rawSettings) {
  try {
    const next = normalizeChatSettingsInput(rawSettings);
    const target = workspaceRoot()
      ? vscode.ConfigurationTarget.Workspace
      : vscode.ConfigurationTarget.Global;
    const config = vscode.workspace.getConfiguration("agentHub");
    for (const [key, value] of Object.entries(next.workspaceSettings)) {
      await config.update(key, value, target);
    }
    const configPath = workspaceRoot()
      ? resolveConfigPath(next.workspaceSettings.configPath, workspaceRoot())
      : "";
    const configChanged = configPath
      ? await saveCloudModelSettingsToConfig(configPath, next.cloudSettings)
      : false;
    const scope = target === vscode.ConfigurationTarget.Workspace ? "workspace" : "user";
    const restartNote = serverProcess || (await isServerOnline())
      ? " Restart Agent Hub to use server or route changes."
      : "";
    const configNote = configChanged ? " Updated Agent Hub model routing." : "";
    postChatSettings(panel, `Saved ${scope} settings.${configNote}${restartNote}`);
  } catch (error) {
    postChatSettings(panel, `Could not save settings: ${error.message}`);
  }
}

function normalizeChatSettingsInput(value) {
  const current = settings();
  const input = value && typeof value === "object" ? value : {};
  const serverUrl = normalizeServerUrl(input.serverUrl, current.serverUrl);
  return {
    workspaceSettings: {
      serverUrl,
      pythonPath: cleanSettingString(input.pythonPath, current.pythonPath),
      configPath: cleanSettingString(input.configPath, current.configPath),
      route: cleanSettingString(input.route, current.route),
      researchRoute: cleanSettingString(input.researchRoute, current.researchRoute),
      codingAgentRoute: cleanSettingString(input.codingAgentRoute, current.codingAgentRoute),
      agentProviderMode: normalizeAgentProviderMode(input.agentProviderMode || current.agentProviderMode),
      agentMaxSteps: cleanSettingInteger(input.agentMaxSteps, current.agentMaxSteps, 1, 100),
      allowShellTools: !!input.allowShellTools,
      maxTokens: cleanSettingInteger(input.maxTokens, current.maxTokens, 1, 200000),
      autoStart: !!input.autoStart
    },
    cloudSettings: {
      cloudRouteMode: normalizeCloudRouteMode(input.cloudRouteMode || "ollama-cloud"),
      apiKeyModelsEnabled: !!input.apiKeyModelsEnabled,
      codexModel: cleanSettingString(input.codexModel, DEFAULT_CODEX_MODEL),
      claudeModel: cleanSettingString(input.claudeModel, DEFAULT_CLAUDE_MODEL),
      geminiModel: cleanSettingString(input.geminiModel, DEFAULT_GEMINI_MODEL),
      chatgptModel: cleanSettingString(input.chatgptModel, DEFAULT_CHATGPT_MODEL)
    }
  };
}

function cleanSettingString(value, fallback) {
  const text = typeof value === "string" ? value.trim() : "";
  return text || fallback;
}

function cleanSettingInteger(value, fallback, min, max) {
  const number = Number.parseInt(value, 10);
  if (!Number.isFinite(number)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, number));
}

function normalizeServerUrl(value, fallback) {
  const text = cleanSettingString(value, fallback).replace(/\/+$/, "");
  let url;
  try {
    url = new URL(text);
  } catch (error) {
    throw new Error("Server URL must be a valid http:// or https:// URL.");
  }
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("Server URL must use http:// or https://.");
  }
  return text;
}

function normalizeCloudRouteMode(value) {
  const mode = typeof value === "string" ? value.toLowerCase() : "";
  if (mode === "local") {
    return "ollama-cloud";
  }
  return ["ollama-cloud", "api-key"].includes(mode) ? mode : "ollama-cloud";
}

function cloudModelSettingsPayload(config) {
  const fallback = {
    cloudRouteMode: "ollama-cloud",
    apiKeyModelsEnabled: false,
    codexModel: DEFAULT_CODEX_MODEL,
    claudeModel: DEFAULT_CLAUDE_MODEL,
    geminiModel: DEFAULT_GEMINI_MODEL,
    chatgptModel: DEFAULT_CHATGPT_MODEL
  };
  const workspace = workspaceRoot();
  if (!workspace) {
    return fallback;
  }

  const configPath = resolveConfigPath(config.configPath, workspace);
  if (!fs.existsSync(configPath)) {
    return fallback;
  }

  try {
    const raw = parseJsonConfigText(fs.readFileSync(configPath, "utf8")).value;
    if (!raw || typeof raw !== "object") {
      return fallback;
    }
    return {
      cloudRouteMode: configCloudRouteMode(raw),
      apiKeyModelsEnabled: apiKeyModelsEnabledFromConfig(raw),
      codexModel: modelForAgent(raw, "codex", DEFAULT_CODEX_MODEL),
      claudeModel: modelForAgent(raw, "claude", DEFAULT_CLAUDE_MODEL),
      geminiModel: modelForAgent(raw, "gemini", DEFAULT_GEMINI_MODEL),
      chatgptModel: modelForAgent(raw, "chatgpt", DEFAULT_CHATGPT_MODEL)
    };
  } catch (_error) {
    return fallback;
  }
}

function modelForAgent(data, name, fallback) {
  const agent = Array.isArray(data.agents)
    ? data.agents.find((item) => item && typeof item === "object" && item.name === name)
    : null;
  return agent && typeof agent.model === "string" && agent.model.trim()
    ? agent.model.trim()
    : fallback;
}

function apiKeyModelsEnabledFromConfig(data) {
  const selection = data && data.cloud_control_selection;
  if (selection && typeof selection === "object" && typeof selection.api_key_models_enabled === "boolean") {
    return selection.api_key_models_enabled;
  }
  return Array.isArray(data && data.agents)
    ? data.agents.some((item) => (
      item &&
      typeof item === "object" &&
      HOSTED_CLOUD_AGENT_NAMES.includes(item.name) &&
      item.enabled === true
    ))
    : false;
}

async function apiKeyStatusRows() {
  const rows = [];
  for (const spec of API_KEY_SECRETS) {
    const saved = extensionContext && extensionContext.secrets
      ? !!(await extensionContext.secrets.get(spec.secret))
      : false;
    rows.push({
      id: spec.id,
      label: spec.label,
      env: spec.env,
      saved
    });
  }
  return rows;
}

async function restartServerFromWebview(panel) {
  if (serverProcess) {
    panel.webview.postMessage({
      type: "serverStatus",
      online: false,
      text: "Restarting Agent Hub..."
    });
    stopServerProcess();
    if (!(await waitForServerOffline(3000))) {
      await stopAgentHubServerOnConfiguredPort();
      await waitForServerOffline(3000);
    }
    await startServer();
    const online = await isServerOnline();
    panel.webview.postMessage({
      type: "serverStatus",
      online,
      text: online ? "Agent Hub restarted" : "Agent Hub did not respond after restart"
    });
    return;
  }

  if (await isServerOnline()) {
    const text = "Agent Hub is running outside this VS Code window. Stop it, then start it here to use saved API keys.";
    vscode.window.showWarningMessage(text);
    panel.webview.postMessage({ type: "serverStatus", online: true, text });
    return;
  }

  await startServer();
  const online = await isServerOnline();
  panel.webview.postMessage({
    type: "serverStatus",
    online,
    text: online ? "Agent Hub started" : "Agent Hub did not respond after start"
  });
}

async function chooseLocalModel(panel) {
  if (modelPullProcess) {
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: true,
      text: "Already pulling a model. Check the Agent Hub output."
    });
    output.show(true);
    return;
  }

  panel.webview.postMessage({
    type: "modelPullStatus",
    running: true,
    text: "Scanning LM Studio and Ollama for local models..."
  });

  const installed = await localModelQuickPickItems();
  if (installed.length) {
    const picked = await vscode.window.showQuickPick(installed, {
      title: "Choose Local Agent Hub Model",
      placeHolder: "Use an installed LM Studio or Ollama model for Local control"
    });
    if (!picked) {
      panel.webview.postMessage({
        type: "modelPullStatus",
        running: false,
        text: "Local model selection cancelled."
      });
      return;
    }
    await saveLocalModelChoice(panel, picked.source);
    return;
  }

  const installPicked = await vscode.window.showQuickPick(ollamaInstallQuickPickItems(), {
    title: "Install Local Ollama Model",
    placeHolder: "No local LM Studio/Ollama models were found. Choose a model to pull."
  });
  if (!installPicked) {
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      text: "No local model selected."
    });
    return;
  }

  await installOllamaModelChoice(panel, installPicked.option);
}

async function localModelQuickPickItems() {
  const [lmStudioModels, ollamaInfos] = await Promise.all([
    detectLmStudioModels(),
    detectOllamaModelInfos()
  ]);
  const items = [];
  for (const model of lmStudioModels) {
    items.push({
      label: `LM Studio: ${model}`,
      description: "loaded local server",
      detail: "Use the model currently exposed by LM Studio on 127.0.0.1:1234.",
      source: lmStudioSource(model)
    });
  }
  for (const info of ollamaInfos) {
    const size = info.size ? `, ${info.size}` : "";
    items.push({
      label: `Ollama: ${info.name}`,
      description: `installed${size}`,
      detail: "Use this Ollama model on 127.0.0.1:11434.",
      source: ollamaSource(info.name)
    });
  }
  return items;
}

function ollamaInstallQuickPickItems() {
  return OLLAMA_INSTALL_OPTIONS.map((option) => ({
    label: option.label,
    description: `${option.model}, ${option.size}`,
    detail: option.detail,
    option
  }));
}

async function installOllamaModelChoice(panel, option) {
  panel.webview.postMessage({
    type: "modelPullStatus",
    running: true,
    text: `Pulling ${option.model} with Ollama (${option.size})...`
  });
  output.show(true);
  output.appendLine("");
  output.appendLine(`Pulling Ollama model: ${option.model} (${option.size})`);

  try {
    await pullOllamaModel(option.model);
    await saveLocalModelChoice(panel, ollamaSource(option.model), {
      prefix: `${option.model} installed and selected for local control.`
    });
  } catch (error) {
    const message = formatOllamaError(error);
    output.appendLine(message);
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      text: message
    });
    vscode.window.showWarningMessage(message);
  } finally {
    modelPullProcess = null;
  }
}

async function saveLocalModelChoice(panel, source, options = {}) {
  const workspace = workspaceRoot();
  if (!workspace) {
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      text: "Open a workspace folder before selecting a local model."
    });
    return;
  }

  try {
    const config = settings();
    const configPath = resolveConfigPath(config.configPath, workspace);
    const changed = applyLocalModelSelectionToConfig(configPath, source);
    const restartNote = serverProcess
      ? " Restart Agent Hub to use it."
      : ((await isServerOnline())
        ? " Restart the running server to use it."
        : " Start Agent Hub to use it.");
    const base = options.prefix || `Selected ${source.label} model ${source.model} for local control.`;
    const suffix = changed ? restartNote : " The config already used this model.";
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      providerMode: "local",
      text: `${base}${suffix}`
    });
  } catch (error) {
    const message = `Could not save local model selection: ${error.message}`;
    output.appendLine(message);
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      text: message
    });
  }
}

function pullOllamaModel(model) {
  return new Promise((resolve, reject) => {
    output.appendLine(`Pulling Ollama model: ${model}`);
    modelPullProcess = cp.spawn("ollama", ["pull", model], {
      cwd: workspaceRoot() || undefined,
      shell: false
    });
    modelPullProcess.stdout.on("data", (data) => output.append(data.toString()));
    modelPullProcess.stderr.on("data", (data) => output.append(data.toString()));
    modelPullProcess.on("error", (error) => {
      output.appendLine(`Failed to pull Ollama model: ${error.message}`);
      reject(error);
    });
    modelPullProcess.on("exit", (code) => {
      output.appendLine(`Ollama pull ${model} exited with code ${code}.`);
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Model pull failed with exit code ${code}. Check the Agent Hub output.`));
      }
    });
  });
}

async function sendChatTurn(panel, message) {
  const text = typeof message.text === "string" ? message.text.trim() : "";
  if (!text) {
    return;
  }

  const requestId = message.requestId || `${Date.now()}`;
  panel.webview.postMessage({ type: "typing", requestId });
  postChatProgress(panel, requestId, `Agent Hub extension ${EXTENSION_VERSION}: checking local server...`);

  if (!(await ensureServerReady())) {
    panel.webview.postMessage({
      type: "chatError",
      requestId,
      text: "Agent Hub is not running. Start the server or check the Agent Hub output."
    });
    return;
  }

  const config = settings();
  const providerMode = normalizeAgentProviderMode(message.providerMode || config.agentProviderMode);
  const health = await serverHealth();
  postChatProgress(panel, requestId, serverConnectionSummary(health, config));
  if (!serverSupportsRequiredBackend(health)) {
    output.appendLine(`Connected Agent Hub server is missing backend features: ${missingBackendFeatures(health).join(", ")}. Restarting.`);
    postChatProgress(panel, requestId, "Connected server is an older Agent Hub build; restarting to load the bundled backend...");
    await restartAgentHubServerForUpdate(health);
    if (!(await waitForRequiredBackend(7000))) {
      panel.webview.postMessage({
        type: "chatError",
        requestId,
        text: [
          "Agent Hub is online, but it is an older server that is missing the current agent backend features.",
          "",
          "Use Agent Hub: Stop Server, then Agent Hub: Start Server, or close the old terminal/process using port 8787.",
          "After restart, bare filenames should prefer the active file/folder and the progress wording should match this extension."
        ].join("\n")
      });
      return;
    }
    postChatProgress(panel, requestId, "Restarted Agent Hub with streaming support.");
  }
  postChatProgress(panel, requestId, controlAgentSummary(providerMode));
  if (providerMode !== "cloud") {
    postChatProgress(panel, requestId, await localModelConnectionSummary());
  }

  const workspace = workspaceRoot();
  const context = message.includeSelection
    ? selectedEditorContext() || activeEditorReferenceContext()
    : activeEditorReferenceContext();
  const body = {
    session_id: message.sessionId || `vscode-chat-${Date.now()}`,
    mode: "agent",
    route: codingAgentRoute(config, providerMode),
    task: codexChatTask(text),
    context,
    use_session_history: true,
    max_tokens: config.maxTokens,
    allow_shell_tools: config.allowShellTools,
    agent_max_steps: config.agentMaxSteps,
    workspace_dir: workspace || ".",
    metadata: {
      source: "vscode-agent-hub-chat",
      control_agent_mode: providerMode
    }
  };

  output.appendLine("");
  output.appendLine(`[Agent Hub Chat] ${text}`);
  try {
    const response = await requestEventStream("POST", "/v1/agent", { ...body, stream: true }, {
      onEvent: (event) => {
        const progress = progressTextFromEvent(event);
        if (!progress) {
          return;
        }
        output.appendLine(`[progress] ${progress}`);
        postChatProgress(panel, requestId, progress, event.name, event.data);
      },
      onNoHeaders: () => {
        postChatProgress(panel, requestId, "Waiting for Agent Hub to open a stream...");
      },
      onNoEvents: () => {
        postChatProgress(panel, requestId, "Connected to Agent Hub; waiting for the model backend to answer...");
      },
      onJsonFallback: () => {
        postChatProgress(panel, requestId, "Server returned a non-streaming response; restart Agent Hub to load the latest backend.");
      }
    });
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
    output.appendLine(`Agent Hub chat failed: ${error.message}`);
    panel.webview.postMessage({
      type: "chatError",
      requestId,
      text: formatAgentHubError(error)
    });
  }
}

function codexChatTask(text) {
  return [
    "Chat with the user as Agent Hub, a careful workspace agent.",
    "Be conversational and concise. Use workspace tools when inspection or edits are useful.",
    "Use the current file path from context when the user refers to an open file by basename.",
    "Use the current folder path and file list from context when the request is about the open folder.",
    "Use Agent Hub file tools when you need to inspect or edit files; do not show tool-call JSON to the user.",
    "You can create files with write_file and edit files with replace_in_file. If the user asks to create, edit, fix, update, or implement, do the file change before finalizing.",
    "Shell tools are enabled for agent requests; use run_command for fast inspection, tests, builds, and commands the user asks you to run.",
    "When using a tool, reply with one raw JSON object, no Markdown fences, and quote every string value such as \"README.md\".",
    "For direct replies, use the final action; never invent other action names.",
    "",
    text
  ].join("\n");
}

function responseText(response) {
  if (response && response.message && typeof response.message.content === "string") {
    return response.message.content;
  }
  if (response && typeof response.text === "string") {
    return response.text;
  }
  if (response && typeof response.content === "string") {
    return response.content;
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

function chatHtml(webview, logoPath, initialSettings = settings()) {
  const nonce = getNonce();
  const logoSrc = webview.asWebviewUri(logoPath);
  const initialSettingsJson = jsonForScript(chatSettingsPayload(initialSettings));
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource}; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Hub</title>
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

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .logo {
      width: 28px;
      height: 28px;
      border-radius: 6px;
      object-fit: cover;
      flex: 0 0 auto;
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

    .header-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      min-width: 0;
    }

    .settings-wrap {
      position: relative;
      flex: 0 0 auto;
    }

    .settings-menu {
      position: absolute;
      z-index: 20;
      top: calc(100% + 8px);
      right: 0;
      width: min(680px, calc(100vw - 28px));
      max-height: calc(100vh - 88px);
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
    }

    .settings-menu[hidden] {
      display: none;
    }

    .settings-head,
    .settings-actions,
    .settings-row {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .settings-head {
      justify-content: space-between;
      margin-bottom: 10px;
    }

    .settings-title,
    .settings-section-title {
      color: var(--vscode-foreground);
      font-weight: 600;
    }

    .settings-section {
      display: grid;
      gap: 10px;
      padding-top: 10px;
      margin-top: 10px;
      border-top: 1px solid var(--border);
    }

    .settings-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(180px, 1fr));
      gap: 10px;
    }

    .settings-field {
      display: grid;
      align-items: stretch;
      gap: 5px;
      color: var(--vscode-foreground);
      font-size: 12px;
    }

    .settings-check {
      color: var(--vscode-foreground);
    }

    .settings-message {
      min-height: 16px;
      color: var(--muted);
      font-size: 11px;
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

    .activity {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }

    .activity li {
      margin: 2px 0;
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

    select {
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 5px 8px;
      color: var(--vscode-input-foreground);
      background: var(--input);
      font: inherit;
    }

    input[type="text"],
    input[type="number"],
    input[type="password"] {
      width: 100%;
      min-width: 0;
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 6px 8px;
      color: var(--vscode-input-foreground);
      background: var(--input);
      font: inherit;
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
    select:disabled,
    input:disabled,
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

    .key-panel {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
    }

    .key-panel summary {
      cursor: pointer;
      color: var(--vscode-foreground);
      font-weight: 600;
    }

    .key-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(150px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }

    .key-field {
      display: grid;
      align-items: stretch;
      gap: 5px;
      color: var(--vscode-foreground);
      font-size: 12px;
    }

    .key-state,
    .key-message {
      min-height: 16px;
      color: var(--muted);
      font-size: 11px;
    }

    .key-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
    }

    @media (max-width: 720px) {
      .settings-grid,
      .key-grid {
        grid-template-columns: 1fr;
      }

      header {
        align-items: flex-start;
      }

      .header-actions {
        flex-direction: column;
        align-items: flex-end;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand">
        <img class="logo" src="${logoSrc}" alt="Agent Hub logo">
        <h1>Agent Hub</h1>
      </div>
      <div class="header-actions">
        <div class="status" id="status">Checking Agent Hub...</div>
        <div class="settings-wrap">
          <button class="secondary" id="settingsToggle" type="button" aria-expanded="false" aria-controls="settingsMenu">Settings</button>
          <section class="settings-menu" id="settingsMenu" hidden>
            <div class="settings-head">
              <div class="settings-title">Settings</div>
              <button class="secondary" id="settingsClose" type="button">Close</button>
            </div>
            <div class="settings-grid">
              <label class="settings-field">
                <span>Control agent</span>
                <select id="controlMode">
                  <option value="cloud">Cloud</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="local">Local</option>
                </select>
              </label>
              <label class="settings-field">
                <span>Cloud route</span>
                <select id="settingCloudRouteMode">
                  <option value="ollama-cloud">Ollama cloud models first</option>
                  <option value="api-key">API-key models first</option>
                </select>
              </label>
              <label class="settings-field">
                <span>Server URL</span>
                <input id="settingServerUrl" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Python path</span>
                <input id="settingPythonPath" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Config path</span>
                <input id="settingConfigPath" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Default route</span>
                <input id="settingRoute" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Local coding route</span>
                <input id="settingCodingRoute" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Research route</span>
                <input id="settingResearchRoute" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Max tokens</span>
                <input id="settingMaxTokens" type="number" min="1" step="100">
              </label>
              <label class="settings-field">
                <span>Agent max steps</span>
                <input id="settingAgentMaxSteps" type="number" min="1" max="100" step="1">
              </label>
              <label class="settings-field">
                <span>OpenAI / Codex model</span>
                <input id="settingCodexModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Claude model</span>
                <input id="settingClaudeModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Gemini model</span>
                <input id="settingGeminiModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>ChatGPT model</span>
                <input id="settingChatgptModel" type="text" autocomplete="off">
              </label>
            </div>
            <div class="settings-row">
              <label class="settings-check"><input id="settingAllowShellTools" type="checkbox"> Allow shell tools</label>
              <label class="settings-check"><input id="settingAutoStart" type="checkbox"> Auto-start server</label>
              <label class="settings-check"><input id="settingApiKeyModelsEnabled" type="checkbox"> Enable API-key models</label>
            </div>
            <div class="settings-actions">
              <button id="saveSettings" type="button">Save Settings</button>
              <button class="secondary" id="openSettings" type="button">Open VS Code Settings</button>
            </div>
            <div class="settings-message" id="settingsMessage"></div>
            <div class="settings-section">
              <div class="settings-section-title">Server</div>
              <div class="settings-actions">
                <button class="secondary" id="startServer" type="button">Start Server</button>
                <button class="secondary" id="restartServer" type="button">Restart Server</button>
                <button class="secondary" id="checkStatus" type="button">Status</button>
                <button class="secondary" id="pullModel" type="button">Choose Local Model</button>
                <button class="secondary" id="openOutput" type="button">Open Output</button>
              </div>
            </div>
            <details class="key-panel" id="apiKeyPanel">
              <summary>API Keys</summary>
              <div class="key-grid">
                <label class="key-field">
                  <span>OpenAI / Codex</span>
                  <input id="keyOpenai" type="password" autocomplete="off" placeholder="OPENAI_API_KEY">
                  <span class="key-state" id="keyOpenaiState">Checking...</span>
                </label>
                <label class="key-field">
                  <span>Claude</span>
                  <input id="keyAnthropic" type="password" autocomplete="off" placeholder="ANTHROPIC_API_KEY">
                  <span class="key-state" id="keyAnthropicState">Checking...</span>
                </label>
                <label class="key-field">
                  <span>Gemini</span>
                  <input id="keyGemini" type="password" autocomplete="off" placeholder="GEMINI_API_KEY">
                  <span class="key-state" id="keyGeminiState">Checking...</span>
                </label>
              </div>
              <div class="key-actions">
                <button class="secondary" id="saveApiKeys" type="button">Save Keys</button>
                <button class="secondary" id="clearApiKeys" type="button">Clear Saved Keys</button>
              </div>
              <div class="key-message" id="keyMessage"></div>
            </details>
          </section>
        </div>
      </div>
    </header>
    <main class="transcript" id="transcript" aria-live="polite"></main>
    <form id="form">
      <textarea id="prompt" placeholder="Ask Agent Hub to create, edit, inspect, explain, or run commands"></textarea>
      <div class="actions">
        <div class="left">
          <label><input id="includeSelection" type="checkbox"> Include selection</label>
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
    const initialSettings = ${initialSettingsJson};
    const transcript = document.getElementById("transcript");
    const form = document.getElementById("form");
    const prompt = document.getElementById("prompt");
    const send = document.getElementById("send");
    const status = document.getElementById("status");
    const settingsToggle = document.getElementById("settingsToggle");
    const settingsMenu = document.getElementById("settingsMenu");
    const settingsClose = document.getElementById("settingsClose");
    const settingsMessage = document.getElementById("settingsMessage");
    const includeSelection = document.getElementById("includeSelection");
    const controlMode = document.getElementById("controlMode");
    const pullModel = document.getElementById("pullModel");
    const settingInputs = {
      cloudRouteMode: document.getElementById("settingCloudRouteMode"),
      serverUrl: document.getElementById("settingServerUrl"),
      pythonPath: document.getElementById("settingPythonPath"),
      configPath: document.getElementById("settingConfigPath"),
      route: document.getElementById("settingRoute"),
      codingAgentRoute: document.getElementById("settingCodingRoute"),
      researchRoute: document.getElementById("settingResearchRoute"),
      maxTokens: document.getElementById("settingMaxTokens"),
      agentMaxSteps: document.getElementById("settingAgentMaxSteps"),
      codexModel: document.getElementById("settingCodexModel"),
      claudeModel: document.getElementById("settingClaudeModel"),
      geminiModel: document.getElementById("settingGeminiModel"),
      chatgptModel: document.getElementById("settingChatgptModel"),
      apiKeyModelsEnabled: document.getElementById("settingApiKeyModelsEnabled"),
      allowShellTools: document.getElementById("settingAllowShellTools"),
      autoStart: document.getElementById("settingAutoStart")
    };
    const keyInputs = {
      openai: document.getElementById("keyOpenai"),
      anthropic: document.getElementById("keyAnthropic"),
      gemini: document.getElementById("keyGemini")
    };
    const keyStates = {
      openai: document.getElementById("keyOpenaiState"),
      anthropic: document.getElementById("keyAnthropicState"),
      gemini: document.getElementById("keyGeminiState")
    };
    const keyMessage = document.getElementById("keyMessage");
    const pending = new Map();
    let sessionId = "vscode-chat-" + Date.now().toString(36);
    let workingTimer = null;
    let workingStarted = 0;

    function setBusy(value) {
      prompt.disabled = value;
      send.disabled = value;
      controlMode.disabled = value;
      if (!value && workingTimer) {
        clearInterval(workingTimer);
        workingTimer = null;
      }
    }

    function setSettingsMenuOpen(value) {
      settingsMenu.hidden = !value;
      settingsToggle.setAttribute("aria-expanded", value ? "true" : "false");
      if (value) {
        const firstField = settingsMenu.querySelector("select, input, button");
        if (firstField) {
          firstField.focus();
        }
      }
    }

    function applyChatSettings(settings, messageText) {
      const next = settings || {};
      controlMode.value = next.agentProviderMode || "cloud";
      settingInputs.cloudRouteMode.value = next.cloudRouteMode || "ollama-cloud";
      settingInputs.serverUrl.value = next.serverUrl || "";
      settingInputs.pythonPath.value = next.pythonPath || "";
      settingInputs.configPath.value = next.configPath || "";
      settingInputs.route.value = next.route || "";
      settingInputs.codingAgentRoute.value = next.codingAgentRoute || "";
      settingInputs.researchRoute.value = next.researchRoute || "";
      settingInputs.maxTokens.value = next.maxTokens || "";
      settingInputs.agentMaxSteps.value = next.agentMaxSteps || "";
      settingInputs.codexModel.value = next.codexModel || "";
      settingInputs.claudeModel.value = next.claudeModel || "";
      settingInputs.geminiModel.value = next.geminiModel || "";
      settingInputs.chatgptModel.value = next.chatgptModel || "";
      settingInputs.apiKeyModelsEnabled.checked = !!next.apiKeyModelsEnabled;
      settingInputs.allowShellTools.checked = !!next.allowShellTools;
      settingInputs.autoStart.checked = !!next.autoStart;
      if (messageText !== undefined) {
        settingsMessage.textContent = messageText || "";
      }
    }

    function collectChatSettings() {
      return {
        serverUrl: settingInputs.serverUrl.value,
        pythonPath: settingInputs.pythonPath.value,
        configPath: settingInputs.configPath.value,
        route: settingInputs.route.value,
        codingAgentRoute: settingInputs.codingAgentRoute.value,
        researchRoute: settingInputs.researchRoute.value,
        agentProviderMode: controlMode.value,
        cloudRouteMode: settingInputs.cloudRouteMode.value,
        maxTokens: settingInputs.maxTokens.value,
        agentMaxSteps: settingInputs.agentMaxSteps.value,
        codexModel: settingInputs.codexModel.value,
        claudeModel: settingInputs.claudeModel.value,
        geminiModel: settingInputs.geminiModel.value,
        chatgptModel: settingInputs.chatgptModel.value,
        apiKeyModelsEnabled: settingInputs.apiKeyModelsEnabled.checked,
        allowShellTools: settingInputs.allowShellTools.checked,
        autoStart: settingInputs.autoStart.checked
      };
    }

    function startWorkingStatus() {
      workingStarted = Date.now();
      if (workingTimer) {
        clearInterval(workingTimer);
      }
      const update = () => {
        const seconds = Math.max(0, Math.floor((Date.now() - workingStarted) / 1000));
        const minutes = Math.floor(seconds / 60);
        const remainder = seconds % 60;
        const elapsed = minutes ? minutes + "m " + remainder + "s" : seconds + "s";
        status.textContent = "Agent Hub is working... " + elapsed;
      };
      update();
      workingTimer = setInterval(update, 1000);
    }

    function appendMessage(role, text, options = {}) {
      const item = document.createElement("section");
      item.className = "message " + role + (options.error ? " error" : "");

      const roleLabel = document.createElement("div");
      roleLabel.className = "role";
      roleLabel.textContent = role === "user" ? "You" : "Agent Hub";

      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;
      item.agentHubBubble = bubble;

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

    function appendLiveMessage() {
      const item = appendMessage("assistant", "Starting...");
      const activity = document.createElement("ul");
      activity.className = "activity";
      item.append(activity);
      return { item, bubble: item.agentHubBubble, activity };
    }

    function appendActivity(turn, text) {
      if (!turn || !turn.activity || !text) {
        return;
      }
      const previous = turn.activity.lastElementChild;
      if (previous && previous.textContent === text) {
        return;
      }
      const item = document.createElement("li");
      item.textContent = text;
      turn.activity.append(item);
      if (turn.bubble && turn.bubble.textContent === "Starting...") {
        turn.bubble.textContent = text;
      }
      transcript.scrollTop = transcript.scrollHeight;
    }

    function finishLiveMessage(turn, text, options = {}) {
      if (!turn || !turn.item || !turn.bubble) {
        appendMessage("assistant", text, options);
        return;
      }
      turn.bubble.textContent = text;
      turn.item.classList.toggle("error", !!options.error);
      if (options.tools && options.tools.length) {
        turn.item.append(detailsBlock("Tools", options.tools.map((tool) => {
          const status = tool.ok ? "ok" : "failed";
          return "#" + tool.step + " " + tool.tool + " (" + status + ")" + (tool.error ? ": " + tool.error : "");
        })));
      }
      if (options.sources && options.sources.length) {
        turn.item.append(detailsBlock("Sources", options.sources));
      }
      transcript.scrollTop = transcript.scrollHeight;
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

    function setApiKeyStatus(keys, messageText, clearInputs) {
      if (clearInputs) {
        for (const input of Object.values(keyInputs)) {
          input.value = "";
        }
      }
      for (const row of keys || []) {
        const state = keyStates[row.id];
        if (!state) {
          continue;
        }
        state.textContent = row.saved ? "Saved" : "Not set";
      }
      if (messageText !== undefined) {
        keyMessage.textContent = messageText || "";
      }
    }

    settingsToggle.addEventListener("click", () => {
      setSettingsMenuOpen(settingsMenu.hidden);
    });

    settingsClose.addEventListener("click", () => {
      setSettingsMenuOpen(false);
      settingsToggle.focus();
    });

    document.addEventListener("click", (event) => {
      if (
        settingsMenu.hidden ||
        settingsMenu.contains(event.target) ||
        settingsToggle.contains(event.target)
      ) {
        return;
      }
      setSettingsMenuOpen(false);
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !settingsMenu.hidden) {
        setSettingsMenuOpen(false);
        settingsToggle.focus();
      }
    });

    document.getElementById("saveSettings").addEventListener("click", () => {
      settingsMessage.textContent = "Saving settings...";
      vscode.postMessage({
        type: "saveChatSettings",
        settings: collectChatSettings()
      });
    });

    document.getElementById("openSettings").addEventListener("click", () => {
      vscode.postMessage({ type: "openSettings" });
    });

    document.getElementById("openOutput").addEventListener("click", () => {
      vscode.postMessage({ type: "openOutput" });
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = prompt.value.trim();
      if (!text) {
        return;
      }
      const requestId = Date.now().toString(36) + Math.random().toString(36).slice(2);
      appendMessage("user", text);
      pending.set(requestId, appendLiveMessage());
      prompt.value = "";
      setBusy(true);
      startWorkingStatus();
      vscode.postMessage({
        type: "send",
        requestId,
        sessionId,
        text,
        includeSelection: includeSelection.checked,
        providerMode: controlMode.value
      });
    });

    document.getElementById("startServer").addEventListener("click", () => {
      status.textContent = "Starting Agent Hub...";
      vscode.postMessage({ type: "startServer" });
    });

    document.getElementById("saveApiKeys").addEventListener("click", () => {
      keyMessage.textContent = "Saving keys...";
      vscode.postMessage({
        type: "saveApiKeys",
        keys: {
          openai: keyInputs.openai.value,
          anthropic: keyInputs.anthropic.value,
          gemini: keyInputs.gemini.value
        }
      });
    });

    document.getElementById("restartServer").addEventListener("click", () => {
      status.textContent = "Restarting Agent Hub...";
      vscode.postMessage({ type: "restartServer" });
    });

    document.getElementById("clearApiKeys").addEventListener("click", () => {
      keyMessage.textContent = "Clearing saved keys...";
      vscode.postMessage({ type: "clearApiKeys" });
    });

    pullModel.addEventListener("click", () => {
      status.textContent = "Scanning local models...";
      pullModel.disabled = true;
      controlMode.value = "local";
      vscode.postMessage({ type: "chooseLocalModel" });
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
      if (message.type === "apiKeyStatus") {
        setApiKeyStatus(message.keys || [], message.text, message.clearInputs);
        return;
      }
      if (message.type === "chatSettings") {
        applyChatSettings(message.settings, message.text);
        return;
      }
      if (message.type === "typing") {
        startWorkingStatus();
        return;
      }
      if (message.type === "chatProgress") {
        appendActivity(pending.get(message.requestId), message.text);
        if (message.text) {
          status.textContent = message.text;
        }
        return;
      }
      if (message.type === "modelPullStatus") {
        status.textContent = message.text;
        if (message.providerMode) {
          controlMode.value = message.providerMode;
        }
        pullModel.disabled = !!message.running;
        if (!message.running && message.text) {
          appendMessage("assistant", message.text);
        }
        return;
      }
      if (message.type === "chatResponse") {
        const turn = pending.get(message.requestId);
        pending.delete(message.requestId);
        finishLiveMessage(turn, message.text, {
          tools: message.tools || [],
          sources: message.sources || []
        });
        setBusy(false);
        status.textContent = "Ready";
        prompt.focus();
        return;
      }
      if (message.type === "chatError") {
        const turn = pending.get(message.requestId);
        pending.delete(message.requestId);
        finishLiveMessage(turn, message.text, { error: true });
        setBusy(false);
        status.textContent = "Request failed";
        prompt.focus();
      }
    });

    prompt.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    applyChatSettings(initialSettings);
    vscode.postMessage({ type: "ready" });
    prompt.focus();
  </script>
</body>
</html>`;
}

function jsonForScript(value) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
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
  const workspace = workspaceRoot();
  if (!workspace) {
    vscode.window.showErrorMessage("Open a workspace folder before starting Agent Hub.");
    return;
  }

  const config = settings();
  const configChanged = await ensureLocalConfig(config, workspace);

  if (await isServerOnline()) {
    if (configChanged) {
      vscode.window.showWarningMessage("Agent Hub config was repaired. Restart Agent Hub to use the repaired config.");
    } else {
      vscode.window.showInformationMessage("Agent Hub is already running.");
    }
    return;
  }
  if (serverProcess) {
    vscode.window.showInformationMessage("Agent Hub is starting.");
    return;
  }

  const launch = await serverLaunchEnvironment(workspace);
  if (!(await ensurePythonBackend(config, workspace, launch))) {
    return;
  }

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

  const pythonArgs = [...launch.pythonArgs, ...args];
  output.appendLine(`Starting Agent Hub: ${launch.pythonLabel} ${args.join(" ")}`);
  serverProcess = cp.spawn(launch.pythonCommand, pythonArgs, {
    cwd: workspace,
    shell: false,
    env: launch.env
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

async function serverLaunchEnvironment(workspace) {
  const env = { ...process.env };
  await applySavedApiKeysToEnv(env);
  const backendRoot = backendSourceRoot(workspace);
  if (backendRoot) {
    prependEnvPath(env, "PYTHONPATH", backendRoot);
  }
  return {
    env,
    backendRoot,
    pythonCommand: "",
    pythonArgs: [],
    pythonLabel: ""
  };
}

async function applySavedApiKeysToEnv(env) {
  if (!extensionContext || !extensionContext.secrets) {
    return;
  }
  for (const spec of API_KEY_SECRETS) {
    const value = await extensionContext.secrets.get(spec.secret);
    if (value && value.trim()) {
      env[spec.env] = value.trim();
    }
  }
}

async function ensurePythonBackend(config, workspace, launch) {
  const script = [
    "import sys",
    "assert sys.version_info >= (3, 11), 'Agent Hub requires Python 3.11 or newer'",
    "import agent_hub",
    "print(sys.executable)",
    "print(getattr(agent_hub, '__file__', 'agent_hub'))"
  ].join("; ");

  const candidates = pythonCandidates(config.pythonPath, workspace);
  const failures = [];
  try {
    for (const candidate of candidates) {
      try {
        const { stdout } = await execFile(candidate.command, [...candidate.args, "-c", script], {
          cwd: workspace,
          env: launch.env,
          timeout: 10000
        });
        const lines = String(stdout || "").trim().split(/\r?\n/).filter(Boolean);
        launch.pythonCommand = candidate.command;
        launch.pythonArgs = candidate.args;
        launch.pythonLabel = candidate.label;
        if (launch.backendRoot) {
          output.appendLine(`Using Agent Hub backend source: ${launch.backendRoot}`);
        }
        if (lines[0]) {
          output.appendLine(`Using Python: ${lines[0]}`);
        }
        if (lines[1]) {
          output.appendLine(`Agent Hub Python backend import: ${lines[1]}`);
        }
        if (candidate.notice) {
          output.appendLine(candidate.notice);
        }
        return true;
      } catch (error) {
        failures.push({ candidate, error });
      }
    }
    throw new Error("No usable Python 3.11+ executable could import Agent Hub.");
  } catch (error) {
    const details = formatPythonBackendError(error, config, launch, failures);
    output.appendLine(details.detail);
    output.show();
    vscode.window.showErrorMessage(details.summary);
    return false;
  }
}

function pythonCandidates(value, workspace) {
  const raw = String(value || "").trim();
  const configured = raw && !["auto", "python"].includes(raw.toLowerCase()) ? raw : "";
  const candidates = [];

  if (configured) {
    const parsed = parsePythonCommand(configured);
    candidates.push({
      ...parsed,
      label: commandLabel(parsed.command, parsed.args),
      notice: ""
    });
  }

  if (workspace) {
    candidates.push(
      {
        command: path.join(workspace, ".venv", "Scripts", "python.exe"),
        args: [],
        label: ".venv\\Scripts\\python.exe",
        notice: configured ? `Configured Python was not usable; using workspace .venv instead.` : ""
      },
      {
        command: path.join(workspace, ".venv", "bin", "python"),
        args: [],
        label: ".venv/bin/python",
        notice: configured ? `Configured Python was not usable; using workspace .venv instead.` : ""
      }
    );
  }

  if (process.platform === "win32") {
    candidates.push(
      { command: "py", args: ["-3.14"], label: "py -3.14", notice: configured ? `Configured Python was not usable; using Python Launcher instead.` : "" },
      { command: "py", args: ["-3.13"], label: "py -3.13", notice: configured ? `Configured Python was not usable; using Python Launcher instead.` : "" },
      { command: "py", args: ["-3.12"], label: "py -3.12", notice: configured ? `Configured Python was not usable; using Python Launcher instead.` : "" },
      { command: "py", args: ["-3.11"], label: "py -3.11", notice: configured ? `Configured Python was not usable; using Python Launcher instead.` : "" },
      { command: "py", args: ["-3"], label: "py -3", notice: configured ? `Configured Python was not usable; using Python Launcher instead.` : "" }
    );
  }

  candidates.push(
    { command: "python", args: [], label: "python", notice: configured ? `Configured Python was not usable; using python on PATH instead.` : "" },
    { command: "python3", args: [], label: "python3", notice: configured ? `Configured Python was not usable; using python3 on PATH instead.` : "" }
  );

  return dedupePythonCandidates(candidates);
}

function parsePythonCommand(value) {
  if (fs.existsSync(value)) {
    return { command: value, args: [] };
  }
  const parts = splitCommandLine(value);
  if (!parts.length) {
    return { command: "python", args: [] };
  }
  return { command: parts[0], args: parts.slice(1) };
}

function splitCommandLine(value) {
  const parts = [];
  const pattern = /"([^"]+)"|'([^']+)'|(\S+)/g;
  let match;
  while ((match = pattern.exec(value)) !== null) {
    parts.push(match[1] || match[2] || match[3]);
  }
  return parts;
}

function dedupePythonCandidates(candidates) {
  const seen = new Set();
  const result = [];
  for (const candidate of candidates) {
    const key = `${candidate.command}\0${candidate.args.join("\0")}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(candidate);
  }
  return result;
}

function commandLabel(command, args) {
  return [command, ...(args || [])].join(" ");
}

function formatPythonBackendError(error, config, launch, failures = []) {
  const raw = error && error.message ? String(error.message) : String(error || "Unknown error");
  const firstUsefulFailure = failures.find((failure) => {
    const message = failure.error && failure.error.message ? String(failure.error.message) : "";
    const stderr = failure.error && failure.error.stderr ? String(failure.error.stderr) : "";
    return message.includes("No module named agent_hub") || stderr.includes("No module named agent_hub");
  });
  const hasMissingPython = failures.length && failures.every((failure) => failure.error && failure.error.code === "ENOENT");
  if ((error && error.code === "ENOENT") || hasMissingPython) {
    return {
      summary: "Agent Hub could not find Python 3.11+. Install Python or set agentHub.pythonPath.",
      detail: [
        `Python backend check failed: ${raw}`,
        "",
        "Agent Hub tried common Python launchers and requires Python 3.11 or newer.",
        "Set VS Code setting agentHub.pythonPath to auto, python, py -3.12, or a full python.exe path."
      ].join("\n")
    };
  }

  if (firstUsefulFailure || raw.includes("No module named agent_hub")) {
    const sourceLine = launch.backendRoot
      ? `Bundled backend source was found at: ${launch.backendRoot}`
      : "No bundled backend source was found in this extension package.";
    return {
      summary: "Agent Hub Python backend is missing. Rebuild/install the latest VSIX or run install.ps1.",
      detail: [
        "Python backend check failed: No module named agent_hub",
        sourceLine,
        `Configured Python setting: ${config.pythonPath}`,
        "",
        "For a packaged extension, rebuild with: cd vscode-extension; npm run package",
        "For a local repo checkout, run: .\\install.ps1"
      ].join("\n")
    };
  }

  return {
    summary: "Agent Hub Python backend check failed. See the Agent Hub output.",
    detail: [
      `Python backend check failed: ${raw}`,
      launch.backendRoot ? `Backend source: ${launch.backendRoot}` : "",
      pythonFailureSummary(failures)
    ].filter(Boolean).join("\n")
  };
}

function pythonFailureSummary(failures) {
  if (!failures.length) {
    return "";
  }
  const lines = ["Python candidates tried:"];
  for (const failure of failures.slice(0, 8)) {
    const message = failure.error && failure.error.stderr
      ? String(failure.error.stderr).trim()
      : (failure.error && failure.error.message ? String(failure.error.message) : "failed");
    lines.push(`- ${failure.candidate.label}: ${message.split(/\r?\n/)[0]}`);
  }
  if (failures.length > 8) {
    lines.push(`- ${failures.length - 8} more candidates omitted`);
  }
  return lines.join("\n");
}

function backendSourceRoot(workspace) {
  const candidates = [];
  if (extensionContext && extensionContext.extensionPath) {
    candidates.push(path.join(extensionContext.extensionPath, "backend"));
  }
  candidates.push(path.join(__dirname, "backend"));
  candidates.push(path.resolve(__dirname, ".."));
  if (workspace) {
    candidates.push(workspace);
  }

  const seen = new Set();
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (seen.has(resolved)) {
      continue;
    }
    seen.add(resolved);
    if (isAgentHubBackendRoot(resolved)) {
      return resolved;
    }
  }
  return "";
}

function isAgentHubBackendRoot(candidate) {
  return fs.existsSync(path.join(candidate, "agent_hub", "__main__.py"));
}

function prependEnvPath(env, name, value) {
  const existing = env[name];
  env[name] = existing ? `${value}${path.delimiter}${existing}` : value;
}

async function ensureLocalConfig(config, workspace) {
  const configPath = resolveConfigPath(config.configPath, workspace);
  if (fs.existsSync(configPath)) {
    return repairGeneratedLocalConfig(configPath);
  }

  const sources = await detectLocalModelSources();
  const selectedSources = sources.length ? sources : fallbackLocalModelSources();
  const data = localConfigForLocalModels(selectedSources);
  fs.writeFileSync(configPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  output.appendLine(`Created Agent Hub config at ${configPath}.`);
  output.appendLine(`Configured cloud control agents: ${describeCloudSources(selectedSources)}`);
  output.appendLine(`Configured local control agents: ${describeLocalSources(selectedSources)}`);
  if (!sources.length) {
    output.appendLine("No local model server was detected yet; start LM Studio or Ollama and restart Agent Hub to repair the config to the loaded model.");
  }
  return true;
}

async function repairGeneratedLocalConfig(configPath) {
  let raw;
  let usedLenientParser = false;
  try {
    const parsed = parseJsonConfigText(fs.readFileSync(configPath, "utf8"));
    raw = parsed.value;
    usedLenientParser = parsed.usedLenientParser;
  } catch (error) {
    output.appendLine(`Could not inspect Agent Hub config for repair: ${error.message}`);
    const sources = await detectLocalModelSources();
    const selectedSources = sources.length ? sources : fallbackLocalModelSources();
    const backupPath = backupConfigFile(configPath);
    fs.writeFileSync(configPath, `${JSON.stringify(localConfigForLocalModels(selectedSources), null, 2)}\n`, "utf8");
    output.appendLine(`Backed up unreadable Agent Hub config to ${backupPath}.`);
    output.appendLine(`Created a fresh local Agent Hub config at ${configPath}.`);
    output.appendLine(`Configured cloud control agents: ${describeCloudSources(selectedSources)}`);
    output.appendLine(`Configured local control agents: ${describeLocalSources(selectedSources)}`);
    return true;
  }

  if (!raw || typeof raw !== "object" || !Array.isArray(raw.agents) || !Array.isArray(raw.routes)) {
    return false;
  }

  const agentNames = new Set(
    raw.agents
      .filter((agent) => agent && typeof agent === "object" && typeof agent.name === "string")
      .map((agent) => agent.name)
  );
  const hasOfflineDefaults = raw.agents.some((agent) => (
    agent &&
    typeof agent === "object" &&
    ["custom-local", "localai", "vllm"].includes(agent.name)
  ));
  const hasGeneratedLocalConfig = raw.agents.some((agent) => (
    agent &&
    typeof agent === "object" &&
    ["ollama-local", "lm-studio"].includes(agent.name)
  ));
  const hasPlaceholderLocalModel = raw.agents.some((agent) => (
    agent &&
    typeof agent === "object" &&
    ["lm-studio", "custom-local", "vllm"].includes(agent.name) &&
    agent.model === "local-model"
  ));
  const hasCloudStyleAliases = ["codex", "claude"].every((name) => agentNames.has(name));
  const hasLocalBackedCloudAliases = raw.agents.some((agent) => (
    agent &&
    typeof agent === "object" &&
    ["codex", "claude", "gemini", "chatgpt"].includes(agent.name) &&
    agent.provider === "openai-compatible"
  ));
  const hasLegacyMinimalOllamaConfig = (
    agentNames.has("ollama-qwen-coder") &&
    agentNames.has("echo") &&
    !hasCloudStyleAliases
  );

  const sources = await detectLocalModelSources();
  const shouldRepairGeneratedConfig = (
    hasOfflineDefaults ||
    hasGeneratedLocalConfig ||
    hasPlaceholderLocalModel ||
    hasLocalBackedCloudAliases ||
    hasLegacyMinimalOllamaConfig
  );
  if (shouldRepairGeneratedConfig) {
    const explicitLocalSources = selectedLocalSources(raw);
    const selectedSources = explicitLocalSources.length
      ? explicitLocalSources
      : (sources.length ? sources : configuredLocalSources(raw));
    const repaired = localConfigForLocalModels(selectedSources, {
      cloudRouteMode: configCloudRouteMode(raw),
      cloudSettings: cloudModelSettingsFromConfig(raw)
    });
    if (explicitLocalSources.length) {
      repaired.local_model_selection = raw.local_model_selection;
    }
    const alreadyMatchesDetectedModels = configsEquivalent(raw, repaired);
    if (alreadyMatchesDetectedModels && !usedLenientParser) {
      return false;
    }
    if (alreadyMatchesDetectedModels && usedLenientParser) {
      raw = repaired;
    } else {
      const backupPath = backupConfigFile(configPath);
      fs.writeFileSync(configPath, `${JSON.stringify(repaired, null, 2)}\n`, "utf8");
      output.appendLine(`Repaired Agent Hub config at ${configPath}.`);
      output.appendLine(`Original config was backed up to ${backupPath}.`);
      output.appendLine(`Configured cloud control agents: ${describeCloudSources(selectedSources)}`);
      output.appendLine(`Configured local control agents: ${describeLocalSources(selectedSources)}`);
      return true;
    }
  }

  if (usedLenientParser) {
    const backupPath = backupConfigFile(configPath);
    fs.writeFileSync(configPath, `${JSON.stringify(raw, null, 2)}\n`, "utf8");
    output.appendLine(`Normalized Agent Hub config as strict JSON at ${configPath}.`);
    output.appendLine(`Original config was backed up to ${backupPath}.`);
    return true;
  }
  return false;
}

function configsEquivalent(left, right) {
  return JSON.stringify(stableConfigValue(left)) === JSON.stringify(stableConfigValue(right));
}

function stableConfigValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => stableConfigValue(item));
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  return Object.keys(value)
    .sort()
    .reduce((result, key) => {
      result[key] = stableConfigValue(value[key]);
      return result;
    }, {});
}

function configuredLocalSources(raw) {
  const agents = raw && Array.isArray(raw.agents) ? raw.agents : [];
  const sources = [];
  const ollama = agents.find((agent) => (
    agent &&
    typeof agent === "object" &&
    ["ollama-local", "ollama-qwen-coder", "ollama-qwen3"].includes(agent.name) &&
    typeof agent.model === "string" &&
    agent.model.trim()
  ));
  if (ollama) {
    const model = ollama.model.trim();
    sources.push(ollamaSource(model, model !== DEFAULT_OLLAMA_MODEL));
  }
  const lmStudio = agents.find((agent) => (
    agent &&
    typeof agent === "object" &&
    agent.name === "lm-studio" &&
    typeof agent.model === "string" &&
    agent.model.trim()
  ));
  if (lmStudio) {
    const model = lmStudio.model.trim();
    sources.push(lmStudioSource(model, model !== DEFAULT_LM_STUDIO_MODEL));
  }
  return sources.length ? sources : fallbackLocalModelSources();
}

function selectedLocalSources(raw) {
  const selection = raw && raw.local_model_selection;
  if (!selection || typeof selection !== "object" || typeof selection.model !== "string") {
    return [];
  }
  const model = selection.model.trim();
  if (!model) {
    return [];
  }
  if (selection.agent === "lm-studio") {
    return [lmStudioSource(model, true)];
  }
  if (["ollama-local", "ollama-qwen-coder", "ollama-qwen3"].includes(selection.agent)) {
    return [ollamaSource(model, true)];
  }
  return [];
}

function cloudModelSettingsFromConfig(raw) {
  return {
    cloudRouteMode: configCloudRouteMode(raw),
    apiKeyModelsEnabled: apiKeyModelsEnabledFromConfig(raw),
    codexModel: modelForAgent(raw, "codex", DEFAULT_CODEX_MODEL),
    claudeModel: modelForAgent(raw, "claude", DEFAULT_CLAUDE_MODEL),
    geminiModel: modelForAgent(raw, "gemini", DEFAULT_GEMINI_MODEL),
    chatgptModel: modelForAgent(raw, "chatgpt", DEFAULT_CHATGPT_MODEL)
  };
}

function localModelSelection(source) {
  return {
    agent: source.name,
    provider: source.label,
    model: source.model
  };
}

function applyLocalModelSelectionToConfig(configPath, source) {
  const existingText = fs.existsSync(configPath) ? fs.readFileSync(configPath, "utf8") : "";
  let data;
  let backedUpExisting = false;
  if (existingText) {
    try {
      data = parseJsonConfigText(existingText).value;
    } catch (_error) {
      const backupPath = backupConfigFile(configPath);
      backedUpExisting = true;
      output.appendLine(`Backed up unreadable Agent Hub config to ${backupPath}.`);
    }
  }

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    data = localConfigForLocalModels([source]);
  } else {
    data.agents = Array.isArray(data.agents) ? data.agents : [];
    data.routes = Array.isArray(data.routes) ? data.routes : [];
    upsertAgentConfig(data.agents, localModelAgentConfig(source));
    ensureLocalModelRoutes(data, source.name);
  }
  data.local_model_selection = localModelSelection(source);

  const nextText = `${JSON.stringify(data, null, 2)}\n`;
  if (existingText && stableConfigText(existingText) === stableConfigText(nextText)) {
    return false;
  }
  if (existingText && !backedUpExisting) {
    const backupPath = backupConfigFile(configPath);
    output.appendLine(`Backed up Agent Hub config to ${backupPath}.`);
  }
  fs.writeFileSync(configPath, nextText, "utf8");
  output.appendLine(`Configured local control model: ${source.label} (${source.model}).`);
  return true;
}

async function saveCloudModelSettingsToConfig(configPath, cloudSettings) {
  const existingText = fs.existsSync(configPath) ? fs.readFileSync(configPath, "utf8") : "";
  let data;
  let backedUpExisting = false;
  if (existingText) {
    try {
      data = parseJsonConfigText(existingText).value;
    } catch (_error) {
      const backupPath = backupConfigFile(configPath);
      backedUpExisting = true;
      output.appendLine(`Backed up unreadable Agent Hub config to ${backupPath}.`);
    }
  }

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    const sources = await detectLocalModelSources();
    data = localConfigForLocalModels(sources.length ? sources : fallbackLocalModelSources(), {
      cloudRouteMode: cloudSettings.cloudRouteMode,
      cloudSettings
    });
  }

  data.agents = Array.isArray(data.agents) ? data.agents : [];
  data.routes = Array.isArray(data.routes) ? data.routes : [];
  data.cloud_control_selection = {
    route_mode: normalizeCloudRouteMode(cloudSettings.cloudRouteMode),
    api_key_models_enabled: !!cloudSettings.apiKeyModelsEnabled
  };

  for (const source of cloudModelSources(cloudSettings)) {
    upsertAgentConfig(data.agents, cloudModelAgentConfig(source));
  }
  ensureDefaultOllamaCloudAgents(data);
  applyCloudRouteMode(data, data.cloud_control_selection.route_mode);

  const nextText = `${JSON.stringify(data, null, 2)}\n`;
  if (existingText && stableConfigText(existingText) === stableConfigText(nextText)) {
    return false;
  }
  if (existingText && !backedUpExisting) {
    const backupPath = backupConfigFile(configPath);
    output.appendLine(`Backed up Agent Hub config to ${backupPath}.`);
  }
  fs.writeFileSync(configPath, nextText, "utf8");
  output.appendLine(`Configured cloud route mode: ${data.cloud_control_selection.route_mode}.`);
  return true;
}

function stableConfigText(text) {
  try {
    return JSON.stringify(stableConfigValue(parseJsonConfigText(text).value));
  } catch (_error) {
    return String(text || "");
  }
}

function upsertAgentConfig(agents, nextAgent) {
  const index = agents.findIndex((agent) => (
    agent &&
    typeof agent === "object" &&
    agent.name === nextAgent.name
  ));
  const normalized = { enabled: true, ...nextAgent };
  if (index === -1) {
    agents.push(normalized);
    return;
  }
  agents[index] = {
    ...agents[index],
    ...normalized
  };
}

function ensureLocalModelRoutes(data, agentName) {
  ensureRouteContainsAgent(data.routes, "local-agent", ["agent", "workspace", "edit", "implement"], agentName, {
    first: true
  });
  ensureRouteContainsAgent(data.routes, "hybrid-agent", [], agentName);
  ensureRouteContainsAgent(data.routes, "coding", ["code", "bug", "fix", "refactor", "test", "repo"], agentName);
  data.default_route = ensureAgentFallback(listOrEmpty(data.default_route), agentName);
}

function ensureDefaultOllamaCloudAgents(data) {
  const agents = Array.isArray(data.agents) ? data.agents : [];
  const existing = new Set(
    agents
      .filter((agent) => agent && typeof agent === "object" && typeof agent.name === "string")
      .map((agent) => agent.name)
  );
  for (const source of ollamaCloudModelSources()) {
    if (!existing.has(source.name)) {
      upsertAgentConfig(agents, ollamaCloudModelAgentConfig(source));
      existing.add(source.name);
    }
  }
  data.agents = agents;
}

function applyCloudRouteMode(data, mode) {
  const routeMode = normalizeCloudRouteMode(mode);
  const routeAgents = cloudRouteAgentsForConfig(data, routeMode);
  setRouteAgents(data.routes, "cloud-agent", [], routeAgents);
  setRouteAgents(data.routes, "hybrid-agent", [], routeAgents);
  setRouteAgents(data.routes, "coding", ["code", "bug", "fix", "refactor", "test", "repo"], routeAgents);
  setRouteAgents(data.routes, "research", ["research", "search", "latest", "sources", "web", "news"], [
    "local-research",
    ...routeAgents.filter((name) => name !== "echo"),
    "echo"
  ]);
  data.default_route = routeAgents;
}

function setRouteAgents(routes, name, keywords, agents) {
  let route = routes.find((item) => item && typeof item === "object" && item.name === name);
  if (!route) {
    route = { name, keywords, agents: [] };
    routes.push(route);
  }
  if (!Array.isArray(route.keywords)) {
    route.keywords = keywords;
  }
  route.agents = uniqueAgentNames(agents);
}

function cloudRouteAgentsForConfig(data, mode) {
  const ollamaCloudAgents = ollamaCloudAgentNames(data);
  const hostedAgents = hostedCloudAgentNames(data);
  const ordered = normalizeCloudRouteMode(mode) === "api-key"
    ? [...hostedAgents, ...ollamaCloudAgents, "echo"]
    : [...ollamaCloudAgents, ...hostedAgents, "echo"];
  return uniqueAgentNames(ordered);
}

function ollamaCloudAgentNames(data) {
  const existing = agentNameSet(data);
  const names = OLLAMA_CLOUD_AGENT_NAMES.filter((name) => existing.has(name));
  return names.length ? names : OLLAMA_CLOUD_AGENT_NAMES;
}

function hostedCloudAgentNames(data) {
  const agents = Array.isArray(data && data.agents) ? data.agents : [];
  return HOSTED_CLOUD_AGENT_NAMES.filter((name) => {
    const agent = agents.find((item) => item && typeof item === "object" && item.name === name);
    return agent && agent.enabled === true;
  });
}

function agentNameSet(data) {
  return new Set(
    (Array.isArray(data.agents) ? data.agents : [])
      .filter((agent) => agent && typeof agent === "object" && typeof agent.name === "string")
      .map((agent) => agent.name)
  );
}

function configCloudRouteMode(data) {
  const explicit = data && data.cloud_control_selection;
  if (explicit && typeof explicit === "object" && typeof explicit.route_mode === "string") {
    return normalizeCloudRouteMode(explicit.route_mode);
  }

  const route = data && Array.isArray(data.routes)
    ? data.routes.find((item) => item && typeof item === "object" && item.name === "cloud-agent")
    : null;
  const firstAgent = route && Array.isArray(route.agents)
    ? route.agents.find((name) => name && name !== "echo")
    : "";
  return OLLAMA_CLOUD_AGENT_NAMES.includes(firstAgent) ? "ollama-cloud" : "api-key";
}

function uniqueAgentNames(names) {
  const seen = new Set();
  const result = [];
  for (const name of names) {
    if (!name || seen.has(name)) {
      continue;
    }
    seen.add(name);
    result.push(name);
  }
  return result;
}

function ensureRouteContainsAgent(routes, name, keywords, agentName, options = {}) {
  let route = routes.find((item) => item && typeof item === "object" && item.name === name);
  if (!route) {
    route = { name, keywords, agents: [] };
    routes.push(route);
  }
  if (!Array.isArray(route.keywords)) {
    route.keywords = keywords;
  }
  route.agents = options.first
    ? [agentName, ...listOrEmpty(route.agents).filter((item) => item !== agentName)]
    : ensureAgentFallback(listOrEmpty(route.agents), agentName);
}

function ensureAgentFallback(names, agentName) {
  const without = names.filter((name) => name !== agentName);
  const echoIndex = without.indexOf("echo");
  if (echoIndex === -1) {
    return [...without, agentName];
  }
  return [
    ...without.slice(0, echoIndex),
    agentName,
    ...without.slice(echoIndex)
  ];
}

function listOrEmpty(value) {
  return Array.isArray(value) ? value : [];
}

function localConfigForLocalModels(sources, options = {}) {
  const localSources = completeLocalModelSources(sources);
  const ollamaCloudSources = ollamaCloudModelSources();
  const cloudSources = cloudModelSources(options.cloudSettings || {});
  const ollamaCloudAgents = ollamaCloudSources.map((source) => source.name);
  const cloudAgents = cloudSources
    .filter((source) => source.enabled)
    .map((source) => source.name);
  const localAgents = localSources.map((source) => source.name);
  const cloudRouteMode = normalizeCloudRouteMode(options.cloudRouteMode || "ollama-cloud");
  const cloudRouteAgents = uniqueAgentNames(
    cloudRouteMode === "api-key"
      ? [...cloudAgents, ...ollamaCloudAgents, "echo"]
      : [...ollamaCloudAgents, ...cloudAgents, "echo"]
  );
  const hybridAgents = cloudRouteAgents;
  return {
    host: "127.0.0.1",
    port: 8787,
    state_dir: ".agent-hub/state",
    inbox_dir: ".agent-hub/inbox",
    outbox_dir: ".agent-hub/outbox",
    archive_dir: ".agent-hub/archive",
    workspace_dir: ".",
    agent_max_steps: 8,
    allow_shell_tools: true,
    free_only: true,
    include_raw_responses: false,
    expose_routing_details: true,
    cloud_control_selection: {
      route_mode: cloudRouteMode,
      api_key_models_enabled: !!options.cloudSettings?.apiKeyModelsEnabled
    },
    default_route: hybridAgents,
    routes: [
      {
        name: "coding",
        keywords: ["code", "bug", "fix", "refactor", "test", "repo"],
        agents: hybridAgents
      },
      {
        name: "local-agent",
        keywords: ["agent", "workspace", "edit", "implement"],
        agents: localAgents
      },
      {
        name: "hybrid-agent",
        keywords: [],
        agents: hybridAgents
      },
      {
        name: "cloud-agent",
        keywords: [],
        agents: cloudRouteAgents
      },
      {
        name: "research",
        keywords: ["research", "search", "latest", "sources", "web", "news"],
        agents: ["local-research", ...cloudRouteAgents.filter((name) => name !== "echo"), "echo"]
      }
    ],
    agents: [
      {
        name: "local-research",
        provider: "local-research",
        model: "local-extractive-research",
        free: true,
        context_window: 1000000,
        timeout_seconds: 20,
        cooldown_seconds: 5
      },
      ...ollamaCloudSources.map((source) => ollamaCloudModelAgentConfig(source)),
      ...cloudSources.map((source) => cloudModelAgentConfig(source)),
      ...localSources.map((source) => localModelAgentConfig(source)),
      {
        name: "echo",
        provider: "echo",
        model: "local-echo",
        free: true,
        context_window: 1000000,
        cooldown_seconds: 1
      }
    ]
  };
}

function cloudModelSources(settings = {}) {
  return [
    {
      name: "codex",
      label: "Codex",
      provider: "openai",
      enabled: !!settings.apiKeyModelsEnabled,
      model: cleanSettingString(settings.codexModel, process.env.AGENT_HUB_CODEX_MODEL || process.env.AGENT_HUB_OPENAI_MODEL || DEFAULT_CODEX_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_CODEX_API_KEY_ENV || "OPENAI_API_KEY",
      baseUrl: process.env.AGENT_HUB_CODEX_BASE_URL || process.env.OPENAI_BASE_URL || "",
      contextWindow: 128000
    },
    {
      name: "claude",
      label: "Claude",
      provider: "anthropic",
      enabled: !!settings.apiKeyModelsEnabled,
      model: cleanSettingString(settings.claudeModel, process.env.AGENT_HUB_CLAUDE_MODEL || DEFAULT_CLAUDE_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_CLAUDE_API_KEY_ENV || "ANTHROPIC_API_KEY",
      baseUrl: process.env.AGENT_HUB_CLAUDE_BASE_URL || "",
      contextWindow: 200000
    },
    {
      name: "gemini",
      label: "Gemini",
      provider: "gemini",
      enabled: !!settings.apiKeyModelsEnabled,
      model: cleanSettingString(settings.geminiModel, process.env.AGENT_HUB_GEMINI_MODEL || DEFAULT_GEMINI_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_GEMINI_API_KEY_ENV || "GEMINI_API_KEY",
      baseUrl: process.env.AGENT_HUB_GEMINI_BASE_URL || "",
      contextWindow: 1000000
    },
    {
      name: "chatgpt",
      label: "ChatGPT",
      provider: "openai",
      enabled: !!settings.apiKeyModelsEnabled,
      model: cleanSettingString(settings.chatgptModel, process.env.AGENT_HUB_CHATGPT_MODEL || process.env.AGENT_HUB_OPENAI_MODEL || DEFAULT_CHATGPT_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_CHATGPT_API_KEY_ENV || "OPENAI_API_KEY",
      baseUrl: process.env.AGENT_HUB_CHATGPT_BASE_URL || process.env.OPENAI_BASE_URL || "",
      contextWindow: 128000
    }
  ];
}

function ollamaCloudModelSources() {
  return OLLAMA_CLOUD_MODELS.map((source) => ({
    ...source,
    baseUrl: OLLAMA_BASE_URL,
    contextWindow: 128000,
    timeoutSeconds: 180,
    cooldownSeconds: 10
  }));
}

function ollamaCloudModelAgentConfig(source) {
  return {
    name: source.name,
    provider: "openai-compatible",
    model: source.model,
    base_url: source.baseUrl,
    free: true,
    max_tokens: 4096,
    context_window: source.contextWindow || 128000,
    timeout_seconds: source.timeoutSeconds || 180,
    cooldown_seconds: source.cooldownSeconds || 10
  };
}

function cloudModelAgentConfig(source) {
  const agent = {
    name: source.name,
    provider: source.provider,
    model: source.model,
    enabled: !!source.enabled,
    free: true,
    api_key_env: source.apiKeyEnv,
    max_tokens: 4096,
    context_window: source.contextWindow,
    timeout_seconds: 60,
    cooldown_seconds: 30
  };
  if (source.baseUrl) {
    agent.base_url = source.baseUrl;
  }
  return agent;
}

function localModelAgentConfig(source) {
  return {
    name: source.name,
    provider: "openai-compatible",
    model: source.model,
    base_url: source.baseUrl,
    free: true,
    max_tokens: 4096,
    context_window: source.contextWindow || 32768,
    timeout_seconds: source.timeoutSeconds || 300,
    cooldown_seconds: source.cooldownSeconds || 10
  };
}

async function detectLocalModelSources() {
  const [lmStudioModels, ollamaModels] = await Promise.all([
    detectLmStudioModels(),
    detectOllamaModels()
  ]);
  const sources = [];
  const ollamaModel = chooseOllamaModel(ollamaModels);
  if (ollamaModel) {
    sources.push(ollamaSource(ollamaModel));
  }
  const lmStudioModel = chooseLmStudioModel(lmStudioModels);
  if (lmStudioModel) {
    sources.push(lmStudioSource(lmStudioModel));
  }
  return sources;
}

function fallbackLocalModelSources() {
  return [
    ollamaSource(DEFAULT_OLLAMA_MODEL, false),
    lmStudioSource(DEFAULT_LM_STUDIO_MODEL, false)
  ];
}

function completeLocalModelSources(sources) {
  const selected = Array.isArray(sources) ? sources.filter(Boolean) : [];
  const hasOllama = selected.some((source) => source && source.name === "ollama-local");
  const hasLmStudio = selected.some((source) => source && source.name === "lm-studio");
  const completed = [...selected];
  if (!hasOllama) {
    completed.push(ollamaSource(DEFAULT_OLLAMA_MODEL, false));
  }
  if (!hasLmStudio) {
    completed.push(lmStudioSource(DEFAULT_LM_STUDIO_MODEL, false));
  }
  return completed;
}

function lmStudioSource(model, detected = true) {
  return {
    name: "lm-studio",
    label: "LM Studio",
    model,
    baseUrl: LM_STUDIO_BASE_URL,
    contextWindow: 32768,
    timeoutSeconds: 300,
    cooldownSeconds: 10,
    detected
  };
}

function ollamaSource(model, detected = true) {
  return {
    name: "ollama-local",
    label: "Ollama",
    model,
    baseUrl: OLLAMA_BASE_URL,
    contextWindow: 32768,
    timeoutSeconds: 300,
    cooldownSeconds: 10,
    detected
  };
}

function describeLocalSources(sources) {
  return sources
    .map((source) => `${source.label} (${source.model})`)
    .join(", ");
}

function describeCloudSources(localSources = fallbackLocalModelSources()) {
  const ollamaCloud = ollamaCloudModelSources()
    .map((source) => `${source.label} (${source.model})`);
  const apiKey = cloudModelSources()
    .map((source) => `${source.label} (${source.model}, ${source.apiKeyEnv}, disabled until enabled in settings)`);
  return [...ollamaCloud, ...apiKey]
    .join(", ");
}

async function detectLmStudioModels() {
  try {
    return await detectOpenAiCompatibleModels(LM_STUDIO_BASE_URL);
  } catch (error) {
    output.appendLine(`Could not detect LM Studio models: ${formatLocalServerError(error)}`);
    return [];
  }
}

async function detectOpenAiCompatibleModels(baseUrl) {
  const payload = await requestExternalJson(openAiModelsUrl(baseUrl), 5000);
  const data = Array.isArray(payload.data) ? payload.data : [];
  return data
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      if (item && typeof item.id === "string") {
        return item.id;
      }
      return "";
    })
    .filter(Boolean);
}

function openAiModelsUrl(baseUrl) {
  const base = new URL(baseUrl);
  base.pathname = `${base.pathname.replace(/\/+$/, "")}/v1/models`;
  return base.toString();
}

async function detectOllamaModels() {
  return (await detectOllamaModelInfos()).map((model) => model.name);
}

async function detectOllamaModelInfos() {
  try {
    const { stdout } = await execFile("ollama", ["list"], { timeout: 10000 });
    return parseOllamaList(stdout);
  } catch (error) {
    output.appendLine(`Could not detect Ollama models: ${formatOllamaError(error)}`);
    return [];
  }
}

function parseOllamaList(text) {
  return String(text || "")
    .split(/\r?\n/)
    .slice(1)
    .map((line) => {
      const parts = line.trim().split(/\s+/).filter(Boolean);
      if (!parts.length || parts[0] === "NAME") {
        return null;
      }
      const size = parts.length >= 4 && /^\d+(\.\d+)?$/.test(parts[2])
        ? `${parts[2]} ${parts[3]}`
        : "";
      return {
        name: parts[0],
        id: parts[1] || "",
        size
      };
    })
    .filter(Boolean);
}

function chooseOllamaModel(models) {
  const available = Array.isArray(models) ? models.filter(Boolean) : [];
  const preferences = [
    /qwen2\.5-coder/i,
    /qwen.*coder/i,
    /codellama/i,
    /deepseek.*coder/i,
    /qwen/i,
    /llama/i,
    /mistral/i
  ];
  for (const pattern of preferences) {
    const match = available.find((model) => pattern.test(model));
    if (match) {
      return match;
    }
  }
  return available[0] || "";
}

function chooseLmStudioModel(models) {
  const available = Array.isArray(models) ? models.filter(Boolean) : [];
  const preferences = [
    /coder/i,
    /qwen/i,
    /deepseek/i,
    /llama/i,
    /mistral/i,
    /gemma/i
  ];
  for (const pattern of preferences) {
    const match = available.find((model) => pattern.test(model));
    if (match) {
      return match;
    }
  }
  return available[0] || "";
}

function parseJsonConfigText(text) {
  const source = String(text || "").replace(/^\uFEFF/, "");
  try {
    return { value: JSON.parse(source), usedLenientParser: false };
  } catch (strictError) {
    const normalized = stripTrailingJsonCommas(stripJsonComments(source));
    try {
      return { value: JSON.parse(normalized), usedLenientParser: true };
    } catch (lenientError) {
      throw new Error(`${strictError.message}; lenient repair also failed: ${lenientError.message}`);
    }
  }
}

function stripJsonComments(text) {
  let result = "";
  let inString = false;
  let escaped = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (inString) {
      result += char;
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === "\"") {
        inString = false;
      }
      continue;
    }

    if (char === "\"") {
      inString = true;
      result += char;
      continue;
    }

    if (char === "/" && next === "/") {
      index += 2;
      while (index < text.length && !["\r", "\n"].includes(text[index])) {
        index += 1;
      }
      if (index < text.length) {
        result += text[index];
      }
      continue;
    }

    if (char === "/" && next === "*") {
      index += 2;
      while (index < text.length) {
        if (text[index] === "*" && text[index + 1] === "/") {
          index += 1;
          break;
        }
        if (["\r", "\n"].includes(text[index])) {
          result += text[index];
        }
        index += 1;
      }
      continue;
    }

    result += char;
  }

  return result;
}

function stripTrailingJsonCommas(text) {
  let result = "";
  let inString = false;
  let escaped = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];

    if (inString) {
      result += char;
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === "\"") {
        inString = false;
      }
      continue;
    }

    if (char === "\"") {
      inString = true;
      result += char;
      continue;
    }

    if (char === ",") {
      let lookahead = index + 1;
      while (lookahead < text.length && /\s/.test(text[lookahead])) {
        lookahead += 1;
      }
      if (text[lookahead] === "}" || text[lookahead] === "]") {
        continue;
      }
    }

    result += char;
  }

  return result;
}

function backupConfigFile(configPath) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const backupPath = `${configPath}.${stamp}.bak`;
  fs.copyFileSync(configPath, backupPath);
  return backupPath;
}

function formatOllamaError(error) {
  const raw = error && error.message ? String(error.message) : String(error || "Unknown error");
  if (error && error.code === "ENOENT") {
    return "Ollama was not found on PATH. Install Ollama, restart VS Code, then run the pull again.";
  }
  return `Could not run Ollama: ${raw}`;
}

function formatLocalServerError(error) {
  const raw = error && error.message ? String(error.message) : String(error || "Unknown error");
  if (raw.includes("ECONNREFUSED") || raw.includes("connect ETIMEDOUT")) {
    return "server is not running";
  }
  return raw;
}

function requestExternalJson(urlString, timeoutMs) {
  const url = new URL(urlString);
  const client = url.protocol === "https:" ? https : http;

  return new Promise((resolve, reject) => {
    const request = client.request(
      url,
      {
        method: "GET",
        timeout: timeoutMs
      },
      (response) => {
        let text = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          text += chunk;
        });
        response.on("end", () => {
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(new Error(text || `HTTP ${response.statusCode}`));
            return;
          }
          try {
            resolve(JSON.parse(text || "{}"));
          } catch (error) {
            reject(error);
          }
        });
      }
    );
    request.on("timeout", () => {
      request.destroy(new Error("Request timed out"));
    });
    request.on("error", reject);
    request.end();
  });
}

function execFile(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    cp.execFile(command, args, options, (error, stdout, stderr) => {
      if (error) {
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
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
    title: "Run Coding Agent",
    prompt: "What should the agent change or investigate in this workspace?",
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
      "Work as a coding agent in this workspace.",
    "Inspect files before editing, keep changes scoped, and verify if possible.",
    "Use the current file, current folder, and folder file list from context before searching broadly.",
    "Use Agent Hub file tools when you need to inspect or edit files; do not show tool-call JSON to the user.",
    "You can create files with write_file and edit files with replace_in_file. If the user asks to create, edit, fix, update, or implement, do the file change before finalizing.",
    "Shell tools are enabled for agent requests; use run_command for fast inspection, tests, builds, and commands the user asks you to run.",
      "When using a tool, reply with one raw JSON object, no Markdown fences, and quote every string value such as \"README.md\".",
      "For direct replies, use the final action; never invent other action names.",
      "",
      task
    ].join("\n"),
    context: selectedEditorContext() || activeEditorReferenceContext(),
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
  const editor = currentTextEditor();
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
  const editor = currentTextEditor();
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
    const text = responseText(response);
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
    vscode.window.showErrorMessage(formatAgentHubError(error));
  }
}

function formatAgentHubError(error) {
  const raw = error && error.message ? String(error.message) : String(error || "Unknown error");
  const details = error && Array.isArray(error.failover) ? error.failover : [];
  const lines = [];

  if (raw.includes("WinError 10061") || raw.includes("actively refused") || raw.trim() === "Network error:") {
    lines.push(
      "Agent Hub is running, but no usable local model backend answered.",
      "",
      "Start LM Studio's local server with a loaded model, or install Ollama and pull a model.",
      "For Ollama, run this in a terminal, then try again:",
      "",
      "ollama pull qwen2.5-coder:7b"
    );
  } else if (raw.includes("missing API key env")) {
    lines.push(
      "Agent Hub tried an API-key model on the cloud control route, but the configured API key is missing.",
      "",
      "Open Settings in Agent Hub chat, save the provider key, and restart Agent Hub. You can also set Cloud route to Ollama cloud models first."
    );
  } else {
    lines.push(`Agent Hub request failed: ${raw}`);
  }

  if (details.length) {
    lines.push("", "Provider attempts:");
    for (const event of details) {
      if (!event || typeof event !== "object") {
        continue;
      }
      const agent = event.agent || "unknown";
      const reason = event.reason || "failed";
      lines.push(`- ${agent}: ${reason}`);
    }
  }

  return lines.join("\n");
}

async function ensureServerReady() {
  const config = settings();
  const health = await serverHealth();
  if (serverSupportsRequiredBackend(health)) {
    return true;
  }
  if (health) {
    await restartAgentHubServerForUpdate(health);
    return serverSupportsRequiredBackend(await serverHealth());
  }
  if (config.autoStart) {
    await startServer();
  }
  return serverSupportsRequiredBackend(await serverHealth());
}

async function serverHealth() {
  try {
    return await requestJson("GET", "/health");
  } catch (error) {
    output.appendLine(`Could not read Agent Hub health: ${error.message}`);
    return null;
  }
}

function serverSupportsNativeStreaming(health) {
  return !!(
    health &&
    health.features &&
    health.features.native_agent_streaming === true
  );
}

function missingBackendFeatures(health) {
  const features = health && health.features && typeof health.features === "object"
    ? health.features
    : {};
  return REQUIRED_BACKEND_FEATURES.filter((feature) => features[feature] !== true);
}

function serverSupportsRequiredBackend(health) {
  return !!(health && missingBackendFeatures(health).length === 0);
}

function serverConnectionSummary(health, config) {
  if (!health) {
    return `Connected to ${config.serverUrl}, but health details were unavailable.`;
  }
  const agents = Array.isArray(health.agents) && health.agents.length
    ? health.agents.join(", ")
    : "none reported";
  const streaming = serverSupportsNativeStreaming(health) ? "streaming ready" : "old backend, no live stream";
  const backend = serverSupportsRequiredBackend(health)
    ? `backend ${health.version || "current"}`
    : `old backend missing ${missingBackendFeatures(health).join(", ")}`;
  const shellTools = health.allow_shell_tools === undefined
    ? (config.allowShellTools ? "enabled by request" : "disabled by request")
    : (health.allow_shell_tools ? "enabled" : "disabled in config");
  return `Connected to Agent Hub at ${config.serverUrl}: ${streaming}; ${backend}; shell tools ${shellTools}; agents: ${agents}.`;
}

async function waitForRequiredBackend(timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const health = await serverHealth();
    if (serverSupportsRequiredBackend(health)) {
      return true;
    }
    await delay(300);
  }
  return false;
}

async function restartAgentHubServerForUpdate(health) {
  stopServerProcess();
  await delay(500);
  if (await isServerOnline()) {
    const stillStale = !serverSupportsRequiredBackend(health || await serverHealth());
    if (stillStale) {
      await stopAgentHubServerOnConfiguredPort();
      await delay(800);
    }
  }
  if (!(await isServerOnline())) {
    await startServer();
  }
}

async function stopAgentHubServerOnConfiguredPort() {
  const config = settings();
  const url = new URL(config.serverUrl);
  const port = Number(url.port || (url.protocol === "https:" ? 443 : 80));
  if (!Number.isInteger(port) || port <= 0) {
    return;
  }

  output.appendLine(`Stopping stale Agent Hub process listening on port ${port}.`);
  if (process.platform === "win32") {
    const script = [
      `$port = ${port}`,
      "$pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique",
      "foreach ($processId in $pids) {",
      "  if ($processId -and $processId -ne $PID) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }",
      "}",
    ].join("; ");
    try {
      await execFile("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], {
        timeout: 10000
      });
    } catch (error) {
      output.appendLine(`Could not stop stale Agent Hub process on port ${port}: ${error.message}`);
    }
    return;
  }

  try {
    await execFile("sh", ["-c", `pids=$(lsof -tiTCP:${port} -sTCP:LISTEN 2>/dev/null); if [ -n "$pids" ]; then kill $pids; fi`], {
      timeout: 10000
    });
  } catch (error) {
    output.appendLine(`Could not stop stale Agent Hub process on port ${port}: ${error.message}`);
  }
}

async function localModelConnectionSummary() {
  const checks = await Promise.all([
    localModelServerSummary("LM Studio", openAiModelsUrl(LM_STUDIO_BASE_URL), "data"),
    localModelServerSummary("Ollama", `${OLLAMA_BASE_URL}/api/tags`, "models"),
  ]);
  const online = checks.filter((check) => check.online);
  if (online.length) {
    return `Model backend online: ${online.map((check) => check.text).join("; ")}.`;
  }
  return "No local model backend answered yet. Start LM Studio's local server with a loaded model, or start Ollama with a pulled model.";
}

async function localModelServerSummary(label, url, collectionKey) {
  try {
    const payload = await requestExternalJson(url, 3000);
    const collection = Array.isArray(payload[collectionKey]) ? payload[collectionKey] : [];
    const models = collection
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item.id === "string") {
          return item.id;
        }
        if (item && typeof item.name === "string") {
          return item.name;
        }
        if (item && typeof item.model === "string") {
          return item.model;
        }
        return "";
      })
      .filter(Boolean);
    return {
      online: true,
      text: models.length ? `${label} (${models.slice(0, 3).join(", ")})` : `${label} (no models reported)`,
    };
  } catch (_error) {
    return { online: false, text: `${label} offline` };
  }
}

function postChatProgress(panel, requestId, text, event, data) {
  if (!panel || !text) {
    return;
  }
  panel.webview.postMessage({
    type: "chatProgress",
    requestId,
    text,
    event: event || "extension_progress",
    data: data || {}
  });
}

function editorContext({ preferSelection }) {
  const editor = currentTextEditor();
  if (!editor) {
    return "";
  }
  const text = preferSelection && !editor.selection.isEmpty
    ? editor.document.getText(editor.selection)
    : editor.document.getText();
  return contextForDocument(editor.document, text);
}

function selectedEditorContext() {
  const editor = currentTextEditor();
  if (!editor || editor.selection.isEmpty) {
    return "";
  }
  return contextForDocument(editor.document, editor.document.getText(editor.selection));
}

function activeEditorReferenceContext() {
  const editor = currentTextEditor();
  if (!editor) {
    return "";
  }
  return documentReferenceContext(editor.document);
}

function contextForDocument(document, text) {
  const relative = documentRelativePath(document);
  const language = document.languageId || "plaintext";
  return [
    `File: ${relative}`,
    `Current folder: ${documentFolderRelativePath(document)}`,
    `Language: ${language}`,
    currentFolderFilesContext(document),
    "",
    text
  ].filter((part) => part !== "").join("\n");
}

function documentReferenceContext(document) {
  const relative = documentRelativePath(document);
  const language = document.languageId || "plaintext";
  return [
    `Current file: ${relative}`,
    `Current folder: ${documentFolderRelativePath(document)}`,
    `Language: ${language}`,
    currentFolderFilesContext(document)
  ].filter((part) => part !== "").join("\n");
}

function documentRelativePath(document) {
  return vscode.workspace.asRelativePath(document.uri, false);
}

function documentFolderRelativePath(document) {
  if (!document || !document.uri || document.uri.scheme !== "file") {
    return ".";
  }
  const folderPath = path.dirname(document.uri.fsPath);
  const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri);
  if (!workspaceFolder) {
    return path.basename(folderPath) || ".";
  }
  return normalizeRelativePath(path.relative(workspaceFolder.uri.fsPath, folderPath)) || ".";
}

function currentFolderFilesContext(document) {
  if (!document || !document.uri || document.uri.scheme !== "file") {
    return "";
  }
  const folderPath = path.dirname(document.uri.fsPath);
  let entries;
  try {
    entries = fs.readdirSync(folderPath, { withFileTypes: true });
  } catch (_error) {
    return "";
  }
  const visible = entries
    .filter((entry) => ![".git", ".agent-hub", "node_modules", "__pycache__"].includes(entry.name))
    .sort((left, right) => {
      if (left.isDirectory() !== right.isDirectory()) {
        return left.isDirectory() ? -1 : 1;
      }
      return left.name.localeCompare(right.name);
    })
    .slice(0, 80)
    .map((entry) => `- ${entry.name}${entry.isDirectory() ? "/" : ""}`);
  if (!visible.length) {
    return "Current folder files: none";
  }
  const omitted = entries.length > visible.length ? `\n- ... ${entries.length - visible.length} more` : "";
  return `Current folder files:\n${visible.join("\n")}${omitted}`;
}

function normalizeRelativePath(value) {
  return String(value || "").replace(/\\/g, "/");
}

function currentTextEditor() {
  return vscode.window.activeTextEditor || lastActiveTextEditor;
}

function settings() {
  const config = vscode.workspace.getConfiguration("agentHub");
  const providerMode = normalizeAgentProviderMode(config.get("agentProviderMode", "cloud"));
  return {
    serverUrl: config.get("serverUrl", "http://127.0.0.1:8787").replace(/\/+$/, ""),
    pythonPath: config.get("pythonPath", "auto"),
    configPath: config.get("configPath", "agent-hub.config.json"),
    route: config.get("route", "coding"),
    researchRoute: config.get("researchRoute", "research"),
    codingAgentRoute: config.get("codingAgentRoute", "local-agent"),
    agentProviderMode: providerMode,
    agentMaxSteps: config.get("agentMaxSteps", 20),
    allowShellTools: config.get("allowShellTools", true),
    maxTokens: config.get("maxTokens", 1200),
    autoStart: config.get("autoStart", true)
  };
}

function normalizeAgentProviderMode(value) {
  const mode = typeof value === "string" ? value.toLowerCase() : "";
  return ["cloud", "hybrid", "local"].includes(mode) ? mode : "cloud";
}

function codingAgentRoute(config, providerMode = config.agentProviderMode) {
  const mode = normalizeAgentProviderMode(providerMode);
  if (mode === "cloud") {
    return "cloud-agent";
  }
  if (mode === "hybrid") {
    return "hybrid-agent";
  }
  return config.codingAgentRoute || "local-agent";
}

function controlAgentSummary(providerMode) {
  const mode = normalizeAgentProviderMode(providerMode);
  if (mode === "local") {
    return "Control agent: local model route.";
  }
  if (mode === "hybrid") {
    return "Control agent: cloud route with local fallback.";
  }
  return "Control agent: cloud route.";
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
  const editor = currentTextEditor();
  if (editor) {
    const activeFolder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
    if (activeFolder) {
      return activeFolder.uri.fsPath;
    }
  }
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

async function waitForServerOffline(timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (!(await isServerOnline())) {
      return true;
    }
    await delay(300);
  }
  return false;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function progressTextFromEvent(event) {
  if (!event || !event.data || typeof event.data !== "object") {
    return "";
  }
  const type = event.data.type || event.name;
  if (type === "final" || type === "done") {
    return "";
  }
  if (typeof event.data.message === "string" && event.data.message.trim()) {
    return event.data.message.trim();
  }
  return "";
}

function requestEventStream(method, pathname, body, callbacks = {}) {
  const config = settings();
  const url = new URL(pathname, config.serverUrl);
  const client = url.protocol === "https:" ? https : http;
  const data = body ? JSON.stringify(body) : undefined;
  const handlers = typeof callbacks === "function" ? { onEvent: callbacks } : callbacks || {};

  return new Promise((resolve, reject) => {
    let settled = false;
    let responseRef = null;
    let sawEvent = false;
    let headersTimer = null;
    let eventTimer = null;

    const clearWatchdogs = () => {
      if (headersTimer) {
        clearTimeout(headersTimer);
        headersTimer = null;
      }
      if (eventTimer) {
        clearTimeout(eventTimer);
        eventTimer = null;
      }
    };

    const finishResolve = (value) => {
      if (!settled) {
        settled = true;
        clearWatchdogs();
        resolve(value);
      }
    };
    const finishReject = (error) => {
      if (!settled) {
        settled = true;
        clearWatchdogs();
        reject(error);
      }
    };

    if (typeof handlers.onNoHeaders === "function") {
      headersTimer = setTimeout(() => {
        if (!settled) {
          handlers.onNoHeaders();
        }
      }, 4000);
    }

    const request = client.request(
      url,
      {
        method,
        headers: {
          "Accept": "text/event-stream",
          "Content-Type": "application/json",
          "Content-Length": data ? Buffer.byteLength(data) : 0
        },
        timeout: 600000
      },
      (response) => {
        responseRef = response;
        if (headersTimer) {
          clearTimeout(headersTimer);
          headersTimer = null;
        }
        const contentType = String(response.headers["content-type"] || "");
        if (!contentType.includes("text/event-stream")) {
          if (typeof handlers.onJsonFallback === "function") {
            handlers.onJsonFallback();
          }
          collectJsonResponse(response, (error, parsed) => {
            if (error) {
              finishReject(error);
            } else {
              finishResolve(parsed);
            }
          });
          return;
        }

        let buffer = "";
        let finalResponse = null;
        if (typeof handlers.onNoEvents === "function") {
          eventTimer = setTimeout(() => {
            if (!settled && !sawEvent) {
              handlers.onNoEvents();
            }
          }, 7000);
        }
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          buffer += String(chunk).replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const event = parseServerSentEvent(block);
            if (event) {
              sawEvent = true;
              if (eventTimer) {
                clearTimeout(eventTimer);
                eventTimer = null;
              }
              if (event.name === "error") {
                const error = new Error(event.data && event.data.message ? event.data.message : "Agent Hub stream failed");
                if (event.data && Array.isArray(event.data.failover)) {
                  error.failover = event.data.failover;
                }
                finishReject(error);
                if (responseRef && typeof responseRef.destroy === "function") {
                  responseRef.destroy();
                }
                return;
              }
              if (event.name === "final" && event.data && event.data.response) {
                finalResponse = event.data.response;
              }
              if (typeof handlers.onEvent === "function") {
                handlers.onEvent(event);
              }
            }
            boundary = buffer.indexOf("\n\n");
          }
        });
        response.on("end", () => {
          if (buffer.trim()) {
            const event = parseServerSentEvent(buffer);
            if (event && event.name === "final" && event.data && event.data.response) {
              finalResponse = event.data.response;
            }
          }
          finishResolve(finalResponse || {});
        });
      }
    );
    request.on("timeout", () => {
      request.destroy(new Error("Request timed out"));
    });
    request.on("error", finishReject);
    if (data) {
      request.write(data);
    }
    request.end();
  });
}

function collectJsonResponse(response, callback) {
  const chunks = [];
  response.on("data", (chunk) => chunks.push(chunk));
  response.on("end", () => {
    const text = Buffer.concat(chunks).toString("utf8");
    let parsed;
    try {
      parsed = text ? JSON.parse(text) : {};
    } catch (error) {
      callback(new Error(`Invalid JSON response: ${error.message}`));
      return;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      const message = parsed.error && parsed.error.message
        ? parsed.error.message
        : text || `HTTP ${response.statusCode}`;
      const error = new Error(message);
      if (Array.isArray(parsed.failover)) {
        error.failover = parsed.failover;
      }
      callback(error);
      return;
    }
    callback(null, parsed);
  });
}

function parseServerSentEvent(block) {
  const lines = String(block || "").split("\n");
  let name = "message";
  const dataLines = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      name = line.slice("event:".length).trim() || "message";
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  if (!dataLines.length) {
    return null;
  }
  const rawData = dataLines.join("\n");
  let data;
  try {
    data = JSON.parse(rawData);
  } catch (_error) {
    data = rawData;
  }
  return { name, data };
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
        timeout: 600000
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
            const error = new Error(message);
            if (Array.isArray(parsed.failover)) {
              error.failover = parsed.failover;
            }
            reject(error);
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
