import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
FILES = [
    "/var/www/opus_trader/services/bot_storage_service.py",
    "/var/www/opus_trader/services/risk_manager_service.py",
    "/var/www/opus_trader/services/pnl_service.py",
    "/var/www/opus_trader/runner.py",
    "/var/www/opus_trader/app.py",
    "/var/www/opus_trader/scripts/self_check_safety.py"
]

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        for f in FILES:
            print(f"\n--- Analyzing {f} ---")
            # Grep for fcntl with 5 lines of context
            stdin, stdout, stderr = ssh.exec_command(f"grep -C 5 'fcntl' {f}")
            out = stdout.read().decode().strip()
            print(out)
        
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
