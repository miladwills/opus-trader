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
        
        # 1. List directory structure (excluding venv and node_modules for noise)
        print("--- Directory Structure ---")
        out = run_cmd(ssh, f"find {BASE_DIR} -maxdepth 2 -not -path '*/.*' -not -path '*/venv*' -not -path '*/node_modules*'")
        print(out)
        
        # 2. Grep for FastAPI excluding scripts
        print("\n--- Grep 'FastAPI' (excluding scripts) ---")
        # Grep, filter out 'scripts/' and matching lines, just files
        out = run_cmd(ssh, f"grep -l 'FastAPI' {BASE_DIR}/**/*.py | grep -v 'scripts/'")
        print(out)
        
        target = None
        if out:
             target = out.split('\n')[0].strip()
        
        if target:
            print(f"\n--- Content of {target} ---")
            cat_out = run_cmd(ssh, f"cat {target}")
            print(cat_out)

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
