import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"

TARGET_FILES = [
    "/etc/apache2/sites-available/madowlab-le-ssl.conf",
    "/etc/apache2/sites-available/madowlab.conf"
]

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        for f in TARGET_FILES:
            print(f"fixing {f}...")
            # Read
            cmd_read = f"cat {f}"
            stdin, stdout, stderr = ssh.exec_command(cmd_read)
            content = stdout.read().decode()
            
            if "8010" in content:
                print("Found 8010, replacing with 8000...")
                new_content = content.replace("8010", "8000")
                
                # Write back (using a temporary file trick or simple echo if content is small, but python paramiko sftp is safer)
                sftp = ssh.open_sftp()
                with sftp.file(f, 'w') as remote_file:
                    remote_file.write(new_content)
                sftp.close()
                print("Updated.")
            else:
                print("No 8010 found (or already fixed).")
        
        print("Restarting Apache...")
        ssh.exec_command("systemctl restart apache2")
        print("Done.")
        
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
