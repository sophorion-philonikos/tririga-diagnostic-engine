import argparse
import os
import sys
from core.engine import TririgaHybridEngine
from cli.router import TririgaNLPRouter


def _require_env(var_name, offline_ok=False, offline_mode=False, default=None):
    """Resolve configuration strictly from the environment.

    Secrets (DB credentials, SSH host/user) must never be committed to source.
    They are read from environment variables at runtime instead.
    """
    value = os.environ.get(var_name, default)
    if value:
        return value
    if offline_mode and offline_ok:
        return default
    return None


def load_configuration(offline_mode):
    """Build the runtime configuration from environment variables.

    Required (LIVE mode only):
        TRIRIGA_DB_USER, TRIRIGA_DB_PASS, TRIRIGA_DB_DSN
        TRIRIGA_SSH_HOST, TRIRIGA_SSH_USER, TRIRIGA_SSH_LOG_PATH

    Always used:
        TRIRIGA_OM_PACKAGE   (default: Land_OnChange_RPIM_Status_Ind.zip)
        TRIRIGA_LOCAL_LOG    (default: server (23).log) -- used by --offline
    """
    config = {
        'db_user': os.environ.get('TRIRIGA_DB_USER'),
        'db_pass': os.environ.get('TRIRIGA_DB_PASS'),
        'db_dsn': os.environ.get('TRIRIGA_DB_DSN'),
        'ssh_host': os.environ.get('TRIRIGA_SSH_HOST'),
        'ssh_user': os.environ.get('TRIRIGA_SSH_USER'),
        'ssh_log_path': os.environ.get('TRIRIGA_SSH_LOG_PATH', '/usr/local/tririga/log/server.log'),
        'om_package': os.environ.get('TRIRIGA_OM_PACKAGE', 'Land_OnChange_RPIM_Status_Ind.zip'),
        'local_log_path': os.environ.get('TRIRIGA_LOCAL_LOG', 'server (23).log'),
    }

    if not offline_mode:
        missing = [name for name, key in [
            ('TRIRIGA_DB_USER', 'db_user'),
            ('TRIRIGA_DB_PASS', 'db_pass'),
            ('TRIRIGA_DB_DSN', 'db_dsn'),
        ] if not config[key]]
        if missing:
            print(
                "CRITICAL: LIVE mode requires database credentials to be set as environment variables.\n"
                f"Missing: {', '.join(missing)}\n\n"
                "Set them before launching, for example:\n"
                "    export TRIRIGA_DB_USER=your_user\n"
                "    export TRIRIGA_DB_PASS=your_password\n"
                "    export TRIRIGA_DB_DSN=host:port/service\n\n"
                "Or run in offline mode with:  python3 main.py --offline"
            )
            sys.exit(1)

    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TRIRIGA Diagnostic Engine")
    parser.add_argument('--offline', action='store_true', help='Run in offline mode using local files.')
    parser.add_argument('--web', action='store_true', help='Launch the local Web UI instead of the interactive CLI.')
    parser.add_argument('--port', type=int, default=8000, help='Port for the Web UI (default: 8000, used with --web).')
    args = parser.parse_args()

    if args.web:
        from web.server import run_server
        run_server(port=args.port)
        sys.exit(0)

    config = load_configuration(args.offline)

    engine = TririgaHybridEngine(
        config['db_user'],
        config['db_pass'],
        config['db_dsn'],
        offline_mode=args.offline,
    )

    if engine.load_om_package(config['om_package']):
        router = TririgaNLPRouter(
            engine,
            ssh_host=config['ssh_host'],
            ssh_user=config['ssh_user'],
            ssh_log_path=config['ssh_log_path'],
            offline_mode=args.offline,
            local_log_path=config['local_log_path'],
        )

        print("\n" + "=" * 40)
        print("=== AI Diagnostic Chat Initialized ===")
        if args.offline:
            print("=== MODE: OFFLINE (Local Logs/XML) ===")
        else:
            print("=== MODE: LIVE (SSH & DB Active)   ===")
        print("=" * 40)

        print("\nType 'help' to see everything you can ask, grouped by category. Highlights:")
        print("  Understanding : 'what is the purpose', 'explain task 333543', 'what is Type 14?'")
        print("  Relationships : 'what does task 333395 have to do with the Start task?',")
        print("                  'what must be true to reach task 333449?'")
        print("  Inventory     : 'list all switches', 'which tasks modify the database?'")
        print("  Context       : 'use workflow triBuilding', 'list workflows'")
        print("  Visualization : 'visualize' (interactive HTML blueprint map)")
        print("  Live          : 'scan log', 'trace live execution', 'trace ad hoc live execution'")
        print("Type 'exit' to quit.\n")

        while True:
            try:
                query = input("Ask a question about the workflow: ")
                if query.lower() == 'exit':
                    break
                else:
                    response = router.process_query(query)
                    if response:
                        print(response)
            except KeyboardInterrupt:
                break

    engine.shutdown()
