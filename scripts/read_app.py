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
        
        # Check app.py
        print("--- Checking app.py ---")
        out = run_cmd(ssh, f"cat {BASE_DIR}/app.py")
        if "No such file" in out:
             print("app.py not found.")
        else:
             print(out)
             
        # Check app_lf.py
        print("\n--- Checking app_lf.py ---")
        out = run_cmd(ssh, f"cat {BASE_DIR}/app_lf.py")
        if "No such file" in out:
             print("app_lf.py not found.")
        else:
             print(out)

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
