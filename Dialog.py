from tkinter import *
from abc import abstractmethod, ABCMeta


class Dialog(Toplevel):
    def __init__(self, master, title=None, text=None, block=True):
        """master: is a tkinter element that is to be the master
        title: is the title of the dialog
        block: tells weather or not to block until the dialog is closed"""
        super().__init__(master)
        self.transient(master)
        self.text = text
        if title:
            self.title(title)
        self.result = None
        body = Frame(self)
        self.initial_focus = self.body(body)
        body.pack(padx=5, pady=5)
        self.buttonbox()
        self.grab_set()
        if not self.initial_focus:
            self.initial_focus = self
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.geometry("+%d+%d" % (master.winfo_rootx() + 50, master.winfo_rooty() + 50))
        self.initial_focus.focus_set()
        if block:
            self.wait_window(self)

    #
    # construction hooks
    def body(self, master):
        """Create dialog body. Return widget that should have initial focus. This method should be overriden."""
        Label(master, text=self.text).pack()

    def buttonbox(self):
        """Add standard button box. Override if you don't want the standard buttons"""
        box = Frame(self)
        w = Button(box, text="OK", width=10, command=self.ok, default=ACTIVE)
        w.pack(side=LEFT, padx=5, pady=5)
        if not self.text:
            w = Button(box, text='Cancel', width=10, command=self.cancel)
            w.pack(side=LEFT, padx=5, pady=5)
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)

        box.pack()

    #
    # standard button semantics
    def ok(self, event=None):
        """Called when the ok button is pressed."""
        if not self.validate():
            self.initial_focus.focus_set()
            return
        self.withdraw()
        self.update_idletasks()
        self.apply()
        self.cancel()

    def cancel(self, event=None, focus=True):
        """put focus back to the parent window"""
        if focus:
            self.master.focus_set()
        self.destroy()

    #
    # command hooks
    def validate(self):
        """Called to check weather or not the ok button should be pressed."""
        return 1  # override

    def apply(self):
        """Called when you should actually do something for the ok button press.
        Overload if you wan't to add things in besides the apply_dialog in the interface."""
        pass
