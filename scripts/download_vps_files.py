import paramiko
import os

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
FILES = [
    "/var/www/opus_trader/services/bot_storage_service.py",
    "/var/www/opus_trader/services/risk_manager_service.py",
    "/var/www/opus_trader/services/pnl_service.py",
    "/var/www/opus_trader/runner.py",
    "/var/www/opus_trader/app.py",
    "/var/www/opus_trader/scripts/self_check_safety.py"
]

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        sftp = ssh.open_sftp()
        
        os.makedirs("temp_vps_files", exist_ok=True)
        
        for remote_path in FILES:
            local_name = os.path.basename(remote_path)
            local_path = os.path.join("temp_vps_files", local_name)
            print(f"Downloading {remote_path} to {local_path}...")
            try:
                sftp.get(remote_path, local_path)
            except Exception as e:
                print(f"Failed to download {remote_path}: {e}")
            
        sftp.close()
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
