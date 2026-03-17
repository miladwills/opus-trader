
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
    if out: print(f"STDOUT: {out}")
    if err: print(f"STDERR: {err}")
    return out

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        print(f"Connecting to {VPS_IP}...")
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS)
        
        # 1. Disable sagebot-runner
        print("Disabling sagebot-runner.service...")
        run_ssh_command(ssh, "systemctl stop sagebot-runner.service")
        run_ssh_command(ssh, "systemctl disable sagebot-runner.service")
        
        # 2. Ensure opus_trader is restarted and healthy
        print("Restarting opus_trader to ensure it takes over clearly...")
        run_ssh_command(ssh, "systemctl restart opus_trader")
        time.sleep(5)
        
        # 3. Verify Port 8000
        print("Verifying Port 8000 ownership...")
        run_ssh_command(ssh, "netstat -tulpn | grep :8000")
        
        # 4. Verify Service Status
        print("Checking opus_trader status...")
        run_ssh_command(ssh, "systemctl status opus_trader --no-pager")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
