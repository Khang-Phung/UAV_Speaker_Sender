import tkinter as tk

from sender_gui import SenderGUI


def main():
    root = tk.Tk()

    app = SenderGUI(root)

    root.mainloop()


if __name__ == "__main__":
    main()
