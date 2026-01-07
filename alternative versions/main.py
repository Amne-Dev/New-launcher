import tkinter as tk
from tkinter import ttk, messagebox
import minecraft_launcher_lib
import subprocess
import threading
import os
import json
from typing import cast, Any

# --- Helpers ---
def get_minecraft_dir():
    return minecraft_launcher_lib.utils.get_minecraft_directory()

def is_version_installed(version_id):
    minecraft_dir = get_minecraft_dir()
    path = os.path.join(minecraft_dir, "versions", version_id, f"{version_id}.json")
    return os.path.exists(path)

# --- Main App ---
class MinecraftLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("Python Universal Launcher")
        self.root.geometry("450x480")
        self.minecraft_dir = get_minecraft_dir()
        self.config_file = "launcher_config.json"
        self.last_version = ""

        # UI Layout
        tk.Label(root, text="Universal Offline Launcher", font=("Arial", 16, "bold")).pack(pady=10)

        # Username Input
        tk.Label(root, text="Username:").pack()
        self.user_entry = tk.Entry(root, justify='center')
        self.user_entry.pack(pady=5)

        # Loader Selection
        tk.Label(root, text="Select Loader:").pack(pady=(10, 0))
        self.loader_var = tk.StringVar(value="Vanilla")
        self.loader_dropdown = ttk.Combobox(root, textvariable=self.loader_var, state="readonly", values=["Vanilla", "Forge", "Fabric", "Third-Party"])
        self.loader_dropdown.pack(pady=5)
        self.loader_dropdown.bind("<<ComboboxSelected>>", lambda e: self.load_versions())

        # Version Selection
        tk.Label(root, text="Select Version (✅ = Installed):").pack(pady=(10, 0))
        self.version_var = tk.StringVar()
        self.version_dropdown = ttk.Combobox(root, textvariable=self.version_var, state="readonly", width=40)
        self.version_dropdown.pack(pady=5)

        # Status and Progress
        self.status_label = tk.Label(root, text="Ready", fg="blue")
        self.status_label.pack(pady=5)
        
        self.progress_bar = ttk.Progressbar(root, orient='horizontal', length=350, mode='determinate')
        self.progress_bar.pack(pady=5)

        # Launch Button
        self.launch_btn = tk.Button(root, text="PLAY", font=("Arial", 12, "bold"), 
                                   bg="#4CAF50", fg="white", width=20, command=self.start_launch)
        self.launch_btn.pack(pady=20)

        # Load data then fetch
        self.load_from_config()
        self.load_versions()

    def load_from_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    self.user_entry.insert(0, data.get("username", "Steve"))
                    self.loader_var.set(data.get("loader", "Vanilla"))
                    self.last_version = data.get("last_version", "")
            except:
                self.user_entry.insert(0, "Steve")
        else:
            self.user_entry.insert(0, "Steve")

    def save_to_config(self):
        data = {
            "username": self.user_entry.get().strip(),
            "loader": self.loader_var.get(),
            "last_version": self.version_var.get()
        }
        with open(self.config_file, "w") as f:
            json.dump(data, f)

    def load_versions(self):
        loader = self.loader_var.get()
        self.status_label.config(text=f"Updating {loader} list...", fg="blue")
        threading.Thread(target=self._fetch_logic, args=(loader,), daemon=True).start()

    def _fetch_logic(self, loader):
        try:
            display_list = []
            if loader == "Vanilla":
                versions = minecraft_launcher_lib.utils.get_available_versions(self.minecraft_dir)
                raw_list = [v['id'] for v in versions if v['type'] == 'release']
            elif loader == "Fabric":
                raw_list = minecraft_launcher_lib.fabric.get_stable_minecraft_versions()
            elif loader == "Forge":
                # Updated logic to avoid the Pylance attribute error
                # We fetch vanilla releases, because Forge can be installed on most of them
                versions = minecraft_launcher_lib.utils.get_available_versions(self.minecraft_dir)
                raw_list = [v['id'] for v in versions if v['type'] == 'release']
            else:
                path = os.path.join(self.minecraft_dir, "versions")
                if os.path.exists(path):
                    raw_list = [f for f in os.listdir(path) if os.path.isdir(os.path.join(path, f))]
                else:
                    raw_list = []

            for v_id in raw_list:
                display_list.append(f"✅ {v_id}" if is_version_installed(v_id) else v_id)
            
            self.root.after(0, lambda: self.update_dropdown_items(display_list))
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.status_label.config(text=f"Error: {err}", fg="red"))

    def update_dropdown_items(self, items):
        self.version_dropdown.config(values=items)
        if self.last_version in items:
            self.version_dropdown.set(self.last_version)
        elif items:
            self.version_dropdown.current(0)
        self.status_label.config(text=f"{self.loader_var.get()} ready", fg="black")

    def start_launch(self):
        selected_text = self.version_var.get()
        loader = self.loader_var.get()
        if not selected_text: return

        self.save_to_config()
        version = selected_text.replace("✅ ", "")
        username = self.user_entry.get().strip() or "Steve"
        self.launch_btn.config(state="disabled", text="Running...")
        threading.Thread(target=self.launch_logic, args=(version, username, loader), daemon=True).start()

    def launch_logic(self, version, username, loader):
        callback = {
            "setStatus": lambda text: self.root.after(0, lambda: self.status_label.config(text=text)),
            "setProgress": lambda value: self.root.after(0, lambda: self.progress_bar.config(value=value)),
            "setMax": lambda value: self.root.after(0, lambda: self.progress_bar.config(maximum=value))
        }

        try:
            launch_id = version
            try:
                if loader == "Fabric":
                    minecraft_launcher_lib.fabric.install_fabric(version, self.minecraft_dir, callback=cast(Any, callback))
                elif loader == "Forge":
                    # find_forge_version returns the latest Forge ID for that MC version
                    forge_v = minecraft_launcher_lib.forge.find_forge_version(version)
                    if forge_v:
                        minecraft_launcher_lib.forge.install_forge_version(forge_v, self.minecraft_dir, callback=cast(Any, callback))
                        launch_id = forge_v
                    else:
                        raise Exception(f"No Forge version found for {version}")
                else:
                    minecraft_launcher_lib.install.install_minecraft_version(version, self.minecraft_dir, callback=cast(Any, callback))
            except Exception as e:
                if str(e) == "'client'" and is_version_installed(version):
                    pass 
                else:
                    raise e

            options = {"username": username, "uuid": "", "token": ""}
            command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, self.minecraft_dir, cast(Any, options))
            
            self.root.after(0, self.root.withdraw)
            subprocess.call(command)
            self.root.after(0, self.root.deiconify)
            
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, lambda err=err_msg: messagebox.showerror("Launch Error", f"An error occurred:\n{err}"))
        finally:
            self.root.after(0, lambda: self.launch_btn.config(state="normal", text="PLAY"))
            self.root.after(0, self.load_versions)

if __name__ == "__main__":
    root = tk.Tk()
    app = MinecraftLauncher(root)
    root.mainloop()