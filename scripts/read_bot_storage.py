import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
FILE = "/var/www/opus_trader/services/bot_storage_service.py"

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        print(f"Reading {FILE}...")
        stdin, stdout, stderr = ssh.exec_command(f"cat {FILE}")
        print(stdout.read().decode())
        
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
