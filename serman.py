#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

"""
About:  serman - an ncurses-based systemd service manager
Author: Xyne, 2013
Notes:

  * This was hacked together in a single sessions and I was quite tired by the
    end of it. Cleaning it up and documenting it is on my todo list.

  * This was my introduction to ncurses. The code is therefore noobish. It will
    be improved as I become familiar with the ncurses library and discover the
    "right way" to do things.

  * Symbols and colors are currently hard-coded. I will likely dump them in an
    external JSON file later to enable user configuration.

  * I am aware that logging and feedback is a mess. See previous points.

  * Navigation will also be improved (e.g. jumping between views with function
    keys).


TODO
  * fix gui and other bugs
  * clean up code
  * move most/all key bindings to external configuration file
  * move colors to external configuration file
  * add regex and status filtering
"""

import argparse
import curses
import curses.textpad
import shlex
import subprocess
import sys

################################### Globals ####################################

DEFAULT_MENU_WIDTH = 10
DEFAULT_CONSOLE_HEIGHT = 10

CP_DEFAULT = 1
CP_HIGHLIGHTED = 2
CP_ACTIVE = 3
CP_ON = 4
CP_OFF = 5
CP_ENABLED = 6
CP_STATIC = 7

OFFSET_CP = 100

# har
STATUS_SYMBOLS = {
  'enable' : ('▲', CP_ENABLED),
  'static' : ('▲', CP_STATIC),
  'start' : ('●', CP_ON),
  'error' : ('●', CP_OFF),
}

# Should be same length to assure alignment.
# ✘✔▼⬕
PREFIX_ON = '➤ '
PREFIX_OFF = '  '
PREFIX_LEN = 2

# TODO
# Consider restructing code to obviate this.
MIN_HEIGHT = 5
HDR_COMMANDS = 'Commands'
HDR_SERVICES = 'Services'
MIN_HDR_WIDTH = 1 + len(HDR_COMMANDS) + len(HDR_SERVICES)

MENU_COMMANDS = {
  'enable' : 'enable and disable services',
  'start' : 'start and stop services',
  'restart' : '(re)start services',
  'status' : 'query service status (display output with F2)'
}

HELP_MSG = '[press F3 for help]'
HELP_MSG_LEN = len(HELP_MSG)

PARAM_PROMPT = 'Parameter: '
PARAM_PROMPT_LEN = len(PARAM_PROMPT)

MIN_STATUS_WIDTH = min(len(s) for s in MENU_COMMANDS.values())
MIN_WIDTH = min(MIN_HDR_WIDTH, MIN_STATUS_WIDTH) + PREFIX_LEN + HELP_MSG_LEN + 1


HELP_TEXT = '''Navigation
  Press ctrl+c to exit the program from any view.

  Main View
    * the up and down arrow keys move up and down one line, resp.
    * the right arrow key activates the checklist
    * the left arrow key activates the menu
    * home and end jump to the top and bottom, resp.
    * page up and page down move up and down one screen, resp.
    * space bar toggles the selection
    * return or enter executes the command for the current selection
    * F3 displays this help message
    * F2 display the log
    * entering a character will search the list for items beginning with that
      character: lowercase searches forward, uppercase searches backwards

  Text Views (F3, F2)
    * arrows keys navigate one line or column at a time
    * home and end jump to the top and bottom, resp.
    * page up and page down move up and down one screen, resp.
    * enter returns to the main view

Status Symbols
  The main view uses status symbols to represent service status:
'''

########################## Quick and dirty debugging. ##########################

# TODO
# Use the logging module.
DEBUG_LOG = None
def debug(msg):
  """
  Simplistic debugging. Do not use.
  """
  with open(DEBUG_LOG, 'a') as f:
    f.write(msg)
    f.write('\n')


################################### Argparse ###################################
argparser = argparse.ArgumentParser(
  description='Ncurses-based systemd service manager.',
  epilog='Press F3 while running %(prog)s for more help.',
)

group = argparser.add_argument_group(title='Systemd', description=None)
group.add_argument(
  '-b', '--bin', default='/usr/bin/systemctl', metavar='<path>',
  help='Path to the systemctl binary. [default: %(default)s]'
)
group.add_argument(
  '-a', '--args', nargs=argparse.REMAINDER, default=[],
  help='Pass remaining arguments directly to systemctl (e.g. --user).'
)
# argparser.add_argument(
#   '--dry-run', action='store_true',
#   help='Print systemctl command instead of running them.'
# )

group = argparser.add_argument_group(title='Commands', description=None)
group.add_argument(
  '-c', '--command', action='append', metavar='<unit command>', default=[],
  help='Additional systemctl commands to add to the menu.'
)

group = argparser.add_argument_group(title='Aesthetics', description=None)
group.add_argument(
  '--on', metavar='<string>', default=PREFIX_ON,
  help='Prefix to use to indicate selected services. Default: "%(default)s".'
)

group.add_argument(
  '--off', metavar='<string>', default=PREFIX_OFF,
  help='Prefix to use to indicate unselected services. Default: "%(default)s".'
)

group = argparser.add_argument_group(title='Miscellaneous', description=None)
group.add_argument(
  '--debug', metavar='<path>',
  help='Path to a debug log file.'
)



#################################### Curses ####################################

def initialize():
  curses.curs_set(False)
  curses.use_default_colors()
  curses.init_pair(CP_DEFAULT, -1, -1)
  succeeded = False

  # init_color may fail even if this returns True
  if curses.can_change_color():
    try:
      active_fg = curses.COLOR_WHITE
      active_bg = OFFSET_CP + CP_ACTIVE
      highlighted_fg = curses.COLOR_WHITE
      highlighted_bg = OFFSET_CP + CP_HIGHLIGHTED
      on_fg = OFFSET_CP + CP_ON
      off_fg = OFFSET_CP + CP_OFF
      enabled_fg = OFFSET_CP + CP_ENABLED
      static_fg = OFFSET_CP + CP_STATIC


      curses.init_color(active_bg, 250, 400, 800)
      curses.init_color(highlighted_bg, 350, 350, 350)
      curses.init_color(on_fg, 0, 800, 350)
      curses.init_color(off_fg, 800, 0, 350)
      curses.init_color(enabled_fg, 0, 750, 1000)
      curses.init_color(static_fg, 500, 500, 1000)
      succeeded = True
    except curses.error:
      pass

  if not succeeded:
    active_fg = curses.COLOR_WHITE
    active_bg = curses.COLOR_BLUE
    highlighted_fg = curses.COLOR_BLACK
    highlighted_bg = curses.COLOR_WHITE
    on_fg = curses.COLOR_GREEN
    off_fg = curses.COLOR_RED
    enabled_fg = curses.COLOR_CYAN
    static_fg = curses.COLOR_MAGENTA

  curses.init_pair(CP_ACTIVE, active_fg, active_bg)
  curses.init_pair(CP_HIGHLIGHTED, highlighted_fg, highlighted_bg)
  curses.init_pair(CP_ON, on_fg, -1)
  curses.init_pair(CP_OFF, off_fg, -1)
  curses.init_pair(CP_ENABLED, enabled_fg, -1)
  curses.init_pair(CP_STATIC, static_fg, -1)



def ignore_curses_errors(f):
  """
  A function decorator for ignoring curses errors.

  This is used to avoid errors during rapid sequences of resize events during
  which the window size changes before all elements have been drawn. There is
  almost certainly a way to elegantly avoid this issue with proper use of the
  curses library but I didn't find it during my hackathon.
  """
  def draw(*args, **kwargs):
    try:
      f(*args, **kwargs)
    except curses.error as e:
      pass
  return draw



class Scrollpad(object):
  def __init__(self, window, *args, **kwargs): #items, current=0, position=0):
    self.window = window
    self.pad = curses.newpad(1, 1)
    self.current = 0
    self.position = 0
    self.configure(*args, **kwargs)

  @ignore_curses_errors
  def draw(self, nout=True, fill=True):
    if fill:
#       self.pad.clear()
      self.fill()
    self.change_position()
    if nout:
      refresh = self.pad.noutrefresh
    else:
      refresh = self.pad.refresh
    refresh(
      self.position,
      0,
      self.vis_y,
      self.vis_x,
      self.vis_y + min(self.h, self.vis_h),
      self.vis_x + min(self.w, self.vis_w) - 1,
    )

  def change_item(self, i, cp):
    self.pad.addstr(
      i, 0,
      self.items[i].ljust(self.w),
      curses.color_pair(cp)
    )

  def fill(self):
    for i in range(len(self.items)):
      if i == self.current:
        if self.window.active == self:
          cp = CP_ACTIVE
        else:
          cp = CP_HIGHLIGHTED
      else:
        cp = CP_DEFAULT
      self.change_item(i, cp)

  def change_current(self, dx):
    next = self.current + dx
    if next < 0:
      next = 0
    elif next >= self.h:
      next = self.h - 1
    if self.current != next:
      self.change_item(self.current, CP_DEFAULT)
      previous = self.current
      self.current = next
      self.change_item(self.current, CP_ACTIVE)
      self.window.update(previous)
      self.change_position()

  def change_position(self):
    if self.current < self.position:
      self.position = self.current
    elif self.current >= self.position + self.vis_h:
      self.position = self.current - self.vis_h
    elif self.h <= self.position + self.vis_h:
      self.position = max(0, self.h - self.vis_h)

  def jump_to_chr(self, c):
    item = self.items[self.current]
    c = chr(c)
    lc = c.lower()
    if c == lc:
      di = 1
      rng = range(self.h)
    else:
      c = lc
      di = -1
      rng = range(self.h-1, 0, di)
    if item[0].lower() == c:
      next = self.items[self.current + di]
      if next[0].lower() == c:
        self.change_current(di)
        return
    for i in rng:
      if self.items[i][0].lower() == c:
        self.change_current(i - self.current)
        return

  def run(self):
    ret = None
    run = True
    self.change_item(self.current, CP_ACTIVE)
    while run:
      self.draw(nout=False, fill=False)
      c = self.window.stdscr.getch()

      if c == curses.KEY_UP:
        self.change_current(-1)

      elif c == curses.KEY_DOWN:
        self.change_current(1)

      elif c == curses.KEY_PPAGE:
        self.change_current(-self.vis_h)

      elif c == curses.KEY_NPAGE:
        self.change_current(self.vis_h)

      elif c == curses.KEY_HOME:
        self.change_current(-self.h)

      elif c == curses.KEY_END:
        self.change_current(self.h)

      elif c == curses.KEY_F3:
        self.window.display_text('help')

      elif c == curses.KEY_F2:
        self.window.display_text('log')

      elif c == curses.KEY_RESIZE:
        self.window.configure()
        self.window.update()
        self.window.draw()

      else:
        ret, run = self.handle_key(c)
        if ret is None:
          self.jump_to_chr(c)

    self.change_item(self.current, CP_HIGHLIGHTED)
    self.draw(nout=False, fill=False)
    return ret



class Menu(Scrollpad):

  def configure(self, choices, current=None, position=None):
    self.items = choices
    if current is not None:
      self.current = current
    if position is not None:
      self.position = position
    self.w = max(len(x) for x in choices)
    self.w = max(self.w, len(HDR_COMMANDS))
    self.h = len(choices)
    self.pad.resize(self.h+1, self.w)

  def handle_key(self, c):
    if c == curses.KEY_RIGHT:
      return self.window.checklist, False
    else:
      return None, True




class Checklist(Scrollpad):

  def configure(self, checklist, current=None, position=None, print_status=False):
    self.print_status = print_status
    self.update_items(checklist)
    if current is not None:
      if isinstance(current, str):
        current = self.items.index(current)
      self.current = current
    if position is not None:
      self.position = position

  def update_items(self, checklist):
    self.checklist = checklist
    if checklist:
      self.w = max(len(x) for x in checklist) + PREFIX_LEN
      if self.print_status:
        self.status_len = self.window.print_status(None, None, None, None, return_max=True)
        self.w += self.status_len
      else:
        self.status_len = 0
    else:
      self.w = 1
    try:
      self.w = max(self.w, self.vis_w)
    except AttributeError:
      pass
    self.h = len(checklist)
    self.pad.resize(self.h+1, self.w)
    self.items = sorted(self.checklist)

  def change_item(self, i, cp):
    if self.checklist:
      item = self.items[i]
      try:
        if self.checklist[item]:
          is_static = self.window.systemd.is_static(item)
          prefix, cp_prefix = self.window.get_checkbox(is_static=is_static)
        else:
          prefix = PREFIX_OFF
          cp_prefix = CP_OFF
      except KeyError:
        self.checklist[item] = False
        prefix = PREFIX_OFF
        cp_prefix = CP_OFF
      prefix_len = len(prefix)
      self.pad.addstr(
        i,
        0,
        prefix,
        curses.color_pair(cp_prefix)
      )
      self.pad.addstr(
        i,
        prefix_len,
        item.ljust(self.w - (prefix_len + self.status_len), ' '),
        curses.color_pair(cp)
      )
      if self.print_status:
        self.window.print_status(
          item,
          self.pad,
          i,
          self.w - self.status_len
        )

  def add_or_update_item(self, item):
    # Just update the item if it already exists.
    try:
      self.checklist[item] = (not self.checklist[item])
      self.current = self.items.index(item)
      self.change_item(self.current, CP_ACTIVE)
    except KeyError:
      self.checklist[item] = True
      self.configure(
        self.checklist,
        current=item,
        position=self.position,
        print_status=self.print_status,
      )
      self.draw()

  def prompt(self, msg):
    self.window.update_status(
      nout=False,
        line=PARAM_PROMPT,
        cp=curses.color_pair(CP_ENABLED),
        help=False
      )

    win = curses.newwin(
      1,
      self.window.w-PARAM_PROMPT_LEN,
      self.window.h-1,
      PARAM_PROMPT_LEN
    )
    textbox = curses.textpad.Textbox(win)
    # There is always a trailing space for some reason. The "strip" method could
    # probably be used here but someone may actually want to use leading and/or
    # trailing spaces for some weird reason.
    string = textbox.edit()[:-1]
    del textbox
    del win
    self.window.update_status(nout=False)
    return string

  def handle_key(self, c):
    if c == curses.KEY_LEFT:
      return self.window.menu, False

    elif c == ord(' '):
      item = self.items[self.current]
      command = self.window.menu.items[self.window.menu.current]

      if item.endswith('@.service'):
        parameter = self.prompt('Enter parameter for {}'.format(item))
        new_item = '{}@{}.service'.format(item[:-9], parameter)
        self.add_or_update_item(new_item)

      elif not (command == 'enable' and self.window.systemd.is_static(item)):
        self.checklist[item] = (not self.checklist[item])
        self.change_item(self.current, CP_ACTIVE)

      return True, True

    elif c == ord('\n'):
      self.window.run_command()
      return True, True

    else:
      return None, True



class StatusLine(object):
  def __init__(self, window, status):
    self.window = window
    self.pad = curses.newpad(1,1)
    self.configure(status)

  def configure(self, status, cp=None, help=True):
    self.status = status
    self.w = max(1, len(status), self.window.w)
    self.pad.resize(1, self.w+1)
    if cp is None:
      cp = curses.color_pair(CP_DEFAULT)
    self.pad.addstr(
      0,
      0,
      status.ljust(self.w, ' '),
      cp
    )
    if help:
      self.pad.addstr(
        0,
        self.w-HELP_MSG_LEN,
        HELP_MSG,
        curses.color_pair(CP_STATIC)
      )

  @ignore_curses_errors
  def draw(self, nout=False, clear=False):
    if clear:
      self.pad.clear()
    if nout:
      refresh = self.pad.noutrefresh
    else:
      refresh = self.pad.refresh
    refresh(
      0,
      0,
      self.window.h-1,
      0,
      self.window.h-1,
      self.window.w-1
    )



class Window(object):
  def __init__(self, stdscr, systemd):
    self.stdscr = stdscr
    self.systemd = systemd
    self.h, self.w = self.stdscr.getmaxyx()
    self.log = ''

    self.menu = Menu(self, sorted(MENU_COMMANDS))
    self.checklist = Checklist(self, dict())
    self.status = StatusLine(self, '')
    self.textpad = curses.newpad(1, 1)

    self.active = self.menu
    self.configure()

  def configure(self):
    self.h, self.w = self.stdscr.getmaxyx()

    while self.h < MIN_HEIGHT or self.w < MIN_WIDTH:
      self.stdscr.clear()
      while self.stdscr.getch() != curses.KEY_RESIZE:
        pass
      self.h, self.w = self.stdscr.getmaxyx()

    real_w = self.menu.w + self.checklist.w + 1
    self.vsplit = self.menu.w
    self.status.vis_w = self.w
    self.status.vis_h = 1
    self.status.vis_x = 0
    self.status.vis_y = max(0, self.h - 1)
    self.menu.vis_w = min(self.menu.w, self.w)
    self.menu.vis_h = max(self.h - (4 + self.status.vis_h), 0)
    self.menu.vis_x = 0
    self.menu.vis_y = 2
    self.checklist.vis_x = self.vsplit+1
    self.checklist.vis_y = 2
    self.checklist.vis_w = max(self.w - self.checklist.vis_x, 0)
    self.checklist.vis_h = self.menu.vis_h

  def update(self, previous=None):
    if self.active == self.menu:
      command = self.update_status(nout=False)

      if command == 'enable':
        self.checklist.configure(
          self.systemd.as_dict(self.systemd.enabled | self.systemd.static),
          print_status=True
        )

      elif command == 'start':
        self.checklist.configure(
          self.systemd.as_dict(self.systemd.started),
          print_status=True
        )

      else:
        print_status = True
        self.checklist.configure(
          self.systemd.as_dict(),
          print_status=print_status
        )

      self.checklist.draw(nout=False)

  @ignore_curses_errors
  def draw(self):
    self.stdscr.clear()
    self.stdscr.addstr(0, 0, HDR_COMMANDS)
    self.stdscr.addstr(0, self.vsplit+1, ' ' * PREFIX_LEN + HDR_SERVICES)
    self.stdscr.bkgdset(' ', curses.color_pair(CP_DEFAULT))
    self.stdscr.vline(0, self.vsplit, curses.ACS_SBSB, self.h-2)
    self.stdscr.hline(1, 0, curses.ACS_BSBS, self.w)
    self.stdscr.hline(self.h-2, 0, curses.ACS_BSBS, self.w)
    self.stdscr.addch(self.h-2, self.vsplit, curses.ACS_SSBS)
    self.stdscr.addch(1, self.vsplit, curses.ACS_SSSS)

    if self.active is not None:
      self.active.change_item(self.active.current, CP_ACTIVE)

    self.stdscr.noutrefresh()
    self.menu.draw()
    self.checklist.draw()
    self.update_status()
    curses.doupdate()

  def update_status(self, nout=True, line=None, cp=None, help=True):
    if line is None:
      command = self.menu.items[self.menu.current]
      try:
        line = MENU_COMMANDS[command]
      except KeyError:
        line = command
    else:
      command = None
    self.status.configure(line, cp=cp, help=help)
    if not nout:
      self.status.draw(nout=nout)
    return command

  def run(self):
    self.systemd.update()
    self.update()
    while self.active is not None:
      self.active = self.active.run()


  def print_status(self, item, window, y, x, return_max=False):
    if return_max:
      return 5 + self.systemd.sub_len
    else:
      window.addstr(y, x, self.systemd.get_sub(item), curses.color_pair(CP_DEFAULT))
      x += 2 + self.systemd.sub_len

      if self.systemd.is_started(item):
        c, cp = STATUS_SYMBOLS['start']
      elif self.systemd.is_error(item):
        c, cp = STATUS_SYMBOLS['error']
      else:
        c = ' '
        cp = CP_DEFAULT
      window.addstr(y, x, c, curses.color_pair(cp))
      x += 1

      window.addstr(y, x, ' ', curses.color_pair(CP_DEFAULT))
      x += 1

      if self.systemd.is_enabled(item):
        c, cp = STATUS_SYMBOLS['enable']
      elif self.systemd.is_static(item):
        c, cp = STATUS_SYMBOLS['static']
      else:
        c = ' '
        cp = CP_DEFAULT
      window.addstr(y, x, c, curses.color_pair(cp))
      x += 1


  def get_checkbox(self, is_static=False):
    command = self.menu.items[self.menu.current]
    if command == 'enable' and is_static:
      command = 'static'
    try:
      c, cp = STATUS_SYMBOLS[command]
      return c + ' ', cp
    except KeyError:
      return PREFIX_ON, CP_ON


  def run_command(self):
    command = self.menu.items[self.menu.current]
    changed = False
    selected = set(k for k,v in self.checklist.checklist.items() if v)

    if command == 'enable':
      enabled = self.systemd.enabled - self.systemd.static
      selected -= self.systemd.static
      newly_enabled = selected - enabled
      newly_disabled = enabled - selected

      if newly_enabled:
        self.log += self.systemd.run_command('enable', newly_enabled)
        self.log += '\n'
        changed = True

      if newly_disabled:
        self.log += self.systemd.run_command('disable', newly_disabled)
        self.log += '\n'
        changed = True

      if changed:
        self.systemd.update()
        self.checklist.update_items(
          self.systemd.as_dict(self.systemd.enabled | self.systemd.static)
        )
        self.checklist.draw()



    elif command in ('start', 'restart'):
      if selected:

        newly_started = selected - self.systemd.started
        if newly_started:
          self.log += self.systemd.run_command('start', newly_started)
          self.log += '\n'

        if command == 'restart':
          restarted = selected & self.systemd.started
          if restarted:
            self.log += self.systemd.run_command('restart', restarted)
            self.log += '\n'

        else:
          newly_stopped = self.systemd.started - selected
          if newly_stopped:
            self.log += self.systemd.run_command('stop', newly_stopped)
            self.log += '\n'

        self.systemd.update()
        if command == 'restart':
          toggled = None
        else:
          toggled = self.systemd.started
        self.checklist.update_items(self.systemd.as_dict(toggled))
        self.checklist.draw()


    else:
      if selected:
        self.log += self.systemd.run_command(command, selected)
        self.log += '\n'
        self.systemd.update()
        for k in self.checklist.checklist:
          self.checklist.checklist[k] = False
          self.checklist.draw()



  # TODO
  # Move to separate class.
  def display_text(self, what):

    padding_south = 2
    return_msg = 'Press return to go back to the main window.'
    return_msg_len = len(return_msg)

    if what == 'help':
      text = HELP_TEXT
      padding_south += len(STATUS_SYMBOLS)

    elif what == 'log':
      text = self.log
      if not text:
        text = 'There is currently no output to display here.'

    else:
      text = 'Invalid display [].'.format(what)

    lines = text.split('\n')
    w = max(max(len(x) for x in lines), return_msg_len)
    h = len(lines)
    x = 0
    y = 0
    scr_h, scr_w = self.stdscr.getmaxyx()
    self.stdscr.clear()
    self.textpad.clear()
    self.stdscr.refresh()

    self.textpad.resize(h+1+padding_south, w+1)
    for i in range(h):
      self.textpad.addstr(i, 0, lines[i].ljust(w, ' '), curses.color_pair(CP_DEFAULT))

    if what == 'help':
      for stat in sorted(STATUS_SYMBOLS):
        sym, cp = STATUS_SYMBOLS[stat]
        self.textpad.addstr(
          h-1, 0,
          "    {} : {}'d\n".format(sym, stat).ljust(w, ' '),
          curses.color_pair(cp)
        )
        h += 1
    else:
      h += 1

    self.textpad.addstr(
      h, 0,
      return_msg,
      curses.color_pair(CP_ACTIVE)
    )

    while True:
      try:
        scr_h, scr_w = self.stdscr.getmaxyx()
        self.textpad.refresh(y, x, 0, 0, max(1, scr_h-1), max(1, scr_w-1))
        curses.doupdate()
        c = self.stdscr.getch()


        if c == curses.KEY_RESIZE:
          continue

        elif c == ord('\n'):
            break

        elif c == curses.KEY_UP:
          y = max(y-1, 0)

        elif c == curses.KEY_DOWN:
          y = min(y+1, h-scr_h)

        elif c == curses.KEY_LEFT:
          x = max(x-1, 0)

        elif c == curses.KEY_RIGHT:
          x = min(x+1, w-scr_w)

        elif c == curses.KEY_PPAGE:
          y = max(y-scr_h, 0)

        elif c == curses.KEY_NPAGE:
          y = min(y+scr_h, h-scr_h)

        elif c == curses.KEY_HOME:
          y = 0

        elif c == curses.KEY_END:
          y = max(0, h-scr_h)


      except curses.error:
        continue

    self.configure()
    self.update()
    self.draw()




################################### Systemd ####################################
class Systemd(object):
  def __init__(self, bin, args):
    self.bin = bin
    self.args = args
    self.services = set()
    self.started = set()
    self.enabled = set()
    self.static = set()
    self.error = set()
    self.sub = dict()
    self.sub_len = 0
    self.err = None

  def as_dict(self, st=None):
    if st is None:
      foo = dict((x, False) for x in self.services)
    else:
      foo = dict()
      for s in self.services:
        foo[s] = (s in st)
    return foo

  def query_enabled(self):
    cmd = [
      self.bin,
      '--no-legend',
      'list-unit-files'
    ] + self.args

    try:
      output = subprocess.check_output(cmd)
    except subprocess.CalledProcessError:
      sys.stderr.write('error: failed to load systemd data\n')
      sys.exit(1)

    self.services.clear()
    self.enabled.clear()
    self.static.clear()
    for service in output.decode().strip().split('\n'):
      service = service.strip()
      if not service:
        continue
      name, status = service.split(None, 1)
      self.services.add(name)
      if status == 'enabled':
        self.enabled.add(name)
      elif status == 'static':
        self.static.add(name)


  def query_started(self):
    cmd = [
      self.bin,
      '--no-legend',
      '--all',
      '--full'
    ] + self.args

    try:
      output = subprocess.check_output(cmd)
    except subprocess.CalledProcessError:
      sys.stderr.write('error: failed to load systemd data\n')
      sys.exit(1)

    self.started.clear()
    self.sub.clear()
    self.sub_len = 0
    for line in output.decode().strip().split('\n'):
      name, loaded, active, sub, rest = line.split(None, 4)
      if not name in self.services:
        bname = '{}@.service'.format(name.split('@',1)[0])
        if bname in self.services:
          self.services.add(name)
          self.enabled.add(name)
        else:
          continue
      self.sub[name] = sub
      self.sub_len = max(self.sub_len, len(sub))
      if loaded == 'loaded' and active == 'active':
        self.started.add(name)
      elif loaded == 'error' or active == 'failed':
        self.error.add(name)

  def update(self):
    self.query_enabled()
    self.query_started()

  def is_enabled(self, unit):
    try:
      return (unit in self.enabled)
    except KeyError:
      return False

  def is_static(self, unit):
    try:
      return (unit in self.static)
    except KeyError:
      return False

  def is_started(self, unit):
    return (unit in self.started)

  def is_error(self, unit):
    return (unit in self.error)

  def get_sub(self, unit):
    try:
      return ' ' + self.sub[unit].rjust(self.sub_len, ' ') + ' '
    except KeyError:
      return ' ' * (self.sub_len + 2)


  def run_command(self, command, services):
    cmd = [
      self.bin,
    ] + self.args + [command,] + sorted(services)
    command = ' '.join(shlex.quote(x) for x in cmd)
    if DEBUG_LOG:
      debug(command)
      return
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
      output, err = p.communicate(cmd)
      self.err = None
      msg = command
      if output:
        msg += '\n' + output.decode()
      if err:
        msg += '\n' + err.decode()
      return msg
    except subprocess.TimeoutExpired as e:
      p.kill()
      self.err = str(e)
      return self.err
    except subprocess.CalledProcessError as e:
      self.err = str(e)
      return self.err

##################################### Main #####################################

def curses_main(stdscr, args):
  initialize()
  systemd = Systemd(args.bin, args.args)
  win = Window(stdscr, systemd)
  win.draw()
  win.run()

def main(args=None):
  args = argparser.parse_args(args)

  global DEBUG_LOG
  DEBUG_LOG = args.debug

  global MENU_COMMANDS
  for cmd in args.command:
    MENU_COMMANDS[cmd] = 'command-line argument'

  # Recalculate globals based on command-line options.
  global PREFIX_ON
  global PREFIX_OFF
  global PREFIX_LEN
  global MIN_HDR_WIDTH
  global MIN_STATUS_WIDTH
  global MIN_WIDTH

  MIN_STATUS_WIDTH = min(len(s) for s in MENU_COMMANDS.values())

  on_len = len(args.on)
  off_len = len(args.off)
  if on_len > off_len:
    args.off = args.off.ljust(on_len, ' ')
    PREFIX_LEN = on_len
  else:
    args.on = args.on.ljust(off_len, ' ')
    PREFIX_LEN = off_len
  PREFIX_ON = args.on
  PREFIX_OFF = args.off
  MIN_WIDTH = min(MIN_HDR_WIDTH, MIN_STATUS_WIDTH) + PREFIX_LEN + HELP_MSG_LEN + 1

  curses.wrapper(curses_main, args)

if __name__ == '__main__':
  try:
    main()
  except KeyboardInterrupt:
    pass
