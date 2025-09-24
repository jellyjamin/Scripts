import subprocess
import time
import os

##################################################
#               command definitions              #
##################################################

# This runs a command and only moves on when its finished.
# Great for doing sequential commands without using time.sleep(time in seconds here)

def Await_run(command):
    process = subprocess.Popen(command, shell=True)
    process.wait()  

# This just runs a command unabridged 

def runnext(command):
    subprocess.run(command, shell=True)

# This opens the command in a seperate shell, good for looping scripts or looping docker containers in a modular way.

def isolated_run(command):
    process = subprocess.Popen(command, shell=True)

##################################################
#             executive commands example         #
##################################################

# cleanup = "sudo apt autoremove -y ; sudo apt autoclean -y ; sudo apt clean -y"
# Await_run(cleanup)

# #update
# update = "sudo apt update"
# Await_run(update)

# #upgrade
# upgrade = "sudo apt upgrade -y"
# Await_run(upgrade)

# time.sleep(5)

# # second way to script commands

# runnext('sudo docker system prune -af')