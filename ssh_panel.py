# -*- coding: utf-8 -*-
#!/usr/bin/env python3

import os
import sys
import json
import re
import subprocess
import datetime
import tempfile
import shutil
import pwd
import bcrypt
import secrets
import string

SSH_CONFIG = "/etc/ssh/sshd_config"
USER_DB = "/opt/ssh_vpn_users.json"
VPN_GROUP = "vpnusers"
SHELL_NOLOGIN = "/usr/sbin/nologin"
SHELL_FALSE = "/bin/false"

def check_root():
    if os.geteuid() != 0:
        print("ERROR: Script must be run as root")
        sys.exit(1)

def init_user_db():
    if not os.path.exists(USER_DB):
        with open(USER_DB, "w") as f:
            json.dump({"users": []}, f)
        os.chmod(USER_DB, 0o600)

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def generate_password(length=12) -> str:
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

def load_users():
    if not os.path.exists(USER_DB):
        return {"users": []}
    try:
        with open(USER_DB, "r") as f:
            return json.load(f)
    except:
        return {"users": []}

def save_users(data):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as tf:
        json.dump(data, tf)
        temp_path = tf.name
    shutil.move(temp_path, USER_DB)
    os.chmod(USER_DB, 0o600)

def user_exists_system(username):
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False

def user_exists_db(username):
    data = load_users()
    return any(u['username'] == username for u in data['users'])

def add_user_to_db(username, password):
    data = load_users()
    data['users'].append({
        "username": username,
        "password": hash_password(password),
        "created": datetime.datetime.now().isoformat()
    })
    save_users(data)

def remove_user_from_db(username):
    data = load_users()
    data['users'] = [u for u in data['users'] if u['username'] != username]
    save_users(data)

def add_vpn_user():
    while True:
        username = input("Enter username (alphanumeric): ").strip()
        if not username.isalnum():
            print("ERROR: Username must be alphanumeric")
            continue
        if user_exists_system(username):
            print("ERROR: User exists in system")
            continue
        if user_exists_db(username):
            print("ERROR: User exists in VPN DB")
            continue
        break

    password = generate_password()
    shell = SHELL_NOLOGIN if os.path.exists(SHELL_NOLOGIN) else SHELL_FALSE

    try:
        subprocess.run(["useradd", "-M", "-s", shell, username], check=True)
        subprocess.run(["chpasswd"], input=f"{username}:{password}", text=True, check=True)
        subprocess.run(["groupadd", "-f", VPN_GROUP], check=True)
        subprocess.run(["usermod", "-aG", VPN_GROUP, username], check=True)
        add_user_to_db(username, password)
        print(f"User {username} created successfully")
        print(f"Generated password (copy it now, it won’t be shown again): {password}")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to add user: {e}")

def remove_vpn_user():
    username = input("Enter username to remove: ").strip()
    if not username:
        return
    if not user_exists_system(username):
        print("ERROR: User does not exist")
        return
    confirm = input(f"Confirm remove {username}? (y/N): ").strip().lower()
    if not confirm.startswith("y"):
        return
    try:
        subprocess.run(["userdel", "-r", username], check=True, stderr=subprocess.DEVNULL)
        remove_user_from_db(username)
        print(f"User {username} removed")
    except subprocess.CalledProcessError:
        print("ERROR: Failed to remove user")

def list_users():
    data = load_users()
    if not data['users']:
        print("No VPN users found")
        return
    print("VPN Users:")
    for u in data['users']:
        print(f"- {u['username']} | created: {u['created']} | password: [HIDDEN]")

def add_ssh_port():
    port = input("Enter new SSH port for VPN clients: ").strip()
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        print("ERROR: Invalid port")
        return
    port = int(port)

    with open(SSH_CONFIG, "r") as f:
        lines = f.read().splitlines()

    existing_ports = [int(m.group(1)) for l in lines if (m:=re.match(r'^\s*Port\s+(\d+)', l))]
    if port in existing_ports:
        print(f"Port {port} already exists")
        return

    insert_index = 0
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("match"):
            insert_index = i
            break
    lines.insert(insert_index, f"Port {port}")

    with open(SSH_CONFIG, "w") as f:
        f.write("\n".join(lines) + "\n")

    try:
        subprocess.run(["systemctl", "restart", "ssh"], check=True)
        print(f"SSH now listens on port {port}")
    except subprocess.CalledProcessError:
        print("ERROR: Failed to restart SSH, check manually")

def main_menu():
    while True:
        print("""
========== SSH VPN MANAGER ==========
1) Add VPN User
2) Remove VPN User
3) List VPN Users
4) Add SSH Port for VPN Clients
5) Exit
==================================
""")
        choice = input("Select: ").strip()
        if choice == "1":
            add_vpn_user()
        elif choice == "2":
            remove_vpn_user()
        elif choice == "3":
            list_users()
        elif choice == "4":
            add_ssh_port()
        elif choice == "5":
            sys.exit(0)
        else:
            print("ERROR: Invalid option")

if __name__ == "__main__":
    check_root()
    init_user_db()
    main_menu()
