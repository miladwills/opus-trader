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
        
        # 1. Check if it is a link or file
        print("Checking file type in sites-enabled...")
        run_cmd(ssh, "ls -l /etc/apache2/sites-enabled/madowlab-le-ssl.conf")
        
        # 2. Force replace in SITES-ENABLED directly
        print("Running sed replacement on sites-enabled...")
        run_cmd(ssh, "sed -i 's/:8010/:8000/g' /etc/apache2/sites-enabled/madowlab-le-ssl.conf")
        
        # 3. Verify change
        print("Verifying CONTENT in sites-enabled...")
        run_cmd(ssh, "grep 'ProxyPass' /etc/apache2/sites-enabled/madowlab-le-ssl.conf")
        
        # 4. Restart Apache
        print("Restarting Apache...")
        run_cmd(ssh, "systemctl restart apache2")
        
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
