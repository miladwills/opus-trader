
import paramiko

VPS_IP = '178.18.245.6'
VPS_USER = 'root'
VPS_PASS = 'aA0109587045'

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS, look_for_keys=False, allow_agent=False)
        stdin, stdout, stderr = ssh.exec_command("journalctl -u opus_trader -n 50 --no-pager")
        print(stdout.read().decode())
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
