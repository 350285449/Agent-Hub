"use strict";

class AgentHubStateManager {
  constructor(context) {
    this.context = context;
  }

  get(key, fallbackValue = undefined) {
    return this.context.globalState.get(key, fallbackValue);
  }

  update(key, value) {
    return this.context.globalState.update(key, value);
  }

  snapshot() {
    return {
      backendUrl: this.get("agentHub.backendUrl", "http://127.0.0.1:8787"),
      selectedRoute: this.get("agentHub.selectedRoute", "cloud-agent"),
      lastReadiness: this.get("agentHub.lastReadiness", null),
    };
  }
}

module.exports = { AgentHubStateManager };
