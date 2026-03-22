import subprocess
import time
import signal
import sys
import select
import os
import re
from pathlib import Path
import shutil
import json
from urllib.request import Request, urlopen

CONFIG_FILE = "config.json"
MAX_MANUAL_SAVE = 100   # set largest manual save number
FILE_PER_PAGE = 5       # max file display in one page (for saves lookup)

CONSOLE_PATTERN = r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(\w+)\] (.*?) (.*)"

class FactorioController:
    """
    Note that due to the fact that the subprocess will forward the CTRL C command (SIGINT) to the subprocess, a shutdown function is not needed. 
    """

    def __init__(self, config_file: str) -> None:
        # read the config.json file and initialize startup command
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
            # if no customized command, use default startup
            if config["startup_command"] == "None":
                self.save_name = config["save_name"]
                self.factorio_dir = config["factorio_directory"]
                self.startup_command = [self.factorio_dir, f"--port {config['port']}", "--start-server", f"./factorio/saves/{config['save_name']}", "--server-settings", f"./factorio/data/{config['server_settings']}"]
            else:   # if there is customized command, use it
                self.startup_command = config["startup_command"]
            self.save_maxsize = config["save_maxsize"]
        
        # check if save folder is created
        Path(f"saves/{self.save_name}").mkdir(parents=True, exist_ok=True)
        # run the server
        self.start_server()

    def start_server(self):
        """ 
        Set stdin and stdout to pipe, and redirect stderr to stdout. set universal_newlines and bufsize for stdin input. 
        """
        server = subprocess.Popen(self.startup_command, stdin = subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
        self.server = server

    def stop_server(self):
        """ 
        Send ctrl-c to the factorio server, then wait for it to close. 
        """
        self.server.send_signal(signal.SIGINT)
        self.server.wait()

    def restart_server(self):
        """
        Restart the factorio server by stopping and starting it again.
        """
        self.stop_server()
        self.start_server()

    def print_to_server(self, msg: str, username: str = ""):
        """
        Print command to factorio server
        Args:
            msg (str): input commands
        """
        if username == "":
            print(msg, file = self.server.stdin, flush = True)
        else:
            print(f"/w {username} {msg}", file = self.server.stdin, flush = True)
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")

    def handle_command(self, cmd: str):
        """ Read outputs from server and handle them

        Args:
            cmd (str): output commands
        """
        # user message format:
        # yyyy-mm-dd hh:mm:ss [JOIN] <username> joined the game
        # yyyy-mm-dd hh:mm:ss [CHAT] <username>: message
        # yyyy-mm-dd hh:mm:ss [LEAVE] <username> left the game

        # server message format:
        # yyyy-mm-dd hh:mm:ss [CHAT] \<server\>: message

        valid, *result = self.parse_chat_msg(cmd)
        if not valid:
            # not a user message or server message, ignore
            return

        _date, _time, _msg_type, username, message = result
        messages = message.split(" ")

        # if command from chat, handle it if it's a valid command
        #TODO: update python to 3.10+
        match messages:
            case ["!!restart", *_]:
                self.print_to_server("Receive restart signal. Restarting the server...")
                time.sleep(1)
                self.restart_server()
            
            case ["!!shutdown", *_]:
                self.print_to_server("Receive shutdown signal. Shutting down the server...")
                time.sleep(1)
                self.stop_server()

            case ["!!help", *_]:
                self.print_to_server("!!shutdown         ->  shutdown the server\n", username)
                self.print_to_server("!!restart          ->  restart the server\n", username)
                self.print_to_server("!!la m             ->  load the autosaved file m files before current save, default m = 1\n", username)
                self.print_to_server("!!save             ->  save the current file immediately\n", username)
                self.print_to_server("!!ls               ->  load the previously saved file\n", username)
                self.print_to_server("!!ls ?             ->  check all saved file and restore from them\n", username)

            case ["!!save", *rest]:
                self.handle_command_save(username, rest)

            case ["!!ls", *rest]:
                self.handle_command_ls(username, rest)

            case ["!!la", *rest]:
                self.handle_command_la(username, rest)

            case _:
                # ignore
                pass
        return

    def handle_command_save(self, username: str, rest: list):
        if len(rest) > 0:
            filename = rest[0]
            self.print_to_server(f"Receive save signal. Saving current file with name {filename}...", username)
            self.save_current(filename, username)
        else:
            self.print_to_server("Receive save signal. Saving current file...")
            self.save_current("request_save", username)

    def handle_command_la(self, username: str, rest: list):
        if len(rest) > 0 and rest[0].isdigit():
            target_index = int(rest[0])
            self.print_to_server(f"Receive load_autosave signal. loading autosave {target_index} files before current save...", username)
        else:
            target_index = 1
            self.print_to_server(f"Receive load_autosave signal. loading the last autosave...", username)

        target_save = self.get_autosave_with_index(target_index)
        if target_save is not None:
            self.load_requested_save(target_save)
        else:
            self.print_to_server(f"Cannot find the autosave {target_index} files before current save. Please check if the index is correct. ")

    def handle_command_ls(self, username: str, rest: list):
        match rest:
            case ["?", *_]:
                target_save = self.get_requested_save()
                if target_save is not None:
                    self.load_requested_save(target_save)

            case [target_name, *_]:
                self.print_to_server(f"Receive load_with_name signal. Loading the save file {target_name}...")

                target_save = self.get_save_with_name(target_name)
                if target_save is not None:
                    self.load_requested_save(target_save)
                else:
                    self.print_to_server(f"Cannot find the save file {target_name}. Please check if the name is correct. ")

            case _:
                self.print_to_server("Receive load_last_save signal. Loading last manual save...", username)

                target_save = self.get_last_manual_save()
                if target_save is not None:
                    self.load_requested_save(target_save)
                else:
                    self.print_to_server("Cannot find any manual save file. ")

    def get_save_with_name(self, target_name: str):
        save_files = self.__get_saves()
        for i, save in enumerate(save_files):
            if i > 100:
                return
            save_name, *_ = self.parse_file_name(str(save))
            if save_name == target_name:
                return save

    def get_last_manual_save(self):
        manual_saves = self.__get_manual_saves()
        if len(manual_saves) > 0:
            return manual_saves[0]

    def get_autosave_with_index(self, target: int):
        autosaves = self.__get_autosaves()
        if target - 1 < len(autosaves):
            return autosaves[target - 1]

    def run(self):
        while True:
            cmd = self.wget_next_msg()
            if cmd is not None:
                self.handle_command(cmd)
            if self.server.poll() is not None:
                sys.exit(0)

    def cleanup_exceeding_saves(self):
        total_size = 0
        for save in self.__get_saves():
            if total_size > self.save_maxsize:
                try:
                    save.unlink(missing_ok=True)
                except FileNotFoundError as e:
                    print("file deletion failed. ")
                    print(e)
                continue
            if save.is_file():
                total_size += save.stat().st_size

    def save_current(self, filename:str = "autosave", commander: str = "server"):
        """
        immediately save the game and save the file to the same folder
        """
        print("/server-save", file = self.server.stdin, flush = True)
        # Check if saving is successful
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")
        line = line.split(" ")
        if line[-1] == "finished\n":
            print("Saving is successful. Copying files now...")
            current_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime())
            shutil.copy2(f"./factorio/saves/{self.save_name}", f"./saves/{self.save_name}/{current_time}_{filename}_{commander}")
        else:
            # TODO: what the code should do if saving failed
            print("Saving failed. ")

        self.cleanup_exceeding_saves()

    def load_requested_save(self, target_save: Path):
        # save current game and store it for backup
        self.save_current()
        time.sleep(1)

        # shutdown server
        self.stop_server()

        # get request file and copy to game save folder
        shutil.copy2(target_save, f"./factorio/saves/{self.save_name}")

        # bootup server
        self.start_server()

    def parse_chat_msg(self, msg: str):
        """ parse the chat message

        Args:
            msg (str): assume not None

        Returns:
            valid(bool): whether the message is a valid chat message
            
            date, time, msg_type, username, message: parsed message if valid, message is stripped
        """
        match_result = re.match(CONSOLE_PATTERN, msg)
        if match_result is None:
            return False, "", "", "", "", ""
        
        _date, _time, msg_type, username, message = match_result.groups()
        if msg_type != "[CHAT]":
            return False, "", "", "", "", ""
        
        return True, _date, _time, msg_type, username, message.strip()

    def wget_next_msg(self):
        """
        wait to get next message from server.stdout or sys.stdin and route it to the corresponding port.
        also return the message if it's from server.stdout.
        """
        cmd = None
        read_fds = [self.server.stdout, sys.stdin]
        read_fds, _, _ = select.select(read_fds, [], [])
        for fd in read_fds:
            # if got something in sys.stdin, route it to the factorio server.
            if fd == sys.stdin:
                line = sys.stdin.readline()
                print(line, file = self.server.stdin, flush = True)
            else: # if got something in server.stdout, print it to sys.out.
                cmd = self.server.stdout.readline()
                print(f"server: {cmd}", flush = True, end = "")
                return cmd
        return None

    def wget_next_chat_msg(self):
        """
        wait to get next message from server.stdout and return it if it's from chat.
        """
        while True:
            cmd = self.wget_next_msg()
            if cmd is None:
                # message not from server.stdout
                continue

            valid, *result = self.parse_chat_msg(cmd)
            if valid:
                return result

    def handle_user_act_to_ls(self, cmd: str, page_index: int, n_files: int):
        """
        handle user's action to the save file list.
        Args:
            cmd: the user's command
            page_index: the current page index
            n_files: the total number of save files
        Returns:
            page_index: the updated page index
            req_index: the index of the requested save file, or None for invalid input
        """
        new_page_index = page_index
        req_index = None

        match cmd:
            case "m":
                if page_index + FILE_PER_PAGE < n_files:
                    new_page_index += FILE_PER_PAGE
                else:
                    self.print_to_server("[color=red]ERROR: this is the last page.[/color]")
            case "n":
                if page_index - FILE_PER_PAGE >= 0:
                    new_page_index -= FILE_PER_PAGE
                else:
                    self.print_to_server("[color=red]ERROR: this is the first page.[/color]")
            case "q":
                new_page_index = None
            case _ if cmd.isdigit():
                req_index = int(cmd)
                if req_index > FILE_PER_PAGE or req_index <= 0:
                    self.print_to_server("invalid file number. ")
                    req_index = None
            case _:
                self.print_to_server("you are currently in save recover mode. ")
                self.print_to_server("choose the save you wish to recover. ")
                self.print_to_server("enter the index to choose the save file, [color=#FF3F3F]n[/color] to view previous page, [color=#FF3F3F]m[/color] to view next page, or [color=#FF3F3F]q[/color] to quit.")
        return new_page_index, req_index

    def parse_file_name(self, file_name: str):
        """
        parse the file name and return the save number and the save type
        """
        # saves/bugu_spaceage.zip/2024_12_02_11_30_45_request_save_bugu
        file_name = file_name.split("/")[-1]
        file_name = file_name.split("_")
        save_time = file_name[:6]
        save_time = f"{save_time[0]}/{save_time[1]}/{save_time[2]} {save_time[3]}:{save_time[4]}:{save_time[5]}"
        save_name = file_name[6:-1]
        save_name = " ".join(save_name)
        save_user = file_name[-1]
        return save_name, save_user, save_time

    def get_requested_save(self):
        """
        load the targeting last save file. 
        """
        save_files = self.__get_saves()
        n_files = len(save_files)

        self.print_to_server("choose the save you wish to recover")
        page_index = 0
        while True:
            # interact with user until selected a save file or manually quit
            self.print_to_server("enter the index to choose the save file, [color=#FF3F3F]n[/color] to view previous page, [color=#FF3F3F]m[/color] to view next page, or [color=#FF3F3F]q[/color] to quit.")
            for i in range(page_index, min(page_index + FILE_PER_PAGE, n_files)):
                save_name, save_user, save_time = self.parse_file_name(str(save_files[i]))
                self.print_to_server(f"    [color=#FF3F3F][{i - page_index + 1}][/color]: [color=#66CCFF]{save_name}[/color] saved by [color=#66CCFF]{save_user}[/color] at UTC [color=#66CCFF]{save_time}[/color]")

            _date, _time, _msg_type, _user_name, cmd = self.wget_next_chat_msg()

            page_index, req_index = self.handle_user_act_to_ls(cmd, page_index, n_files)
            if page_index is None:
                # pressed 'q' for quit
                self.print_to_server("quit save recover mode.")
                return None
            if req_index is not None:
                return save_files[page_index + req_index - 1]

    def __get_saves(self):
        """
        get all the save files in the save folder and sort them by modified time. 
        """
        save_files = sorted(Path(f"saves/{self.save_name}").iterdir(),
                            key=os.path.getmtime, reverse = True)
        return save_files

    def __get_manual_saves(self):
        """
        get all the manual save files in the save folder and sort them by modified time. 
        """
        save_files = self.__get_saves()
        manual_saves = list(i for i in save_files if "autosave_server" not in str(i))
        return manual_saves

    def __get_autosaves(self):
        """
        get all the autosave files in the save folder and sort them by modified time. 
        """
        save_files = self.__get_saves()
        autosaves = list(i for i in save_files if "autosave_server" in str(i))
        return autosaves

    def auto_update(self):
        """get the latest headless server version and check local version"""
        req = Request(
            url='https://factorio.com/api/latest-releases',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        latest = json.loads(urlopen(req).read().decode('utf-8'))["stable"]["headless"]


def test():
    p = subprocess.Popen(["python3", "out.py", "-l"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # returns None while subprocess is running
    line = p.stdout.readline()
    print(line)
    sys.stdout.flush()
    print(b"test", file=p.stdin, flush=True)
    line = p.stdout.readline()
    print(line)
    sys.stdout.flush()



controller = FactorioController(CONFIG_FILE)

# ignore the SIGINT signal from the terminal
signal.signal(signal.SIGINT, signal.SIG_IGN)

if __name__ == "__main__":
    controller.run()