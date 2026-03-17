import paramiko
import sys

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
BASE_DIR = "/var/www/opus_trader"

def run_cmd(ssh, cmd):
    print(f"CMD: {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    # print(out) # debug
    return out

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        # 1. Find file with FastAPI
        print("Searching for FastAPI instance...")
        # Grep for 'app = FastAPI' or 'FastAPI('
        cmd = f"grep -r 'FastAPI' {BASE_DIR}"
        out = run_cmd(ssh, cmd)
        print(f"Grep Results:\n{out}")
        
        target_file = None
        for line in out.split('\n'):
            if "main.py" in line or "app.py" in line:
                target_file = line.split(':')[0]
                break
        
        if not target_file and out:
            # check first result
            target_file = out.split('\n')[0].split(':')[0]

        if target_file:
            print(f"\nReading Target File: {target_file}")
            content = run_cmd(ssh, f"cat {target_file}")
            print("--- FILE CONTENT START ---")
            print(content)
            print("--- FILE CONTENT END ---")
        else:
            print("Could not locate FastAPI app definition.")

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
