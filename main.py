import argparse
from core.engine import TririgaHybridEngine
from cli.router import TririgaNLPRouter

if __name__ == "__main__":
    # Set up command-line arguments
    parser = argparse.ArgumentParser(description="TRIRIGA Diagnostic Engine")
    parser.add_argument('--offline', action='store_true', help='Run in offline mode using local files.')
    args = parser.parse_args()

    # Configuration
    DB_USER = "U_TESTER01"
    DB_PASS = "HoneyOracle01"
    DB_DSN = "honeywell.axeffy.rds.amazonaws.com:1551/honeywelltty"
    OM_PACKAGE_NAME = r"Land_OnChange_RPIM_Status_Ind.zip"
    
    SSH_HOST = "w1ifqwasrpm004.irmnet.ds2.quant.edu" 
    SSH_USER = "zzFRMann"
    SSH_LOG_PATH = "/usr/local/tririga/log/server.log"
    LOCAL_LOG_PATH = "server (23).log" # The local file used during --offline mode

    # Initialize Engine with the offline flag
    engine = TririgaHybridEngine(DB_USER, DB_PASS, DB_DSN, offline_mode=args.offline)
    
    if engine.load_om_package(OM_PACKAGE_NAME):
        # Initialize Router with the offline flag
        router = TririgaNLPRouter(
            engine, 
            ssh_host=SSH_HOST, 
            ssh_user=SSH_USER, 
            ssh_log_path=SSH_LOG_PATH, 
            offline_mode=args.offline,
            local_log_path=LOCAL_LOG_PATH
        )
        
        print("\n" + "="*40)
        if args.offline:
            print("=== AI Diagnostic Chat Initialized ===")
            print("=== MODE: OFFLINE (Local Logs/XML) ===")
        else:
            print("=== AI Diagnostic Chat Initialized ===")
            print("=== MODE: LIVE (SSH & DB Active)   ===")
        print("="*40)
        
        print("\nType 'exit' to quit.")
        print("Type 'scan log' or 'what just failed' to securely scan the logs for errors.")
        print("Type 'trace live execution' to map out exactly how your OMP workflow routed itself.")
        print("Type 'trace ad hoc live execution' or 'another workflow' to trace workflows not in the OMP.\n")
        
        while True:
            try:
                query = input("Ask a question about the workflow: ")
                if query.lower() == 'exit': break
                else:
                    response = router.process_query(query)
                    if response: print(response)
            except KeyboardInterrupt: break
                
    engine.shutdown()