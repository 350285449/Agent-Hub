"use strict";

function modelQuickPickRows(models = []) {
  return models.map((model) => ({ label: model.model || model.name || "model", description: model.provider || "" }));
}

module.exports = { modelQuickPickRows };
