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
import uuid
from typing import cast
import requests

import minecraft_launcher_lib

from nlc.ui.theme import COLORS, FONT_FAMILY, derive_hover_color
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.ui.components.modal import get_modal_manager
from nlc.net.ms_auth import MicrosoftDeviceAuth, MSA_CLIENT_ID
from nlc.net.elyby_auth import ElyByAuth

logger = logging.getLogger(__name__)

class AccountsScreenMixin:
    """Mixin providing profile/account menus, addition modals, and authentication flows."""
    def close_profile_drawer(self):
        """Collapse in-sidebar account drawer if open."""
        if getattr(self, 'sidebar_account_drawer_open', False):
            if hasattr(self, 'sidebar_account_drawer') and self.sidebar_account_drawer.winfo_exists():
                self.sidebar_account_drawer.pack_forget()
            self.sidebar_account_drawer_open = False
            if hasattr(self, 'sidebar_chevron') and self.sidebar_chevron.winfo_exists():
                self.sidebar_chevron.config(text="▾")
        if hasattr(self, 'profile_menu') and self.profile_menu and isinstance(self.profile_menu, tk.Toplevel):
            try:
                if self.profile_menu.winfo_exists():
                    self.profile_menu.destroy()
            except Exception:
                pass
            self.profile_menu = None

    def toggle_profile_menu(self):
        """Toggle the collapsible in-app Account Center drawer in the sidebar."""
        # Ensure drawer exists on sidebar
        if not hasattr(self, 'sidebar_account_drawer') or not self.sidebar_account_drawer.winfo_exists():
            target_parent = getattr(self, 'sidebar', getattr(self, 'root', None))
            if target_parent is None:
                return
            self.sidebar_account_drawer = tk.Frame(
                target_parent,
                bg=COLORS['card_bg'],
                highlightthickness=1,
                highlightbackground=COLORS.get('border_subtle', '#2D3139')
            )
            self.sidebar_account_drawer_open = False

        if getattr(self, 'sidebar_account_drawer_open', False):
            # Collapse drawer
            self.sidebar_account_drawer.pack_forget()
            self.sidebar_account_drawer_open = False
            self.profile_menu = None
            if hasattr(self, 'sidebar_chevron') and self.sidebar_chevron.winfo_exists():
                self.sidebar_chevron.config(text="▾")
            return

        # Expand drawer
        self.sidebar_account_drawer_open = True
        self.profile_menu = None
        if hasattr(self, 'sidebar_chevron') and self.sidebar_chevron.winfo_exists():
            self.sidebar_chevron.config(text="▴")

        self.render_sidebar_account_drawer()
        sep = getattr(self, 'sidebar_nav_separator', None)
        if sep and sep.winfo_exists():
            self.sidebar_account_drawer.pack(fill="x", padx=10, pady=(0, 10), before=sep)
        else:
            self.sidebar_account_drawer.pack(fill="x", padx=10, pady=(0, 10))

    def render_sidebar_account_drawer(self):
        """Render the contents of the in-sidebar Account Center drawer."""
        if not hasattr(self, 'sidebar_account_drawer') or not self.sidebar_account_drawer.winfo_exists():
            return

        drawer = self.sidebar_account_drawer
        for child in drawer.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

        card_bg = COLORS['card_bg']
        drawer.config(
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=COLORS.get('border_subtle', '#2D3139')
        )

        # Header Row
        header_frame = tk.Frame(drawer, bg=card_bg)
        header_frame.pack(fill="x", padx=10, pady=(8, 4))

        count_text = f"ACCOUNTS ({len(self.profiles)})" if hasattr(self, 'profiles') and self.profiles else "ACCOUNTS"
        tk.Label(
            header_frame,
            text=count_text,
            font=(FONT_FAMILY, 8, "bold"),
            bg=card_bg,
            fg=COLORS['text_secondary']
        ).pack(side="left")

        # Profiles list
        profiles = getattr(self, 'profiles', [])
        if not profiles:
            tk.Label(
                drawer,
                text="No accounts",
                font=(FONT_FAMILY, 9),
                bg=card_bg,
                fg=COLORS.get('text_muted', '#6B7280')
            ).pack(pady=8)
        else:
            if len(profiles) > 3:
                scroll_container = tk.Frame(drawer, bg=card_bg, height=180)
                scroll_container.pack(fill="x", padx=6, pady=2)
                scroll_container.pack_propagate(False)

                canvas = tk.Canvas(scroll_container, bg=card_bg, highlightthickness=0, height=180)
                list_frame = tk.Frame(canvas, bg=card_bg)

                list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
                canvas.create_window((0, 0), window=list_frame, anchor="nw", width=210)
                canvas.pack(side="left", fill="both", expand=True)

                self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"sb_acct_{id(canvas)}")
                self._bind_smooth_scroll(canvas, list_frame)

                for idx, p in enumerate(profiles):
                    self.create_sidebar_profile_item(list_frame, idx, p)
            else:
                list_frame = tk.Frame(drawer, bg=card_bg)
                list_frame.pack(fill="x", padx=6, pady=2)
                for idx, p in enumerate(profiles):
                    self.create_sidebar_profile_item(list_frame, idx, p)

        # Footer Action Button: + Add Account
        footer_frame = tk.Frame(drawer, bg=card_bg)
        footer_frame.pack(fill="x", padx=8, pady=(6, 8))

        add_btn = self._make_btn(
            footer_frame,
            "+ Add Account",
            style="secondary",
            font_size=9,
            bold=True,
            command=self.open_add_account_modal
        )
        add_btn.pack(fill="x", ipady=3)

    def create_sidebar_profile_item(self, parent, idx, profile):
        """Render a single account card in the in-sidebar drawer."""
        is_active = (idx == self.current_profile_index)
        bg = COLORS.get('hover_bg', '#3A3F4D') if is_active else COLORS['card_bg']
        card_border = COLORS['accent_color'] if is_active else COLORS.get('border_subtle', '#2D3139')

        frame = tk.Frame(
            parent,
            bg=bg,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=card_border,
            padx=6,
            pady=4
        )
        frame.pack(fill="x", pady=2)

        # Player skin head (24x24)
        head = self.get_head_from_skin(profile.get("skin_path"), size=24)
        lbl_icon = tk.Label(frame, image=head, bg=bg, cursor="hand2")
        lbl_icon.image = head  # type: ignore[attr-defined]
        lbl_icon.pack(side="left", padx=(2, 6))

        # Text column (Name & Type)
        text_frame = tk.Frame(frame, bg=bg, cursor="hand2")
        text_frame.pack(side="left", fill="x", expand=True)

        display_name = self._get_streamer_safe_name(profile.get("name", "Unknown"))
        lbl_name = tk.Label(
            text_frame,
            text=display_name,
            font=(FONT_FAMILY, 9, "bold" if is_active else "normal"),
            bg=bg,
            fg=COLORS['text_primary'],
            anchor="w",
            cursor="hand2"
        )
        lbl_name.pack(fill="x")

        type_text = profile.get("type", "offline").capitalize()
        lbl_type = tk.Label(
            text_frame,
            text=type_text,
            font=(FONT_FAMILY, 7),
            bg=bg,
            fg=COLORS['accent_color'] if is_active else COLORS['text_secondary'],
            anchor="w",
            cursor="hand2"
        )
        lbl_type.pack(fill="x")

        # Active checkmark
        if is_active:
            lbl_check = tk.Label(
                frame,
                text="✓",
                font=(FONT_FAMILY, 8, "bold"),
                bg=bg,
                fg=COLORS.get('play_btn_green', '#2ECC71')
            )
            lbl_check.pack(side="right", padx=(2, 4))

        # Delete Button
        err_red = COLORS.get('error_red', '#EF4444')
        del_btn = self._make_btn(
            frame,
            "×",
            style="danger",
            font_size=10,
            bold=True,
            icon=True,
            command=lambda i=idx: self.delete_profile(i)
        )
        del_btn.config(bg=bg, fg=err_red, activebackground=bg, activeforeground=err_red)
        del_btn.bind("<Enter>", lambda e, b=del_btn: b.config(fg="white", bg=err_red))
        del_btn.bind("<Leave>", lambda e, b=del_btn, rbg=bg: b.config(fg=err_red, bg=rbg))
        del_btn.pack(side="right", padx=(2, 2))

        def on_click(e=None):
            old_idx = self.current_profile_index
            self.current_profile_index = idx
            if old_idx != idx:
                self.update_active_profile()
                if hasattr(self, 'update_installation_dropdown'):
                    self.update_installation_dropdown()
            self.render_sidebar_account_drawer()

        frame.bind("<Button-1>", on_click)
        lbl_icon.bind("<Button-1>", on_click)
        text_frame.bind("<Button-1>", on_click)
        lbl_name.bind("<Button-1>", on_click)
        lbl_type.bind("<Button-1>", on_click)

        # Hover state
        hover_col = COLORS.get('card_hover', '#2C313C')
        def on_enter(e=None):
            if not (idx == self.current_profile_index):
                frame.config(bg=hover_col)
                lbl_icon.config(bg=hover_col)
                text_frame.config(bg=hover_col)
                lbl_name.config(bg=hover_col)
                lbl_type.config(bg=hover_col)
                del_btn.config(bg=hover_col)

        def on_leave(e=None):
            if not (idx == self.current_profile_index):
                frame.config(bg=bg)
                lbl_icon.config(bg=bg)
                text_frame.config(bg=bg)
                lbl_name.config(bg=bg)
                lbl_type.config(bg=bg)
                del_btn.config(bg=bg)

        frame.bind("<Enter>", on_enter)
        frame.bind("<Leave>", on_leave)

    def create_profile_item(self, parent, idx, profile):
        """Backward-compatible alias for create_sidebar_profile_item."""
        return self.create_sidebar_profile_item(parent, idx, profile)

    def delete_profile(self, idx):
        if not self.profiles or idx < 0 or idx >= len(self.profiles):
            return

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

            if hasattr(self, 'render_sidebar_account_drawer') and getattr(self, 'sidebar_account_drawer_open', False):
                self.render_sidebar_account_drawer()

    def open_add_account_modal(self):
        print("Opening add account modal")
        if hasattr(self, 'profile_menu') and self.profile_menu and isinstance(self.profile_menu, tk.Toplevel):
            try:
                if self.profile_menu.winfo_exists():
                    self.profile_menu.destroy()
                    self.profile_menu = None
            except:
                pass
        
        mgr = get_modal_manager(self.root)
        if not mgr:
            return

        def build_content(body_frame, close_modal):
            view_container = tk.Frame(body_frame, bg=COLORS['card_bg'])
            view_container.pack(fill="both", expand=True, padx=20, pady=10)

            def show_selection_view():
                for w in view_container.winfo_children():
                    w.destroy()

                tk.Label(view_container, text="Select account provider", font=(FONT_FAMILY, 12, "bold"),
                         bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(pady=(10, 20))

                self._make_btn(view_container, "Microsoft Account", style="primary", font_size=11,
                               width=25, command=show_ms_view).pack(pady=6, ipady=4)

                accent_blue = COLORS.get('accent_blue', '#3498DB')
                btn_ely = self._make_btn(view_container, "Ely.by Account", style="secondary", font_size=11,
                                         width=25, command=show_ely_view)
                btn_ely.config(bg=accent_blue, activebackground=derive_hover_color(accent_blue))
                btn_ely.bind("<Enter>", lambda e: btn_ely.config(bg=derive_hover_color(accent_blue)))
                btn_ely.bind("<Leave>", lambda e: btn_ely.config(bg=accent_blue))
                btn_ely.pack(pady=6, ipady=4)

                self._make_btn(view_container, "Offline Account", style="secondary", font_size=11,
                               width=25, command=show_offline_view).pack(pady=6, ipady=4)

            def show_ms_view():
                for w in view_container.winfo_children():
                    w.destroy()

                header = tk.Frame(view_container, bg=COLORS['card_bg'])
                header.pack(fill="x", pady=(0, 10))
                self._make_btn(header, "← Back", style="secondary", font_size=9, command=show_selection_view).pack(side="left")

                status_lbl = tk.Label(view_container, text="Initializing...", font=(FONT_FAMILY, 10),
                                     bg=COLORS['card_bg'], fg=COLORS['text_secondary'], wraplength=450)
                status_lbl.pack(pady=10)

                code_lbl = tk.Label(view_container, text="", font=(FONT_FAMILY, 24, "bold"),
                                   bg=COLORS['card_bg'], fg=COLORS.get('accent_color', COLORS.get('play_btn_green', '#2ECC71')))
                code_lbl.pack(pady=10)

                url_lbl = tk.Label(view_container, text="", font=(FONT_FAMILY, 11, "underline"),
                                  bg=COLORS['card_bg'], fg=COLORS.get('accent_blue', '#3498DB'), cursor="hand2")
                url_lbl.pack(pady=5)

                copy_btn = self._make_btn(view_container, "Copy Code", style="secondary", font_size=10)
                copy_btn.config(state="disabled")
                copy_btn.pack(pady=10)

                def open_url(e):
                    url = url_lbl.cget("text")
                    if url: webbrowser.open(url)
                url_lbl.bind("<Button-1>", open_url)

                threading.Thread(target=self._start_microsoft_device_flow, args=(body_frame, status_lbl, code_lbl, url_lbl, copy_btn, close_modal), daemon=True).start()

            def show_ely_view():
                for w in view_container.winfo_children():
                    w.destroy()

                header = tk.Frame(view_container, bg=COLORS['card_bg'])
                header.pack(fill="x", pady=(0, 10))
                self._make_btn(header, "← Back", style="secondary", font_size=9, command=show_selection_view).pack(side="left")

                frame = tk.Frame(view_container, bg=COLORS['card_bg'])
                frame.pack(fill="x", padx=20, pady=10)

                tk.Label(frame, text="Username / Email", font=(FONT_FAMILY, 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
                user_entry = tk.Entry(frame, font=(FONT_FAMILY, 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat")
                user_entry.pack(fill="x", ipady=5, pady=(5, 12))

                tk.Label(frame, text="Password", font=(FONT_FAMILY, 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
                pass_entry = tk.Entry(frame, font=(FONT_FAMILY, 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", show="*")
                pass_entry.pack(fill="x", ipady=5, pady=(5, 16))

                def do_login():
                    u = user_entry.get().strip()
                    p = pass_entry.get().strip()
                    if not u or not p:
                        custom_showerror("Error", "Please fill all fields", parent=self.root)
                        return
                    res = ElyByAuth.authenticate(u, p)
                    if "error" in res:
                        custom_showerror("Login Failed", f"Could not login to Ely.by: {res['error']}", parent=self.root)
                    else:
                        profile = cast(dict, res.get("selectedProfile", {}))
                        uuid_ = profile.get("id", "")
                        name_ = profile.get("name", u)
                        token = res.get("accessToken", "")
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
                        close_modal()
                        custom_showinfo("Success", f"Logged in as {name_}", parent=self.root)

                self._make_btn(view_container, "Login", style="primary", font_size=11, bold=True,
                              width=25, command=do_login).pack(pady=10, ipady=4)

            def show_offline_view():
                for w in view_container.winfo_children():
                    w.destroy()

                header = tk.Frame(view_container, bg=COLORS['card_bg'])
                header.pack(fill="x", pady=(0, 10))
                self._make_btn(header, "← Back", style="secondary", font_size=9, command=show_selection_view).pack(side="left")

                tk.Label(view_container, text="Username", bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", padx=30, pady=(15, 0))
                entry = tk.Entry(view_container, font=(FONT_FAMILY, 11), bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
                entry.pack(fill="x", padx=30, pady=(5, 20), ipady=8)
                entry.focus_set()

                def save():
                    name = entry.get().strip()
                    if not name:
                        custom_showerror("Error", "Username cannot be empty", parent=self.root)
                        return
                    new_profile = {
                        "name": name,
                        "type": "offline",
                        "skin_path": "",
                        "uuid": str(uuid.uuid4())
                    }
                    self.profiles.append(new_profile)
                    self.current_profile_index = len(self.profiles) - 1
                    self.update_active_profile()
                    self.save_config()
                    close_modal()
                    custom_showinfo("Success", f"Offline profile '{name}' added", parent=self.root)

                self._make_btn(view_container, "Add Profile", style="primary", font_size=11, bold=True,
                              width=25, command=save).pack(pady=10, ipady=4)

            show_selection_view()

        mgr.show_modal("Add Account", build_content, width=500, height=420)

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
    
    def _start_microsoft_device_flow(self, win, status, code_display, url_display, copy_btn, close_modal=None):
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
                     self._finalize_microsoft_login(token_data, win, status, close_modal=close_modal)
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

    def _finalize_microsoft_login(self, token_data, win, status, close_modal=None):
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
                if callable(close_modal):
                    self.root.after(1000, close_modal)
                elif hasattr(win, 'destroy'):
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

