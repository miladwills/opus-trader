
import paramiko

VPS_IP = '178.18.245.6'
VPS_USER = 'root'
VPS_PASS = 'aA0109587045'

# Services to potentially disable
SERVICES_TO_DISABLE = [
    'madowlab-bot-worker.service',
    'mytrading-bot.service',
    # 'opustraderscalp.service' # This one sounds like it might be the scalp bot user mentioned earlier, proceed with caution?
    # User said "kill all other bots process", implying anything not "opus_trader" (the one we are fixing) should go.
]
# NOTE: user said "kill all other bots". 
# madowlab-bot-worker.service
# mytrading-bot.service
# opustraderscalp.service (The user's original issue was about 'madowlab.online' and 'Opus Trader'. Scalp might be a different strategy?)
# I will list them for the user to confirm or just disable them as requested "kill ALL other bots". 
# The request was "kill all other bots process to prevent them from conflicting again". 
# This implies aggressive cleanup.
# However, `opustraderscalp` sounds like a variant. 
# But `opus_trader.service` is the one running on 8000/8010.
# I will disable `madowlab-bot-worker.service` and `mytrading-bot.service` primarily.
# I will also look for the sage-bot definition.

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
        ssh.connect(VPS_IP, username=VPS_USER, password=VPS_PASS)
        
        # 1. Search for sage-bot service specifically since it was the PID conflict
        print("Finding sage-bot service...")
        run_ssh_command(ssh, "grep -r 'sage-bot' /etc/systemd/system/")

        # 2. Disable known conflicts
        services = ['madowlab-bot-worker.service', 'mytrading-bot.service']
        
        # Check if opustraderscalp should be disabled? The user said "kill all OTHER bots". 
        # madowlab.online seems to be the main goal. 
        # I'll disable sage-related things if found.
        
        for service in services:
            print(f"Disabling {service}...")
            run_ssh_command(ssh, f"systemctl stop {service}")
            run_ssh_command(ssh, f"systemctl disable {service}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
