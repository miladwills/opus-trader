import paramiko
import time

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"

def run_cmd(ssh, cmd):
    print(f"> {cmd}")
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
        print("Connected.")
        
        # 1. Identify what is on port 80
        print("\n--- Processes on Port 80 ---")
        run_cmd(ssh, "netstat -tulpn | grep :80")
        
        # 2. Kill them
        print("\n--- Killing Process on Port 80 ---")
        # fuser -k 80/tcp is a strong way to kill whatever is there
        run_cmd(ssh, "fuser -k 80/tcp")
        time.sleep(1)
        
        # 3. Stop potential culprits
        run_cmd(ssh, "systemctl stop nginx")
        run_cmd(ssh, "systemctl stop apache2")
        time.sleep(2)
        
        # 4. Start Apache
        print("\n--- Starting Apache ---")
        run_cmd(ssh, "systemctl start apache2")
        time.sleep(3)
        
        # 5. Check Status
        print("\n--- Final Apache Status ---")
        out = run_cmd(ssh, "systemctl status apache2")
        
        if "active (running)" in out:
            print("SUCCESS: Apache is running.")
        else:
            print("FAILURE: Apache still not running.")
            run_cmd(ssh, "tail -n 10 /var/log/apache2/error.log")

        ssh.close()
        
    except Exception as e:
        print(f"Operation Failed: {e}")

if __name__ == "__main__":
    main()
