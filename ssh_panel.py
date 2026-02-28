#!/usr/bin/env python3
import json
import os
import sys
import re
import subprocess
import pwd
import datetime
import tempfile
import shutil
import secrets
import string
from pathlib import Path

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'

class SSHVPNManager:
    def __init__(self):
        self.shell_nologin = "/usr/sbin/nologin"
        self.user_db = "/opt/ssh_vpn_users.json"
        self.ssh_config = "/etc/ssh/sshd_config"
        self.group_name = "vpnusers"

    # -------------------- SYSTEM CHECK --------------------

    def check_root(self):
        if os.geteuid() != 0:
            print(f"{Colors.RED}Run as root!{Colors.RESET}")
            sys.exit(1)

    def ensure_group_exists(self):
        try:
            subprocess.run(["getent", "group", self.group_name], check=True, stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            subprocess.run(["groupadd", self.group_name], check=True)

    def init_db(self):
        if not os.path.exists(self.user_db):
            with open(self.user_db, 'w') as f:
                json.dump({"users": []}, f, indent=2)
            os.chmod(self.user_db, 0o600)

    # -------------------- PASSWORD --------------------

    def generate_password(self, length=16):
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    # -------------------- USER DB --------------------

    def add_user_to_db(self, username):
        self.init_db()
        now = datetime.datetime.now(datetime.UTC).isoformat()

        with open(self.user_db, 'r') as f:
            data = json.load(f)

        data["users"].append({
            "username": username,
            "created": now,
            "last_password_change": now
        })

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            json.dump(data, tmp, indent=2)
            temp_path = tmp.name

        shutil.move(temp_path, self.user_db)
        os.chmod(self.user_db, 0o600)

    def update_password_date(self, username):
        with open(self.user_db, 'r') as f:
            data = json.load(f)

        now = datetime.datetime.now(datetime.UTC).isoformat()

        for user in data["users"]:
            if user["username"] == username:
                user["last_password_change"] = now

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            json.dump(data, tmp, indent=2)
            temp_path = tmp.name

        shutil.move(temp_path, self.user_db)
        os.chmod(self.user_db, 0o600)

    def remove_user_from_db(self, username):
        with open(self.user_db, 'r') as f:
            data = json.load(f)

        data["users"] = [u for u in data["users"] if u["username"] != username]

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            json.dump(data, tmp, indent=2)
            temp_path = tmp.name

        shutil.move(temp_path, self.user_db)
        os.chmod(self.user_db, 0o600)

    # -------------------- SSH HARDENING --------------------

    def harden_ssh(self):
        with open(self.ssh_config, 'r') as f:
            content = f.read()

        if "Match Group vpnusers" not in content:
            with open(self.ssh_config, 'a') as f:
                f.write(f"""

Match Group {self.group_name}
    AllowTcpForwarding yes
    X11Forwarding no
    AllowAgentForwarding no
    PermitTunnel no
    ForceCommand echo 'This account is restricted to SSH tunneling only'
""")

        subprocess.run(["systemctl", "restart", "ssh"], check=True)

    # -------------------- USER MANAGEMENT --------------------

    def add_user(self):
        username = input("Username: ").strip()

        if not re.match(r'^[a-zA-Z0-9]+$', username):
            print("Alphanumeric only.")
            return

        try:
            pwd.getpwnam(username)
            print("User exists.")
            return
        except KeyError:
            pass

        password = self.generate_password()

        subprocess.run(["useradd", "-M", "-s", self.shell_nologin, "-G", self.group_name, username], check=True)
        subprocess.run(["chpasswd"], input=f"{username}:{password}", text=True, check=True)

        self.add_user_to_db(username)

        print(f"{Colors.GREEN}User created!{Colors.RESET}")
        print(f"{Colors.YELLOW}Password (save it now): {password}{Colors.RESET}")

    def remove_user(self):
        username = input("Username to remove: ").strip()

        subprocess.run(["userdel", "-r", username], stderr=subprocess.DEVNULL)
        self.remove_user_from_db(username)

        print("User removed.")

    def list_users(self):
        self.init_db()
        with open(self.user_db, 'r') as f:
            data = json.load(f)

        print("\nVPN USERS:")
        for user in data["users"]:
            print(f"- {user['username']} | Created: {user['created']} | Last change: {user['last_password_change']}")

    def change_password(self):
        username = input("Username: ").strip()
        password = self.generate_password()

        subprocess.run(["chpasswd"], input=f"{username}:{password}", text=True, check=True)
        self.update_password_date(username)

        print(f"{Colors.GREEN}Password updated!{Colors.RESET}")
        print(f"{Colors.YELLOW}New password: {password}{Colors.RESET}")

    # -------------------- SSH PORT --------------------

    def change_port(self):
        port = input("New SSH port: ").strip()

        if not port.isdigit():
            print("Invalid port.")
            return

        shutil.copy2(self.ssh_config, f"{self.ssh_config}.bak")

        with open(self.ssh_config, 'r') as f:
            lines = f.readlines()

        lines = [l for l in lines if not re.match(r'^\s*#?\s*Port\s+', l)]
        lines.append(f"Port {port}\n")

        with open(self.ssh_config, 'w') as f:
            f.writelines(lines)

        subprocess.run(["systemctl", "restart", "ssh"], check=True)
        print(f"SSH now on port {port}")

    # -------------------- MENU --------------------

    def menu(self):
        while True:
            print(f"""
{Colors.CYAN}====== SSH VPN MANAGER ======{Colors.RESET}
1) Add User
2) Remove User
3) List Users
4) Change User Password
5) Change SSH Port
6) Harden SSH (recommended first run)
7) Exit
""")
            choice = input("Select: ").strip()

            if choice == "1":
                self.add_user()
            elif choice == "2":
                self.remove_user()
            elif choice == "3":
                self.list_users()
            elif choice == "4":
                self.change_password()
            elif choice == "5":
                self.change_port()
            elif choice == "6":
                self.harden_ssh()
                print("SSH hardened.")
            elif choice == "7":
                sys.exit(0)
            else:
                print("Invalid.")

    def run(self):
        self.check_root()
        self.ensure_group_exists()
        self.init_db()
        self.menu()

if __name__ == "__main__":
    SSHVPNManager().run()
