import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
FILE_PATH = "/var/www/opus_trader/services/grid_bot_service.py"

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        # Read file
        print(f"Reading {FILE_PATH}...")
        stdin, stdout, stderr = ssh.exec_command(f"cat {FILE_PATH}")
        content = stdout.read().decode()
        
        # The target pattern to replace:
        # We want to remove the block that starts with "    orders = orders_resp.get("data", [])" 
        # and ends with "return 0" inside _cancel_opening_orders_only
        # But specifically, the chunk after the return statement.
        
        # We can look for the method definition and replace it entirely with the clean version
        
        old_method_signature = "def _cancel_opening_orders_only(self, bot: Dict[str, Any], symbol: str) -> int:"
        
        # If we can't do exact block replacement easily, let's look for the known buggy block 
        if old_method_signature in content:
            # We will construct a "clean" file content line by line
            lines = content.split('\n')
            new_lines = []
            skip = False
            
            for i, line in enumerate(lines):
                # Start of method
                if old_method_signature in line:
                    new_lines.append(line)
                    continue
                
                # The line that IS valid
                if 'return self._cancel_non_reducing_bot_orders(bot, symbol)' in line:
                    new_lines.append(line)
                    # Start skipping the dead code that follows until the next method
                    skip = True
                    continue
                
                # Stop skipping when we hit the next method
                if skip and 'def _handle_upnl_hard_stoploss' in line:
                    skip = False
                    new_lines.append(line)
                    continue
                
                if not skip:
                    new_lines.append(line)
            
            new_content = '\n'.join(new_lines)
            
            if len(new_content) < len(content):
                print("Code cleanup applied locally. Uploading...")
                sftp = ssh.open_sftp()
                with sftp.file(FILE_PATH, 'w') as f:
                    f.write(new_content)
                sftp.close()
                print("File uploaded.")
                
                print("Restarting service...")
                ssh.exec_command("systemctl restart opus_trader")
                print("Service restarted.")
            else:
                print("No changes needed or pattern not found.")
                # print(content[1410:1460]) # debug
        else:
             print("Method signature not found.")

        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
