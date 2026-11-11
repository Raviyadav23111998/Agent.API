#!/usr/bin/env python3
"""Agent — entry point.

Usage:
    ./main.py              # CLI mode (interactive REPL)
    ./main.py --gateway    # Gateway mode (Telegram + Cron)
    ./main.py -g           # Gateway mode (short flag)
"""
import path_setup  # noqa: F401 — must be first (bootstraps Agent.Core path)
import os
import sys
import signal
import asyncio


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from core.obs_logging import setup_structured_logging
    setup_structured_logging(app="agent")

    workspace = os.getcwd()
    
    if "--gateway" in sys.argv or "-g" in sys.argv:
        from gateway.runner import GatewayRunner
        
        runner = GatewayRunner(workspace)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(runner.start())
        except (KeyboardInterrupt, SystemExit):
            loop.run_until_complete(runner.stop())
        finally:
            loop.close()
    else:
        from client.cli import AgentCLI
        cli = AgentCLI(workspace)
        asyncio.run(cli.run())


if __name__ == "__main__":
    main()
