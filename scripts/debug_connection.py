
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
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS, look_for_keys=False, allow_agent=False)
        
        # 1. Test local connectivity
        print("Testing local connectivity to app...")
        run_ssh_command(ssh, "curl -v http://127.0.0.1:8000/")
        
        # 2. Check Apache config again
        print("Checking Apache config...")
        run_ssh_command(ssh, "cat /etc/apache2/sites-enabled/madowlab-le-ssl.conf")
        
        # 3. Restart Apache to be sure
        print("Restarting Apache...")
        run_ssh_command(ssh, "systemctl restart apache2")
        time.sleep(3)
        
        # 4. Check status
        print("Apache status...")
        run_ssh_command(ssh, "systemctl status apache2 --no-pager")
        
        # 5. Check error log again (tail)
        print("Latest Apache error logs:")
        run_ssh_command(ssh, "tail -n 20 /var/log/apache2/error.log")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
