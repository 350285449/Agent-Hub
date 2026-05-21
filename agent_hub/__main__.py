from .cli import main

# Entry point for the agent_hub package
# This calls the main function from the CLI module and handles the exit code

if __name__ == "__main__":
    # Launch the command line interface and exit with the resulting status code
    raise SystemExit(main())
