import paramiko
import time

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
        
        # 1. Check Error Log for the LATEST 503 cause
        print("\n--- Latest Apache Error Logs ---")
        run_cmd(ssh, "tail -n 10 /var/log/apache2/error.log")
        
        # 2. Check the ENABLED config (the one Apache actually uses)
        # Verify it resolves to the file we edited
        print("\n--- Active Config Content ---")
        run_cmd(ssh, "cat /etc/apache2/sites-enabled/madowlab-le-ssl.conf")
        
        # 3. Check for any other configs that might conflict
        print("\n--- All Enabled Sites ---")
        run_cmd(ssh, "ls -l /etc/apache2/sites-enabled/")
        
        # 4. Check for syntax errors
        print("\n--- Apache Config Test ---")
        run_cmd(ssh, "apachectl configtest")

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
