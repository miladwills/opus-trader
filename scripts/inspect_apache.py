import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        # List files
        stdin, stdout, stderr = ssh.exec_command("ls /etc/apache2/sites-enabled/")
        files = stdout.read().decode().strip().split()
        
        print(f"Files found: {files}")
        
        for f in files:
            print(f"\n--- {f} ---")
            stdin, stdout, stderr = ssh.exec_command(f"cat /etc/apache2/sites-enabled/{f}")
            print(stdout.read().decode())
            
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
