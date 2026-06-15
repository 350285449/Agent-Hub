"use strict";

function createCommandRegistry(vscode, context) {
  const registrations = [];
  return {
    register(command, handler) {
      const disposable = vscode.commands.registerCommand(command, handler);
      context.subscriptions.push(disposable);
      registrations.push(command);
      return disposable;
    },
    commands() {
      return registrations.slice();
    },
  };
}

module.exports = { createCommandRegistry };
