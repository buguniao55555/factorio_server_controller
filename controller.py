import subprocess
import time
import signal
import sys
import select
import os
from pathlib import Path
import shutil
import json
from urllib.request import Request, urlopen

config_file = "config.json"
MAX_MANUAL_SAVE = 100   # set largest manual save number
FILE_PER_PAGE = 5       # max file display in one page (for saves lookup)

class factorio_server:
    """
    Note that due to the fact that the subprocess will forward the CTRL C command (SIGINT) to the subprocess, a shutdown function is not needed. 
    """

    
    def __init__(self, config_file: str) -> None:

        # read the config.json file and initialize startup command
        with open(config_file) as f:
            data = json.load(f)
            # if no customized command, use default startup
            if (data["startup_command"] == "None"): 
                self.save_name = data["save_name"]
                self.factorio_dir = data["factorio_directory"]
                self.startup_command = [self.factorio_dir, f"--port {data['port']}", "--start-server", f"./factorio/saves/{data['save_name']}", "--server-settings", f"./factorio/data/{data['server_settings']}"]
            else:   # if there is customized command, use it
                self.startup_command = data["startup_command"]
        
        # check if save folder is created
        Path(f"saves/{self.save_name}").mkdir(parents=True, exist_ok=True)
        # run the server
        self.server = self.run_server()

    # 
    def run_server(self): 
        """ 
        Set stdin and stdout to pipe, and redirect stderr to stdout. set universal_newlines and bufsize for stdin input. 
        """
        server = subprocess.Popen(self.startup_command, stdin = subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
        return server

    def restart_server(self):
        """
        Send ctrl-c to the factorio server, then wait for it to close and run a new one. 
        """
        self.server.send_signal(signal.SIGINT)
        self.server.wait()
        self.server = self.run_server()
        pass
    
    def print_to_server(self, cmd: str): 
        """ Print command to factorio server

        Args:
            cmd (str): input commands
        """
        print(cmd, file = self.server.stdin, flush = True)
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")

    def handle_command(self, cmd: str): 
        """ Read outputs from server and handle them

        Args:
            cmd (str): output commands
        """

        # if unrelated cmd, return
        if(len(cmd) < 26):
            return
        
        # check commands and react to them
        cmd = cmd.split(" ")

        # if command from chat, check if there's any available commands
        if (cmd[2] == "[CHAT]"):
            if (cmd[-1] == "!!restart\n"):
                self.print_to_server("Receive restart signal. Restarting the server...")
                time.sleep(1)
                self.restart_server()
            elif (cmd[-1] == "!!shutdown\n"):
                self.print_to_server("Receive shutdown signal. Shutting down the server...")
                time.sleep(1)
                self.server.send_signal(signal.SIGINT)

            # load the designated autosave
            elif (cmd[-2] == "!!la" and cmd[-1][:-1].isdigit()):
                self.print_to_server("Receive load_autosave signal. loading autosave...")
                target = int(cmd[-1][:-1])
                self.load_autosave(target)

            # load the latest autosave
            elif (cmd[-1][:-1] == "!!la"):
                self.print_to_server("Receive load_autosave signal. loading autosave...")
                target = 1
                self.load_autosave(target)

            # print out help menu
            elif (cmd[-1] == "!!help\n"):
                self.print_to_server("!!shutdown         ->  shutdown the server\n")
                self.print_to_server("!!restart          ->  restart the server\n")
                self.print_to_server("!!la m             ->  load the autosaved file m files before current save, default m = 1\n")
                self.print_to_server("!!save             ->  save the current file immediately\n")
                self.print_to_server("!!ls               ->  load the previously saved file\n")
                self.print_to_server("!!ls ?             ->  check all saved file and restore from them\n")

            # save current save
            elif (cmd[-1] == "!!save\n"):
                self.print_to_server("Receive save signal. Saving current file...")
                self.save_current("request_save", cmd[3][:-1])

            # load the latest save
            elif (cmd[-1] == "!!ls\n"):
                self.print_to_server("Receive load_last_save signal. Loading last save...")
                self.load_last_save()
            
            # save current save with custom name
            elif (cmd[-2] == "!!save"):
                self.print_to_server("Receive save signal. Saving current file...")
                self.save_current(cmd[-1][:-1], cmd[3][:-1])

            # print out all saved files and let user to choose which to restore
            elif (cmd[-2] == "!!ls" and cmd[-1][:-1] == "?"):
                self.load_requested_save()
            
        return
    
    def run(self):
        while True:
            # listen to both server.stdout and sys.stdin. 
            read_fds = [self.server.stdout, sys.stdin]
            read_fds, _, _ = select.select(read_fds, [], [])
            for fd in read_fds:
                # if got something in sys.stdin, send it to the factorio server. 
                if (fd == sys.stdin):
                    line = sys.stdin.readline()
                    print(line, file = self.server.stdin, flush = True)
                else: # if got something in server.stdout, print it to sys.out. 
                    line = self.server.stdout.readline()
                    print(f"server: {line}", flush = True, end = "")
                    self.handle_command(line)
            if (self.server.poll() is not None):
                sys.exit(0)

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
        if (line[-1] == "finished\n"):
            print("Saving is successful. Copying files now...")
            current_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime())
            shutil.copy2(f"./factorio/saves/{self.save_name}", f"./saves/{self.save_name}/{current_time}_{filename}_{commander}")
        else:
            # TODO: what the code should do if saving failed
            print("Saving failed. ")
            pass

    def load_last_save(self):
        """
        load the targeting last save file. 
        """

        # save current game and store it for backup
        self.save_current()
        self.print_to_server(f"loading the last manual saved file")
        time.sleep(1)

        # shutdown server
        self.server.send_signal(signal.SIGINT)
        self.server.wait()

        # get autosave files and sort them in last modified time
        save_files = sorted(Path(f"saves/{self.save_name}").iterdir(), key=os.path.getmtime, reverse = True)
        save_files = list(i for i in save_files if ("autosave_server" not in str(i)))
        target_autosave = save_files[0]
        shutil.copy2(target_autosave, f"./factorio/saves/{self.save_name}")

        # bootup server
        self.server = self.run_server()

    def load_autosave(self, target: int):
        """
        load the targeting autosave file. 
        """

        # save current game and store it for backup
        self.save_current()
        self.print_to_server(f"loading the autosave {target} files before...")
        time.sleep(1)

        # shutdown server
        self.server.send_signal(signal.SIGINT)
        self.server.wait()

        # move target 1 before for indexing
        target -= 1

        # get autosave files and sort them in last modified time
        save_files = sorted(Path("factorio/saves/").iterdir(), key=os.path.getmtime, reverse = True)
        save_files = list(i for i in save_files if ("_autosave" in str(i)))
        target_autosave = save_files[target]
        shutil.copy2(target_autosave, f"./factorio/saves/{self.save_name}")

        # bootup server
        self.server = self.run_server()

    def load_requested_save(self):
        """
        load the targeting last save file. 
        """
        # get autosave files and sort them in last modified time
        save_files = sorted(Path(f"saves/{self.save_name}").iterdir(), key=os.path.getmtime, reverse = True)
        save_files = list(save_files)
        target_save = None

        self.print_to_server(f"choose the save you wish to recover")
        self.print_to_server(f"enter the index to choose the save file, n to view previous page, m to view next page, or q to quit")
        page_index = 0
        while True:
            for i in range(page_index, min(page_index + FILE_PER_PAGE, len(save_files))):
                self.print_to_server(f"{i - page_index + 1}: {save_files[i]}")
            while True:
                while True:
                    cmd = None
                    read_fds = [self.server.stdout, sys.stdin]
                    read_fds, _, _ = select.select(read_fds, [], [])
                    for fd in read_fds:
                        # if got something in sys.stdin, send it to the factorio server. 
                        if (fd == sys.stdin):
                            line = sys.stdin.readline()
                            print(line, file = self.server.stdin, flush = True)
                        else: # if got something in server.stdout, print it to sys.out. 
                            cmd = self.server.stdout.readline()
                            print(f"server: {cmd}", flush = True, end = "")
                    if (cmd is not None):
                        break
                cmd = cmd.split(" ")
                if (cmd[2] == "[CHAT]"):
                    if (cmd[-1][:-1] == "m"):
                        if (page_index + FILE_PER_PAGE < len(save_files)):
                            page_index += FILE_PER_PAGE
                        else:
                            self.print_to_server("this is the last page. ")
                    elif (cmd[-1][:-1] == "n"):
                        if (page_index - FILE_PER_PAGE >= 0):
                            page_index -= FILE_PER_PAGE
                        else:
                            self.print_to_server("this is the first page. ")
                    elif (cmd[-1][:-1] == "q"):
                        return
                    elif (cmd[-1][:-1].isdigit()):
                        req_index = int(cmd[-1][:-1])
                        if (req_index > page_index + FILE_PER_PAGE):
                            self.print_to_server("invalid file number. ")
                        else:
                            target_save = save_files[page_index + req_index - 1]
                            break
                    else:
                        self.print_to_server("you are currently in save recover mode. ")
                        self.print_to_server(f"choose the save you wish to recover. ")
                        self.print_to_server(f"enter the index to choose the save file, n to view previous page, m to view next page, or q to quit. ")
                        break
            if (target_save is not None):
                break
        
            

        # save current game and store it for backup
        self.save_current()

        # shutdown server
        self.server.send_signal(signal.SIGINT)
        self.server.wait()

        # get request file and copy to game save folder
        shutil.copy2(target_save, f"./factorio/saves/{self.save_name}")

        # bootup server
        self.server = self.run_server()

    def auto_update():
        # get the latest headless server version and check local version
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



server = factorio_server(config_file)

signal.signal(signal.SIGINT, signal.SIG_IGN)

if __name__ == "__main__":
    server.run()