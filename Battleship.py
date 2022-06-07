import abc
import socket
import threading
import time
import tkinter as tk
import tkinter.font
from datetime import datetime
from random import randint
from PIL import ImageTk, Image
from queue import Queue
from operator import add, sub

import Dialog
from insthelp import resource_path
from vars import *


def _create_circle(self, x, y, r, **kwargs):
    return self.create_oval(x - r, y - r, x + r, y + r, **kwargs)


tk.Canvas.create_circle = _create_circle


class Hole(object):
    def __init__(self, mine: bool, coords):
        self._mine = mine
        self.coords = coords
        self.hit = False
        self.valid = False
        if self._mine:
            self.hold_ship = None


class Peg:
    def __init__(self):
        self.hole = None


class ColorPeg(Peg):
    def __init__(self, color):
        super().__init__()
        self.color = color


class ShipPeg(Peg):
    def __init__(self, ship):
        super().__init__()
        self.ship = ship


class Ship(metaclass=abc.ABCMeta):
    def __init__(self, length: int):
        self.length = length
        self.pegs = []
        for i in range(length):
            self.pegs.append(ShipPeg(self))

    def is_sunk(self):
        for peg in self.pegs:
            if not peg.hole.hit:
                return False
        return True


class Player:
    def __init__(self):
        self.grid_mine = None
        self.grid_opponent = None
        x, y = PLAYER_START
        self.mine = [[Hole(True, (x + SPACE * ii,
                                  y + SPACE * i))
                      for i in range(1, BOARD_HEIGHT + 1)]
                     for ii in range(1, BOARD_WIDTH + 1)]
        x, y = OPPONENT_START
        self.opponent = [[Hole(False, (x + SPACE * ii,
                                       y + SPACE * i))
                          for i in range(1, BOARD_HEIGHT + 1)] for ii in range(1, BOARD_WIDTH + 1)]
        self.ships = [Ship(2), Ship(3), Ship(3), Ship(4), Ship(5)]

    # noinspection PyUnresolvedReferences
    def place_ship(self, ship, coordinates):
        ship_peg = (peg for peg in ship.pegs)

        x = coordinates[0][0]
        y = coordinates[0][1]
        xe = coordinates[1][0]
        ye = coordinates[1][1]
        if x > xe or y > ye:
            x, xe = xe, x
            y, ye = ye, y
        xp = 0
        yp = 0
        if x == xe:
            yp = 1
        else:
            xp = 1
        self.mine[x][y].hold_ship = peg = next(ship_peg)
        peg.hole = self.mine[x][y]
        while x != xe or y != ye:
            x += xp
            y += yp
            self.mine[x][y].hold_ship = peg = next(ship_peg)
            peg.hole = self.mine[x][y]


class Broadcast(threading.Thread):
    def __init__(self, master):
        super().__init__()
        self.running = False
        self.master = master

    def run(self):
        self.running = True
        s = socket.socket(type=socket.SOCK_DGRAM)
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            s.sendto(('%s\n%s\n%i' % (self.master.name, self.master.uuid, self.master.server.port)).encode(),
                     ('<broadcast>', PORT))
            time.sleep(1)
        s.sendto(('%s\nCLOSED\n%s' % (self.master.name, self.master.uuid)).encode(), ('<broadcast>', PORT))
        s.close()

    def stop(self):
        if self.is_alive():
            self.running = False
            self.join()


class Client(threading.Thread):
    def __init__(self, master, callback):
        super().__init__()
        self.running = False
        self.master = master
        self.player_list = Client.PlayerList(master, callback)

    def run(self):
        self.running = True
        s = socket.socket(type=socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', PORT))
        s.setblocking(False)
        while self.running:
            try:
                data, address = s.recvfrom(512)
                self.player_list.process(data.decode(), address[0])
            except BlockingIOError:
                pass
        s.close()

    def stop(self):
        if self.is_alive():
            self.running = False
            if not self.player_list.destroyed:
                self.player_list.cancel(destroy=False, focus=False)
            self.join()

    class PlayerList(Dialog.Dialog):
        def apply(self):
            pass

        def buttonbox(self):
            self.bind('<Escape>', self.cancel)

        def body(self, master):
            self.body_frame = master

        def cancel(self, event=None, destroy=True, focus=True):
            super().cancel(event, focus)
            if destroy:
                self.master.destroy()
            self.destroyed = True

        def __init__(self, master, callback):
            self.body_frame = None
            self.player = None
            self.players = {}
            self.sock = None
            self.callback = callback
            self.destroyed = False
            super().__init__(master=master, title='Players', block=False)

        def validate(self):
            return True

        def process(self, data: str, address):
            data = data.splitlines()
            name = data[0]
            uuid = data[1]
            port = data[2]
            if uuid == self.master.uuid:
                return
            if uuid == 'CLOSED':
                uuid = port
                if uuid in self.players:
                    self.players[uuid][tk.Button].destroy()
                    del self.players[uuid]
            else:
                if uuid not in self.players:
                    self.players[uuid] = {'name': name, 'address': (address, int(port))}
                    button = tk.Button(self.body_frame, text=name, command=lambda: self.select(uuid))
                    button.pack(padx=5, pady=5)
                    self.players[uuid][tk.Button] = button

        def select(self, uuid):
            player = self.players[uuid]
            if self.master.name == player['name']:
                return
            s = socket.socket()
            s.connect(player['address'])
            s.sendall(('CONNECT\nname=%s' % self.master.name).encode())
            message = s.recv(512)
            if message.decode() == 'GRANTED':
                self.player = player
                self.sock = s
                self.withdraw()
                self.callback(s, player['name'])
            else:
                print('Declined')


class Server(threading.Thread):
    def run(self):
        self.running = True
        self.sock.listen(0)
        try:
            while self.running:
                client, address = self.sock.accept()
                data = client.recv(1024)
                data = data.decode().splitlines()
                details = {}
                first = True
                for line in data:
                    if first:
                        first = False
                        if line != 'CONNECT':
                            break
                        else:
                            continue
                    temp = line.split('=')
                    details[temp[0]] = temp[1]
                work = True
                for i in ['name']:
                    if i not in details:
                        work = False
                        break
                if work:
                    test = Server.ConfirmConnection(self.master, details)
                    if test.connect:
                        client.sendall('GRANTED'.encode())
                        self.details = details
                        self.client = client
                        self.sock.close()
                        self.running = False
                        self.callback(client, details['name'])
                        break
                client.close()
        except OSError:
            pass

    def __init__(self, master, callback):
        self.running = False
        self.master = master
        self.port = None
        self.sock = socket.socket()
        self.callback = callback
        binding = True
        while binding:
            try:
                self.port = randint(2000, 9999)
                self.sock.bind(('', self.port))
                binding = False
            except OSError:
                pass
        self.client = None
        self.details = None
        super().__init__()

    def stop(self):
        if self.is_alive():
            self.running = False
            self.sock.close()
            self.join()

    class ConfirmConnection(Dialog.Dialog):
        def validate(self):
            return True

        def __init__(self, master, player):
            self.connect = False
            self.player = player
            super().__init__(master, 'Connect?')

        def apply(self):
            self.connect = True

        def body(self, master):
            tk.Label(master, text='Do you want to accept connection to %s?' % self.player['name']).pack(padx=5, pady=5)


class WhoStartsDialog(Dialog.Dialog):
    def __init__(self, master):
        self.master = master
        self.sock = master.sock
        self.name = master.name
        self.opponent = master.opponent
        self.label_opponent = None
        self.label_self = None
        self.choice_opponent = None
        self.choice_self = None
        self.decision = None
        self.approved = False
        self.waiting = False
        self.options = [master.name, master.opponent]
        super().__init__(master, WHO_STARTS_TITLE, block=True)

    def apply(self):
        self.decision = self.choice_self
        self.master.queue.put(None)
        super().cancel()

    def ok(self, event=None):
        if not self.validate():
            self.initial_focus.focus_set()
            return
        self.withdraw()
        self.update_idletasks()
        self.apply()

    def body(self, master):
        tk.Label(master, text='Who should start first?').grid(row=0, column=0, columnspan=2)
        self.label_opponent = tk.Label(master, text='%s has not chose yet.' % self.opponent)
        self.label_opponent.grid(row=1, column=0, columnspan=2)
        self.label_self = tk.Label(master, text='You have not chose yet.')
        self.label_self.grid(row=2, column=0, columnspan=2)
        tk.Button(master, text=self.name, command=lambda: self.sendto(self.name)).grid(row=3, column=0)
        tk.Button(master, text=self.opponent, command=lambda: self.sendto(self.opponent)).grid(row=3, column=1)
        threading.Thread(target=self.process_data).start()

    def validate(self):
        if self.choice_self and self.choice_self == self.choice_opponent:
            self.sock.sendall(('APPLY\n%s' % self.choice_self).encode())
            self.waiting = True
            while self.waiting:
                time.sleep(.2)
            return self.approved
        return False

    def cancel(self, event=None, focus=True):
        super().cancel(event, focus)
        self.master.after(0, self.master.destroy)

    def process_data(self):
        while True:
            lines = self.master.queue.get()
            if not lines:
                return
            if len(lines) != 2:
                raise Exception('Bad Protocol!')
            if lines[0] == 'CHOOSE':
                if lines[1] not in self.options:
                    raise Exception('User opponent chose is not an option!')
                self.label_opponent['text'] = '%s has chose %s to start first.' % (self.opponent, lines[1])
                self.choice_opponent = lines[1]
            elif lines[0] == 'APPLY':
                if lines[1] == 'APPROVED':
                    self.approved = True
                    self.waiting = False
                elif lines[1] == 'DENIED':
                    self.approved = False
                    self.waiting = False
                elif lines[1] == self.choice_self:
                    self.sock.sendall('APPLY\nAPPROVED'.encode())
                    threading.Thread(target=self.apply).start()
                elif lines[1] in self.options:
                    self.sock.sendall('APPLY\nDENIED'.encode())
                else:
                    raise Exception('Incorrect parameter supplied to APPLY')
            else:
                raise Exception('Data did not start with "CHOOSE"!\n%s' % lines)

    def sendto(self, player):
        self.sock.sendall(('CHOOSE\n%s' % player).encode())
        self.label_self['text'] = 'You have chose %s to start first.' % player
        self.choice_self = player


class GUI(tk.Tk):
    def __init__(self):
        super().__init__(None, None, 'Tk', 1, 0, None)
        self.title(BATTLE_SHIP_TITLE)
        self.sock = None
        self.opponent = None
        self.player = None
        self.grids = None
        self.thread_listen = None
        self.turn_yours = False
        self.turn_text = None
        self.sunk = 0
        self.opponent_sunk = 0
        self.queue = Queue()
        self.my_queue = Queue()
        self.background = ImageTk.PhotoImage(Image.open(resource_path('images/background.png')))
        self.canvas = tk.Canvas(self, width=592, height=783, bd=0, highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image((0, 0), image=self.background, anchor='nw')
        self.resizable(False, False)
        self.font = tk.font.Font(weight='bold')
        self.sunk_text = self.canvas.create_text(SUNK_POS, text='SUNK: 0', fill='white', font=self.font)
        self.player = Player()
        canvas = self.canvas
        xx, yy = OPPONENT_START
        self.player.grid_opponent = [[canvas.create_circle(xx + SPACE * (x + 1),
                                                           yy + SPACE * (y + 1), 3, fill='black')
                                      for y in range(BOARD_HEIGHT)]
                                     for x in range(BOARD_WIDTH)]
        xx, yy = PLAYER_START
        self.player.grid_mine = [[canvas.create_circle(xx + SPACE * (x + 1),
                                                       yy + SPACE * (y + 1), 3, fill='white', outline='white')
                                  for y in range(BOARD_HEIGHT)]
                                 for x in range(BOARD_WIDTH)]
        for pos, grid, color in zip((OPPONENT_START, PLAYER_START),
                                    (self.player.grid_opponent, self.player.grid_mine),
                                    ('black', 'white')):
            x, y = pos
            for i in range(1, BOARD_WIDTH + 1):
                canvas.create_text(x + SPACE * i, y, text=str(i), fill=color, font=self.font)
            for i, l in zip(range(1, BOARD_HEIGHT + 1), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
                canvas.create_text(x, y + SPACE * i, text=l, fill=color, font=self.font)

            for i in range(0, BOARD_WIDTH):
                canvas.create_line(x + SPACE / 2 + SPACE * i, y - SPACE / 2,
                                   x + SPACE / 2 + SPACE * i, y + SPACE * BOARD_HEIGHT + SPACE / 2, fill=color)
            for i in range(0, BOARD_HEIGHT):
                canvas.create_line(x - SPACE / 2, y + SPACE / 2 + SPACE * i,
                                   x + SPACE / 2 + SPACE * BOARD_WIDTH, y + SPACE / 2 + SPACE * i, fill=color)

        self.name, self.uuid = self.get_name()
        if not self.name:
            self.destroy()
            return
        canvas.create_text(PLAYER_NAME, text=self.name, font=self.font, fill='white')

        self.server = Server(self, self.callback)
        self.broad = Broadcast(self)
        self.client = Client(self, self.callback)
        self.server.start()
        self.broad.start()
        self.client.start()
        self.mainloop()
        self.my_queue.put(None)
        self.server.stop()
        self.broad.stop()
        self.client.stop()
        if self.thread_listen:
            self.thread_listen.stop()

    def click_canvas(self, event):
        if self.turn_yours:
            dots = self.canvas.find_closest(event.x, event.y)
            pos = None
            for dot in dots:
                for column in self.player.grid_opponent:
                    if dot in column:
                        pos = (self.player.grid_opponent.index(column), column.index(dot))
                        break
                if pos:
                    break
            if not pos:
                return
            hole = self.player.opponent[pos[0]][pos[1]]
            if hole.hit:
                return
            hole.hit = True
            self.sock.sendall(('SHOOT\n%i\n%i' % (pos[0], pos[1])).encode())
            data = self.queue.get()
            if len(data) != 2:
                raise Exception('Bad Protocol!')
            if data[0] != 'SHOT':
                raise Exception('Bad Protocol!')
            if data[1] not in ('SUNK', 'HIT', 'MISS'):
                raise Exception('Bad Protocol!')
            x, y = hole.coords
            if data[1] == 'MISS':
                self.canvas.create_circle(x, y, 8, fill='white')
            else:
                self.canvas.create_circle(x, y, 8, fill='red')
                if data[1] == 'SUNK':
                    self.sunk += 1
                    self.canvas.itemconfig(self.sunk_text, text='Sunk: %i' % self.sunk)
                    Dialog.Dialog(self, title='Sunk!', text='You sunk a ship!')
                    if self.sunk == 5:
                        Dialog.Dialog(self, title='Winner!', text='You won!')
                        self.turn_yours = False
                        self.canvas.itemconfig(self.turn_text, text='Winner!', fill='gold')
                        return
            self.turn_yours = False
            self.canvas.itemconfig(self.turn_text, text=TURN_MESSAGE[False], fill=TURN_COLOR[False])
            threading.Thread(target=self.opponent_turn).start()

    def callback(self, sock, name):
        """
        Method that gets called when a player actually connects
        :param sock: socket for communication to opponent
        :param name: The name of the player which connected.
        :return: None
        """
        self.sock = sock
        self.opponent = name
        self.thread_listen = ListenThread(self, self.sock)
        self.thread_listen.start()

        def stop():
            self.server.stop()
            self.client.stop()
            self.broad.stop()

        self.after(0, stop)

        def later():
            canvas = self.canvas
            canvas.create_text(OPPONENT_NAME, text=self.opponent, font=self.font, fill='white')

            x, y, x1, y1 = RECTANGLE_POS
            rectangle = canvas.create_rectangle(x, y, x1, y1, fill='black')
            text = canvas.create_text((x1 - x) / 2 + x, (y1 - y) / 4 + y, font=self.font, fill='white')

            def click(event):
                dots = canvas.find_closest(event.x, event.y)
                pos = None
                for dot in dots:
                    for row in self.player.grid_mine:
                        if dot in row:
                            pos = (self.player.grid_mine.index(row), row.index(dot))
                            break
                    if pos:
                        break
                if not pos:
                    return
                self.my_queue.put(pos)

            for row in self.player.grid_mine:
                for dot in row:
                    canvas.tag_bind(dot, '<1>', click)

            for ship in self.player.ships:
                canvas.itemconfig(text, text='Click the first dot for the %i long ship!' % ship.length)
                data = self.my_queue.get()
                if not data:
                    return
                x1, y1 = data
                canvas.itemconfig(text, text='Click the second dot for the ship!\n'
                                             'Only the red dots are valid.')
                mine = self.player.mine
                length = ship.length - 1
                valid_dots = []
                dots = []
                for x, y in ((x1 - length, y1), (x1 + length, y1), (x1, y1 - length), (x1, y1 + length)):
                    if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
                        hole = mine[x][y]
                        dot = self.player.grid_mine[x][y]
                        if not hole.hold_ship:
                            valid_dots.append(dot)
                            canvas.itemconfig(self.player.grid_mine[x][y], fill='red')
                while True:
                    data = self.my_queue.get()
                    if not data:
                        return
                    x2, y2 = data
                    dot = self.player.grid_mine[x2][y2]
                    if dot in valid_dots:
                        break
                for dot in valid_dots:
                    canvas.itemconfig(dot, fill='white')
                self.player.place_ship(ship, ((x1, y1), (x2, y2)))
                x1, y1 = ship.pegs[0].hole.coords
                x2, y2 = ship.pegs[-1].hole.coords
                canvas.create_oval(x1 - SPACE / 3, y1 - SPACE / 3,
                                   x2 + SPACE / 3, y2 + SPACE / 3, fill='grey', outline='grey')
                for peg in ship.pegs:
                    x, y = peg.hole.coords
                    canvas.create_circle(x, y, 3, fill='black')

            for row in self.player.grid_mine:
                for dot in row:
                    canvas.tag_unbind(dot, '<1>')

            canvas.delete(text)
            canvas.delete(rectangle)
            self.after(0, self.start)

        threading.Thread(target=later).start()

    def opponent_turn(self):
        try:
            data = self.queue.get()
            if not data:
                return
            if len(data) != 3:
                raise Exception('Bad Protocol!')
            if data[0] != 'SHOOT':
                raise Exception('Bad Protocol!')
            try:
                x = int(data[1])
                y = int(data[2])
                hole = self.player.mine[x][y]
                hole.hit = True
                gx, gy = hole.coords
                if hole.hold_ship:
                    if hole.hold_ship.ship.is_sunk():
                        self.sock.sendall('SHOT\nSUNK'.encode())
                        self.opponent_sunk += 1
                        if self.opponent_sunk == 5:
                            self.canvas.itemconfig(self.turn_text, text='Looser!', fill='silver')
                            Dialog.Dialog(self, title='Lost!', text='You lost!')
                            return
                    else:
                        self.sock.sendall('SHOT\nHIT'.encode())
                    self.canvas.create_circle(gx, gy, 8, fill='red')
                else:
                    self.sock.sendall('SHOT\nMISS'.encode())
                    self.canvas.create_circle(gx, gy, 8, fill='white')
                self.turn_yours = True
                self.canvas.itemconfig(self.turn_text, text=TURN_MESSAGE[True], fill=TURN_COLOR[True])
            except TypeError:
                raise Exception('Protocol Error!')
        except ConnectionAbortedError:
            return

    def start(self):
        """
        Starts the game!
        :return: None
        """
        canvas = self.canvas
        starts_dialog = WhoStartsDialog(self)
        if not starts_dialog.decision:
            return
        self.turn_yours = starts_dialog.decision == self.name
        self.turn_text = canvas.create_text(TURN_TEXT, text=TURN_MESSAGE[self.turn_yours], font=self.font,
                                            fill=TURN_COLOR[self.turn_yours])
        for row in self.player.grid_opponent:
            for dot in row:
                canvas.tag_bind(dot, '<1>', self.click_canvas)
        if not self.turn_yours:
            threading.Thread(target=self.opponent_turn).start()

    def get_name(self):
        class Dialog1(Dialog.Dialog):
            def __init__(self, master, title=None, block=True):
                self.name = None
                super().__init__(master=master, title=title, block=block)

            def apply(self):
                self.name = self.initial_focus.get().strip()

            def validate(self):
                return True if self.initial_focus.get().strip() else False

            def body(self, master):
                tk.Label(master, text=NAME_QUESTION).pack(padx=5, pady=5)
                entry = tk.Entry(master)
                entry.pack(padx=5, pady=5)
                return entry

        d = Dialog1(self, title='Name?')
        name = d.name
        now = datetime.now()
        seconds = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
        return name, str(seconds)


class ListenThread(threading.Thread):
    def __init__(self, master, sock: socket.socket):
        self.running = False
        self.master = master
        self.queue = master.queue
        self.sock = sock
        sock.setblocking(False)
        super().__init__()

    def run(self):
        self.running = True
        while self.running:
            try:
                data = self.sock.recv(512).decode().splitlines()
                if len(data) == 1 and data[0] == 'CLOSED':
                    self.stop(True)
                    break
                self.queue.put(data)
            except OSError as e:
                if '10035' not in repr(e):
                    self.stop(True)
                    raise Exception('Error!')
        self.running = False

    def stop(self, from_self=False):
        if self.running:
            self.running = False
            self.queue.put(None)
            if not from_self:
                self.sock.sendall('CLOSED'.encode())
            self.sock.close()
            if from_self:
                self.master.after(0, self.master.destroy)


if __name__ == '__main__':
    gui = GUI()
