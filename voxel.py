#!/usr/bin/python3

# Based on https://github.com/russinnes/py-vox-recorder/blob/master/py-corder-osx.py
# apt-get install python3-pyaudio python3-numpy libasound2-dev

import argparse
# Alsa blarg error blocking imports
# See https://stackoverflow.com/questions/7088672/pyaudio-working-but-spits-out-error-messages-each-time
#     for original code
from ctypes import *
from contextlib import contextmanager
# These 3 for tty status checking
import sys
import tty
import termios
# These for the sound stuff
import pyaudio
import threading
import time
import numpy as np
import queue
import wave

FORMAT = pyaudio.paInt16
CHANNELS = 1

class voxdat:
    def __init__(self):
        self.devindex = self.threshold = self.saverecs = self.hangdelay = self.chunk = self.devrate = self.current = self.rcnt = 0
        self.recordflag = self.running = self.peakflag = False
        self.rt = self.km = self.ttysettings = self.ttyfd = self.pyaudio = self.devstream = self.processor = None
        self.preque = self.samplequeue = None

# Alsa error message blocking

ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)

def py_error_handler(filename, line, function, err, fmt):
    pass

c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)

@contextmanager
def noalsaerr():
    asound = cdll.LoadLibrary('libasound.so')
    asound.snd_lib_error_set_handler(c_error_handler)
    yield
    asound.snd_lib_error_set_handler(None)

# Code for the app

class _streamProcessor(threading.Thread):
    def __init__(self, pdat):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.pdat = pdat
        self.rt = self.pdat.rt
#        self.queue = self.pdat.samplequeue
#        self.prequeue = self.pdat.preque
        self.wf = None
        self.filename = "No File"
        
    def run(self):
        while self.pdat.running:
            data = self.pdat.samplequeue.get(1)
            if data == None:
                time.sleep(0.1)
            else:
                data2 = np.fromstring(data,dtype=np.int16)
                peak = np.average(np.abs(data2))
                peak = (100*peak)/2**12
                self.pdat.current = int(peak)
                if self.pdat.current > self.pdat.threshold:
                    self.rt.reset_timer(time.time())
                if self.pdat.recordflag:
                    if not self.wf:
                        self.filename = time.strftime("%Y%m%d-%H%M%S.wav")
                        print("opening file " + self.filename + "\r")
                        self.wf = wave.open(self.filename, 'wb')
                        self.wf.setnchannels(CHANNELS)
                        self.wf.setsampwidth(self.pdat.pyaudio.get_sample_size(FORMAT))
                        self.wf.setframerate(self.pdat.devrate)
                        if self.pdat.rcnt != 0:
                            self.pdat.rcnt = 0
                            while True:
                                try:
                                    data3 = None
                                    data3 = self.pdat.preque.get_nowait()
                                    self.wf.writeframes(data3)
                                except:
                                    pass
                                if data3 == None: break
                                pass
                    self.wf.writeframes(data)
                else:
                    if self.pdat.rcnt == self.pdat.saverecs:
                        data3 = self.pdat.preque.get_nowait()
                    else:
                        self.pdat.rcnt +=1  #  self.pdat.rcnt+1
                    self.pdat.preque.put(data)
                    pass
             
    def ReadCallback(self, indata, framecount, timeinfo, status):
        self.pdat.samplequeue.put(indata)
        if self.pdat.running:
            return(None, pyaudio.paContinue)
        else:
            return(None, pyaudio.paAbort)

    def close(self):
        if self.wf:
            self.wf.close()
            self.wf = False
            self.filename = "No File"

class _recordTimer(threading.Thread):
    def __init__(self, pdat):
        threading.Thread.__init__(self)
        self.pdat = pdat
        self.setDaemon(True)
        self.timer = 0
        
    def run(self):
        while self.pdat.running:
            if time.time() - self.timer < self.pdat.hangdelay:
                self.pdat.recordflag = True
            if time.time() - self.timer > self.pdat.hangdelay + 1:
                self.pdat.recordflag = False
                self.pdat.processor.close()
            if self.pdat.peakflag:
                nf = min (self.pdat.current, 99)
                nf2 = nf
                if nf > 50: nf = int(min(50 + (nf - 50)/3, 72))
                if nf <= 0: nf=1
                rf = ""
                if self.pdat.recordflag: rf = "*"
                print("{} {}{}\r".format("#"*nf, nf2, rf))
            time.sleep(1)
                
    def reset_timer(self, timer):
        self.timer = timer

class KBListener(threading.Thread):
    def __init__(self,pdat):
        threading.Thread.__init__(self)
        self.pdat = pdat
        self.setDaemon(True)

    def treset(self):
        termios.tcsetattr(self.pdat.ttyfd, termios.TCSADRAIN, self.pdat.ttysettings)

    def getch(self):
        try:
            tty.setraw(self.pdat.ttyfd)
            ch = sys.stdin.read(1)
            self.treset()
        finally:
            self.treset()
        return ch
    
    def rstop(self):
        self.pdat.rt.reset_timer(0)
        self.pdat.recordflag = False
        self.pdat.threshold = 100
        self.pdat.processor.close()

    def run(self):
        self.pdat.ttyfd = sys.stdin.fileno()
        self.pdat.ttysettings = termios.tcgetattr(self.pdat.ttyfd)
        while self.pdat.running:
            ch = self.getch()
            if ch == "h" or ch == "?":
                print("h: help, f: show filename, k:show peak level, p: show peak")
                print("q: quit, r: record on/off, v: set trigger level")
            elif ch == "k":
                print("Peak/Trigger: " + str(self.pdat.current) + " " + str(self.pdat.threshold))
            elif ch == "v":
                self.treset()
                pf = self.pdat.peakflag
                self.pdat.peakflag = False
                try:
                    newpeak = int (input("New Peak Limit: "))
                except:
                    newpeak = 0
                if newpeak == 0:
                    print("? Number not recognized")
                else:
                    self.pdat.threshold = newpeak
                self.pdat.peakflag = pf
            elif ch == "f":
                if self.pdat.recordflag:
                    print("Filename: " + self.pdat.processor.filename)
                else:
                    print("Not recording")
            elif ch == "r":
                if self.pdat.recordflag:
                    self.rstop()
                    print("Recording disabled")
                else:
                    self.pdat.recordflag = True
                    self.pdat.threshold = 1
                    self.pdat.rt.reset_timer(time.time())
                    print("Recording enabled")
            elif ch == "p":
                self.pdat.peakflag = not self.pdat.peakflag
            elif ch == "q":
                print("Quitting...")
                self.rstop()
                self.pdat.running = False
                self.treset()
                time.sleep(0.5)
#
# Main code. Parse command and execute
#
parser = argparse.ArgumentParser()
parser.add_argument("command", choices=['record', 'listdevs'],   help="'record' or 'listdevs'")
parser.add_argument("-c", "--chunk",     type=int, default=8192, help="Chunk size [8192]")
parser.add_argument("-d", "--devno",     type=int, default=2,    help="Device number [2]")
parser.add_argument("-s", "--saverecs",  type=int, default=8,    help="Records to buffer ahead of threshold [8]")
parser.add_argument("-t", "--threshold", type=int, default=99,   help="Minimum volume threshold (1-99) [99]")
parser.add_argument("-l", "--hangdelay", type=int, default=6,    help="Seconds to record after input drops below threshold [6]")
args = parser.parse_args()
pdat = voxdat()

pdat.devindex = args.devno
pdat.threshold = args.threshold
pdat.saverecs =  args.saverecs
pdat.hangdelay = args.hangdelay
pdat.chunk = args.chunk
#
# Fire up PyAudio and process the request
#
with noalsaerr():
    pdat.pyaudio = pyaudio.PyAudio()

if args.command == "listdevs":
    print("Device Information:")
    for i in range(pdat.pyaudio.get_device_count()):
        print("Dev#: ",i, pdat.pyaudio.get_device_info_by_index(i).get('name'))
else:
    pdat.samplequeue = queue.Queue()
    pdat.preque = queue.Queue()

    pdat.running = True
    pdat.rt = _recordTimer(pdat)
    pdat.processor = _streamProcessor(pdat)
    pdat.processor.start()
    pdat.rt.start()

    pdat.devrate = int(pdat.pyaudio.get_device_info_by_index(pdat.devindex).get('defaultSampleRate'))
    pdat.devstream = pdat.pyaudio.open(format=FORMAT,
                                             channels=CHANNELS,
                                             rate=pdat.devrate,
                                             input=True,
                                             input_device_index=pdat.devindex,
                                             frames_per_buffer=pdat.chunk,
                                             stream_callback=pdat.processor.ReadCallback)
    pdat.devstream.start_stream()

    pdat.km = KBListener(pdat)
    pdat.km.start()

    while pdat.running:
        time.sleep(1)

print("Done.")
