"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");
const runtimePolicy = require("./runtime-policy");

let serverProcess = null;
let modelPullProcess = null;
let output;
let chatPanel = null;
let chatWebviewReady = false;
let pendingChatRequests = [];
let extensionContext = null;
let sidebarProvider = null;
let statusBarItem = null;
let benchmarkSharePanel = null;
let routeLabPanel = null;
let lastActiveTextEditor = null;
let serverLifecycleState = "Stopped";
let lastServerMessage = "";
const runtimeApprovalToken = crypto.randomBytes(32).toString("hex");
const EXTENSION_VERSION = readExtensionPackageVersion();
const DEFAULT_CONFIG_FILENAME = "agent-hub.config.json";
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
const DEFAULT_CODEX_CLI_MODEL = "gpt-5.5";
const DEFAULT_AGENT_CONTEXT_BUDGET = 32000;
const DEFAULT_AGENT_MAX_STEPS = 20;
const MAX_TOKEN_SAVE_OUTPUT_TOKENS = 800;
const CODEX_CLI_CONTEXT_BUDGET = 2400;
const CODEX_CLI_OUTPUT_TOKENS = 500;
const CODEX_CLI_AGENT_STEPS = 6;
const CODEX_CLI_REPO_FILES = 1;
const CODEX_CLI_REPO_CHARS = 1800;
const CODEX_CLI_NPM_PACKAGE = "@openai/codex@latest";
const OLLAMA_BASE_URL = "http://127.0.0.1:11434";
const OLLAMA_DOWNLOAD_URL = "https://ollama.com/download";
const LM_STUDIO_BASE_URL = "http://127.0.0.1:1234";
const PYTHON_DOWNLOAD_URL = "https://www.python.org/downloads/";
const NODE_DOWNLOAD_URL = "https://nodejs.org/en/download";
const README_PROOF_URL = "https://github.com/350285449/Agent-Hub#proof-you-can-run-locally";
const FIRST_RUN_PROOF_VERSION_KEY = "agentHub.firstRunProofPromptedVersion";
const PERSONAL_BENCHMARK_LIMIT = 50;
const PERSONAL_BENCHMARK_PROMPT = "Fix a failing pytest in a repository service layer, update the regression test, and explain why the route was selected.";
const PYTHON_WINGET_ID = "Python.Python.3.12";
const NODE_WINGET_ID = "OpenJS.NodeJS.LTS";
const CODEX_CLI_AGENT_NAME = "codex-cli";
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
const LOCAL_API_KEY_OPTIONAL_PROVIDER_TYPES = new Set([
  "codex-cli",
  "echo",
  "llama-cpp",
  "lm-studio",
  "local-research",
  "localai",
  "ollama",
  "ollama-local",
  "vllm"
]);
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
  "provider_presets",
  "routing_intelligence_api",
  "routing_memory_api",
  "optimization_dashboard",
  "routing_simulation",
  "cost_dashboard",
  "model_leaderboard",
  "benchmark_results_dashboard",
  "workspace_checkpoints",
  "workspace_rollback_api",
  "events_endpoint",
  "dashboard_status_endpoints",
  "tool_execution_loop",
  "readiness_scorecard",
  "feature_maturity_status",
  "production_acceptance_check",
  "runtime_kernel_control_plane",
  "runtime_kernel_dashboard"
];
const APPROVAL_MODES = new Set(["ask", "auto", "safe", "readonly", "shell-ask", "deny"]);
const SENSITIVE_PERMISSION_CATEGORIES = new Set([
  "cloud_provider",
  "config_edit",
  "file_write",
  "model_exploration",
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
  return runtimePolicy.normalizeApprovalMode(value);
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
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      showFirstRunProofPrompt(context).catch((error) => {
        output.appendLine(`Could not show first-run proof prompt after workspace change: ${error.message}`);
      });
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
    vscode.commands.registerCommand("agentHub.openDashboard", () => openAgentHubDashboard("/dashboard")),
    vscode.commands.registerCommand("agentHub.openRuntimeKernel", () => openAgentHubDashboard("/dashboard/kernel")),
    vscode.commands.registerCommand("agentHub.openSettings", openAgentHubSettings),
    vscode.commands.registerCommand("agentHub.runCheckup", () => runCheckupCommand()),
    vscode.commands.registerCommand("agentHub.checkRequirements", checkRequirementsCommand),
    vscode.commands.registerCommand("agentHub.fixSafeConfig", fixSafeConfigCommand),
    vscode.commands.registerCommand("agentHub.installPython", installPythonCommand),
    vscode.commands.registerCommand("agentHub.installNode", installNodeCommand),
    vscode.commands.registerCommand("agentHub.enableFreeOnlyMode", enableFreeOnlyModeCommand),
    vscode.commands.registerCommand("agentHub.enableTokenSafeMode", enableTokenSafeModeCommand),
    vscode.commands.registerCommand("agentHub.enableCodexCliMode", enableCodexCliModeCommand),
    vscode.commands.registerCommand("agentHub.installCodexCli", installCodexCliCommand),
    vscode.commands.registerCommand("agentHub.installOllamaDesktop", installOllamaDesktopCommand),
    vscode.commands.registerCommand("agentHub.status", showStatus),
    vscode.commands.registerCommand("agentHub.ask", askAgent),
    vscode.commands.registerCommand("agentHub.codeAgent", runCodingAgent),
    vscode.commands.registerCommand("agentHub.generateCommitMessage", generateCommitMessage),
    vscode.commands.registerCommand("agentHub.research", researchWeb),
    vscode.commands.registerCommand("agentHub.explainSelection", explainSelection),
    vscode.commands.registerCommand("agentHub.explainFile", explainFile),
    vscode.commands.registerCommand("agentHub.copyClineConfig", copyClineConfig),
    vscode.commands.registerCommand("agentHub.testClineConnection", testClineConnection),
    vscode.commands.registerCommand("agentHub.showClineSetup", showClineSetup),
    vscode.commands.registerCommand("agentHub.copyClaudeCodeConfig", copyClaudeCodeConfig),
    vscode.commands.registerCommand("agentHub.testAnthropicEndpoint", testAnthropicEndpoint),
    vscode.commands.registerCommand("agentHub.showClaudeCodeSetup", showClaudeCodeSetup),
    vscode.commands.registerCommand("agentHub.rollbackLatestCheckpoint", rollbackLatestCheckpoint),
    vscode.commands.registerCommand("agentHub.openModelLeaderboard", () => openAgentHubDashboard("/dashboard/model-leaderboard")),
    vscode.commands.registerCommand("agentHub.openCostDashboard", () => openAgentHubDashboard("/dashboard/costs")),
    vscode.commands.registerCommand("agentHub.openBenchmarkResults", () => openAgentHubDashboard("/dashboard/benchmarks")),
    vscode.commands.registerCommand("agentHub.runPersonalBenchmark", () => runPersonalBenchmark()),
    vscode.commands.registerCommand("agentHub.explainRoute", () => explainRouteCommand()),
    vscode.commands.registerCommand("agentHub.openRouteLab", () => openRouteLabCommand()),
    vscode.commands.registerCommand("agentHub.openBenchmarkShareCard", () => openLatestBenchmarkShareCard()),
    vscode.commands.registerCommand("agentHub.openReadmeProof", openReadmeProofSection),
    vscode.commands.registerCommand("agentHub.openOutput", () => output.show())
  );
  scheduleFirstRunProofPrompt(context);
}

async function openAgentHubDashboard(pathname) {
  const url = new URL(pathname, settings().serverUrl);
  await vscode.env.openExternal(vscode.Uri.parse(url.toString()));
}

function scheduleFirstRunProofPrompt(context) {
  setTimeout(() => {
    showFirstRunProofPrompt(context).catch((error) => {
      output.appendLine(`Could not show first-run proof prompt: ${error.message}`);
    });
  }, 1800);
}

async function showFirstRunProofPrompt(context, options = {}) {
  if (!context || !context.globalState) {
    return;
  }
  const storedVersion = context.globalState.get(FIRST_RUN_PROOF_VERSION_KEY, "");
  if (options.force !== true && !runtimePolicy.shouldShowFirstRunProofPrompt(storedVersion, EXTENSION_VERSION)) {
    return;
  }
  if (!workspaceRoot()) {
    return;
  }
  await context.globalState.update(FIRST_RUN_PROOF_VERSION_KEY, EXTENSION_VERSION);
  const checkup = "Run Checkup";
  const run = "Run Benchmark";
  const routeLab = "Open Route Lab";
  const proof = "Open Proof";
  const choice = await vscode.window.showInformationMessage(
    "Agent-Hub can check setup, repair safe config issues, start the backend, and show route reasoning in one pass.",
    checkup,
    run,
    routeLab,
    proof,
    "Later"
  );
  if (choice === checkup) {
    await runCheckupCommand({ source: "first-run" });
  } else if (choice === run) {
    await runPersonalBenchmark({ source: "first-run" });
  } else if (choice === routeLab) {
    await openRouteLabCommand({ prompt: PERSONAL_BENCHMARK_PROMPT });
  } else if (choice === proof) {
    await openReadmeProofSection();
  }
}

async function openReadmeProofSection() {
  await vscode.env.openExternal(vscode.Uri.parse(README_PROOF_URL));
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
          providerMode: settings().agentProviderMode,
          autoSend: message.autoSend !== false
        });
      }
      return;
    }
    if (message.type === "applyTrustPreset") {
      await applySidebarTrustPreset(message.preset);
      await this.refresh();
      return;
    }
    if (message.type === "enableTokenSafeMode") {
      await enableTokenSafeModeCommand({ refreshSidebar: false });
      await this.refresh();
      return;
    }
    if (message.type === "enableFreeOnlyMode") {
      await enableFreeOnlyModeCommand({ refreshSidebar: false });
      await this.refresh();
      return;
    }
    if (message.type === "enableCodexCliMode") {
      await enableCodexCliModeCommand({ refreshSidebar: false });
      await this.refresh();
      return;
    }
    if (message.type === "toggleAutomatedFeedback") {
      await toggleAutomatedModelFeedback();
      await this.refresh();
      return;
    }
    if (message.type === "installCodexCli") {
      await installCodexCliCommand();
      await this.refresh();
      return;
    }
    if (message.type === "installOllamaDesktop") {
      await installOllamaDesktopCommand();
      await this.refresh();
      return;
    }
    if (message.type === "openDashboard") {
      await openAgentHubDashboard("/dashboard");
      return;
    }
    if (message.type === "openRuntimeKernel") {
      await openAgentHubDashboard("/dashboard/kernel");
      return;
    }
    if (message.type === "runCheckup") {
      await runCheckupCommand({ source: "sidebar" });
      await this.refresh();
      return;
    }
    if (message.type === "openRoutingDashboard") {
      await openAgentHubDashboard("/dashboard/routing-intelligence");
      return;
    }
    if (message.type === "runPersonalBenchmark") {
      await runPersonalBenchmark();
      await this.refresh();
      return;
    }
    if (message.type === "openBenchmarkShareCard") {
      await openLatestBenchmarkShareCard();
      return;
    }
    if (message.type === "explainRoute") {
      await explainRouteCommand();
      return;
    }
    if (message.type === "openRouteLab") {
      await openRouteLabCommand();
      return;
    }
    if (message.type === "openReadmeProof") {
      await openReadmeProofSection();
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
    if (message.type === "checkRequirements") {
      await checkRequirementsCommand();
      await this.refresh();
      return;
    }
    if (message.type === "fixSafeConfig") {
      await fixSafeConfigCommand();
      await this.refresh();
      return;
    }
    if (message.type === "installPython") {
      await installPythonCommand();
      await this.refresh();
      return;
    }
    if (message.type === "installNode") {
      await installNodeCommand();
      await this.refresh();
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

async function applySidebarTrustPreset(preset) {
  const profiles = {
    safe: {
      approvalMode: "safe",
      allowShellTools: true,
      label: "Safe approvals"
    },
    shellAsk: {
      approvalMode: "shell-ask",
      allowShellTools: true,
      label: "Confirm shell"
    },
    readonly: {
      approvalMode: "readonly",
      allowShellTools: false,
      label: "Read-only"
    },
    auto: {
      approvalMode: "auto",
      allowShellTools: true,
      label: "Auto"
    }
  };
  const profile = profiles[preset] || profiles.safe;
  const config = vscode.workspace.getConfiguration("agentHub");
  await config.update("approvalMode", profile.approvalMode, vscode.ConfigurationTarget.Global);
  await config.update("allowShellTools", profile.allowShellTools, vscode.ConfigurationTarget.Global);
  const restart = serverProcess || (await isServerOnline())
    ? " Restart Agent Hub if an already-running backend should inherit this default."
    : "";
  vscode.window.showInformationMessage(`Agent Hub trust controls set to ${profile.label}.${restart}`);
}

async function toggleAutomatedModelFeedback(nextValue) {
  const current = settings().automatedModelFeedback;
  const enabled = typeof nextValue === "boolean" ? nextValue : !current;
  const config = vscode.workspace.getConfiguration("agentHub");
  await config.update("automatedModelFeedback", enabled, vscode.ConfigurationTarget.Global);
  const message = enabled
    ? "Automated model feedback is on. Agent Hub will ask a judge model to score successful chat responses."
    : "Automated model feedback is off.";
  vscode.window.showInformationMessage(message);
  postChatSettings(chatPanel, message);
  return { ok: true, enabled, message };
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
  const cloudSettings = cloudModelSettingsPayload(config);
  const dashboard = {
    status: serverLifecycleState,
    statusText: lastServerMessage || "Agent Hub is not running.",
    serverUrl: config.serverUrl,
    agentProviderMode: config.agentProviderMode,
    agentMode: config.agentMode,
    approvalMode: config.approvalMode,
    tokenSafeMode: isFreeCloudSavingsMode(config),
    freeOnlyStrictMode: cloudSettings.freeOnly !== false && cloudSettings.disableNonFreeModels === true,
    codexCliMode: isMaxTokenSaveMode(config) && cloudSettings.cloudRouteMode === "codex-cli",
    autoStart: config.autoStart,
    automatedModelFeedback: config.automatedModelFeedback,
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
    readiness: null,
    optimization: null,
    routingIntelligence: null,
    routingExplanation: null,
    runtimeKernel: sidebarRuntimeKernel(null),
    modelStats: sidebarModelStats(null, null, null, null),
    orchestrationFlow: sidebarOrchestrationFlow(null, null),
    workflowTemplates: sidebarWorkflowTemplates(),
    workspaceProfile: await sidebarWorkspaceProfile(config, null),
    tools: [],
    trustControls: sidebarTrustControls(config, null, []),
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
    let routingIntelligence = null;
    let runtimeKernel = null;
    let debugContext = null;
    let tools = null;
    let modelLeaderboard = null;
    let benchmarks = null;
    let costDashboard = null;
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
      routingIntelligence = await requestJson("GET", "/v1/routing-intelligence");
    } catch (_error) {
      routingIntelligence = null;
    }
    try {
      runtimeKernel = await requestJson("GET", "/v1/kernel");
    } catch (_error) {
      runtimeKernel = null;
    }
    try {
      debugContext = await requestJson("GET", "/debug/context");
    } catch (_error) {
      debugContext = null;
    }
    try {
      tools = await requestJson("GET", "/v1/tools");
    } catch (_error) {
      tools = null;
    }
    try {
      modelLeaderboard = await requestJson("GET", "/v1/model-leaderboard");
    } catch (_error) {
      modelLeaderboard = null;
    }
    try {
      benchmarks = await requestJson("GET", "/v1/benchmarks");
    } catch (_error) {
      benchmarks = null;
    }
    try {
      costDashboard = await requestJson("GET", "/v1/cost-dashboard");
    } catch (_error) {
      costDashboard = null;
    }
    dashboard.status = "Running";
    dashboard.statusText = `Running at ${config.serverUrl}`;
    dashboard.health = health;
    dashboard.readiness = health && health.readiness && typeof health.readiness === "object" ? health.readiness : null;
    dashboard.activeModel = sidebarActiveModel(health, limits);
    dashboard.providers = sidebarProviderRows(health, limits);
    dashboard.limits = sidebarLimitRows(health, limits);
    dashboard.failedModels = sidebarFailedModels(health, limits);
    dashboard.permissions = sidebarPermissionState(health, permissions, config);
    dashboard.tokenUsage = sidebarTokenUsage(usage, dashboard.limits);
    dashboard.contextDiagnostics = sidebarContextDiagnostics(debugContext);
    dashboard.tools = sidebarToolRows(tools);
    dashboard.optimization = optimization || (metrics && metrics.optimization) || null;
    dashboard.routingIntelligence = routingIntelligence;
    dashboard.routingExplanation = sidebarRoutingExplanation(routingIntelligence, health, limits);
    dashboard.runtimeKernel = sidebarRuntimeKernel(runtimeKernel);
    if (metrics && dashboard.optimization) {
      metrics.optimization = dashboard.optimization;
    }
    dashboard.statistics = sidebarStatistics(health, usage, metrics, permissions, dashboard.providers, dashboard.limits, debugContext, dashboard.optimization, dashboard.readiness);
    dashboard.modelStats = sidebarModelStats(dashboard, modelLeaderboard, benchmarks, costDashboard);
    dashboard.insights = sidebarInsightRows(dashboard, metrics);
    dashboard.onboarding = await sidebarOnboardingState(config, health);
    dashboard.workspaceProfile = await sidebarWorkspaceProfile(config, health);
    dashboard.orchestrationFlow = sidebarOrchestrationFlow(metrics, dashboard);
    dashboard.workflowTemplates = sidebarWorkflowTemplates();
    dashboard.trustControls = sidebarTrustControls(config, permissions, dashboard.tools);
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

function sidebarStatistics(health, usage, metrics, permissions, providers, limits, debugContext, optimization, readiness) {
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
  const readinessScore = readiness && Number.isFinite(Number(readiness.score))
    ? Math.max(0, Math.min(100, Math.round(Number(readiness.score))))
    : null;
  const readinessState = readiness && readiness.state ? String(readiness.state).replace(/_/g, " ") : "";
  const readinessNextStep = readiness && readiness.next_step && typeof readiness.next_step === "object"
    ? readiness.next_step
    : null;

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
    readinessScore,
    readinessState,
    readinessNextStepLabel: readinessNextStep && readinessNextStep.label ? readinessNextStep.label : "",
    readinessNextStepDetail: readinessNextStep && readinessNextStep.detail ? readinessNextStep.detail : "",
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

function sidebarModelStats(dashboard, leaderboard, benchmarks, costDashboard) {
  const stats = dashboard && dashboard.statistics ? dashboard.statistics : {};
  const active = dashboard && dashboard.activeModel ? dashboard.activeModel : null;
  const failedModels = dashboard && Array.isArray(dashboard.failedModels) ? dashboard.failedModels : [];
  const leaderboardSummary = objectValue(leaderboard && leaderboard.summary);
  const benchmarkSummary = objectValue(benchmarks && benchmarks.summary);
  const benchmarkCoverage = objectValue(benchmarks && benchmarks.coverage_snapshot);
  const benchmarkCoverageSummary = objectValue(benchmarkCoverage.summary);
  const costSummary = objectValue(costDashboard && costDashboard.summary);
  const rows = Array.isArray(leaderboard && leaderboard.data) ? leaderboard.data : [];
  const activeRow = active
    ? rows.find((row) => (
      row &&
      (row.agent === active.agent || row.model === active.model || row.provider === active.provider)
    ))
    : null;
  const leader = rows[0] || activeRow || {};
  const healthScore = numberOrZero(stats.healthScore);
  const gatewayOnline = dashboard && dashboard.status === "Running" && numberOrZero(stats.providersAvailable) > 0;
  const fallbackSignals = numberOrZero(stats.routingFallbacks) + failedModels.length + numberOrZero(stats.recentFailures);
  const measuredSamples = numberOrZero(leaderboardSummary.sample_count);
  const measuredAgents = numberOrZero(leaderboardSummary.measured_agent_count);
  const benchmarkReports = numberOrZero(benchmarkSummary.report_count);
  const averageReadiness = numberOrZero(benchmarkCoverageSummary.average_readiness_score);
  const pricingCoverage = Math.round(numberOrZero(costSummary.pricing_coverage_rate) * 100);
  const knownCost = numberValueOrNull(
    costSummary.known_cost_usd,
    costDashboard && costDashboard.known_cost_usd
  );
  const averageKnownCost = numberValueOrNull(
    costSummary.average_known_cost_usd,
    costDashboard && costDashboard.average_known_cost_usd
  );

  const incidents = [];
  if (!gatewayOnline) {
    incidents.push({
      label: dashboard && dashboard.status === "Running" ? "No ready provider" : "Gateway offline",
      detail: dashboard && dashboard.statusText ? dashboard.statusText : "Start Agent Hub to collect model signals.",
      tone: dashboard && dashboard.status === "Running" ? "error" : "warn"
    });
  }
  for (const failed of failedModels.slice(0, 3)) {
    incidents.push({
      label: failed.model || failed.agent || failed.provider || "Provider issue",
      detail: failed.reason || "Recent provider failure",
      tone: "error"
    });
  }
  if (!measuredSamples && rows.length) {
    incidents.push({
      label: "Measurements pending",
      detail: "Configured baselines are ranked; live outcomes will sharpen model stats.",
      tone: "warn"
    });
  }
  if (pricingCoverage > 0 && pricingCoverage < 100) {
    incidents.push({
      label: "Pricing coverage partial",
      detail: `${pricingCoverage}% of configured model pricing is covered.`,
      tone: "warn"
    });
  }
  if (!incidents.length) {
    incidents.push({
      label: "No incident signals",
      detail: "Provider health, cost, benchmark, and routing signals look clean.",
      tone: "ok"
    });
  }

  const routerRows = rows.slice(0, 6).map((row) => ({
    agent: row.agent || "",
    provider: row.provider || "",
    model: row.model || "",
    rank: row.rank,
    score: Math.round(numberOrZero(row.ranking_score || row.overall_score || row.baseline_score)),
    successRate: Math.round(numberOrZero(row.success_rate) * 100),
    latencyMs: numberOrZero(row.average_latency_ms),
    samples: numberOrZero(row.samples),
    status: row.measurement_status || "configured_baseline",
    free: !!row.free
  }));

  return {
    gateway: {
      status: gatewayOnline ? "Online" : dashboard && dashboard.status === "Running" ? "Needs provider" : "Offline",
      detail: active
        ? [active.provider || active.agent || "provider", active.model || ""].filter(Boolean).join(" / ")
        : dashboard && dashboard.serverUrl
          ? dashboard.serverUrl
          : "No active model yet",
      tone: gatewayOnline ? "ok" : dashboard && dashboard.status === "Running" ? "error" : "warn"
    },
    tiles: [
      {
        label: "Gateway",
        value: gatewayOnline ? "Online" : "Offline",
        detail: active ? (active.agent || active.provider || "active route") : "no active route",
        tone: gatewayOnline ? "ok" : "error"
      },
      {
        label: "Sessions",
        value: compactStatValue(stats.requests || measuredSamples),
        detail: measuredSamples ? `${measuredSamples} learned sample(s)` : "waiting for requests",
        tone: measuredSamples ? "info" : "warn"
      },
      {
        label: "Agent Capacity",
        value: String(numberOrZero(stats.providersAvailable)),
        detail: `${numberOrZero(stats.providersTotal)} configured provider(s)`,
        tone: numberOrZero(stats.providersAvailable) ? "ok" : "error"
      },
      {
        label: "Queues",
        value: String(fallbackSignals),
        detail: "fallback, failure, and incident signals",
        tone: fallbackSignals ? "warn" : "ok"
      },
      {
        label: "System Load",
        value: dashboard && dashboard.status === "Running" ? `${healthScore}%` : "--",
        detail: "provider health score",
        tone: healthScore >= 80 ? "ok" : healthScore >= 50 ? "warn" : "error"
      }
    ],
    goldenSignals: [
      {
        label: "Traffic",
        value: compactStatValue(stats.totalCalls || stats.requests),
        detail: "provider calls"
      },
      {
        label: "Errors",
        value: compactStatValue(stats.failedCalls || failedModels.length),
        detail: `${numberOrZero(stats.successRate)}% success`
      },
      {
        label: "Saturation",
        value: `${numberOrZero(stats.providerAvailabilityPercent)}%`,
        detail: "provider availability"
      },
      {
        label: "Memory",
        value: compactStatValue(stats.totalTokens),
        detail: "tokens used"
      },
      {
        label: "Bench",
        value: averageReadiness ? `${Math.round(averageReadiness)}%` : "--",
        detail: benchmarkReports ? `${benchmarkReports} report(s)` : "baseline snapshot"
      },
      {
        label: "Cost",
        value: moneySummaryText(knownCost, averageKnownCost),
        detail: pricingCoverage ? `${pricingCoverage}% pricing coverage` : "pricing pending"
      }
    ],
    routerRows,
    incidents: incidents.slice(0, 5),
    taskFlow: [
      {
        label: "In box",
        value: compactStatValue(stats.requests),
        detail: "recent request traces"
      },
      {
        label: "In progress",
        value: compactStatValue(stats.workflows),
        detail: "workflow events"
      },
      {
        label: "Done",
        value: compactStatValue(stats.successfulCalls),
        detail: "successful provider calls"
      },
      {
        label: "Blocked",
        value: compactStatValue(numberOrZero(stats.failedCalls) + failedModels.length),
        detail: "failed calls and provider incidents"
      }
    ],
    auditRows: [
      {
        label: "Measured agents",
        value: `${measuredAgents}/${numberOrZero(leaderboardSummary.agent_count)}`,
        detail: leaderboardSummary.data_state || "baseline pending"
      },
      {
        label: "Benchmark reports",
        value: String(benchmarkReports),
        detail: benchmarkSummary.data_state || "baseline pending"
      },
      {
        label: "Pricing",
        value: pricingCoverage ? `${pricingCoverage}%` : "--",
        detail: costSummary.measurement_state || "waiting for usage"
      },
      {
        label: "Auto feedback",
        value: dashboard && dashboard.automatedModelFeedback ? "On" : "Off",
        detail: "judge model feedback loop"
      }
    ],
    best: {
      agent: leader.agent || "",
      provider: leader.provider || active && active.provider || "",
      model: leader.model || active && active.model || "",
      score: Math.round(numberOrZero(leader.ranking_score || leader.overall_score || leader.baseline_score)),
      status: leader.measurement_status || "waiting"
    },
    active: activeRow || active || null
  };
}

function sidebarRuntimeKernel(kernel) {
  const body = objectValue(kernel);
  const telemetry = objectValue(body.request_telemetry);
  const latency = objectValue(telemetry.latency_ms);
  const pressure = objectValue(body.pressure);
  const cache = objectValue(body.diagnostics_cache);
  const subsystems = Array.isArray(body.subsystems) ? body.subsystems : [];
  const timeline = Array.isArray(body.timeline) ? body.timeline : [];
  const score = numberValueOrNull(body.operational_score);
  const state = body.state ? String(body.state).replace(/_/g, " ") : "offline";
  const isOnline = body.object === "agent_hub.runtime_kernel";
  const pressureSignals = Array.isArray(pressure.signals) ? pressure.signals : [];
  const nextActions = Array.isArray(body.next_actions) ? body.next_actions : [];
  const cacheHitRate = numberValueOrNull(cache.hit_rate, telemetry.cache_hit_rate);
  const ewmaLatency = numberValueOrNull(latency.ewma);
  const totalRequests = numberOrZero(telemetry.total_requests);
  const slowCount = Array.isArray(telemetry.recent_slow_requests)
    ? telemetry.recent_slow_requests.length
    : numberOrZero(body.slow_request_count);

  return {
    online: isOnline,
    title: isOnline ? `Kernel ${score === null ? "--" : Math.round(score)}/100` : "Kernel offline",
    detail: isOnline
      ? `${state} / uptime ${durationText(body.uptime_seconds)} / ${compactStatValue(totalRequests)} request(s)`
      : "Start Agent Hub to inspect runtime pressure and subsystem state.",
    state: isOnline ? state : "offline",
    score: score === null ? null : Math.round(score),
    status: isOnline ? state : "Offline",
    statusTone: runtimeTone(pressure.state || state, score),
    tiles: [
      {
        label: "State",
        value: isOnline ? state : "Offline",
        detail: isOnline ? `boot ${String(body.boot_id || "").slice(0, 8) || "unknown"}` : "waiting for backend",
        tone: runtimeTone(pressure.state || state, score)
      },
      {
        label: "Requests",
        value: compactStatValue(totalRequests),
        detail: `${numberOrZero(telemetry.in_flight)} in flight`,
        tone: numberOrZero(telemetry.in_flight) > 4 ? "warn" : "ok"
      },
      {
        label: "Latency",
        value: latencyText(ewmaLatency),
        detail: `max ${latencyText(latency.max)}`,
        tone: ewmaLatency !== null && ewmaLatency >= 750 ? "warn" : "ok"
      },
      {
        label: "Cache",
        value: cacheHitRate === null ? "--" : `${Math.round(cacheHitRate * 100)}%`,
        detail: `${numberOrZero(cache.entries)} live entries`,
        tone: cacheHitRate !== null && cacheHitRate < 0.2 && numberOrZero(cache.misses) > 8 ? "warn" : "ok"
      },
      {
        label: "Slow Path",
        value: compactStatValue(slowCount),
        detail: "retained slow request(s)",
        tone: slowCount ? "warn" : "ok"
      }
    ],
    pressureRows: pressureSignals.map((signal) => ({
      label: signal.id || "pressure",
      value: signal.value === null || signal.value === undefined ? "" : String(signal.value),
      detail: signal.detail || "",
      tone: signal.state === "hot" ? "error" : signal.state === "elevated" ? "warn" : "ok"
    })),
    actionRows: nextActions.map((row) => ({
      label: row.title || "Recommended action",
      value: row.severity || "",
      detail: [row.detail, row.command ? `Command: ${row.command}` : "", row.path ? `Open: ${row.path}` : ""].filter(Boolean).join(" / "),
      tone: row.severity === "critical" ? "error" : row.severity === "warn" ? "warn" : row.severity === "ok" ? "ok" : "info"
    })),
    subsystemRows: subsystems.map((row) => ({
      label: row.id || "subsystem",
      value: row.state || "unknown",
      detail: row.detail || "",
      tone: row.state === "critical" || row.state === "degraded" ? "error" : row.state === "watching" || row.state === "needs_setup" ? "warn" : "ok"
    })),
    timelineRows: timeline.slice(0, 6).map((row) => ({
      label: row.title || row.type || "kernel event",
      value: row.tone === "error" ? "issue" : row.tone === "warn" ? "watch" : "ok",
      detail: [row.timestamp, row.detail].filter(Boolean).join(" - "),
      tone: row.tone || "info"
    }))
  };
}

function runtimeTone(state, score) {
  const text = String(state || "").toLowerCase();
  if (text.includes("critical") || text.includes("hot") || (score !== null && score < 55)) {
    return "error";
  }
  if (text.includes("degraded") || text.includes("elevated") || text.includes("attention") || (score !== null && score < 80)) {
    return "warn";
  }
  return "ok";
}

function latencyText(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    return "--";
  }
  if (number >= 1000) {
    return `${(number / 1000).toFixed(1)}s`;
  }
  return `${Math.round(number)}ms`;
}

function durationText(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "--";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const minutes = seconds / 60;
  if (minutes < 60) {
    return `${Math.round(minutes)}m`;
  }
  const hours = minutes / 60;
  if (hours < 48) {
    return `${hours.toFixed(1)}h`;
  }
  return `${(hours / 24).toFixed(1)}d`;
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function numberValueOrNull(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number)) {
      return number;
    }
  }
  return null;
}

function numberOrZero(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function compactStatValue(value) {
  const number = numberOrZero(value);
  if (Math.abs(number) >= 1000000) {
    return `${(number / 1000000).toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (Math.abs(number) >= 1000) {
    return `${(number / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  }
  return String(Math.round(number));
}

function moneySummaryText(knownCost, averageKnownCost) {
  const value = knownCost !== null ? knownCost : averageKnownCost;
  if (value === null) {
    return "--";
  }
  return `$${Number(value || 0).toFixed(value < 0.01 ? 4 : 2)}`;
}

function sidebarInsightRows(dashboard, metrics) {
  const stats = dashboard.statistics || {};
  const insights = [];
  if (dashboard.status !== "Running") {
    insights.push({ tone: "warn", main: "Agent Hub is off", meta: "Click Start to collect health and usage numbers." });
  }
  if (dashboard.status === "Running" && stats.readinessScore !== null && stats.readinessScore !== undefined) {
    if (stats.readinessScore >= 90) {
      insights.push({ tone: "ok", main: `Readiness ${stats.readinessScore}/100`, meta: stats.readinessState || "production ready" });
    } else if (stats.readinessNextStepLabel) {
      insights.push({ tone: "warn", main: `Readiness ${stats.readinessScore}/100`, meta: `${stats.readinessNextStepLabel}: ${stats.readinessNextStepDetail || "review readiness"}` });
    }
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

function sidebarRoutingExplanation(intelligence, health, limits) {
  const latest = intelligence && intelligence.latest_explanation && typeof intelligence.latest_explanation === "object"
    ? intelligence.latest_explanation
    : {};
  const latestDecision = intelligence && intelligence.latest_decision && typeof intelligence.latest_decision === "object"
    ? intelligence.latest_decision
    : {};
  const selected = latest.selected && typeof latest.selected === "object" ? latest.selected : {};
  const context = latest.context_optimization && typeof latest.context_optimization === "object"
    ? latest.context_optimization
    : intelligence && intelligence.context_optimization && typeof intelligence.context_optimization === "object"
      ? intelligence.context_optimization
      : {};
  const cost = latest.cost_savings && typeof latest.cost_savings === "object"
    ? latest.cost_savings
    : intelligence && intelligence.cost_savings && typeof intelligence.cost_savings === "object"
      ? intelligence.cost_savings
      : {};
  const repository = intelligence && intelligence.repository_dna && typeof intelligence.repository_dna === "object"
    ? intelligence.repository_dna
    : latest.repository_dna && typeof latest.repository_dna === "object"
      ? latest.repository_dna
      : {};
  const prediction = latest.failure_prediction && typeof latest.failure_prediction === "object"
    ? latest.failure_prediction
    : intelligence && intelligence.failure_prediction && typeof intelligence.failure_prediction === "object"
      ? intelligence.failure_prediction
      : {};
  const costOptimizer = intelligence && intelligence.cost_optimizer && typeof intelligence.cost_optimizer === "object"
    ? intelligence.cost_optimizer
    : {};
  const rejected = Array.isArray(latest.rejected)
    ? latest.rejected
    : intelligence && Array.isArray(intelligence.failover_events)
      ? intelligence.failover_events
      : [];
  const reasons = Array.isArray(latest.reasons) ? latest.reasons : [];
  const fallbackOptions = Array.isArray(latest.provider_rankings)
    ? latest.provider_rankings.slice(1, 5)
    : sidebarRoutingChain(health, limits).slice(1, 5);
  const costEstimate = firstNumber(
    prediction.estimated_cost_usd,
    cost.estimated_selected_cost_usd,
    cost.estimated_cost_usd,
    context.estimated_cost_usd,
    latestDecision.estimated_cost_usd
  );
  const latencyMs = firstNumber(
    prediction.estimated_time_seconds ? Number(prediction.estimated_time_seconds) * 1000 : null,
    latestDecision.latency_ms,
    selected.latency_ms,
    selected.average_latency_ms
  );
  const fallbackCount = firstNumber(
    latestDecision.fallback_count,
    Array.isArray(latestDecision.failover) ? latestDecision.failover.length : null,
    rejected.length
  );
  return {
    summary: latest.summary || "",
    selectedProvider: selected.provider || "",
    selectedModel: selected.model || "",
    selectedAgent: selected.agent || "",
    selectedWorkflow: selected.workflow || "direct route",
    riskLevel: selected.risk_level || "",
    taskType: selected.task_type || "",
    contextStrategy: context.context_strategy || "",
    contextTokens: Number(context.estimated_total_tokens || context.estimated_input_tokens || 0),
    repoSize: context.repo_size_bucket || "",
    costSavings: cost.estimated_savings_usd,
    savedToday: costOptimizer.saved_today_usd,
    savedMonth: costOptimizer.saved_this_month_usd,
    costEstimate,
    latencyMs,
    successChance: firstNumber(
      prediction.chance_of_success_percent,
      prediction.chance_of_success ? Number(prediction.chance_of_success) * 100 : null
    ),
    repositoryProject: repository.project || "",
    repositoryLanguage: repository.language || "",
    repositoryArchitecture: repository.architecture || "",
    repositoryTesting: repository.testing || "",
    fallbackCount,
    reasons: reasons.slice(0, 6),
    rejected: rejected.slice(0, 4),
    fallbackOptions
  };
}

function firstNumber(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number)) {
      return number;
    }
  }
  return null;
}

function sidebarWorkflowTemplates() {
  return [
    {
      id: "fixBug",
      label: "Fix Bug",
      meta: "debug + patch + test",
      prompt: "Find the most likely bug behind the current failure. Plan the fix, edit the needed files, run the most relevant tests, fix any failures once, and summarize the change."
    },
    {
      id: "addFeature",
      label: "Add Feature",
      meta: "plan + implement",
      prompt: "Add the requested feature in this workspace. Identify the right files, implement the change, run targeted validation, and summarize the user-facing result."
    },
    {
      id: "reviewCode",
      label: "Review Code",
      meta: "bugs first",
      prompt: "Review the current selection or recent workspace changes. Prioritize bugs, regressions, security issues, and missing tests with file references."
    },
    {
      id: "refactor",
      label: "Refactor",
      meta: "scoped cleanup",
      prompt: "Refactor the relevant code while preserving behavior. Keep the change scoped, run targeted validation, and summarize what became simpler."
    },
    {
      id: "writeTests",
      label: "Write Tests",
      meta: "coverage gap",
      prompt: "Find the important untested behavior for this request, add focused tests, run them, and fix any failures caused by the new tests."
    },
    {
      id: "explainRepo",
      label: "Explain Repo",
      meta: "architecture",
      prompt: "Inspect this repository and explain how it is organized, where the main entry points are, and what a new contributor should read first."
    },
    {
      id: "generatePr",
      label: "Generate PR",
      meta: "summary + risks",
      prompt: "Run the issue-to-PR workflow for the current changes: inspect the diff, summarize the pull request, include validation, risks, and follow-up work."
    }
  ];
}

function sidebarOrchestrationFlow(metrics, dashboard) {
  const events = metrics && Array.isArray(metrics.workflow_events) ? metrics.workflow_events : [];
  const latestWorkflowId = latestWorkflowIdFromEvents(events);
  const recent = latestWorkflowId
    ? events.filter((event) => event && event.workflow_id === latestWorkflowId)
    : [];
  const workflowName = recent.find((event) => event && event.workflow)?.workflow || "workflow";
  const finalEvent = [...recent].reverse().find((event) => event && event.type === "workflow_finished");
  const cancelled = recent.some((event) => event && event.type === "workflow_cancelled");
  const timedOut = recent.some((event) => event && event.type === "workflow_stage_timeout");
  const live = recent.length > 0 && !finalEvent && !cancelled && !timedOut;
  const steps = [
    orchestrationStep("planner", "Planner", recent, (event) => event.role === "planner" || event.stage === "plan"),
    orchestrationStep("worker", "Worker", recent, (event) => event.stage === "work" || event.role === "coder" || event.role === "explainer"),
    orchestrationStep("reviewer", "Reviewer", recent, (event) => event.stage === "review" || event.role === "reviewer"),
    orchestrationStep("fixer", "Fixer", recent, (event) => String(event.stage || "").includes("retry")),
    {
      id: "final",
      label: "Final",
      status: finalEvent ? "done" : live ? "pending" : "ready",
      meta: finalEvent
        ? (finalEvent.final_status || "summarized")
        : live
          ? "waiting"
          : "ready"
    }
  ];
  if (!recent.length) {
    return {
      status: dashboard && dashboard.status === "Running" ? "Ready" : "Offline",
      detail: "planner > worker > reviewer > fixer > final",
      steps
    };
  }
  if (cancelled || timedOut) {
    for (const step of steps) {
      if (step.status === "active") {
        step.status = "blocked";
      }
    }
  }
  return {
    status: cancelled ? "Cancelled" : timedOut ? "Timed out" : finalEvent ? "Complete" : "Running",
    detail: `${workflowName} ${latestWorkflowId}`.trim(),
    steps
  };
}

function latestWorkflowIdFromEvents(events) {
  for (const event of [...events].reverse()) {
    if (event && event.workflow_id) {
      return event.workflow_id;
    }
  }
  return "";
}

function orchestrationStep(id, label, events, match) {
  const matching = events.filter((event) => event && match(event));
  const started = matching.some((event) => event.type === "workflow_stage_started");
  const finished = [...matching].reverse().find((event) => event.type === "workflow_stage_finished");
  const timeout = matching.some((event) => event.type === "workflow_stage_timeout");
  return {
    id,
    label,
    status: timeout ? "blocked" : finished ? "done" : started ? "active" : "ready",
    meta: finished
      ? [finished.provider || finished.agent || "", finished.model || ""].filter(Boolean).join(" / ") || "done"
      : started
        ? "running"
        : "ready"
  };
}

function sidebarToolRows(toolsBody) {
  const tools = toolsBody && Array.isArray(toolsBody.tools) ? toolsBody.tools : [];
  return tools.slice(0, 24).map((tool) => ({
    name: tool.name || "",
    readOnly: tool.read_only === true,
    permission: tool.permission || "",
    description: tool.description || ""
  }));
}

function sidebarTrustControls(config, permissions, tools) {
  const approvalMode = normalizeApprovalMode(config.approvalMode || "ask");
  const shellAllowed = !!config.allowShellTools;
  const rows = [
    {
      label: "Shell commands",
      state: shellAllowed
        ? (approvalMode === "auto" ? "allowed automatically" : "confirmation enabled")
        : "disabled",
      ok: shellAllowed && approvalMode !== "auto"
    },
    {
      label: "File deletes",
      state: approvalMode === "readonly" || approvalMode === "deny"
        ? "blocked"
        : approvalMode === "auto"
          ? "security-gated"
          : "confirmation enabled",
      ok: approvalMode !== "auto"
    },
    {
      label: "Diff preview",
      state: approvalMode === "auto" ? "high-risk edits only" : "shown before approval",
      ok: approvalMode !== "auto"
    },
    {
      label: "Tool list",
      state: `${tools.length || 0} available`,
      ok: tools.length > 0
    }
  ];
  const recent = permissions && Array.isArray(permissions.recent) ? permissions.recent : [];
  const denied = recent
    .filter((item) => item && item.denied)
    .map((item) => item.tool || item.category || item.type || "action")
    .slice(-4);
  const allowedTools = tools
    .filter((tool) => tool && tool.name)
    .map((tool) => tool.name)
    .slice(0, 8);
  const blockedTools = [
    ...(!shellAllowed ? ["run_command"] : []),
    ...denied
  ].filter(Boolean);
  return {
    approvalMode,
    shellAllowed,
    rows,
    allowedTools,
    blockedTools,
    presets: [
      { id: "safe", label: "Safe" },
      { id: "shellAsk", label: "Ask Shell" },
      { id: "readonly", label: "Read Only" },
      { id: "auto", label: "Auto" }
    ]
  };
}

async function sidebarWorkspaceProfile(config, health) {
  const workspace = workspaceRoot();
  const keyRows = await apiKeyStatusRows().catch(() => []);
  const providerSignals = keyRows.filter((row) => row.saved || row.envPresent);
  const mcp = detectMcpServers(config, workspace);
  const workspaceType = detectWorkspaceType(workspace);
  const providerCount = health && Array.isArray(health.agents) ? health.agents.length : 0;
  const suggestedDefault = suggestedWorkingDefault({
    providerSignals,
    providerCount,
    workspaceType,
    mcp
  });
  return {
    workspaceType,
    providerSignals: providerSignals.map((row) => row.label),
    providerSignalCount: providerSignals.length,
    mcp,
    suggestedDefault
  };
}

function detectWorkspaceType(workspace) {
  if (!workspace) {
    return { label: "No workspace", detail: "Open a folder" };
  }
  const checks = [
    { file: "pyproject.toml", label: "Python" },
    { file: "requirements.txt", label: "Python" },
    { file: "package.json", label: "Node" },
    { file: path.join("vscode-extension", "package.json"), label: "VS Code extension" },
    { file: "go.mod", label: "Go" },
    { file: "Cargo.toml", label: "Rust" },
    { file: "pom.xml", label: "Java" },
    { file: "Dockerfile", label: "Docker" }
  ];
  const labels = [];
  for (const check of checks) {
    if (fs.existsSync(path.join(workspace, check.file)) && !labels.includes(check.label)) {
      labels.push(check.label);
    }
  }
  if (!labels.length) {
    return { label: "Workspace", detail: path.basename(workspace) };
  }
  return {
    label: labels.slice(0, 3).join(" + "),
    detail: labels.length > 3 ? `${labels.length} project signals` : path.basename(workspace)
  };
}

function detectMcpServers(config, workspace) {
  const sources = [];
  const configPath = workspace ? resolveConfigPath(config.configPath, workspace) : "";
  if (configPath && fs.existsSync(configPath)) {
    const count = mcpServerCountFromJsonFile(configPath);
    if (count > 0) {
      sources.push({ source: "Agent Hub config", count });
    }
  }
  const workspaceFiles = workspace
    ? [
      ".mcp.json",
      path.join(".vscode", "mcp.json"),
      path.join(".cursor", "mcp.json")
    ]
    : [];
  for (const relative of workspaceFiles) {
    const filePath = path.join(workspace, relative);
    const count = mcpServerCountFromJsonFile(filePath);
    if (count > 0) {
      sources.push({ source: relative, count });
    }
  }
  const appData = process.env.APPDATA || "";
  const claudeConfig = appData ? path.join(appData, "Claude", "claude_desktop_config.json") : "";
  const claudeCount = mcpServerCountFromJsonFile(claudeConfig);
  if (claudeCount > 0) {
    sources.push({ source: "Claude Desktop", count: claudeCount });
  }
  const count = sources.reduce((total, row) => total + row.count, 0);
  return {
    count,
    sources,
    detail: sources.length
      ? sources.map((row) => `${row.source}: ${row.count}`).join(" / ")
      : "none detected"
  };
}

function mcpServerCountFromJsonFile(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return 0;
  }
  try {
    const data = parseJsonConfigText(fs.readFileSync(filePath, "utf8")).value;
    if (!data || typeof data !== "object") {
      return 0;
    }
    if (Array.isArray(data.mcp_servers)) {
      return data.mcp_servers.filter((server) => server && server.enabled !== false).length;
    }
    const servers = data.mcpServers || data.servers;
    if (servers && typeof servers === "object") {
      return Object.keys(servers).length;
    }
  } catch (_error) {
    return 0;
  }
  return 0;
}

function suggestedWorkingDefault({ providerSignals, providerCount, workspaceType, mcp }) {
  if (providerCount > 0) {
    return {
      label: "Use current routing",
      detail: `${providerCount} live provider route(s) are ready for ${workspaceType.label}.`
    };
  }
  if (providerSignals.length > 0) {
    return {
      label: "Cloud control",
      detail: `${providerSignals[0].label} is configured; start Agent Hub and use cloud mode.`
    };
  }
  if (mcp.count > 0) {
    return {
      label: "Local setup first",
      detail: `${mcp.count} MCP server(s) detected; add a model provider to activate them.`
    };
  }
  return {
    label: "Choose a local model",
    detail: "Start Ollama or LM Studio, then choose Local control."
  };
}

async function sidebarOnboardingState(config, health) {
  const workspace = workspaceRoot();
  const configPath = workspace ? resolveConfigPath(config.configPath, workspace) : "";
  const backendRoot = backendSourceRoot(workspace);
  const keys = await apiKeyStatusRows().catch(() => []);
  const savedKeys = keys.filter((row) => row.saved).length;
  const envKeys = keys.filter((row) => row.envPresent).length;
  const availableKeys = keys.filter((row) => row.saved || row.envPresent).length;
  const localStatus = await sidebarLocalServerStatus();
  const localModelsReady = localStatus.some((row) => row.ok);
  const python = await detectPythonForOnboarding(config, workspace);
  const node = await nodeRuntimeStatus();
  const npm = await npmRuntimeStatus();
  const codex = await codexCliStatus();
  const ollama = await ollamaDesktopStatus();
  const providers = health && Array.isArray(health.agents) ? health.agents.length : 0;
  const providerReady = providers > 0 || availableKeys > 0 || localModelsReady;
  const workspaceProfile = await sidebarWorkspaceProfile(config, health);
  const proof = personalBenchmarkReportStatus(config, workspace);
  return [
    {
      label: "Workspace",
      ok: !!workspace,
      detail: workspace ? `${workspaceProfile.workspaceType.label} - ${workspaceProfile.workspaceType.detail}` : "open a workspace folder",
      setupRequired: true
    },
    {
      label: "Backend",
      ok: !!backendRoot,
      detail: backendRoot ? `found at ${backendRoot}` : "backend package not found",
      setupRequired: true
    },
    {
      label: "Python",
      ok: python.ok,
      detail: python.detail,
      actionType: python.ok ? "" : "installPython",
      actionLabel: "Install",
      setupRequired: true
    },
    {
      label: "Config",
      ok: !!(configPath && fs.existsSync(configPath)),
      detail: configPath ? `using ${configPath}` : "open a workspace folder",
      setupRequired: true
    },
    {
      label: "Model provider",
      ok: providerReady,
      detail: providers > 0
        ? `${providers} ready`
        : availableKeys > 0
          ? `${savedKeys} saved key(s), ${envKeys} env key(s)`
          : "save a key or start a local model",
      actionType: providerReady ? "" : "installOllamaDesktop",
      actionLabel: "Install Ollama",
      setupRequired: true
    },
    {
      label: "Node.js",
      ok: node.ok,
      detail: node.detail,
      optional: true,
      actionType: node.ok ? "" : "installNode",
      actionLabel: "Install",
      setupRequired: false
    },
    {
      label: "npm",
      ok: npm.ok,
      detail: npm.detail,
      optional: true,
      actionType: npm.ok ? "" : "installNode",
      actionLabel: "Install Node",
      setupRequired: false
    },
    {
      label: "Codex CLI",
      ok: codex.installed,
      detail: codex.installed
        ? (codex.version || "installed")
        : "optional no-key routing helper",
      optional: true,
      actionType: codex.installed ? "" : "installCodexCli",
      actionLabel: "Install",
      setupRequired: false
    },
    {
      label: "Provider keys",
      ok: availableKeys > 0,
      detail: availableKeys > 0 ? `${availableKeys} detected` : "none detected",
      optional: true,
      setupRequired: false
    },
    {
      label: "MCP servers",
      ok: workspaceProfile.mcp.count > 0,
      detail: workspaceProfile.mcp.detail,
      optional: true,
      setupRequired: false
    },
    {
      label: "Working default",
      ok: providerReady,
      detail: `${workspaceProfile.suggestedDefault.label}: ${workspaceProfile.suggestedDefault.detail}`,
      optional: true,
      setupRequired: false
    },
    {
      label: "Personal proof",
      ok: proof.exists,
      detail: proof.exists
        ? `benchmark report ready: ${proof.updatedText}`
        : "run the shipped 50-task corpus locally",
      optional: true,
      actionType: proof.exists ? "" : "runPersonalBenchmark",
      actionLabel: "Run",
      setupRequired: false
    },
    {
      label: "Local models",
      ok: localModelsReady,
      detail: localStatus.map((row) => `${row.name}: ${row.ok ? "running" : "offline"}`).join(" / "),
      optional: true,
      actionType: localModelsReady || ollama.installed ? "" : "installOllamaDesktop",
      actionLabel: "Install Ollama",
      setupRequired: false
    },
    {
      label: "Start Agent Hub",
      ok: health && health.running === true,
      detail: health && health.running ? `running at ${config.serverUrl}` : "click Start Agent Hub",
      action: true,
      actionType: health && health.running ? "" : "startServer",
      actionLabel: "Start",
      setupRequired: false
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

function personalBenchmarkReportStatus(config, workspace) {
  const reportDir = personalBenchmarkReportDir(config, workspace);
  const jsonPath = reportDir ? path.join(reportDir, "benchmark-report.json") : "";
  const markdownPath = reportDir ? path.join(reportDir, "benchmark-report.md") : "";
  const exists = !!(jsonPath && fs.existsSync(jsonPath));
  let updatedText = "";
  if (exists) {
    try {
      updatedText = new Date(fs.statSync(jsonPath).mtimeMs).toLocaleString();
    } catch (_error) {
      updatedText = "latest report";
    }
  }
  return {
    exists,
    reportDir,
    jsonPath,
    markdownPath,
    updatedText: updatedText || "not run yet"
  };
}

function personalBenchmarkReportDir(config, workspace) {
  if (!workspace) {
    return "";
  }
  const raw = readResolvedAgentHubConfig(config);
  const workspaceDir = raw && typeof raw.workspace_dir === "string" && raw.workspace_dir.trim()
    ? raw.workspace_dir.trim()
    : workspace;
  const stateDir = raw && typeof raw.state_dir === "string" && raw.state_dir.trim()
    ? raw.state_dir.trim()
    : path.join(defaultExtensionWorkspaceStorageDir(workspace), "runtime", "state");
  const resolvedState = resolveRuntimeStatePath(stateDir, workspaceDir || workspace);
  return resolvedState ? path.join(resolvedState, "benchmark_reports") : "";
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
      --border: var(--vscode-sideBarSectionHeader-border, var(--vscode-panel-border, rgba(127, 127, 127, 0.22)));
      --subtle-border: color-mix(in srgb, var(--app-fg) 18%, transparent);
      --panel: color-mix(in srgb, var(--vscode-sideBarSectionHeader-background, var(--app-bg)) 88%, var(--app-fg) 12%);
      --panel-soft: color-mix(in srgb, var(--app-bg) 91%, var(--app-fg) 9%);
      --card: color-mix(in srgb, var(--vscode-input-background, var(--app-bg)) 82%, var(--app-fg) 18%);
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
      --cyan: #22d3ee;
      --violet: #8b5cf6;
      --rose: #fb7185;
      --amber: #f59e0b;
      --accent: color-mix(in srgb, var(--button) 78%, #2dd4bf 22%);
      --accent-soft: color-mix(in srgb, var(--accent) 18%, transparent);
      --ok-soft: color-mix(in srgb, var(--ok) 18%, transparent);
      --warn-soft: color-mix(in srgb, var(--warn) 18%, transparent);
      --error-soft: color-mix(in srgb, var(--error) 18%, transparent);
      --violet-soft: color-mix(in srgb, var(--violet) 16%, transparent);
      --cyan-soft: color-mix(in srgb, var(--cyan) 15%, transparent);
      --panel-line: color-mix(in srgb, var(--app-fg) 9%, transparent);
      --shadow: 0 12px 28px rgba(0, 0, 0, 0.26);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--app-fg);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--app-bg) 78%, #020617 22%) 0%, var(--app-bg) 45%),
        linear-gradient(135deg, var(--cyan-soft), transparent 42%),
        linear-gradient(215deg, var(--violet-soft), transparent 46%),
        var(--app-bg);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(color-mix(in srgb, var(--app-fg) 4%, transparent) 1px, transparent 1px),
        linear-gradient(90deg, color-mix(in srgb, var(--app-fg) 4%, transparent) 1px, transparent 1px);
      background-size: 22px 22px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.55), transparent 68%);
      opacity: 0.45;
    }

    .shell {
      min-width: 0;
      display: grid;
      gap: 10px;
      padding: 10px;
    }

    header,
    section,
    details.panel {
      position: relative;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel) 96%, var(--app-fg) 4%), color-mix(in srgb, var(--panel) 88%, transparent));
      box-shadow: var(--shadow);
    }

    details.panel {
      transition: border-color 140ms ease, background 140ms ease, box-shadow 140ms ease;
    }

    details.panel[open] {
      border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
      background: color-mix(in srgb, var(--panel) 96%, var(--accent) 4%);
    }

    header {
      display: flex;
      align-items: center;
      gap: 8px;
      position: sticky;
      top: 0;
      z-index: 5;
      backdrop-filter: blur(16px);
    }

    .topbar {
      border-color: color-mix(in srgb, var(--cyan) 24%, var(--border));
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--cyan) 10%, var(--panel)), color-mix(in srgb, var(--violet) 8%, var(--panel)));
      box-shadow:
        0 10px 26px rgba(0, 0, 0, 0.22),
        inset 0 1px 0 var(--panel-line);
    }

    .brand {
      min-width: 0;
      display: grid;
      gap: 1px;
      flex: 1 1 auto;
    }

    .brand-kicker {
      color: color-mix(in srgb, var(--cyan) 82%, var(--muted));
      font-size: 9px;
      line-height: 1.1;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .topbar-status {
      display: flex;
      align-items: center;
      gap: 5px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .topbar-chip {
      max-width: 108px;
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      padding: 2px 7px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.3;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      background: color-mix(in srgb, var(--card) 82%, transparent);
    }

    .topbar-chip[data-state="Running"] {
      color: var(--ok);
      border-color: color-mix(in srgb, var(--ok) 42%, var(--subtle-border));
      background: var(--ok-soft);
    }

    .topbar-chip[data-state="Starting"] {
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 42%, var(--subtle-border));
      background: var(--warn-soft);
    }

    .topbar-chip[data-state="Error"],
    .topbar-chip[data-state="Stopped"] {
      color: var(--error);
      border-color: color-mix(in srgb, var(--error) 42%, var(--subtle-border));
      background: var(--error-soft);
    }

    .hero {
      position: relative;
      display: grid;
      gap: 10px;
      overflow: hidden;
      border-color: color-mix(in srgb, var(--accent) 44%, var(--border));
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--accent) 20%, var(--panel)) 0%, color-mix(in srgb, var(--panel) 95%, #020617 5%) 48%, color-mix(in srgb, var(--violet) 12%, var(--panel)) 100%);
    }

    .hero::before {
      content: "";
      position: absolute;
      inset: 0;
      border-top: 1px solid color-mix(in srgb, var(--accent) 70%, transparent);
      pointer-events: none;
    }

    .hero > * {
      position: relative;
    }

    .hero-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
    }

    .hero-kicker {
      color: color-mix(in srgb, var(--cyan) 86%, var(--muted));
      font-size: 10px;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0;
      margin-bottom: 2px;
    }

    .hero h2 {
      font-size: 15px;
      line-height: 1.2;
    }

    .hero-copy {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      margin-top: 3px;
      overflow-wrap: anywhere;
    }

    .command-surface {
      display: grid;
      gap: 8px;
      border: 1px solid color-mix(in srgb, var(--accent) 26%, var(--subtle-border));
      border-radius: 8px;
      padding: 8px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--card) 90%, var(--accent) 10%), color-mix(in srgb, var(--card) 86%, transparent));
      box-shadow: inset 0 1px 0 var(--panel-line);
    }

    .health-card {
      position: relative;
      display: flex;
      align-items: baseline;
      justify-content: flex-end;
      gap: 5px;
      min-width: 0;
      color: var(--app-fg);
      border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--subtle-border));
      border-radius: 8px;
      padding: 6px 8px;
      background: var(--accent-soft);
    }

    .health-card::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }

    .health-card[data-state="Running"],
    .health-card[data-state="Ready"] {
      border-color: color-mix(in srgb, var(--ok) 42%, var(--subtle-border));
      background: var(--ok-soft);
    }

    .health-card[data-state="Running"]::before,
    .health-card[data-state="Ready"]::before {
      background: var(--ok);
      box-shadow: 0 0 0 3px var(--ok-soft);
    }

    .health-card[data-state="Starting"] {
      border-color: color-mix(in srgb, var(--warn) 42%, var(--subtle-border));
      background: var(--warn-soft);
    }

    .health-card[data-state="Starting"]::before {
      background: var(--warn);
      box-shadow: 0 0 0 3px var(--warn-soft);
    }

    .health-card[data-state="Error"],
    .health-card[data-state="Stopped"] {
      border-color: color-mix(in srgb, var(--error) 42%, var(--subtle-border));
      background: var(--error-soft);
    }

    .health-card[data-state="Error"]::before,
    .health-card[data-state="Stopped"]::before {
      background: var(--error);
      box-shadow: 0 0 0 3px var(--error-soft);
    }

    .health-label {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .health-value {
      font-size: 13px;
      font-weight: 700;
      line-height: 1.1;
    }

    .hero-state-strip {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      min-width: 0;
    }

    .state-pill {
      position: relative;
      display: inline-flex;
      flex-direction: column;
      gap: 2px;
      color: var(--app-fg);
      min-width: 0;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 7px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--card) 88%, var(--app-fg) 4%), color-mix(in srgb, var(--card) 74%, transparent));
      box-shadow: inset 0 1px 0 var(--panel-line);
    }

    .state-pill::before {
      content: "";
      position: absolute;
      inset: 7px 7px auto auto;
      width: 5px;
      height: 5px;
      border-radius: 999px;
      background: var(--accent);
      opacity: 0.72;
    }

    .state-pill:nth-child(2)::before {
      background: var(--violet);
    }

    .state-pill:nth-child(3)::before {
      background: var(--cyan);
    }

    .state-pill:nth-child(4)::before {
      background: var(--amber);
    }

    .state-pill span {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .state-pill strong {
      font-size: 12px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }

    .hero-card {
      display: grid;
      gap: 6px;
      color: var(--app-fg);
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 9px;
      background: color-mix(in srgb, var(--card) 84%, transparent);
    }

    .hero-card-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-weight: 600;
    }

    .model-control-plane {
      display: grid;
      gap: 10px;
      border-color: color-mix(in srgb, var(--button) 38%, var(--border));
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--button) 10%, var(--panel)) 0%, color-mix(in srgb, var(--panel) 94%, #020617 6%) 44%, color-mix(in srgb, var(--violet) 10%, var(--panel)) 100%);
      box-shadow:
        0 14px 32px rgba(0, 0, 0, 0.30),
        inset 0 1px 0 var(--panel-line);
    }

    .inline-toggle {
      width: auto;
      min-height: 24px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 11px;
      line-height: 1.2;
      white-space: nowrap;
    }

    .inline-toggle[data-state="on"] {
      color: var(--button-fg);
      border-color: color-mix(in srgb, var(--ok) 60%, var(--subtle-border));
      background: color-mix(in srgb, var(--ok) 62%, var(--button) 38%);
    }

    .control-plane-status {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 8px;
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--cyan) 10%, var(--card)), color-mix(in srgb, var(--card) 88%, transparent));
      box-shadow: inset 0 1px 0 var(--panel-line);
    }

    .control-plane-status strong,
    .control-plane-status span {
      display: block;
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .control-plane-status strong {
      font-size: 13px;
      line-height: 1.25;
    }

    .control-plane-status span {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.3;
      margin-top: 2px;
    }

    .control-plane-status .status {
      justify-self: end;
    }

    .signal-tile-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(86px, 1fr));
      gap: 7px;
    }

    .signal-tile {
      min-width: 0;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 8px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--card) 92%, var(--app-fg) 4%), color-mix(in srgb, var(--card) 80%, transparent));
      box-shadow: inset 0 1px 0 color-mix(in srgb, var(--app-fg) 8%, transparent);
    }

    .signal-tile:nth-child(2) {
      border-color: color-mix(in srgb, var(--violet) 38%, var(--subtle-border));
    }

    .signal-tile:nth-child(3) {
      border-color: color-mix(in srgb, var(--cyan) 40%, var(--subtle-border));
    }

    .signal-tile:nth-child(4) {
      border-color: color-mix(in srgb, var(--rose) 34%, var(--subtle-border));
    }

    .signal-tile:nth-child(5) {
      border-color: color-mix(in srgb, var(--amber) 38%, var(--subtle-border));
    }

    .signal-tile[data-tone="ok"] {
      border-color: color-mix(in srgb, var(--ok) 42%, var(--subtle-border));
      background: color-mix(in srgb, var(--ok) 10%, var(--card));
    }

    .signal-tile[data-tone="warn"] {
      border-color: color-mix(in srgb, var(--warn) 42%, var(--subtle-border));
      background: color-mix(in srgb, var(--warn) 10%, var(--card));
    }

    .signal-tile[data-tone="error"] {
      border-color: color-mix(in srgb, var(--error) 42%, var(--subtle-border));
      background: color-mix(in srgb, var(--error) 10%, var(--card));
    }

    .signal-tile[data-tone="info"] {
      border-color: color-mix(in srgb, #38bdf8 42%, var(--subtle-border));
      background: color-mix(in srgb, #38bdf8 10%, var(--card));
    }

    .signal-tile span,
    .signal-tile strong,
    .signal-tile small {
      display: block;
      overflow-wrap: anywhere;
    }

    .signal-tile span {
      color: var(--muted);
      font-size: 9px;
      line-height: 1.25;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .signal-tile strong {
      color: var(--app-fg);
      font-size: 16px;
      line-height: 1.15;
      margin-top: 3px;
    }

    .signal-tile small {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.25;
      margin-top: 3px;
    }

    .model-board-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
      gap: 8px;
    }

    .model-board-grid.compact {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .model-panel {
      min-width: 0;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 9px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--card) 90%, var(--panel) 10%), color-mix(in srgb, var(--card) 78%, transparent));
      box-shadow: inset 0 1px 0 var(--panel-line);
    }

    .model-panel h3 {
      margin: 0 0 7px;
      color: var(--app-fg);
      font-size: 12px;
      font-weight: 600;
      line-height: 1.25;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .model-panel h3::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }

    .model-signal-list,
    .model-router-list,
    .mini-flow-list {
      display: grid;
      gap: 6px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .model-signal-row,
    .model-router-row,
    .mini-flow-row {
      display: grid;
      gap: 2px;
      min-width: 0;
      border: 1px solid color-mix(in srgb, var(--subtle-border) 72%, transparent);
      border-radius: 7px;
      padding: 7px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-soft) 86%, var(--app-fg) 3%), color-mix(in srgb, var(--panel-soft) 68%, transparent));
      box-shadow: inset 0 1px 0 color-mix(in srgb, var(--app-fg) 6%, transparent);
      transition: border-color 120ms ease, transform 120ms ease;
    }

    .model-signal-row:hover,
    .model-router-row:hover,
    .mini-flow-row:hover {
      border-color: color-mix(in srgb, var(--accent) 36%, var(--subtle-border));
      transform: translateY(-1px);
    }

    .model-router-row {
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      column-gap: 7px;
    }

    .rank-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 22px;
      height: 22px;
      border: 1px solid color-mix(in srgb, var(--button) 45%, var(--subtle-border));
      border-radius: 999px;
      color: var(--app-fg);
      font-size: 10px;
      background: color-mix(in srgb, var(--button) 18%, var(--card));
    }

    .model-router-main,
    .mini-flow-main {
      min-width: 0;
      color: var(--app-fg);
      font-size: 11px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }

    .model-router-meta,
    .mini-flow-meta,
    .model-signal-row span {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }

    .router-score {
      color: var(--ok);
      font-size: 10px;
      line-height: 1.2;
      text-align: right;
      white-space: nowrap;
    }

    .mini-flow-row {
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      column-gap: 8px;
    }

    .mini-flow-value {
      color: var(--app-fg);
      font-weight: 700;
      white-space: nowrap;
    }

    .mini-flow-row[data-tone="ok"] {
      border-color: color-mix(in srgb, var(--ok) 36%, var(--subtle-border));
      background: color-mix(in srgb, var(--ok) 9%, var(--panel-soft));
    }

    .mini-flow-row[data-tone="warn"] {
      border-color: color-mix(in srgb, var(--warn) 38%, var(--subtle-border));
      background: color-mix(in srgb, var(--warn) 9%, var(--panel-soft));
    }

    .mini-flow-row[data-tone="error"] {
      border-color: color-mix(in srgb, var(--error) 38%, var(--subtle-border));
      background: color-mix(in srgb, var(--error) 9%, var(--panel-soft));
    }

    .incident-stream {
      min-height: 100%;
    }

    .progress-track {
      height: 6px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--progress-bg);
      opacity: 0.9;
    }

    .progress-fill {
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--ok));
      transition: width 160ms ease-out;
    }

    .next-step {
      display: grid;
      gap: 2px;
      padding-left: 0;
    }

    .stat-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }

    .stat-grid + .list {
      margin-top: 10px;
    }

    .routing-summary-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }

    .routing-summary-item {
      min-width: 0;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 8px;
      background: color-mix(in srgb, var(--card) 88%, transparent);
      box-shadow: inset 0 1px 0 color-mix(in srgb, var(--app-fg) 9%, transparent);
    }

    .routing-summary-item span,
    .routing-summary-item strong {
      display: block;
      overflow-wrap: anywhere;
    }

    .routing-summary-item span {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.25;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .routing-summary-item strong {
      color: var(--app-fg);
      font-size: 12px;
      line-height: 1.3;
    }

    .flow-strip {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 5px;
      margin-bottom: 8px;
    }

    .flow-step {
      min-width: 0;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 7px 5px;
      text-align: center;
      background: color-mix(in srgb, var(--card) 85%, transparent);
    }

    .flow-step strong,
    .flow-step span {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .flow-step strong {
      font-size: 11px;
      line-height: 1.25;
    }

    .flow-step span {
      color: var(--muted);
      font-size: 9px;
      line-height: 1.2;
      margin-top: 2px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .flow-step[data-status="active"] {
      border-color: var(--button);
      background: color-mix(in srgb, var(--accent) 16%, var(--card));
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--button) 30%, transparent);
    }

    .flow-step[data-status="done"] span {
      color: var(--ok);
    }

    .flow-step[data-status="blocked"] span {
      color: var(--error);
    }

    .template-grid,
    .trust-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      margin-top: 8px;
    }

    .template-button {
      min-height: 44px;
    }

    .killer-button {
      margin-top: 6px;
      min-height: 38px;
    }

    .trust-row {
      min-width: 0;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 8px;
      background: color-mix(in srgb, var(--card) 86%, transparent);
    }

    .trust-row strong,
    .trust-row span {
      display: block;
      overflow-wrap: anywhere;
    }

    .trust-row strong {
      font-size: 11px;
      line-height: 1.25;
    }

    .trust-row span {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.25;
      margin-top: 2px;
    }

    .trust-row[data-ok="true"] span {
      color: var(--ok);
    }

    .trust-row[data-ok="true"] {
      border-color: color-mix(in srgb, var(--ok) 42%, var(--subtle-border));
      background: color-mix(in srgb, var(--ok) 10%, var(--card));
    }

    .tool-chip-list {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 8px;
    }

    .tool-chip {
      max-width: 100%;
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      padding: 3px 8px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.4;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      background: color-mix(in srgb, var(--card) 72%, transparent);
    }

    .tool-chip[data-kind="blocked"] {
      color: var(--error);
    }

    .help-menu {
      margin-top: 10px;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 8px;
      background: color-mix(in srgb, var(--card) 86%, transparent);
    }

    .help-menu > summary {
      cursor: pointer;
      color: var(--app-fg);
      font-weight: 600;
      list-style-position: inside;
    }

    .help-content {
      display: grid;
      gap: 10px;
      margin-top: 8px;
    }

    .help-block {
      display: grid;
      gap: 5px;
    }

    .help-block h3 {
      margin: 0;
      color: var(--app-fg);
      font-size: 12px;
      font-weight: 600;
    }

    .help-list {
      display: grid;
      gap: 5px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .help-list li {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .help-list strong {
      color: var(--app-fg);
      font-weight: 600;
    }

    .stat-card {
      display: grid;
      gap: 4px;
      min-width: 0;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 10px;
      color: var(--app-fg);
      background: color-mix(in srgb, var(--card) 82%, transparent);
      box-shadow: inset 0 1px 0 color-mix(in srgb, var(--app-fg) 8%, transparent);
    }

    .stat-card.featured {
      grid-column: 1 / -1;
      padding: 12px;
      border-color: color-mix(in srgb, var(--accent) 44%, var(--subtle-border));
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--accent) 17%, var(--card)), color-mix(in srgb, var(--ok) 12%, var(--card)));
    }

    .stat-card[data-tone="ok"] {
      border-color: color-mix(in srgb, var(--ok) 34%, var(--subtle-border));
      background: color-mix(in srgb, var(--ok) 8%, var(--card));
    }

    .stat-card[data-tone="warn"] {
      border-color: color-mix(in srgb, var(--warn) 34%, var(--subtle-border));
      background: color-mix(in srgb, var(--warn) 8%, var(--card));
    }

    .stat-card[data-tone="error"] {
      border-color: color-mix(in srgb, var(--error) 34%, var(--subtle-border));
      background: color-mix(in srgb, var(--error) 8%, var(--card));
    }

    .stat-value {
      font-size: 19px;
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
      height: 6px;
      overflow: hidden;
      border-radius: 999px;
      background: var(--progress-bg);
    }

    .mini-meter-fill {
      height: 100%;
      width: 0%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--ok));
      transition: width 160ms ease-out;
    }

    .mini-meter-fill[data-tone="warn"] {
      background: var(--warn);
    }

    .mini-meter-fill[data-tone="error"] {
      background: var(--error);
    }

    .insight-row {
      border-left: 3px solid var(--accent);
      padding-left: 9px;
      background: color-mix(in srgb, var(--accent) 7%, var(--card));
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
      width: 22px;
      height: 22px;
      border-radius: 5px;
      flex: 0 0 auto;
      box-shadow: 0 0 0 1px var(--subtle-border);
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
      line-height: 1.2;
    }

    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }

    .section-head h2 {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }

    .section-head h2::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--cyan), var(--violet));
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--cyan) 13%, transparent);
      flex: 0 0 auto;
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
      content: "";
      width: 18px;
      height: 18px;
      color: var(--muted);
      text-align: right;
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      background:
        linear-gradient(var(--muted), var(--muted)) center / 8px 1px no-repeat,
        linear-gradient(90deg, var(--muted), var(--muted)) center / 1px 8px no-repeat,
        color-mix(in srgb, var(--card) 70%, transparent);
      flex: 0 0 auto;
    }

    details.panel[open] > summary.section-head::after {
      background:
        linear-gradient(var(--muted), var(--muted)) center / 8px 1px no-repeat,
        color-mix(in srgb, var(--card) 70%, transparent);
    }

    .status {
      position: relative;
      display: inline-flex;
      align-items: center;
      min-width: auto;
      justify-content: center;
      gap: 5px;
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      color: var(--muted);
      background: color-mix(in srgb, var(--card) 72%, transparent);
    }

    .status::before {
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 999px;
      background: currentColor;
      opacity: 0.82;
    }

    .status[data-state="Running"] {
      color: var(--ok);
      border-color: color-mix(in srgb, var(--ok) 42%, var(--subtle-border));
      background: var(--ok-soft);
    }

    .status[data-state="Ready"] {
      color: var(--ok);
    }

    .status[data-state="Starting"] {
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 44%, var(--subtle-border));
      background: var(--warn-soft);
    }

    .status[data-state="Error"] {
      color: var(--error);
      border-color: color-mix(in srgb, var(--error) 44%, var(--subtle-border));
      background: var(--error-soft);
    }

    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      margin-top: 8px;
    }

    .quick-actions {
      margin-top: 0;
    }

    .quick-actions button {
      min-height: 32px;
    }

    button {
      width: 100%;
      min-height: 30px;
      border: 1px solid var(--subtle-border);
      border-radius: 6px;
      padding: 6px 8px;
      color: var(--secondary-fg);
      background: var(--secondary);
      font: inherit;
      cursor: pointer;
      text-align: center;
      transition: background 120ms ease, border-color 120ms ease, transform 120ms ease, box-shadow 120ms ease;
    }

    .command-button {
      position: relative;
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 1px;
      align-content: center;
      text-align: left;
      min-height: 42px;
      border-radius: 8px;
      padding: 8px 9px 8px 8px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--secondary) 82%, var(--cyan) 8%), color-mix(in srgb, var(--secondary) 78%, var(--card)));
      box-shadow: inset 0 1px 0 color-mix(in srgb, var(--app-fg) 8%, transparent);
    }

    .command-button:hover {
      box-shadow:
        inset 0 1px 0 color-mix(in srgb, var(--app-fg) 10%, transparent),
        0 8px 18px color-mix(in srgb, var(--accent) 14%, transparent);
    }

    .command-button::before {
      content: attr(data-icon);
      grid-row: 1 / span 2;
      align-self: center;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 23px;
      height: 23px;
      margin-right: 2px;
      border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--subtle-border));
      border-radius: 999px;
      color: color-mix(in srgb, var(--cyan) 84%, var(--app-fg));
      font-size: 10px;
      font-weight: 700;
      background: color-mix(in srgb, var(--accent) 12%, var(--card));
    }

    .command-button::after {
      content: "";
      position: absolute;
      inset: auto 8px 5px 38px;
      height: 2px;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), transparent);
      opacity: 0.72;
    }

    .button-main,
    .button-meta {
      display: block;
      grid-column: 2;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .button-main {
      color: inherit;
      font-weight: 600;
      font-size: 12px;
    }

    .button-meta {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.25;
    }

    button:hover {
      background: var(--secondary-hover);
      border-color: color-mix(in srgb, var(--accent) 42%, var(--subtle-border));
      transform: translateY(-1px);
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
      transform: none;
    }

    button.primary:disabled:hover {
      background: var(--button);
    }

    .hero-server-action {
      min-height: 54px;
      border-radius: 8px;
      padding: 12px 14px;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
      box-shadow:
        0 10px 22px color-mix(in srgb, var(--button) 26%, transparent),
        inset 0 1px 0 color-mix(in srgb, #ffffff 18%, transparent);
    }

    .hero-server-action:hover {
      box-shadow:
        0 12px 26px color-mix(in srgb, var(--button) 30%, transparent),
        inset 0 1px 0 color-mix(in srgb, #ffffff 20%, transparent);
    }

    .hero-server-action[data-state="Running"] {
      color: #ffffff;
      background: var(--ok);
      background: linear-gradient(135deg, var(--ok), color-mix(in srgb, var(--ok) 70%, var(--accent)));
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--ok) 40%, transparent);
    }

    .hero-server-action[data-state="Running"]:hover {
      background: color-mix(in srgb, var(--ok) 86%, #000000 14%);
    }

    .hero-server-action[data-action="stopServer"] {
      color: #ffffff;
      background: var(--error);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--error) 40%, transparent);
    }

    .hero-server-action[data-action="stopServer"]:hover {
      background: color-mix(in srgb, var(--error) 86%, #000000 14%);
    }

    .hero-server-action[data-state="Starting"] {
      color: #ffffff;
      background: var(--warn);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--warn) 40%, transparent);
    }

    .hero-server-action[data-state="Error"] {
      color: #ffffff;
      background: var(--error);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--error) 40%, transparent);
    }

    .quick-task {
      display: grid;
      gap: 6px;
      background: transparent;
    }

    .quick-task label,
    .task-options label {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.3;
    }

    .quick-task textarea {
      width: 100%;
      min-height: 56px;
      max-height: 120px;
      resize: vertical;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 8px;
      color: var(--app-fg);
      background: color-mix(in srgb, var(--card) 92%, transparent);
      font: inherit;
      line-height: 1.35;
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

    .task-submit-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
    }

    .task-submit-row button {
      width: auto;
      white-space: nowrap;
    }

    button.primary {
      border-color: transparent;
      color: var(--button-fg);
      background: linear-gradient(135deg, var(--button), var(--accent));
      font-weight: 600;
    }

    button.primary:hover {
      background: var(--button-hover);
    }

    .hero-server-action[data-state="Starting"]:disabled:hover {
      background: var(--warn);
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
      position: relative;
      display: grid;
      gap: 2px;
      padding: 8px 9px;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      background: color-mix(in srgb, var(--card) 86%, transparent);
      box-shadow: inset 0 1px 0 color-mix(in srgb, var(--app-fg) 7%, transparent);
      transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
    }

    .row::before {
      content: "";
      position: absolute;
      inset: 9px auto auto 0;
      width: 3px;
      height: calc(100% - 18px);
      min-height: 14px;
      border-radius: 0 999px 999px 0;
      background: var(--accent);
      opacity: 0.78;
    }

    .row:hover {
      border-color: color-mix(in srgb, var(--accent) 34%, var(--subtle-border));
      background: color-mix(in srgb, var(--card) 91%, var(--accent) 9%);
      transform: translateY(-1px);
    }

    .row[data-tone="ok"] {
      border-color: color-mix(in srgb, var(--ok) 34%, var(--subtle-border));
      background: color-mix(in srgb, var(--ok) 9%, var(--card));
    }

    .row[data-tone="ok"]::before {
      background: var(--ok);
    }

    .row[data-tone="warn"] {
      border-color: color-mix(in srgb, var(--warn) 38%, var(--subtle-border));
      background: color-mix(in srgb, var(--warn) 9%, var(--card));
    }

    .row[data-tone="warn"]::before {
      background: var(--warn);
    }

    .row[data-tone="error"] {
      border-color: color-mix(in srgb, var(--error) 38%, var(--subtle-border));
      background: color-mix(in srgb, var(--error) 9%, var(--card));
    }

    .row[data-tone="error"]::before {
      background: var(--error);
    }

    .row-head {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      padding-left: 4px;
    }

    .row-badge {
      flex: 0 0 auto;
      max-width: 82px;
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      padding: 1px 6px;
      color: var(--muted);
      font-size: 9px;
      line-height: 1.45;
      text-transform: uppercase;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      background: color-mix(in srgb, var(--card) 76%, transparent);
    }

    .row[data-tone="ok"] .row-badge {
      color: var(--ok);
      border-color: color-mix(in srgb, var(--ok) 42%, var(--subtle-border));
      background: var(--ok-soft);
    }

    .row[data-tone="warn"] .row-badge {
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 42%, var(--subtle-border));
      background: var(--warn-soft);
    }

    .row[data-tone="error"] .row-badge {
      color: var(--error);
      border-color: color-mix(in srgb, var(--error) 42%, var(--subtle-border));
      background: var(--error-soft);
    }

    .main {
      color: var(--app-fg);
      overflow-wrap: anywhere;
    }

    .row .meta {
      padding-left: 4px;
    }

    .row-action {
      justify-self: start;
      margin: 4px 0 0 4px;
      padding: 4px 8px;
      min-height: 24px;
      border-radius: 6px;
      font-size: 11px;
      line-height: 1.2;
    }

    .empty {
      color: var(--muted);
      font-size: 12px;
      border: 1px dashed var(--subtle-border);
      border-radius: 8px;
      padding: 9px;
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--card) 72%, var(--cyan) 6%), color-mix(in srgb, var(--card) 58%, transparent));
    }

    @media (max-width: 280px) {
      .shell {
        padding: 6px;
      }

      header,
      section,
      details.panel {
        padding: 8px;
      }

      .hero-head,
      .task-submit-row,
      .actions,
      .routing-summary-grid,
      .template-grid,
      .trust-grid,
      .hero-state-strip,
      .control-plane-status,
      .model-board-grid,
      .model-board-grid.compact {
        grid-template-columns: 1fr;
      }

      .health-card {
        justify-content: flex-start;
      }

      .flow-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <img src="${logoSrc}" alt="">
      <div class="brand">
        <div class="brand-kicker">Mission Control</div>
        <h1>Agent Hub</h1>
        <div class="meta" id="extensionVersion">VS Code extension</div>
      </div>
      <div class="topbar-status">
        <span class="topbar-chip" id="headerStatus" data-state="Stopped">Offline</span>
        <span class="topbar-chip" id="headerRoute">cloud</span>
      </div>
    </header>
    <section class="hero">
      <div class="hero-head">
        <div>
          <div class="hero-kicker">Gateway Control Plane</div>
          <h2>Command Center</h2>
          <div class="hero-copy" id="heroSummary">Checking status</div>
        </div>
        <div class="health-card" id="heroHealthCard" data-state="Stopped" title="Health score is a 0-100 summary of provider availability, success rate, fallbacks, permissions, context pressure, stream failures, and degraded providers. Open Statistics > Help for details.">
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
        <div class="state-pill">
          <span>Readiness</span>
          <strong id="heroReadiness">--</strong>
        </div>
      </div>
      <button class="primary hero-server-action" id="heroServerAction" type="button" data-primary-action="start-server" data-state="Stopped">Start</button>
      <div class="command-surface">
        <form class="quick-task" id="quickTaskForm">
          <label for="quickTaskInput">Task</label>
          <textarea id="quickTaskInput" placeholder="Describe the change, investigation, or review"></textarea>
          <div class="task-submit-row">
            <div class="task-options">
              <label><input id="quickTaskIncludeSelection" type="checkbox" checked> Include selection</label>
            </div>
            <button class="primary" id="quickTaskSend" type="submit">Send</button>
          </div>
        </form>
      </div>
      <div class="actions quick-actions">
        <button class="command-button" id="openChat" type="button" title="Open Agent Hub chat" data-icon="C">
          <span class="button-main">Chat</span>
          <span class="button-meta">Open chat</span>
        </button>
        <button class="command-button" id="quickDashboard" type="button" title="Open the Agent Hub dashboard in your browser" data-icon="D">
          <span class="button-main">Dashboard</span>
          <span class="button-meta">Browser</span>
        </button>
        <button class="command-button" id="quickKernel" type="button" title="Open the runtime kernel control plane" data-icon="K">
          <span class="button-main">Kernel</span>
          <span class="button-meta">Runtime</span>
        </button>
        <button class="command-button" id="quickCheckup" type="button" title="Repair config, check requirements, start Agent Hub, and open Route Lab" data-icon="V">
          <span class="button-main">Checkup</span>
          <span class="button-meta">One click</span>
        </button>
        <button class="command-button" id="quickRouteLab" type="button" title="Score current route candidates without calling a provider" data-icon="R">
          <span class="button-main">Route Lab</span>
          <span class="button-meta">Why model?</span>
        </button>
        <button class="command-button" id="quickSettings" type="button" title="Open Agent Hub settings" data-icon="S">
          <span class="button-main">Settings</span>
          <span class="button-meta">Models</span>
        </button>
        <button class="command-button" id="quickTokenSafeMode" type="button" title="Enable Token Safe Mode" data-icon="T">
          <span class="button-main">Token Safe</span>
          <span class="button-meta">Save context</span>
        </button>
        <button class="command-button" id="quickFreeOnlyMode" type="button" title="Disable Codex CLI and non-free models" data-icon="F">
          <span class="button-main">Free Only</span>
          <span class="button-meta">No paid models</span>
        </button>
        <button class="command-button" id="quickCodexCliMode" type="button" title="Use Codex CLI without an API key" data-icon="X">
          <span class="button-main">Codex CLI</span>
          <span class="button-meta">No API key</span>
        </button>
        <button class="command-button" id="quickInstallCodexCli" type="button" title="Install or sign in to Codex CLI" data-icon="I">
          <span class="button-main">Install CLI</span>
          <span class="button-meta">Codex setup</span>
        </button>
        <button class="command-button" id="codeAgent" type="button" title="Run the coding agent" data-icon="A">
          <span class="button-main">Code</span>
          <span class="button-meta">Edit files</span>
        </button>
        <button class="command-button" id="explainFile" type="button" title="Explain the current file" data-icon="E">
          <span class="button-main">Explain</span>
          <span class="button-meta">This file</span>
        </button>
      </div>
    </section>
    <section class="model-control-plane">
      <div class="section-head">
        <h2>Model Stats</h2>
        <button class="inline-toggle" id="autoFeedbackToggle" type="button" data-state="off" title="Use a separate judge model to submit adaptive feedback after successful chat responses.">Auto Feedback Off</button>
      </div>
      <div class="control-plane-status">
        <div>
          <strong id="modelGatewayTitle">Gateway offline</strong>
          <span id="modelGatewayDetail">Start Agent Hub to collect model signals.</span>
        </div>
        <span class="status" id="modelGatewayStatus" data-state="Stopped">Offline</span>
      </div>
      <div class="signal-tile-grid" id="modelSignalGrid"></div>
      <div class="model-board-grid">
        <div class="model-panel">
          <h3>Gateway Health + Golden Signals</h3>
          <ul class="model-signal-list" id="goldenSignalList"></ul>
        </div>
        <div class="model-panel">
          <h3>Session Router</h3>
          <ul class="model-router-list" id="modelRouterList"></ul>
        </div>
      </div>
      <div class="model-board-grid compact">
        <div class="model-panel">
          <h3>Task Flow</h3>
          <ul class="mini-flow-list" id="modelTaskFlowList"></ul>
        </div>
        <div class="model-panel incident-stream">
          <h3>Security + Audit</h3>
          <ul class="mini-flow-list" id="modelAuditList"></ul>
        </div>
      </div>
      <div class="model-panel incident-stream">
        <h3>Incident Stream</h3>
        <ul class="mini-flow-list" id="modelIncidentList"></ul>
      </div>
    </section>
    <section class="model-control-plane runtime-kernel-panel">
      <div class="section-head">
        <h2>Runtime Kernel</h2>
        <span class="status" id="kernelStatus" data-state="Stopped">Offline</span>
      </div>
      <div class="control-plane-status">
        <div>
          <strong id="kernelTitle">Kernel offline</strong>
          <span id="kernelDetail">Start Agent Hub to inspect runtime pressure and subsystem state.</span>
        </div>
        <button id="openRuntimeKernel" type="button">Open Kernel</button>
      </div>
      <div class="signal-tile-grid" id="kernelSignalGrid"></div>
      <div class="model-board-grid compact">
        <div class="model-panel">
          <h3>Recommended Actions</h3>
          <ul class="mini-flow-list" id="kernelActionList"></ul>
        </div>
        <div class="model-panel">
          <h3>Pressure Signals</h3>
          <ul class="mini-flow-list" id="kernelPressureList"></ul>
        </div>
      </div>
      <div class="model-board-grid compact">
        <div class="model-panel">
          <h3>Subsystems</h3>
          <ul class="mini-flow-list" id="kernelSubsystemList"></ul>
        </div>
        <div class="model-panel incident-stream">
          <h3>Kernel Timeline</h3>
          <ul class="mini-flow-list" id="kernelTimelineList"></ul>
        </div>
      </div>
    </section>
    <section>
      <div class="section-head">
        <h2>Orchestration</h2>
        <span class="status" id="flowStatus">Ready</span>
      </div>
      <div class="flow-strip" id="flowStrip"></div>
      <div class="detail" id="flowDetail">planner &gt; worker &gt; reviewer &gt; fixer &gt; final</div>
      <div class="template-grid" id="workflowTemplateList"></div>
      <button class="primary killer-button" id="killerWorkflow" type="button">Issue to PR</button>
    </section>
    <details class="panel">
      <summary class="section-head">
        <h2>Health</h2>
        <span class="status" id="statsHealth">Waiting</span>
      </summary>
      <div class="stat-grid" id="statsGrid"></div>
      <ul class="list" id="insightList"></ul>
      <details class="help-menu">
        <summary>What do these numbers mean?</summary>
        <div class="help-content">
          <div class="help-block">
            <h3>Health</h3>
            <ul class="help-list">
              <li><strong>Health score</strong>: a 0-100 quick read. Higher means providers are available and recent requests look stable.</li>
              <li><strong>Healthy</strong>: ready to use. <strong>Degraded</strong>: usable, but recent failures or weak providers were seen. <strong>Needs attention</strong>: no model provider is ready. <strong>Offline</strong>: start Agent Hub first.</li>
              <li><strong>Why it changes</strong>: failed providers, fallback attempts, denied permissions, stream failures, or very large prompts can lower the score.</li>
            </ul>
          </div>
          <div class="help-block">
            <h3>Statistics</h3>
            <ul class="help-list">
              <li><strong>Providers available</strong>: model providers Agent Hub can use right now.</li>
              <li><strong>Success rate</strong>: how often provider calls have worked recently.</li>
              <li><strong>Tokens</strong>: prompt and response size reported by providers.</li>
              <li><strong>Workspace tool runs</strong>: file, shell, and workspace actions Agent Hub used.</li>
              <li><strong>Routing fallbacks</strong>: times Agent Hub tried another provider after the first one could not answer.</li>
              <li><strong>Best model/workflow</strong>: what Agent Hub has learned works best from recent samples. It may show "learning" until enough tasks run.</li>
              <li><strong>Permission events</strong>: actions that were allowed, denied, or needed approval.</li>
              <li><strong>Latest context tokens</strong>: how much workspace context was sent with the most recent request.</li>
            </ul>
          </div>
        </div>
      </details>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Setup</h2>
        <span class="status" id="serverStatus">Stopped</span>
      </summary>
      <div class="hero-card">
        <div class="hero-card-title">
          <span>Setup</span>
          <span class="status" id="setupProgressText">0%</span>
        </div>
        <div class="progress-track" aria-hidden="true"><div class="progress-fill" id="setupProgressFill"></div></div>
        <div class="next-step">
          <div class="main" id="nextStepTitle">Checking setup...</div>
          <div class="meta" id="nextStepDetail">Agent Hub is collecting local status.</div>
        </div>
      </div>
      <div class="detail" id="serverDetail">Checking Agent Hub...</div>
      <ul class="list" id="onboardingList"></ul>
      <div class="actions">
        <button id="stopServer" type="button">Stop</button>
        <button id="restartServer" type="button">Restart</button>
        <button id="runCheckup" type="button">Run Checkup</button>
        <button id="checkRequirements" type="button">Check Requirements</button>
        <button id="fixSafeConfig" type="button">Repair Config</button>
        <button id="checkHealth" type="button">Check Status</button>
      </div>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Permissions</h2>
      </summary>
      <div class="detail" id="permissionDetail">Approval: ask</div>
      <div class="trust-grid" id="trustControlGrid"></div>
      <div class="actions">
        <button class="trust-preset" data-preset="safe" type="button">Safe</button>
        <button class="trust-preset" data-preset="shellAsk" type="button">Ask Shell</button>
        <button class="trust-preset" data-preset="readonly" type="button">Read Only</button>
        <button class="trust-preset" data-preset="auto" type="button">Auto</button>
      </div>
      <div class="tool-chip-list" id="toolControlList"></div>
      <ul class="list" id="permissionList"></ul>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Models</h2>
      </summary>
      <div class="detail" id="activeModel">No active model yet</div>
      <ul class="list" id="routingChain"></ul>
      <ul class="list" id="providerList"></ul>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Routing Intelligence</h2>
      </summary>
      <div class="routing-summary-grid" id="routingSummaryGrid"></div>
      <div class="detail" id="routingExplanation">No routing decision yet</div>
      <ul class="list" id="routingReasonList"></ul>
      <ul class="list" id="routingRejectedList"></ul>
      <div class="actions">
        <button id="openRouteLab" type="button">Open Route Lab</button>
        <button id="explainRoute" type="button">Plain Text Explain</button>
        <button id="openRoutingDashboard" type="button">Dashboard</button>
      </div>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Limits</h2>
      </summary>
      <ul class="list" id="limitList"></ul>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Tokens</h2>
      </summary>
      <div class="detail" id="tokenUsage">No token usage yet</div>
      <div class="detail" id="contextDiagnostics"></div>
      <div class="actions">
        <button id="freeOnlyMode" type="button">Free Only Mode</button>
        <button id="tokenSafeMode" type="button">Token Safe Mode</button>
      </div>
      <div class="detail" id="tokenSafeModeDetail">Token Safe Mode: Off</div>
    </details>
    <details class="panel">
      <summary class="section-head">
        <h2>Recent Activity</h2>
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
    const heroHealthCard = document.getElementById("heroHealthCard");
    const heroHealthScore = document.getElementById("heroHealthScore");
    const heroMode = document.getElementById("heroMode");
    const heroApproval = document.getElementById("heroApproval");
    const heroProviders = document.getElementById("heroProviders");
    const heroReadiness = document.getElementById("heroReadiness");
    const setupProgressText = document.getElementById("setupProgressText");
    const setupProgressFill = document.getElementById("setupProgressFill");
    const nextStepTitle = document.getElementById("nextStepTitle");
    const nextStepDetail = document.getElementById("nextStepDetail");
    const flowStatus = document.getElementById("flowStatus");
    const flowStrip = document.getElementById("flowStrip");
    const flowDetail = document.getElementById("flowDetail");
    const workflowTemplateList = document.getElementById("workflowTemplateList");
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
    const routingSummaryGrid = document.getElementById("routingSummaryGrid");
    const routingExplanation = document.getElementById("routingExplanation");
    const routingReasonList = document.getElementById("routingReasonList");
    const routingRejectedList = document.getElementById("routingRejectedList");
    const permissionDetail = document.getElementById("permissionDetail");
    const trustControlGrid = document.getElementById("trustControlGrid");
    const toolControlList = document.getElementById("toolControlList");
    const permissionList = document.getElementById("permissionList");
    const limitList = document.getElementById("limitList");
    const tokenUsage = document.getElementById("tokenUsage");
    const contextDiagnostics = document.getElementById("contextDiagnostics");
    const tokenSafeModeDetail = document.getElementById("tokenSafeModeDetail");
    const activityList = document.getElementById("activityList");
    const logDetail = document.getElementById("logDetail");
    const settingsDetail = document.getElementById("settingsDetail");
    const quickTaskForm = document.getElementById("quickTaskForm");
    const quickTaskInput = document.getElementById("quickTaskInput");
    const quickTaskIncludeSelection = document.getElementById("quickTaskIncludeSelection");
    const headerStatus = document.getElementById("headerStatus");
    const headerRoute = document.getElementById("headerRoute");
    const autoFeedbackToggle = document.getElementById("autoFeedbackToggle");
    const modelGatewayTitle = document.getElementById("modelGatewayTitle");
    const modelGatewayDetail = document.getElementById("modelGatewayDetail");
    const modelGatewayStatus = document.getElementById("modelGatewayStatus");
    const modelSignalGrid = document.getElementById("modelSignalGrid");
    const goldenSignalList = document.getElementById("goldenSignalList");
    const modelRouterList = document.getElementById("modelRouterList");
    const modelTaskFlowList = document.getElementById("modelTaskFlowList");
    const modelAuditList = document.getElementById("modelAuditList");
    const modelIncidentList = document.getElementById("modelIncidentList");

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
      setText(headerStatus, status === "Running" ? "Online" : status);
      headerStatus.dataset.state = status;
      setText(headerRoute, compactModeText(dashboard.agentProviderMode || "cloud", dashboard.agentMode || "agent"));
      setText(heroMode, compactModeText(dashboard.agentProviderMode || "cloud", dashboard.agentMode || "agent"));
      setText(heroApproval, dashboard.approvalMode || "ask");
      setText(heroProviders, providerCountText(dashboard.statistics || {}));
      setText(heroReadiness, readinessText(dashboard.readiness));
      renderServerControls(status, dashboard);
      renderSetupSummary(dashboard);
      renderModelStats(dashboard.modelStats || {}, dashboard.automatedModelFeedback);
      renderRuntimeKernel(dashboard.runtimeKernel || {});
      renderOrchestration(dashboard.orchestrationFlow || {});
      renderWorkflowTemplates(dashboard.workflowTemplates || []);
      renderStatistics(dashboard.statistics || {}, dashboard.insights || [], status);
      renderOnboarding(dashboard.onboarding || []);
      setText(activeModel, activeModelText(dashboard.activeModel));
      renderRoutingChain(dashboard.routingChain || []);
      renderProviderRows(dashboard.providers || []);
      renderRoutingIntelligence(dashboard.routingExplanation || {});
      renderPermissions(dashboard.permissions || {}, dashboard.trustControls || {});
      renderLimitRows(dashboard.limits || []);
      setText(tokenUsage, tokenUsageText(dashboard.tokenUsage || {}));
      setText(contextDiagnostics, contextDiagnosticsText(dashboard.contextDiagnostics || {}));
      setText(tokenSafeModeDetail, tokenSafeModeText(dashboard));
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
        heroServerAction.textContent = "Stop";
        heroServerAction.disabled = false;
        heroServerAction.dataset.action = "stopServer";
        setText(heroSummary, "Running");
        setText(serverDetail, "Running at " + serverUrl + ".");
      } else if (isStarting) {
        heroServerAction.textContent = "Starting...";
        heroServerAction.disabled = true;
        heroServerAction.dataset.action = "";
        setText(heroSummary, "Starting");
        setText(serverDetail, "Starting Agent Hub.");
      } else if (isError) {
        heroServerAction.textContent = "Restart";
        heroServerAction.disabled = false;
        heroServerAction.dataset.action = "restartServer";
        setText(heroSummary, "Needs attention");
        setText(serverDetail, dashboard.statusText || "Open logs or restart Agent Hub.");
      } else {
        heroServerAction.textContent = "Start";
        heroServerAction.disabled = false;
        heroServerAction.dataset.action = "startServer";
        setText(heroSummary, "Off");
        setText(serverDetail, "Start Agent Hub to use the sidebar, VS Code Chat, or Cline.");
      }
      heroServerAction.dataset.state = status;

      const stopButton = document.getElementById("stopServer");
      const restartButton = document.getElementById("restartServer");
      stopButton.disabled = !isRunning && !isStarting;
      restartButton.textContent = isRunning ? "Restart" : "Start Again";
      restartButton.disabled = isStarting;
    }

    function renderSetupSummary(dashboard) {
      const readiness = dashboard.readiness && typeof dashboard.readiness === "object" ? dashboard.readiness : null;
      const rows = Array.isArray(dashboard.onboarding) ? dashboard.onboarding : [];
      const setupRows = rows.filter((row) => row && row.setupRequired !== false && row.action !== true);
      const complete = setupRows.filter((row) => row && row.ok).length;
      const total = setupRows.length || 1;
      const readinessScore = readiness && Number.isFinite(Number(readiness.score)) ? Number(readiness.score) : null;
      const percent = readinessScore === null ? Math.round((complete / total) * 100) : Math.max(0, Math.min(100, Math.round(readinessScore)));
      setupProgressText.textContent = percent + "%";
      setupProgressText.title = readiness
        ? "Readiness score from Agent Hub backend: " + percent + "/100."
        : complete + " of " + total + " setup checks passed. Starting Agent Hub is the next action, not a setup check.";
      setupProgressText.dataset.state = percent >= 90 ? "Ready" : percent >= 50 ? "Starting" : "Stopped";
      setupProgressFill.style.width = percent + "%";

      const readinessStep = readiness && readiness.next_step && typeof readiness.next_step === "object"
        ? readiness.next_step
        : null;
      const nextSetup = setupRows.find((row) => row && !row.ok);
      const nextAction = rows.find((row) => row && row.action === true && !row.ok);
      if (readinessStep && dashboard.status === "Running") {
        nextStepTitle.textContent = readinessStep.status === "warn" ? "Review: " + readinessStep.label : "Next: " + readinessStep.label;
        nextStepDetail.textContent = readinessStep.detail || readinessStep.command || "Review Agent Hub readiness.";
        return;
      }
      if (dashboard.status === "Running" && percent === 100) {
        nextStepTitle.textContent = "Ready";
        nextStepDetail.textContent = "Send a task from the main panel.";
        return;
      }
      if (nextSetup) {
        nextStepTitle.textContent = "Next: " + nextSetup.label;
        nextStepDetail.textContent = setupStepDetail(nextSetup);
        return;
      }
      if (nextAction) {
        nextStepTitle.textContent = "Ready";
        nextStepDetail.textContent = "Click Start in the main panel.";
        return;
      }
      nextStepTitle.textContent = "Ready";
      nextStepDetail.textContent = "Send a task from the main panel.";
    }

    function setupStepDetail(row) {
      const label = row && row.label ? row.label : "";
      if (label === "Python") {
        return "Install Python 3.11 or newer, or set agentHub.pythonPath.";
      }
      if (label === "Workspace") {
        return "Open the repository folder you want Agent Hub to control.";
      }
      if (label === "Config") {
        return "Open a workspace folder so Agent Hub can create or find its config.";
      }
      if (label === "Model provider") {
        return "Save an API key, start Ollama or LM Studio, or choose a local model.";
      }
      if (label === "Node.js" || label === "npm") {
        return "Install Node.js 20 or newer to package the extension or install Codex CLI.";
      }
      if (label === "Codex CLI") {
        return "Install Codex CLI to use no-key Codex routing.";
      }
      if (label === "Backend") {
        return "Reinstall or rebuild the VSIX so the bundled backend is included.";
      }
      return row && row.detail ? row.detail : "Complete this setup step.";
    }

    function readinessText(readiness) {
      if (!readiness || typeof readiness !== "object") {
        return "--";
      }
      const score = Number(readiness.score);
      const label = readiness.state ? String(readiness.state).replace(/_/g, " ") : "unknown";
      return Number.isFinite(score) ? Math.round(score) + "% " + label : label;
    }

    function renderModelStats(stats, automatedFeedback) {
      const state = stats || {};
      const gateway = state.gateway || {};
      modelGatewayTitle.textContent = gateway.status || "Gateway offline";
      modelGatewayDetail.textContent = gateway.detail || "Start Agent Hub to collect model signals.";
      modelGatewayStatus.textContent = gateway.status || "Offline";
      modelGatewayStatus.dataset.state = gatewayStatusState(gateway);
      autoFeedbackToggle.textContent = automatedFeedback ? "Auto Feedback On" : "Auto Feedback Off";
      autoFeedbackToggle.dataset.state = automatedFeedback ? "on" : "off";
      autoFeedbackToggle.title = automatedFeedback
        ? "Automated model feedback is on. Click to turn it off."
        : "Ask a separate judge model to submit adaptive feedback after successful chat responses.";

      modelSignalGrid.textContent = "";
      const tiles = Array.isArray(state.tiles) ? state.tiles : [];
      for (const tile of tiles) {
        modelSignalGrid.append(signalTile(tile));
      }
      if (!tiles.length) {
        modelSignalGrid.append(signalTile({
          label: "Gateway",
          value: "Offline",
          detail: "waiting for diagnostics",
          tone: "warn"
        }));
      }

      renderSignalRows(goldenSignalList, state.goldenSignals || []);
      renderRouterRows(state.routerRows || []);
      renderMiniFlowRows(modelTaskFlowList, state.taskFlow || [], "No task flow yet");
      renderMiniFlowRows(modelAuditList, state.auditRows || [], "No audit signals yet");
      renderMiniFlowRows(modelIncidentList, state.incidents || [], "No incident signals yet");
    }

    function gatewayStatusState(gateway) {
      const tone = gateway && gateway.tone ? gateway.tone : "";
      if (tone === "ok") {
        return "Running";
      }
      if (tone === "error") {
        return "Error";
      }
      return "Starting";
    }

    function renderRuntimeKernel(kernel) {
      const state = kernel || {};
      kernelTitle.textContent = state.title || "Kernel offline";
      kernelDetail.textContent = state.detail || "Start Agent Hub to inspect runtime pressure and subsystem state.";
      kernelStatus.textContent = state.status || "Offline";
      kernelStatus.dataset.state = kernelStatusState(state.statusTone);
      kernelSignalGrid.textContent = "";
      const tiles = Array.isArray(state.tiles) ? state.tiles : [];
      if (!tiles.length) {
        kernelSignalGrid.append(signalTile({
          label: "Kernel",
          value: "Offline",
          detail: "waiting for /v1/kernel",
          tone: "warn"
        }));
      } else {
        for (const tile of tiles) {
          kernelSignalGrid.append(signalTile(tile));
        }
      }
      renderMiniFlowRows(kernelActionList, state.actionRows || [], "No recommended actions yet");
      renderMiniFlowRows(kernelPressureList, state.pressureRows || [], "No pressure signals yet");
      renderMiniFlowRows(kernelSubsystemList, state.subsystemRows || [], "No subsystem state yet");
      renderMiniFlowRows(kernelTimelineList, state.timelineRows || [], "No kernel events yet");
    }

    function kernelStatusState(tone) {
      if (tone === "ok") {
        return "Running";
      }
      if (tone === "error") {
        return "Error";
      }
      return "Starting";
    }

    function signalTile(tile) {
      const item = document.createElement("div");
      item.className = "signal-tile";
      item.dataset.tone = tile.tone || "info";
      const label = document.createElement("span");
      label.textContent = tile.label || "Signal";
      const value = document.createElement("strong");
      value.textContent = tile.value || "--";
      const detail = document.createElement("small");
      detail.textContent = tile.detail || "";
      item.append(label, value, detail);
      return item;
    }

    function renderSignalRows(list, rows) {
      list.textContent = "";
      const items = Array.isArray(rows) ? rows : [];
      if (!items.length) {
        list.append(emptyRow("No golden signals yet"));
        return;
      }
      for (const row of items.slice(0, 8)) {
        const item = document.createElement("li");
        item.className = "model-signal-row";
        const main = document.createElement("div");
        main.className = "mini-flow-main";
        main.textContent = (row.label || "Signal") + ": " + (row.value || "--");
        const meta = document.createElement("span");
        meta.textContent = row.detail || "";
        item.append(main, meta);
        list.append(item);
      }
    }

    function renderRouterRows(rows) {
      modelRouterList.textContent = "";
      const items = Array.isArray(rows) ? rows : [];
      if (!items.length) {
        modelRouterList.append(emptyRow("No ranked models yet"));
        return;
      }
      for (const row of items.slice(0, 6)) {
        const item = document.createElement("li");
        item.className = "model-router-row";
        const rank = document.createElement("span");
        rank.className = "rank-pill";
        rank.textContent = row.rank ? "#" + row.rank : "-";
        const text = document.createElement("div");
        text.className = "model-router-text";
        const main = document.createElement("div");
        main.className = "model-router-main";
        main.textContent = [row.provider || row.agent || "provider", row.model || ""].filter(Boolean).join(" / ");
        const meta = document.createElement("div");
        meta.className = "model-router-meta";
        meta.textContent = [
          row.status || "baseline",
          row.samples ? row.samples + " sample(s)" : "",
          row.latencyMs ? Math.round(row.latencyMs) + " ms" : "",
          row.free ? "free" : ""
        ].filter(Boolean).join(" - ");
        text.append(main, meta);
        const score = document.createElement("div");
        score.className = "router-score";
        score.textContent = row.successRate ? row.successRate + "% ok" : row.score ? row.score + " score" : "--";
        item.append(rank, text, score);
        modelRouterList.append(item);
      }
    }

    function renderMiniFlowRows(list, rows, emptyText) {
      list.textContent = "";
      const items = Array.isArray(rows) ? rows : [];
      if (!items.length) {
        list.append(emptyRow(emptyText));
        return;
      }
      for (const row of items.slice(0, 6)) {
        const item = document.createElement("li");
        item.className = "mini-flow-row";
        if (row.tone) {
          item.dataset.tone = row.tone;
        }
        const text = document.createElement("div");
        const main = document.createElement("div");
        main.className = "mini-flow-main";
        main.textContent = row.label || "Signal";
        const meta = document.createElement("div");
        meta.className = "mini-flow-meta";
        meta.textContent = row.detail || "";
        text.append(main, meta);
        const value = document.createElement("div");
        value.className = "mini-flow-value";
        value.textContent = row.value || "";
        item.append(text, value);
        list.append(item);
      }
    }

    function renderOrchestration(flow) {
      flowStrip.textContent = "";
      const status = flow.status || "Ready";
      flowStatus.textContent = status;
      flowStatus.dataset.state = status === "Complete" || status === "Ready" ? "Running" : status === "Running" ? "Starting" : status === "Offline" ? "Stopped" : "Error";
      flowDetail.textContent = flow.detail || "planner > worker > reviewer > fixer > final";
      const steps = Array.isArray(flow.steps) ? flow.steps : [];
      for (const step of steps) {
        const item = document.createElement("div");
        item.className = "flow-step";
        item.dataset.status = step.status || "ready";
        const label = document.createElement("strong");
        label.textContent = step.label || "Step";
        const meta = document.createElement("span");
        meta.textContent = step.status || step.meta || "ready";
        meta.title = step.meta || "";
        item.title = step.meta || step.label || "";
        item.append(label, meta);
        flowStrip.append(item);
      }
    }

    function renderWorkflowTemplates(templates) {
      workflowTemplateList.textContent = "";
      for (const template of templates.slice(0, 8)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "command-button template-button";
        button.dataset.prompt = template.prompt || "";
        button.dataset.icon = "W";
        const main = document.createElement("span");
        main.className = "button-main";
        main.textContent = template.label || "Workflow";
        const meta = document.createElement("span");
        meta.className = "button-meta";
        meta.textContent = template.meta || "";
        button.append(main, meta);
        button.addEventListener("click", () => runWorkflowPrompt(template.prompt));
        workflowTemplateList.append(button);
      }
    }

    function runWorkflowPrompt(text) {
      const cleanText = String(text || "").trim();
      if (!cleanText) {
        return;
      }
      vscode.postMessage({
        type: "quickTask",
        text: cleanText,
        includeSelection: quickTaskIncludeSelection.checked,
        autoSend: true
      });
    }

    function renderStatistics(stats, insights, status) {
      statsGrid.textContent = "";
      const score = status === "Running" ? Number(stats.healthScore || 0) : 0;
      heroHealthScore.textContent = status === "Running" ? String(score) : "--";
      statsHealth.textContent = status === "Running" ? healthLabel(stats) : "Offline";
      statsHealth.dataset.state = statisticsStatusState(stats, status);
      heroHealthCard.dataset.state = statisticsStatusState(stats, status);

      const cards = [
        {
          value: status === "Running" ? String(score) : "--",
          label: "health score",
          caption: healthCaption(stats, status),
          percent: score,
          featured: true
        },
        {
          value: status === "Running" && stats.readinessScore !== null && stats.readinessScore !== undefined
            ? String(stats.readinessScore)
            : "--",
          label: "readiness score",
          caption: stats.readinessNextStepLabel
            ? stats.readinessState + " / " + stats.readinessNextStepLabel
            : stats.readinessState || "waiting for backend readiness",
          percent: stats.readinessScore === null || stats.readinessScore === undefined ? 0 : Number(stats.readinessScore)
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
        return "No model provider is ready.";
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
      if (typeof card.percent === "number") {
        item.dataset.tone = card.percent >= 80 ? "ok" : card.percent >= 50 ? "warn" : "error";
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
          [row.available ? "active candidate" : "fallback candidate", row.reason || ""].filter(Boolean).join(" - "),
          { tone: row.available ? "ok" : "warn", badge: row.available ? "active" : "fallback" }
        ));
      }
    }

    function renderRoutingIntelligence(row) {
      routingSummaryGrid.textContent = "";
      routingReasonList.textContent = "";
      routingRejectedList.textContent = "";
      const selectedModel = [row.selectedProvider, row.selectedModel].filter(Boolean).join(" / ");
      if (!selectedModel && !row.summary) {
        routingExplanation.textContent = "No routing decision yet";
        routingReasonList.append(emptyRow("Send a request to collect routing intelligence"));
        return;
      }
      routingExplanation.textContent = row.summary || "Routing decision recorded";
      const cards = [
        ["Model", selectedModel || row.selectedAgent || "--"],
        ["Repository", routingRepositoryText(row)],
        ["Success", routingSuccessText(row)],
        ["Workflow", row.selectedWorkflow || "direct route"],
        ["Risk", row.riskLevel || "--"],
        ["Task", row.taskType || "--"],
        ["Context", routingContextText(row)],
        ["Cost", routingCostText(row)],
        ["Saved Today", routingMoneyText(row.savedToday)],
        ["Saved Month", routingMoneyText(row.savedMonth)],
        ["Time", routingTimeText(row)],
        ["Fallbacks", routingFallbackText(row)]
      ];
      for (const card of cards) {
        routingSummaryGrid.append(routingSummaryItem(card[0], card[1]));
      }
      const reasons = Array.isArray(row.reasons) ? row.reasons : [];
      if (reasons.length) {
        for (const reason of reasons.slice(0, 6)) {
          routingReasonList.append(rowElement(
            reason.label || "signal",
            [reason.detail || "", reason.source ? "source " + reason.source : ""].filter(Boolean).join(" - "),
            { badge: "signal" }
          ));
        }
      } else {
        routingReasonList.append(emptyRow("No explanation signals yet"));
      }
      const rejected = Array.isArray(row.rejected) && row.rejected.length
        ? row.rejected
        : Array.isArray(row.fallbackOptions)
          ? row.fallbackOptions
          : [];
      if (rejected.length) {
        for (const item of rejected.slice(0, 4)) {
          routingRejectedList.append(rowElement(
            [item.provider || item.agent || "fallback", item.model || ""].filter(Boolean).join(" / "),
            item.reason || item.why || (item.available ? "fallback option" : "not selected"),
            { tone: item.available ? "warn" : "error", badge: item.available ? "option" : "skipped" }
          ));
        }
      } else {
        routingRejectedList.append(emptyRow("No fallback options recorded"));
      }
    }

    function routingSummaryItem(label, value) {
      const item = document.createElement("div");
      item.className = "routing-summary-item";
      const labelEl = document.createElement("span");
      labelEl.textContent = label;
      const valueEl = document.createElement("strong");
      valueEl.textContent = value || "--";
      item.append(labelEl, valueEl);
      return item;
    }

    function routingContextText(row) {
      const parts = [];
      if (row.contextTokens) {
        parts.push(compactNumber(row.contextTokens) + " tokens");
      }
      if (row.contextStrategy) {
        parts.push(row.contextStrategy);
      }
      if (row.repoSize) {
        parts.push(row.repoSize + " repo");
      }
      return parts.join(" / ") || "--";
    }

    function routingRepositoryText(row) {
      const parts = [];
      if (row.repositoryProject) {
        parts.push(row.repositoryProject);
      }
      if (row.repositoryLanguage) {
        parts.push(row.repositoryLanguage);
      }
      if (row.repositoryArchitecture) {
        parts.push(row.repositoryArchitecture);
      }
      return parts.join(" / ") || "--";
    }

    function routingSuccessText(row) {
      const value = Number(row.successChance);
      if (!Number.isFinite(value) || value <= 0) {
        return "--";
      }
      return Math.round(value) + "%";
    }

    function routingMoneyText(value) {
      if (value === null || value === undefined || value === "") {
        return "--";
      }
      const number = Number(value || 0);
      return Number.isFinite(number) ? "$" + number.toFixed(2) : "--";
    }

    function routingSavingsText(row) {
      if (row.costSavings === null || row.costSavings === undefined || row.costSavings === "") {
        return "--";
      }
      const value = Number(row.costSavings || 0);
      return Number.isFinite(value) ? "$" + value.toFixed(4) : "--";
    }

    function routingCostText(row) {
      if (row.costEstimate !== null && row.costEstimate !== undefined && row.costEstimate !== "") {
        const value = Number(row.costEstimate || 0);
        if (Number.isFinite(value)) {
          return "$" + value.toFixed(value < 0.01 ? 6 : 4);
        }
      }
      return routingSavingsText(row);
    }

    function routingTimeText(row) {
      const value = Number(row.latencyMs);
      if (!Number.isFinite(value) || value <= 0) {
        return "--";
      }
      return value >= 1000 ? (value / 1000).toFixed(1) + "s" : Math.round(value) + "ms";
    }

    function routingFallbackText(row) {
      const value = Number(row.fallbackCount);
      if (!Number.isFinite(value) || value <= 0) {
        return "0";
      }
      return String(Math.round(value));
    }

    function renderOnboarding(rows) {
      onboardingList.textContent = "";
      if (!rows.length) {
        return;
      }
      for (const row of rows) {
        const tone = row && row.ok ? "ok" : row && row.action ? "warn" : row && row.optional ? "info" : "error";
        const action = row && !row.ok && row.actionType ? row.actionType : "";
        onboardingList.append(rowElement(
          onboardingLabel(row),
          row.detail || "",
          {
            tone,
            badge: setupBadge(row, tone),
            action,
            actionLabel: row && row.actionLabel ? row.actionLabel : "Fix"
          }
        ));
      }
    }

    function setupBadge(row, tone) {
      if (row && row.ok) {
        return "ready";
      }
      if (row && row.action) {
        return "action";
      }
      if (row && row.optional) {
        return "optional";
      }
      return tone === "error" ? "needed" : "setup";
    }

    function onboardingLabel(row) {
      const label = row && row.label ? row.label : "Setup";
      return row && row.optional ? label + " (optional)" : label;
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
          ].filter(Boolean).join(" - "),
          {
            tone: row.available ? (row.degraded ? "warn" : "ok") : "error",
            badge: row.available ? (row.degraded ? "degraded" : "ready") : "offline"
          }
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
          limitText(row),
          { tone: limitTone(row), badge: limitBadge(row) }
        ));
      }
    }

    function renderPermissions(state, controls) {
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
      renderTrustControls(controls || {});
      permissionList.textContent = "";
      const recent = Array.isArray(state.recent) ? state.recent.slice(-4).reverse() : [];
      if (!recent.length) {
        permissionList.append(emptyRow("No permission events yet"));
        return;
      }
      for (const item of recent) {
        permissionList.append(rowElement(
          item.tool || item.provider || item.type || "permission",
          [item.category || "", item.risk_level || "", item.allowed ? "allowed" : item.requires_approval ? "approval required" : item.denied ? "denied" : ""].filter(Boolean).join(" - "),
          {
            tone: item.denied ? "error" : item.requires_approval ? "warn" : item.allowed ? "ok" : "info",
            badge: item.denied ? "denied" : item.requires_approval ? "review" : item.allowed ? "allowed" : "event"
          }
        ));
      }
    }

    function renderTrustControls(controls) {
      trustControlGrid.textContent = "";
      toolControlList.textContent = "";
      const rows = Array.isArray(controls.rows) ? controls.rows : [];
      for (const row of rows) {
        const item = document.createElement("div");
        item.className = "trust-row";
        item.dataset.ok = row.ok ? "true" : "false";
        const main = document.createElement("strong");
        main.textContent = row.label || "Control";
        const meta = document.createElement("span");
        meta.textContent = row.state || "";
        item.append(main, meta);
        trustControlGrid.append(item);
      }
      const allowedTools = Array.isArray(controls.allowedTools) ? controls.allowedTools : [];
      const blockedTools = Array.isArray(controls.blockedTools) ? controls.blockedTools : [];
      for (const name of allowedTools.slice(0, 6)) {
        toolControlList.append(toolChip(name, "allowed"));
      }
      for (const name of blockedTools.slice(0, 4)) {
        toolControlList.append(toolChip(name, "blocked"));
      }
      if (!allowedTools.length && !blockedTools.length) {
        toolControlList.append(toolChip("tools pending", "allowed"));
      }
    }

    function toolChip(text, kind) {
      const chip = document.createElement("span");
      chip.className = "tool-chip";
      chip.dataset.kind = kind;
      chip.textContent = text;
      chip.title = text;
      return chip;
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

    function tokenSafeModeText(dashboard) {
      if (dashboard.freeOnlyStrictMode) {
        return "Free Only Mode: On. Codex CLI and non-free/API-key fallbacks are disabled.";
      }
      if (dashboard.codexCliMode) {
        return "Codex CLI Mode: On. No OpenAI API key fallback, compacted workspace, 500-token output cap.";
      }
      return dashboard.tokenSafeMode
        ? "Token Safe Mode: On. Free cloud first; Codex CLI/API-key fallback keeps normal context and output."
        : "Token Safe Mode: Off. Uses the current token and context settings.";
    }

    function renderActivityRows(rows) {
      activityList.textContent = "";
      if (!rows.length) {
        activityList.append(emptyRow("No recent activity"));
        return;
      }
      for (const row of rows.slice(0, 6)) {
        activityList.append(rowElement(row.main, row.meta, { tone: row.tone || "info", badge: activityBadge(row) }));
      }
    }

    function activityBadge(row) {
      const tone = row && row.tone ? row.tone : "info";
      if (tone === "ok") {
        return "done";
      }
      if (tone === "warn") {
        return "watch";
      }
      if (tone === "error") {
        return "issue";
      }
      return "event";
    }

    function limitTone(row) {
      if (!row || row.unavailable_reason) {
        return "error";
      }
      const numbers = [
        row.requests_remaining,
        row.tokens_remaining,
        row.credits_remaining,
        row.quota_remaining
      ]
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value));
      if (numbers.some((value) => value <= 0)) {
        return "error";
      }
      if (numbers.some((value) => value > 0 && value <= 5)) {
        return "warn";
      }
      return numbers.length ? "ok" : "info";
    }

    function limitBadge(row) {
      const tone = limitTone(row);
      if (tone === "ok") {
        return "clear";
      }
      if (tone === "warn") {
        return "low";
      }
      if (tone === "error") {
        return "limit";
      }
      return "unknown";
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

    function rowElement(mainText, metaText, options = {}) {
      const item = document.createElement("li");
      item.className = "row";
      if (options.tone) {
        item.dataset.tone = options.tone;
      }
      const head = document.createElement("div");
      head.className = "row-head";
      if (options.badge) {
        const badge = document.createElement("span");
        badge.className = "row-badge";
        badge.textContent = options.badge;
        head.append(badge);
      }
      const main = document.createElement("div");
      main.className = "main";
      main.textContent = mainText || "Unknown";
      head.append(main);
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = metaText || "";
      item.append(head, meta);
      if (options.action) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "row-action";
        button.textContent = options.actionLabel || "Fix";
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          post(options.action);
        });
        item.append(button);
      }
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
    document.getElementById("quickDashboard").addEventListener("click", () => post("openDashboard"));
    document.getElementById("quickKernel").addEventListener("click", () => post("openRuntimeKernel"));
    document.getElementById("openRuntimeKernel").addEventListener("click", () => post("openRuntimeKernel"));
    document.getElementById("quickCheckup").addEventListener("click", () => post("runCheckup"));
    document.getElementById("quickRouteLab").addEventListener("click", () => post("openRouteLab"));
    document.getElementById("quickSettings").addEventListener("click", () => post("openSettings"));
    document.getElementById("quickTokenSafeMode").addEventListener("click", () => post("enableTokenSafeMode"));
    document.getElementById("quickFreeOnlyMode").addEventListener("click", () => post("enableFreeOnlyMode"));
    document.getElementById("quickCodexCliMode").addEventListener("click", () => post("enableCodexCliMode"));
    document.getElementById("quickInstallCodexCli").addEventListener("click", () => post("installCodexCli"));
    autoFeedbackToggle.addEventListener("click", () => post("toggleAutomatedFeedback"));
    document.getElementById("codeAgent").addEventListener("click", () => post("codeAgent"));
    document.getElementById("explainFile").addEventListener("click", () => post("explainFile"));
    document.getElementById("killerWorkflow").addEventListener("click", () => runWorkflowPrompt("Run the issue-to-PR workflow. Take the current issue or selected prompt through the full Agent Hub loop: plan the work, edit the needed files, run the most relevant tests, fix failures once, and summarize a pull request with files changed, validation, and risks. If no issue is selected, inspect the workspace first and choose the highest-impact actionable issue."));
    document.getElementById("stopServer").addEventListener("click", () => post("stopServer"));
    document.getElementById("restartServer").addEventListener("click", () => post("restartServer"));
    document.getElementById("runCheckup").addEventListener("click", () => post("runCheckup"));
    document.getElementById("checkRequirements").addEventListener("click", () => post("checkRequirements"));
    document.getElementById("fixSafeConfig").addEventListener("click", () => post("fixSafeConfig"));
    document.getElementById("checkHealth").addEventListener("click", () => post("checkHealth"));
    document.getElementById("openRouteLab").addEventListener("click", () => post("openRouteLab"));
    document.getElementById("explainRoute").addEventListener("click", () => post("explainRoute"));
    document.getElementById("openRoutingDashboard").addEventListener("click", () => post("openRoutingDashboard"));
    document.getElementById("tokenSafeMode").addEventListener("click", () => post("enableTokenSafeMode"));
    document.getElementById("freeOnlyMode").addEventListener("click", () => post("enableFreeOnlyMode"));
    document.getElementById("openOutput").addEventListener("click", () => post("openOutput"));
    document.getElementById("openSettings").addEventListener("click", () => post("openSettings"));
    document.getElementById("copyClineConfig").addEventListener("click", () => post("copyClineConfig"));
    document.getElementById("testClineConnection").addEventListener("click", () => post("testClineConnection"));
    document.getElementById("showClineSetup").addEventListener("click", () => post("showClineSetup"));
    document.getElementById("copyClaudeCodeConfig").addEventListener("click", () => post("copyClaudeCodeConfig"));
    document.getElementById("testAnthropicEndpoint").addEventListener("click", () => post("testAnthropicEndpoint"));
    document.getElementById("showClaudeCodeSetup").addEventListener("click", () => post("showClaudeCodeSetup"));
    for (const button of document.querySelectorAll(".trust-preset")) {
      button.addEventListener("click", () => {
        vscode.postMessage({
          type: "applyTrustPreset",
          preset: button.getAttribute("data-preset") || "safe"
        });
      });
    }

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
  const command = request && typeof request.command === "string" ? request.command : "agent";
  if (command === "token-safe") {
    stream.progress("Turning on Token Safe Mode...");
    const result = await enableTokenSafeModeCommand();
    stream.markdown(result.message);
    return { metadata: { command, ok: !!result.ok, cancelled: !!result.cancelled } };
  }
  if (command === "codex-cli") {
    stream.progress("Turning on Codex CLI Mode...");
    const result = await enableCodexCliModeCommand();
    stream.markdown(result.message);
    return { metadata: { command, ok: !!result.ok, cancelled: !!result.cancelled } };
  }
  if (!prompt) {
    stream.markdown("Tell Agent Hub what to inspect, explain, research, or change.");
    return {};
  }

  const config = settings();
  const workspace = workspaceRoot();
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
    stream.markdown("Agent Hub is not running. Click Start in Agent Hub and try again.");
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
    },
    agent_hub: agentHubRequestOptions(config, {
      classification_text: prompt,
      user_task: prompt
    })
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

  if (message.type === "enableMaxTokenSave") {
    await enableMaxTokenSaveModeFromWebview(panel, message.settings);
    return;
  }

  if (message.type === "enableFreeOnlyMode") {
    await enableFreeOnlyModeFromWebview(panel, message.settings);
    return;
  }

  if (message.type === "enableCodexCliMode") {
    await enableCodexCliModeFromWebview(panel, message.settings);
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

  if (message.type === "openDashboard") {
    await openAgentHubDashboard("/dashboard");
    return;
  }

  if (message.type === "installOllamaDesktop") {
    const result = await installOllamaDesktopCommand({ showAlreadyInstalled: false });
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      text: result.message
    });
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
      workflow_success: !!message.workflowSuccess,
      reason: typeof message.reason === "string" ? message.reason : ""
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

async function autoSubmitModelFeedback(panel, options) {
  const requestId = typeof options.responseRequestId === "string" ? options.responseRequestId.trim() : "";
  const webviewRequestId = typeof options.webviewRequestId === "string" ? options.webviewRequestId : "";
  if (!requestId) {
    return;
  }
  postAutoFeedbackStatus(panel, webviewRequestId, "Auto feedback: judge model is reviewing the response.", "info");
  try {
    const verdict = await judgeModelFeedback(options);
    await requestJson("POST", "/v1/feedback", {
      request_id: requestId,
      rating: verdict.rating,
      workflow_success: verdict.workflowSuccess,
      reason: verdict.reason
    });
    const label = verdict.rating === "up" ? "positive" : "needs work";
    postAutoFeedbackStatus(
      panel,
      webviewRequestId,
      `Auto feedback saved: ${label} (${verdict.reason}).`,
      verdict.rating === "up" ? "ok" : "warn"
    );
    output.appendLine(`Automated model feedback saved for ${requestId}: ${verdict.rating}/${verdict.reason} (${verdict.confidence}).`);
  } catch (error) {
    postAutoFeedbackStatus(panel, webviewRequestId, "Auto feedback could not be saved. Check Agent Hub output.", "warn");
    output.appendLine(`Automated model feedback failed for ${requestId}: ${error.message}`);
  }
}

async function judgeModelFeedback(options) {
  const config = options.config || settings();
  const body = autoFeedbackJudgePayload(options, config, "agent-hub-research");
  try {
    return parseJudgeVerdict(chatCompletionContent(await requestJson("POST", "/v1/chat/completions", body)));
  } catch (error) {
    output.appendLine(`Automated feedback judge route failed: ${error.message}. Trying coding route.`);
    const fallbackBody = autoFeedbackJudgePayload(options, config, "agent-hub-coding");
    return parseJudgeVerdict(chatCompletionContent(await requestJson("POST", "/v1/chat/completions", fallbackBody)));
  }
}

function autoFeedbackJudgePayload(options, config, model) {
  return {
    model,
    messages: [
      {
        role: "system",
        content: [
          "You are Agent Hub's independent model-feedback judge.",
          "Evaluate whether the assistant response satisfied the user task.",
          "Return only one compact JSON object with keys rating, workflow_success, reason, confidence, and notes.",
          "rating must be up or down.",
          "reason must be one of good, worked, failed, too_expensive, wrong_files.",
          "Use down when the answer is materially wrong, incomplete, unsafe, edits the wrong files, or admits failure."
        ].join(" ")
      },
      {
        role: "user",
        content: [
          "Original user task:",
          truncateForJudge(options.userText, 6000),
          "",
          "Assistant response:",
          truncateForJudge(options.assistantText, 10000),
          "",
          "Routing and tool summary:",
          JSON.stringify(feedbackRoutingSummary(options.response), null, 2)
        ].join("\n")
      }
    ],
    temperature: 0,
    max_tokens: 260,
    stream: false,
    metadata: {
      source: "vscode-auto-feedback",
      parent_request_id: options.responseRequestId || "",
      client: "agent-hub-vscode"
    },
    agent_hub: {
      route: model === "agent-hub-research" ? (config.researchRoute || "research") : codingAgentRoute(config),
      use_session_history: false,
      automated_feedback_judge: true,
      provider_approval_granted: true
    }
  };
}

function feedbackRoutingSummary(response) {
  const metadata = response && response.agent_hub && typeof response.agent_hub === "object" ? response.agent_hub : {};
  const tools = Array.isArray(metadata.steps)
    ? metadata.steps.slice(0, 12).map((step) => ({
      tool: step && step.tool,
      ok: !(step && step.result && step.result.ok === false),
      error: step && step.result && step.result.error
    }))
    : [];
  return {
    request_id: response && (response.request_id || response.id),
    model: response && response.model,
    agent: response && response.agent,
    provider: response && response.provider,
    usage: response && response.usage,
    failover_count: Array.isArray(response && response.failover) ? response.failover.length : 0,
    tools
  };
}

function parseJudgeVerdict(text) {
  const parsed = parseJsonObjectFromText(text);
  const rating = parsed && String(parsed.rating || "").toLowerCase() === "down" ? "down" : "up";
  const workflowSuccess = typeof (parsed && parsed.workflow_success) === "boolean"
    ? parsed.workflow_success
    : rating === "up";
  const reason = normalizeFeedbackReason(parsed && parsed.reason, rating);
  const confidence = Number(parsed && parsed.confidence);
  return {
    rating,
    workflowSuccess,
    reason,
    confidence: Number.isFinite(confidence) ? Math.max(0, Math.min(1, confidence)) : 0
  };
}

function normalizeFeedbackReason(value, rating) {
  const allowed = new Set(["good", "worked", "failed", "too_expensive", "wrong_files"]);
  const reason = String(value || "").trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_");
  if (allowed.has(reason)) {
    return reason;
  }
  return rating === "up" ? "worked" : "failed";
}

function parseJsonObjectFromText(text) {
  const raw = String(text || "").trim();
  if (!raw) {
    throw new Error("Judge returned an empty response.");
  }
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed;
    }
  } catch (_error) {
    // Fall through to extracting the first object below.
  }
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start === -1 || end <= start) {
    throw new Error("Judge did not return JSON.");
  }
  const parsed = JSON.parse(raw.slice(start, end + 1));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Judge JSON was not an object.");
  }
  return parsed;
}

function chatCompletionContent(response) {
  if (response && Array.isArray(response.choices) && response.choices[0]) {
    const message = response.choices[0].message;
    if (message && typeof message.content === "string") {
      return message.content;
    }
  }
  return responseText(response);
}

function truncateForJudge(value, limit) {
  const text = String(value || "");
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit)}\n[truncated ${text.length - limit} chars]`;
}

function postAutoFeedbackStatus(panel, requestId, text, tone) {
  if (!panel || !panel.webview) {
    return;
  }
  panel.webview.postMessage({
    type: "autoFeedbackStatus",
    requestId,
    text,
    tone
  });
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
  const savedEnvs = [];
  for (const spec of API_KEY_SECRETS) {
    const value = typeof values[spec.id] === "string" ? values[spec.id].trim() : "";
    if (!value) {
      continue;
    }
    await extensionContext.secrets.store(spec.secret, value);
    saved.push(spec.label);
    savedEnvs.push(spec.env);
  }

  if (!saved.length) {
    await postApiKeyStatus(panel, "No new keys entered.");
    return;
  }

  const configSynced = await syncApiKeyProviderAvailabilityForCurrentWorkspace();
  const online = await isServerOnline();
  const suffix = serverProcess
    ? " Restart Agent Hub to use the updated keys."
    : (online
      ? " Restart the running server to use the saved keys."
      : " Start Agent Hub to use the saved keys.");
  const configNote = configSynced
    ? " Enabled matching provider route entries."
    : (savedEnvs.length ? " Matching providers will be enabled when the config is created or repaired." : "");
  await postApiKeyStatus(panel, `Saved ${saved.join(", ")}.${configNote}${suffix}`, { clearInputs: true });
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
  const configSynced = await syncApiKeyProviderAvailabilityForCurrentWorkspace();
  const configNote = configSynced ? " Disabled providers without remaining environment keys." : "";
  await postApiKeyStatus(panel, `Saved API keys cleared.${configNote}`, { clearInputs: true });
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
    automatedModelFeedback: config.automatedModelFeedback,
    ...cloudModelSettingsPayload(config)
  };
}

async function saveChatSettingsFromWebview(panel, rawSettings) {
  try {
    const next = normalizeChatSettingsInput(rawSettings);
    const workspace = workspaceRoot();
    const resource = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "VS Code user settings";
    if (!(await requestPermission({
      category: "config_edit",
      description: "Agent Hub wants to modify VS Code and Agent Hub configuration.",
      resource,
      risk: "medium",
      detail: "This may change provider routing, approval mode, model selections, and server settings."
    }))) {
      postChatSettings(panel, "Saving settings was cancelled.");
      return;
    }
    const target = vscode.ConfigurationTarget.Global;
    const config = vscode.workspace.getConfiguration("agentHub");
    for (const [key, value] of Object.entries(next.workspaceSettings)) {
      await config.update(key, value, target);
    }
    const clearedWorkspaceSettings = workspace
      ? await clearWorkspaceAgentHubSettings(config, Object.keys(next.workspaceSettings))
      : false;
    const configPath = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "";
    const configChanged = configPath
      ? await saveCloudModelSettingsToConfig(configPath, next.cloudSettings, {
        workspaceDir: generatedConfigWorkspaceDir(next.workspaceSettings.configPath, workspace),
        storageDir: generatedConfigStorageDir(next.workspaceSettings.configPath, workspace)
      })
      : false;
    const restartNote = serverProcess || (await isServerOnline())
      ? " Restart Agent Hub to use server or route changes."
      : "";
    const configNote = configChanged ? " Updated Agent Hub model routing." : "";
    const migrationNote = clearedWorkspaceSettings ? " Moved Agent Hub settings out of workspace settings." : "";
    postChatSettings(panel, `Saved user settings.${migrationNote}${configNote}${restartNote}`);
  } catch (error) {
    postChatSettings(panel, `Could not save settings: ${error.message}`);
  }
}

async function enableTokenSafeModeCommand(options = {}) {
  const result = await applyTokenSafeModeSettings(options.rawSettings);
  if (result.ok) {
    vscode.window.showInformationMessage(result.message);
    postChatSettings(chatPanel, result.message);
    if (sidebarProvider && options.refreshSidebar !== false) {
      await sidebarProvider.refresh();
    }
  } else if (result.cancelled) {
    vscode.window.showInformationMessage(result.message);
  } else {
    vscode.window.showErrorMessage(result.message);
  }
  return result;
}

async function enableMaxTokenSaveModeFromWebview(panel, rawSettings) {
  const result = await applyTokenSafeModeSettings(rawSettings);
  postChatSettings(panel, result.message);
  if (result.ok && sidebarProvider) {
    await sidebarProvider.refresh();
  }
  return result;
}

async function enableFreeOnlyModeCommand(options = {}) {
  const result = await applyFreeOnlyModeSettings(options.rawSettings);
  if (result.ok) {
    vscode.window.showInformationMessage(result.message);
    postChatSettings(chatPanel, result.message);
    if (sidebarProvider && options.refreshSidebar !== false) {
      await sidebarProvider.refresh();
    }
  } else if (result.cancelled) {
    vscode.window.showInformationMessage(result.message);
  } else {
    vscode.window.showErrorMessage(result.message);
  }
  return result;
}

async function enableCodexCliModeCommand(options = {}) {
  if (options.skipCodexCliCheck !== true) {
    const status = await codexCliStatus();
    if (!status.installed) {
      const install = "Install Codex CLI";
      const continueAnyway = "Continue Anyway";
      const choice = await vscode.window.showWarningMessage(
        "Codex CLI is not installed or is not on PATH. Install it before enabling no-key Codex CLI routing.",
        install,
        continueAnyway,
        "Cancel"
      );
      if (choice === install) {
        const installResult = await installCodexCliCommand({ showAlreadyInstalled: false });
        return {
          ok: false,
          cancelled: false,
          message: installResult.message
        };
      }
      if (choice !== continueAnyway) {
        return {
          ok: false,
          cancelled: true,
          message: "Codex CLI Mode was cancelled because Codex CLI is not installed."
        };
      }
    }
  }
  const result = await applyCodexCliModeSettings(options.rawSettings);
  if (result.ok) {
    vscode.window.showInformationMessage(result.message);
    postChatSettings(chatPanel, result.message);
    if (sidebarProvider && options.refreshSidebar !== false) {
      await sidebarProvider.refresh();
    }
  } else if (result.cancelled) {
    vscode.window.showInformationMessage(result.message);
  } else {
    vscode.window.showErrorMessage(result.message);
  }
  return result;
}

async function checkRequirementsCommand(options = {}) {
  const rows = await setupRequirementRows(settings(), workspaceRoot());
  const requiredMissing = rows.filter((row) => row.required && !row.ok);
  const actionableMissing = rows.filter((row) => !row.ok && row.actionType);
  const primary = requiredMissing.find((row) => row.actionType) || actionableMissing[0];

  output.appendLine("Agent Hub requirement check:");
  for (const row of rows) {
    output.appendLine(`- ${row.ok ? "OK" : row.required ? "MISSING" : "OPTIONAL"} ${row.label}: ${row.detail}`);
  }

  if (!primary) {
    const optional = rows.filter((row) => row.optional && !row.ok);
    const suffix = optional.length
      ? ` Optional missing: ${optional.map((row) => row.label).join(", ")}.`
      : "";
    if (options.showReadyMessage !== false) {
      vscode.window.showInformationMessage(`Agent Hub core requirements are ready.${suffix}`);
    }
    return { ok: true, rows };
  }

  if (options.promptForFixes === false) {
    if (requiredMissing.length && options.showFailureMessage !== false) {
      vscode.window.showWarningMessage(`${primary.label} is required before Agent Hub can run. ${primary.detail}`);
    }
    return { ok: requiredMissing.length === 0, rows, primary };
  }

  const actionLabel = primary.actionLabel || "Fix";
  const message = requiredMissing.length
    ? `${primary.label} is required before Agent Hub can run. ${primary.detail}`
    : `${primary.label} is optional, but unlocks more Agent Hub features. ${primary.detail}`;
  const choice = await vscode.window.showWarningMessage(
    message,
    actionLabel,
    "Open Logs",
    "Close"
  );
  if (choice === actionLabel) {
    await runRequirementAction(primary.actionType);
  } else if (choice === "Open Logs") {
    output.show(true);
  }
  return { ok: requiredMissing.length === 0, rows };
}

async function runCheckupCommand(options = {}) {
  const workspace = workspaceRoot();
  if (!workspace) {
    vscode.window.showWarningMessage("Open a workspace folder before running Agent Hub Checkup.");
    return { ok: false, cancelled: true };
  }
  output.appendLine("");
  output.appendLine("Agent Hub checkup");
  const requirements = await checkRequirementsCommand({
    promptForFixes: false,
    showReadyMessage: false,
    showFailureMessage: false
  });
  const requiredMissing = Array.isArray(requirements.rows)
    ? requirements.rows.filter((row) => row.required && !row.ok)
    : [];
  if (requiredMissing.length) {
    const first = requiredMissing[0];
    const choice = await vscode.window.showWarningMessage(
      `${first.label} is required before Agent Hub can run. ${first.detail}`,
      "Fix Requirements",
      "Open Logs",
      "Close"
    );
    if (choice === "Fix Requirements") {
      await checkRequirementsCommand();
    } else if (choice === "Open Logs") {
      output.show(true);
    }
    return { ok: false, requirements };
  }

  const repair = await fixSafeConfigCommand({ quietNoChange: true, source: options.source || "checkup" });
  if (repair && repair.ok === false && repair.cancelled !== true) {
    return { ok: false, requirements, repair };
  }

  if (!(await isServerOnline())) {
    setServerLifecycleState("Starting", "Checkup is starting Agent Hub...");
    await startServer();
  }
  const online = (await isServerOnline()) || (await waitForServer(7000));
  if (!online) {
    const message = "Checkup could not confirm the Agent Hub backend is running. Open logs for the startup details.";
    output.appendLine(message);
    const choice = await vscode.window.showWarningMessage(message, "Open Logs", "Route Lab Anyway");
    if (choice === "Open Logs") {
      output.show(true);
      return { ok: false, requirements, repair, backendOnline: false };
    }
    if (choice !== "Route Lab Anyway") {
      return { ok: false, requirements, repair, backendOnline: false };
    }
  }

  const routeLab = await openRouteLabCommand({ prompt: PERSONAL_BENCHMARK_PROMPT });
  if (routeLab.ok) {
    vscode.window.showInformationMessage("Agent Hub Checkup complete. Route Lab is open with the current model decision.");
  }
  return {
    ok: !!routeLab.ok,
    requirements,
    repair,
    backendOnline: online,
    routeLab
  };
}

async function fixSafeConfigCommand(options = {}) {
  const workspace = workspaceRoot();
  if (!workspace) {
    vscode.window.showWarningMessage("Open a workspace folder before repairing Agent Hub config.");
    return { ok: false, cancelled: true };
  }
  const config = settings();
  const configPath = resolveConfigPath(config.configPath, workspace);
  if (!(await requestPermission({
    category: "config_edit",
    description: "Agent Hub wants to apply conservative repairs to the workspace config.",
    resource: configPath,
    risk: "medium",
    detail: "This removes unknown route agent references and aligns shell-tool toggles with the effective shell policy."
  }))) {
    return { ok: false, cancelled: true };
  }
  const launch = await serverLaunchEnvironment(workspace);
  if (!(await ensurePythonBackend(config, workspace, launch))) {
    return { ok: false, cancelled: false };
  }
  const args = [
    ...launch.pythonArgs,
    "-m",
    "agent_hub",
    "--config",
    configPath,
    "doctor",
    "--fix-safe",
    "--json"
  ];
  output.appendLine("");
  output.appendLine("Agent Hub safe config repair");
  output.appendLine(formatCliCommandForLog(launch.pythonCommand, args));
  try {
    const { stdout, stderr } = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Agent Hub: Repairing config",
        cancellable: false
      },
      () => execFile(launch.pythonCommand, args, {
        cwd: workspace,
        env: launch.env,
        timeout: 120000,
        maxBuffer: 6 * 1024 * 1024
      })
    );
    if (stderr && String(stderr).trim()) {
      output.appendLine(String(stderr).trim());
    }
    const report = parseJsonObjectFromText(stdout);
    const fix = report && report.fix_safe && typeof report.fix_safe === "object"
      ? report.fix_safe
      : {};
    const errors = Array.isArray(fix.errors) ? fix.errors.filter(Boolean) : [];
    const changes = Array.isArray(fix.changes) ? fix.changes.filter(Boolean) : [];
    if (errors.length) {
      const message = `Agent Hub config repair could not finish: ${errors[0]}`;
      output.appendLine(message);
      vscode.window.showErrorMessage(message);
      return { ok: false, errors };
    }
    const message = changes.length
      ? `Agent Hub config repaired: ${changes.join(" ")}`
      : "Agent Hub config already looks clean.";
    output.appendLine(message);
    if (changes.length || options.quietNoChange !== true) {
      vscode.window.showInformationMessage(message);
    }
    return { ok: true, changed: !!fix.changed, changes };
  } catch (error) {
    output.appendLine(`Config repair failed: ${error.message}`);
    if (error.stderr) {
      output.appendLine(String(error.stderr));
    }
    output.show(true);
    vscode.window.showErrorMessage(`Config repair failed: ${error.message}`);
    return { ok: false, cancelled: false };
  }
}

async function setupRequirementRows(config, workspace) {
  const backendRoot = backendSourceRoot(workspace);
  const python = await detectPythonForOnboarding(config, workspace);
  const node = await nodeRuntimeStatus();
  const npm = await npmRuntimeStatus();
  const codex = await codexCliStatus();
  const ollama = await ollamaDesktopStatus();
  return [
    {
      label: "Workspace",
      ok: !!workspace,
      required: true,
      detail: workspace ? workspace : "open a workspace folder"
    },
    {
      label: "Backend",
      ok: !!backendRoot,
      required: true,
      detail: backendRoot ? `found at ${backendRoot}` : "backend package not found"
    },
    {
      label: "Python",
      ok: python.ok,
      required: true,
      detail: python.detail,
      actionType: python.ok ? "" : "installPython",
      actionLabel: "Install Python"
    },
    {
      label: "Node.js",
      ok: node.ok,
      optional: true,
      detail: node.detail,
      actionType: node.ok ? "" : "installNode",
      actionLabel: "Install Node"
    },
    {
      label: "npm",
      ok: npm.ok,
      optional: true,
      detail: npm.detail,
      actionType: npm.ok ? "" : "installNode",
      actionLabel: "Install Node"
    },
    {
      label: "Codex CLI",
      ok: codex.installed,
      optional: true,
      detail: codex.installed ? (codex.version || "installed") : "optional no-key routing helper",
      actionType: codex.installed ? "" : "installCodexCli",
      actionLabel: "Install Codex CLI"
    },
    {
      label: "Ollama",
      ok: ollama.installed,
      optional: true,
      detail: ollama.installed ? (ollama.version || "installed") : "optional local-model runtime",
      actionType: ollama.installed ? "" : "installOllamaDesktop",
      actionLabel: "Install Ollama"
    }
  ];
}

async function runRequirementAction(actionType) {
  if (actionType === "installPython") {
    return installPythonCommand();
  }
  if (actionType === "installNode") {
    return installNodeCommand();
  }
  if (actionType === "installCodexCli") {
    return installCodexCliCommand({ showAlreadyInstalled: false });
  }
  if (actionType === "installOllamaDesktop") {
    return installOllamaDesktopCommand({ showAlreadyInstalled: false });
  }
  if (actionType === "startServer") {
    return startServer();
  }
  if (actionType === "runCheckup") {
    return runCheckupCommand({ source: "onboarding" });
  }
  if (actionType === "openSettings") {
    return openAgentHubSettings();
  }
  if (actionType === "runPersonalBenchmark") {
    return runPersonalBenchmark({ source: "sidebar" });
  }
  if (actionType === "explainRoute") {
    return explainRouteCommand();
  }
  if (actionType === "openRouteLab") {
    return openRouteLabCommand();
  }
  if (actionType === "openReadmeProof") {
    return openReadmeProofSection();
  }
  return undefined;
}

async function installPythonCommand(options = {}) {
  const status = await detectPythonForOnboarding(settings(), workspaceRoot());
  if (status.ok && options.force !== true) {
    const message = `Python is already ready. ${status.detail}`;
    vscode.window.showInformationMessage(message);
    return { ok: true, message };
  }

  const winget = await wingetStatus();
  const choices = process.platform === "win32" && winget.installed
    ? ["Install with winget", "Open Download", "Cancel"]
    : ["Open Download", "Cancel"];
  const choice = await vscode.window.showWarningMessage(
    "Agent Hub needs Python 3.11 or newer. Install Python, then restart VS Code if PATH changes.",
    ...choices
  );
  if (choice === "Install with winget") {
    const command = `winget install -e --id ${PYTHON_WINGET_ID}`;
    if (!(await requestPermission({
      category: "shell_command",
      description: "Agent Hub wants to install Python with winget.",
      resource: command,
      risk: "high",
      detail: "This opens a visible VS Code terminal. Review the installer prompts before accepting them."
    }))) {
      return { ok: false, cancelled: true, message: "Python install was cancelled." };
    }
    openSetupTerminal("Agent Hub Python Setup", command);
    return { ok: true, message: "Opened a terminal to install Python. Restart VS Code after installation if PATH changes." };
  }
  if (choice === "Open Download") {
    await vscode.env.openExternal(vscode.Uri.parse(PYTHON_DOWNLOAD_URL));
    return { ok: true, message: "Opened the official Python download page." };
  }
  return { ok: false, cancelled: true, message: "Python install was cancelled." };
}

async function installNodeCommand(options = {}) {
  const status = await nodeRuntimeStatus();
  const npm = await npmRuntimeStatus();
  if (status.ok && npm.ok && options.force !== true) {
    const message = `Node.js is already ready. ${status.detail}`;
    vscode.window.showInformationMessage(message);
    return { ok: true, message };
  }

  const winget = await wingetStatus();
  const choices = process.platform === "win32" && winget.installed
    ? ["Install with winget", "Open Download", "Cancel"]
    : ["Open Download", "Cancel"];
  const choice = await vscode.window.showWarningMessage(
    "Agent Hub needs Node.js 20 or newer for extension packaging and Codex CLI installation.",
    ...choices
  );
  if (choice === "Install with winget") {
    const command = `winget install -e --id ${NODE_WINGET_ID}`;
    if (!(await requestPermission({
      category: "shell_command",
      description: "Agent Hub wants to install Node.js with winget.",
      resource: command,
      risk: "high",
      detail: "This opens a visible VS Code terminal. Review the installer prompts before accepting them."
    }))) {
      return { ok: false, cancelled: true, message: "Node.js install was cancelled." };
    }
    openSetupTerminal("Agent Hub Node Setup", command);
    return { ok: true, message: "Opened a terminal to install Node.js. Restart VS Code after installation if PATH changes." };
  }
  if (choice === "Open Download") {
    await vscode.env.openExternal(vscode.Uri.parse(NODE_DOWNLOAD_URL));
    return { ok: true, message: "Opened the official Node.js download page." };
  }
  return { ok: false, cancelled: true, message: "Node.js install was cancelled." };
}

async function installCodexCliCommand(options = {}) {
  const status = await codexCliStatus();
  if (status.installed && options.force !== true && options.showAlreadyInstalled !== false) {
    const login = "Run Login";
    const upgrade = "Upgrade";
    const versionText = status.version ? ` (${status.version})` : "";
    const choice = await vscode.window.showInformationMessage(
      `Codex CLI is already installed${versionText}.`,
      login,
      upgrade,
      "Close"
    );
    if (choice === login) {
      openCodexCliTerminal(codexCliLoginTerminalCommand());
      return {
        ok: true,
        message: "Opened a terminal for Codex CLI login."
      };
    }
    if (choice !== upgrade) {
      return {
        ok: true,
        message: "Codex CLI is already installed."
      };
    }
  }

  const npm = await npmRuntimeStatus();
  if (!npm.ok) {
    const choice = await vscode.window.showWarningMessage(
      "Codex CLI installs through npm, but npm was not found. Install Node.js first.",
      "Install Node.js",
      "Cancel"
    );
    if (choice === "Install Node.js") {
      return installNodeCommand({ force: true });
    }
    return {
      ok: false,
      cancelled: true,
      message: "Codex CLI install was cancelled because npm is missing."
    };
  }

  const command = codexCliInstallTerminalCommand();
  if (!(await requestPermission({
    category: "shell_command",
    description: "Agent Hub wants to install the OpenAI Codex CLI with npm.",
    resource: `npm install -g ${CODEX_CLI_NPM_PACKAGE}`,
    risk: "high",
    detail: "This opens a visible VS Code terminal, installs the official @openai/codex npm package globally, and then starts Codex CLI login."
  }))) {
    return {
      ok: false,
      cancelled: true,
      message: "Codex CLI install was cancelled."
    };
  }

  openCodexCliTerminal(command);
  const message = "Opened a terminal to install Codex CLI. After login finishes, run Agent Hub: Use Codex CLI Without API Key again.";
  vscode.window.showInformationMessage(message);
  return {
    ok: true,
    cancelled: false,
    message
  };
}

async function installOllamaDesktopCommand(options = {}) {
  const status = await ollamaDesktopStatus();
  if (status.installed && options.force !== true && options.showAlreadyInstalled !== false) {
    const versionText = status.version ? ` (${status.version})` : "";
    const chooseModel = "Choose Local Model";
    const choice = await vscode.window.showInformationMessage(
      `Ollama is already installed${versionText}.`,
      chooseModel,
      "Close"
    );
    if (choice === chooseModel && chatPanel) {
      await chooseLocalModel(chatPanel);
    }
    return {
      ok: true,
      cancelled: false,
      message: "Ollama is already installed."
    };
  }

  if (!(await requestPermission({
    category: "model_download",
    description: "Agent Hub wants to open the official Ollama Desktop download page.",
    resource: OLLAMA_DOWNLOAD_URL,
    risk: "medium",
    detail: "Install Ollama Desktop, restart VS Code if the ollama command is not detected, then use Choose Local Model to pull qwen2.5-coder:7b."
  }))) {
    return {
      ok: false,
      cancelled: true,
      message: "Ollama Desktop install was cancelled."
    };
  }

  await vscode.env.openExternal(vscode.Uri.parse(OLLAMA_DOWNLOAD_URL));
  const message = "Opened the official Ollama Desktop download page. Install Ollama, restart VS Code if PATH is not updated, then choose a local model.";
  vscode.window.showInformationMessage(message);
  return {
    ok: true,
    cancelled: false,
    message
  };
}

async function enableCodexCliModeFromWebview(panel, rawSettings) {
  const result = await applyCodexCliModeSettings(rawSettings);
  postChatSettings(panel, result.message);
  if (result.ok && sidebarProvider) {
    await sidebarProvider.refresh();
  }
  return result;
}

async function enableFreeOnlyModeFromWebview(panel, rawSettings) {
  const result = await applyFreeOnlyModeSettings(rawSettings);
  postChatSettings(panel, result.message);
  if (result.ok && sidebarProvider) {
    await sidebarProvider.refresh();
  }
  return result;
}

async function applyCodexCliModeSettings(rawSettings) {
  try {
    const baseSettings = chatSettingsPayload(settings());
    const profileInput = {
      ...baseSettings,
      ...(rawSettings && typeof rawSettings === "object" ? rawSettings : {}),
      agentProviderMode: "cloud",
      cloudRouteMode: "codex-cli",
      codexCliEnabled: true,
      apiKeyModelsEnabled: false,
      freeCloudPresetsEnabled: false,
      freeOnly: true,
      disableNonFreeModels: false,
      enableLoadBalancing: false,
      maxTokens: CODEX_CLI_OUTPUT_TOKENS,
      agentMaxSteps: CODEX_CLI_AGENT_STEPS,
      groupPlanCandidates: 1
    };
    const next = normalizeChatSettingsInput(profileInput);
    const workspace = workspaceRoot();
    const resource = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "VS Code user settings";
    if (!(await requestPermission({
      category: "config_edit",
      description: "Agent Hub wants to enable Codex CLI Mode without an OpenAI API key.",
      resource,
      risk: "medium",
      detail: "This uses the locally logged-in Codex CLI, disables API-key model fallbacks, and applies a smaller context/output budget for Codex requests."
    }))) {
      return {
        ok: false,
        cancelled: true,
        message: "Codex CLI Mode was cancelled."
      };
    }

    const target = vscode.ConfigurationTarget.Global;
    const config = vscode.workspace.getConfiguration("agentHub");
    for (const [key, value] of Object.entries(next.workspaceSettings)) {
      await config.update(key, value, target);
    }
    await config.update("agentContextBudgetTokens", CODEX_CLI_CONTEXT_BUDGET, target);
    await config.update("agentContextCompactionEnabled", true, target);
    await config.update("contextMode", "minimal", target);

    const clearKeys = [
      ...Object.keys(next.workspaceSettings),
      "agentContextBudgetTokens",
      "agentContextCompactionEnabled",
      "contextMode"
    ];
    const clearedWorkspaceSettings = workspace
      ? await clearWorkspaceAgentHubSettings(config, clearKeys)
      : false;
    const configPath = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "";
    const configChanged = configPath
      ? await saveCloudModelSettingsToConfig(configPath, {
        ...next.cloudSettings,
        cloudRouteMode: "codex-cli",
        codexCliEnabled: true,
        apiKeyModelsEnabled: false,
        freeCloudPresetsEnabled: false,
        freeOnly: true,
        disableNonFreeModels: false,
        enableLoadBalancing: false,
        freeCloudSavingsMode: false,
        codexCliMode: true,
        codexCliTokenOptimized: true,
        agentContextBudgetTokens: CODEX_CLI_CONTEXT_BUDGET
      }, {
        workspaceDir: generatedConfigWorkspaceDir(next.workspaceSettings.configPath, workspace),
        storageDir: generatedConfigStorageDir(next.workspaceSettings.configPath, workspace)
      })
      : false;
    const restartNote = serverProcess || (await isServerOnline())
      ? " Restart Agent Hub to use the Codex CLI route."
      : "";
    const configNote = configChanged ? " Updated Agent Hub routing and Codex token budgets." : "";
    const migrationNote = clearedWorkspaceSettings ? " Moved Agent Hub settings out of workspace settings." : "";
    return {
      ok: true,
      cancelled: false,
      message: `Codex CLI Mode is on: codex-cli first, no OpenAI API key fallback, compact context.${migrationNote}${configNote}${restartNote}`
    };
  } catch (error) {
    return {
      ok: false,
      cancelled: false,
      message: `Could not enable Codex CLI Mode: ${error.message}`
    };
  }
}

async function applyFreeOnlyModeSettings(rawSettings) {
  try {
    const baseSettings = chatSettingsPayload(settings());
    const profileInput = {
      ...baseSettings,
      ...(rawSettings && typeof rawSettings === "object" ? rawSettings : {}),
      agentProviderMode: "cloud",
      cloudRouteMode: "ollama-cloud",
      codexCliEnabled: false,
      apiKeyModelsEnabled: false,
      freeCloudPresetsEnabled: true,
      freeOnly: true,
      disableNonFreeModels: true,
      enableLoadBalancing: true,
      maxTokens: null,
      agentMaxSteps: DEFAULT_AGENT_MAX_STEPS,
      groupPlanCandidates: 1
    };
    const next = normalizeChatSettingsInput(profileInput);
    const workspace = workspaceRoot();
    const resource = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "VS Code user settings";
    if (!(await requestPermission({
      category: "config_edit",
      description: "Agent Hub wants to disable Codex CLI and non-free model fallbacks.",
      resource,
      risk: "medium",
      detail: "This keeps only free/local/free-tier models eligible and prevents Codex CLI, OpenAI, Claude, Gemini, and other non-free fallbacks from being selected."
    }))) {
      return {
        ok: false,
        cancelled: true,
        message: "Free Only Mode was cancelled."
      };
    }

    const target = vscode.ConfigurationTarget.Global;
    const config = vscode.workspace.getConfiguration("agentHub");
    for (const [key, value] of Object.entries(next.workspaceSettings)) {
      await config.update(key, value, target);
    }
    await config.update("agentContextBudgetTokens", DEFAULT_AGENT_CONTEXT_BUDGET, target);
    await config.update("agentContextCompactionEnabled", true, target);
    await config.update("contextMode", "balanced", target);

    const clearKeys = [
      ...Object.keys(next.workspaceSettings),
      "agentContextBudgetTokens",
      "agentContextCompactionEnabled",
      "contextMode"
    ];
    const clearedWorkspaceSettings = workspace
      ? await clearWorkspaceAgentHubSettings(config, clearKeys)
      : false;
    const configPath = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "";
    const configChanged = configPath
      ? await saveCloudModelSettingsToConfig(configPath, {
        ...next.cloudSettings,
        cloudRouteMode: "ollama-cloud",
        codexCliEnabled: false,
        apiKeyModelsEnabled: false,
        freeCloudPresetsEnabled: true,
        freeOnly: true,
        disableNonFreeModels: true,
        enableLoadBalancing: true,
        maxTokenSaveMode: false,
        freeCloudSavingsMode: false,
        codexCliMode: false,
        codexCliTokenOptimized: false,
        agentContextBudgetTokens: DEFAULT_AGENT_CONTEXT_BUDGET
      }, {
        workspaceDir: generatedConfigWorkspaceDir(next.workspaceSettings.configPath, workspace),
        storageDir: generatedConfigStorageDir(next.workspaceSettings.configPath, workspace)
      })
      : false;
    const restartNote = serverProcess || (await isServerOnline())
      ? " Restart Agent Hub to apply strict free routing."
      : "";
    const configNote = configChanged ? " Updated Agent Hub routing and disabled non-free agents." : "";
    const migrationNote = clearedWorkspaceSettings ? " Moved Agent Hub settings out of workspace settings." : "";
    return {
      ok: true,
      cancelled: false,
      message: `Free Only Mode is on: Codex CLI and non-free/API-key fallbacks are disabled.${migrationNote}${configNote}${restartNote}`
    };
  } catch (error) {
    return {
      ok: false,
      cancelled: false,
      message: `Could not enable Free Only Mode: ${error.message}`
    };
  }
}

async function applyTokenSafeModeSettings(rawSettings) {
  try {
    const baseSettings = chatSettingsPayload(settings());
    const profileInput = {
      ...baseSettings,
      ...(rawSettings && typeof rawSettings === "object" ? rawSettings : {}),
      agentProviderMode: "cloud",
      cloudRouteMode: "ollama-cloud",
      codexCliEnabled: true,
      apiKeyModelsEnabled: true,
      freeCloudPresetsEnabled: true,
      freeOnly: false,
      disableNonFreeModels: false,
      enableLoadBalancing: true,
      maxTokens: null,
      agentMaxSteps: DEFAULT_AGENT_MAX_STEPS,
      groupPlanCandidates: 1
    };
    const next = normalizeChatSettingsInput(profileInput);
    const workspace = workspaceRoot();
    const resource = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "VS Code user settings";
    if (!(await requestPermission({
      category: "config_edit",
      description: "Agent Hub wants to enable Token Safe Mode for free cloud offload.",
      resource,
      risk: "medium",
      detail: "This enables free cloud models first with Codex CLI and API-key fallback kept at the normal context and output budget."
    }))) {
      return {
        ok: false,
        cancelled: true,
        message: "Token Safe Mode was cancelled."
      };
    }

    const target = vscode.ConfigurationTarget.Global;
    const config = vscode.workspace.getConfiguration("agentHub");
    for (const [key, value] of Object.entries(next.workspaceSettings)) {
      await config.update(key, value, target);
    }
    await config.update("agentContextBudgetTokens", DEFAULT_AGENT_CONTEXT_BUDGET, target);
    await config.update("agentContextCompactionEnabled", true, target);
    await config.update("contextMode", "balanced", target);

    const clearKeys = [
      ...Object.keys(next.workspaceSettings),
      "agentContextBudgetTokens",
      "agentContextCompactionEnabled",
      "contextMode"
    ];
    const clearedWorkspaceSettings = workspace
      ? await clearWorkspaceAgentHubSettings(config, clearKeys)
      : false;
    const configPath = workspace
      ? resolveConfigPath(next.workspaceSettings.configPath, workspace)
      : "";
    const configChanged = configPath
      ? await saveCloudModelSettingsToConfig(configPath, {
        ...next.cloudSettings,
        cloudRouteMode: "ollama-cloud",
        codexCliEnabled: true,
        apiKeyModelsEnabled: true,
        freeCloudPresetsEnabled: true,
        freeOnly: false,
        disableNonFreeModels: false,
        enableLoadBalancing: true,
        maxTokenSaveMode: true,
        freeCloudSavingsMode: true,
        agentContextBudgetTokens: DEFAULT_AGENT_CONTEXT_BUDGET
      }, {
        workspaceDir: generatedConfigWorkspaceDir(next.workspaceSettings.configPath, workspace),
        storageDir: generatedConfigStorageDir(next.workspaceSettings.configPath, workspace)
      })
      : false;
    const restartNote = serverProcess || (await isServerOnline())
      ? " Restart Agent Hub to use the updated config defaults."
      : "";
    const configNote = configChanged ? " Updated Agent Hub routing and token budgets." : "";
    const migrationNote = clearedWorkspaceSettings ? " Moved Agent Hub settings out of workspace settings." : "";
    return {
      ok: true,
      cancelled: false,
      message: `Token Safe Mode is on: free cloud models first, full Codex CLI/API-key fallback preserved.${migrationNote}${configNote}${restartNote}`
    };
  } catch (error) {
    return {
      ok: false,
      cancelled: false,
      message: `Could not enable Token Safe Mode: ${error.message}`
    };
  }
}

async function clearWorkspaceAgentHubSettings(config, keys) {
  let cleared = 0;
  for (const key of keys) {
    const inspected = config.inspect(key);
    if (!inspected || inspected.workspaceValue === undefined) {
      continue;
    }
    await config.update(key, undefined, vscode.ConfigurationTarget.Workspace);
    cleared += 1;
  }
  return cleared > 0;
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
      autoStart: !!input.autoStart,
      automatedModelFeedback: !!input.automatedModelFeedback
    },
    cloudSettings: {
      cloudRouteMode: normalizeCloudRouteMode(input.cloudRouteMode || "ollama-cloud"),
      apiKeyModelsEnabled: !!input.apiKeyModelsEnabled,
      freeCloudPresetsEnabled: !!input.freeCloudPresetsEnabled,
      freeOnly: !!input.freeOnly,
      disableNonFreeModels: !!input.disableNonFreeModels,
      enableLoadBalancing: !!input.enableLoadBalancing,
      exposeRoutingDetails: !!input.exposeRoutingDetails,
      codexModel: cleanSettingString(input.codexModel, DEFAULT_CODEX_MODEL),
      codexCliEnabled: normalizeCloudRouteMode(input.cloudRouteMode || current.cloudRouteMode) === "codex-cli" || !!input.codexCliEnabled,
      codexCliModel: cleanSettingString(input.codexCliModel, DEFAULT_CODEX_CLI_MODEL),
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
  if (body && body.max_tokens !== undefined && body.max_tokens !== null) {
    const explicit = Number(body.max_tokens);
    if (Number.isFinite(explicit) && explicit > 0) {
      body.max_tokens = Math.floor(explicit);
      return body;
    }
  }
  const value = config && Number(config.maxTokens);
  if (Number.isFinite(value) && value > 0) {
    body.max_tokens = Math.floor(value);
  }
  return body;
}

function isMaxTokenSaveMode(config) {
  if (!config || normalizeContextMode(config.contextMode) !== "minimal") {
    return false;
  }
  const budget = Number(config.agentContextBudgetTokens);
  const outputTokens = Number(config.maxTokens);
  const steps = Number(config.agentMaxSteps);
  return (
    Number.isFinite(budget) &&
    budget > 0 &&
    budget <= 4000 &&
    Number.isFinite(outputTokens) &&
    outputTokens > 0 &&
    outputTokens <= 800 &&
    Number.isFinite(steps) &&
    steps > 0 &&
    steps <= 8
  );
}

function isFreeCloudSavingsMode(config) {
  const raw = readResolvedAgentHubConfig(config);
  const routing = raw && raw.routing && typeof raw.routing === "object" && !Array.isArray(raw.routing)
    ? raw.routing
    : {};
  if (routing.free_cloud_savings_mode === true) {
    return true;
  }
  const cloudSettings = cloudModelSettingsPayload(config);
  return isMaxTokenSaveMode(config) && cloudSettings.cloudRouteMode !== "codex-cli";
}

function isCodexCliTokenOptimizedMode(config) {
  const cloudSettings = cloudModelSettingsPayload(config);
  return isMaxTokenSaveMode(config) && cloudSettings.cloudRouteMode === "codex-cli";
}

function readResolvedAgentHubConfig(config) {
  const workspace = workspaceRoot();
  if (!workspace) {
    return null;
  }
  try {
    const configPath = resolveConfigPath(config.configPath, workspace);
    if (!fs.existsSync(configPath)) {
      return null;
    }
    const raw = parseJsonConfigText(fs.readFileSync(configPath, "utf8")).value;
    return raw && typeof raw === "object" && !Array.isArray(raw) ? raw : null;
  } catch (_error) {
    return null;
  }
}

function agentHubRequestOptions(config, extra = {}) {
  const options = { ...(extra && typeof extra === "object" ? extra : {}) };
  const cloudSettings = cloudModelSettingsPayload(config);
  if (cloudSettings.freeOnly !== false && cloudSettings.disableNonFreeModels === true) {
    options.free_only = true;
    options.disable_non_free_models = true;
    options.routing_mode = "cheapest";
  }
  if (isFreeCloudSavingsMode(config)) {
    options.free_cloud_offload = true;
    options.prefer_free_cloud = true;
    options.allow_cloud_exploration = true;
    options.routing_mode = "cheapest";
  }
  if (isCodexCliTokenOptimizedMode(config)) {
    options.max_token_save_mode = true;
    options.context_mode = "minimal";
    options.minimal_tool_schema = true;
    options.reduced_repo_context = true;
    options.codex_cli_token_optimized = true;
    options.codex_cli_prompt_budget_tokens = config.agentContextBudgetTokens;
    options.max_context_tokens = config.agentContextBudgetTokens;
    options.context_budget_tokens = config.agentContextBudgetTokens;
  }
  return options;
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
  return ["ollama-cloud", "api-key", "codex-cli"].includes(mode) ? mode : "ollama-cloud";
}

function cloudModelSettingsPayload(config) {
  const fallback = {
    cloudRouteMode: "ollama-cloud",
    apiKeyModelsEnabled: false,
    freeCloudPresetsEnabled: false,
    freeOnly: true,
    disableNonFreeModels: false,
    enableLoadBalancing: true,
    exposeRoutingDetails: false,
    codexModel: DEFAULT_CODEX_MODEL,
    codexCliModel: DEFAULT_CODEX_CLI_MODEL,
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
      disableNonFreeModels: raw.disable_non_free_models === true,
      enableLoadBalancing: raw.enable_load_balancing !== false,
      exposeRoutingDetails: raw.expose_routing_details === true,
      codexModel: modelForAgent(raw, "codex", DEFAULT_CODEX_MODEL),
      codexCliModel: modelForAgent(raw, CODEX_CLI_AGENT_NAME, DEFAULT_CODEX_CLI_MODEL),
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
  if (selection && typeof selection === "object" && selection.api_key_models_enabled === true) {
    return true;
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
  const selection = data && data.cloud_control_selection;
  if (selection && typeof selection === "object" && selection.free_cloud_presets_enabled === true) {
    return true;
  }
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
      envPresent: !!process.env[spec.env],
      saved
    });
  }
  return rows;
}

async function availableApiKeyEnvs() {
  const envs = new Set();
  for (const spec of API_KEY_SECRETS) {
    if (process.env[spec.env]) {
      envs.add(spec.env);
      continue;
    }
    if (!extensionContext || !extensionContext.secrets) {
      continue;
    }
    const value = await extensionContext.secrets.get(spec.secret);
    if (value && value.trim()) {
      envs.add(spec.env);
    }
  }
  return envs;
}

function cloudSettingsWithAvailableApiKeys(cloudSettings, envs) {
  return {
    ...(cloudSettings && typeof cloudSettings === "object" ? cloudSettings : {}),
    availableApiKeyEnvs: Array.from(envs || [])
  };
}

function availableApiKeyEnvSet(settings = {}) {
  return new Set(Array.isArray(settings.availableApiKeyEnvs) ? settings.availableApiKeyEnvs : []);
}

function sourceHasAvailableApiKey(source, settings = {}) {
  const envName = source && source.apiKeyEnv;
  if (!envName) {
    return false;
  }
  return availableApiKeyEnvSet(settings).has(envName) || !!process.env[envName];
}

async function syncApiKeyProviderAvailabilityForCurrentWorkspace() {
  const workspace = workspaceRoot();
  if (!workspace) {
    return false;
  }
  const config = settings();
  const configPath = resolveConfigPath(config.configPath, workspace);
  if (!fs.existsSync(configPath)) {
    return false;
  }
  try {
    return await syncApiKeyProviderAvailabilityToConfig(configPath);
  } catch (error) {
    output.appendLine(`Could not update API-key provider enablement: ${error.message}`);
    return false;
  }
}

async function syncApiKeyProviderAvailabilityToConfig(configPath) {
  const existingText = fs.existsSync(configPath) ? fs.readFileSync(configPath, "utf8") : "";
  if (!existingText) {
    return false;
  }
  const data = parseJsonConfigText(existingText).value;
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return false;
  }
  let changed = await applySavedApiKeyProviderAvailability(data);
  if (data.disable_non_free_models === true || (
    data.cloud_control_selection &&
    typeof data.cloud_control_selection === "object" &&
    data.cloud_control_selection.disable_non_free_models === true
  )) {
    const beforeStrictFree = stableConfigText(JSON.stringify(data));
    applyStrictFreeOnlyModeToConfig(data);
    changed = changed || beforeStrictFree !== stableConfigText(JSON.stringify(data));
  }
  if (!changed) {
    return false;
  }
  data.routes = Array.isArray(data.routes) ? data.routes : [];
  applyCloudRouteMode(data, configCloudRouteMode(data));
  const nextText = `${JSON.stringify(data, null, 2)}\n`;
  if (stableConfigText(existingText) === stableConfigText(nextText)) {
    return false;
  }
  const backupPath = backupConfigFile(configPath);
  ensureConfigDirectory(configPath);
  fs.writeFileSync(configPath, nextText, "utf8");
  output.appendLine(`Updated API-key provider enablement in ${configPath}.`);
  output.appendLine(`Original config was backed up to ${backupPath}.`);
  return true;
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

  const ollamaStatus = await ollamaDesktopStatus();
  if (!ollamaStatus.installed) {
    const result = await installOllamaDesktopCommand({ showAlreadyInstalled: false });
    panel.webview.postMessage({
      type: "modelPullStatus",
      running: false,
      text: result.message
    });
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
    const changed = applyLocalModelSelectionToConfig(configPath, source, {
      workspaceDir: generatedConfigWorkspaceDir(config.configPath, workspace),
      storageDir: generatedConfigStorageDir(config.configPath, workspace)
    });
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
          "Stop Agent Hub, start it again, or close the old terminal/process using port 8787.",
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
    agent_hub: agentHubRequestOptions(config, {
      classification_text: text,
      user_task: text
    }),
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
            ...(body.agent_hub && typeof body.agent_hub === "object" ? body.agent_hub : {}),
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
      response,
      autoFeedbackEnabled: !!config.automatedModelFeedback
    });
    if (config.automatedModelFeedback) {
      void autoSubmitModelFeedback(panel, {
        webviewRequestId: requestId,
        responseRequestId: response && (response.request_id || response.id),
        userText: text,
        assistantText: reply || "",
        response,
        config
      });
    }
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
      --subtle-border: color-mix(in srgb, var(--app-fg) 18%, transparent);
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
      --warn: var(--vscode-testing-iconQueued, #d29922);
      --error: var(--vscode-errorForeground, #f85149);
      --accent: color-mix(in srgb, var(--button) 76%, #2dd4bf 24%);
      --accent-soft: color-mix(in srgb, var(--accent) 16%, transparent);
      --panel: color-mix(in srgb, var(--surface) 88%, var(--app-fg) 12%);
      --shadow: 0 12px 28px rgba(0, 0, 0, 0.24);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--app-fg);
      background:
        linear-gradient(180deg, var(--accent-soft), transparent 220px),
        linear-gradient(135deg, color-mix(in srgb, var(--ok) 7%, transparent), transparent 42%),
        var(--app-bg);
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
      position: sticky;
      top: 0;
      z-index: 15;
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      background: color-mix(in srgb, var(--app-bg) 88%, transparent);
      backdrop-filter: blur(16px);
      box-shadow: 0 8px 22px rgba(0, 0, 0, 0.14);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .logo {
      width: 30px;
      height: 30px;
      border-radius: 8px;
      object-fit: cover;
      flex: 0 0 auto;
      box-shadow:
        0 0 0 1px var(--subtle-border),
        0 8px 18px color-mix(in srgb, var(--accent) 22%, transparent);
    }

    h1 {
      margin: 0;
      color: var(--app-fg);
      font-size: 15px;
      font-weight: 600;
    }

    .status {
      max-width: min(340px, 36vw);
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      background: color-mix(in srgb, var(--surface) 84%, transparent);
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
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--accent) 8%, var(--panel)), var(--panel));
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
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
      position: relative;
      display: grid;
      gap: 2px;
      padding: 9px 9px 9px 13px;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      background: color-mix(in srgb, var(--surface) 86%, transparent);
      transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
    }

    .model-row:first-child {
      border-top: 1px solid var(--subtle-border);
    }

    .model-row::before {
      content: "";
      position: absolute;
      inset: 9px auto 9px 0;
      width: 3px;
      border-radius: 0 999px 999px 0;
      background: var(--accent);
    }

    .model-row[data-status="active"],
    .model-row[data-status="routing"] {
      border-color: color-mix(in srgb, var(--ok) 34%, var(--subtle-border));
      background: color-mix(in srgb, var(--ok) 9%, var(--surface));
    }

    .model-row[data-status="active"]::before,
    .model-row[data-status="routing"]::before {
      background: var(--ok);
    }

    .model-row[data-status="failover"],
    .model-row[data-status="stopped"] {
      border-color: color-mix(in srgb, var(--warn) 36%, var(--subtle-border));
      background: color-mix(in srgb, var(--warn) 9%, var(--surface));
    }

    .model-row[data-status="failover"]::before,
    .model-row[data-status="stopped"]::before {
      background: var(--warn);
    }

    .model-row:hover {
      border-color: color-mix(in srgb, var(--accent) 38%, var(--subtle-border));
      transform: translateY(-1px);
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
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--accent) 8%, var(--panel)), var(--panel));
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
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
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 8px;
      background: color-mix(in srgb, var(--surface) 78%, transparent);
    }

    .settings-check {
      color: var(--app-fg);
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      padding: 5px 8px;
      background: color-mix(in srgb, var(--surface) 72%, transparent);
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
      padding: 18px 14px;
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
      border: 1px solid color-mix(in srgb, var(--accent) 38%, var(--border));
      border-radius: 8px;
      padding: 16px;
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--accent) 14%, var(--surface)), color-mix(in srgb, var(--ok) 9%, var(--surface)));
      box-shadow: var(--shadow);
    }

    .welcome[hidden] {
      display: none;
    }

    .welcome-title {
      color: var(--app-fg);
      font-size: 18px;
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
      min-height: 48px;
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 9px 10px;
      color: var(--secondary-fg);
      background: color-mix(in srgb, var(--secondary) 78%, var(--surface));
      text-align: left;
    }

    .message {
      display: grid;
      gap: 6px;
      max-width: 920px;
      margin: 0;
      animation: messageIn 160ms ease-out;
    }

    .message.user {
      margin-left: auto;
      justify-items: end;
    }

    .role {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .role::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }

    .assistant .role::before {
      background: var(--ok);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 16%, transparent);
    }

    .error .role::before {
      background: var(--error);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--error) 16%, transparent);
    }

    .bubble {
      border: 1px solid var(--subtle-border);
      border-radius: 8px;
      padding: 11px 13px;
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--app-fg);
      background: color-mix(in srgb, var(--surface) 88%, transparent);
      box-shadow: inset 0 1px 0 color-mix(in srgb, var(--app-fg) 7%, transparent);
    }

    .message.user .bubble {
      max-width: min(780px, 86vw);
    }

    .message.assistant .bubble {
      max-width: min(880px, 92vw);
    }

    .user .bubble {
      border-color: color-mix(in srgb, var(--accent) 42%, var(--subtle-border));
      background: color-mix(in srgb, var(--accent) 15%, var(--bubble));
    }

    .assistant .bubble {
      border-left: 3px solid var(--ok);
      background: color-mix(in srgb, var(--surface) 92%, var(--ok) 8%);
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

    .activity li::marker {
      color: var(--accent);
    }

    .feedback {
      display: flex;
      gap: 6px;
      margin-top: 6px;
      flex-wrap: wrap;
    }

    .feedback button {
      min-height: 24px;
      padding: 2px 8px;
      font-size: 12px;
    }

    .auto-feedback-status {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      max-width: 100%;
      margin-top: 6px;
      border: 1px solid var(--subtle-border);
      border-radius: 999px;
      padding: 4px 8px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.25;
      background: color-mix(in srgb, var(--surface) 84%, transparent);
    }

    .auto-feedback-status::before {
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 999px;
      background: currentColor;
      flex: 0 0 auto;
    }

    .auto-feedback-status[data-tone="ok"] {
      color: var(--ok);
      border-color: color-mix(in srgb, var(--ok) 42%, var(--subtle-border));
    }

    .auto-feedback-status[data-tone="warn"] {
      color: var(--warn);
      border-color: color-mix(in srgb, var(--warn) 42%, var(--subtle-border));
    }

    form {
      display: grid;
      gap: 8px;
      margin: 0 auto 12px;
      width: min(980px, calc(100% - 28px));
      padding: 10px;
      border-top: 1px solid var(--border);
      border: 1px solid var(--border);
      border-radius: 8px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface-alt) 90%, var(--accent) 10%), var(--surface-alt));
      box-shadow: var(--shadow);
    }

    textarea {
      width: 100%;
      min-height: 84px;
      max-height: 220px;
      resize: vertical;
      border: 1px solid var(--input-border);
      border-radius: 8px;
      padding: 10px 11px;
      color: var(--input-fg);
      background: color-mix(in srgb, var(--input) 92%, transparent);
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
      background: color-mix(in srgb, var(--input) 92%, transparent);
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
      background: color-mix(in srgb, var(--input) 92%, transparent);
      font: inherit;
    }

    button {
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 6px 10px;
      color: var(--button-fg);
      background: linear-gradient(135deg, var(--button), var(--accent));
      font: inherit;
      cursor: pointer;
      transition: background 120ms ease, border-color 120ms ease, transform 120ms ease, box-shadow 120ms ease;
    }

    button:hover {
      background: var(--button-hover);
      transform: translateY(-1px);
    }

    button.secondary {
      border-color: var(--subtle-border);
      color: var(--secondary-fg);
      background: color-mix(in srgb, var(--secondary) 86%, var(--surface));
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
      transform: none;
    }

    textarea:focus-visible,
    select:focus-visible,
    input:focus-visible,
    button:focus-visible {
      outline: 1px solid var(--accent);
      outline-offset: 2px;
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
      padding: 9px 10px;
      background: color-mix(in srgb, var(--surface) 78%, transparent);
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

    @keyframes messageIn {
      from {
        opacity: 0;
        transform: translateY(6px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @media (max-width: 720px) {
      .settings-grid,
      .key-grid,
      .prompt-pills {
        grid-template-columns: 1fr;
      }

      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .header-actions {
        width: 100%;
        justify-content: space-between;
        align-items: stretch;
      }

      .status,
      #modelsToggle {
        max-width: 100%;
      }

      .models-wrap,
      .settings-wrap {
        width: 100%;
      }

      .models-wrap > button,
      .settings-wrap > button {
        width: 100%;
      }

      form {
        width: calc(100% - 20px);
        margin-bottom: 10px;
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
                  <option value="codex-cli">Codex CLI without API key</option>
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
                <span>Codex CLI model</span>
                <input id="settingCodexCliModel" type="text" autocomplete="off">
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
              <label class="settings-check"><input id="settingAutomatedFeedback" type="checkbox"> Auto model feedback</label>
              <label class="settings-check"><input id="settingApiKeyModelsEnabled" type="checkbox"> Enable API-key models</label>
              <label class="settings-check"><input id="settingFreeCloudPresetsEnabled" type="checkbox"> Enable free cloud presets</label>
              <label class="settings-check"><input id="settingFreeOnly" type="checkbox"> Free-only routing</label>
              <label class="settings-check"><input id="settingDisableNonFreeModels" type="checkbox"> Disable non-free models</label>
              <label class="settings-check"><input id="settingLoadBalancing" type="checkbox"> Load balancing</label>
              <label class="settings-check"><input id="settingRoutingDetails" type="checkbox"> Routing details</label>
            </div>
            <div class="settings-actions">
              <button class="secondary" id="codexCliMode" type="button">Codex CLI Mode</button>
              <button class="secondary" id="freeOnlyModeSettings" type="button">Free Only Mode</button>
              <button class="secondary" id="maxTokenSave" type="button">Token Safe Mode</button>
              <button id="saveSettings" type="button">Save Settings</button>
              <button class="secondary" id="openSettings" type="button">Open VS Code Settings</button>
            </div>
            <div class="settings-message" id="settingsMessage"></div>
            <div class="settings-section">
              <div class="settings-section-title">Server</div>
              <div class="settings-actions">
                <button class="secondary" id="startServer" type="button">Start Agent Hub</button>
                <button class="secondary" id="restartServer" type="button">Restart</button>
                <button class="secondary" id="checkStatus" type="button">Status</button>
                <button class="secondary" id="openDashboard" type="button">Dashboard</button>
                <button class="secondary" id="pullModel" type="button">Choose Local Model</button>
                <button class="secondary" id="installOllamaDesktop" type="button">Install Ollama</button>
                <button class="secondary" id="openOutput" type="button">Open Logs</button>
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
          <div class="welcome-title">What do you want to do?</div>
          <div class="welcome-meta">Ask in plain language. Agent Hub can start itself, read workspace context, and ask before sensitive actions.</div>
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
      codexCliModel: document.getElementById("settingCodexCliModel"),
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
      disableNonFreeModels: document.getElementById("settingDisableNonFreeModels"),
      enableLoadBalancing: document.getElementById("settingLoadBalancing"),
      exposeRoutingDetails: document.getElementById("settingRoutingDetails"),
      allowShellTools: document.getElementById("settingAllowShellTools"),
      autoStart: document.getElementById("settingAutoStart"),
      automatedModelFeedback: document.getElementById("settingAutomatedFeedback")
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
      settingInputs.codexCliModel.value = next.codexCliModel || "";
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
      settingInputs.disableNonFreeModels.checked = !!next.disableNonFreeModels;
      settingInputs.enableLoadBalancing.checked = next.enableLoadBalancing !== false;
      settingInputs.exposeRoutingDetails.checked = !!next.exposeRoutingDetails;
      settingInputs.allowShellTools.checked = !!next.allowShellTools;
      settingInputs.autoStart.checked = !!next.autoStart;
      settingInputs.automatedModelFeedback.checked = !!next.automatedModelFeedback;
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
        codexCliModel: settingInputs.codexCliModel.value,
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
        disableNonFreeModels: settingInputs.disableNonFreeModels.checked,
        enableLoadBalancing: settingInputs.enableLoadBalancing.checked,
        exposeRoutingDetails: settingInputs.exposeRoutingDetails.checked,
        allowShellTools: settingInputs.allowShellTools.checked,
        autoStart: settingInputs.autoStart.checked,
        automatedModelFeedback: settingInputs.automatedModelFeedback.checked
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
      if (options.routingDetails && options.routingDetails.length) {
        item.append(detailsBlock("Routing", options.routingDetails));
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
      if (options.routingDetails && options.routingDetails.length) {
        turn.item.append(detailsBlock("Routing", options.routingDetails));
      }
      if (options.feedbackRequestId && !options.error) {
        turn.item.append(feedbackControls(options.feedbackRequestId));
      }
      if (options.autoFeedbackEnabled && options.requestId && !options.error) {
        turn.item.append(autoFeedbackStatusBadge(options.requestId));
      }
      transcript.scrollTop = transcript.scrollHeight;
    }

    function autoFeedbackStatusBadge(requestId) {
      const badge = document.createElement("div");
      badge.className = "auto-feedback-status";
      badge.dataset.requestId = requestId;
      badge.dataset.tone = "info";
      badge.textContent = "Auto feedback queued";
      return badge;
    }

    function updateAutoFeedbackStatus(message) {
      const requestId = message && message.requestId ? String(message.requestId) : "";
      const text = message && message.text ? String(message.text) : "";
      if (text) {
        status.textContent = text;
      }
      if (!requestId) {
        return;
      }
      const badge = Array.from(document.querySelectorAll(".auto-feedback-status"))
        .find((item) => item.dataset.requestId === requestId);
      if (!badge) {
        return;
      }
      badge.textContent = text || "Auto feedback updated";
      badge.dataset.tone = message.tone || "info";
    }

    function feedbackControls(agentHubRequestId) {
      const wrapper = document.createElement("div");
      wrapper.className = "feedback";
      const options = [
        ["Good", "up", "good"],
        ["Bad", "down", "bad"],
        ["Worked", "up", "worked"],
        ["Failed", "down", "failed"],
        ["Too expensive", "down", "too_expensive"],
        ["Wrong files", "down", "wrong_files"]
      ];
      const buttons = options.map(([label, rating, reason]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = reason.replaceAll("_", " ");
        button.addEventListener("click", () => send(rating, reason));
        return button;
      });
      const send = (rating, reason) => {
        for (const button of buttons) {
          button.disabled = true;
        }
        vscode.postMessage({
          type: "feedback",
          requestId: agentHubRequestId,
          rating,
          reason,
          workflowSuccess: rating === "up"
        });
      };
      wrapper.append(...buttons);
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

    function routingDetailsLines(response) {
      const lines = [];
      const payload = response && typeof response === "object" ? response : {};
      const agent = payload.agent && typeof payload.agent === "object" ? payload.agent : {};
      const provider = payload.provider || agent.provider || "";
      const model = payload.model || agent.model || "";
      const agentName = payload.agent && typeof payload.agent === "string" ? payload.agent : agent.name || "";
      if (provider || model || agentName) {
        lines.push("chosen provider/model: " + [provider || agentName || "provider", model].filter(Boolean).join(" / "));
      }
      const metadata = payload.agent_hub && typeof payload.agent_hub === "object" ? payload.agent_hub : {};
      const workflow = metadata.workflow && typeof metadata.workflow === "object" ? metadata.workflow : {};
      if (workflow.kind || workflow.context && workflow.context.workflow_pattern) {
        lines.push("workflow: " + [workflow.kind, workflow.context && workflow.context.workflow_pattern].filter(Boolean).join(" / "));
      }
      const usage = payload.usage && typeof payload.usage === "object" ? payload.usage : {};
      const inputTokens = numberValue(usage.prompt_tokens, usage.input_tokens, metadata.input_tokens);
      const outputTokens = numberValue(usage.completion_tokens, usage.output_tokens, metadata.output_tokens);
      if (inputTokens !== null || outputTokens !== null) {
        lines.push("tokens: " + [inputTokens !== null ? "in " + inputTokens : "", outputTokens !== null ? "out " + outputTokens : ""].filter(Boolean).join(", "));
      }
      const cost = numberValue(payload.estimated_cost_usd, usage.estimated_cost_usd, metadata.estimated_cost_usd);
      if (cost !== null) {
        lines.push("cost: $" + cost.toFixed(cost < 0.01 ? 6 : 4));
      }
      const latencyMs = numberValue(payload.latency_ms, metadata.latency_ms);
      if (latencyMs !== null) {
        lines.push("time: " + (latencyMs >= 1000 ? (latencyMs / 1000).toFixed(1) + "s" : Math.round(latencyMs) + "ms"));
      }
      const failover = Array.isArray(payload.failover) ? payload.failover : [];
      if (failover.length) {
        lines.push("fallback attempts: " + failover.length);
        for (const event of failover.slice(0, 4)) {
          lines.push("fallback: " + [event.agent || event.provider || "provider", event.model || "", event.reason || ""].filter(Boolean).join(" / "));
        }
      } else {
        lines.push("fallback attempts: 0");
      }
      return lines;
    }

    function numberValue() {
      for (const value of arguments) {
        const number = Number(value);
        if (Number.isFinite(number)) {
          return number;
        }
      }
      return null;
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
      if (metadata && Array.isArray(metadata.workflow_stages)) {
        for (const stage of metadata.workflow_stages) {
          if (!stage || typeof stage !== "object") {
            continue;
          }
          recordSessionModel({
            role: stage.role || stage.stage || "workflow",
            agent: stage.agent,
            provider: stage.provider,
            model: stage.model,
            status: "used",
            detail: stage.stage ? "stage: " + stage.stage : "workflow"
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
        item.dataset.status = "empty";
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
        item.dataset.status = row.status || "used";
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
        state.textContent = row.saved ? "Saved" : row.envPresent ? "Env" : "Not set";
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

    document.getElementById("codexCliMode").addEventListener("click", () => {
      controlMode.value = "cloud";
      settingInputs.cloudRouteMode.value = "codex-cli";
      settingInputs.apiKeyModelsEnabled.checked = false;
      settingInputs.freeCloudPresetsEnabled.checked = false;
      settingInputs.freeOnly.checked = true;
      settingInputs.disableNonFreeModels.checked = false;
      settingInputs.enableLoadBalancing.checked = false;
      settingInputs.maxTokens.value = String(${CODEX_CLI_OUTPUT_TOKENS});
      settingInputs.agentMaxSteps.value = String(${CODEX_CLI_AGENT_STEPS});
      settingInputs.groupPlanCandidates.value = "1";
      settingsMessage.textContent = "Turning on Codex CLI Mode...";
      vscode.postMessage({
        type: "enableCodexCliMode",
        settings: collectChatSettings()
      });
    });

    document.getElementById("freeOnlyModeSettings").addEventListener("click", () => {
      controlMode.value = "cloud";
      settingInputs.cloudRouteMode.value = "ollama-cloud";
      settingInputs.apiKeyModelsEnabled.checked = false;
      settingInputs.freeCloudPresetsEnabled.checked = true;
      settingInputs.freeOnly.checked = true;
      settingInputs.disableNonFreeModels.checked = true;
      settingInputs.enableLoadBalancing.checked = true;
      settingInputs.maxTokens.value = "";
      settingInputs.agentMaxSteps.value = String(${DEFAULT_AGENT_MAX_STEPS});
      settingInputs.groupPlanCandidates.value = "1";
      settingsMessage.textContent = "Turning on Free Only Mode...";
      vscode.postMessage({
        type: "enableFreeOnlyMode",
        settings: collectChatSettings()
      });
    });

    document.getElementById("maxTokenSave").addEventListener("click", () => {
      controlMode.value = "cloud";
      settingInputs.cloudRouteMode.value = "ollama-cloud";
      settingInputs.apiKeyModelsEnabled.checked = true;
      settingInputs.freeCloudPresetsEnabled.checked = true;
      settingInputs.freeOnly.checked = false;
      settingInputs.disableNonFreeModels.checked = false;
      settingInputs.enableLoadBalancing.checked = true;
      settingInputs.maxTokens.value = "";
      settingInputs.agentMaxSteps.value = String(${DEFAULT_AGENT_MAX_STEPS});
      settingInputs.groupPlanCandidates.value = "1";
      settingsMessage.textContent = "Turning on Token Safe Mode...";
      vscode.postMessage({
        type: "enableMaxTokenSave",
        settings: collectChatSettings()
      });
    });

    document.getElementById("openSettings").addEventListener("click", () => {
      vscode.postMessage({ type: "openSettings" });
    });

    document.getElementById("openOutput").addEventListener("click", () => {
      vscode.postMessage({ type: "openOutput" });
    });
    document.getElementById("openDashboard").addEventListener("click", () => {
      vscode.postMessage({ type: "openDashboard" });
    });
    document.getElementById("installOllamaDesktop").addEventListener("click", () => {
      status.textContent = "Opening Ollama download...";
      vscode.postMessage({ type: "installOllamaDesktop" });
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
      if (message.type === "autoFeedbackStatus") {
        updateAutoFeedbackStatus(message);
        return;
      }
      if (message.type === "chatResponse") {
        const turn = pending.get(message.requestId);
        pending.delete(message.requestId);
        updateSessionModelsFromResponse(message.response);
        finishLiveMessage(turn, message.text, {
          requestId: message.requestId,
          tools: message.tools || [],
          sources: message.sources || [],
          routingDetails: routingDetailsLines(message.response),
          feedbackRequestId: message.response && (message.response.id || message.response.request_id),
          autoFeedbackEnabled: !!message.autoFeedbackEnabled
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
    setServerLifecycleState("Stopped", "Start Agent Hub was cancelled.");
    return;
  }
  const configChanged = await ensureLocalConfig(config, workspace);

  if (await isServerOnline()) {
    if (configChanged && serverProcess) {
      output.appendLine("Agent Hub config was repaired; restarting extension-owned backend to load it.");
      setServerLifecycleState("Starting", "Restarting Agent Hub to load repaired config...");
      stopServerProcess();
      const offline = await waitForServerOffline(3000);
      if (!offline && (await isServerOnline())) {
        setServerLifecycleState("Error", "Agent Hub config was repaired, but the running backend did not stop.");
        vscode.window.showWarningMessage("Agent Hub config was repaired, but the running backend did not stop. Restart Agent Hub to use the repaired config.");
        return;
      }
    } else {
      setServerLifecycleState("Running", `Running at ${config.serverUrl}`);
      if (configChanged) {
        vscode.window.showWarningMessage("Agent Hub config was repaired. Restart Agent Hub to use the repaired config.");
      } else {
        vscode.window.showInformationMessage("Agent Hub is already running.");
      }
      return;
    }
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
  const config = settings();
  env.AGENT_HUB_TRUSTED_APPROVAL_TOKEN = config.approvalToken || runtimeApprovalToken;
  if (config.apiToken) {
    env.AGENT_HUB_API_TOKEN = config.apiToken;
  }
  await applySavedApiKeysToEnv(env);
  const backendRoot = backendSourceRoot(workspace);
  if (backendRoot) {
    prependEnvPath(env, "PYTHONPATH", backendRoot);
    env.PYTHONSAFEPATH = "1";
    env.PYTHONDONTWRITEBYTECODE = "1";
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
    "import agent_hub.cli",
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
  return runtimePolicy.splitCommandLine(value);
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
      summary: "Agent Hub needs Python 3.11 or newer.",
      detail: [
        `Python check failed: ${raw}`,
        "",
        "Install Python 3.11 or newer, then restart VS Code.",
        "If Python is already installed, set agentHub.pythonPath to auto, python, py -3.12, or a full python.exe path."
      ].join("\n")
    };
  }

  if (firstUsefulFailure || raw.includes("No module named agent_hub")) {
    const sourceLine = launch.backendRoot
      ? `Bundled backend source was found at: ${launch.backendRoot}`
      : "No bundled backend source was found in this extension package.";
    return {
      summary: "Agent Hub backend files are missing from this extension install.",
      detail: [
        "Backend check failed: No module named agent_hub",
        sourceLine,
        `Configured Python setting: ${config.pythonPath}`,
        "",
        "Install the latest VSIX again.",
        "If you are building from source, run: cd vscode-extension; npm run package"
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
  const workspaceDir = generatedConfigWorkspaceDir(config.configPath, workspace);
  const storageDir = generatedConfigStorageDir(config.configPath, workspace);
  if (fs.existsSync(configPath)) {
    return repairGeneratedLocalConfig(configPath, { workspaceDir, storageDir });
  }

  const sources = await detectLocalModelSources();
  const selectedSources = sources.length ? sources : fallbackLocalModelSources();
  const keyEnvs = await availableApiKeyEnvs();
  const data = localConfigForLocalModels(selectedSources, {
    workspaceDir,
    storageDir,
    cloudSettings: cloudSettingsWithAvailableApiKeys(cloudModelSettingsPayload(config), keyEnvs)
  });
  ensureConfigDirectory(configPath);
  fs.writeFileSync(configPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  output.appendLine(`Created Agent Hub config at ${configPath}.`);
  output.appendLine(`Configured cloud control agents: ${describeCloudSources(selectedSources)}`);
  output.appendLine(`Configured local control agents: ${describeLocalSources(selectedSources)}`);
  if (!sources.length) {
    output.appendLine("No local model server was detected yet; start LM Studio or Ollama and restart Agent Hub to repair the config to the loaded model.");
  }
  return true;
}

async function repairGeneratedLocalConfig(configPath, options = {}) {
  const workspaceDir = normalizeWorkspaceDirOption(options.workspaceDir);
  const storageDir = normalizeWorkspaceDirOption(options.storageDir);
  const keyEnvs = await availableApiKeyEnvs();
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
    fs.writeFileSync(configPath, `${JSON.stringify(localConfigForLocalModels(selectedSources, {
      workspaceDir,
      storageDir,
      cloudSettings: cloudSettingsWithAvailableApiKeys({}, keyEnvs)
    }), null, 2)}\n`, "utf8");
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
      cloudSettings: cloudSettingsWithAvailableApiKeys(cloudModelSettingsFromConfig(raw), keyEnvs),
      approvalMode: raw.approval_mode,
      workspaceDir,
      storageDir
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

  const statePathsChanged = applyGeneratedStoragePaths(raw, storageDir, workspaceDir);
  const keyAvailabilityChanged = applyApiKeyProviderAvailability(raw, keyEnvs);
  if (keyAvailabilityChanged && Array.isArray(raw.routes)) {
    applyCloudRouteMode(raw, configCloudRouteMode(raw));
  }
  if ((workspaceDir && raw.workspace_dir !== workspaceDir) || statePathsChanged || keyAvailabilityChanged) {
    const backupPath = backupConfigFile(configPath);
    if (workspaceDir) {
      raw.workspace_dir = workspaceDir;
    }
    fs.writeFileSync(configPath, `${JSON.stringify(raw, null, 2)}\n`, "utf8");
    output.appendLine(`Updated Agent Hub workspace/state paths for ${configPath}.`);
    output.appendLine(`Original config was backed up to ${backupPath}.`);
    return true;
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
    disableNonFreeModels: raw.disable_non_free_models === true,
    enableLoadBalancing: raw.enable_load_balancing !== false,
    exposeRoutingDetails: raw.expose_routing_details === true,
    codexModel: modelForAgent(raw, "codex", DEFAULT_CODEX_MODEL),
    codexCliModel: modelForAgent(raw, CODEX_CLI_AGENT_NAME, DEFAULT_CODEX_CLI_MODEL),
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

function applyLocalModelSelectionToConfig(configPath, source, options = {}) {
  const workspaceDir = normalizeWorkspaceDirOption(options.workspaceDir);
  const storageDir = normalizeWorkspaceDirOption(options.storageDir);
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
    data = localConfigForLocalModels([source], { workspaceDir, storageDir });
  } else {
    if (workspaceDir) {
      data.workspace_dir = workspaceDir;
    }
    applyGeneratedStoragePaths(data, storageDir, workspaceDir);
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
  ensureConfigDirectory(configPath);
  fs.writeFileSync(configPath, nextText, "utf8");
  output.appendLine(`Configured local control model: ${source.label} (${source.model}).`);
  return true;
}

async function saveCloudModelSettingsToConfig(configPath, cloudSettings, options = {}) {
  const workspaceDir = normalizeWorkspaceDirOption(options.workspaceDir);
  const storageDir = normalizeWorkspaceDirOption(options.storageDir);
  const keyEnvs = await availableApiKeyEnvs();
  const effectiveCloudSettings = cloudSettingsWithAvailableApiKeys(cloudSettings, keyEnvs);
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
      cloudRouteMode: effectiveCloudSettings.cloudRouteMode,
      cloudSettings: effectiveCloudSettings,
      workspaceDir,
      storageDir
    });
  }

  if (workspaceDir) {
    data.workspace_dir = workspaceDir;
  }
  applyGeneratedStoragePaths(data, storageDir, workspaceDir);
  data.agents = Array.isArray(data.agents) ? data.agents : [];
  data.routes = Array.isArray(data.routes) ? data.routes : [];
  data.free_only = effectiveCloudSettings.freeOnly !== false;
  data.disable_non_free_models = effectiveCloudSettings.disableNonFreeModels === true;
  data.enable_load_balancing = effectiveCloudSettings.enableLoadBalancing !== false;
  data.expose_routing_details = !!effectiveCloudSettings.exposeRoutingDetails;
  data.cloud_control_selection = {
    route_mode: normalizeCloudRouteMode(effectiveCloudSettings.cloudRouteMode),
    api_key_models_enabled: !!effectiveCloudSettings.apiKeyModelsEnabled,
    free_cloud_presets_enabled: !!effectiveCloudSettings.freeCloudPresetsEnabled,
    disable_non_free_models: effectiveCloudSettings.disableNonFreeModels === true
  };
  if (effectiveCloudSettings.maxTokenSaveMode) {
    applyMaxTokenSaveModeToConfig(data, effectiveCloudSettings);
  }
  if (effectiveCloudSettings.codexCliMode) {
    applyCodexCliModeToConfig(data, effectiveCloudSettings);
  }

  for (const source of ollamaCloudModelSources(effectiveCloudSettings)) {
    upsertAgentConfig(data.agents, ollamaCloudModelAgentConfig(source));
  }
  for (const source of cloudModelSources(effectiveCloudSettings)) {
    upsertAgentConfig(data.agents, cloudModelAgentConfig(source));
  }
  ensureDefaultOllamaCloudAgents(data);
  applyApiKeyProviderAvailability(data, keyEnvs);
  if (effectiveCloudSettings.disableNonFreeModels === true) {
    applyStrictFreeOnlyModeToConfig(data);
  }
  applyCloudRouteMode(data, data.cloud_control_selection.route_mode);

  const nextText = `${JSON.stringify(data, null, 2)}\n`;
  if (existingText && stableConfigText(existingText) === stableConfigText(nextText)) {
    return false;
  }
  if (existingText && !backedUpExisting) {
    const backupPath = backupConfigFile(configPath);
    output.appendLine(`Backed up Agent Hub config to ${backupPath}.`);
  }
  ensureConfigDirectory(configPath);
  fs.writeFileSync(configPath, nextText, "utf8");
  output.appendLine(`Configured cloud route mode: ${data.cloud_control_selection.route_mode}.`);
  return true;
}

function applyMaxTokenSaveModeToConfig(data, settings = {}) {
  const budget = cleanSettingInteger(
    settings.agentContextBudgetTokens,
    DEFAULT_AGENT_CONTEXT_BUDGET,
    1000,
    200000
  );
  data.agent_context_budget_tokens = budget;
  data.agent_context_compaction_enabled = true;
  data.context_mode = "balanced";
  data.free_only = false;
  data.enable_load_balancing = true;
  delete data.max_context_tokens;
  delete data.repo_context_max_files;
  delete data.repo_context_max_chars;
  data.routing = {
    ...(data.routing && typeof data.routing === "object" && !Array.isArray(data.routing)
      ? data.routing
      : {}),
    free_cloud_savings_mode: true,
    free_first: true,
    prefer_available_quota: true,
    max_tokens_mode: "auto",
    simple_cloud_exploration_enabled: true,
    simple_cloud_exploration_rate: 0.35,
    simple_cloud_min_relative_score: 0.82,
    simple_cloud_min_samples: 3
  };
  const compatibility = data.compatibility_mode && typeof data.compatibility_mode === "object" && !Array.isArray(data.compatibility_mode)
    ? { ...data.compatibility_mode }
    : {};
  delete compatibility.minimal_tool_schema;
  delete compatibility.reduced_repo_context;
  delete compatibility.max_context_tokens;
  delete compatibility.codex_cli_prompt_optimized;
  delete compatibility.codex_cli_prompt_budget_tokens;
  data.compatibility_mode = compatibility;
}

function applyCodexCliModeToConfig(data, settings = {}) {
  const budget = cleanSettingInteger(
    settings.agentContextBudgetTokens,
    CODEX_CLI_CONTEXT_BUDGET,
    800,
    200000
  );
  data.agent_context_budget_tokens = budget;
  data.agent_context_compaction_enabled = true;
  data.context_mode = "minimal";
  data.max_context_tokens = budget;
  data.repo_context_max_files = CODEX_CLI_REPO_FILES;
  data.repo_context_max_chars = CODEX_CLI_REPO_CHARS;
  data.free_only = true;
  data.enable_load_balancing = false;
  data.routing = {
    ...(data.routing && typeof data.routing === "object" && !Array.isArray(data.routing)
      ? data.routing
      : {}),
    free_cloud_savings_mode: false,
    free_first: true,
    prefer_available_quota: true,
    max_tokens_mode: "explicit",
    simple_cloud_exploration_enabled: false
  };
  data.compatibility_mode = {
    ...(data.compatibility_mode && typeof data.compatibility_mode === "object" && !Array.isArray(data.compatibility_mode)
      ? data.compatibility_mode
      : {}),
    minimal_tool_schema: true,
    reduced_repo_context: true,
    max_context_tokens: budget,
    codex_cli_prompt_optimized: true,
    codex_cli_prompt_budget_tokens: budget
  };
}

function applyStrictFreeOnlyModeToConfig(data) {
  data.free_only = true;
  data.disable_non_free_models = true;
  data.enable_load_balancing = true;
  data.cloud_control_selection = {
    ...(data.cloud_control_selection && typeof data.cloud_control_selection === "object" && !Array.isArray(data.cloud_control_selection)
      ? data.cloud_control_selection
      : {}),
    route_mode: "ollama-cloud",
    api_key_models_enabled: false,
    free_cloud_presets_enabled: true,
    disable_non_free_models: true
  };
  data.routing = {
    ...(data.routing && typeof data.routing === "object" && !Array.isArray(data.routing)
      ? data.routing
      : {}),
    free_first: true,
    token_saver_enabled: false,
    prefer_available_quota: true
  };
  if (!Array.isArray(data.agents)) {
    return;
  }
  for (const agent of data.agents) {
    if (!agent || typeof agent !== "object" || strictFreeAgentConfigAllowed(agent)) {
      continue;
    }
    agent.enabled = false;
    agent.free = false;
  }
}

async function applySavedApiKeyProviderAvailability(data) {
  return applyApiKeyProviderAvailability(data, await availableApiKeyEnvs());
}

function applyApiKeyProviderAvailability(data, keyEnvs) {
  if (!data || typeof data !== "object" || !Array.isArray(data.agents)) {
    return false;
  }
  const strictFree = data.disable_non_free_models === true || (
    data.cloud_control_selection &&
    typeof data.cloud_control_selection === "object" &&
    data.cloud_control_selection.disable_non_free_models === true
  );
  let changed = false;
  for (const agent of data.agents) {
    if (!agent || typeof agent !== "object" || !isManagedApiKeyProviderAgent(agent)) {
      continue;
    }
    const desired = strictFree && !strictFreeAgentConfigAllowed(agent)
      ? false
      : agentHasAvailableApiKey(agent, keyEnvs);
    if (agent.enabled !== desired) {
      agent.enabled = desired;
      changed = true;
    }
  }
  return changed;
}

function strictFreeAgentConfigAllowed(agent) {
  if (!agent || typeof agent !== "object") {
    return false;
  }
  const name = String(agent.name || "").toLowerCase();
  const provider = normalizeProviderName(String(agent.provider || ""));
  const providerType = String(agent.provider_type || agent.provider || "").toLowerCase();
  if (["codex", "codex-cli", "chatgpt", "claude", "gemini"].includes(name)) {
    return false;
  }
  if (["openai", "anthropic", "gemini", "codex-cli"].includes(provider)) {
    return false;
  }
  if (["openai", "anthropic", "gemini", "codex-cli"].includes(providerType)) {
    return false;
  }
  if (["echo", "local-research"].includes(provider)) {
    return true;
  }
  if (providerType === "ollama-cloud" || OLLAMA_CLOUD_AGENT_NAMES.includes(name)) {
    return true;
  }
  if (LOCAL_API_KEY_OPTIONAL_PROVIDER_TYPES.has(providerType) || LOCAL_API_KEY_OPTIONAL_PROVIDER_TYPES.has(provider)) {
    return true;
  }
  if (provider === "openai-compatible" && isLocalOrPrivateUrl(agent.base_url)) {
    return true;
  }
  return agent.free === true;
}

function normalizeProviderName(value) {
  const provider = String(value || "").toLowerCase();
  if (["codex", "chatgpt", "openai-chat", "gpt"].includes(provider)) {
    return "openai";
  }
  if (["claude", "anthropic-messages"].includes(provider)) {
    return "anthropic";
  }
  if (["google", "google-gemini", "generative-language"].includes(provider)) {
    return "gemini";
  }
  if (["codex_cli", "codex-login"].includes(provider)) {
    return "codex-cli";
  }
  return provider;
}

function isManagedApiKeyProviderAgent(agent) {
  if (!agent || typeof agent !== "object") {
    return false;
  }
  if (!agent.api_key_env && !agent.api_key) {
    return false;
  }
  const provider = String(agent.provider || "").toLowerCase();
  const providerType = String(agent.provider_type || agent.provider || "").toLowerCase();
  if (provider === "openai-compatible" && isLocalOrPrivateUrl(agent.base_url)) {
    return false;
  }
  if (LOCAL_API_KEY_OPTIONAL_PROVIDER_TYPES.has(providerType)) {
    return false;
  }
  if (["openai", "anthropic", "gemini"].includes(provider)) {
    return true;
  }
  if (CLOUD_PROVIDER_TYPES.has(providerType)) {
    return true;
  }
  if (provider === "openai-compatible") {
    return !!agent.base_url;
  }
  return false;
}

function agentHasAvailableApiKey(agent, keyEnvs) {
  if (agent && typeof agent.api_key === "string" && agent.api_key.trim()) {
    return true;
  }
  const envName = agent && typeof agent.api_key_env === "string" ? agent.api_key_env.trim() : "";
  if (!envName) {
    return false;
  }
  return (keyEnvs instanceof Set && keyEnvs.has(envName)) || !!process.env[envName];
}

function isLocalOrPrivateUrl(value) {
  if (!value || typeof value !== "string") {
    return false;
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch (_error) {
    return false;
  }
  const host = String(parsed.hostname || "").toLowerCase();
  if (!host) {
    return false;
  }
  if (["localhost", "host.docker.internal", "0.0.0.0", "127.0.0.1", "::1"].includes(host)) {
    return true;
  }
  return (
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(host) ||
    /^169\.254\./.test(host)
  );
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
  const routeMode = normalizeCloudRouteMode(mode);
  const codexCliAgents = codexCliAgentNames(data);
  const ordered = routeMode === "codex-cli"
    ? [...codexCliAgents, ...ollamaCloudAgents, ...hostedAgents.filter((name) => name !== CODEX_CLI_AGENT_NAME)]
    : routeMode === "api-key"
    ? [...hostedAgents, ...ollamaCloudAgents]
    : [...ollamaCloudAgents, ...hostedAgents];
  return uniqueAgentNames(ordered);
}

function codexCliAgentNames(data) {
  const agents = Array.isArray(data && data.agents) ? data.agents : [];
  return agents.some((agent) => (
    agent &&
    typeof agent === "object" &&
    agent.name === CODEX_CLI_AGENT_NAME &&
    agent.enabled === true
  ))
    ? [CODEX_CLI_AGENT_NAME]
    : [];
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
        agent.name === CODEX_CLI_AGENT_NAME ||
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
  if (firstAgent === CODEX_CLI_AGENT_NAME) {
    return "codex-cli";
  }
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

function generatedConfigApprovalMode(value) {
  const hasExplicitValue = value !== undefined && value !== null && String(value).trim() !== "";
  if (!hasExplicitValue) {
    return "auto";
  }
  const mode = normalizeApprovalMode(value);
  return mode === "ask" ? "auto" : mode;
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
    cloudRouteMode === "codex-cli"
      ? [
        ...cloudAgents.filter((name) => name === CODEX_CLI_AGENT_NAME),
        ...ollamaCloudAgents,
        ...cloudAgents.filter((name) => name !== CODEX_CLI_AGENT_NAME)
      ]
      : cloudRouteMode === "api-key"
      ? [...cloudAgents, ...ollamaCloudAgents]
      : [...ollamaCloudAgents, ...cloudAgents]
  );
  const hybridAgents = cloudRouteAgents;
  const storagePaths = generatedStoragePaths(options.storageDir);
  return {
    host: "127.0.0.1",
    port: 8787,
    state_dir: storagePaths.stateDir,
    inbox_dir: storagePaths.inboxDir,
    outbox_dir: storagePaths.outboxDir,
    archive_dir: storagePaths.archiveDir,
    workspace_dir: normalizeWorkspaceDirOption(options.workspaceDir) || ".",
    agent_max_steps: 8,
    agent_context_budget_tokens: 32000,
    agent_context_compaction_enabled: true,
    context_mode: "balanced",
    cline_compatibility_mode: true,
    tool_loop_enabled_for_cline: false,
    allow_shell_tools: true,
    approval_mode: generatedConfigApprovalMode(options.approvalMode),
    free_only: options.cloudSettings?.freeOnly !== false,
    disable_non_free_models: options.cloudSettings?.disableNonFreeModels === true,
    enable_load_balancing: options.cloudSettings?.enableLoadBalancing !== false,
    include_raw_responses: false,
    expose_routing_details: options.cloudSettings?.exposeRoutingDetails === true,
    debug_echo_enabled: false,
    cloud_control_selection: {
      route_mode: cloudRouteMode,
      api_key_models_enabled: !!options.cloudSettings?.apiKeyModelsEnabled,
      free_cloud_presets_enabled: !!options.cloudSettings?.freeCloudPresetsEnabled,
      disable_non_free_models: options.cloudSettings?.disableNonFreeModels === true
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
  const routeMode = normalizeCloudRouteMode(settings.cloudRouteMode);
  const codexCli = {
    name: CODEX_CLI_AGENT_NAME,
    label: "Codex CLI",
    provider: "codex-cli",
    providerType: "codex-cli",
    enabled: settings.disableNonFreeModels === true ? false : routeMode === "codex-cli" || !!settings.codexCliEnabled,
    free: settings.disableNonFreeModels === true ? false : routeMode === "codex-cli",
    model: cleanSettingString(settings.codexCliModel, process.env.AGENT_HUB_CODEX_CLI_MODEL || DEFAULT_CODEX_CLI_MODEL),
    contextWindow: 400000,
    timeoutSeconds: 300,
    cooldownSeconds: 30,
    maxTokens: routeMode === "codex-cli" ? CODEX_CLI_OUTPUT_TOKENS : undefined,
    priority: 90,
    codingScore: 0.9,
    reasoningScore: 0.9,
    speedScore: 0.55,
    supportsTools: false,
    supportsJson: true,
    supportsStreaming: false,
    supportsVision: true,
    supportsFunctionCalling: false
  };
  const hosted = [
    {
      name: "codex",
      label: "Codex",
      provider: "openai",
      enabled: false,
      free: settings.disableNonFreeModels || settings.maxTokenSaveMode ? false : true,
      model: cleanSettingString(settings.codexModel, process.env.AGENT_HUB_CODEX_MODEL || process.env.AGENT_HUB_OPENAI_MODEL || DEFAULT_CODEX_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_CODEX_API_KEY_ENV || "OPENAI_API_KEY",
      baseUrl: process.env.AGENT_HUB_CODEX_BASE_URL || process.env.OPENAI_BASE_URL || "",
      contextWindow: 128000
    },
    {
      name: "claude",
      label: "Claude",
      provider: "anthropic",
      enabled: false,
      free: settings.disableNonFreeModels || settings.maxTokenSaveMode ? false : true,
      model: cleanSettingString(settings.claudeModel, process.env.AGENT_HUB_CLAUDE_MODEL || DEFAULT_CLAUDE_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_CLAUDE_API_KEY_ENV || "ANTHROPIC_API_KEY",
      baseUrl: process.env.AGENT_HUB_CLAUDE_BASE_URL || "",
      contextWindow: 200000
    },
    {
      name: "gemini",
      label: "Gemini",
      provider: "gemini",
      enabled: false,
      free: settings.disableNonFreeModels || settings.maxTokenSaveMode ? false : true,
      model: cleanSettingString(settings.geminiModel, process.env.AGENT_HUB_GEMINI_MODEL || DEFAULT_GEMINI_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_GEMINI_API_KEY_ENV || "GEMINI_API_KEY",
      baseUrl: process.env.AGENT_HUB_GEMINI_BASE_URL || "",
      contextWindow: 1000000
    },
    {
      name: "chatgpt",
      label: "ChatGPT",
      provider: "openai",
      enabled: false,
      free: settings.disableNonFreeModels || settings.maxTokenSaveMode ? false : true,
      model: cleanSettingString(settings.chatgptModel, process.env.AGENT_HUB_CHATGPT_MODEL || process.env.AGENT_HUB_OPENAI_MODEL || DEFAULT_CHATGPT_MODEL),
      apiKeyEnv: process.env.AGENT_HUB_CHATGPT_API_KEY_ENV || "OPENAI_API_KEY",
      baseUrl: process.env.AGENT_HUB_CHATGPT_BASE_URL || process.env.OPENAI_BASE_URL || "",
      contextWindow: 128000
    }
  ];
  const hostedWithAvailability = hosted.map((source) => ({
    ...source,
    enabled: apiKeySourceEnabled(source, !!settings.apiKeyModelsEnabled, settings)
  }));
  return [codexCli, ...hostedWithAvailability, ...freeCloudPresetSources(settings)];
}

function freeCloudPresetSources(settings = {}) {
  const familyEnabled = !!settings.freeCloudPresetsEnabled;
  const maxTokens = settings.maxTokenSaveMode ? MAX_TOKEN_SAVE_OUTPUT_TOKENS : undefined;
  return [
    {
      name: "groq-qwen3-32b",
      label: "Groq Qwen3 32B",
      provider: "openai-compatible",
      providerType: "groq",
      enabled: false,
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
      enabled: false,
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
      enabled: false,
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
      enabled: false,
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
      enabled: false,
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
      enabled: false,
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
      enabled: false,
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
      enabled: false,
      model: cleanSettingString(settings.cloudflareModel, DEFAULT_CLOUDFLARE_MODEL),
      apiKeyEnv: "CLOUDFLARE_API_TOKEN",
      baseUrl: "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/ai/v1",
      contextWindow: 8192,
      priority: 40,
      codingScore: 0.45,
      reasoningScore: 0.55,
      speedScore: 0.8
    }
  ].map((source) => ({
    ...source,
    enabled: apiKeySourceEnabled(source, familyEnabled, settings),
    maxTokens
  }));
}

function apiKeySourceEnabled(source, familyEnabled, settings = {}) {
  if (settings.disableNonFreeModels === true && !strictFreeSourceAllowed(source)) {
    return false;
  }
  if (!source || !source.apiKeyEnv) {
    return !!familyEnabled;
  }
  return !!familyEnabled && sourceHasAvailableApiKey(source, settings);
}

function strictFreeSourceAllowed(source) {
  if (!source || typeof source !== "object") {
    return false;
  }
  return strictFreeAgentConfigAllowed({
    name: source.name,
    provider: source.provider,
    provider_type: source.providerType,
    base_url: source.baseUrl,
    free: source.free !== false
  });
}

function ollamaCloudModelSources(settings = {}) {
  const maxTokens = settings.maxTokenSaveMode ? MAX_TOKEN_SAVE_OUTPUT_TOKENS : undefined;
  return OLLAMA_CLOUD_MODELS.map((source) => ({
    ...source,
    baseUrl: OLLAMA_BASE_URL,
    contextWindow: 128000,
    maxTokens,
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
    max_tokens: source.maxTokens,
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
    free: source.free !== false,
    api_key_env: source.apiKeyEnv,
    context_window: source.contextWindow,
    timeout_seconds: source.timeoutSeconds || 60,
    max_tokens: source.maxTokens,
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
    .map((source) => source.apiKeyEnv
      ? `${source.label} (${source.model}, ${source.apiKeyEnv}, disabled until enabled in settings)`
      : `${source.label} (${source.model}, no API key, disabled until enabled in settings)`);
  return [...ollamaCloud, ...apiKey]
    .join(", ");
}

async function detectLmStudioModels() {
  try {
    return await detectOpenAiCompatibleModels(LM_STUDIO_BASE_URL);
  } catch (error) {
    if (!isLocalServerOfflineError(error)) {
      output.appendLine(`Could not detect LM Studio models: ${formatLocalServerError(error)}`);
    }
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
    return "Ollama was not found on PATH. Install Ollama Desktop, restart VS Code, then run the pull again.";
  }
  return `Could not run Ollama: ${raw}`;
}

function formatLocalServerError(error) {
  const raw = error && error.message ? String(error.message) : String(error || "Unknown error");
  if (isLocalServerOfflineError(error)) {
    return "server is not running";
  }
  return raw;
}

function isLocalServerOfflineError(error) {
  const raw = error && error.message ? String(error.message) : String(error || "");
  return raw.includes("ECONNREFUSED") || raw.includes("connect ETIMEDOUT");
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

async function nodeRuntimeStatus() {
  try {
    const { stdout, stderr } = await execFile("node", ["-p", "process.versions.node"], {
      shell: process.platform === "win32",
      timeout: 5000
    });
    const version = String(stdout || stderr || "").trim().split(/\r?\n/).find(Boolean) || "";
    const major = Number.parseInt(version.split(".")[0], 10);
    const ok = Number.isFinite(major) && major >= 20;
    return {
      ok,
      version,
      detail: ok
        ? `Node.js ${version}`
        : version
          ? `Node.js ${version} is older than 20`
          : "Node.js 20+ not detected"
    };
  } catch (_error) {
    return {
      ok: false,
      version: "",
      detail: "Node.js 20+ not detected"
    };
  }
}

async function npmRuntimeStatus() {
  try {
    const { stdout, stderr } = await execFile("npm", ["--version"], {
      shell: process.platform === "win32",
      timeout: 5000
    });
    const version = String(stdout || stderr || "").trim().split(/\r?\n/).find(Boolean) || "";
    return {
      ok: !!version,
      version,
      detail: version ? `npm ${version}` : "npm not detected"
    };
  } catch (_error) {
    return {
      ok: false,
      version: "",
      detail: "npm not detected"
    };
  }
}

async function wingetStatus() {
  if (process.platform !== "win32") {
    return { installed: false, version: "" };
  }
  try {
    const { stdout, stderr } = await execFile("winget", ["--version"], {
      shell: true,
      timeout: 5000
    });
    return {
      installed: true,
      version: String(stdout || stderr || "").trim().split(/\r?\n/).find(Boolean) || ""
    };
  } catch (_error) {
    return { installed: false, version: "" };
  }
}

async function codexCliStatus() {
  try {
    const { stdout, stderr } = await execFile("codex", ["--version"], {
      shell: process.platform === "win32",
      timeout: 5000
    });
    const version = String(stdout || stderr || "").trim().split(/\r?\n/).find(Boolean) || "";
    return {
      installed: true,
      version
    };
  } catch (_error) {
    return {
      installed: false,
      version: ""
    };
  }
}

async function ollamaDesktopStatus() {
  try {
    const { stdout, stderr } = await execFile("ollama", ["--version"], {
      shell: process.platform === "win32",
      timeout: 5000
    });
    const version = String(stdout || stderr || "").trim().split(/\r?\n/).find(Boolean) || "";
    return {
      installed: true,
      version
    };
  } catch (_error) {
    return {
      installed: false,
      version: ""
    };
  }
}

function openCodexCliTerminal(command) {
  openSetupTerminal("Agent Hub Codex CLI", command);
}

function openSetupTerminal(name, command) {
  const options = {
    name
  };
  const workspace = workspaceRoot();
  if (workspace) {
    options.cwd = workspace;
  }
  if (process.platform === "win32") {
    options.shellPath = "powershell.exe";
  }
  const terminal = vscode.window.createTerminal(options);
  terminal.show();
  terminal.sendText(command, true);
}

function codexCliInstallTerminalCommand() {
  return process.platform === "win32"
    ? `npm.cmd install -g ${CODEX_CLI_NPM_PACKAGE}; if ($LASTEXITCODE -eq 0) { codex.cmd login }`
    : `npm install -g ${CODEX_CLI_NPM_PACKAGE} && codex login`;
}

function codexCliLoginTerminalCommand() {
  return process.platform === "win32" ? "codex.cmd login" : "codex login";
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
    const agents = Array.isArray(health.agents) ? health.agents.length : 0;
    setServerLifecycleState("Running", `Running at ${settings().serverUrl}`);
    vscode.window.showInformationMessage(`Agent Hub is ready. ${agents} model route(s) available.`);
    output.appendLine(JSON.stringify(health, null, 2));
  } catch (error) {
    setServerLifecycleState(serverProcess ? "Error" : "Stopped", `Agent Hub is offline or unhealthy: ${error.message}`);
    vscode.window.showWarningMessage(`Agent Hub is offline or unhealthy: ${error.message}`);
  }
}

async function runPersonalBenchmark(options = {}) {
  const workspace = workspaceRoot();
  if (!workspace) {
    vscode.window.showWarningMessage("Open a workspace folder before running a personal Agent-Hub benchmark.");
    return { ok: false, cancelled: true };
  }
  const config = settings();
  const route = config.route || "coding";
  const reportStatus = personalBenchmarkReportStatus(config, workspace);
  const reportDir = reportStatus.reportDir;
  if (!(await requestPermission({
    category: "cloud_provider",
    description: "Agent Hub wants to run the shipped benchmark corpus against your configured baseline and routed models.",
    resource: reportDir || workspace,
    risk: "medium",
    detail: [
      `Route: ${route}.`,
      `Tasks: ${PERSONAL_BENCHMARK_LIMIT}.`,
      "This may call configured local or cloud providers and may consume quota or credits.",
      "Reports are written locally as benchmark-report.json and benchmark-report.md."
    ].join(" ")
  }))) {
    vscode.window.showWarningMessage("Personal benchmark cancelled.");
    return { ok: false, cancelled: true };
  }

  if (!(await ensureServerReady())) {
    vscode.window.showErrorMessage("Agent Hub is not ready. Start the backend or open the Agent Hub output.");
    return { ok: false, cancelled: false };
  }

  const launch = await serverLaunchEnvironment(workspace);
  if (!(await ensurePythonBackend(config, workspace, launch))) {
    return { ok: false, cancelled: false };
  }
  if (reportDir) {
    fs.mkdirSync(reportDir, { recursive: true });
  }
  const configPath = resolveConfigPath(config.configPath, workspace);
  const args = [
    ...launch.pythonArgs,
    "-m",
    "agent_hub",
    "--config",
    configPath,
    "benchmark",
    "run",
    "--route",
    route,
    "--limit",
    String(PERSONAL_BENCHMARK_LIMIT),
    "--json"
  ];
  if (reportDir) {
    args.push("--output-dir", reportDir);
  }
  output.appendLine("");
  output.appendLine("Agent Hub personal benchmark");
  output.appendLine(formatCliCommandForLog(launch.pythonCommand, args));
  const started = Date.now();
  try {
    const { stdout, stderr } = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Agent Hub: Running personal benchmark",
        cancellable: false
      },
      () => execFile(launch.pythonCommand, args, {
        cwd: workspace,
        env: launch.env,
        timeout: 60 * 60 * 1000,
        maxBuffer: 32 * 1024 * 1024
      })
    );
    if (stderr && String(stderr).trim()) {
      output.appendLine(String(stderr).trim());
    }
    output.appendLine(String(stdout || "").trim());
    const report = parseJsonObjectFromText(stdout);
    const elapsedSeconds = ((Date.now() - started) / 1000).toFixed(1);
    await openBenchmarkReport(report, reportStatus);
    openBenchmarkShareCard(report);
    const message = `${formatBenchmarkCompletionMessage(report)} Finished in ${elapsedSeconds}s.`;
    const next = await vscode.window.showInformationMessage(
      message,
      "Explain Routing",
      "README Proof",
      "Benchmark Dashboard"
    );
    if (next === "Explain Routing") {
      await explainRouteCommand({ prompt: PERSONAL_BENCHMARK_PROMPT });
    } else if (next === "README Proof") {
      await openReadmeProofSection();
    } else if (next === "Benchmark Dashboard") {
      await openAgentHubDashboard("/dashboard/benchmarks");
    }
    refreshSidebar();
    return { ok: true, report };
  } catch (error) {
    output.appendLine(`Personal benchmark failed: ${error.message}`);
    if (error.stderr) {
      output.appendLine(String(error.stderr));
    }
    output.show(true);
    vscode.window.showErrorMessage(`Personal benchmark failed: ${error.message}`);
    return { ok: false, cancelled: false };
  }
}

async function openLatestBenchmarkShareCard() {
  const status = personalBenchmarkReportStatus(settings(), workspaceRoot());
  if (!status.jsonPath || !fs.existsSync(status.jsonPath)) {
    vscode.window.showWarningMessage("No personal benchmark report found yet. Run Agent Hub: Run Personal Benchmark first.");
    return;
  }
  try {
    const report = JSON.parse(fs.readFileSync(status.jsonPath, "utf8"));
    openBenchmarkShareCard(report);
  } catch (error) {
    vscode.window.showErrorMessage(`Could not open benchmark share card: ${error.message}`);
  }
}

function openBenchmarkShareCard(report) {
  const card = benchmarkShareCard(report);
  if (!benchmarkSharePanel) {
    benchmarkSharePanel = vscode.window.createWebviewPanel(
      "agentHubBenchmarkShare",
      "Agent Hub Benchmark Card",
      vscode.ViewColumn.Beside,
      { enableScripts: true }
    );
    benchmarkSharePanel.onDidDispose(() => {
      benchmarkSharePanel = null;
    });
    benchmarkSharePanel.webview.onDidReceiveMessage((message) => {
      if (!message || message.type !== "copyShareVariant") {
        return;
      }
      const key = String(message.variant || "");
      const text = benchmarkSharePanel && benchmarkSharePanel.shareVariants
        ? benchmarkSharePanel.shareVariants[key]
        : "";
      if (text) {
        vscode.env.clipboard.writeText(text);
        vscode.window.showInformationMessage(`Copied ${shareVariantLabel(key)} benchmark card.`);
      }
    });
  }
  benchmarkSharePanel.shareVariants = card.variants;
  benchmarkSharePanel.webview.html = benchmarkShareCardHtml(card);
  benchmarkSharePanel.reveal(vscode.ViewColumn.Beside);
}

function benchmarkShareCard(report) {
  const comparison = report && report.comparison && typeof report.comparison === "object"
    ? report.comparison
    : {};
  const baseline = report && report.baseline && typeof report.baseline === "object"
    ? report.baseline
    : {};
  const baselineLabel = baseline.model || baseline.agent || baseline.provider || "User default";
  const tasks = Number(report && report.task_count) || (Array.isArray(report && report.results) ? report.results.length : 0);
  const metrics = {
    cost: formatPercentMetric(comparison.cost_reduction),
    latency: formatPercentMetric(comparison.latency_reduction),
    success: formatSignedPointMetric(comparison.success_delta)
  };
  const markdown = [
    "# My Agent-Hub Benchmark",
    "",
    `Baseline: ${baselineLabel}`,
    `Tasks: ${tasks}`,
    "",
    `Cost Reduction: ${metrics.cost}`,
    `Latency Reduction: ${metrics.latency}`,
    `Success Rate: ${metrics.success}`,
    "",
    "Agent-Hub ships the benchmark corpus so I can verify routing, cost, latency, and success locally."
  ].join("\n");
  const reddit = [
    "I ran Agent-Hub's local benchmark corpus.",
    "",
    `Baseline: ${baselineLabel}`,
    `Tasks: ${tasks}`,
    `Cost Reduction: ${metrics.cost}`,
    `Latency Reduction: ${metrics.latency}`,
    `Success Rate: ${metrics.success}`,
    "",
    "The useful part: the benchmark corpus and reports are local/reproducible, not just vendor claims."
  ].join("\n");
  const x = (
    `I ran Agent-Hub's local benchmark corpus vs ${baselineLabel}: ` +
    `${metrics.cost} cost, ${metrics.latency} latency, ${metrics.success} success across ${tasks} tasks. ` +
    "Reproducible proof reports ship with the tool."
  ).slice(0, 280);
  const github = [
    "## Agent-Hub Benchmark Result",
    "",
    `- Baseline: ${baselineLabel}`,
    `- Tasks: ${tasks}`,
    `- Cost Reduction: ${metrics.cost}`,
    `- Latency Reduction: ${metrics.latency}`,
    `- Success Rate: ${metrics.success}`,
    "",
    "The report was generated locally from the bundled benchmark corpus."
  ].join("\n");
  return {
    baseline: baselineLabel,
    tasks,
    metrics,
    variants: {
      markdown,
      reddit,
      x,
      github
    }
  };
}

function benchmarkShareCardHtml(card) {
  const nonce = getNonce();
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Hub Benchmark Card</title>
  <style nonce="${nonce}">
    body {
      margin: 0;
      padding: 20px;
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      font-family: var(--vscode-font-family);
    }
    .card {
      max-width: 680px;
      border: 1px solid var(--vscode-panel-border);
      border-radius: 8px;
      padding: 18px;
      background: var(--vscode-sideBar-background);
    }
    h1 {
      margin: 0 0 12px;
      font-size: 22px;
      line-height: 1.2;
    }
    .meta {
      color: var(--vscode-descriptionForeground);
      margin-bottom: 18px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }
    .metric {
      border: 1px solid var(--vscode-panel-border);
      border-radius: 8px;
      padding: 12px;
      background: var(--vscode-editor-inactiveSelectionBackground);
    }
    .metric span {
      display: block;
      color: var(--vscode-descriptionForeground);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .metric strong {
      font-size: 22px;
      line-height: 1.1;
    }
    .buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    button {
      border: 0;
      border-radius: 4px;
      padding: 8px 10px;
      color: var(--vscode-button-foreground);
      background: var(--vscode-button-background);
      cursor: pointer;
    }
    button:hover {
      background: var(--vscode-button-hoverBackground);
    }
    pre {
      white-space: pre-wrap;
      border: 1px solid var(--vscode-panel-border);
      border-radius: 8px;
      padding: 12px;
      color: var(--vscode-editor-foreground);
      background: var(--vscode-textCodeBlock-background);
    }
  </style>
</head>
<body>
  <main class="card">
    <h1>My Agent-Hub Benchmark</h1>
    <div class="meta">Baseline: ${escapeHtml(card.baseline)} · Tasks: ${escapeHtml(card.tasks)}</div>
    <section class="metrics">
      <div class="metric"><span>Cost Reduction</span><strong>${escapeHtml(card.metrics.cost)}</strong></div>
      <div class="metric"><span>Latency Reduction</span><strong>${escapeHtml(card.metrics.latency)}</strong></div>
      <div class="metric"><span>Success Rate</span><strong>${escapeHtml(card.metrics.success)}</strong></div>
    </section>
    <div class="buttons">
      <button data-copy="markdown">Copy Markdown</button>
      <button data-copy="reddit">Copy Reddit Version</button>
      <button data-copy="x">Copy X Version</button>
      <button data-copy="github">Copy GitHub Discussion Version</button>
    </div>
    <pre>${escapeHtml(card.variants.markdown)}</pre>
  </main>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.querySelectorAll("button[data-copy]").forEach((button) => {
      button.addEventListener("click", () => {
        vscode.postMessage({ type: "copyShareVariant", variant: button.dataset.copy });
      });
    });
  </script>
</body>
</html>`;
}

function shareVariantLabel(key) {
  if (key === "x") {
    return "X";
  }
  if (key === "github") {
    return "GitHub Discussion";
  }
  return key ? key.charAt(0).toUpperCase() + key.slice(1) : "benchmark";
}

async function explainRouteCommand(options = {}) {
  const workspace = workspaceRoot();
  if (!workspace) {
    vscode.window.showWarningMessage("Open a workspace folder before explaining an Agent-Hub route.");
    return { ok: false, cancelled: true };
  }
  const prompt = options.prompt || await vscode.window.showInputBox({
    title: "Explain Agent-Hub Route",
    prompt: "Task to score. This explains routing without calling a provider.",
    value: PERSONAL_BENCHMARK_PROMPT,
    ignoreFocusOut: true
  });
  if (!prompt) {
    return { ok: false, cancelled: true };
  }
  if (!(await ensureServerReady())) {
    vscode.window.showErrorMessage("Agent Hub is not ready. Start the backend or open the Agent Hub output.");
    return { ok: false, cancelled: false };
  }
  const config = settings();
  const launch = await serverLaunchEnvironment(workspace);
  if (!(await ensurePythonBackend(config, workspace, launch))) {
    return { ok: false, cancelled: false };
  }
  const route = config.route || "coding";
  const args = [
    ...launch.pythonArgs,
    "-m",
    "agent_hub",
    "--config",
    resolveConfigPath(config.configPath, workspace),
    "explain-route",
    "--route",
    route,
    "--prefer",
    "coding",
    "--needs-tools",
    prompt
  ];
  output.appendLine("");
  output.appendLine("Agent Hub route explanation");
  output.appendLine(formatCliCommandForLog(launch.pythonCommand, args));
  try {
    const { stdout, stderr } = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Agent Hub: Explaining route",
        cancellable: false
      },
      () => execFile(launch.pythonCommand, args, {
        cwd: workspace,
        env: launch.env,
        timeout: 120000,
        maxBuffer: 4 * 1024 * 1024
      })
    );
    if (stderr && String(stderr).trim()) {
      output.appendLine(String(stderr).trim());
    }
    const text = String(stdout || "").trim() || "No route explanation was returned.";
    output.appendLine(text);
    const document = await vscode.workspace.openTextDocument({
      content: text,
      language: "plaintext"
    });
    await vscode.window.showTextDocument(document, { preview: true });
    const next = await vscode.window.showInformationMessage(
      "Route explanation generated from the current candidate scorecards.",
      "README Proof",
      "Benchmark Dashboard"
    );
    if (next === "README Proof") {
      await openReadmeProofSection();
    } else if (next === "Benchmark Dashboard") {
      await openAgentHubDashboard("/dashboard/benchmarks");
    }
    return { ok: true, text };
  } catch (error) {
    output.appendLine(`Route explanation failed: ${error.message}`);
    if (error.stderr) {
      output.appendLine(String(error.stderr));
    }
    output.show(true);
    vscode.window.showErrorMessage(`Route explanation failed: ${error.message}`);
    return { ok: false, cancelled: false };
  }
}

async function openRouteLabCommand(options = {}) {
  const workspace = workspaceRoot();
  if (!workspace) {
    vscode.window.showWarningMessage("Open a workspace folder before opening Agent Hub Route Lab.");
    return { ok: false, cancelled: true };
  }
  const prompt = options.prompt || await vscode.window.showInputBox({
    title: "Agent Hub Route Lab",
    prompt: "Task to diagnose. Route Lab scores candidates without calling a provider.",
    value: PERSONAL_BENCHMARK_PROMPT,
    ignoreFocusOut: true
  });
  if (!prompt) {
    return { ok: false, cancelled: true };
  }
  const config = settings();
  const launch = await serverLaunchEnvironment(workspace);
  if (!(await ensurePythonBackend(config, workspace, launch))) {
    return { ok: false, cancelled: false };
  }
  const route = options.route || config.route || "coding";
  const outputTokens = Number.isFinite(Number(options.outputTokens))
    ? Math.max(1, Number.parseInt(options.outputTokens, 10))
    : (config.maxTokens || 1024);
  const args = [
    ...launch.pythonArgs,
    "-m",
    "agent_hub",
    "--config",
    resolveConfigPath(config.configPath, workspace),
    "route-diagnose",
    "--route",
    route,
    "--prefer",
    options.prefer || "coding",
    "--needs-tools",
    "--output-tokens",
    String(outputTokens),
    "--json",
    prompt
  ];
  output.appendLine("");
  output.appendLine("Agent Hub Route Lab");
  output.appendLine(formatCliCommandForLog(launch.pythonCommand, args));
  try {
    const { stdout, stderr } = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Agent Hub: Opening Route Lab",
        cancellable: false
      },
      () => execFile(launch.pythonCommand, args, {
        cwd: workspace,
        env: launch.env,
        timeout: 120000,
        maxBuffer: 6 * 1024 * 1024
      })
    );
    if (stderr && String(stderr).trim()) {
      output.appendLine(String(stderr).trim());
    }
    const report = parseJsonObjectFromText(stdout);
    if (!report || report.object !== "agent_hub.route_diagnosis") {
      throw new Error("Route diagnosis did not return valid JSON.");
    }
    routeLabPanel = routeLabPanel || vscode.window.createWebviewPanel(
      "agentHub.routeLab",
      "Agent Hub Route Lab",
      vscode.ViewColumn.Beside,
      {
        enableScripts: false,
        retainContextWhenHidden: true
      }
    );
    routeLabPanel.onDidDispose(() => {
      routeLabPanel = null;
    });
    routeLabPanel.webview.html = routeLabHtml(routeLabPanel.webview, report, prompt);
    routeLabPanel.reveal(vscode.ViewColumn.Beside);
    vscode.window.showInformationMessage("Route Lab scored the current candidate stack.");
    return { ok: true, report };
  } catch (error) {
    output.appendLine(`Route Lab failed: ${error.message}`);
    if (error.stderr) {
      output.appendLine(String(error.stderr));
    }
    output.show(true);
    vscode.window.showErrorMessage(`Route Lab failed: ${error.message}`);
    return { ok: false, cancelled: false };
  }
}

function routeLabHtml(webview, report, prompt) {
  const nonce = getNonce();
  const selected = {
    agent: report.selected_agent || "none",
    provider: report.selected_provider || "none",
    model: report.selected_model || "none",
    latency: formatRouteLabLatency(report.latency_ms),
    cost: formatRouteLabCost(report.estimated_cost_usd)
  };
  const candidates = Array.isArray(report.candidates) ? report.candidates : [];
  const skipped = Array.isArray(report.skipped_providers) ? report.skipped_providers : [];
  const warnings = Array.isArray(report.selection_warnings) ? report.selection_warnings : [];
  const tokenSaver = report.token_saver && typeof report.token_saver === "object" ? report.token_saver : null;
  const baselineComparisons = report.baseline_comparisons && typeof report.baseline_comparisons === "object"
    ? report.baseline_comparisons
    : {};
  const baselines = Array.isArray(report.baseline_comparisons)
    ? report.baseline_comparisons
    : Array.isArray(baselineComparisons.named_baselines)
      ? baselineComparisons.named_baselines
      : [];
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Hub Route Lab</title>
  <style nonce="${nonce}">
    :root {
      color-scheme: light dark;
      --bg: var(--vscode-editor-background, #1f2328);
      --fg: var(--vscode-foreground, #d4d4d4);
      --muted: var(--vscode-descriptionForeground, #8b949e);
      --border: var(--vscode-panel-border, #3b3f46);
      --panel: var(--vscode-sideBar-background, #252a31);
      --accent: var(--vscode-button-background, #2563eb);
      --accent-fg: var(--vscode-button-foreground, #ffffff);
      --warn: var(--vscode-editorWarning-foreground, #d29922);
      --ok: var(--vscode-testing-iconPassed, #3fb950);
      --bad: var(--vscode-testing-iconFailed, #f85149);
      --code: var(--vscode-textCodeBlock-background, rgba(127, 127, 127, 0.12));
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      color: var(--fg);
      background: var(--bg);
      font-family: var(--vscode-font-family, system-ui, sans-serif);
      font-size: var(--vscode-font-size, 13px);
    }
    main {
      width: min(1180px, 100%);
      margin: 0 auto;
      padding: 24px;
    }
    header {
      display: grid;
      gap: 14px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--border);
    }
    h1, h2, h3, p {
      margin: 0;
    }
    h1 {
      font-size: 26px;
      font-weight: 700;
    }
    h2 {
      font-size: 16px;
      margin-bottom: 10px;
    }
    h3 {
      font-size: 13px;
      margin-bottom: 8px;
    }
    .prompt {
      max-width: 960px;
      color: var(--muted);
      line-height: 1.45;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }
    .metric {
      min-height: 82px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      background: var(--panel);
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .metric strong {
      display: block;
      overflow-wrap: anywhere;
      font-size: 17px;
      line-height: 1.25;
    }
    section {
      margin-top: 22px;
    }
    .split {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
      gap: 16px;
    }
    .panel {
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px;
      background: color-mix(in srgb, var(--panel) 88%, transparent);
    }
    .why {
      line-height: 1.45;
    }
    .honesty {
      border-left: 3px solid ${warnings.length ? "var(--warn)" : "var(--ok)"};
      padding-left: 12px;
      line-height: 1.45;
    }
    .warning-list {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    .warning {
      border: 1px solid color-mix(in srgb, var(--warn) 52%, var(--border));
      border-radius: 6px;
      padding: 9px 10px;
      color: var(--fg);
      background: color-mix(in srgb, var(--warn) 12%, transparent);
    }
    .kv {
      display: grid;
      grid-template-columns: 140px minmax(0, 1fr);
      gap: 8px;
      color: var(--muted);
    }
    .kv strong {
      color: var(--fg);
      overflow-wrap: anywhere;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      background: var(--panel);
    }
    tr:last-child td {
      border-bottom: 0;
    }
    .status {
      display: inline-block;
      min-width: 70px;
      border-radius: 999px;
      padding: 2px 8px;
      text-align: center;
      font-size: 12px;
      color: var(--accent-fg);
      background: var(--accent);
    }
    .status.off {
      color: var(--fg);
      background: var(--code);
    }
    .mono {
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 12px;
    }
    .col-rank {
      width: 54px;
    }
    .col-state {
      width: 96px;
    }
    .col-score {
      width: 90px;
    }
    .col-latency {
      width: 112px;
    }
    .muted {
      color: var(--muted);
    }
    .empty {
      border: 1px dashed var(--border);
      border-radius: 6px;
      padding: 14px;
      color: var(--muted);
    }
    @media (max-width: 760px) {
      main {
        padding: 16px;
      }
      .split {
        grid-template-columns: 1fr;
      }
      .kv {
        grid-template-columns: 1fr;
      }
      th:nth-child(6), td:nth-child(6) {
        display: none;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Agent Hub Route Lab</h1>
      <p class="prompt">${escapeHtml(prompt)}</p>
    </header>

    <section class="summary" aria-label="Selected route summary">
      <div class="metric"><span>Route</span><strong>${escapeHtml(report.route || "unknown")}</strong></div>
      <div class="metric"><span>Selected Agent</span><strong>${escapeHtml(selected.agent)}</strong></div>
      <div class="metric"><span>Model</span><strong>${escapeHtml(selected.model)}</strong></div>
      <div class="metric"><span>Latency</span><strong>${escapeHtml(selected.latency)}</strong></div>
      <div class="metric"><span>Cost Estimate</span><strong>${escapeHtml(selected.cost)}</strong></div>
    </section>

    <section class="split">
      <div class="panel">
        <h2>Why This Route</h2>
        <p class="why">${escapeHtml(report.why_provider_chosen || report.fallback_reason || "No route reason was returned.")}</p>
      </div>
      <div class="panel">
        <h2>Selection Honesty</h2>
        <p class="honesty">${escapeHtml(report.selection_honesty || "No health summary was returned.")}</p>
        ${warnings.length ? `<div class="warning-list">${warnings.map((warning) => `<div class="warning">${escapeHtml(warning)}</div>`).join("")}</div>` : ""}
      </div>
    </section>

    <section class="split">
      <div class="panel">
        <h2>Routing Signals</h2>
        <div class="kv">
          <span>Mode</span><strong>${escapeHtml(report.routing_mode || "unknown")}</strong>
          <span>Task Type</span><strong>${escapeHtml(report.task_type || "unknown")}</strong>
          <span>Input Tokens</span><strong>${escapeHtml(formatRouteLabNumber(report.estimated_input_tokens))}</strong>
          <span>Output Tokens</span><strong>${escapeHtml(formatRouteLabNumber(report.estimated_output_tokens))}</strong>
          <span>Fallback Reason</span><strong>${escapeHtml(report.fallback_reason || "none")}</strong>
        </div>
      </div>
      <div class="panel">
        <h2>Token Saver</h2>
        ${tokenSaver ? routeLabTokenSaverHtml(tokenSaver) : `<div class="empty">No token saver scorecard was attached.</div>`}
      </div>
    </section>

    <section>
      <h2>Candidate Stack</h2>
      ${candidates.length ? routeLabCandidatesTable(candidates) : `<div class="empty">No candidates were returned.</div>`}
    </section>

    <section class="split">
      <div>
        <h2>Skipped Providers</h2>
        ${skipped.length ? routeLabSkippedTable(skipped) : `<div class="empty">No providers were skipped.</div>`}
      </div>
      <div>
        <h2>Baseline Comparison</h2>
        ${baselines.length ? routeLabBaselineTable(baselines) : `<div class="empty">No baseline comparison was returned.</div>`}
      </div>
    </section>
  </main>
</body>
</html>`;
}

function routeLabTokenSaverHtml(tokenSaver) {
  const active = tokenSaver.active ? "active" : "inactive";
  const confidence = tokenSaver.confidence === null || tokenSaver.confidence === undefined
    ? "unknown"
    : Number(tokenSaver.confidence).toFixed(2);
  return `<div class="kv">
    <span>State</span><strong>${escapeHtml(active)}</strong>
    <span>Confidence</span><strong>${escapeHtml(confidence)}</strong>
    <span>Summary</span><strong>${escapeHtml(tokenSaver.summary || "none")}</strong>
  </div>`;
}

function routeLabCandidatesTable(candidates) {
  return `<table>
    <thead>
      <tr>
        <th class="col-rank">Rank</th>
        <th>Agent</th>
        <th>Provider</th>
        <th>Model</th>
        <th class="col-state">State</th>
        <th class="col-score">Score</th>
        <th class="col-latency">Latency</th>
        <th>Reason</th>
      </tr>
    </thead>
    <tbody>
      ${candidates.map((row) => `<tr>
        <td class="mono">${escapeHtml(formatRouteLabNumber(row.rank))}</td>
        <td>${escapeHtml(row.agent || "")}</td>
        <td>${escapeHtml(row.provider || "")}</td>
        <td>${escapeHtml(row.model || "")}</td>
        <td><span class="status ${row.available ? "" : "off"}">${escapeHtml(row.available ? "ready" : "skipped")}</span></td>
        <td class="mono">${escapeHtml(formatRouteLabScore(row.routing_score ?? row.score))}</td>
        <td class="mono">${escapeHtml(formatRouteLabLatency(row.latency_ms))}</td>
        <td>${escapeHtml(row.reason || row.why || "")}</td>
      </tr>`).join("")}
    </tbody>
  </table>`;
}

function routeLabSkippedTable(skipped) {
  return `<table>
    <thead>
      <tr>
        <th>Agent</th>
        <th>Model</th>
        <th>Reason</th>
      </tr>
    </thead>
    <tbody>
      ${skipped.map((row) => `<tr>
        <td>${escapeHtml(row.agent || "")}</td>
        <td>${escapeHtml(row.model || "")}</td>
        <td>${escapeHtml(row.reason || row.fallback_reason || "")}</td>
      </tr>`).join("")}
    </tbody>
  </table>`;
}

function routeLabBaselineTable(baselines) {
  return `<table>
    <thead>
      <tr>
        <th>Baseline</th>
        <th>Model</th>
        <th>Cost</th>
        <th>Savings</th>
      </tr>
    </thead>
    <tbody>
      ${baselines.map((row) => `<tr>
        <td>${escapeHtml(row.baseline_name || row.agent || row.name || row.provider || "baseline")}</td>
        <td>${escapeHtml(row.baseline_model || row.model || row.baseline_agent || "")}</td>
        <td class="mono">${escapeHtml(formatRouteLabCost(row.estimated_cost_usd ?? row.cost_usd ?? row.cost))}</td>
        <td>${escapeHtml(formatRouteLabSavings(row))}</td>
      </tr>`).join("")}
    </tbody>
  </table>`;
}

function formatRouteLabSavings(row) {
  const savingsUsd = Number(row.savings_usd);
  const savingsPct = Number(row.savings_pct);
  if (Number.isFinite(savingsUsd) && Number.isFinite(savingsPct)) {
    return `${formatRouteLabCost(savingsUsd)} (${savingsPct.toFixed(1)}%)`;
  }
  return row.comparison || row.summary || row.delta || row.reason || "";
}

function formatRouteLabLatency(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) {
    return "unknown";
  }
  return number >= 1000 ? `${(number / 1000).toFixed(1)} s` : `${number.toFixed(0)} ms`;
}

function formatRouteLabCost(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) {
    return "unpriced";
  }
  if (number === 0) {
    return "$0.000000";
  }
  return `$${number.toFixed(number < 0.001 ? 6 : 4)}`;
}

function formatRouteLabScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "";
  }
  return number.toFixed(3);
}

function formatRouteLabNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "";
  }
  return new Intl.NumberFormat("en-US").format(number);
}

async function openBenchmarkReport(report, fallbackStatus) {
  const paths = report && report.report_paths && typeof report.report_paths === "object"
    ? report.report_paths
    : {};
  const markdownPath = typeof paths.markdown === "string" && paths.markdown
    ? paths.markdown
    : fallbackStatus.markdownPath;
  if (markdownPath && fs.existsSync(markdownPath)) {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(markdownPath));
    await vscode.window.showTextDocument(document, { preview: false });
    return;
  }
  output.show(true);
}

function formatBenchmarkCompletionMessage(report) {
  const comparison = report && report.comparison && typeof report.comparison === "object"
    ? report.comparison
    : {};
  const tasks = report && report.task_count ? report.task_count : PERSONAL_BENCHMARK_LIMIT;
  return [
    `Personal benchmark complete: ${tasks} tasks.`,
    `Cost ${formatPercentMetric(comparison.cost_reduction)}.`,
    `Latency ${formatPercentMetric(comparison.latency_reduction)}.`,
    `Success ${formatSignedPointMetric(comparison.success_delta)}.`
  ].join(" ");
}

function formatPercentMetric(value) {
  if (value === null || value === undefined || value === "") {
    return "unpriced";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "unpriced";
  }
  return `${number.toFixed(1)}%`;
}

function formatSignedPointMetric(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "0.0 pp";
  }
  return `${number >= 0 ? "+" : ""}${number.toFixed(1)} pp`;
}

function parseJsonObjectFromText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch (_error) {
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start !== -1 && end > start) {
      try {
        return JSON.parse(text.slice(start, end + 1));
      } catch (_nestedError) {
        return {};
      }
    }
  }
  return {};
}

function formatCliCommandForLog(command, args) {
  return [command, ...args]
    .map((part) => /\s/.test(String(part)) ? `"${String(part).replace(/"/g, '\\"')}"` : String(part))
    .join(" ");
}

async function copyClineConfig() {
  const text = clineConfigText(settings());
  await vscode.env.clipboard.writeText(text);
  vscode.window.showInformationMessage("Cline setup copied. Paste it into Cline's OpenAI Compatible provider settings.");
}

async function showClineSetup() {
  output.show(true);
  output.appendLine("");
  output.appendLine("Agent Hub setup for Cline");
  output.appendLine("");
  output.appendLine("1. Start Agent Hub from the sidebar.");
  output.appendLine("2. In Cline, choose OpenAI Compatible.");
  output.appendLine("3. Paste these values:");
  output.appendLine("");
  output.appendLine(clineConfigText(settings()));
  output.appendLine("");
  output.appendLine("Tip: the Base URL must end with /v1.");
}

async function testClineConnection() {
  if (!(await ensureServerReady())) {
    vscode.window.showWarningMessage("Agent Hub is not running. Click Start first.");
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
      ? "Cline can reach Agent Hub. You are ready to use model agent-hub-coding."
      : "Cline reached Agent Hub, but the test found missing context details. Open logs for more information.";
    output.appendLine(JSON.stringify(response, null, 2));
    vscode.window.showInformationMessage(message);
  } catch (error) {
    vscode.window.showErrorMessage(`Cline connection test failed: ${formatAgentHubError(error)}`);
  }
}

async function copyClaudeCodeConfig() {
  const text = claudeCodeConfigText(settings());
  await vscode.env.clipboard.writeText(text);
  vscode.window.showInformationMessage("Claude Code setup copied.");
}

async function showClaudeCodeSetup() {
  output.show(true);
  output.appendLine("");
  output.appendLine("Agent Hub setup for Claude Code");
  output.appendLine("");
  output.appendLine("1. Start Agent Hub from the sidebar.");
  output.appendLine("2. Add these environment variables to Claude Code:");
  output.appendLine("");
  output.appendLine(claudeCodeConfigText(settings()));
  output.appendLine("");
  output.appendLine("Tip: use model agent-hub-coding.");
}

async function testAnthropicEndpoint() {
  if (!(await ensureServerReady())) {
    vscode.window.showWarningMessage("Agent Hub is not running. Click Start first.");
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
      ? "Claude Code can reach Agent Hub. You are ready to use model agent-hub-coding."
      : "Claude Code reached Agent Hub, but the test found missing context details. Open logs for more information.";
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
  await sendAgentRequest({ task, context: editorContext({ preferSelection: true }), routingText: task });
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
    routingText: task,
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

async function generateCommitMessage(...args) {
  const repository = await selectGitRepository(args);
  if (!repository) {
    return;
  }

  let diffContext;
  try {
    diffContext = await gitCommitMessageContext(repository);
  } catch (error) {
    output.appendLine(`Could not read Git changes: ${error.message}`);
    vscode.window.showErrorMessage(`Could not read Git changes: ${error.message}`);
    return;
  }

  if (!diffContext || !diffContext.context.trim()) {
    vscode.window.showInformationMessage("No Git changes found to summarize.");
    return;
  }

  const config = settings();
  if (!(await approveModelRequest({
    providerMode: config.agentProviderMode,
    contextText: diffContext.context,
    source: "VS Code Source Control"
  }))) {
    vscode.window.showWarningMessage("Commit message generation cancelled because permission was not granted.");
    return;
  }
  if (!(await ensureServerReady())) {
    vscode.window.showErrorMessage("Agent Hub is not running. Click Start or open logs.");
    return;
  }

  try {
    const message = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Agent Hub: Generating commit message",
        cancellable: false
      },
      () => requestCommitMessage(diffContext)
    );
    if (!message) {
      vscode.window.showWarningMessage("Agent Hub returned an empty commit message.");
      return;
    }
    if (!repository.inputBox) {
      await vscode.env.clipboard.writeText(message);
      vscode.window.showWarningMessage("Generated commit message copied, but the Git commit input was unavailable.");
      return;
    }
    repository.inputBox.value = message;
    vscode.window.showInformationMessage("Agent Hub generated a commit message.");
  } catch (error) {
    output.appendLine(`Commit message generation failed: ${error.message}`);
    vscode.window.showErrorMessage(formatAgentHubError(error));
  }
}

async function requestCommitMessage(diffContext) {
  const config = settings();
  const body = {
    session_id: `vscode-commit-${Date.now()}`,
    mode: "route",
    route: codingAgentRoute(config),
    task: commitMessageTask(diffContext.scope),
    context: diffContext.context,
    approval_mode: config.approvalMode,
    provider_approval_granted: true,
    context_mode: config.contextMode,
    cline_compatibility_mode: config.clineCompatibilityMode,
    max_tokens: 160,
    agent_hub: agentHubRequestOptions(config, {
      classification_text: "Generate a concise Git commit message for the provided diff.",
      routing_mode: isMaxTokenSaveMode(config) ? "cheapest" : undefined
    }),
    metadata: {
      source: "vscode-scm",
      command: "generateCommitMessage",
      diff_scope: diffContext.scope
    }
  };
  applyOptionalMaxTokens(body, config);

  output.show(true);
  output.appendLine("");
  output.appendLine(`[Agent Hub SCM] Generating commit message for ${diffContext.scope}.`);
  const response = await requestJson("POST", "/v1/route", body);
  const message = normalizeCommitMessage(responseText(response));
  output.appendLine(message || "(empty commit message)");
  return message;
}

async function rollbackLatestCheckpoint() {
  try {
    const body = await requestJson("GET", "/v1/workspace/checkpoints");
    const checkpoints = Array.isArray(body.data) ? body.data : [];
    const checkpoint = checkpoints[0];
    if (!checkpoint || !checkpoint.id) {
      vscode.window.showInformationMessage("Agent Hub has no workspace checkpoints to restore.");
      return;
    }
    const paths = Array.isArray(checkpoint.paths) ? checkpoint.paths : [];
    const approved = await requestPermission({
      category: "file_write",
      description: "Agent Hub wants to restore the latest workspace checkpoint.",
      resource: checkpoint.id,
      risk: "high",
      detail: paths.length ? `Files: ${paths.slice(0, 12).join(", ")}` : "Checkpoint file list unavailable."
    });
    if (!approved) {
      return;
    }
    const result = await requestJson("POST", "/v1/workspace/rollback", {
      checkpoint_id: checkpoint.id
    });
    output.appendLine(`[rollback] ${JSON.stringify(result)}`);
    vscode.window.showInformationMessage(
      result.ok
        ? `Agent Hub restored checkpoint ${checkpoint.id}.`
        : `Agent Hub rollback was partial for checkpoint ${checkpoint.id}.`
    );
  } catch (error) {
    output.appendLine(`Workspace rollback failed: ${error.message}`);
    vscode.window.showErrorMessage(formatAgentHubError(error));
  }
}

function commitMessageTask(scope) {
  return [
    "Generate a Git commit message for the provided diff.",
    "Match VS Code Copilot commit-message behavior: concise, specific, and ready to paste into the Source Control commit input.",
    "Return only the commit message. Do not include markdown, labels, explanations, or quotes.",
    "Prefer one Conventional Commit subject line like type(scope): summary when it fits.",
    "Use a short body only when the diff genuinely needs extra explanation.",
    `Diff scope: ${scope}.`
  ].join("\n");
}

function normalizeCommitMessage(text) {
  let value = String(text || "").trim();
  if (!value) {
    return "";
  }
  value = value.replace(/^```[a-zA-Z0-9_-]*\s*/, "").replace(/\s*```$/, "").trim();
  value = value.replace(/^\s*(?:commit message|message)\s*:\s*/i, "").trim();
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    value = value.slice(1, -1).trim();
  }
  const lines = value.split(/\r?\n/).map((line) => line.trimEnd());
  while (lines.length && !lines[0].trim()) {
    lines.shift();
  }
  while (lines.length && !lines[lines.length - 1].trim()) {
    lines.pop();
  }
  if (lines.length === 1) {
    lines[0] = lines[0].replace(/^[-*]\s+/, "").trim();
  }
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

async function selectGitRepository(commandArgs = []) {
  const api = await gitExtensionApi();
  if (!api) {
    vscode.window.showWarningMessage("The VS Code Git extension is not available.");
    return null;
  }

  const repositories = Array.isArray(api.repositories) ? api.repositories : [];
  if (!repositories.length) {
    vscode.window.showWarningMessage("No Git repositories are open in this workspace.");
    return null;
  }

  const argumentRepository = repositoryFromCommandArgs(commandArgs, repositories);
  if (argumentRepository) {
    return argumentRepository;
  }

  const editor = currentTextEditor();
  if (editor && editor.document && editor.document.uri && typeof api.getRepository === "function") {
    const activeRepository = api.getRepository(editor.document.uri);
    if (activeRepository) {
      return activeRepository;
    }
  }

  if (repositories.length === 1) {
    return repositories[0];
  }

  const workspace = workspaceRoot();
  if (workspace) {
    const matchingRepository = repositories.find((repository) => {
      const root = repositoryRootPath(repository);
      return root && pathInside(workspace, root);
    });
    if (matchingRepository) {
      return matchingRepository;
    }
  }

  const choice = await vscode.window.showQuickPick(
    repositories.map((repository) => ({
      label: repositoryLabel(repository),
      description: repositoryRootPath(repository),
      repository
    })),
    { placeHolder: "Generate a commit message for which repository?" }
  );
  return choice ? choice.repository : null;
}

function repositoryFromCommandArgs(commandArgs, repositories) {
  const args = Array.isArray(commandArgs) ? commandArgs.flat() : [];
  for (const arg of args) {
    if (!arg || typeof arg !== "object") {
      continue;
    }
    if (repositoryRootPath(arg) && arg.inputBox) {
      return arg;
    }
    const rootUri = arg.rootUri || arg.sourceControl && arg.sourceControl.rootUri;
    if (rootUri && rootUri.fsPath) {
      const match = repositories.find((repository) => repositoryRootPath(repository) === rootUri.fsPath);
      if (match) {
        return match;
      }
    }
  }
  return null;
}

async function gitExtensionApi() {
  const gitExtension = vscode.extensions.getExtension("vscode.git");
  if (!gitExtension) {
    return null;
  }
  try {
    const exports = gitExtension.isActive ? gitExtension.exports : await gitExtension.activate();
    return exports && typeof exports.getAPI === "function" ? exports.getAPI(1) : null;
  } catch (error) {
    output.appendLine(`Could not activate VS Code Git extension: ${error.message}`);
    return null;
  }
}

async function gitCommitMessageContext(repository) {
  const root = repositoryRootPath(repository);
  if (!root) {
    throw new Error("Git repository root was unavailable.");
  }

  const [
    status,
    stagedStat,
    stagedDiff,
    unstagedStat,
    unstagedDiff,
    untrackedOutput
  ] = await Promise.all([
    git(root, ["status", "--short"]),
    git(root, ["diff", "--cached", "--stat", "--find-renames"]),
    git(root, ["diff", "--cached", "--no-ext-diff", "--find-renames", "--find-copies", "--unified=80"]),
    git(root, ["diff", "--stat", "--find-renames"]),
    git(root, ["diff", "--no-ext-diff", "--find-renames", "--find-copies", "--unified=80"]),
    git(root, ["ls-files", "--others", "--exclude-standard"])
  ]);

  const untrackedFiles = gitOutputLines(untrackedOutput);
  const hasStagedChanges = Boolean(stagedDiff.trim() || stagedStat.trim());
  const hasUnstagedChanges = Boolean(unstagedDiff.trim() || unstagedStat.trim() || untrackedFiles.length);
  if (!hasStagedChanges && !hasUnstagedChanges) {
    return null;
  }

  const scope = hasStagedChanges ? "staged changes" : "unstaged and untracked changes";
  const parts = [
    `Repository: ${repositoryLabel(repository)}`,
    `Scope: ${scope}`,
    "",
    "Git status:",
    status.trim() || "(clean)"
  ];

  if (hasStagedChanges) {
    parts.push("", "Staged diff stat:", stagedStat.trim() || "(no stat)");
    parts.push("", "Staged diff:", stagedDiff.trim());
  } else {
    parts.push("", "Unstaged diff stat:", unstagedStat.trim() || "(no stat)");
    parts.push("", "Unstaged diff:", unstagedDiff.trim() || "(no tracked-file diff)");
    if (untrackedFiles.length) {
      parts.push("", "Untracked files:", untrackedFiles.map((file) => `- ${file}`).join("\n"));
      parts.push("", "Untracked file previews:", untrackedFilePreviews(root, untrackedFiles));
    }
  }

  return {
    context: truncateText(parts.filter((part) => part !== "").join("\n"), 28000),
    scope,
    root
  };
}

async function git(root, args) {
  const { stdout } = await execFile("git", args, {
    cwd: root,
    timeout: 20000,
    maxBuffer: 20 * 1024 * 1024
  });
  return String(stdout || "");
}

function gitOutputLines(outputText) {
  return String(outputText || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function untrackedFilePreviews(root, files) {
  const previews = [];
  for (const file of files.slice(0, 8)) {
    const fullPath = safeRepositoryPath(root, file);
    if (!fullPath) {
      continue;
    }
    try {
      const stats = fs.statSync(fullPath);
      if (!stats.isFile()) {
        previews.push(`--- ${normalizeRelativePath(file)}\n(directory or special file skipped)`);
        continue;
      }
      if (stats.size > 20000) {
        previews.push(`--- ${normalizeRelativePath(file)}\n(file is ${stats.size} bytes; content skipped)`);
        continue;
      }
      const buffer = fs.readFileSync(fullPath);
      if (bufferLooksBinary(buffer)) {
        previews.push(`--- ${normalizeRelativePath(file)}\n(binary content skipped)`);
        continue;
      }
      previews.push(`--- ${normalizeRelativePath(file)}\n${truncateText(buffer.toString("utf8"), 4000)}`);
    } catch (error) {
      previews.push(`--- ${normalizeRelativePath(file)}\n(could not read file: ${error.message})`);
    }
  }
  if (files.length > 8) {
    previews.push(`... ${files.length - 8} more untracked file(s) omitted.`);
  }
  return previews.join("\n\n");
}

function bufferLooksBinary(buffer) {
  const limit = Math.min(buffer.length, 8000);
  for (let index = 0; index < limit; index += 1) {
    if (buffer[index] === 0) {
      return true;
    }
  }
  return false;
}

function safeRepositoryPath(root, relativePath) {
  const resolvedRoot = path.resolve(root);
  const fullPath = path.resolve(resolvedRoot, relativePath);
  return pathInside(fullPath, resolvedRoot) ? fullPath : null;
}

function repositoryRootPath(repository) {
  return repository && repository.rootUri && repository.rootUri.fsPath
    ? repository.rootUri.fsPath
    : "";
}

function repositoryLabel(repository) {
  const root = repositoryRootPath(repository);
  if (!root) {
    return "Git repository";
  }
  const rootUri = repository.rootUri;
  const workspaceFolder = rootUri ? vscode.workspace.getWorkspaceFolder(rootUri) : null;
  return workspaceFolder ? workspaceFolder.name : path.basename(root);
}

function pathInside(childPath, parentPath) {
  const relative = path.relative(path.resolve(parentPath), path.resolve(childPath));
  return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function truncateText(text, maxChars) {
  const value = String(text || "");
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, maxChars)}\n... truncated ...`;
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
    routingText: query,
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
    context: contextForDocument(editor.document, selected),
    routingText: "Explain this selected code or text clearly."
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
    context: contextForDocument(editor.document, editor.document.getText()),
    routingText: "Explain this file clearly."
  });
}

async function sendAgentRequest({ task, context, route, routingText, agentMode = true, extra = {} }) {
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
    vscode.window.showErrorMessage("Agent Hub is not running. Click Start or open logs.");
    return;
  }

  const selectedAgentMode = agentMode ? normalizeAgentMode(config.agentMode) : "route";
  const { agent_hub: extraAgentHub, ...extraBody } = extra && typeof extra === "object" ? extra : {};
  const body = {
    ...extraBody,
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
    agent_hub: agentHubRequestOptions(config, {
      ...(extraAgentHub && typeof extraAgentHub === "object" ? extraAgentHub : {}),
      classification_text: routingText || task,
      user_task: routingText || task
    }),
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
  return runtimePolicy.missingBackendFeatures(health, REQUIRED_BACKEND_FEATURES);
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
    apiToken: String(config.get("apiToken", "") || ""),
    approvalToken: String(config.get("approvalToken", "") || ""),
    pythonPath: config.get("pythonPath", "auto"),
    configPath: config.get("configPath", ""),
    route: config.get("route", "coding"),
    researchRoute: config.get("researchRoute", "research"),
    codingAgentRoute: config.get("codingAgentRoute", "local-agent"),
    agentProviderMode: providerMode,
    agentMode: normalizeAgentMode(config.get("agentMode", "agent")),
    approvalMode: normalizeApprovalMode(config.get("approvalMode", "safe")),
    groupPlanCandidates: config.get("groupPlanCandidates", 1),
    agentMaxSteps: config.get("agentMaxSteps", 20),
    agentContextBudgetTokens: config.get("agentContextBudgetTokens", 32000),
    agentContextCompactionEnabled: config.get("agentContextCompactionEnabled", true),
    contextMode: normalizeContextMode(config.get("contextMode", "balanced")),
    clineCompatibilityMode: config.get("clineCompatibilityMode", true),
    allowShellTools: config.get("allowShellTools", false),
    maxTokens: normalizeOptionalPositiveInteger(config.get("maxTokens", null)),
    autoStart: config.get("autoStart", true),
    automatedModelFeedback: config.get("automatedModelFeedback", false)
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
  const config = settings();
  const mode = normalizeAgentProviderMode(providerMode || config.agentProviderMode);
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
      isMaxTokenSaveMode(config)
        ? "Maximum token save mode may randomly try compatible free cloud models for simple tasks, compare stored model feedback against Codex-like fallback performance, and use the fallback when learned quality is not close enough."
        : "",
      secretWarning,
      "Provider API usage may consume quota or credits."
    ].filter(Boolean).join(" ")
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
  const deleteCount = Number(event && event.delete_count || 0);
  const category = event && event.category
    ? String(event.category)
    : tool === "run_command"
      ? "shell_command"
      : deleteCount > 0
        ? "file_delete"
        : "file_write";
  const detailParts = [];
  if (event && event.impact) {
    detailParts.push(event.impact);
  }
  if (event && event.patch_preview) {
    detailParts.push("Preview:\n" + String(event.patch_preview).slice(0, 3200));
  }
  return {
    category,
    description: event && event.summary
      ? `Agent Hub asks permission: ${event.summary}`
      : `Agent Hub asks permission to run ${tool}.`,
    resource: files.length ? files.join(", ") : commands.join(", "),
    risk: event && event.risk_level ? event.risk_level : "medium",
    detail: detailParts.join("\n\n")
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
  const configured = String(configPath || "").trim();
  if (isDefaultConfigSetting(configured)) {
    return defaultExtensionConfigPath(workspace);
  }
  const expanded = expandHomePath(configured);
  if (path.isAbsolute(expanded)) {
    return expanded;
  }
  if (!workspace) {
    return path.resolve(expanded);
  }
  return path.join(workspace, expanded);
}

function isDefaultConfigSetting(configPath) {
  const normalized = normalizeRelativePath(String(configPath || "").trim());
  return !normalized || normalized === DEFAULT_CONFIG_FILENAME;
}

function defaultExtensionConfigPath(workspace) {
  return path.join(defaultExtensionWorkspaceStorageDir(workspace), DEFAULT_CONFIG_FILENAME);
}

function defaultExtensionWorkspaceStorageDir(workspace) {
  const storageRoot = extensionContext && extensionContext.globalStorageUri
    ? extensionContext.globalStorageUri.fsPath
    : path.join(workspace || process.cwd(), ".agent-hub", "vscode");
  return path.join(storageRoot, "workspaces", workspaceStorageKey(workspace));
}

function workspaceStorageKey(workspace) {
  const resolved = path.resolve(workspace || "no-workspace");
  const label = (path.basename(resolved) || "workspace").replace(/[^A-Za-z0-9._-]+/g, "-");
  const hash = crypto.createHash("sha1").update(resolved.toLowerCase()).digest("hex").slice(0, 12);
  return `${label}-${hash}`;
}

function generatedConfigWorkspaceDir(configPath, workspace) {
  if (!workspace || !isDefaultConfigSetting(configPath)) {
    return "";
  }
  return path.resolve(workspace);
}

function generatedConfigStorageDir(configPath, workspace) {
  if (!workspace || !isDefaultConfigSetting(configPath)) {
    return "";
  }
  return path.join(defaultExtensionWorkspaceStorageDir(workspace), "runtime");
}

function generatedStoragePaths(storageDir) {
  const root = normalizeWorkspaceDirOption(storageDir);
  if (!root) {
    return {
      stateDir: ".agent-hub/state",
      inboxDir: ".agent-hub/inbox",
      outboxDir: ".agent-hub/outbox",
      archiveDir: ".agent-hub/archive"
    };
  }
  return {
    stateDir: path.join(root, "state"),
    inboxDir: path.join(root, "inbox"),
    outboxDir: path.join(root, "outbox"),
    archiveDir: path.join(root, "archive")
  };
}

function applyGeneratedStoragePaths(data, storageDir, workspaceDir = "") {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return false;
  }
  const paths = generatedStoragePaths(storageDir);
  if (!normalizeWorkspaceDirOption(storageDir)) {
    return false;
  }
  const previous = {
    state_dir: data.state_dir,
    inbox_dir: data.inbox_dir,
    outbox_dir: data.outbox_dir,
    archive_dir: data.archive_dir
  };
  let changed = false;
  for (const [key, value] of Object.entries({
    state_dir: paths.stateDir,
    inbox_dir: paths.inboxDir,
    outbox_dir: paths.outboxDir,
    archive_dir: paths.archiveDir
  })) {
    if (data[key] !== value) {
      data[key] = value;
      changed = true;
    }
  }
  migrateGeneratedStateDirectory(previous.state_dir, paths.stateDir, workspaceDir);
  migrateGeneratedStateDirectory(previous.inbox_dir, paths.inboxDir, workspaceDir);
  migrateGeneratedStateDirectory(previous.outbox_dir, paths.outboxDir, workspaceDir);
  migrateGeneratedStateDirectory(previous.archive_dir, paths.archiveDir, workspaceDir);
  return changed;
}

function migrateGeneratedStateDirectory(previousPath, nextPath, workspaceDir = "") {
  if (!previousPath || !nextPath) {
    return;
  }
  const source = resolveRuntimeStatePath(previousPath, workspaceDir);
  const target = resolveRuntimeStatePath(nextPath, workspaceDir);
  if (!source || !target || path.resolve(source) === path.resolve(target)) {
    return;
  }
  try {
    if (!fs.existsSync(source) || fs.existsSync(target)) {
      return;
    }
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.cpSync(source, target, { recursive: true, errorOnExist: false, force: false });
    output.appendLine(`Migrated Agent Hub state from ${source} to ${target}.`);
  } catch (error) {
    output.appendLine(`Could not migrate Agent Hub state from ${source} to ${target}: ${error.message}`);
  }
}

function resolveRuntimeStatePath(value, workspaceDir = "") {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) {
    return "";
  }
  const expanded = expandHomePath(text);
  if (path.isAbsolute(expanded)) {
    return expanded;
  }
  return path.resolve(workspaceDir || process.cwd(), expanded);
}

function normalizeWorkspaceDirOption(value) {
  const text = typeof value === "string" ? value.trim() : "";
  return text ? path.resolve(text) : "";
}

function ensureConfigDirectory(configPath) {
  const directory = path.dirname(configPath);
  if (directory && directory !== "." && !fs.existsSync(directory)) {
    fs.mkdirSync(directory, { recursive: true });
  }
}

function expandHomePath(value) {
  if (value === "~") {
    return process.env.HOME || process.env.USERPROFILE || value;
  }
  if (value.startsWith(`~${path.sep}`) || value.startsWith("~/") || value.startsWith("~\\")) {
    const home = process.env.HOME || process.env.USERPROFILE;
    if (home) {
      return path.join(home, value.slice(2));
    }
  }
  return value;
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

function agentHubHttpHeaders(extra = {}) {
  const config = settings();
  const headers = {
    "X-Agent-Hub-Client": "vscode-agent-hub",
    ...extra
  };
  if (config.apiToken) {
    headers.Authorization = `Bearer ${config.apiToken}`;
    headers["X-Agent-Hub-API-Token"] = config.apiToken;
  }
  const approvalToken = config.approvalToken || runtimeApprovalToken;
  if (approvalToken) {
    headers["X-Agent-Hub-Approval-Token"] = approvalToken;
  }
  return headers;
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
        headers: agentHubHttpHeaders({
          "Accept": "text/event-stream",
          "Content-Type": "application/json",
          "Content-Length": data ? Buffer.byteLength(data) : 0
        }),
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
        headers: agentHubHttpHeaders({
          "Content-Type": "application/json",
          "Content-Length": data ? Buffer.byteLength(data) : 0
        }),
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
