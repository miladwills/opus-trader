import paramiko
import time
import sys

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
    return out, err

def main():
    print(f"Connecting to {HOST}...")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        print("Connected.")
        
        # 1. Check System
        print("\n--- System Status ---")
        run_cmd(ssh, "uptime")
        run_cmd(ssh, "df -h /")
        run_cmd(ssh, "free -m")

        # 2. Check Service
        print("\n--- Service Status ---")
        # Try to guess service name or check python processes
        out, _ = run_cmd(ssh, "systemctl list-units --type=service --state=running | grep opus")
        
        service_name = "opus_trader"
        status_out, _ = run_cmd(ssh, f"systemctl status {service_name}")
        
        if "could not be found" in status_out:
             print("opus_trader service not found. Checking for python processes...")
             run_cmd(ssh, "ps aux | grep python")
             # Try listing all systemd services to find it
             run_cmd(ssh, "ls /etc/systemd/system/ | grep .service")
        else:
             print(f"{service_name} status check completed.")

        # 3. Check Web Server Logs
        print("\n--- Apache Error Log (Last 20 lines) ---")
        run_cmd(ssh, "tail -n 20 /var/log/apache2/error.log")

        # 4. Attempt Restart
        print("\n--- Attempting Restart ---")
        # Try restarting opus_trader if it exists, otherwise just say we can't
        if "could not be found" not in status_out:
            print(f"Restarting {service_name}...")
            run_cmd(ssh, f"systemctl restart {service_name}")
            time.sleep(3)
            run_cmd(ssh, f"systemctl status {service_name}")
        
        # 5. Check if Apache is running
        print("\n--- Apache Status ---")
        run_cmd(ssh, "systemctl status apache2")

        ssh.close()
        
    except Exception as e:
        print(f"Connection Failed: {e}")

if __name__ == "__main__":
    main()
