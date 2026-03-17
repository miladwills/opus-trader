
import paramiko
import time

VPS_IP = '178.18.245.6'
VPS_USER = 'root'
VPS_PASS = 'aA0109587045'

def run_ssh_command(ssh, command):
    print(f"Running: {command}")
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(f"STDOUT: {out}")
    if err:
        print(f"STDERR: {err}")
    return exit_status, out, err

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        print(f"Connecting to {VPS_IP}...")
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS)
        print("Connected.")

        # 1. Stop the service first
        run_ssh_command(ssh, "systemctl stop opus_trader")

        # 2. Kill any rogue process on port 8000
        # Using fuser -k 8000/tcp or finding pid and killing
        print("Checking for rogue process on port 8000...")
        _, pid_out, _ = run_ssh_command(ssh, "lsof -t -i:8000")
        if pid_out:
            print(f"Found process {pid_out} on port 8000. Killing...")
            run_ssh_command(ssh, f"kill -9 {pid_out}")
        else:
            print("No process found on port 8000.")

        # 3. Update the service file
        # We want to change Environment="APP_PORT=8010" to Environment="APP_PORT=8000"
        print("Updating /etc/systemd/system/opus_trader.service...")
        run_ssh_command(ssh, "sed -i 's/APP_PORT=8010/APP_PORT=8000/g' /etc/systemd/system/opus_trader.service")
        
        # Verify the change
        _, check_out, _ = run_ssh_command(ssh, "grep APP_PORT /etc/systemd/system/opus_trader.service")
        print(f"Service file check: {check_out}")

        # 4. Reload and Restart
        print("Reloading systemd and restarting service...")
        run_ssh_command(ssh, "systemctl daemon-reload")
        run_ssh_command(ssh, "systemctl restart opus_trader")

        print("Waiting 5 seconds for service to stabilize...")
        time.sleep(5)

        # 5. Verify
        print("Verifying service status...")
        run_ssh_command(ssh, "systemctl status opus_trader --no-pager")
        
        print("Verifying port 8000 is listening...")
        run_ssh_command(ssh, "netstat -tulpn | grep :8000")

        print("Testing local curl...")
        run_ssh_command(ssh, "curl -I http://127.0.0.1:8000/")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
