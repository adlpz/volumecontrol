from subprocess import Popen, PIPE
from pacmd.parser import parseList

def run(command):
    p = Popen(['pacmd', command], stdout=PIPE)
    output = p.communicate()[0]
    return parseList(output)
