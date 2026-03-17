import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
BASE_DIR = "/var/www/opus_trader"

def run_cmd(ssh, cmd):
    print(f"\n> {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    return out

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        # Head of app.py
        print("--- Head of app.py ---")
        out = run_cmd(ssh, f"head -n 30 {BASE_DIR}/app.py")
        print(out)
        
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
