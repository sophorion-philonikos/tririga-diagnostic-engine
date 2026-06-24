import paramiko
import getpass
from collections import deque

class SSHClientManager:
    def __init__(self, host, user, log_path, offline_mode=False, local_log_path=None):
        self.ssh_host = host
        self.ssh_user = user
        self.ssh_log_path = log_path
        self.offline_mode = offline_mode
        self.local_log_path = local_log_path
        self._cached_ssh_pass = None

    def fetch_remote_log(self, lines_to_read, show_workflow_note=False):
        """Fetches logs via SSH, or reads a local log file if in OFFLINE mode."""
        
        # --- OFFLINE MODE ROUTING ---
        if self.offline_mode:
            print(f"\n[Offline Mode] Scanning local log file: {self.local_log_path}...")
            try:
                # Use deque to efficiently pull the last N lines without loading the whole file into memory
                with open(self.local_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = deque(f, lines_to_read)
                    return list(lines)
            except FileNotFoundError:
                return f"ERROR: Local log file '{self.local_log_path}' not found in the root directory."

        # --- LIVE SSH ROUTING ---
        print(f"\n[Live SSH Log Scan Initiated] Target: {self.ssh_user}@{self.ssh_host}:{self.ssh_log_path}")
        if show_workflow_note:
            print("NOTE: TRIRIGA 'Workflow Logging -> Start, End, and Steps' must be enabled for this trace.")

        while True:
            if not getattr(self, '_cached_ssh_pass', None):
                self._cached_ssh_pass = getpass.getpass(f"Enter your daily SSH/sudo password for {self.ssh_user}: ")

            print("Establishing secure SSH connection and elevating privileges via sudo...")
            print("-" * 50)

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                client.connect(hostname=self.ssh_host, username=self.ssh_user, password=self._cached_ssh_pass, timeout=15)
                
                command = f"sudo tail -n {lines_to_read} {self.ssh_log_path}"
                stdin, stdout, stderr = client.exec_command(command, get_pty=True)
                stdin.write(self._cached_ssh_pass + '\n')
                stdin.flush()
                
                lines = stdout.readlines()
                log_text = "".join(lines)
                
                if "incorrect password attempt" in log_text.lower() or "sorry, try again" in log_text.lower():
                    print("\n[!] Sudo authentication failed. Your password may be incorrect or expired.")
                    self._cached_ssh_pass = None 
                    client.close()
                    continue 

                client.close()
                return lines 

            except paramiko.AuthenticationException:
                print("\n[!] SSH authentication failed. Your password may be incorrect or expired.")
                self._cached_ssh_pass = None 
                client.close()
                continue 
            except Exception as e:
                client.close()
                return f"ERROR: Critical error during SSH execution: {e}"