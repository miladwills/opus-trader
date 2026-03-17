
import paramiko

VPS_IP = '178.18.245.6'
VPS_USER = 'root'
VPS_PASS = 'aA0109587045'

def run_ssh_command(ssh, command):
    print(f"Running: {command}")
    stdin, stdout, stderr = ssh.exec_command(command)
    # Don't fail on exit code, we want to see output even if service is failed
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(f"STDOUT:\n{out}\n")
    if err: print(f"STDERR:\n{err}\n")
    return out

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        print(f"Connecting to {VPS_IP}...")
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS)
        
        print("1. Checking opus_trader service status...")
        run_ssh_command(ssh, "systemctl status opus_trader --no-pager")
        
        print("2. Checking listening ports...")
        run_ssh_command(ssh, "netstat -tulpn | grep -E 'python|8000|8010'")
        
        print("3. Checking recent service logs...")
        run_ssh_command(ssh, "journalctl -u opus_trader -n 50 --no-pager")
        
        print("4. Checking Apache error logs...")
        run_ssh_command(ssh, "tail -n 20 /var/log/apache2/error.log")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
