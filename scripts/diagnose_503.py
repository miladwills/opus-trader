import paramiko
import time

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"

def run_cmd(ssh, cmd):
    print(f"> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err:
        print(f"ERR: {err}")
    return out

def main():
    print(f"Connecting to {HOST}...")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        print("Connected.")
        
        # 1. Check Apache Error Log for Proxy Errors
        print("\n--- Apache Error Log (Proxy/503) ---")
        run_cmd(ssh, "tail -n 30 /var/log/apache2/error.log")
        
        # 2. Check if Backend is responsive from inside
        print("\n--- Checking Backend (localhost:8000) ---")
        # Try to curl the backend to see if it responds
        run_cmd(ssh, "curl -I http://127.0.0.1:8000")
        
        # 3. Check Apache Config to confirm upstream
        print("\n--- Apache Sites Config ---")
        # List enabled sites to find the config file
        run_cmd(ssh, "ls -l /etc/apache2/sites-enabled/")
        # Try to cat the likely config file (assuming madowlab or similar)
        run_cmd(ssh, "grep -r 'ProxyPass' /etc/apache2/sites-enabled/")

        ssh.close()
        
    except Exception as e:
        print(f"Diagnosis Failed: {e}")

if __name__ == "__main__":
    main()
