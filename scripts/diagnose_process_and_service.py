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
        
        # 1. Check process on port 8000
        print("--- Checking Port 8000 ---")
        out = run_cmd(ssh, "netstat -tulpn | grep :8000")
        print(out)
        
        if out:
            parts = out.split()
            # pid/name is usually the last column or near it. e.g. "1234/python"
            # format: Proto Recv-Q Send-Q Local Address Foreign Address State PID/Program name
            pid_part = parts[-1]
            if '/' in pid_part:
                pid = pid_part.split('/')[0]
                print(f"\n--- Process Info for PID {pid} ---")
                run_cmd(ssh, f"ps -fp {pid}")
                run_cmd(ssh, f"cat /proc/{pid}/cmdline | tr '\\0' ' '")

                # Check current working directory of the process
                print(f"\n--- CWD for PID {pid} ---")
                run_cmd(ssh, f"ls -l /proc/{pid}/cwd")

        # 2. Check systemd service definition
        print("\n--- Service Definition ---")
        out = run_cmd(ssh, "cat /etc/systemd/system/opus_trader.service")
        print(out)
        
        # 3. Check app_lf.py just in case
        print(f"\n--- Checking app_lf.py content type ---")
        run_cmd(ssh, f"head -n 20 {BASE_DIR}/app_lf.py")

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
