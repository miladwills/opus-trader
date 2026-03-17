import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"

def run_cmd(ssh, cmd):
    print(f"\n> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err:
        print(f"ERR: {err}")

def main():
    print(f"Connecting to {HOST}...")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        # 1. Get exact Proxy error from Apache logs
        print("\n--- Apache Log Analysis (Last 20 lines) ---")
        run_cmd(ssh, "tail -n 20 /var/log/apache2/error.log")
        
        # 2. Check the Python process details (PID 952 was seen earlier)
        print("\n--- Python Process Details ---")
        run_cmd(ssh, "ps aux | grep python")
        # Find the specific PID listening on 8000
        run_cmd(ssh, "netstat -tulpn | grep :8000")
        
        # 3. Check enabled config content to verify the fix applied
        print("\n--- Current Apache Config (Sites Enabled) ---")
        run_cmd(ssh, "grep -r 'ProxyPass' /etc/apache2/sites-enabled/")
        run_cmd(ssh, "cat /etc/apache2/sites-enabled/madowlab-le-ssl.conf")

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
