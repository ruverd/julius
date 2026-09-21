"""Entry point for the bundled CLI and its own bounded subprocess protocols."""

import sys

from julius.cli import main


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "-m":
        module = sys.argv[2]
        if module in {"julius", "julius.cli"}:
            del sys.argv[1:3]
        elif module == "julius.repo_task_pilot":
            from julius.repo_task_pilot import _main as repo_task_main

            del sys.argv[1:3]
            raise SystemExit(repo_task_main())
        elif module == "julius.claude_pair":
            from julius.claude_pair import _main as pair_main

            del sys.argv[1:3]
            raise SystemExit(pair_main())
        else:
            raise SystemExit(f"Unsupported bundled module: {module}")
    main()
