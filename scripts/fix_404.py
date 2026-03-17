import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
BASE_DIR = "/var/www/opus_trader"

ROUTE_CODE = """
# [AUTO-ADDED] Root Route
@app.route('/')
def index():
    try:
        with open('dashboard.html', 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error loading dashboard: {e}"
"""

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        # 1. Read app.py
        print("Reading app.py...")
        stdin, stdout, stderr = ssh.exec_command(f"cat {BASE_DIR}/app.py")
        content = stdout.read().decode()
        
        if "@app.route('/')" in content:
            print("Route already exists!")
        else:
            print("Injecting route...")
            # Insert before main execution block
            if 'if __name__ == "__main__":' in content:
                new_content = content.replace('if __name__ == "__main__":', ROUTE_CODE + '\nif __name__ == "__main__":')
            else:
                # Fallback: append to end
                new_content = content + ROUTE_CODE

            # Write back
            sftp = ssh.open_sftp()
            with sftp.file(f"{BASE_DIR}/app.py", 'w') as f:
                f.write(new_content)
            sftp.close()
            print("File updated.")
            
            # Restart service
            print("Restarting opus_trader service...")
            ssh.exec_command("systemctl restart opus_trader")
            print("Service restarted.")

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
