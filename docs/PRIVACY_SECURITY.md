# Privacy And Security

Before cloud provider use, Agent Hub evaluates provider permission, secret
findings, workspace context, and approval mode. Cloud transparency data includes
provider/model, token estimate, file/snippet hints, and secret findings when
available.

Agent Hub does not install packages, pull models, edit configs, spawn
processes, upload workspace data, or write files without permission in modes
that require approval. `readonly` blocks workspace mutation. `safe` requires
approval for risky operations and blocks critical commands.

API keys saved through the VS Code extension are stored in VS Code Secret
Storage and injected into the backend environment when the server is started.
