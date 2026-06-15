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
