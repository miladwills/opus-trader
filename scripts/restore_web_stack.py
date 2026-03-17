
import paramiko
import time

VPS_IP = '178.18.245.6'
VPS_USER = 'root'
VPS_PASS = 'aA0109587045'

def run_ssh_command(ssh, command):
    print(f"\n> {command}")
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
        # Use explicit authentication to bypass banner issues and key conflicts
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS, look_for_keys=False, allow_agent=False)
        print("Connected successfully.")

        # 1. Stop services
        print("\n--- Stopping Services ---")
        run_ssh_command(ssh, "systemctl stop opus_trader")
        run_ssh_command(ssh, "systemctl stop apache2")

        # 2. Kill rogue processes on port 8000 and 80
        print("\n--- Clearing Ports 8000 and 80 ---")
        run_ssh_command(ssh, "fuser -k 8000/tcp")
        run_ssh_command(ssh, "fuser -k 80/tcp")
        time.sleep(2)
        
        # Double check with lsof/kill if fuser didn't get them all
        print("\n--- Verifying ports are clear ---")
        p8000 = run_ssh_command(ssh, "lsof -t -i:8000")
        if p8000:
            print(f"Killing remaining processes on 8000: {p8000}")
            run_ssh_command(ssh, f"kill -9 {p8000}")
            
        p80 = run_ssh_command(ssh, "lsof -t -i:80")
        if p80:
            print(f"Killing remaining processes on 80: {p80}")
            run_ssh_command(ssh, f"kill -9 {p80}")

        # 3. Start services
        print("\n--- Restarting Services ---")
        run_ssh_command(ssh, "systemctl daemon-reload")
        run_ssh_command(ssh, "systemctl start opus_trader")
        time.sleep(3) # Give Flask a moment to bind
        run_ssh_command(ssh, "systemctl start apache2")

        # 4. Verification and Debugging
        print("\n--- Debugging Information ---")
        print("Opus Trader Service Definition:")
        run_ssh_command(ssh, "cat /etc/systemd/system/opus_trader.service")
        
        print("\nApache Configuration:")
        run_ssh_command(ssh, "cat /etc/apache2/sites-enabled/*.conf")

        print("\n--- Final Verification ---")
        print("\nChecking local app (port 8000) - root:")
        run_ssh_command(ssh, "curl -I http://127.0.0.1:8000/")
        
        print("\nChecking local app (port 8000) - neutral-scan API:")
        run_ssh_command(ssh, "curl -v http://127.0.0.1:8000/api/neutral-scan")
        
        print("\nChecking Apache status:")
        run_ssh_command(ssh, "systemctl status apache2 --no-pager")
        
        print("\nChecking opus_trader status:")
        run_ssh_command(ssh, "systemctl status opus_trader --no-pager")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
