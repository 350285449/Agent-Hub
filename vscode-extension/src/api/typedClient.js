"use strict";

class AgentHubApiClient {
  constructor(baseUrl, token) {
    this.baseUrl = (baseUrl || "http://127.0.0.1:8787").replace(/\/$/, "");
    this.token = token || "";
  }

  readiness() {
    return this.get("/v1/readiness");
  }

  route(messages, model = "agent-hub") {
    return this.post("/v1/chat/completions", { model, messages });
  }

  simulateRoute(payload) {
    return this.post("/v1/routing/simulate", payload);
  }

  async get(path) {
    return this.request("GET", path);
  }

  async post(path, payload) {
    return this.request("POST", path, payload);
  }

  async request(method, path, payload) {
    const headers = { Accept: "application/json" };
    if (payload) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const body = await response.json();
    if (!response.ok) throw new Error(`Agent-Hub ${response.status}: ${JSON.stringify(body)}`);
    return body;
  }
}

module.exports = { AgentHubApiClient };
