import subprocess
import time
import signal
import sys
import select
import os
from pathlib import Path
import shutil


startup_command = ["./factorio/bin/x64/factorio", "--port 34197", "--start-server", "./factorio/saves/2024_1_15.zip", "--server-settings", "./factorio/data/server-settings.json"]
save_name = "2024_1_15.zip"


class factorio_server:
    """
    Note that due to the fact that the subprocess will forward the CTRL C command (SIGINT) to the subprocess, a shutdown function is not needed. 
    """

    
    def __init__(self, save_name) -> None:
        # create temp folder for saves
        if (not os.path.exists("temp/")):
            os.makedirs("temp/")
        # run the server
        self.server = self.run_server()
        self.save_name = save_name

    def run_server(self): 
        # assume this file (main.py) is located in the same folder as the factorio. 
        # set stdin and stdout to pipe, and redirect stderr to stdout. set universal_newlines and bufsize for stdin input. 
        server = subprocess.Popen(startup_command, stdin = subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
        return server

    def restart_server(self):
        # send ctrl-c to the factorio server, then wait for it to close and run a new one. 
        self.server.send_signal(signal.SIGINT)
        self.server.wait()
        self.server = self.run_server()
        pass

    def handle_command(self, cmd: str):
        if(len(cmd) < 26):
            return
        
        # if command is "\restart" then restart the server. 
        cmd = cmd.split(" ")
        if (cmd[2] == "[CHAT]"):
            if (cmd[-1] == "!!restart\n"):
                print("Receive restart signal. Restarting the server...")
                print("Receive restart signal. Restarting the server...\n", file = self.server.stdin, flush = True)
                time.sleep(1)
                self.restart_server()
            elif (cmd[-1] == "!!shutdown\n"):
                print("Receive shutdown signal. Shutting down the server...")
                print("Receive shutdown signal. Shutting down the server...\n", file = self.server.stdin, flush = True)
                time.sleep(1)
                self.server.send_signal(signal.SIGINT)
            elif (cmd[-2] == "!!la" and cmd[-1][:-1].isdigit()):
                print("Receive load_autosave signal. loading autosave...")
                print("Receive load_autosave signal. loading autosave...\n", file = self.server.stdin, flush = True)
                target = int(cmd[-1][:-1])
                self.load_autosave(target)
            elif (cmd[-1] == "!!help\n"):
                print("!!shutdown         ->  shutdown the server\n", file = self.server.stdin, flush = True)
                line = self.server.stdout.readline()
                print(f"server: {line}", flush = True, end = "")
                print("!!restart          ->  restart the server\n", file = self.server.stdin, flush = True)
                line = self.server.stdout.readline()
                print(f"server: {line}", flush = True, end = "")
                print("!!la m             ->  load the autosaved file m files before current save\n", file = self.server.stdin, flush = True)
                line = self.server.stdout.readline()
                print(f"server: {line}", flush = True, end = "")
                print("!!save             ->  save the current file immediately\n", file = self.server.stdin, flush = True)
                line = self.server.stdout.readline()
                print(f"server: {line}", flush = True, end = "")
                print("!!ls               ->  load the previously saved file\n", file = self.server.stdin, flush = True)
                line = self.server.stdout.readline()
                print(f"server: {line}", flush = True, end = "")
            elif (cmd[-1] == "!!save\n"):
                print("Receive save signal. Saving current file...")
                print("Receive save signal. Saving current file...\n", file = self.server.stdin, flush = True)
                self.save_current()
            elif (cmd[-1] == "!!ls\n"):
                print("Receive load_last_save signal. Loading last save...")
                print("Receive load_last_save signal. Loading last save...\n", file = self.server.stdin, flush = True)
                self.load_last_save()
            elif (cmd[-2] == "!!save"):
                print("Receive save signal. Saving current file...")
                print("Receive save signal. Saving current file...\n", file = self.server.stdin, flush = True)
                self.save_current(cmd[-1][:-1])
            elif (cmd[-2] == "!!ls"):
                print("Receive load_last_save signal. Loading last save...")
                print("Receive load_last_save signal. Loading last save...\n", file = self.server.stdin, flush = True)
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
        print(f"loading the last manual saved file", file = self.server.stdin, flush = True)
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
        print(f"loading the autosave {target} files before...", file = self.server.stdin, flush = True)
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
        line = self.server.stdout.readline()
        print(f"server: {line}", flush = True, end = "")
        line = line.split(" ")
        if (line[-1] == "finished\n"):
            print("Saving is successful. Copying files now...")
            current_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime())
            shutil.copy2(f"./factorio/saves/{self.save_name}", f"./temp/{current_time}_{save_name}")
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



server = factorio_server(save_name)

signal.signal(signal.SIGINT, signal.SIG_IGN)

if __name__ == "__main__":
    server.run()