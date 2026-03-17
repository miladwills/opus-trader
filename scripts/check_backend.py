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
        
        # 1. Netstat to confirm listening ports
        run_cmd(ssh, "netstat -tulpn | grep python")
        
        # 2. Curl localhost:8000
        run_cmd(ssh, "curl -I -m 5 http://127.0.0.1:8000")
        
        # 3. Check Apache Proxy Config
        # Find files containing ProxyPass
        run_cmd(ssh, "grep -r 'ProxyPass' /etc/apache2/sites-enabled/")
        
        ssh.close()
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    main()
