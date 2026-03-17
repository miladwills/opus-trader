
import paramiko

VPS_IP = '178.18.245.6'
VPS_USER = 'root'
VPS_PASS = 'aA0109587045'

def run_ssh_command(ssh, command):
    print(f"Running: {command}")
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        print(f"Connecting to {VPS_IP}...")
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS)
        print("Connected.")

        # List all enabled service unit files
        print("Listing enabled service unit files:")
        services = run_ssh_command(ssh, "systemctl list-unit-files --state=enabled | grep -E 'bot|trader|sage|app|process'")
        print(services)
        
        # Also list active services just in case
        print("\nListing active services:")
        active = run_ssh_command(ssh, "systemctl list-units --type=service --state=running | grep -E 'bot|trader|sage|app|process'")
        print(active)

        # Specifically look for the sage-bot service file location since we saw it running from /var/www/sage-bot
        print("\nSearching for sage-bot service file:")
        sage_service = run_ssh_command(ssh, "find /etc/systemd/system -name '*sage*'")
        print(sage_service)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
