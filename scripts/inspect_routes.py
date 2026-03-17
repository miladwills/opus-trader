import paramiko
import time

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
BASE_DIR = "/var/www/opus_trader"

def run_cmd(ssh, cmd):
    print(f"\n> {cmd}")
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
        
        # 1. List root dir
        print("\n--- Listing Root Dir ---")
        run_cmd(ssh, f"ls -F {BASE_DIR}")
        
        # 2. Search for FastAPI app definition
        print("\n--- Searching for FastAPI app ---")
        # specific for "app =" or "FastAPI("
        grep_cmd = f"grep -r 'FastAPI' {BASE_DIR} | grep '.py'"
        results = run_cmd(ssh, grep_cmd)
        
        # 3. If found, read the file
        if results:
            lines = results.split('\n')
            first_match = lines[0].split(':')[0] # filename
            print(f"\n--- Reading {first_match} ---")
            run_cmd(ssh, f"cat {first_match}")
            
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
