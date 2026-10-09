"""
nlc.ui.components - Reusable design-system widget library
"""

from nlc.ui.components.buttons import make_button
from nlc.ui.components.dialogs import CustomMessagebox, custom_showinfo, custom_showwarning, custom_showerror, custom_askyesno
from nlc.ui.components.toasts import ToastManager, PopupManager
from nlc.ui.components.cards import create_card
from nlc.ui.components.context_menu import (
    NeoContextMenu,
    attach_context_menu,
    attach_entry_context_menu,
    dismiss_active_context_menu
)
