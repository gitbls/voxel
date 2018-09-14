# voxel
command-line voice-activated recorder.
This is a voice-activated recorder with a command line interface only (no GUI). When it's running it accepts single-letter commands:
* h - Print some help
* f - Print the current filename
* k - Print the peak and trigger levels
* q - Quit
* p - Start or stop the peak level meter
* r - Turn recording on/off
* v - Set the sound trigger level. You'll be prompted for a peak level

Help for the command-line interface
usage: voxel.py COMMAND [-h] [-c CHUNK] [-d DEVNO] [-s SAVERECS] [-t THRESHOLD] [-l HANGDELAY]
COMMAND is:
    * record - enter record mode
    * listdevs - list the sound devices
    
    Requires Python3 and the modules python3-pyaudio python3-numpy libasound2-dev
    
    With thanks to https://github.com/russinnes/py-vox-recorder, on which this code is loosely based.
