import subprocess
import time
import signal
import sys
import select
import os
from pathlib import Path
import shutil
import json

config_file = "config.json"

class factorio_server:
    """
    Note that due to the fact that the subprocess will forward the CTRL C command (SIGINT) to the subprocess, a shutdown function is not needed. 
    """

    
    def __init__(self, config_file: str) -> None:
        # create temp folder for saves
        if (not os.path.exists("temp/")):
            os.makedirs("temp/")
        with open(config_file) as f:
            data = json.load(f)
            self.save_name = data["save_name"]
            self.startup_command = ["./factorio/bin/x64/factorio", f"--port {data['port']}", "--start-server", f"./factorio/saves/{data['save_name']}", "--server-settings", f"./factorio/data/{data['server_settings']}"]
        # run the server
        self.server = self.run_server()

    def run_server(self): 
        # assume this file (main.py) is located in the same folder as the factorio. 
        # set stdin and stdout to pipe, and redirect stderr to stdout. set universal_newlines and bufsize for stdin input. 
        server = subprocess.Popen(self.startup_command, stdin = subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
        return server

    def restart_server(self):
        # send ctrl-c to the factorio server, then wait for it to close and run a new one. 
        self.server.send_signal(signal.SIGINT)
        self.server.wait()
        self.server = self.run_server()
        pass
    
    def print_to_server(self, cmd: str): 
        print(cmd, file = self.server.stdin, flush = True)
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")

    def handle_command(self, cmd: str): 
        if(len(cmd) < 26):
            return
        
        # if command is "\restart" then restart the server. 
        cmd = cmd.split(" ")
        if (cmd[2] == "[CHAT]"):
            if (cmd[-1] == "!!restart\n"):
                self.print_to_server("Receive restart signal. Restarting the server...")
                time.sleep(1)
                self.restart_server()
            elif (cmd[-1] == "!!shutdown\n"):
                self.print_to_server("Receive shutdown signal. Shutting down the server...")
                time.sleep(1)
                self.server.send_signal(signal.SIGINT)
            elif (cmd[-2] == "!!la" and cmd[-1][:-1].isdigit()):
                self.print_to_server("Receive load_autosave signal. loading autosave...")
                target = int(cmd[-1][:-1])
                self.load_autosave(target)
            elif (cmd[-1][:-1] == "!!la"):
                self.print_to_server("Receive load_autosave signal. loading autosave...")
                target = 1
                self.load_autosave(target)
            elif (cmd[-1] == "!!help\n"):
                self.print_to_server("!!shutdown         ->  shutdown the server\n")
                self.print_to_server("!!restart          ->  restart the server\n")
                self.print_to_server("!!la m             ->  load the autosaved file m files before current save\n")
                self.print_to_server("!!save             ->  save the current file immediately\n")
                self.print_to_server("!!ls               ->  load the previously saved file\n")
            elif (cmd[-1] == "!!save\n"):
                self.print_to_server("Receive save signal. Saving current file...")
                self.save_current()
            elif (cmd[-1] == "!!ls\n"):
                self.print_to_server("Receive load_last_save signal. Loading last save...")
                self.load_last_save()
            elif (cmd[-2] == "!!save"):
                self.print_to_server("Receive save signal. Saving current file...")
                self.save_current(cmd[-1][:-1])
            elif (cmd[-2] == "!!ls"):
                self.print_to_server("Receive load_last_save signal. Loading last save...")
                self.load_last_save(cmd[-1][:-1])
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

    def save_current(self, filename:str = "last_save"):
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
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")
        line = line.split(" ")
        if (line[-1] == "finished\n"):
            print("Saving is successful. Copying files now...")
            shutil.copy2(f"./factorio/saves/{self.save_name}", f"./factorio/saves/{filename}_{self.save_name}")
        else:
            # TODO: what the code should do if saving failed
            print("Saving failed. ")
            pass

    def load_last_save(self, filename:str = "last_save"):
        """
        load the targeting last save file. 
        """

        # save current game and store it for backup
        self.save_current_game()
        self.print_to_server(f"loading the last manual saved file")
        time.sleep(1)

        # shutdown server
        self.server.send_signal(signal.SIGINT)
        self.server.wait()

        # get autosave files and sort them in last modified time
        shutil.copy2(f"./factorio/saves/{filename}_{self.save_name}", f"./factorio/saves/{self.save_name}")

        # bootup server
        self.server = self.run_server()

    def load_autosave(self, target: int):
        """
        load the targeting autosave file. 
        """

        # save current game and store it for backup
        self.save_current_game()
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

    def save_current_game(self):
        """
        immediately save the game and save the file to a temp folder in case something went wrong
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
            shutil.copy2(f"./factorio/saves/{self.save_name}", f"./temp/{current_time}_{self.save_name}")
        else:
            # TODO: what the code should do if saving failed
            print("Saving failed. ")
            pass
        

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