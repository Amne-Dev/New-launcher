"""
nlc.ui.screens.accounts - Account management modals and login flows
"""

import logging
import os
import threading
import time
import webbrowser
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from typing import cast
import requests

import minecraft_launcher_lib

from nlc.ui.theme import COLORS, FONT_FAMILY, derive_hover_color
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.net.ms_auth import MicrosoftDeviceAuth, MSA_CLIENT_ID
from nlc.net.elyby_auth import ElyByAuth

logger = logging.getLogger(__name__)

class AccountsScreenMixin:
    """Mixin providing profile/account menus, addition modals, and authentication flows."""
    def toggle_profile_menu(self):
        if hasattr(self, 'profile_menu') and self.profile_menu:
            try:
                if self.profile_menu.winfo_exists():
                    print("Closing existing profile menu")
                    self.profile_menu.destroy()
                    self.profile_menu = None
                    return
            except:
                self.profile_menu = None

        print("Opening profile menu")
        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
        menu.config(bg=COLORS['card_bg'], highlightthickness=1, highlightbackground=COLORS.get('border_subtle', '#2D3139'))
        menu.transient(self.root)
        menu.attributes('-topmost', True)
        self.profile_menu = menu

        # Position with screen bounds check
        try:
            x = self.sidebar.winfo_rootx() + self.sidebar.winfo_width()
            y = self.profile_frame.winfo_rooty()
            
            # Check screen bounds
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            
            # Adjust if menu would go off-screen
            if x + 250 > screen_w:
                x = self.sidebar.winfo_rootx() - 250
            if y + 300 > screen_h:
                y = screen_h - 300 - 10
                
            menu.geometry(f"250x300+{x}+{y}")
        except: 
            menu.geometry("250x300")

        tk.Label(menu, text="ACCOUNTS", font=(FONT_FAMILY, 10, "bold"), 
                bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", padx=15, pady=10)

        # Create Footer FIRST (so we can pack it to bottom)
        footer = tk.Frame(menu, bg=COLORS['bottom_bar_bg'], height=45)
        # Use pack(side="bottom") for footer first to ensure it stays visible!
        footer.pack(fill="x", side="bottom") 
        footer.pack_propagate(False)

        # Scrollable Area
        container = tk.Frame(menu, bg=COLORS['card_bg'])
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=COLORS['card_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        list_frame = tk.Frame(canvas, bg=COLORS['card_bg'])

        list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=list_frame, anchor="nw", width=230) # 250 - 20 padding/scrollbar
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar packing handled in refresh/configure
        
        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        self._bind_smooth_scroll(canvas, list_frame)
        
        # Update Scrollbar visibility
        def update_scroll_state(e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                scrollbar.pack(side="right", fill="y")
            else:
                scrollbar.pack_forget()
            self._bind_smooth_scroll(canvas, list_frame)

        list_frame.bind("<Configure>", update_scroll_state)

        if not self.profiles:
             tk.Label(list_frame, text="No profiles", bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(pady=10)
        else:
            for idx, p in enumerate(self.profiles):
                self.create_profile_item(list_frame, idx, p)

        add_acct_btn = self._make_btn(footer, "+ Add Account", style="text", font_size=9,
                                       command=self.open_add_account_modal)
        add_acct_btn.config(bg=COLORS['bottom_bar_bg'], fg=COLORS['text_primary'])
        add_acct_btn.bind("<Enter>", lambda e: add_acct_btn.config(fg="white"))
        add_acct_btn.bind("<Leave>", lambda e: add_acct_btn.config(fg=COLORS['text_primary']))
        add_acct_btn.pack(side="left", padx=10, fill="y")

        # Ensure menu is visible and focused with slide animation
        menu.update_idletasks()
        menu.deiconify()
        menu.lift()
        menu.focus_set()
        self._animate_menu_open(menu, 300, direction="down")
        menu.bind("<FocusOut>", lambda e: self._close_menu_delayed(menu))

    def _close_menu_delayed(self, menu):
        # Small delay to allow button clicks inside
        try:
            if menu and menu.winfo_exists():
                # Check if focus is still in the menu tree
                focused = self.root.focus_displayof()
                if focused and str(focused).startswith(str(menu)):
                    return  # Don't close if focus is still inside
                menu.destroy()
        except:
            pass

    def delete_profile(self, idx):
        if not self.profiles or idx < 0 or idx >= len(self.profiles): return
        
        p_name = self.profiles[idx].get("name", "Account")
        display_name = self._get_streamer_safe_name(p_name)
        if custom_askyesno("Remove Account", f"Are you sure you want to remove account '{display_name}'?"):
            del self.profiles[idx]
            
            # Reset index if needed
            if self.current_profile_index >= len(self.profiles):
                self.current_profile_index = max(0, len(self.profiles) - 1)
            
            if not self.profiles:
                self.create_default_profile()
            
            # Update UI first, then save to avoid redundant syncs
            self.update_active_profile()
            self.save_config(sync_ui=False)
            
            # Close menu to refresh
            if hasattr(self, 'profile_menu') and self.profile_menu:
                try:
                    if self.profile_menu.winfo_exists():
                        self.profile_menu.destroy()
                except:
                    pass

    def create_profile_item(self, parent, idx, profile):
        is_active = (idx == self.current_profile_index)
        bg = COLORS.get('hover_bg', '#3A3F4D') if is_active else COLORS['card_bg']
        
        frame = tk.Frame(parent, bg=bg, pady=8, padx=10, cursor="hand2")
        frame.pack(fill="x", pady=1)
        
        head = self.get_head_from_skin(profile.get("skin_path"), size=24)
        lbl_icon = tk.Label(frame, image=head, bg=bg) # type: ignore
        lbl_icon.image = head # type: ignore # keep ref
        lbl_icon.pack(side="left", padx=(0, 10))
        
        tk.Label(frame, text=self._get_streamer_safe_name(profile.get("name", "Unknown")), font=(FONT_FAMILY, 10, "bold"),
                bg=bg, fg=COLORS['text_primary']).pack(side="left")
        
        # Delete Button
        err_red = COLORS.get('error_red', '#EF4444')
        del_btn = self._make_btn(frame, "-", style="danger", font_size=12, bold=True, icon=True,
                                 command=lambda: self.delete_profile(idx))
        del_btn.config(bg=bg, fg=err_red, activebackground=bg, activeforeground=err_red)
        del_btn.bind("<Enter>", lambda e: del_btn.config(fg="white", bg=err_red))
        del_btn.bind("<Leave>", lambda e: del_btn.config(fg=err_red, bg=bg))
        
        # Only show delete if strictly more than 1 profile? Or allow deleting the last one (which resets to default)?
        # User said "right of every account".
        # Standard launcher behavior typically allows removing any added account.
        del_btn.pack(side="right", padx=(5, 0))

        tk.Label(frame, text=profile.get("type", "offline").title(), font=(FONT_FAMILY, 8),
                bg=bg, fg=COLORS['text_secondary']).pack(side="right")
        
        def on_click(e):
            old_index = self.current_profile_index
            self.current_profile_index = idx
            
            # Only update if index actually changed
            if old_index != idx:
                self.update_active_profile()
                # Update installation dropdown in case settings changed
                if hasattr(self, 'update_installation_dropdown'):
                    self.update_installation_dropdown()
                    
            if hasattr(self, 'profile_menu') and self.profile_menu:
                try:
                    if self.profile_menu.winfo_exists():
                        self.profile_menu.destroy()
                except:
                    pass
            
        frame.bind("<Button-1>", on_click)
        for child in frame.winfo_children():
            if child != del_btn:
                child.bind("<Button-1>", on_click)

    def open_add_account_modal(self):
        print("Opening add account modal")
        if hasattr(self, 'profile_menu') and self.profile_menu:
            try:
                if self.profile_menu.winfo_exists():
                    self.profile_menu.destroy()
                    self.profile_menu = None
            except:
                pass
        
        win = tk.Toplevel(self.root)
        self._register_dialog_window(win)
        win.title("Add Account")
        win.geometry("450x350")
        win.config(bg=COLORS['main_bg'])
        if os.name != "nt":
            win.transient(self.root)
        win.resizable(False, False)
        if os.name != "nt":
            win.grab_set()
        
        # Center on parent
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 175
        win.geometry(f"+{x}+{y}")
        
        # Ensure visibility
        win.deiconify()
        win.lift()
        win.geometry(f"+{x}+{y}")
        win_root = self._apply_custom_toplevel_chrome(win, "Add Account")
        self._schedule_dialog_raise()

        tk.Label(win_root, text="Add a new account", font=(FONT_FAMILY, 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(30, 20))
        
        self._make_btn(win_root, "Microsoft Account", style="primary", font_size=11,
                      width=25, command=lambda: self.show_microsoft_login(win)).pack(pady=5, ipady=4)

        accent_blue = COLORS.get('accent_blue', '#3498DB')
        btn_ely = self._make_btn(win_root, "Ely.by Account", style="secondary", font_size=11,
                                 width=25, command=lambda: self.show_elyby_login(win))
        btn_ely.config(bg=accent_blue, activebackground=derive_hover_color(accent_blue))
        btn_ely.bind("<Enter>", lambda e: btn_ely.config(bg=derive_hover_color(accent_blue)))
        btn_ely.bind("<Leave>", lambda e: btn_ely.config(bg=accent_blue))
        btn_ely.pack(pady=5, ipady=4)

        self._make_btn(win_root, "Offline Account", style="secondary", font_size=11,
                      width=25, command=lambda: self.show_offline_login(win)).pack(pady=5, ipady=4)

    def show_microsoft_login(self, parent):
        self._register_dialog_window(parent)
        try:
            parent._nlc_force_above_launcher = True  # type: ignore[attr-defined]
        except Exception:
            pass
        parent.title("Microsoft Login - Device Flow")
        self._apply_custom_toplevel_chrome(parent, "Microsoft Login")
        content_root = self._clear_toplevel_content(parent)
        parent.geometry("550x500")
        
        # Re-center after changing size
        parent.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width()//2) - 275
        y = self.root.winfo_y() + (self.root.winfo_height()//2) - 250
        parent.geometry(f"+{x}+{y}")
        self._schedule_dialog_raise()
        
        tk.Label(content_root, text="Microsoft Login", font=(FONT_FAMILY, 16, "bold"), 
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(20, 10))
        
        # Status Label
        status_lbl = tk.Label(content_root, text="Initializing...", font=(FONT_FAMILY, 10), 
                             bg=COLORS['main_bg'], fg=COLORS['text_secondary'], wraplength=450)
        status_lbl.pack(pady=10)
        
        # Code Display
        code_lbl = tk.Label(content_root, text="", font=(FONT_FAMILY, 24, "bold"), 
                           bg=COLORS['main_bg'], fg=COLORS.get('accent_color', COLORS['success_green']))
        code_lbl.pack(pady=10)
        
        # URL Display
        url_lbl = tk.Label(content_root, text="", font=(FONT_FAMILY, 11, "underline"), 
                          bg=COLORS['main_bg'], fg=COLORS.get('accent_blue', '#3498DB'), cursor="hand2")
        url_lbl.pack(pady=5)
        
        # Copy Button
        copy_btn = self._make_btn(content_root, "Copy Code", style="secondary", font_size=10)
        copy_btn.config(state="disabled")
        copy_btn.pack(pady=10)
        
        self._make_btn(content_root, "Cancel", style="text", font_size=10,
                      command=parent.destroy).pack(pady=20)

        # Helper to open URL
        def open_url(e):
            url = url_lbl.cget("text")
            if url: webbrowser.open(url)
        url_lbl.bind("<Button-1>", open_url)

        # Start Thread
        threading.Thread(target=self._start_microsoft_device_flow, args=(parent, status_lbl, code_lbl, url_lbl, copy_btn), daemon=True).start()
    
    def _start_microsoft_device_flow(self, win, status, code_display, url_display, copy_btn):
        # 1. Request Device Code
        self.log("Starting Microsoft Account device flow login...")
        try:
             client_id = MSA_CLIENT_ID
             scope = "XboxLive.signin offline_access"
             
             if not win.winfo_exists(): return
             status.config(text="Contacting Microsoft...")
             
             # Request Device Code
             r = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
                               data={"client_id": client_id, "scope": scope})
             
             if r.status_code != 200:
                 if win.winfo_exists(): status.config(text=f"Error initiating login: {r.text}", fg=COLORS['error_red'])
                 return
                 
             data = r.json()
             user_code = data.get("user_code")
             verification_uri = data.get("verification_uri")
             device_code = data.get("device_code")
             interval = data.get("interval", 5)
             
             # Update UI
             if win.winfo_exists():
                 code_display.config(text=user_code)
                 url_display.config(text=verification_uri)
                 status.config(text="1. Open the verification link below\n2. Enter the code shown\n3. Sign in to your Microsoft Account")
                 
                 copy_btn.config(state="normal", command=lambda: self.root.clipboard_clear() or self.root.clipboard_append(user_code) or self.root.update())
             
             # 2. Poll
             while win.winfo_exists():
                 time.sleep(interval)
                 
                 r_poll = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                                       data={"grant_type": "device_code", "client_id": client_id, "device_code": device_code})
                 
                 if r_poll.status_code == 200:
                     # Success
                     token_data = r_poll.json()
                     self._finalize_microsoft_login(token_data, win, status)
                     break
                 
                 err = r_poll.json()
                 err_code = err.get("error")
                 
                 if err_code == "authorization_pending":
                     continue # Keep waiting
                 elif err_code == "slow_down":
                     interval += 2
                 elif err_code == "expired_token":
                     if win.winfo_exists(): status.config(text="Code expired. Please try again.", fg=COLORS['error_red'])
                     break
                 else:
                     if win.winfo_exists(): status.config(text=f"Error: {err.get('error_description')}", fg=COLORS['error_red'])
                     break
                     
        except Exception as e:
            self.log(f"Device Flow Error: {e}")
            logging.error("Device Flow Error", exc_info=True)
            if win.winfo_exists(): status.config(text=f"Exception: {e}", fg=COLORS['error_red'])

    def _finalize_microsoft_login(self, token_data, win, status):
        self.log("Finalizing Microsoft Login...")
        try:
            if not win.winfo_exists(): return
            status.config(text="Authenticating with Xbox Live...")
            access_token = token_data["access_token"]
            refresh_token = token_data["refresh_token"]
            
            # Xbox Live
            xbl = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(access_token)
            
            # XSTS
            if not win.winfo_exists(): return
            status.config(text="Authenticating with XSTS...")
            xsts = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl["Token"])
            
            # Minecraft
            if not win.winfo_exists(): return
            status.config(text="Authenticating with Minecraft...")
            mc_auth = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(xbl["DisplayClaims"]["xui"][0]["uhs"], xsts["Token"])
            
            # Profile
            if not win.winfo_exists(): return
            status.config(text="Fetching Profile...")
            profile = minecraft_launcher_lib.microsoft_account.get_profile(mc_auth["access_token"])
            
            # Success - Save
            new_profile = {
                "name": profile["name"],
                "uuid": profile["id"],
                "type": "microsoft",
                "skin_path": "", # Will fetch later
                "access_token": mc_auth["access_token"],
                "refresh_token": refresh_token,
                "created": datetime.now().strftime("%Y-%m-%d")
            }
            
            self.profiles.append(new_profile)
            self.current_profile_index = len(self.profiles) - 1
            self.save_config()
            
            # Done
            if win.winfo_exists():
                status.config(text="Login Successful!", fg=COLORS['success_green'])
                win.after(1000, win.destroy)
                
                def on_finish():
                    self.update_active_profile()
                    self.refresh_skin()
                    
                self.root.after(100, on_finish)
                
        except Exception as e:
            self.log(f"Microsoft Auth Error: {e}")
            logging.error("Microsoft Auth Trace", exc_info=True)
            if win.winfo_exists(): status.config(text=f"Finalization Error: {e}", fg=COLORS['error_red'])

    def show_elyby_login(self, parent):
        parent.title("Ely.by Login")
        self._apply_custom_toplevel_chrome(parent, "Ely.by Login")
        content_root = self._clear_toplevel_content(parent)
        self._schedule_dialog_raise()
        
        tk.Label(content_root, text="Ely.by Login", font=(FONT_FAMILY, 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(20, 10))

        frame = tk.Frame(content_root, bg=COLORS['main_bg'])
        frame.pack(fill="x", padx=40)

        tk.Label(frame, text="Username / Email", font=(FONT_FAMILY, 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        user_entry = tk.Entry(frame, font=(FONT_FAMILY, 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat")
        user_entry.pack(fill="x", ipady=5, pady=(5, 15))

        tk.Label(frame, text="Password", font=(FONT_FAMILY, 9), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
        pass_entry = tk.Entry(frame, font=(FONT_FAMILY, 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", show="*")
        pass_entry.pack(fill="x", ipady=5, pady=(5, 20))

        def do_login():
            u = user_entry.get().strip()
            p = pass_entry.get().strip()
            if not u or not p:
                custom_showerror("Error", "Please fill all fields")
                return
            
            res = ElyByAuth.authenticate(u, p)
            if "error" in res:
                custom_showerror("Login Failed", f"Could not login to Ely.by details: {res['error']}")
            else:
                # Success
                profile = cast(dict, res.get("selectedProfile", {}))
                uuid_ = profile.get("id", "")
                name_ = profile.get("name", u)
                token = res.get("accessToken", "")
                
                # Fetch Skin using shared logic
                skin_cache_path = self.fetch_elyby_skin(name_, uuid_, profile.get("properties", []))

                new_profile = {
                    "name": name_,
                    "type": "ely.by",
                    "skin_path": skin_cache_path, 
                    "uuid": uuid_,
                    "token": token
                }
                self.profiles.append(new_profile)
                self.current_profile_index = len(self.profiles) - 1
                self.update_active_profile()
                self.add_skin_to_history(skin_cache_path)
                self.save_config()
                parent.destroy()
                custom_showinfo("Success", f"Logged in as {name_}")

        self._make_btn(content_root, "Login", style="primary", font_size=11, bold=True,
                      width=25, command=do_login).pack(pady=10, ipady=4)

    def show_offline_login(self, parent):
        parent.title("Offline Account")
        self._apply_custom_toplevel_chrome(parent, "Offline Account")
        content_root = self._clear_toplevel_content(parent)
        self._schedule_dialog_raise()
        
        tk.Label(content_root, text="Offline Account", font=(FONT_FAMILY, 16, "bold"),
                bg=COLORS['main_bg'], fg=COLORS['text_primary']).pack(pady=(30, 10))
                
        tk.Label(content_root, text="Username", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w", padx=60)
        entry = tk.Entry(content_root, font=(FONT_FAMILY, 11), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        entry.pack(fill="x", padx=60, pady=(5, 30), ipady=8)
        entry.focus()
        
        def save():
            name = entry.get().strip()
            if name:
                self.profiles.append({"name": name, "type": "offline", "skin_path": "", "uuid": ""})
                self.current_profile_index = len(self.profiles) - 1
                self.update_active_profile()
                self.save_config()
                parent.destroy()
        
        self._make_btn(content_root, "Add Account", style="primary", font_size=11, bold=True,
                      width=20, command=save).pack(pady=10, ipady=4)

    # --- SETTINGS TAB ---
    # --- MODS TAB ---

