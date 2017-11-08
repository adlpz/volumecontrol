#!/usr/bin/env python

#  volumecontrol - manage pulseaudio sinks and sources
#
#  copyright © 2017 Adria Lopez <adria@prealfa.com>
#
#  this program is free software. it comes without any warranty, to
#  the extent permitted by applicable law. you can redistribute it
#  and/or modify it under the terms of the do what the fuck you want
#  to public license, version 2, as published by the wtfpl task force.
#  see http://www.wtfpl.net/ for more details.

from cursesmenu import *
from cursesmenu.items import *
from pacmd.cli import run as pacmd
import json
import curses
import argparse
import sys
import os

os.environ.setdefault('ESCDELAY', '25')

volume_steps = 100

def parse_volume(volume_string):
    volumes = volume_string.split(',')
    parsed_volumes = []
    for volume in volumes:
        parts = list(map(lambda s: s.strip(), volume.split('/')))
        subparts = list(map(lambda s: s.strip(), parts[0].split(':')))
        parsed_volumes.append({
            "name": subparts[0],
            "volume": subparts[1],
            "percent": parts[1]})
    return parsed_volumes

def get_sinks():
    sinks = pacmd('list-sinks')

    active_item = None
    if 'activeItem' in sinks:
        active_item = sinks['activeItem']
        del sinks['activeItem']

    return {k: {"name": i["properties"]["device.description"],
                 "muted": True if i["muted"] == "yes" else False,
                 "volume": parse_volume(i["volume"]),
                 "max_volume": int(i["volume steps"]) - 1,
                 "active": True if k == active_item else False}
                 for k,i in sinks.items()}

def get_applications():
    apps = list(pacmd('list-sink-inputs').items());
    if len(apps) == 1 and apps[0][0] == -1:
        return {}
    return {k: {"name": v["properties"]["application.name"],
                "sink": v["sink"].split(" ")[0].strip()}
        for k,v in apps}

def set_default_sink(device):
    pacmd('set-default-sink ' + str(device))

def set_sink_volume(device, volume):
    pacmd('set-sink-volume ' + str(device) + ' ' + str(volume))

def set_application_sink(app, sink):
    pacmd('move-sink-input ' + str(app) + ' ' + str(sink))

def calculate_global_volume(volumes):
    return max(map(lambda v: int(v["volume"]), volumes))

def change_volume(direction, device, current_volumes, max_volume):
    volume_step = int(max_volume / volume_steps)
    global_volume = calculate_global_volume(current_volumes)
    if direction == "down":
        volume_step = -volume_step
    volume = global_volume + volume_step
    if (volume < 0):
        volume = 0
    set_sink_volume(device, volume)
    return volume

def volume_up(device):
    props = get_sinks()[device]
    return change_volume("up", device, props["volume"], props["max_volume"]) 

def volume_down(device):
    props = get_sinks()[device]
    return change_volume("down", device, props["volume"], props["max_volume"]) 

def toggle_mute(device):
    props = get_sinks()[device]
    pacmd('set-sink-mute ' + device + (' false' if props["muted"] else ' true'))

def get_sink_global_percent_volume(sink):
    return int(100* (calculate_global_volume(sink['volume'])/sink["max_volume"]))

class SinkMenuItem(MenuItem):
    def __init__(self, sink_id, sink):
        self.sink_id = sink_id
        self.sink = sink
        self.menu = None
        self.should_exit = False
    def show(self, index):
        selected_indicator = "[ X ]" if self.sink['active'] else "[   ]"
        name = self.sink['name']
        volume = get_sink_global_percent_volume(self.sink)
        volume = ("%4d%%" % volume) if not self.sink["muted"] else "Muted"
        return "%d - %s %-50s %s" % (index+1, selected_indicator, name, volume)
    def action(self):
        set_default_sink(self.sink_id)
    def volume_up(self):
        volume_up(self.sink_id)
    def volume_down(self):
        volume_down(self.sink_id)
    def toggle_mute(self):
        toggle_mute(self.sink_id)

class ModifiedCursesMenu(CursesMenu):
    def _wrap_start(self):
        """Overriden the original method to remove the call to terminal_reset(), which
        calls UNIX "reset", which waits 1 second before returning."""
        if self.parent is None:
            curses.wrapper(self._main_loop)
        else:
            self._main_loop(None)
        CursesMenu.currently_active_menu = None
        self.clear_screen()
        os.system("tput reset")
        CursesMenu.currently_active_menu = self.previous_active_menu
    def process_user_input(self):
        user_input = CursesMenu.process_user_input(self)

        if user_input == 27 or user_input == ord("q"):
            self.should_exit = True

        return user_input

class PacmdMenu(ModifiedCursesMenu):
    def rebuild(self):
        sinks = get_sinks()
        for i, sink in sinks.items():
            for menu_item in self.items:
                if isinstance(menu_item, SinkMenuItem):
                    if menu_item.sink_id == i:
                        menu_item.sink = sink
    # Overriden methods

    def draw(self):
        self.rebuild()
        CursesMenu.draw(self)

    def process_user_input(self):
        user_input = ModifiedCursesMenu.process_user_input(self)
        current_sink = self.items[self.current_option]

        if user_input == ord("m"):
            if isinstance(current_sink, SinkMenuItem):
                current_sink.toggle_mute()
                self.draw()
        elif user_input == curses.KEY_RIGHT:
            if isinstance(current_sink, SinkMenuItem):
                current_sink.volume_up()
                self.draw()
        elif user_input == curses.KEY_LEFT:
            if isinstance(current_sink, SinkMenuItem):
                current_sink.volume_down()
                self.draw()

        return user_input

class FastFunctionItem(FunctionItem):
    """This overrides the FunctionItem so it doest't call reset"""
    def set_up(self):
        self.menu.pause()
        curses.def_prog_mode()
        os.system("tput reset")
        self.menu.clear_screen()

class CallbackItem(MenuItem):
    def __init__(self, name, callback, menu):
        self.callback = callback
        MenuItem.__init__(self, sink['name'], menu=menu, should_exit=True)

class ApplicationMenuItem(SubmenuItem):
    def __init__(self, app_id, app, sinks):
        self.app_id = app_id
        self.app = app
        self.sinks = sinks
        self.menu = None
        self.should_exit = False

        sink_selection_submenu = ModifiedCursesMenu("Select sink for application " + app['name'])
        for k, sink in sinks.items():
            sink_selection_item = FastFunctionItem(sink["name"], lambda k=k: self.change_sink(k), menu=sink_selection_submenu, should_exit=True)
            sink_selection_submenu.append_item(sink_selection_item)
        self.submenu = sink_selection_submenu
    def show(self, index):
        if self.app['sink'] in self.sinks.keys():
            sink = self.sinks[self.app['sink']]
            return "%d - %-30s %s" % (index+1, self.app['name'], sink['name'])
        return "no clue"
    def change_sink(self, sink_id):
        set_application_sink(self.app_id, sink_id)
        self.rebuild()
        self.draw()
    def rebuild(self):
        applications = get_applications()
        self.app = applications[self.app_id]


def draw():
    menu = PacmdMenu("Volume Control")
    sinks = get_sinks()

    for i, sink in sinks.items():
        menu.append_item(SinkMenuItem(i, sink))

    applications_menu = ModifiedCursesMenu("Applications")

    applications = get_applications()
    for i, application in applications.items():
        application_menu_item = ApplicationMenuItem(i, application, sinks)
        applications_menu.append_item(application_menu_item)
        application_menu_item.set_menu(applications_menu)

    applications_submenu_item = SubmenuItem("Applications", submenu=applications_menu)
    applications_submenu_item.set_menu(menu)

    menu.append_item(applications_submenu_item)

    menu.show()

parser = argparse.ArgumentParser(description="Control the PulseAudio sound system")
parser.add_argument('action', metavar="ACTION", type=str, choices=["gui", "volume-up", "volume-down", "show-volume", "mute"])

args = parser.parse_args()
if args.action == "gui":
    draw()
else:
    sinks = get_sinks()
    current_sink = None
    for i,sink in sinks.items():
        if sink['active']:
            current_sink = sink
            current_sink["id"] = i
            break
    if current_sink is None:
        print("No sink is selected")
        sys.exit()

    if args.action == "volume-up":
        print(int(100*volume_up(current_sink["id"])/current_sink["max_volume"]))
    elif args.action == "volume-down":
        print(int(100*volume_down(current_sink["id"])/current_sink["max_volume"]))
    elif args.action == "show-volume":
        print(get_sink_global_percent_volume(sink))
    elif args.action == "mute":
        toggle_mute(sink)
