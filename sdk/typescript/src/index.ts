export type ChatMessage = {
  role: string;
  content: unknown;
};

export type AgentHubClientOptions = {
  baseUrl?: string;
  token?: string;
};

export class AgentHubClient {
  private readonly baseUrl: string;
  private readonly token?: string;

  constructor(options: AgentHubClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://127.0.0.1:8787").replace(/\/$/, "");
    this.token = options.token;
  }

  route(messages: ChatMessage[], model = "agent-hub"): Promise<Record<string, unknown>> {
    return this.post("/v1/chat/completions", { model, messages });
  }

  simulateRoute(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post("/v1/routing/simulate", payload);
  }

  listAgents(): Promise<Record<string, unknown>> {
    return this.get("/v1/agents");
  }

  createAgent(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post("/v1/agents", payload);
  }

  updateAgent(name: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post(`/v1/agents/${encodeURIComponent(name)}`, payload);
  }

  deleteAgent(name: string): Promise<Record<string, unknown>> {
    return this.request("DELETE", `/v1/agents/${encodeURIComponent(name)}`);
  }

  listWorkflowTemplates(): Promise<Record<string, unknown>> {
    return this.get("/v1/workflow-templates");
  }

  createWorkflowTemplate(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post("/v1/workflow-templates", payload);
  }

  updateWorkflowTemplate(id: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post(`/v1/workflow-templates/${encodeURIComponent(id)}`, payload);
  }

  deleteWorkflowTemplate(id: string): Promise<Record<string, unknown>> {
    return this.request("DELETE", `/v1/workflow-templates/${encodeURIComponent(id)}`);
  }

  listRoutingProfiles(): Promise<Record<string, unknown>> {
    return this.get("/v1/routing-profiles");
  }

  listRoutingStrategies(): Promise<Record<string, unknown>> {
    return this.get("/v1/routing-strategies");
  }

  createRoutingProfile(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post("/v1/routing-profiles", payload);
  }

  updateRoutingProfile(id: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post(`/v1/routing-profiles/${encodeURIComponent(id)}`, payload);
  }

  deleteRoutingProfile(id: string): Promise<Record<string, unknown>> {
    return this.request("DELETE", `/v1/routing-profiles/${encodeURIComponent(id)}`);
  }

  compactAnalytics(): Promise<Record<string, unknown>> {
    return this.post("/v1/analytics/compact", {});
  }

  observabilityExport(): Promise<Record<string, unknown>> {
    return this.get("/v1/observability/export");
  }

  otlpExport(): Promise<Record<string, unknown>> {
    return this.get("/v1/observability/otlp");
  }

  prometheusExport(): Promise<Record<string, unknown>> {
    return this.get("/v1/observability/prometheus");
  }

  simulateSwarm(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post("/v1/swarms/simulate", payload);
  }

  simulateTokenPooling(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.post("/v1/token-pools/simulate", payload);
  }

  readiness(): Promise<Record<string, unknown>> {
    return this.get("/v1/readiness");
  }

  openapi(): Promise<Record<string, unknown>> {
    return this.get("/openapi.json");
  }

  private get(path: string): Promise<Record<string, unknown>> {
    return this.request("GET", path);
  }

  private post(path: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", path, payload);
  }

  private async request(
    method: string,
    path: string,
    payload?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (payload) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const body = (await response.json()) as Record<string, unknown>;
    if (!response.ok) {
      throw new Error(`Agent-Hub HTTP ${response.status}: ${JSON.stringify(body)}`);
    }
    return body;
  }
}
