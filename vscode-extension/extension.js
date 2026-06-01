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
let chatWebviewReady = false;
let pendingChatRequests = [];
let extensionContext = null;
let sidebarProvider = null;
let statusBarItem = null;
let lastActiveTextEditor = null;
let serverLifecycleState = "Stopped";
let lastServerMessage = "";
const EXTENSION_VERSION = readExtensionPackageVersion();
const CHAT_PARTICIPANT_ID = "agent-hub.agent-hub-vscode.agenthub";
const SIDEBAR_VIEW_ID = "agentHub.sidebar";
const DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b";
const DEFAULT_LM_STUDIO_MODEL = "local-model";
const DEFAULT_OPENAI_MODEL = "gpt-4o-mini";
const DEFAULT_CODEX_MODEL = DEFAULT_OPENAI_MODEL;
const DEFAULT_CLAUDE_MODEL = "claude-3-5-haiku-latest";
const DEFAULT_GEMINI_MODEL = "gemini-2.0-flash";
const DEFAULT_CHATGPT_MODEL = DEFAULT_OPENAI_MODEL;
const DEFAULT_GROQ_MODEL = "qwen/qwen3-32b";
const DEFAULT_OPENROUTER_MODEL = "qwen/qwen3-coder:free";
const DEFAULT_CEREBRAS_MODEL = "llama-3.3-70b";
const DEFAULT_MISTRAL_MODEL = "mistral-small-latest";
const DEFAULT_GITHUB_MODELS_MODEL = "qwen/qwen3-coder-30b-a3b-instruct";
const DEFAULT_HUGGINGFACE_MODEL = "Qwen/Qwen3-Coder-30B-A3B-Instruct";
const DEFAULT_NVIDIA_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct";
const DEFAULT_CLOUDFLARE_MODEL = "@cf/meta/llama-3.1-8b-instruct";
const OLLAMA_BASE_URL = "http://127.0.0.1:11434";
const LM_STUDIO_BASE_URL = "http://127.0.0.1:1234";
const HOSTED_CLOUD_AGENT_NAMES = ["codex", "claude", "gemini", "chatgpt"];
const FREE_CLOUD_AGENT_NAMES = [
  "groq-qwen3-32b",
  "openrouter-qwen-free",
  "cerebras-llama-3-3-70b",
  "mistral-small-latest",
  "github-models-qwen3-coder",
  "huggingface-qwen3-coder",
  "nvidia-nemotron",
  "cloudflare-llama-3-1-8b"
];
const CLOUD_PROVIDER_TYPES = new Set([
  "groq",
  "openrouter",
  "cerebras",
  "together",
  "fireworks",
  "deepinfra",
  "mistral",
  "sambanova",
  "nvidia-nim",
  "github-models",
  "google-ai-studio",
  "huggingface",
  "cloudflare-workers-ai",
  "hyperbolic",
  "featherless",
  "replicate",
  "novita",
  "kluster",
  "parasail",
  "anyscale"
]);
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
    id: "ollama",
    label: "Ollama Cloud",
    env: "OLLAMA_API_KEY",
    secret: "agentHub.ollamaApiKey"
  },
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
  },
  {
    id: "groq",
    label: "Groq",
    env: "GROQ_API_KEY",
    secret: "agentHub.groqApiKey"
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    env: "OPENROUTER_API_KEY",
    secret: "agentHub.openrouterApiKey"
  },
  {
    id: "cerebras",
    label: "Cerebras",
    env: "CEREBRAS_API_KEY",
    secret: "agentHub.cerebrasApiKey"
  },
  {
    id: "together",
    label: "Together",
    env: "TOGETHER_API_KEY",
    secret: "agentHub.togetherApiKey"
  },
  {
    id: "fireworks",
    label: "Fireworks",
    env: "FIREWORKS_API_KEY",
    secret: "agentHub.fireworksApiKey"
  },
  {
    id: "deepinfra",
    label: "DeepInfra",
    env: "DEEPINFRA_API_KEY",
    secret: "agentHub.deepinfraApiKey"
  },
  {
    id: "mistral",
    label: "Mistral",
    env: "MISTRAL_API_KEY",
    secret: "agentHub.mistralApiKey"
  },
  {
    id: "sambanova",
    label: "SambaNova",
    env: "SAMBANOVA_API_KEY",
    secret: "agentHub.sambanovaApiKey"
  },
  {
    id: "nvidia",
    label: "NVIDIA NIM",
    env: "NVIDIA_API_KEY",
    secret: "agentHub.nvidiaApiKey"
  },
  {
    id: "github",
    label: "GitHub Models",
    env: "GITHUB_TOKEN",
    secret: "agentHub.githubToken"
  },
  {
    id: "huggingface",
    label: "Hugging Face",
    env: "HUGGINGFACE_API_KEY",
    secret: "agentHub.huggingfaceApiKey"
  },
  {
    id: "cloudflare",
    label: "Cloudflare",
    env: "CLOUDFLARE_API_TOKEN",
    secret: "agentHub.cloudflareApiToken"
  },
  {
    id: "hyperbolic",
    label: "Hyperbolic",
    env: "HYPERBOLIC_API_KEY",
    secret: "agentHub.hyperbolicApiKey"
  },
  {
    id: "featherless",
    label: "Featherless",
    env: "FEATHERLESS_API_KEY",
    secret: "agentHub.featherlessApiKey"
  },
  {
    id: "novita",
    label: "Novita",
    env: "NOVITA_API_KEY",
    secret: "agentHub.novitaApiKey"
  },
  {
    id: "parasail",
    label: "Parasail",
    env: "PARASAIL_API_KEY",
    secret: "agentHub.parasailApiKey"
  },
  {
    id: "anyscale",
    label: "Anyscale",
    env: "ANYSCALE_API_KEY",
    secret: "agentHub.anyscaleApiKey"
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
  "fast_write_finalize",
  "agent_context_compaction",
  "context_usage_bar",
  "cline_compatibility_mode",
  "context_debug_endpoints",
  "team_agent_mode",
  "provider_presets"
];
const APPROVAL_MODES = new Set(["ask", "auto", "safe", "readonly", "shell-ask", "deny"]);
const SENSITIVE_PERMISSION_CATEGORIES = new Set([
  "cloud_provider",
  "config_edit",
  "file_write",
  "model_download",
  "process_control",
  "secret_edit",
  "shell_command",
  "workspace_cloud"
]);

function readExtensionPackageVersion() {
  try {
    const manifestPath = path.join(__dirname, "package.json");
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    return typeof manifest.version === "string" && manifest.version.trim()
      ? manifest.version.trim()
      : "0.0.0";
  } catch (_error) {
    return "0.0.0";
  }
}

class PermissionManager {
  constructor(config = settings()) {
    this.mode = normalizeApprovalMode(config.approvalMode || "ask");
  }

  async request(action) {
    const category = action && action.category ? action.category : "unknown";
    if (!SENSITIVE_PERMISSION_CATEGORIES.has(category)) {
      return true;
    }
    if (this.mode === "auto") {
      return true;
    }
    if (this.mode === "readonly" || this.mode === "deny") {
      vscode.window.showWarningMessage(permissionDeniedText(action, this.mode));
      return false;
    }
    if (this.mode === "shell-ask" && category !== "shell_command") {
      return true;
    }

    const allow = "Allow Once";
    const choice = await vscode.window.showWarningMessage(
      permissionPromptText(action),
      { modal: true },
      allow,
      "Deny"
    );
    return choice === allow;
  }
}

function normalizeApprovalMode(value) {
  const mode = typeof value === "string" ? value.toLowerCase() : "";
  return APPROVAL_MODES.has(mode) ? mode : "ask";
}

async function requestPermission(action) {
  return new PermissionManager(settings()).request(action);
}

function permissionPromptText(action) {
  const risk = action.risk ? ` Risk: ${action.risk}.` : "";
  const resource = action.resource ? `\n\nTarget: ${action.resource}` : "";
  const detail = action.detail ? `\n\n${action.detail}` : "";
  return `${action.description || "Agent Hub needs permission to continue."}${risk}${resource}${detail}`;
}

function permissionDeniedText(action, mode) {
  return `${action.description || "Agent Hub action"} was blocked by approval mode '${mode}'.`;
}

function activate(context) {
  extensionContext = context;
  output = vscode.window.createOutputChannel("Agent Hub");
  context.subscriptions.push(output);
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBarItem.command = "agentHub.status";
  statusBarItem.text = "$(hubot) Agent Hub";
  statusBarItem.tooltip = "Agent Hub status";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);
  lastActiveTextEditor = vscode.window.activeTextEditor || null;
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor) {
        lastActiveTextEditor = editor;
      }
    })
  );

  registerChatParticipant(context);
  sidebarProvider = new AgentHubSidebarProvider(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(SIDEBAR_VIEW_ID, sidebarProvider, {
      webviewOptions: { retainContextWhenHidden: true }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("agentHub.chat", () => openChat(context)),
    vscode.commands.registerCommand("agentHub.startServer", startServer),
    vscode.commands.registerCommand("agentHub.stopServer", stopServer),
    vscode.commands.registerCommand("agentHub.restartServer", restartServer),
    vscode.commands.registerCommand("agentHub.checkHealth", checkHealth),
    vscode.commands.registerCommand("agentHub.openSettings", openAgentHubSettings),
    vscode.commands.registerCommand("agentHub.status", showStatus),
    vscode.commands.registerCommand("agentHub.ask", askAgent),
    vscode.commands.registerCommand("agentHub.codeAgent", runCodingAgent),
    vscode.commands.registerCommand("agentHub.research", researchWeb),
    vscode.commands.registerCommand("agentHub.explainSelection", explainSelection),
    vscode.commands.registerCommand("agentHub.explainFile", explainFile),
    vscode.commands.registerCommand("agentHub.copyClineConfig", copyClineConfig),
    vscode.commands.registerCommand("agentHub.testClineConnection", testClineConnection),
    vscode.commands.registerCommand("agentHub.showClineSetup", showClineSetup),
    vscode.commands.registerCommand("agentHub.copyClaudeCodeConfig", copyClaudeCodeConfig),
    vscode.commands.registerCommand("agentHub.testAnthropicEndpoint", testAnthropicEndpoint),
    vscode.commands.registerCommand("agentHub.showClaudeCodeSetup", showClaudeCodeSetup),
    vscode.commands.registerCommand("agentHub.openOutput", () => output.show())
  );
}

class AgentHubSidebarProvider {
  constructor(context) {
    this.context = context;
    this.view = null;
  }

  resolveWebviewView(webviewView) {
    this.view = webviewView;
    const assetsRoot = vscode.Uri.file(path.join(this.context.extensionPath, "assets"));
    const logoUri = vscode.Uri.file(path.join(this.context.extensionPath, "assets", "agent-hub-icon.png"));
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [assetsRoot]
    };
    webviewView.webview.html = sidebarHtml(webviewView.webview, logoUri);
    webviewView.webview.onDidReceiveMessage(
      (message) => this.handleMessage(message),
      undefined,
      this.context.subscriptions
    );
    this.refresh();
  }

  async handleMessage(message) {
    if (!message || typeof message !== "object") {
      return;
    }
    if (message.type === "ready" || message.type === "refresh") {
      await this.refresh();
      return;
    }
    if (message.type === "startServer") {
      setServerLifecycleState("Starting", "Starting Agent Hub...");
      await this.refresh();
      await startServer();
      await this.refresh();
      return;
    }
    if (message.type === "stopServer") {
      await stopServer();
      await this.refresh();
      return;
    }
    if (message.type === "restartServer") {
      await restartServer();
      await this.refresh();
      return;
    }
    if (message.type === "openChat") {
      openChat(this.context);
      return;
    }
    if (message.type === "quickTask") {
      const text = typeof message.text === "string" ? message.text.trim() : "";
      if (text) {
        openChat(this.context, {
          text,
          includeSelection: !!message.includeSelection,
          providerMode: settings().agentProviderMode
        });
      }
      return;
    }
    if (message.type === "askAgent") {
      await askAgent();
      return;
    }
    if (message.type === "codeAgent") {
      await runCodingAgent();
      return;
    }
    if (message.type === "explainFile") {
      await explainFile();
      return;
    }
    if (message.type === "openSettings") {
      await openAgentHubSettings();
      return;
    }
    if (message.type === "copyClineConfig") {
      await copyClineConfig();
      return;
    }
    if (message.type === "testClineConnection") {
      await testClineConnection();
      await this.refresh();
      return;
    }
    if (message.type === "showClineSetup") {
      await showClineSetup();
      return;
    }
    if (message.type === "copyClaudeCodeConfig") {
      await copyClaudeCodeConfig();
      return;
    }
    if (message.type === "testAnthropicEndpoint") {
      await testAnthropicEndpoint();
      await this.refresh();
      return;
    }
    if (message.type === "showClaudeCodeSetup") {
      await showClaudeCodeSetup();
      return;
    }
    if (message.type === "checkHealth") {
      await checkHealth();
      await this.refresh();
      return;
    }
    if (message.type === "openOutput") {
      output.show(true);
    }
  }

  async refresh() {
    if (!this.view || !this.view.webview) {
      return;
    }
    const dashboard = await sidebarDashboardState();
    updateStatusBar(dashboard);
    this.view.webview.postMessage({ type: "dashboard", dashboard });
  }
}

function setServerLifecycleState(state, message = "") {
  serverLifecycleState = state;
  lastServerMessage = message;
  refreshSidebar();
}

function refreshSidebar() {
  if (sidebarProvider) {
    sidebarProvider.refresh();
  }
  updateStatusBar({
    status: serverLifecycleState,
    statusText: lastServerMessage,
  });
}

function updateStatusBar(dashboard = {}) {
  if (!statusBarItem) {
    return;
  }
  const status = dashboard.status || serverLifecycleState || "Stopped";
  const active = dashboard.activeModel;
  const provider = active && (active.provider || active.provider_name || active.agent);
  const model = active && active.model;
  const remaining = dashboard.tokenUsage && dashboard.tokenUsage.remainingText
    ? ` ${dashboard.tokenUsage.remainingText}`
    : "";
  statusBarItem.text = status === "Running"
    ? `$(hubot) Agent Hub: ${provider || "provider"}${model ? `/${model}` : ""}${remaining}`
    : `$(circle-slash) Agent Hub: ${status}`;
  statusBarItem.tooltip = dashboard.statusText || "Agent Hub";
}

async function sidebarDashboardState() {
  const config = settings();
  const dashboard = {
    status: serverLifecycleState,
    statusText: lastServerMessage || "Agent Hub is not running.",
    serverUrl: config.serverUrl,
    agentProviderMode: config.agentProviderMode,
    agentMode: config.agentMode,
    approvalMode: config.approvalMode,
    autoStart: config.autoStart,
    extensionVersion: EXTENSION_VERSION,
    activeModel: null,
    providers: [],
    limits: [],
    failedModels: [],
    permissions: {
      approvalMode: config.approvalMode,
      safeMode: config.approvalMode === "safe",
      recent: []
    },
    tokenUsage: {
      totalTokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      remainingText: ""
    },
    onboarding: await sidebarOnboardingState(config, null),
    contextDiagnostics: {},
    statistics: sidebarStatistics(null, null, null, null, [], [], null),
    optimization: null,
    insights: [],
    activity: [],
    routingChain: [],
    logs: lastServerMessage || "",
  };

  try {
    const health = await requestJson("GET", "/health");
    let limits = null;
    let usage = null;
    let permissions = null;
    let metrics = null;
    let optimization = null;
    let debugContext = null;
    try {
      limits = await requestJson("GET", "/limits");
    } catch (_error) {
      limits = null;
    }
    try {
      usage = await requestJson("GET", "/usage");
    } catch (_error) {
      usage = null;
    }
    try {
      permissions = await requestJson("GET", "/permissions");
    } catch (_error) {
      permissions = null;
    }
    try {
      metrics = await requestJson("GET", "/metrics");
    } catch (_error) {
      metrics = null;
    }
    try {
      optimization = await requestJson("GET", "/v1/optimization");
    } catch (_error) {
      optimization = metrics && metrics.optimization ? metrics.optimization : null;
    }
    try {
      debugContext = await requestJson("GET", "/debug/context");
    } catch (_error) {
      debugContext = null;
    }
    dashboard.status = "Running";
    dashboard.statusText = `Running at ${config.serverUrl}`;
    dashboard.health = health;
    dashboard.activeModel = sidebarActiveModel(health, limits);
    dashboard.providers = sidebarProviderRows(health, limits);
    dashboard.limits = sidebarLimitRows(health, limits);
    dashboard.failedModels = sidebarFailedModels(health, limits);
    dashboard.permissions = sidebarPermissionState(health, permissions, config);
    dashboard.tokenUsage = sidebarTokenUsage(usage, dashboard.limits);
    dashboard.contextDiagnostics = sidebarContextDiagnostics(debugContext);
    dashboard.optimization = optimization || (metrics && metrics.optimization) || null;
    if (metrics && dashboard.optimization) {
      metrics.optimization = dashboard.optimization;
    }
    dashboard.statistics = sidebarStatistics(health, usage, metrics, permissions, dashboard.providers, dashboard.limits, debugContext, dashboard.optimization);
    dashboard.insights = sidebarInsightRows(dashboard, metrics);
    dashboard.onboarding = await sidebarOnboardingState(config, health);
    dashboard.activity = sidebarActivityRows(usage, metrics, dashboard.failedModels);
    dashboard.routingChain = sidebarRoutingChain(health, limits);
    dashboard.logs = "Open the Agent Hub output for live server logs.";
    return dashboard;
  } catch (error) {
    if (serverLifecycleState === "Starting" || serverLifecycleState === "Error" || serverProcess) {
      dashboard.status = serverLifecycleState === "Starting" ? "Starting" : "Error";
      dashboard.statusText = lastServerMessage || `Waiting for Agent Hub at ${config.serverUrl}.`;
      if (dashboard.status === "Error") {
        dashboard.statusText = lastServerMessage || `Agent Hub is unhealthy: ${error.message}`;
      }
    } else {
      dashboard.status = "Stopped";
      dashboard.statusText = `Stopped. Server URL: ${config.serverUrl}`;
    }
    dashboard.error = error.message;
    return dashboard;
  }
}

function sidebarActiveModel(health, limits) {
  if (limits && limits.active_model) {
    return limits.active_model;
  }
  const recommendations = health && Array.isArray(health.recommendations) ? health.recommendations : [];
  const active = recommendations.find((item) => item && item.available) || recommendations[0];
  if (!active) {
    return null;
  }
  return {
    provider: active.provider,
    model: active.model,
    agent: active.agent,
  };
}

function sidebarProviderRows(health, limits) {
  if (limits && Array.isArray(limits.providers)) {
    return limits.providers.slice(0, 12);
  }
  const providerHealth = health && health.provider_health && typeof health.provider_health === "object"
    ? health.provider_health
    : {};
  return Object.entries(providerHealth).slice(0, 12).map(([agent, row]) => ({
    agent,
    provider: row.provider || "",
    model: row.model || "",
    available: !!row.available,
    degraded: !!row.degraded,
    requests_remaining: row.requests_remaining,
    tokens_remaining: row.tokens_remaining,
    credits_remaining: row.credits_remaining,
    cooldown_until: row.cooldown_until,
  }));
}

function sidebarLimitRows(health, limits) {
  if (limits && Array.isArray(limits.limits)) {
    return limits.limits.slice(0, 12);
  }
  return sidebarProviderRows(health, limits);
}

function sidebarFailedModels(health, limits) {
  if (limits && Array.isArray(limits.failed_models)) {
    return limits.failed_models.slice(0, 8);
  }
  const providerHealth = health && health.provider_health && typeof health.provider_health === "object"
    ? health.provider_health
    : {};
  const rows = [];
  for (const [agent, row] of Object.entries(providerHealth)) {
    if (row && row.last_error_message) {
      rows.push({
        agent,
        provider: row.provider || "",
        model: row.model || "",
        reason: row.last_error_message,
      });
    }
  }
  return rows.slice(0, 8);
}

function sidebarPermissionState(health, permissions, config) {
  const policy = health && health.permission_policy && typeof health.permission_policy === "object"
    ? health.permission_policy
    : {};
  return {
    approvalMode: permissions && permissions.approval_mode ? permissions.approval_mode : config.approvalMode,
    safeMode: !!(permissions && permissions.safe_mode) || !!policy.safe_mode,
    readonlyMode: !!policy.readonly_mode,
    secretDetection: policy.secret_detection !== false,
    dangerousCommandBlocking: policy.dangerous_command_blocking !== false,
    recent: permissions && Array.isArray(permissions.recent) ? permissions.recent.slice(-5) : [],
    counts: permissions && permissions.counts ? permissions.counts : {}
  };
}

function sidebarTokenUsage(usage, limits) {
  const inputTokens = Number(usage && usage.input_tokens || 0);
  const outputTokens = Number(usage && usage.output_tokens || 0);
  const totalTokens = Number(usage && usage.total_tokens || inputTokens + outputTokens);
  const tokenRows = Array.isArray(limits) ? limits : [];
  const remaining = tokenRows
    .map((row) => row && row.tokens_remaining)
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value >= 0);
  const minRemaining = remaining.length ? Math.min(...remaining) : null;
  return {
    inputTokens,
    outputTokens,
    totalTokens,
    remainingTokens: minRemaining,
    remainingText: minRemaining === null ? "" : `${minRemaining} tok left`
  };
}

function sidebarStatistics(health, usage, metrics, permissions, providers, limits, debugContext, optimization) {
  const providerRows = Array.isArray(providers) && providers.length ? providers : sidebarProviderRows(health, limits);
  const counters = metrics && metrics.counters && typeof metrics.counters === "object" ? metrics.counters : {};
  const metricUsage = metrics && metrics.usage && typeof metrics.usage === "object" ? metrics.usage : {};
  const successfulCalls = Number(usage && usage.successful_provider_calls || counters.provider_successes || 0);
  const failedCalls = Number(usage && usage.failed_provider_calls || counters.provider_failures || 0);
  const totalCalls = successfulCalls + failedCalls;
  const availableProviders = Number(metrics && metrics.providers_available || providerRows.filter((row) => row.available).length || 0);
  const totalProviders = Number(metrics && metrics.providers_total || providerRows.length || 0);
  const degradedProviders = Number(metrics && metrics.providers_degraded || providerRows.filter((row) => row.degraded).length || 0);
  const unavailableProviders = Math.max(0, totalProviders - availableProviders);
  const usageTotal = Number(usage && usage.total_tokens || metricUsage.total_tokens || 0);
  const usageInput = Number(usage && usage.input_tokens || metricUsage.input_tokens || 0);
  const usageOutput = Number(usage && usage.output_tokens || metricUsage.output_tokens || 0);
  const toolExecutions = Number(usage && usage.tool_executions || metricUsage.tool_executions || counters.tool_executions || 0);
  const permissionEvents = Number(usage && usage.permission_events || metricUsage.permission_events || 0);
  const permissionCounts = permissions && permissions.counts && typeof permissions.counts === "object" ? permissions.counts : {};
  const permissionAllowed = Number(permissionCounts.allowed || 0);
  const permissionDenied = Number(permissionCounts.denied || 0);
  const approvalRequired = Number(permissionCounts.approval_required || 0);
  const routingFallbacks = Number(counters.routing_fallbacks || 0);
  const streamFailures = Number(counters.stream_failures || 0);
  const contextTruncations = Number(counters.context_truncations || 0);
  const workflows = metrics && Array.isArray(metrics.workflow_events) ? metrics.workflow_events.length : 0;
  const requests = metrics && Array.isArray(metrics.request_traces) ? metrics.request_traces.length : 0;
  const recentFailures = metrics && Array.isArray(metrics.recent_failures) ? metrics.recent_failures.length : 0;
  const debugSummary = debugContext && debugContext.summary && typeof debugContext.summary === "object" ? debugContext.summary : {};
  const contextIncoming = Number(debugSummary.incoming_context_size || debugSummary.incoming_token_count || 0);
  const contextProtected = Number(debugSummary.protected_token_count || 0);
  const optimizationSummary = optimization && typeof optimization === "object"
    ? optimization
    : metrics && metrics.optimization && typeof metrics.optimization === "object"
      ? metrics.optimization
      : {};
  const workflowRate = optimizationSummary.workflow_success_rate && typeof optimizationSummary.workflow_success_rate === "object"
    ? optimizationSummary.workflow_success_rate
    : {};
  const bestModels = Array.isArray(optimizationSummary.model_win_rates) ? optimizationSummary.model_win_rates : [];
  const bestModel = bestModels[0] || {};
  const taskWinners = optimizationSummary.task_model_winners && typeof optimizationSummary.task_model_winners === "object"
    ? optimizationSummary.task_model_winners
    : {};
  const codingWinner = taskWinners.coding || taskWinners.debug || taskWinners.tool_use || {};
  const roleWinners = optimizationSummary.role_model_winners && typeof optimizationSummary.role_model_winners === "object"
    ? optimizationSummary.role_model_winners
    : optimizationSummary.best_provider_by_workflow_role && typeof optimizationSummary.best_provider_by_workflow_role === "object"
      ? optimizationSummary.best_provider_by_workflow_role
      : {};
  const plannerWinner = roleWinners.planner || {};
  const workerWinner = roleWinners.coder || roleWinners.worker || {};
  const effectiveProviders = Array.isArray(optimizationSummary.most_effective_providers)
    ? optimizationSummary.most_effective_providers
    : [];
  const effectiveProvider = effectiveProviders[0] || {};
  const workflowAnalytics = Array.isArray(optimizationSummary.workflow_analytics)
    ? optimizationSummary.workflow_analytics
    : [];
  const bestWorkflow = workflowAnalytics[0] || {};
  const successRate = percent(successfulCalls, totalCalls);
  const providerAvailabilityPercent = percent(availableProviders, totalProviders);
  const healthScore = dashboardHealthScore({
    providerAvailabilityPercent,
    degradedProviders,
    failedCalls,
    totalCalls,
    routingFallbacks,
    permissionDenied,
    contextTruncations,
    streamFailures
  });

  return {
    providersTotal: totalProviders,
    providersAvailable: availableProviders,
    providersDegraded: degradedProviders,
    providersUnavailable: unavailableProviders,
    providerAvailabilityPercent,
    successfulCalls,
    failedCalls,
    totalCalls,
    successRate,
    failureRate: percent(failedCalls, totalCalls),
    totalTokens: usageTotal,
    inputTokens: usageInput,
    outputTokens: usageOutput,
    averageTokensPerCall: totalCalls > 0 ? Math.round(usageTotal / totalCalls) : 0,
    toolExecutions,
    permissionEvents,
    permissionAllowed,
    permissionDenied,
    approvalRequired,
    routingFallbacks,
    streamFailures,
    contextTruncations,
    workflows,
    requests,
    recentFailures,
    contextIncoming,
    contextProtected,
    workflowSuccessRate: Math.round(Number(workflowRate.rate || 0) * 100),
    workflowSuccessAttempts: Number(workflowRate.attempts || 0),
    averageKnownCost: optimizationSummary.average_known_cost_usd,
    adaptiveAverageLatencyMs: Number(optimizationSummary.average_latency_ms || 0),
    adaptiveAverageRetries: Number(optimizationSummary.average_retries || 0),
    failedRequestsRecovered: Number(optimizationSummary.failed_requests_recovered || 0),
    bestWorkflow: bestWorkflow.label || bestWorkflow.workflow_pattern || "",
    bestWorkflowAttempts: Number(bestWorkflow.attempts || 0),
    bestWorkflowSuccessRate: Math.round(Number(bestWorkflow.success_rate || 0) * 100),
    bestLearnedModel: [bestModel.provider, bestModel.model].filter(Boolean).join(" / "),
    bestCodingModel: [codingWinner.provider, codingWinner.model].filter(Boolean).join(" / "),
    bestCodingModelAttempts: Number(codingWinner.attempts || 0),
    bestCodingModelSuccessRate: Math.round(Number(codingWinner.success_rate || 0) * 100),
    bestPlannerModel: [plannerWinner.provider, plannerWinner.model].filter(Boolean).join(" / "),
    bestPlannerAttempts: Number(plannerWinner.attempts || 0),
    bestWorkerModel: [workerWinner.provider, workerWinner.model].filter(Boolean).join(" / "),
    bestWorkerAttempts: Number(workerWinner.attempts || 0),
    mostEffectiveProvider: effectiveProvider.provider || "",
    mostEffectiveProviderAttempts: Number(effectiveProvider.attempts || 0),
    mostEffectiveProviderSuccessRate: Math.round(Number(effectiveProvider.success_rate || 0) * 100),
    healthScore
  };
}

function sidebarInsightRows(dashboard, metrics) {
  const stats = dashboard.statistics || {};
  const insights = [];
  if (dashboard.status !== "Running") {
    insights.push({ tone: "warn", main: "Server is offline", meta: "Start Agent Hub to enable provider, token, and workflow statistics." });
  }
  if (stats.providersTotal > 0 && stats.providersAvailable === 0) {
    insights.push({ tone: "error", main: "No providers are available", meta: "Check API keys, local model servers, or provider cooldowns." });
  } else if (stats.providersDegraded > 0) {
    insights.push({ tone: "warn", main: `${stats.providersDegraded} provider(s) degraded`, meta: "Agent Hub will prefer healthier fallbacks when possible." });
  } else if (dashboard.status === "Running" && stats.providersAvailable > 0) {
    insights.push({ tone: "ok", main: `${stats.providersAvailable} provider(s) ready`, meta: "Routing has at least one usable model candidate." });
  }
  if (stats.totalCalls > 0 && stats.successRate < 80) {
    insights.push({ tone: "warn", main: `Provider success rate is ${stats.successRate}%`, meta: "Review recent failures and routing fallbacks before a long task." });
  } else if (stats.totalCalls > 0) {
    insights.push({ tone: "ok", main: `${stats.successRate}% provider success rate`, meta: `${stats.successfulCalls} successful call(s), ${stats.failedCalls} failed.` });
  }
  if (stats.routingFallbacks > 0) {
    insights.push({ tone: "info", main: `${stats.routingFallbacks} routing fallback(s) recorded`, meta: "Fallbacks are normal when quotas, context, or health checks rule out a model." });
  }
  if (stats.workflowSuccessAttempts > 0) {
    insights.push({
      tone: stats.workflowSuccessRate >= 80 ? "ok" : "info",
      main: `${stats.workflowSuccessRate}% workflow success`,
      meta: stats.bestWorkflow ? `Best workflow: ${stats.bestWorkflow}.` : "Adaptive workflow data is accumulating."
    });
  }
  if (stats.permissionDenied > 0) {
    insights.push({ tone: "warn", main: `${stats.permissionDenied} permission denial(s)`, meta: "Adjust approval mode only if the blocked actions were expected." });
  }
  if (stats.contextTruncations > 0) {
    insights.push({ tone: "warn", main: `${stats.contextTruncations} context truncation(s)`, meta: "Use a larger context route or reduce repository context for huge prompts." });
  }
  const failures = metrics && Array.isArray(metrics.recent_failures) ? metrics.recent_failures : [];
  for (const failure of failures.slice(-2).reverse()) {
    insights.push({
      tone: "error",
      main: failure.provider || failure.agent || failure.name || "Recent provider failure",
      meta: failure.message || failure.error || failure.reason || "Open logs for details."
    });
  }
  if (!insights.length) {
    insights.push({ tone: "ok", main: "Everything looks healthy", meta: "No immediate provider, permission, or context issues detected." });
  }
  return insights.slice(0, 5);
}

function percent(part, total) {
  const numerator = Number(part || 0);
  const denominator = Number(total || 0);
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round((numerator / denominator) * 100)));
}

function dashboardHealthScore(stats) {
  const availability = stats.providerAvailabilityPercent || 0;
  let score = availability || (stats.totalCalls > 0 ? 100 : 0);
  if (stats.totalCalls > 0) {
    score = Math.round((score * 0.55) + (percent(stats.totalCalls - stats.failedCalls, stats.totalCalls) * 0.45));
  }
  score -= Math.min(20, Number(stats.degradedProviders || 0) * 5);
  score -= Math.min(12, Number(stats.routingFallbacks || 0) * 2);
  score -= Math.min(10, Number(stats.permissionDenied || 0) * 2);
  score -= Math.min(10, Number(stats.contextTruncations || 0) * 3);
  score -= Math.min(10, Number(stats.streamFailures || 0) * 4);
  if (!stats.providerAvailabilityPercent && !stats.totalCalls) {
    score = 0;
  }
  return Math.max(0, Math.min(100, Math.round(score)));
}

function sidebarActivityRows(usage, metrics, failedModels) {
  const rows = [];
  const tools = usage && Array.isArray(usage.recent_tool_executions) ? usage.recent_tool_executions : [];
  for (const item of tools.slice(-4).reverse()) {
    rows.push({
      main: `${item.tool || "tool"} ${item.ok === false ? "failed" : "ok"}`,
      meta: item.error || (Array.isArray(item.paths) && item.paths.length ? item.paths.join(", ") : "workspace tool")
    });
  }
  const routing = metrics && Array.isArray(metrics.routing_decisions) ? metrics.routing_decisions : [];
  for (const item of routing.slice(-3).reverse()) {
    rows.push({
      main: item.agent ? `Routed to ${item.agent}` : item.type || "routing",
      meta: item.message || item.model || item.route || ""
    });
  }
  const optimization = metrics && metrics.optimization && typeof metrics.optimization === "object" ? metrics.optimization : {};
  const adaptive = Array.isArray(optimization.recent_optimization_decisions) ? optimization.recent_optimization_decisions : [];
  for (const item of adaptive.slice(-2).reverse()) {
    rows.push({
      main: item.success === false ? `Learning: ${item.agent || "provider"} failed` : `Learning: ${item.agent || "provider"} worked`,
      meta: [item.task_type, item.workflow_pattern, item.model].filter(Boolean).join(" / ")
    });
  }
  for (const item of (failedModels || []).slice(0, 2)) {
    rows.push({
      main: `Fallback: ${item.agent || item.model || "provider"}`,
      meta: item.reason || "provider unavailable"
    });
  }
  return rows.slice(0, 8);
}

function sidebarRoutingChain(health, limits) {
  const recommendations = limits && Array.isArray(limits.recommendations)
    ? limits.recommendations
    : health && Array.isArray(health.recommendations)
      ? health.recommendations
      : [];
  return recommendations.slice(0, 5).map((row) => ({
    agent: row.agent,
    provider: row.provider,
    model: row.model,
    available: row.available,
    reason: row.unavailable_reason || row.why || ""
  }));
}

async function sidebarOnboardingState(config, health) {
  const workspace = workspaceRoot();
  const configPath = workspace ? resolveConfigPath(config.configPath, workspace) : "";
  const backendRoot = backendSourceRoot(workspace);
  const keys = await apiKeyStatusRows().catch(() => []);
  const savedKeys = keys.filter((row) => row.saved).length;
  const localStatus = await sidebarLocalServerStatus();
  const python = await detectPythonForOnboarding(config, workspace);
  const providers = health && Array.isArray(health.agents) ? health.agents.length : 0;
  return [
    {
      label: "Backend",
      ok: !!backendRoot,
      detail: backendRoot ? `found at ${backendRoot}` : "backend package not found"
    },
    {
      label: "Python",
      ok: python.ok,
      detail: python.detail
    },
    {
      label: "Config",
      ok: !!(configPath && fs.existsSync(configPath)),
      detail: configPath || "open a workspace folder"
    },
    {
      label: "Providers",
      ok: providers > 0 || savedKeys > 0 || localStatus.some((row) => row.ok),
      detail: providers > 0 ? `${providers} enabled` : savedKeys > 0 ? `${savedKeys} saved key(s)` : "add a key or start a local model"
    },
    {
      label: "Local models",
      ok: localStatus.some((row) => row.ok),
      detail: localStatus.map((row) => `${row.name}: ${row.ok ? "running" : "offline"}`).join(" / ")
    },
    {
      label: "Start Server",
      ok: health && health.running === true,
      detail: health && health.running ? `running at ${config.serverUrl}` : "click Start Server"
    }
  ];
}

async function sidebarLocalServerStatus() {
  const rows = [
    { name: "Ollama", check: () => detectOllamaModels() },
    { name: "LM Studio", check: () => detectLmStudioModels() }
  ];
  const result = [];
  for (const row of rows) {
    try {
      const models = await row.check();
      result.push({ name: row.name, ok: Array.isArray(models) && models.length > 0 });
    } catch (_error) {
      result.push({ name: row.name, ok: false });
    }
  }
  return result;
}

async function detectPythonForOnboarding(config, workspace) {
  const candidates = pythonCandidates(config.pythonPath, workspace).slice(0, 5);
  for (const candidate of candidates) {
    try {
      const { stdout, stderr } = await execFile(candidate.command, [...candidate.args, "--version"], {
        cwd: workspace || undefined,
        timeout: 2000
      });
      const text = String(stdout || stderr || "").trim();
      const match = text.match(/Python\s+(\d+)\.(\d+)/i);
      const ok = !!(match && (Number(match[1]) > 3 || (Number(match[1]) === 3 && Number(match[2]) >= 11)));
      if (ok) {
        return { ok: true, detail: `${candidate.label}: ${text}` };
      }
    } catch (_error) {
      // Try the next configured launcher.
    }
  }
  return { ok: false, detail: "Python 3.11+ not detected" };
}

function sidebarContextDiagnostics(debugContext) {
  const summary = debugContext && debugContext.summary && typeof debugContext.summary === "object"
    ? debugContext.summary
    : {};
  return {
    incoming: Number(summary.incoming_context_size || summary.incoming_token_count || 0),
    preserved: Number(summary.preserved_context_size || summary.compacted_token_count || 0),
    compacted: Number(summary.compacted_amount || 0),
    protected: Number(summary.protected_token_count || 0),
    preservedToolCalls: Number(summary.preserved_tool_calls || 0),
    preservedTodos: Number(summary.preserved_todo_count || 0),
    activeFiles: Array.isArray(summary.active_files_detected) ? summary.active_files_detected : [],
    taskProgressPresent: !!summary.task_progress_present,
    suspiciouslyEmpty: !!summary.suspiciously_empty,
    warning: summary.warning || ""
  };
}

function sidebarHtml(webview, logoPath) {
  const nonce = getNonce();
  const logoSrc = webview.asWebviewUri(logoPath);
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
      --app-bg: var(--vscode-sideBar-background, var(--vscode-editor-background, #1f2328));
      --app-fg: var(--vscode-sideBar-foreground, var(--vscode-foreground, #d4d4d4));
      --border: var(--vscode-sideBarSectionHeader-border, var(--vscode-panel-border, rgba(127, 127, 127, 0.35)));
      --panel: var(--vscode-editorWidget-background, var(--vscode-sideBarSectionHeader-background, var(--app-bg)));
      --card: var(--vscode-input-background, var(--app-bg));
      --muted: var(--vscode-descriptionForeground, var(--vscode-disabledForeground, #8b949e));
      --button: var(--vscode-button-background, #0e639c);
      --button-fg: var(--vscode-button-foreground, #ffffff);
      --button-hover: var(--vscode-button-hoverBackground, #1177bb);
      --secondary: var(--vscode-button-secondaryBackground, var(--vscode-input-background, rgba(127, 127, 127, 0.14)));
      --secondary-fg: var(--vscode-button-secondaryForeground, var(--app-fg));
      --secondary-hover: var(--vscode-button-secondaryHoverBackground, var(--vscode-list-hoverBackground, rgba(127, 127, 127, 0.22)));
      --progress-bg: var(--vscode-progressBar-background, rgba(127, 127, 127, 0.28));
      --error: var(--vscode-errorForeground, #f85149);
      --ok: var(--vscode-testing-iconPassed, #3fb950);
      --warn: var(--vscode-testing-iconQueued, #d29922);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--app-fg);
      background: var(--app-bg);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
    }

    .shell {
      min-width: 0;
    }

    header,
    section,
    details.panel {
      padding: 12px;
      border-bottom: 1px solid var(--border);
    }

    header {
      display: flex;
      align-items: center;
      gap: 9px;
    }

    .brand {
      min-width: 0;
      display: grid;
      gap: 1px;
    }

    .hero {
      display: grid;
      gap: 11px;
      padding-top: 10px;
      background: var(--panel);
    }

    .hero-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 82px;
      gap: 10px;
      align-items: stretch;
    }

    .hero-copy {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      margin-top: 4px;
      overflow-wrap: anywhere;
    }

    .health-card {
      display: grid;
      place-items: center;
      min-width: 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 7px;
      color: var(--app-fg);
      background: var(--card);
    }

    .health-label {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .health-value {
      font-size: 22px;
      font-weight: 700;
      line-height: 1.1;
    }

    .hero-state-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 7px;
    }

    .state-pill {
      min-width: 0;
      border: 1px solid var(--border);
      border-radius: 7px;
      padding: 7px;
      color: var(--app-fg);
      background: var(--card);
    }

    .state-pill span {
      display: block;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .state-pill strong {
      display: block;
      margin-top: 2px;
      font-size: 12px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }

    .hero-card {
      display: grid;
      gap: 8px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      color: var(--app-fg);
      background: var(--card);
    }

    .hero-card-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-weight: 600;
    }

    .progress-track {
      height: 7px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--progress-bg);
      opacity: 0.9;
    }

    .progress-fill {
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: var(--button);
      transition: width 160ms ease-out;
    }

    .next-step {
      display: grid;
      gap: 2px;
      border-left: 3px solid var(--button);
      padding-left: 8px;
    }

    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }

    .stat-grid + .list {
      margin-top: 10px;
    }

    .stat-card {
      display: grid;
      gap: 4px;
      min-width: 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 9px;
      color: var(--app-fg);
      background: var(--panel);
    }

    .stat-card.featured {
      grid-column: 1 / -1;
      padding: 11px;
      background: var(--card);
    }

    .stat-value {
      font-size: 18px;
      font-weight: 700;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }

    .stat-label {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.3;
    }

    .stat-caption {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .mini-meter {
      height: 5px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--progress-bg);
    }

    .mini-meter-fill {
      height: 100%;
      width: 0%;
      border-radius: inherit;
      background: var(--ok);
      transition: width 160ms ease-out;
    }

    .mini-meter-fill[data-tone="warn"] {
      background: var(--warn);
    }

    .mini-meter-fill[data-tone="error"] {
      background: var(--error);
    }

    .insight-row {
      border-left: 3px solid var(--button);
      padding-left: 8px;
    }

    .insight-row[data-tone="ok"] {
      border-left-color: var(--ok);
    }

    .insight-row[data-tone="warn"] {
      border-left-color: var(--warn);
    }

    .insight-row[data-tone="error"] {
      border-left-color: var(--error);
    }

    img {
      width: 24px;
      height: 24px;
      border-radius: 5px;
      flex: 0 0 auto;
    }

    h1,
    h2 {
      margin: 0;
      color: var(--app-fg);
      font-size: 13px;
      font-weight: 600;
    }

    h1 {
      font-size: 14px;
    }

    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }

    details.panel > summary.section-head {
      margin: 0 0 8px;
      list-style: none;
      cursor: pointer;
    }

    details.panel > summary.section-head::-webkit-details-marker {
      display: none;
    }

    details.panel > summary.section-head::after {
      content: "+";
      min-width: 18px;
      color: var(--muted);
      text-align: right;
    }

    details.panel[open] > summary.section-head::after {
      content: "-";
    }

    .status {
      display: inline-flex;
      align-items: center;
      min-width: 72px;
      justify-content: center;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 3px 7px;
      font-size: 11px;
      color: var(--muted);
      background: var(--card);
    }

    .status[data-state="Running"] {
      color: var(--ok);
    }

    .status[data-state="Starting"] {
      color: var(--warn);
    }

    .status[data-state="Error"] {
      color: var(--error);
    }

    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 7px;
      margin-top: 10px;
    }

    .quick-actions {
      margin-top: 0;
    }

    .quick-actions button {
      min-height: 40px;
    }

    button {
      width: 100%;
      min-height: 28px;
      border: 1px solid var(--border);
      border-radius: 5px;
      padding: 5px 8px;
      color: var(--secondary-fg);
      background: var(--secondary);
      font: inherit;
      cursor: pointer;
      text-align: center;
    }

    .command-button {
      display: grid;
      gap: 1px;
      align-content: center;
      text-align: left;
    }

    .button-main,
    .button-meta {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .button-main {
      color: inherit;
      font-weight: 600;
    }

    .button-meta {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.25;
    }

    button:hover {
      background: var(--secondary-hover);
    }

    button:focus-visible {
      outline: 1px solid var(--button);
      outline-offset: 2px;
    }

    button:disabled {
      opacity: 0.72;
      cursor: default;
    }

    button:disabled:hover {
      background: var(--secondary);
    }

    button.primary:disabled:hover {
      background: var(--button);
    }

    .hero-server-action {
      min-height: 34px;
    }

    .quick-task {
      display: grid;
      gap: 8px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      background: var(--card);
    }

    .quick-task label,
    .task-options label {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.3;
    }

    .quick-task textarea {
      width: 100%;
      min-height: 78px;
      max-height: 160px;
      resize: vertical;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px;
      color: var(--app-fg);
      background: var(--app-bg);
      font: inherit;
      line-height: 1.4;
    }

    .quick-task textarea:focus-visible {
      outline: 1px solid var(--button);
      outline-offset: 2px;
    }

    .task-options {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    button[data-state="Running"]::before {
      content: "OK ";
    }

    button[data-state="Starting"]::before {
      content: "... ";
    }

    button.primary {
      grid-column: 1 / -1;
      border-color: transparent;
      color: var(--button-fg);
      background: var(--button);
      font-weight: 600;
    }

    button.primary:hover {
      background: var(--button-hover);
    }

    .detail,
    .meta {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }

    .list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .row {
      display: grid;
      gap: 2px;
      padding: 6px 8px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--card);
    }

    .main {
      color: var(--app-fg);
      overflow-wrap: anywhere;
    }

    .empty {
      color: var(--muted);
      font-size: 12px;
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <img src="${logoSrc}" alt="">
      <div class="brand">
        <h1>Agent Hub</h1>
        <div class="meta" id="extensionVersion">VS Code extension</div>
      </div>
    </header>
    <section class="hero">
      <div class="hero-head">
        <div>
          <h2>Control center</h2>
          <div class="hero-copy" id="heroSummary">Checking workspace status...</div>
        </div>
        <div class="health-card" title="Health score combines provider availability, success rate, fallbacks, permissions, and context pressure.">
          <span class="health-label">Health</span>
          <strong class="health-value" id="heroHealthScore">--</strong>
        </div>
      </div>
      <div class="hero-state-strip">
        <div class="state-pill">
          <span>Mode</span>
          <strong id="heroMode">cloud</strong>
        </div>
        <div class="state-pill">
          <span>Approval</span>
          <strong id="heroApproval">ask</strong>
        </div>
        <div class="state-pill">
          <span>Providers</span>
          <strong id="heroProviders">0/0</strong>
        </div>
      </div>
      <div class="hero-card">
        <div class="hero-card-title">
          <span>Setup progress</span>
          <span class="status" id="setupProgressText">0%</span>
        </div>
        <div class="progress-track" aria-hidden="true"><div class="progress-fill" id="setupProgressFill"></div></div>
        <div class="next-step">
          <div class="main" id="nextStepTitle">Checking setup...</div>
          <div class="meta" id="nextStepDetail">Agent Hub is collecting local status.</div>
        </div>
      </div>
      <form class="quick-task" id="quickTaskForm">
        <label for="quickTaskInput">Task</label>
        <textarea id="quickTaskInput" placeholder="Fix a bug, explain the current file, add a feature, or inspect the workspace"></textarea>
        <div class="task-options">
          <label><input id="quickTaskIncludeSelection" type="checkbox" checked> Include selection</label>
        </div>
        <button class="primary" id="quickTaskSend" type="submit">Start &amp; Send</button>
      </form>
      <button class="primary hero-server-action" id="heroServerAction" type="button" data-state="Stopped">Start Agent Hub</button>
      <div class="actions quick-actions">
        <button class="command-button" id="openChat" type="button" title="Open Agent Hub chat">
          <span class="button-main">Chat</span>
          <span class="button-meta">Workspace</span>
        </button>
        <button class="command-button" id="askAgent" type="button" title="Ask the default route">
          <span class="button-main">Ask</span>
          <span class="button-meta">Default route</span>
        </button>
        <button class="command-button" id="codeAgent" type="button" title="Run the coding agent">
          <span class="button-main">Code</span>
          <span class="button-meta">Agent loop</span>
        </button>
        <button class="command-button" id="explainFile" type="button" title="Explain the current file">
          <span class="button-main">Explain</span>
          <span class="button-meta">Current file</span>
        </button>
      </div>
    </section>
    <details class="panel">
      <summary class="section-head">
        <h2>Statistics</h2>
        <span class="status" id="statsHealth">Waiting</span>
      </summary>
      <div class="stat-grid" id="statsGrid"></div>
      <ul class="list" id="insightList"></ul>
    </details>
    <details class="panel" open>
      <summary class="section-head">
        <h2>Server</h2>
        <span class="status" id="serverStatus">Stopped</span>
      </summary>
      <div class="detail" id="serverDetail">Checking Agent Hub...</div>
      <ul class="list" id="onboardingList"></ul>
      <div class="actions">
        <button class="primary" id="startServer" type="button" data-primary-action="start-server">Start Server</button>
        <button id="stopServer" type="button">Stop Server</button>
        <button id="restartServer" type="button">Restart Server</button>
        <button id="checkHealth" type="button">Check Health</button>
      </div>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Permissions</h2>
      </summary>
      <div class="detail" id="permissionDetail">Approval: ask</div>
      <ul class="list" id="permissionList"></ul>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Models / Providers</h2>
      </summary>
      <div class="detail" id="activeModel">No active model yet</div>
      <ul class="list" id="routingChain"></ul>
      <ul class="list" id="providerList"></ul>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Limits</h2>
      </summary>
      <ul class="list" id="limitList"></ul>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Token Usage</h2>
      </summary>
      <div class="detail" id="tokenUsage">No token usage yet</div>
      <div class="detail" id="contextDiagnostics"></div>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Activity</h2>
      </summary>
      <ul class="list" id="activityList"></ul>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Logs</h2>
      </summary>
      <div class="detail" id="logDetail">Open the output channel for live logs.</div>
      <div class="actions">
        <button id="openOutput" type="button">Open Logs</button>
      </div>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Settings</h2>
      </summary>
      <div class="detail" id="settingsDetail"></div>
      <div class="actions">
        <button id="openSettings" type="button">Open Settings</button>
        <button id="copyClineConfig" type="button">Copy Cline Config</button>
        <button id="testClineConnection" type="button">Test Cline Connection</button>
        <button id="showClineSetup" type="button">Show Cline Setup</button>
        <button id="copyClaudeCodeConfig" type="button">Copy Claude Code Config</button>
        <button id="testAnthropicEndpoint" type="button">Test Anthropic Endpoint</button>
        <button id="showClaudeCodeSetup" type="button">Show Claude Code Setup</button>
      </div>
    </details>
  </div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const extensionVersion = document.getElementById("extensionVersion");
    const heroSummary = document.getElementById("heroSummary");
    const heroHealthScore = document.getElementById("heroHealthScore");
    const heroMode = document.getElementById("heroMode");
    const heroApproval = document.getElementById("heroApproval");
    const heroProviders = document.getElementById("heroProviders");
    const setupProgressText = document.getElementById("setupProgressText");
    const setupProgressFill = document.getElementById("setupProgressFill");
    const nextStepTitle = document.getElementById("nextStepTitle");
    const nextStepDetail = document.getElementById("nextStepDetail");
    const statsHealth = document.getElementById("statsHealth");
    const statsGrid = document.getElementById("statsGrid");
    const insightList = document.getElementById("insightList");
    const heroServerAction = document.getElementById("heroServerAction");
    const serverStatus = document.getElementById("serverStatus");
    const serverDetail = document.getElementById("serverDetail");
    const onboardingList = document.getElementById("onboardingList");
    const activeModel = document.getElementById("activeModel");
    const routingChain = document.getElementById("routingChain");
    const providerList = document.getElementById("providerList");
    const permissionDetail = document.getElementById("permissionDetail");
    const permissionList = document.getElementById("permissionList");
    const limitList = document.getElementById("limitList");
    const tokenUsage = document.getElementById("tokenUsage");
    const contextDiagnostics = document.getElementById("contextDiagnostics");
    const activityList = document.getElementById("activityList");
    const logDetail = document.getElementById("logDetail");
    const settingsDetail = document.getElementById("settingsDetail");
    const quickTaskForm = document.getElementById("quickTaskForm");
    const quickTaskInput = document.getElementById("quickTaskInput");
    const quickTaskIncludeSelection = document.getElementById("quickTaskIncludeSelection");

    function post(type) {
      vscode.postMessage({ type });
    }

    function setText(element, value) {
      element.textContent = value || "";
    }

    function renderDashboard(data) {
      const dashboard = data || {};
      const status = dashboard.status || "Stopped";
      serverStatus.textContent = status;
      serverStatus.dataset.state = status;
      setText(extensionVersion, dashboard.extensionVersion ? "v" + dashboard.extensionVersion : "VS Code extension");
      setText(heroMode, compactModeText(dashboard.agentProviderMode || "cloud", dashboard.agentMode || "agent"));
      setText(heroApproval, dashboard.approvalMode || "ask");
      setText(heroProviders, providerCountText(dashboard.statistics || {}));
      renderServerControls(status, dashboard);
      renderSetupSummary(dashboard);
      renderStatistics(dashboard.statistics || {}, dashboard.insights || [], status);
      renderOnboarding(dashboard.onboarding || []);
      setText(activeModel, activeModelText(dashboard.activeModel));
      renderRoutingChain(dashboard.routingChain || []);
      renderProviderRows(dashboard.providers || []);
      renderPermissions(dashboard.permissions || {});
      renderLimitRows(dashboard.limits || []);
      setText(tokenUsage, tokenUsageText(dashboard.tokenUsage || {}));
      setText(contextDiagnostics, contextDiagnosticsText(dashboard.contextDiagnostics || {}));
      renderActivityRows(dashboard.activity || []);
      setText(logDetail, dashboard.logs || "Open the output channel for live logs.");
      setText(settingsDetail, "Mode: " + (dashboard.agentProviderMode || "cloud") + " / " + (dashboard.agentMode || "agent") + ". Approval: " + (dashboard.approvalMode || "ask") + ". Auto-start: " + (dashboard.autoStart ? "on" : "off") + ".");
    }

    function compactModeText(providerMode, agentMode) {
      const mode = String(providerMode || "cloud");
      const agent = String(agentMode || "agent").replace("-agent", "");
      return mode + " / " + agent;
    }

    function providerCountText(stats) {
      return Number(stats.providersAvailable || 0) + "/" + Number(stats.providersTotal || 0);
    }

    function renderServerControls(status, dashboard) {
      const serverUrl = dashboard.serverUrl || "Agent Hub";
      const isRunning = status === "Running";
      const isStarting = status === "Starting";
      const isError = status === "Error";

      if (isRunning) {
        heroServerAction.textContent = "Server running - Open Chat";
        heroServerAction.disabled = false;
        heroServerAction.dataset.action = "openChat";
        setText(heroSummary, "Online at " + serverUrl + ".");
        setText(serverDetail, "Online and ready for requests.");
      } else if (isStarting) {
        heroServerAction.textContent = "Starting Agent Hub...";
        heroServerAction.disabled = true;
        heroServerAction.dataset.action = "";
        setText(heroSummary, "Starting local backend.");
        setText(serverDetail, "Starting local backend. Logs will show progress if this takes a moment.");
      } else if (isError) {
        heroServerAction.textContent = "Restart Agent Hub";
        heroServerAction.disabled = false;
        heroServerAction.dataset.action = "restartServer";
        setText(heroSummary, dashboard.statusText || "Agent Hub needs attention.");
        setText(serverDetail, dashboard.statusText || "Agent Hub needs attention. Open logs or restart the server.");
      } else {
        heroServerAction.textContent = "Start Agent Hub";
        heroServerAction.disabled = false;
        heroServerAction.dataset.action = "startServer";
        setText(heroSummary, "Offline. Ready to start at " + serverUrl + ".");
        setText(serverDetail, "Offline. Start the local server for " + serverUrl + ".");
      }
      heroServerAction.dataset.state = status;

      const startButton = document.getElementById("startServer");
      const stopButton = document.getElementById("stopServer");
      const restartButton = document.getElementById("restartServer");
      startButton.textContent = isRunning ? "Server Running" : isStarting ? "Starting..." : isError ? "Try Start Again" : "Start Server";
      startButton.disabled = isRunning || isStarting;
      startButton.dataset.state = status;
      stopButton.disabled = !isRunning && !isStarting;
      restartButton.textContent = isRunning ? "Restart / Reload" : "Restart Server";
      restartButton.disabled = isStarting;
    }

    function renderSetupSummary(dashboard) {
      const rows = Array.isArray(dashboard.onboarding) ? dashboard.onboarding : [];
      const complete = rows.filter((row) => row && row.ok).length;
      const total = rows.length || 1;
      const percent = Math.round((complete / total) * 100);
      setupProgressText.textContent = percent + "%";
      setupProgressText.dataset.state = percent === 100 ? "Running" : percent >= 50 ? "Starting" : "Stopped";
      setupProgressFill.style.width = percent + "%";

      const next = rows.find((row) => row && !row.ok);
      if (dashboard.status === "Running" && percent === 100) {
        nextStepTitle.textContent = "Ready to work";
        nextStepDetail.textContent = "Use the main server button or any quick action to start a task.";
        return;
      }
      if (dashboard.status === "Running") {
        nextStepTitle.textContent = next ? "Next: " + next.label : "Ready to work";
        nextStepDetail.textContent = next ? next.detail : "Use the main server button or any quick action to start a task.";
        return;
      }
      nextStepTitle.textContent = next ? "Next: " + next.label : "Start Agent Hub";
      nextStepDetail.textContent = next ? next.detail : "Click Start Server after setup checks pass.";
    }

    function renderStatistics(stats, insights, status) {
      statsGrid.textContent = "";
      const score = status === "Running" ? Number(stats.healthScore || 0) : 0;
      heroHealthScore.textContent = status === "Running" ? String(score) : "--";
      statsHealth.textContent = status === "Running" ? healthLabel(stats) : "Offline";
      statsHealth.dataset.state = statisticsStatusState(stats, status);

      const cards = [
        {
          value: status === "Running" ? String(score) : "--",
          label: "health score",
          caption: healthCaption(stats, status),
          percent: score,
          featured: true
        },
        {
          value: Number(stats.providersAvailable || 0) + "/" + Number(stats.providersTotal || 0),
          label: "providers available",
          caption: compactNumber(stats.providersUnavailable || 0) + " unavailable, " + compactNumber(stats.providersDegraded || 0) + " degraded",
          percent: Number(stats.providerAvailabilityPercent || 0)
        },
        {
          value: Number(stats.totalCalls || 0) ? Number(stats.successRate || 0) + "%" : "--",
          label: "provider success rate",
          caption: compactNumber(stats.successfulCalls || 0) + " ok / " + compactNumber(stats.failedCalls || 0) + " failed",
          percent: Number(stats.successRate || 0)
        },
        {
          value: compactNumber(stats.totalTokens || 0),
          label: "tokens used",
          caption: compactNumber(stats.inputTokens || 0) + " input / " + compactNumber(stats.outputTokens || 0) + " output"
        },
        {
          value: compactNumber(stats.averageTokensPerCall || 0),
          label: "avg tokens per call",
          caption: compactNumber(stats.totalCalls || 0) + " provider call(s)"
        },
        {
          value: compactNumber(stats.toolExecutions || 0),
          label: "workspace tool runs",
          caption: compactNumber(stats.workflows || 0) + " workflow event(s)"
        },
        {
          value: compactNumber(stats.routingFallbacks || 0),
          label: "routing fallbacks",
          caption: compactNumber(stats.streamFailures || 0) + " stream failure(s)"
        },
        {
          value: Number(stats.workflowSuccessAttempts || 0) ? Number(stats.workflowSuccessRate || 0) + "%" : "--",
          label: "workflow success",
          caption: compactNumber(stats.failedRequestsRecovered || 0) + " recovered by failover",
          percent: Number(stats.workflowSuccessRate || 0)
        },
        {
          value: stats.bestWorkflow || "--",
          label: "best workflow",
          caption: Number(stats.bestWorkflowAttempts || 0)
            ? Number(stats.bestWorkflowSuccessRate || 0) + "% over " + compactNumber(stats.bestWorkflowAttempts || 0) + " sample(s)"
            : "waiting for workflow samples"
        },
        {
          value: stats.bestLearnedModel || "learning",
          label: "best learned model",
          caption: Number(stats.adaptiveAverageLatencyMs || 0)
            ? Math.round(Number(stats.adaptiveAverageLatencyMs || 0)) + " ms avg / " + Number(stats.adaptiveAverageRetries || 0).toFixed(2) + " retries"
            : "waiting for samples"
        },
        {
          value: stats.bestCodingModel || "--",
          label: "best coding model",
          caption: Number(stats.bestCodingModelAttempts || 0)
            ? Number(stats.bestCodingModelSuccessRate || 0) + "% over " + compactNumber(stats.bestCodingModelAttempts || 0) + " sample(s)"
            : "waiting for coding samples"
        },
        {
          value: stats.bestPlannerModel || "--",
          label: "best planner",
          caption: Number(stats.bestPlannerAttempts || 0)
            ? compactNumber(stats.bestPlannerAttempts || 0) + " planner sample(s)"
            : "waiting for planner samples"
        },
        {
          value: stats.bestWorkerModel || "--",
          label: "best worker",
          caption: Number(stats.bestWorkerAttempts || 0)
            ? compactNumber(stats.bestWorkerAttempts || 0) + " worker sample(s)"
            : "waiting for worker samples"
        },
        {
          value: stats.mostEffectiveProvider || "--",
          label: "effective provider",
          caption: Number(stats.mostEffectiveProviderAttempts || 0)
            ? Number(stats.mostEffectiveProviderSuccessRate || 0) + "% over " + compactNumber(stats.mostEffectiveProviderAttempts || 0) + " sample(s)"
            : "waiting for provider samples"
        },
        {
          value: stats.averageKnownCost === null || stats.averageKnownCost === undefined ? "--" : "$" + Number(stats.averageKnownCost || 0).toFixed(4),
          label: "avg known cost",
          caption: "adaptive routing cost signal"
        },
        {
          value: compactNumber(stats.permissionEvents || 0),
          label: "permission events",
          caption: compactNumber(stats.permissionAllowed || 0) + " allowed / " + compactNumber(stats.permissionDenied || 0) + " denied"
        },
        {
          value: compactNumber(stats.requests || 0),
          label: "recent request traces",
          caption: compactNumber(stats.recentFailures || 0) + " recent failure(s)"
        },
        {
          value: compactNumber(stats.contextIncoming || 0),
          label: "latest context tokens",
          caption: compactNumber(stats.contextProtected || 0) + " protected"
        }
      ];
      for (const card of cards) {
        statsGrid.append(statCard(card));
      }

      insightList.textContent = "";
      const rows = Array.isArray(insights) ? insights : [];
      for (const row of rows.slice(0, 5)) {
        insightList.append(insightElement(row));
      }
      if (!rows.length) {
        insightList.append(emptyRow("No statistics yet"));
      }
    }

    function healthCaption(stats, status) {
      if (status !== "Running") {
        return "Start the server to collect live statistics.";
      }
      if (Number(stats.providersTotal || 0) && !Number(stats.providersAvailable || 0)) {
        return "No available provider candidates.";
      }
      if (Number(stats.recentFailures || 0) || Number(stats.providersDegraded || 0)) {
        return "Check insights before a long request.";
      }
      return "Provider, routing, permission, and context signals look stable.";
    }

    function healthLabel(stats) {
      if (Number(stats.providersTotal || 0) && !Number(stats.providersAvailable || 0)) {
        return "Needs attention";
      }
      if (Number(stats.providersDegraded || 0) || Number(stats.recentFailures || 0)) {
        return "Degraded";
      }
      return "Healthy";
    }

    function statisticsStatusState(stats, status) {
      if (status !== "Running") {
        return status;
      }
      if (Number(stats.providersTotal || 0) && !Number(stats.providersAvailable || 0)) {
        return "Error";
      }
      if (Number(stats.providersDegraded || 0) || Number(stats.recentFailures || 0)) {
        return "Starting";
      }
      return "Running";
    }

    function statCard(card) {
      const item = document.createElement("div");
      item.className = "stat-card";
      if (card.featured) {
        item.classList.add("featured");
      }
      const value = document.createElement("div");
      value.className = "stat-value";
      value.textContent = card.value;
      const label = document.createElement("div");
      label.className = "stat-label";
      label.textContent = card.label;
      item.append(value, label);
      if (card.caption) {
        const caption = document.createElement("div");
        caption.className = "stat-caption";
        caption.textContent = card.caption;
        item.append(caption);
      }
      if (typeof card.percent === "number") {
        const meter = document.createElement("div");
        meter.className = "mini-meter";
        const fill = document.createElement("div");
        fill.className = "mini-meter-fill";
        fill.style.width = Math.max(0, Math.min(100, card.percent)) + "%";
        fill.dataset.tone = card.percent >= 80 ? "ok" : card.percent >= 50 ? "warn" : "error";
        meter.append(fill);
        item.append(meter);
      }
      return item;
    }

    function insightElement(row) {
      const item = rowElement(row.main, row.meta);
      item.classList.add("insight-row");
      item.dataset.tone = row.tone || "info";
      return item;
    }

    function compactNumber(value) {
      const number = Number(value || 0);
      if (!Number.isFinite(number)) {
        return "0";
      }
      if (Math.abs(number) >= 1000000) {
        return (number / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
      }
      if (Math.abs(number) >= 1000) {
        return (number / 1000).toFixed(1).replace(/\.0$/, "") + "k";
      }
      return String(number);
    }

    function activeModelText(row) {
      if (!row || (!row.model && !row.provider && !row.agent)) {
        return "No active model yet";
      }
      const provider = row.provider ? row.provider + " / " : "";
      const agent = row.agent ? " (" + row.agent + ")" : "";
      return "Active: " + provider + (row.model || "model pending") + agent;
    }

    function renderRoutingChain(rows) {
      routingChain.textContent = "";
      if (!rows.length) {
        return;
      }
      for (const row of rows.slice(0, 4)) {
        routingChain.append(rowElement(
          [row.provider || row.agent || "provider", row.model || ""].filter(Boolean).join(" / "),
          [row.available ? "active candidate" : "fallback candidate", row.reason || ""].filter(Boolean).join(" - ")
        ));
      }
    }

    function renderOnboarding(rows) {
      onboardingList.textContent = "";
      if (!rows.length) {
        return;
      }
      for (const row of rows) {
        onboardingList.append(rowElement(
          (row.ok ? "[ok] " : "[ ] ") + (row.label || "Setup"),
          row.detail || ""
        ));
      }
    }

    function renderProviderRows(rows) {
      providerList.textContent = "";
      if (!rows.length) {
        providerList.append(emptyRow("No provider health yet"));
        return;
      }
      for (const row of rows.slice(0, 6)) {
        providerList.append(rowElement(
          [row.provider || row.agent || "provider", row.model || ""].filter(Boolean).join(" / "),
          [
            row.agent ? "agent " + row.agent : "",
            row.available ? "available" : "unavailable",
            row.degraded ? "degraded" : ""
          ].filter(Boolean).join(" - ")
        ));
      }
    }

    function renderLimitRows(rows) {
      limitList.textContent = "";
      if (!rows.length) {
        limitList.append(emptyRow("No remaining limits reported yet"));
        return;
      }
      for (const row of rows.slice(0, 6)) {
        limitList.append(rowElement(
          [row.provider || row.agent || "provider", row.model || ""].filter(Boolean).join(" / "),
          limitText(row)
        ));
      }
    }

    function renderPermissions(state) {
      const flags = [];
      flags.push("Approval: " + (state.approvalMode || "ask"));
      if (state.safeMode) {
        flags.push("safe mode");
      }
      if (state.readonlyMode) {
        flags.push("readonly");
      }
      if (state.secretDetection) {
        flags.push("secret detection");
      }
      if (state.dangerousCommandBlocking) {
        flags.push("command blocking");
      }
      setText(permissionDetail, flags.join(" - "));
      permissionList.textContent = "";
      const recent = Array.isArray(state.recent) ? state.recent.slice(-4).reverse() : [];
      if (!recent.length) {
        permissionList.append(emptyRow("No permission events yet"));
        return;
      }
      for (const item of recent) {
        permissionList.append(rowElement(
          item.tool || item.provider || item.type || "permission",
          [item.category || "", item.risk_level || "", item.allowed ? "allowed" : item.requires_approval ? "approval required" : item.denied ? "denied" : ""].filter(Boolean).join(" - ")
        ));
      }
    }

    function tokenUsageText(row) {
      const total = Number(row.totalTokens || 0);
      const input = Number(row.inputTokens || 0);
      const output = Number(row.outputTokens || 0);
      const remaining = row.remainingTokens === null || row.remainingTokens === undefined
        ? ""
        : " - remaining " + row.remainingTokens;
      if (!total && !input && !output) {
        return "No token usage yet";
      }
      return "Used " + total + " tokens (in " + input + ", out " + output + ")" + remaining;
    }

    function contextDiagnosticsText(row) {
      const incoming = Number(row.incoming || 0);
      const preserved = Number(row.preserved || 0);
      const compacted = Number(row.compacted || 0);
      const protectedTokens = Number(row.protected || 0);
      const files = Array.isArray(row.activeFiles) ? row.activeFiles.length : 0;
      const warnings = [];
      if (row.suspiciouslyEmpty) {
        warnings.push("context looks empty");
      }
      if (!row.taskProgressPresent && incoming > 0) {
        warnings.push("task_progress missing");
      }
      const base = "Context: incoming " + incoming + ", preserved " + preserved + ", compacted " + compacted + ", protected " + protectedTokens + ", files " + files + ", todos " + Number(row.preservedTodos || 0) + ".";
      return warnings.length ? base + " Warning: " + warnings.join(", ") + "." : base;
    }

    function renderActivityRows(rows) {
      activityList.textContent = "";
      if (!rows.length) {
        activityList.append(emptyRow("No recent activity"));
        return;
      }
      for (const row of rows.slice(0, 6)) {
        activityList.append(rowElement(row.main, row.meta));
      }
    }

    function limitText(row) {
      const parts = [];
      pushRemaining(parts, "requests", row.requests_remaining);
      pushRemaining(parts, "tokens", row.tokens_remaining);
      pushRemaining(parts, "credits", row.credits_remaining);
      pushRemaining(parts, "quota", row.quota_remaining);
      if (!parts.length && row.remaining === "unknown") {
        parts.push("remaining unknown");
      }
      const reset = timeText(row.rate_limit_reset_at || row.reset_at);
      const cooldown = timeText(row.cooldown_until);
      if (reset) {
        parts.push("reset " + reset);
      }
      if (cooldown) {
        parts.push("cooldown " + cooldown);
      }
      if (row.unavailable_reason) {
        parts.push(row.unavailable_reason);
      }
      return parts.length ? parts.join(" - ") : "No limit data reported";
    }

    function pushRemaining(parts, label, value) {
      if (value === null || value === undefined || value === "") {
        return;
      }
      parts.push(label + " " + value);
    }

    function timeText(value) {
      const number = Number(value);
      if (!Number.isFinite(number) || number <= 0) {
        return "";
      }
      const seconds = Math.max(0, Math.round(number - Date.now() / 1000));
      if (seconds <= 0) {
        return "now";
      }
      if (seconds < 60) {
        return "in " + seconds + "s";
      }
      if (seconds < 3600) {
        return "in " + Math.round(seconds / 60) + "m";
      }
      return "in " + Math.round(seconds / 3600) + "h";
    }

    function rowElement(mainText, metaText) {
      const item = document.createElement("li");
      item.className = "row";
      const main = document.createElement("div");
      main.className = "main";
      main.textContent = mainText || "Unknown";
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = metaText || "";
      item.append(main, meta);
      return item;
    }

    function emptyRow(text) {
      const item = document.createElement("li");
      item.className = "empty";
      item.textContent = text;
      return item;
    }

    quickTaskForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = quickTaskInput.value.trim();
      if (!text) {
        quickTaskInput.focus();
        return;
      }
      quickTaskInput.value = "";
      vscode.postMessage({
        type: "quickTask",
        text,
        includeSelection: quickTaskIncludeSelection.checked
      });
    });

    heroServerAction.addEventListener("click", () => {
      const action = heroServerAction.dataset.action || "startServer";
      if (action) {
        post(action);
      }
    });
    document.getElementById("openChat").addEventListener("click", () => post("openChat"));
    document.getElementById("askAgent").addEventListener("click", () => post("askAgent"));
    document.getElementById("codeAgent").addEventListener("click", () => post("codeAgent"));
    document.getElementById("explainFile").addEventListener("click", () => post("explainFile"));
    document.getElementById("startServer").addEventListener("click", () => post("startServer"));
    document.getElementById("stopServer").addEventListener("click", () => post("stopServer"));
    document.getElementById("restartServer").addEventListener("click", () => post("restartServer"));
    document.getElementById("checkHealth").addEventListener("click", () => post("checkHealth"));
    document.getElementById("openOutput").addEventListener("click", () => post("openOutput"));
    document.getElementById("openSettings").addEventListener("click", () => post("openSettings"));
    document.getElementById("copyClineConfig").addEventListener("click", () => post("copyClineConfig"));
    document.getElementById("testClineConnection").addEventListener("click", () => post("testClineConnection"));
    document.getElementById("showClineSetup").addEventListener("click", () => post("showClineSetup"));
    document.getElementById("copyClaudeCodeConfig").addEventListener("click", () => post("copyClaudeCodeConfig"));
    document.getElementById("testAnthropicEndpoint").addEventListener("click", () => post("testAnthropicEndpoint"));
    document.getElementById("showClaudeCodeSetup").addEventListener("click", () => post("showClaudeCodeSetup"));

    window.addEventListener("message", (event) => {
      const message = event.data;
      if (message && message.type === "dashboard") {
        renderDashboard(message.dashboard);
      }
    });

    window.setInterval(() => post("refresh"), 10000);
    vscode.postMessage({ type: "ready" });
  </script>
</body>
</html>`;
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
  const selectedAgentMode = agentMode ? normalizeAgentMode(config.agentMode) : "route";
  const route = command === "research" ? config.researchRoute : codingAgentRoute(config);
  const context = participantContext(command, request);
  const task = participantTask(command, prompt, chatContext);
  if (!(await approveModelRequest({
    providerMode: config.agentProviderMode,
    contextText: context,
    source: "VS Code chat participant"
  }))) {
    stream.markdown("Agent Hub request cancelled because permission was not granted.");
    return { metadata: { command, ok: false, permission_denied: true } };
  }

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
    mode: selectedAgentMode,
    route,
    task,
    context,
    use_session_history: true,
    approval_mode: config.approvalMode,
    provider_approval_granted: true,
    metadata: {
      source: "vscode-chat-participant",
      command,
      agent_mode: selectedAgentMode
    }
  };
  applyOptionalMaxTokens(body, config);

  if (agentMode) {
    body.allow_shell_tools = config.allowShellTools;
    body.agent_max_steps = config.agentMaxSteps;
    body.coder_max_steps = config.agentMaxSteps;
    body.agent_context_budget_tokens = config.agentContextBudgetTokens;
    body.agent_context_compaction_enabled = config.agentContextCompactionEnabled;
    body.context_mode = config.contextMode;
    body.cline_compatibility_mode = config.clineCompatibilityMode;
    body.group_agent = {
      plan_candidates: config.groupPlanCandidates
    };
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

function openChat(context, request = null) {
  const queued = normalizeChatRequest(request);
  if (queued) {
    pendingChatRequests.push(queued);
  }
  if (chatPanel) {
    chatPanel.reveal(vscode.ViewColumn.Beside);
    flushPendingChatRequests(chatPanel);
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
  chatWebviewReady = false;
  chatPanel.onDidDispose(() => {
    chatPanel = null;
    chatWebviewReady = false;
  });
  chatPanel.webview.onDidReceiveMessage(
    (message) => handleChatMessage(chatPanel, message),
    undefined,
    context.subscriptions
  );
}

function normalizeChatRequest(value) {
  if (!value || typeof value !== "object") {
    return null;
  }
  const text = typeof value.text === "string" ? value.text.trim() : "";
  if (!text) {
    return null;
  }
  return {
    text,
    includeSelection: value.includeSelection !== false,
    providerMode: normalizeAgentProviderMode(value.providerMode || settings().agentProviderMode),
    autoSend: value.autoSend !== false
  };
}

function flushPendingChatRequests(panel) {
  if (!panel || !panel.webview || !chatWebviewReady || !pendingChatRequests.length) {
    return;
  }
  const requests = pendingChatRequests.splice(0);
  for (const request of requests) {
    panel.webview.postMessage({
      type: "queuedPrompt",
      ...request
    });
  }
}

async function handleChatMessage(panel, message) {
  if (!panel || !message || typeof message !== "object") {
    return;
  }

  if (message.type === "ready" || message.type === "status") {
    if (message.type === "ready") {
      chatWebviewReady = true;
    }
    const online = await isServerOnline();
    panel.webview.postMessage({
      type: "serverStatus",
      online,
      text: online ? "Agent Hub is online" : "Agent Hub is offline"
    });
    postChatSettings(panel);
    await postApiKeyStatus(panel);
    flushPendingChatRequests(panel);
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
    return;
  }

  if (message.type === "feedback") {
    await sendAdaptiveFeedback(panel, message);
  }
}

async function sendAdaptiveFeedback(panel, message) {
  const requestId = typeof message.requestId === "string" ? message.requestId.trim() : "";
  const rating = message.rating === "down" ? "down" : "up";
  if (!requestId) {
    return;
  }
  try {
    await requestJson("POST", "/v1/feedback", {
      request_id: requestId,
      rating,
      workflow_success: !!message.workflowSuccess
    });
    panel.webview.postMessage({
      type: "serverStatus",
      online: true,
      text: rating === "up" ? "Feedback saved. Agent Hub will learn from it." : "Feedback saved. Agent Hub will avoid repeats."
    });
  } catch (error) {
    output.appendLine(`Adaptive feedback failed: ${error.message}`);
  }
}

async function saveApiKeysFromWebview(panel, keys) {
  if (!(await requestPermission({
    category: "secret_edit",
    description: "Agent Hub wants to save provider API keys in VS Code Secret Storage.",
    resource: "VS Code Secret Storage",
    risk: "high"
  }))) {
    await postApiKeyStatus(panel, "Saving API keys was cancelled.");
    return;
  }
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
  if (!(await requestPermission({
    category: "secret_edit",
    description: "Agent Hub wants to clear saved provider API keys from VS Code Secret Storage.",
    resource: "VS Code Secret Storage",
    risk: "medium"
  }))) {
    await postApiKeyStatus(panel, "Clearing API keys was cancelled.");
    return;
  }
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
    agentMode: config.agentMode,
    approvalMode: config.approvalMode,
    groupPlanCandidates: config.groupPlanCandidates,
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
    if (!(await requestPermission({
      category: "config_edit",
      description: "Agent Hub wants to modify VS Code and Agent Hub configuration.",
      resource: next.workspaceSettings.configPath,
      risk: "medium",
      detail: "This may change provider routing, approval mode, model selections, and server settings."
    }))) {
      postChatSettings(panel, "Saving settings was cancelled.");
      return;
    }
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
      agentMode: normalizeAgentMode(input.agentMode || current.agentMode),
      approvalMode: normalizeApprovalMode(input.approvalMode || current.approvalMode),
      groupPlanCandidates: cleanSettingInteger(input.groupPlanCandidates, current.groupPlanCandidates, 1, 5),
      agentMaxSteps: cleanSettingInteger(input.agentMaxSteps, current.agentMaxSteps, 1, 100),
      allowShellTools: !!input.allowShellTools,
      maxTokens: cleanOptionalSettingInteger(input.maxTokens, current.maxTokens, 1, 200000),
      autoStart: !!input.autoStart
    },
    cloudSettings: {
      cloudRouteMode: normalizeCloudRouteMode(input.cloudRouteMode || "ollama-cloud"),
      apiKeyModelsEnabled: !!input.apiKeyModelsEnabled,
      freeCloudPresetsEnabled: !!input.freeCloudPresetsEnabled,
      freeOnly: !!input.freeOnly,
      enableLoadBalancing: !!input.enableLoadBalancing,
      exposeRoutingDetails: !!input.exposeRoutingDetails,
      codexModel: cleanSettingString(input.codexModel, DEFAULT_CODEX_MODEL),
      claudeModel: cleanSettingString(input.claudeModel, DEFAULT_CLAUDE_MODEL),
      geminiModel: cleanSettingString(input.geminiModel, DEFAULT_GEMINI_MODEL),
      chatgptModel: cleanSettingString(input.chatgptModel, DEFAULT_CHATGPT_MODEL),
      groqModel: cleanSettingString(input.groqModel, DEFAULT_GROQ_MODEL),
      openrouterModel: cleanSettingString(input.openrouterModel, DEFAULT_OPENROUTER_MODEL),
      cerebrasModel: cleanSettingString(input.cerebrasModel, DEFAULT_CEREBRAS_MODEL),
      mistralModel: cleanSettingString(input.mistralModel, DEFAULT_MISTRAL_MODEL),
      githubModelsModel: cleanSettingString(input.githubModelsModel, DEFAULT_GITHUB_MODELS_MODEL),
      huggingfaceModel: cleanSettingString(input.huggingfaceModel, DEFAULT_HUGGINGFACE_MODEL),
      nvidiaModel: cleanSettingString(input.nvidiaModel, DEFAULT_NVIDIA_MODEL),
      cloudflareModel: cleanSettingString(input.cloudflareModel, DEFAULT_CLOUDFLARE_MODEL)
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

function cleanOptionalSettingInteger(value, fallback, min, max) {
  if (value === null || value === undefined || String(value).trim() === "") {
    return null;
  }
  return cleanSettingInteger(value, fallback === undefined ? null : fallback, min, max);
}

function applyOptionalMaxTokens(body, config) {
  const value = config && Number(config.maxTokens);
  if (Number.isFinite(value) && value > 0) {
    body.max_tokens = Math.floor(value);
  }
  return body;
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
    freeCloudPresetsEnabled: false,
    freeOnly: true,
    enableLoadBalancing: true,
    exposeRoutingDetails: false,
    codexModel: DEFAULT_CODEX_MODEL,
    claudeModel: DEFAULT_CLAUDE_MODEL,
    geminiModel: DEFAULT_GEMINI_MODEL,
    chatgptModel: DEFAULT_CHATGPT_MODEL,
    groqModel: DEFAULT_GROQ_MODEL,
    openrouterModel: DEFAULT_OPENROUTER_MODEL,
    cerebrasModel: DEFAULT_CEREBRAS_MODEL,
    mistralModel: DEFAULT_MISTRAL_MODEL,
    githubModelsModel: DEFAULT_GITHUB_MODELS_MODEL,
    huggingfaceModel: DEFAULT_HUGGINGFACE_MODEL,
    nvidiaModel: DEFAULT_NVIDIA_MODEL,
    cloudflareModel: DEFAULT_CLOUDFLARE_MODEL
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
      freeCloudPresetsEnabled: freeCloudPresetsEnabledFromConfig(raw),
      freeOnly: raw.free_only !== false,
      enableLoadBalancing: raw.enable_load_balancing !== false,
      exposeRoutingDetails: raw.expose_routing_details === true,
      codexModel: modelForAgent(raw, "codex", DEFAULT_CODEX_MODEL),
      claudeModel: modelForAgent(raw, "claude", DEFAULT_CLAUDE_MODEL),
      geminiModel: modelForAgent(raw, "gemini", DEFAULT_GEMINI_MODEL),
      chatgptModel: modelForAgent(raw, "chatgpt", DEFAULT_CHATGPT_MODEL),
      groqModel: modelForAgent(raw, "groq-qwen3-32b", DEFAULT_GROQ_MODEL),
      openrouterModel: modelForAgent(raw, "openrouter-qwen-free", DEFAULT_OPENROUTER_MODEL),
      cerebrasModel: modelForAgent(raw, "cerebras-llama-3-3-70b", DEFAULT_CEREBRAS_MODEL),
      mistralModel: modelForAgent(raw, "mistral-small-latest", DEFAULT_MISTRAL_MODEL),
      githubModelsModel: modelForAgent(raw, "github-models-qwen3-coder", DEFAULT_GITHUB_MODELS_MODEL),
      huggingfaceModel: modelForAgent(raw, "huggingface-qwen3-coder", DEFAULT_HUGGINGFACE_MODEL),
      nvidiaModel: modelForAgent(raw, "nvidia-nemotron", DEFAULT_NVIDIA_MODEL),
      cloudflareModel: modelForAgent(raw, "cloudflare-llama-3-1-8b", DEFAULT_CLOUDFLARE_MODEL)
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

function freeCloudPresetsEnabledFromConfig(data) {
  return Array.isArray(data && data.agents)
    ? data.agents.some((item) => (
      item &&
      typeof item === "object" &&
      FREE_CLOUD_AGENT_NAMES.includes(item.name) &&
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
  panel.webview.postMessage({
    type: "serverStatus",
    online: false,
    text: "Restarting Agent Hub..."
  });
  await restartServer();
  const online = await isServerOnline();
  panel.webview.postMessage({
    type: "serverStatus",
    online,
    text: online ? "Agent Hub restarted" : "Agent Hub did not respond after restart"
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
  if (!(await requestPermission({
    category: "model_download",
    description: "Agent Hub wants to download an Ollama model.",
    resource: `${option.model} (${option.size})`,
    risk: "medium",
    detail: "This runs 'ollama pull' and downloads model files to your machine."
  }))) {
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      text: "Model download cancelled."
    });
    return;
  }
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
    if (!(await requestPermission({
      category: "config_edit",
      description: "Agent Hub wants to update the local model selection in its config.",
      resource: source.model,
      risk: "medium"
    }))) {
      panel.webview.postMessage({
        type: "modelPullStatus",
        running: false,
        text: "Local model selection was not saved."
      });
      return;
    }
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
  const agentMode = normalizeAgentMode(config.agentMode);
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
  if (!(await approveModelRequest({
    providerMode,
    contextText: context,
    source: "Agent Hub sidebar/chat"
  }))) {
    panel.webview.postMessage({
      type: "chatError",
      requestId,
      text: "Request cancelled because permission was not granted."
    });
    return;
  }
  const body = {
    session_id: message.sessionId || `vscode-chat-${Date.now()}`,
    mode: agentMode,
    route: codingAgentRoute(config, providerMode),
    task: codexChatTask(text),
    context,
    use_session_history: true,
    approval_mode: config.approvalMode,
    provider_approval_granted: true,
    allow_shell_tools: config.allowShellTools,
    agent_max_steps: config.agentMaxSteps,
    coder_max_steps: config.agentMaxSteps,
    agent_context_budget_tokens: config.agentContextBudgetTokens,
    agent_context_compaction_enabled: config.agentContextCompactionEnabled,
    context_mode: config.contextMode,
    cline_compatibility_mode: config.clineCompatibilityMode,
    group_agent: {
      plan_candidates: config.groupPlanCandidates
    },
    workspace_dir: workspace || ".",
    metadata: {
      source: "vscode-agent-hub-chat",
      control_agent_mode: providerMode,
      agent_mode: agentMode
    }
  };
  applyOptionalMaxTokens(body, config);

  output.appendLine("");
  output.appendLine(`[Agent Hub Chat] ${text}`);
  try {
    let approvalEvent = null;
    const streamHandlers = {
      onEvent: (event) => {
        if (event && event.data && event.data.type === "approval_required") {
          approvalEvent = event.data;
        }
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
    };
    let response = await requestEventStream("POST", "/v1/agent", { ...body, stream: true }, streamHandlers);
    if (approvalEvent && await requestPermission(permissionActionFromApprovalEvent(approvalEvent))) {
      postChatProgress(panel, requestId, "Approval granted. Resuming Agent Hub...");
      approvalEvent = null;
      response = await requestEventStream(
        "POST",
        "/v1/agent",
        {
          ...body,
          stream: true,
          approval_granted: true,
          agent_hub: {
            approval_granted: true
          }
        },
        streamHandlers
      );
    }
    const reply = responseText(response);
    output.appendLine(reply || "(empty response)");
    appendAgentTrace(response);
    appendResearchMetadata(response);
    panel.webview.postMessage({
      type: "chatResponse",
      requestId,
      text: reply || "(empty response)",
      tools: agentToolSteps(response),
      sources: sourceLines(response),
      response
    });
  } catch (error) {
    output.appendLine(`Agent Hub chat failed: ${error.message}`);
    panel.webview.postMessage({
      type: "chatError",
      requestId,
      text: formatAgentHubError(error),
      failover: Array.isArray(error.failover) ? error.failover : []
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

function apiKeyFieldsHtml() {
  return API_KEY_SECRETS.map((spec) => `
                <label class="key-field">
                  <span>${escapeHtml(spec.label)}</span>
                  <input id="key-${escapeHtml(spec.id)}" type="password" autocomplete="off" placeholder="${escapeHtml(spec.env)}">
                  <span class="key-state" id="key-${escapeHtml(spec.id)}-state">Checking...</span>
                </label>`).join("");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function chatHtml(webview, logoPath, initialSettings = settings()) {
  const nonce = getNonce();
  const logoSrc = webview.asWebviewUri(logoPath);
  const initialSettingsJson = jsonForScript(chatSettingsPayload(initialSettings));
  const apiKeyIdsJson = jsonForScript(API_KEY_SECRETS.map((spec) => spec.id));
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
      --app-bg: var(--vscode-editor-background, var(--vscode-sideBar-background, #1f2328));
      --app-fg: var(--vscode-foreground, var(--vscode-sideBar-foreground, #d4d4d4));
      --border: var(--vscode-panel-border, var(--vscode-sideBarSectionHeader-border, rgba(127, 127, 127, 0.35)));
      --muted: var(--vscode-descriptionForeground, var(--vscode-disabledForeground, #8b949e));
      --input: var(--vscode-input-background, var(--app-bg));
      --input-fg: var(--vscode-input-foreground, var(--app-fg));
      --input-border: var(--vscode-input-border, var(--border));
      --button: var(--vscode-button-background, #0e639c);
      --button-fg: var(--vscode-button-foreground, #ffffff);
      --button-hover: var(--vscode-button-hoverBackground, #1177bb);
      --secondary: var(--vscode-button-secondaryBackground, var(--input));
      --secondary-fg: var(--vscode-button-secondaryForeground, var(--app-fg));
      --secondary-hover: var(--vscode-button-secondaryHoverBackground, var(--vscode-list-hoverBackground, rgba(127, 127, 127, 0.22)));
      --bubble: var(--vscode-editor-inactiveSelectionBackground, rgba(127, 127, 127, 0.16));
      --surface: var(--vscode-editorWidget-background, var(--vscode-input-background, rgba(127, 127, 127, 0.08)));
      --surface-alt: var(--vscode-sideBarSectionHeader-background, rgba(127, 127, 127, 0.12));
      --ok: var(--vscode-testing-iconPassed, #3fb950);
      --error: var(--vscode-errorForeground, #f85149);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--app-fg);
      background: var(--app-bg);
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
      color: var(--app-fg);
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

    .models-wrap {
      position: relative;
      flex: 0 1 auto;
      min-width: 0;
    }

    #modelsToggle {
      max-width: min(280px, 42vw);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .models-menu {
      position: absolute;
      z-index: 19;
      top: calc(100% + 8px);
      right: 0;
      width: min(440px, calc(100vw - 28px));
      max-height: calc(100vh - 88px);
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      color: var(--app-fg);
      background: var(--app-bg);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
    }

    .models-menu[hidden] {
      display: none;
    }

    .models-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 10px;
    }

    .models-title {
      font-weight: 600;
    }

    .active-model {
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }

    .models-list {
      display: grid;
      gap: 6px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .model-row {
      display: grid;
      gap: 2px;
      padding: 7px 0;
      border-top: 1px solid var(--border);
    }

    .model-row:first-child {
      border-top: 0;
    }

    .model-main {
      color: var(--app-fg);
      overflow-wrap: anywhere;
    }

    .model-meta {
      color: var(--muted);
      font-size: 11px;
      overflow-wrap: anywhere;
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
      color: var(--app-fg);
      background: var(--app-bg);
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
      color: var(--app-fg);
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
      color: var(--app-fg);
      font-size: 12px;
    }

    .settings-check {
      color: var(--app-fg);
    }

    .settings-message {
      min-height: 16px;
      color: var(--muted);
      font-size: 11px;
    }

    .transcript {
      display: grid;
      align-content: start;
      gap: 14px;
      overflow-y: auto;
      padding: 14px;
    }

    .message-list {
      display: grid;
      gap: 14px;
      width: min(980px, 100%);
      margin: 0 auto;
    }

    .welcome {
      display: grid;
      gap: 12px;
      width: min(980px, 100%);
      margin: 0 auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      background: var(--surface);
    }

    .welcome[hidden] {
      display: none;
    }

    .welcome-title {
      color: var(--app-fg);
      font-size: 16px;
      font-weight: 600;
    }

    .welcome-meta {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }

    .prompt-pills {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .prompt-chip {
      min-height: 42px;
      color: var(--secondary-fg);
      background: var(--secondary);
      text-align: left;
    }

    .message {
      display: grid;
      gap: 6px;
      max-width: 920px;
      margin: 0;
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
      color: var(--app-fg);
      background: var(--surface);
    }

    .user .bubble {
      background: var(--bubble);
    }

    .assistant .bubble {
      border-left: 3px solid var(--ok);
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

    .feedback {
      display: flex;
      gap: 6px;
      margin-top: 6px;
    }

    .feedback button {
      min-height: 24px;
      padding: 2px 8px;
      font-size: 12px;
    }

    form {
      display: grid;
      gap: 8px;
      padding: 12px 14px 14px;
      border-top: 1px solid var(--border);
      background: var(--surface-alt);
    }

    textarea {
      width: 100%;
      min-height: 84px;
      max-height: 220px;
      resize: vertical;
      border: 1px solid var(--input-border);
      border-radius: 6px;
      padding: 9px 10px;
      color: var(--input-fg);
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
      color: var(--input-fg);
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
      color: var(--input-fg);
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
      color: var(--secondary-fg);
      background: var(--secondary);
    }

    button.secondary:hover {
      background: var(--secondary-hover);
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
      color: var(--app-fg);
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
      color: var(--app-fg);
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
      .key-grid,
      .prompt-pills {
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
        <div class="models-wrap">
          <button class="secondary" id="modelsToggle" type="button" aria-expanded="false" aria-controls="modelsMenu">Models</button>
          <section class="models-menu" id="modelsMenu" hidden>
            <div class="models-head">
              <div class="models-title">Session Models</div>
              <button class="secondary" id="modelsClose" type="button">Close</button>
            </div>
            <div class="active-model" id="activeModel">No model in this session yet</div>
            <ul class="models-list" id="sessionModelsList">
              <li class="model-row">
                <div class="model-main">No models yet</div>
                <div class="model-meta">Send a request to see routing live.</div>
              </li>
            </ul>
          </section>
        </div>
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
                <span>Agent mode</span>
                <select id="settingAgentMode">
                  <option value="agent">Standard agent</option>
                  <option value="group-agent">Group agent</option>
                </select>
              </label>
              <label class="settings-field">
                <span>Approval mode</span>
                <select id="settingApprovalMode">
                  <option value="ask">Ask before privileged actions</option>
                  <option value="readonly">Read-only</option>
                  <option value="shell-ask">Ask for shell only</option>
                  <option value="auto">Auto approve</option>
                  <option value="deny">Deny privileged actions</option>
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
                <span>Group plans</span>
                <input id="settingGroupPlanCandidates" type="number" min="1" max="5" step="1">
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
              <label class="settings-field">
                <span>Groq model</span>
                <input id="settingGroqModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>OpenRouter model</span>
                <input id="settingOpenrouterModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Cerebras model</span>
                <input id="settingCerebrasModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Mistral model</span>
                <input id="settingMistralModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>GitHub Models model</span>
                <input id="settingGithubModelsModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Hugging Face model</span>
                <input id="settingHuggingfaceModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>NVIDIA NIM model</span>
                <input id="settingNvidiaModel" type="text" autocomplete="off">
              </label>
              <label class="settings-field">
                <span>Cloudflare model</span>
                <input id="settingCloudflareModel" type="text" autocomplete="off">
              </label>
            </div>
            <div class="settings-row">
              <label class="settings-check"><input id="settingAllowShellTools" type="checkbox"> Allow shell tools</label>
              <label class="settings-check"><input id="settingAutoStart" type="checkbox"> Auto-start server</label>
              <label class="settings-check"><input id="settingApiKeyModelsEnabled" type="checkbox"> Enable API-key models</label>
              <label class="settings-check"><input id="settingFreeCloudPresetsEnabled" type="checkbox"> Enable free cloud presets</label>
              <label class="settings-check"><input id="settingFreeOnly" type="checkbox"> Free-only routing</label>
              <label class="settings-check"><input id="settingLoadBalancing" type="checkbox"> Load balancing</label>
              <label class="settings-check"><input id="settingRoutingDetails" type="checkbox"> Routing details</label>
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
${apiKeyFieldsHtml()}
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
    <main class="transcript" id="transcript" aria-live="polite">
      <section class="welcome" id="welcome">
        <div>
          <div class="welcome-title">What should Agent Hub do?</div>
          <div class="welcome-meta">Start with a normal request. Agent Hub will start the server, gather workspace context, and ask before privileged actions.</div>
        </div>
        <div class="prompt-pills">
          <button class="prompt-chip secondary" type="button" data-prompt="Inspect this workspace and suggest the next useful improvement">Inspect workspace</button>
          <button class="prompt-chip secondary" type="button" data-prompt="Explain the current file and call out anything risky">Explain file</button>
          <button class="prompt-chip secondary" type="button" data-prompt="Find and fix the most likely failing test">Fix tests</button>
          <button class="prompt-chip secondary" type="button" data-prompt="Research the current problem and summarize the best sources">Research</button>
        </div>
      </section>
      <div class="message-list" id="messageList"></div>
    </main>
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
    const apiKeyIds = ${apiKeyIdsJson};
    const transcript = document.getElementById("transcript");
    const welcome = document.getElementById("welcome");
    const messageList = document.getElementById("messageList");
    const form = document.getElementById("form");
    const prompt = document.getElementById("prompt");
    const send = document.getElementById("send");
    const status = document.getElementById("status");
    const modelsToggle = document.getElementById("modelsToggle");
    const modelsMenu = document.getElementById("modelsMenu");
    const modelsClose = document.getElementById("modelsClose");
    const activeModel = document.getElementById("activeModel");
    const sessionModelsList = document.getElementById("sessionModelsList");
    const settingsToggle = document.getElementById("settingsToggle");
    const settingsMenu = document.getElementById("settingsMenu");
    const settingsClose = document.getElementById("settingsClose");
    const settingsMessage = document.getElementById("settingsMessage");
    const includeSelection = document.getElementById("includeSelection");
    const controlMode = document.getElementById("controlMode");
    const pullModel = document.getElementById("pullModel");
    const settingInputs = {
      cloudRouteMode: document.getElementById("settingCloudRouteMode"),
      agentMode: document.getElementById("settingAgentMode"),
      approvalMode: document.getElementById("settingApprovalMode"),
      serverUrl: document.getElementById("settingServerUrl"),
      pythonPath: document.getElementById("settingPythonPath"),
      configPath: document.getElementById("settingConfigPath"),
      route: document.getElementById("settingRoute"),
      codingAgentRoute: document.getElementById("settingCodingRoute"),
      researchRoute: document.getElementById("settingResearchRoute"),
      maxTokens: document.getElementById("settingMaxTokens"),
      agentMaxSteps: document.getElementById("settingAgentMaxSteps"),
      groupPlanCandidates: document.getElementById("settingGroupPlanCandidates"),
      codexModel: document.getElementById("settingCodexModel"),
      claudeModel: document.getElementById("settingClaudeModel"),
      geminiModel: document.getElementById("settingGeminiModel"),
      chatgptModel: document.getElementById("settingChatgptModel"),
      groqModel: document.getElementById("settingGroqModel"),
      openrouterModel: document.getElementById("settingOpenrouterModel"),
      cerebrasModel: document.getElementById("settingCerebrasModel"),
      mistralModel: document.getElementById("settingMistralModel"),
      githubModelsModel: document.getElementById("settingGithubModelsModel"),
      huggingfaceModel: document.getElementById("settingHuggingfaceModel"),
      nvidiaModel: document.getElementById("settingNvidiaModel"),
      cloudflareModel: document.getElementById("settingCloudflareModel"),
      apiKeyModelsEnabled: document.getElementById("settingApiKeyModelsEnabled"),
      freeCloudPresetsEnabled: document.getElementById("settingFreeCloudPresetsEnabled"),
      freeOnly: document.getElementById("settingFreeOnly"),
      enableLoadBalancing: document.getElementById("settingLoadBalancing"),
      exposeRoutingDetails: document.getElementById("settingRoutingDetails"),
      allowShellTools: document.getElementById("settingAllowShellTools"),
      autoStart: document.getElementById("settingAutoStart")
    };
    const keyInputs = Object.fromEntries(apiKeyIds.map((id) => [id, document.getElementById("key-" + id)]));
    const keyStates = Object.fromEntries(apiKeyIds.map((id) => [id, document.getElementById("key-" + id + "-state")]));
    const keyMessage = document.getElementById("keyMessage");
    const pending = new Map();
    const sessionModels = new Map();
    let sessionId = "vscode-chat-" + Date.now().toString(36);
    let activeModelKey = "";
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

    function setWelcomeVisible(value) {
      welcome.hidden = !value;
    }

    function setSettingsMenuOpen(value) {
      settingsMenu.hidden = !value;
      settingsToggle.setAttribute("aria-expanded", value ? "true" : "false");
      if (value) {
        setModelsMenuOpen(false);
        const firstField = settingsMenu.querySelector("select, input, button");
        if (firstField) {
          firstField.focus();
        }
      }
    }

    function setModelsMenuOpen(value) {
      modelsMenu.hidden = !value;
      modelsToggle.setAttribute("aria-expanded", value ? "true" : "false");
      if (value) {
        setSettingsMenuOpen(false);
        modelsClose.focus();
      }
    }

    function applyChatSettings(settings, messageText) {
      const next = settings || {};
      controlMode.value = next.agentProviderMode || "cloud";
      settingInputs.cloudRouteMode.value = next.cloudRouteMode || "ollama-cloud";
      settingInputs.agentMode.value = next.agentMode || "agent";
      settingInputs.approvalMode.value = next.approvalMode || "ask";
      settingInputs.serverUrl.value = next.serverUrl || "";
      settingInputs.pythonPath.value = next.pythonPath || "";
      settingInputs.configPath.value = next.configPath || "";
      settingInputs.route.value = next.route || "";
      settingInputs.codingAgentRoute.value = next.codingAgentRoute || "";
      settingInputs.researchRoute.value = next.researchRoute || "";
      settingInputs.maxTokens.value = next.maxTokens || "";
      settingInputs.agentMaxSteps.value = next.agentMaxSteps || "";
      settingInputs.groupPlanCandidates.value = next.groupPlanCandidates || "";
      settingInputs.codexModel.value = next.codexModel || "";
      settingInputs.claudeModel.value = next.claudeModel || "";
      settingInputs.geminiModel.value = next.geminiModel || "";
      settingInputs.chatgptModel.value = next.chatgptModel || "";
      settingInputs.groqModel.value = next.groqModel || "";
      settingInputs.openrouterModel.value = next.openrouterModel || "";
      settingInputs.cerebrasModel.value = next.cerebrasModel || "";
      settingInputs.mistralModel.value = next.mistralModel || "";
      settingInputs.githubModelsModel.value = next.githubModelsModel || "";
      settingInputs.huggingfaceModel.value = next.huggingfaceModel || "";
      settingInputs.nvidiaModel.value = next.nvidiaModel || "";
      settingInputs.cloudflareModel.value = next.cloudflareModel || "";
      settingInputs.apiKeyModelsEnabled.checked = !!next.apiKeyModelsEnabled;
      settingInputs.freeCloudPresetsEnabled.checked = !!next.freeCloudPresetsEnabled;
      settingInputs.freeOnly.checked = next.freeOnly !== false;
      settingInputs.enableLoadBalancing.checked = next.enableLoadBalancing !== false;
      settingInputs.exposeRoutingDetails.checked = !!next.exposeRoutingDetails;
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
        agentMode: settingInputs.agentMode.value,
        approvalMode: settingInputs.approvalMode.value,
        cloudRouteMode: settingInputs.cloudRouteMode.value,
        maxTokens: settingInputs.maxTokens.value,
        agentMaxSteps: settingInputs.agentMaxSteps.value,
        groupPlanCandidates: settingInputs.groupPlanCandidates.value,
        codexModel: settingInputs.codexModel.value,
        claudeModel: settingInputs.claudeModel.value,
        geminiModel: settingInputs.geminiModel.value,
        chatgptModel: settingInputs.chatgptModel.value,
        groqModel: settingInputs.groqModel.value,
        openrouterModel: settingInputs.openrouterModel.value,
        cerebrasModel: settingInputs.cerebrasModel.value,
        mistralModel: settingInputs.mistralModel.value,
        githubModelsModel: settingInputs.githubModelsModel.value,
        huggingfaceModel: settingInputs.huggingfaceModel.value,
        nvidiaModel: settingInputs.nvidiaModel.value,
        cloudflareModel: settingInputs.cloudflareModel.value,
        apiKeyModelsEnabled: settingInputs.apiKeyModelsEnabled.checked,
        freeCloudPresetsEnabled: settingInputs.freeCloudPresetsEnabled.checked,
        freeOnly: settingInputs.freeOnly.checked,
        enableLoadBalancing: settingInputs.enableLoadBalancing.checked,
        exposeRoutingDetails: settingInputs.exposeRoutingDetails.checked,
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
      setWelcomeVisible(false);
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
      messageList.append(item);
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
      if (options.feedbackRequestId && !options.error) {
        turn.item.append(feedbackControls(options.feedbackRequestId));
      }
      transcript.scrollTop = transcript.scrollHeight;
    }

    function feedbackControls(agentHubRequestId) {
      const wrapper = document.createElement("div");
      wrapper.className = "feedback";
      const up = document.createElement("button");
      up.type = "button";
      up.textContent = "Good";
      const down = document.createElement("button");
      down.type = "button";
      down.textContent = "Bad";
      const send = (rating) => {
        up.disabled = true;
        down.disabled = true;
        vscode.postMessage({
          type: "feedback",
          requestId: agentHubRequestId,
          rating,
          workflowSuccess: rating === "up"
        });
      };
      up.addEventListener("click", () => send("up"));
      down.addEventListener("click", () => send("down"));
      wrapper.append(up, down);
      return wrapper;
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

    function resetSessionModels() {
      sessionModels.clear();
      activeModelKey = "";
      renderSessionModels();
    }

    function sessionModelKey(row) {
      return [
        row.role || "agent",
        row.agent || "",
        row.provider || "",
        row.model || ""
      ].join("|");
    }

    function providerModelText(row) {
      const provider = row.provider || "provider pending";
      const model = row.model || "model pending";
      return provider + " / " + model;
    }

    function shortModelText(row) {
      if (!row || (!row.provider && !row.model && !row.agent)) {
        return "Models";
      }
      const model = row.model || row.agent || "routing";
      const provider = row.provider ? row.provider + " / " : "";
      return "Models: " + provider + model;
    }

    function cleanSessionModelRow(row) {
      const source = row || {};
      return {
        role: String(source.role || "agent"),
        agent: String(source.agent || ""),
        provider: String(source.provider || ""),
        model: String(source.model || ""),
        status: String(source.status || "active"),
        detail: String(source.detail || "")
      };
    }

    function recordSessionModel(row, options = {}) {
      const clean = cleanSessionModelRow(row);
      if (!clean.agent && !clean.provider && !clean.model) {
        return;
      }
      if ((clean.provider || clean.model) && clean.agent) {
        sessionModels.delete([
          clean.role || "agent",
          clean.agent,
          "",
          ""
        ].join("|"));
      }
      const key = sessionModelKey(clean);
      const previous = sessionModels.get(key) || {};
      const next = Object.assign({}, previous, clean);
      sessionModels.set(key, next);
      if (options.active || next.status === "active" || next.status === "routing") {
        activeModelKey = key;
      }
      renderSessionModels();
    }

    function recordFailovers(failovers, fallbackRole) {
      if (!Array.isArray(failovers)) {
        return;
      }
      for (const event of failovers) {
        if (!event || typeof event !== "object") {
          continue;
        }
        recordSessionModel({
          role: fallbackRole || "failover",
          agent: event.agent,
          provider: event.provider,
          model: event.model,
          status: "failover",
          detail: event.reason || "failover"
        });
      }
    }

    function updateSessionModelsFromEvent(eventName, data) {
      const payload = data && typeof data === "object" ? data : {};
      const type = payload.type || eventName || "";
      if (type === "model_response") {
        recordSessionModel({
          role: "agent",
          agent: payload.agent,
          provider: payload.provider,
          model: payload.model,
          status: "active",
          detail: payload.step ? "Step " + payload.step : "workspace agent"
        }, { active: true });
      } else if (type === "team_role_started") {
        recordSessionModel({
          role: payload.role,
          agent: payload.agent,
          status: "routing",
          detail: "routing"
        }, { active: true });
      } else if (type === "team_role_finished") {
        recordSessionModel({
          role: payload.role,
          agent: payload.agent,
          provider: payload.provider,
          model: payload.model,
          status: "active",
          detail: "team role complete"
        }, { active: true });
      } else if (type === "route_finished") {
        recordSessionModel({
          role: "route",
          agent: payload.agent,
          provider: payload.provider,
          model: payload.model,
          status: "active",
          detail: "direct route"
        }, { active: true });
      } else if (type === "agent_stopped") {
        recordSessionModel({
          role: "agent",
          agent: payload.agent,
          provider: payload.provider,
          model: payload.model,
          status: "stopped",
          detail: "stopped"
        }, { active: true });
      }
      recordFailovers(payload.failover, payload.role);
    }

    function updateSessionModelsFromResponse(response) {
      const payload = response && typeof response === "object" ? response : {};
      if (payload.agent && typeof payload.agent === "object") {
        recordSessionModel({
          role: "final",
          agent: payload.agent.name,
          provider: payload.agent.provider,
          model: payload.agent.model,
          status: "active",
          detail: "final response"
        }, { active: true });
      } else if (payload.model && sessionModels.size === 0) {
        recordSessionModel({
          role: "final",
          model: payload.model,
          status: "active",
          detail: "final response"
        }, { active: true });
      }
      recordFailovers(payload.failover);
      const metadata = payload.agent_hub;
      if (metadata && Array.isArray(metadata.steps)) {
        for (const step of metadata.steps) {
          if (!step || typeof step !== "object") {
            continue;
          }
          recordSessionModel({
            role: "agent",
            agent: step.agent,
            provider: step.provider,
            model: step.model,
            status: "used",
            detail: step.tool ? "tool: " + step.tool : "step"
          });
        }
      }
    }

    function renderSessionModels() {
      const rows = Array.from(sessionModels.values());
      const active = activeModelKey ? sessionModels.get(activeModelKey) : rows[rows.length - 1];
      activeModel.textContent = active
        ? "Active: " + providerModelText(active) + " (" + (active.role || "agent") + ")"
        : "No model in this session yet";
      modelsToggle.textContent = shortModelText(active);
      sessionModelsList.textContent = "";
      if (!rows.length) {
        const item = document.createElement("li");
        item.className = "model-row";
        const main = document.createElement("div");
        main.className = "model-main";
        main.textContent = "No models yet";
        const meta = document.createElement("div");
        meta.className = "model-meta";
        meta.textContent = "Send a request to see routing live.";
        item.append(main, meta);
        sessionModelsList.append(item);
        return;
      }
      for (const row of rows.slice().reverse()) {
        const item = document.createElement("li");
        item.className = "model-row";
        const main = document.createElement("div");
        main.className = "model-main";
        main.textContent = providerModelText(row);
        const meta = document.createElement("div");
        meta.className = "model-meta";
        const pieces = [];
        if (row.role) {
          pieces.push("role: " + row.role);
        }
        if (row.agent) {
          pieces.push("agent: " + row.agent);
        }
        if (row.status) {
          pieces.push(row.status);
        }
        if (row.detail) {
          pieces.push(row.detail);
        }
        meta.textContent = pieces.join(" - ");
        item.append(main, meta);
        sessionModelsList.append(item);
      }
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

    modelsToggle.addEventListener("click", () => {
      setModelsMenuOpen(modelsMenu.hidden);
    });

    modelsClose.addEventListener("click", () => {
      setModelsMenuOpen(false);
      modelsToggle.focus();
    });

    document.addEventListener("click", (event) => {
      if (
        !settingsMenu.hidden &&
        !settingsMenu.contains(event.target) &&
        !settingsToggle.contains(event.target)
      ) {
        setSettingsMenuOpen(false);
      }
      if (
        !modelsMenu.hidden &&
        !modelsMenu.contains(event.target) &&
        !modelsToggle.contains(event.target)
      ) {
        setModelsMenuOpen(false);
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (!settingsMenu.hidden) {
          setSettingsMenuOpen(false);
          settingsToggle.focus();
        }
        if (!modelsMenu.hidden) {
          setModelsMenuOpen(false);
          modelsToggle.focus();
        }
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

    for (const chip of document.querySelectorAll("[data-prompt]")) {
      chip.addEventListener("click", () => {
        prompt.value = chip.getAttribute("data-prompt") || "";
        prompt.focus();
      });
    }

    function submitPrompt(text, options = {}) {
      const cleanText = String(text || "").trim();
      const includeContext = typeof options.includeSelection === "boolean"
        ? options.includeSelection
        : includeSelection.checked;
      const selectedProviderMode = options.providerMode || controlMode.value;
      const autoSend = options.autoSend !== false;
      if (!autoSend) {
        prompt.value = cleanText;
        includeSelection.checked = includeContext;
        controlMode.value = selectedProviderMode;
        prompt.focus();
        return;
      }
      if (!cleanText) {
        return;
      }
      const requestId = Date.now().toString(36) + Math.random().toString(36).slice(2);
      appendMessage("user", cleanText);
      pending.set(requestId, appendLiveMessage());
      prompt.value = "";
      includeSelection.checked = includeContext;
      controlMode.value = selectedProviderMode;
      setBusy(true);
      startWorkingStatus();
      vscode.postMessage({
        type: "send",
        requestId,
        sessionId,
        text: cleanText,
        includeSelection: includeContext,
        providerMode: selectedProviderMode
      });
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitPrompt(prompt.value, {
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
      const keys = {};
      for (const id of apiKeyIds) {
        keys[id] = keyInputs[id] ? keyInputs[id].value : "";
      }
      vscode.postMessage({
        type: "saveApiKeys",
        keys
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
      messageList.textContent = "";
      setWelcomeVisible(true);
      sessionId = "vscode-chat-" + Date.now().toString(36);
      resetSessionModels();
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
      if (message.type === "queuedPrompt") {
        submitPrompt(message.text, {
          includeSelection: message.includeSelection !== false,
          providerMode: message.providerMode || controlMode.value,
          autoSend: message.autoSend !== false
        });
        return;
      }
      if (message.type === "typing") {
        startWorkingStatus();
        return;
      }
      if (message.type === "chatProgress") {
        updateSessionModelsFromEvent(message.event, message.data);
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
        updateSessionModelsFromResponse(message.response);
        finishLiveMessage(turn, message.text, {
          tools: message.tools || [],
          sources: message.sources || [],
          feedbackRequestId: message.response && message.response.id
        });
        setBusy(false);
        status.textContent = "Ready";
        prompt.focus();
        return;
      }
      if (message.type === "chatError") {
        const turn = pending.get(message.requestId);
        pending.delete(message.requestId);
        recordFailovers(message.failover);
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
    renderSessionModels();
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

async function startServer(options = {}) {
  const workspace = workspaceRoot();
  if (!workspace) {
    setServerLifecycleState("Error", "Open a workspace folder before starting Agent Hub.");
    vscode.window.showErrorMessage("Open a workspace folder before starting Agent Hub.");
    return;
  }

  const config = settings();
  if (!options.permissionAlreadyGranted && !(await requestPermission({
    category: "process_control",
    description: "Agent Hub wants to start the local backend server process.",
    resource: config.serverUrl,
    risk: "medium",
    detail: "This launches Python from the selected workspace and may create or repair the Agent Hub config."
  }))) {
    setServerLifecycleState("Stopped", "Start Server was cancelled.");
    return;
  }
  const configChanged = await ensureLocalConfig(config, workspace);

  if (await isServerOnline()) {
    setServerLifecycleState("Running", `Running at ${config.serverUrl}`);
    if (configChanged) {
      vscode.window.showWarningMessage("Agent Hub config was repaired. Restart Agent Hub to use the repaired config.");
    } else {
      vscode.window.showInformationMessage("Agent Hub is already running.");
    }
    return;
  }
  if (serverProcess) {
    setServerLifecycleState("Starting", "Agent Hub is starting.");
    vscode.window.showInformationMessage("Agent Hub is starting.");
    return;
  }

  const launch = await serverLaunchEnvironment(workspace);
  if (!(await ensurePythonBackend(config, workspace, launch))) {
    setServerLifecycleState("Error", "Python backend check failed. See Agent Hub output.");
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
  setServerLifecycleState("Starting", `Starting Agent Hub at ${config.serverUrl}...`);
  serverProcess = cp.spawn(launch.pythonCommand, pythonArgs, {
    cwd: workspace,
    shell: false,
    env: launch.env
  });

  serverProcess.stdout.on("data", (data) => output.append(data.toString()));
  serverProcess.stderr.on("data", (data) => output.append(data.toString()));
  serverProcess.on("exit", (code, signal) => {
    output.appendLine(`Agent Hub server exited with code ${code}.`);
    serverProcess = null;
    const stoppedByRequest = signal || code === 0 || code === null;
    setServerLifecycleState(
      stoppedByRequest ? "Stopped" : "Error",
      stoppedByRequest ? "Agent Hub stopped." : `Agent Hub exited with code ${code}.`
    );
  });
  serverProcess.on("error", (error) => {
    output.appendLine(`Failed to start Agent Hub: ${error.message}`);
    vscode.window.showErrorMessage(`Failed to start Agent Hub: ${error.message}`);
    serverProcess = null;
    setServerLifecycleState("Error", `Failed to start Agent Hub: ${error.message}`);
  });

  const online = await waitForServer(7000);
  if (online) {
    setServerLifecycleState("Running", `Running at ${config.serverUrl}`);
    vscode.window.showInformationMessage(`Agent Hub started at ${config.serverUrl}.`);
  } else {
    setServerLifecycleState("Error", "Agent Hub did not respond yet. Check the Agent Hub output.");
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
    freeCloudPresetsEnabled: freeCloudPresetsEnabledFromConfig(raw),
    freeOnly: raw.free_only !== false,
    enableLoadBalancing: raw.enable_load_balancing !== false,
    exposeRoutingDetails: raw.expose_routing_details === true,
    codexModel: modelForAgent(raw, "codex", DEFAULT_CODEX_MODEL),
    claudeModel: modelForAgent(raw, "claude", DEFAULT_CLAUDE_MODEL),
    geminiModel: modelForAgent(raw, "gemini", DEFAULT_GEMINI_MODEL),
    chatgptModel: modelForAgent(raw, "chatgpt", DEFAULT_CHATGPT_MODEL),
    groqModel: modelForAgent(raw, "groq-qwen3-32b", DEFAULT_GROQ_MODEL),
    openrouterModel: modelForAgent(raw, "openrouter-qwen-free", DEFAULT_OPENROUTER_MODEL),
    cerebrasModel: modelForAgent(raw, "cerebras-llama-3-3-70b", DEFAULT_CEREBRAS_MODEL),
    mistralModel: modelForAgent(raw, "mistral-small-latest", DEFAULT_MISTRAL_MODEL),
    githubModelsModel: modelForAgent(raw, "github-models-qwen3-coder", DEFAULT_GITHUB_MODELS_MODEL),
    huggingfaceModel: modelForAgent(raw, "huggingface-qwen3-coder", DEFAULT_HUGGINGFACE_MODEL),
    nvidiaModel: modelForAgent(raw, "nvidia-nemotron", DEFAULT_NVIDIA_MODEL),
    cloudflareModel: modelForAgent(raw, "cloudflare-llama-3-1-8b", DEFAULT_CLOUDFLARE_MODEL)
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
  data.free_only = cloudSettings.freeOnly !== false;
  data.enable_load_balancing = cloudSettings.enableLoadBalancing !== false;
  data.expose_routing_details = !!cloudSettings.exposeRoutingDetails;
  data.cloud_control_selection = {
    route_mode: normalizeCloudRouteMode(cloudSettings.cloudRouteMode),
    api_key_models_enabled: !!cloudSettings.apiKeyModelsEnabled,
    free_cloud_presets_enabled: !!cloudSettings.freeCloudPresetsEnabled
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
    ...routeAgents.filter((name) => name !== "echo")
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
    ? [...hostedAgents, ...ollamaCloudAgents]
    : [...ollamaCloudAgents, ...hostedAgents];
  return uniqueAgentNames(ordered);
}

function ollamaCloudAgentNames(data) {
  const existing = agentNameSet(data);
  const names = OLLAMA_CLOUD_AGENT_NAMES.filter((name) => existing.has(name));
  return names.length ? names : OLLAMA_CLOUD_AGENT_NAMES;
}

function hostedCloudAgentNames(data) {
  const agents = Array.isArray(data && data.agents) ? data.agents : [];
  return agents
    .filter((agent) => (
      agent &&
      typeof agent === "object" &&
      typeof agent.name === "string" &&
      agent.enabled === true &&
      (
        HOSTED_CLOUD_AGENT_NAMES.includes(agent.name) ||
        CLOUD_PROVIDER_TYPES.has(String(agent.provider_type || "").toLowerCase())
      )
    ))
    .map((agent) => agent.name);
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
      ? [...cloudAgents, ...ollamaCloudAgents]
      : [...ollamaCloudAgents, ...cloudAgents]
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
    agent_context_budget_tokens: 32000,
    agent_context_compaction_enabled: true,
    context_mode: "balanced",
    cline_compatibility_mode: true,
    allow_shell_tools: true,
    approval_mode: "ask",
    free_only: options.cloudSettings?.freeOnly !== false,
    enable_load_balancing: options.cloudSettings?.enableLoadBalancing !== false,
    include_raw_responses: false,
    expose_routing_details: options.cloudSettings?.exposeRoutingDetails === true,
    debug_echo_enabled: false,
    cloud_control_selection: {
      route_mode: cloudRouteMode,
      api_key_models_enabled: !!options.cloudSettings?.apiKeyModelsEnabled,
      free_cloud_presets_enabled: !!options.cloudSettings?.freeCloudPresetsEnabled
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
        agents: ["local-research", ...cloudRouteAgents.filter((name) => name !== "echo")]
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
      ...localSources.map((source) => localModelAgentConfig(source))
    ]
  };
}

function cloudModelSources(settings = {}) {
  const hosted = [
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
  return [...hosted, ...freeCloudPresetSources(settings)];
}

function freeCloudPresetSources(settings = {}) {
  const enabled = !!settings.freeCloudPresetsEnabled;
  return [
    {
      name: "groq-qwen3-32b",
      label: "Groq Qwen3 32B",
      provider: "openai-compatible",
      providerType: "groq",
      enabled,
      model: cleanSettingString(settings.groqModel, DEFAULT_GROQ_MODEL),
      apiKeyEnv: "GROQ_API_KEY",
      baseUrl: "https://api.groq.com/openai/v1",
      contextWindow: 128000,
      priority: 74,
      codingScore: 0.84,
      reasoningScore: 0.82,
      speedScore: 0.9,
      supportsTools: true
    },
    {
      name: "openrouter-qwen-free",
      label: "OpenRouter Qwen free",
      provider: "openai-compatible",
      providerType: "openrouter",
      enabled,
      model: cleanSettingString(settings.openrouterModel, DEFAULT_OPENROUTER_MODEL),
      apiKeyEnv: "OPENROUTER_API_KEY",
      baseUrl: "https://openrouter.ai/api/v1",
      headers: {
        "HTTP-Referer": "${AGENT_HUB_HTTP_REFERER:-http://localhost:8787}",
        "X-Title": "${AGENT_HUB_X_TITLE:-Agent Hub}"
      },
      contextWindow: 64000,
      priority: 66,
      codingScore: 0.9,
      reasoningScore: 0.78,
      speedScore: 0.5,
      supportsTools: true
    },
    {
      name: "cerebras-llama-3-3-70b",
      label: "Cerebras Llama 3.3 70B",
      provider: "openai-compatible",
      providerType: "cerebras",
      enabled,
      model: cleanSettingString(settings.cerebrasModel, DEFAULT_CEREBRAS_MODEL),
      apiKeyEnv: "CEREBRAS_API_KEY",
      baseUrl: "https://api.cerebras.ai/v1",
      contextWindow: 128000,
      priority: 68,
      codingScore: 0.68,
      reasoningScore: 0.78,
      speedScore: 0.95
    },
    {
      name: "mistral-small-latest",
      label: "Mistral Small",
      provider: "openai-compatible",
      providerType: "mistral",
      enabled,
      model: cleanSettingString(settings.mistralModel, DEFAULT_MISTRAL_MODEL),
      apiKeyEnv: "MISTRAL_API_KEY",
      baseUrl: "https://api.mistral.ai/v1",
      contextWindow: 128000,
      priority: 58,
      codingScore: 0.66,
      reasoningScore: 0.72,
      speedScore: 0.75,
      supportsTools: true
    },
    {
      name: "github-models-qwen3-coder",
      label: "GitHub Models Qwen3 Coder",
      provider: "openai-compatible",
      providerType: "github-models",
      enabled,
      model: cleanSettingString(settings.githubModelsModel, DEFAULT_GITHUB_MODELS_MODEL),
      apiKeyEnv: "GITHUB_TOKEN",
      baseUrl: "https://models.github.ai/inference",
      chatCompletionsPath: "/chat/completions",
      headers: {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "${GITHUB_API_VERSION:-2026-03-10}"
      },
      contextWindow: 128000,
      priority: 62,
      codingScore: 0.86,
      reasoningScore: 0.78,
      speedScore: 0.6
    },
    {
      name: "huggingface-qwen3-coder",
      label: "Hugging Face Qwen3 Coder",
      provider: "openai-compatible",
      providerType: "huggingface",
      enabled,
      model: cleanSettingString(settings.huggingfaceModel, DEFAULT_HUGGINGFACE_MODEL),
      apiKeyEnv: "HUGGINGFACE_API_KEY",
      baseUrl: "https://router.huggingface.co/v1",
      contextWindow: 64000,
      priority: 54,
      codingScore: 0.86,
      reasoningScore: 0.78,
      speedScore: 0.45,
      supportsTools: true
    },
    {
      name: "nvidia-nemotron",
      label: "NVIDIA Nemotron",
      provider: "openai-compatible",
      providerType: "nvidia-nim",
      enabled,
      model: cleanSettingString(settings.nvidiaModel, DEFAULT_NVIDIA_MODEL),
      apiKeyEnv: "NVIDIA_API_KEY",
      baseUrl: "https://integrate.api.nvidia.com/v1",
      contextWindow: 131072,
      priority: 64,
      codingScore: 0.72,
      reasoningScore: 0.82,
      speedScore: 0.72,
      supportsTools: true
    },
    {
      name: "cloudflare-llama-3-1-8b",
      label: "Cloudflare Workers AI",
      provider: "openai-compatible",
      providerType: "cloudflare-workers-ai",
      enabled,
      model: cleanSettingString(settings.cloudflareModel, DEFAULT_CLOUDFLARE_MODEL),
      apiKeyEnv: "CLOUDFLARE_API_TOKEN",
      baseUrl: "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/ai/v1",
      contextWindow: 8192,
      priority: 40,
      codingScore: 0.45,
      reasoningScore: 0.55,
      speedScore: 0.8
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
    provider_type: "ollama-cloud",
    model: source.model,
    base_url: source.baseUrl,
    free: true,
    context_window: source.contextWindow || 128000,
    timeout_seconds: source.timeoutSeconds || 180,
    cooldown_seconds: source.cooldownSeconds || 10
  };
}

function cloudModelAgentConfig(source) {
  const agent = {
    name: source.name,
    provider: source.provider,
    provider_type: source.providerType,
    model: source.model,
    enabled: !!source.enabled,
    free: true,
    api_key_env: source.apiKeyEnv,
    context_window: source.contextWindow,
    timeout_seconds: 60,
    cooldown_seconds: source.cooldownSeconds || 30,
    coding_score: source.codingScore,
    reasoning_score: source.reasoningScore,
    speed_score: source.speedScore,
    supports_tools: source.supportsTools,
    supports_json: source.supportsJson !== false,
    supports_streaming: source.supportsStreaming !== false,
    supports_vision: source.supportsVision,
    supports_function_calling: source.supportsFunctionCalling,
    priority: source.priority
  };
  if (source.baseUrl) {
    agent.base_url = source.baseUrl;
  }
  if (source.chatCompletionsPath) {
    agent.chat_completions_path = source.chatCompletionsPath;
  }
  if (source.headers) {
    agent.headers = source.headers;
  }
  return agent;
}

function localModelAgentConfig(source) {
  return {
    name: source.name,
    provider: "openai-compatible",
    provider_type: "openai-compatible",
    model: source.model,
    base_url: source.baseUrl,
    free: true,
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

async function stopServer() {
  if (!(await requestPermission({
    category: "process_control",
    description: "Agent Hub wants to stop the backend server process.",
    resource: settings().serverUrl,
    risk: "medium"
  }))) {
    refreshSidebar();
    return;
  }
  if (stopServerProcess()) {
    setServerLifecycleState("Stopped", "Agent Hub server stopped.");
    vscode.window.showInformationMessage("Agent Hub server stopped.");
    await waitForServerOffline(3000);
    refreshSidebar();
    return;
  }

  if (await isServerOnline()) {
    await stopAgentHubServerOnConfiguredPort();
    const offline = await waitForServerOffline(3000);
    setServerLifecycleState(
      offline ? "Stopped" : "Error",
      offline
        ? "Agent Hub server stopped."
        : "Agent Hub is still running. Check the process using the configured port."
    );
    if (offline) {
      vscode.window.showInformationMessage("Agent Hub server stopped.");
    } else {
      vscode.window.showWarningMessage("Agent Hub is still running. Check the process using the configured port.");
    }
    return;
  }

  setServerLifecycleState("Stopped", "Agent Hub server is stopped.");
  vscode.window.showInformationMessage("Agent Hub server is stopped.");
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

async function restartServer() {
  if (!(await requestPermission({
    category: "process_control",
    description: "Agent Hub wants to restart the backend server process.",
    resource: settings().serverUrl,
    risk: "medium"
  }))) {
    refreshSidebar();
    return;
  }
  setServerLifecycleState("Starting", "Restarting Agent Hub...");
  if (serverProcess) {
    stopServerProcess();
    await waitForServerOffline(3000);
  } else if (await isServerOnline()) {
    await stopAgentHubServerOnConfiguredPort();
    await waitForServerOffline(3000);
  }
  await startServer({ permissionAlreadyGranted: true });
  refreshSidebar();
}

async function openAgentHubSettings() {
  await vscode.commands.executeCommand("workbench.action.openSettings", "Agent Hub");
}

async function checkHealth() {
  await showStatus();
  refreshSidebar();
}

async function showStatus() {
  try {
    const health = await requestJson("GET", "/health");
    const agents = Array.isArray(health.agents) ? health.agents.join(", ") : "unknown";
    const freeOnly = health.free_only === undefined ? "unknown" : String(health.free_only);
    setServerLifecycleState("Running", `Running at ${settings().serverUrl}`);
    vscode.window.showInformationMessage(`Agent Hub online. Agents: ${agents}. free_only: ${freeOnly}.`);
    output.appendLine(JSON.stringify(health, null, 2));
  } catch (error) {
    setServerLifecycleState(serverProcess ? "Error" : "Stopped", `Agent Hub is offline or unhealthy: ${error.message}`);
    vscode.window.showWarningMessage(`Agent Hub is offline or unhealthy: ${error.message}`);
  }
}

async function copyClineConfig() {
  const text = clineConfigText(settings());
  await vscode.env.clipboard.writeText(text);
  vscode.window.showInformationMessage("Agent Hub Cline config copied. Use model agent-hub-coding.");
}

async function showClineSetup() {
  output.show(true);
  output.appendLine("");
  output.appendLine("Agent Hub Cline setup");
  output.appendLine(clineConfigText(settings()));
  output.appendLine("");
  output.appendLine("Use the OpenAI-compatible provider in Cline. Base URL must include /v1.");
}

async function testClineConnection() {
  if (!(await ensureServerReady())) {
    vscode.window.showWarningMessage("Agent Hub backend is not running. Click Start Server first.");
    return;
  }
  const payload = {
    api_shape: "openai-chat",
    model: "agent-hub-coding",
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: "Cline connectivity probe." },
          { type: "tool_result", tool_use_id: "probe", content: [{ type: "text", text: "tool result preserved" }] }
        ],
        task_progress: [{ title: "probe", status: "in_progress" }],
        active_files: activeEditorFileList()
      }
    ],
    tools: [
      {
        type: "function",
        function: {
          name: "agent_hub_probe",
          parameters: { type: "object", properties: {} }
        }
      }
    ],
    agent_hub: { cline_compatibility_mode: true }
  };
  try {
    const response = await requestJson("POST", "/debug/request", payload);
    const diagnostics = response.diagnostics || {};
    const ok = diagnostics.structured_content_messages > 0 && diagnostics.preserved_tool_results > 0;
    const message = ok
      ? "Cline request normalization OK: structured content, tool results, and task state are preserved."
      : "Cline request reached Agent Hub, but context diagnostics look incomplete. Open logs for details.";
    output.appendLine(JSON.stringify(response, null, 2));
    vscode.window.showInformationMessage(message);
  } catch (error) {
    vscode.window.showErrorMessage(`Cline connection test failed: ${formatAgentHubError(error)}`);
  }
}

async function copyClaudeCodeConfig() {
  const text = claudeCodeConfigText(settings());
  await vscode.env.clipboard.writeText(text);
  vscode.window.showInformationMessage("Agent Hub Claude Code config copied.");
}

async function showClaudeCodeSetup() {
  output.show(true);
  output.appendLine("");
  output.appendLine("Agent Hub Claude Code setup");
  output.appendLine(claudeCodeConfigText(settings()));
  output.appendLine("");
  output.appendLine("Agent Hub exposes Anthropic Messages at /v1/messages and keeps tool_use/tool_result blocks structured.");
}

async function testAnthropicEndpoint() {
  if (!(await ensureServerReady())) {
    vscode.window.showWarningMessage("Agent Hub backend is not running. Click Start Server first.");
    return;
  }
  const payload = {
    api_shape: "anthropic-messages",
    model: "agent-hub-coding",
    max_tokens: 16,
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: "Claude Code endpoint probe." },
          { type: "tool_result", tool_use_id: "toolu_probe", content: "tool result preserved" }
        ],
        task_progress: [{ title: "probe", status: "in_progress" }],
        active_files: activeEditorFileList()
      }
    ],
    tools: [
      {
        name: "agent_hub_probe",
        input_schema: { type: "object", properties: {} }
      }
    ],
    agent_hub: { cline_compatibility_mode: true }
  };
  try {
    const response = await requestJson("POST", "/debug/request", payload);
    const diagnostics = response.diagnostics || {};
    const ok = diagnostics.structured_content_messages > 0 && diagnostics.preserved_tool_results > 0;
    const message = ok
      ? "Anthropic request normalization OK: /v1/messages shape, tool results, and task state are preserved."
      : "Anthropic request reached Agent Hub, but context diagnostics look incomplete. Open logs for details.";
    output.appendLine(JSON.stringify(response, null, 2));
    vscode.window.showInformationMessage(message);
  } catch (error) {
    vscode.window.showErrorMessage(`Anthropic endpoint test failed: ${formatAgentHubError(error)}`);
  }
}

function clineConfigText(config) {
  const baseUrl = `${config.serverUrl.replace(/\/+$/, "")}/v1`;
  return JSON.stringify({
    apiProvider: "openai-compatible",
    openAiBaseUrl: baseUrl,
    openAiApiKey: "agent-hub-local",
    openAiModelId: "agent-hub-coding",
    model: "agent-hub-coding",
    agentHub: {
      cline_compatibility_mode: true
    }
  }, null, 2);
}

function claudeCodeConfigText(config) {
  const baseUrl = config.serverUrl.replace(/\/+$/, "");
  return [
    "# Agent Hub Claude Code",
    `ANTHROPIC_BASE_URL=${baseUrl}`,
    "ANTHROPIC_AUTH_TOKEN=agent-hub-local",
    "ANTHROPIC_MODEL=agent-hub-coding"
  ].join("\n");
}

function activeEditorFileList() {
  const files = [];
  const editor = currentTextEditor();
  if (editor && editor.document && editor.document.uri) {
    files.push(vscode.workspace.asRelativePath(editor.document.uri, false));
  }
  for (const tabGroup of vscode.window.tabGroups.all) {
    for (const tab of tabGroup.tabs) {
      const uri = tab.input && tab.input.uri;
      if (uri && uri.scheme === "file") {
        files.push(vscode.workspace.asRelativePath(uri, false));
      }
    }
  }
  return Array.from(new Set(files)).slice(0, 20);
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
      agent_context_budget_tokens: config.agentContextBudgetTokens,
      agent_context_compaction_enabled: config.agentContextCompactionEnabled,
      context_mode: config.contextMode,
      cline_compatibility_mode: config.clineCompatibilityMode,
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
  if (!(await approveModelRequest({
    providerMode: config.agentProviderMode,
    contextText: context,
    source: "VS Code command"
  }))) {
    vscode.window.showWarningMessage("Agent Hub request cancelled because permission was not granted.");
    return;
  }
  if (!(await ensureServerReady())) {
    vscode.window.showErrorMessage("Agent Hub is not running. Use 'Agent Hub: Start Server' or check the output.");
    return;
  }

  const selectedAgentMode = agentMode ? normalizeAgentMode(config.agentMode) : "route";
  const body = {
    ...extra,
    session_id: `vscode-${Date.now()}`,
    mode: selectedAgentMode,
    route: route || config.route,
    task,
    context,
    approval_mode: config.approvalMode,
    provider_approval_granted: true,
    agent_context_budget_tokens: config.agentContextBudgetTokens,
    agent_context_compaction_enabled: config.agentContextCompactionEnabled,
    context_mode: config.contextMode,
    cline_compatibility_mode: config.clineCompatibilityMode,
    group_agent: {
      plan_candidates: config.groupPlanCandidates
    },
    metadata: {
      source: "vscode",
      agent_mode: selectedAgentMode
    }
  };
  applyOptionalMaxTokens(body, config);

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
  } else if (raw.includes("No usable model") || raw.includes("No enabled agents")) {
    lines.push(
      "No usable model is available for this request.",
      "",
      "Enable a provider in Agent Hub settings, add an API key, or start a local Ollama/LM Studio model.",
      "For Cline, use base URL " + settings().serverUrl.replace(/\/+$/, "") + "/v1 and model agent-hub-coding."
    );
  } else if (raw.includes("Echo is disabled")) {
    lines.push(
      "Echo is disabled by default.",
      "",
      "Configure a real provider or set debug_echo_enabled=true only for diagnostics."
    );
  } else if (raw.includes("Approval required") || raw.includes("permission")) {
    lines.push(
      "Agent Hub needs explicit approval before continuing.",
      "",
      "Review the permission prompt, switch approval mode in settings, or use a local provider for private workspace content."
    );
  } else if (raw.includes("context looks empty") || raw.includes("suspiciously empty")) {
    lines.push(
      "The client request reached Agent Hub, but the context looks empty.",
      "",
      "Run Agent Hub: Test Cline Connection and check /debug/context for dropped messages, task_progress, and active file metadata."
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
  if (!(await requestPermission({
    category: "process_control",
    description: "Agent Hub wants to restart the backend to load the bundled version.",
    resource: settings().serverUrl,
    risk: "medium",
    detail: health && health.version ? `Running backend version: ${health.version}` : ""
  }))) {
    return;
  }
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
  if (!(await requestPermission({
    category: "process_control",
    description: "Agent Hub wants to stop a process listening on the configured server port.",
    resource: `port ${port}`,
    risk: "high",
    detail: "This is used when another Agent Hub process is already bound to the port."
  }))) {
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
    agentMode: normalizeAgentMode(config.get("agentMode", "agent")),
    approvalMode: normalizeApprovalMode(config.get("approvalMode", "ask")),
    groupPlanCandidates: config.get("groupPlanCandidates", 1),
    agentMaxSteps: config.get("agentMaxSteps", 20),
    agentContextBudgetTokens: config.get("agentContextBudgetTokens", 32000),
    agentContextCompactionEnabled: config.get("agentContextCompactionEnabled", true),
    contextMode: normalizeContextMode(config.get("contextMode", "balanced")),
    clineCompatibilityMode: config.get("clineCompatibilityMode", true),
    allowShellTools: config.get("allowShellTools", true),
    maxTokens: normalizeOptionalPositiveInteger(config.get("maxTokens", null)),
    autoStart: config.get("autoStart", true)
  };
}

function normalizeOptionalPositiveInteger(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function normalizeAgentProviderMode(value) {
  const mode = typeof value === "string" ? value.toLowerCase() : "";
  return ["cloud", "hybrid", "local"].includes(mode) ? mode : "cloud";
}

function normalizeAgentMode(value) {
  const mode = typeof value === "string" ? value.toLowerCase() : "";
  return ["agent", "group-agent"].includes(mode) ? mode : "agent";
}

function normalizeContextMode(value) {
  const mode = typeof value === "string" ? value.toLowerCase() : "";
  return ["minimal", "balanced", "deep"].includes(mode) ? mode : "balanced";
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

async function approveModelRequest({ providerMode, contextText, source }) {
  const mode = normalizeAgentProviderMode(providerMode || settings().agentProviderMode);
  if (mode === "local") {
    return true;
  }
  const sendsWorkspace = typeof contextText === "string" && contextText.trim().length > 0;
  const tokenEstimate = estimateTokens(contextText || "");
  const files = workspaceContextFiles(contextText || "");
  const secretWarning = looksLikeSecret(contextText || "")
    ? "Possible secret-like text was detected; review carefully before sending."
    : "No obvious secret patterns detected.";
  return requestPermission({
    category: sendsWorkspace ? "workspace_cloud" : "cloud_provider",
    description: "Agent Hub wants to send this request to a cloud-capable model route.",
    resource: mode,
    risk: sendsWorkspace ? "high" : "medium",
    detail: [
      `Source: ${source || "Agent Hub"}.`,
      `Provider/model: selected by ${mode} route.`,
      `Estimated input: ${tokenEstimate} tokens.`,
      files.length ? `Files/snippets: ${files.slice(0, 6).join(", ")}.` : "Files/snippets: none detected.",
      sendsWorkspace
        ? "Workspace/file context may be included in the model request."
        : "The request may use an external provider depending on routing.",
      secretWarning,
      "Provider API usage may consume quota or credits."
    ].join(" ")
  });
}

function estimateTokens(text) {
  return Math.max(1, Math.ceil(String(text || "").length / 4));
}

function workspaceContextFiles(text) {
  const files = [];
  for (const line of String(text || "").split(/\r?\n/)) {
    const match = line.match(/^\s*(?:Current file|File|Reference):\s*(.+?)\s*$/i);
    if (match && match[1] && !files.includes(match[1].trim())) {
      files.push(match[1].trim());
    }
  }
  return files;
}

function looksLikeSecret(text) {
  return /(api[_-]?key|token|secret|password)\s*[:=]\s*['"]?[^'"\s]{8,}|-----BEGIN .*PRIVATE KEY-----|sk-[A-Za-z0-9_-]{20,}/i.test(String(text || ""));
}

function permissionActionFromApprovalEvent(event) {
  const tool = event && event.tool ? String(event.tool) : "tool";
  const files = Array.isArray(event && event.affected_files) ? event.affected_files : [];
  const commands = Array.isArray(event && event.commands) ? event.commands : [];
  const category = tool === "run_command" ? "shell_command" : "file_write";
  return {
    category,
    description: event && event.summary
      ? `Agent Hub asks permission: ${event.summary}`
      : `Agent Hub asks permission to run ${tool}.`,
    resource: files.length ? files.join(", ") : commands.join(", "),
    risk: event && event.risk_level ? event.risk_level : "medium",
    detail: event && event.impact ? event.impact : ""
  };
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
  if (type === "context_usage_updated") {
    return contextUsageProgressText(event.data);
  }
  if (typeof event.data.message === "string" && event.data.message.trim()) {
    return event.data.message.trim();
  }
  return "";
}

function contextUsageProgressText(data) {
  const inputTokens = Number(data.input_tokens || 0);
  const budgetTokens = Number(data.budget_tokens || 0);
  const percent = Number(data.percent_used || (budgetTokens > 0 ? (inputTokens / budgetTokens) * 100 : 0));
  const clamped = Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : 0;
  const width = 18;
  const filled = Math.max(0, Math.min(width, Math.round((clamped / 100) * width)));
  const bar = "#".repeat(filled) + "-".repeat(width - filled);
  const delta = Number(data.tokens_added_since_last_step || 0);
  const deltaText = `${delta >= 0 ? "+" : ""}${delta}`;
  const compactions = Number(data.compaction_count || data.compacted_messages_count || 0);
  const saved = Number(data.estimated_tokens_saved || 0);
  const warning = data.warning_level && data.warning_level !== "normal" ? ` ${data.warning_level}` : "";
  const budgetText = budgetTokens > 0 ? `${inputTokens}/${budgetTokens}` : `${inputTokens}`;
  const compactText = compactions > 0 ? ` compacted ${compactions}, saved ~${saved}` : " no compaction";
  return `Context [${bar}] ${clamped.toFixed(1)}% (${budgetText} tokens, ${deltaText})${compactText}${warning}`;
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
                if (typeof handlers.onEvent === "function") {
                  handlers.onEvent(event);
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
            if (parsed.error && parsed.error.suggested_fix) {
              error.suggestedFix = parsed.error.suggested_fix;
              error.message += ` Suggested fix: ${parsed.error.suggested_fix}`;
            }
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
