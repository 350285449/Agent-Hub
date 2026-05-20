"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const http = require("http");
const https = require("https");
const path = require("path");

let serverProcess = null;
let output;

function activate(context) {
  output = vscode.window.createOutputChannel("Agent Hub");
  context.subscriptions.push(output);

  context.subscriptions.push(
    vscode.commands.registerCommand("agentHub.startServer", startServer),
    vscode.commands.registerCommand("agentHub.stopServer", stopServer),
    vscode.commands.registerCommand("agentHub.status", showStatus),
    vscode.commands.registerCommand("agentHub.ask", askAgent),
    vscode.commands.registerCommand("agentHub.explainSelection", explainSelection),
    vscode.commands.registerCommand("agentHub.explainFile", explainFile),
    vscode.commands.registerCommand("agentHub.openOutput", () => output.show())
  );
}

function deactivate() {
  stopServerProcess();
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

async function sendAgentRequest({ task, context }) {
  const config = settings();
  if (!(await isServerOnline())) {
    if (config.autoStart) {
      await startServer();
    }
    if (!(await isServerOnline())) {
      vscode.window.showErrorMessage("Agent Hub is not running. Use 'Agent Hub: Start Server' or check the output.");
      return;
    }
  }

  const body = {
    session_id: `vscode-${Date.now()}`,
    mode: "agent",
    route: config.route,
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
    const response = await requestJson("POST", "/v1/agent", body);
    const text = response && response.message ? response.message.content : JSON.stringify(response, null, 2);
    output.appendLine("");
    output.appendLine(text || "(empty response)");
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
    pythonPath: config.get("pythonPath", "python"),
    configPath: config.get("configPath", "agent-hub.config.json"),
    route: config.get("route", "coding"),
    maxTokens: config.get("maxTokens", 1200),
    autoStart: config.get("autoStart", true)
  };
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
