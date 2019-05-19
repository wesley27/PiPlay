#!/usr/bin/env python3
import alsaaudio
from lxml import etree
import mpv
import requests
import socket
import threading
import time
import urllib.request

# TODO
# volume improvements
# skip should be able to skip to autoplay if nothing in queue
# add a stop command to stop whatever is currently playing
# autoplay needs to be worked on so it doesn't repeat, currently repeats after a few songs
# running the skip command breaks the queue for some reason, look into this

HOST = "0.0.0.0"
PORT = 2727

VERSION = "1.1"
CMDLET = "---> "

player = ""
queue = []
autoplay = ""
connections = []
active_timer = ""

def send(conn, msg="", cmdlet=True):
    if not cmdlet:
        conn.sendall(("%s\n" % (msg)).encode())
        if "Welcome" not in msg:
            send(conn)
    else:
        conn.sendall(("\n%s" % (CMDLET)).encode())

def send_help(conn):
    HELPMSG = """The following commands exist:
    \tplay <YouTube URL>\t- Adds a song to the queue.
    \tplaynow <YouTube URL>\t- Stops the current song and plays the requested URL.
    \tskip\t\t\t- Skips the current song and moves to the next one.
    \tqueue\t\t\t- Shows the current song queue.
    \tvol <0-100>\t\t- Sets the volume level.
    \thelp\t\t\t- Shows this help message.
    \texit\t\t\t- Exits this PiPlay connection.\n"""
    conn.sendall(HELPMSG.encode())

def grab_autoplay(conn, url):
    global autoplay
    html = requests.get(url).text

    # pull the URL from youtube's autoplay "up next" feature
    html = html[html.index("Up next"):]
    html = html[html.index("href"):html.index("href")+100]
    url = "https://www.youtube.com%s" % (html.split('"')[1])

    autoplay = url

def play(conn, url):
    global player, connections, active_timer
    try:
        # load url into mpv
        player.play(url)
        player.fullscreen = True

        # keep track of when songs were started so that a playlist will only run for 6 minutes before moving on in the queue
        active_timer = time.time()

        # get song name cause mpv doesn't get it when streamed
        link = etree.HTML(urllib.request.urlopen(url).read())
        title = link.xpath("//span[@id='eow-title']/@title")

        # if there's nothing in the queue to play after this song, grab the autoplay up next from youtube
        if len(queue) == 0:
            grab_autoplay(conn, url)
        for c in connections:
            
            send(c, "\nNow playing %s" % (''.join(title)), False)
    except ValueError:
        if conn is not None:
            send(conn, "Invalid URL entered.", False)

def cycle_queue():
    global player, queue, autoplay, active_timer

    # loop every 7 seconds checking queue
    while True:
        time.sleep(7)
        # if no song is playing and there is something in the queue, play it
        if player.playtime_remaining is None or (time.time() - active_timer > 360):
            if len(queue) > 0:
                play(None, queue.pop(0))
            else:
                # nothing is playing and queue is empty, close player
                if autoplay != "":  # skip if autoplay is its initial value of empty string
                    play(None, autoplay)

def handle_server(conn, addr):
    print("Accepting connection from %s." % (addr[0]))
    send(conn, "Welcome to PiPlay!", False)
    send_help(conn)
    send(conn)

    global player, queue
    m = alsaaudio.Mixer()
    
    while True:
        try:
            cmd = str(conn.recv(1024).strip())
            cmd = cmd[2:-1] # get rid of bytes identifier (screw python 3)
            if "play " in cmd:
                # play music
                args = cmd.split(" ")
                if len(args) != 2:
                    send(conn, "Invalid syntax.", False)
                    continue

                # obtain url
                url = args[1]
                # if queue is empty or nothing is playing, play now, otherwise queue it
                if len(queue) == 0 and player.playtime_remaining is None:
                        play(conn, url)
                else:
                    queue.append(url)
                    send(conn, "Video added to queue.", False)

            elif "playnow " in cmd:
                args = cmd.split(" ")
                if len(args) != 2:
                    send(conn, "Invalid syntax.", False)
                    continue
                
                # stop whatever is currently playing and play
                url = args[1]
                player.play(conn, url)

            elif cmd == "skip":
                # skips current song
                elif len(queue) < 1:
                    send(conn, "Queue is empty, nothing to skip to.")
                else:
                    print("Skipping to next song.")
                    play(conn, queue.pop(0))

            elif cmd == "queue":
                # list songs in queue
                if len(queue) == 0:
                    send(conn, "Queue is empty.", False)
                else:
                    i = 1
                    for url in queue:
                        link = etree.HTML(urllib.request.urlopen(url).read())
                        title = link.xpath("//span[@id='eow-title']/@title")
                        conn.sendall(("%d. %s\n" % (i, ''.join(title))).encode())
                        i += 1
                    send(conn)

            elif "vol " in cmd:
                # change volume
                args = cmd.split(" ")
                if len(args) != 2:
                    send(conn, "Invalid syntax.", False)
                    continue

                try:
                    new_vol = int(args[1])
                    if new_vol < 0 or new_vol > 100:
                        send(conn, "Invalid syntax.", False)
                    vol = m.getvolume()
                    m.setvolume(new_vol)
                    send(conn, "Volume was set to %d." % (new_vol), False)
                except ValueError:
                    send(conn, "Invalid syntax.", False)

            elif cmd == "help":
                # show help
                send_help(conn)
                send(conn)

            elif cmd == "exit":
                conn.close()

            else:
                send(conn, "Invalid command entered.", False)

        except socket.error as e:
            if "Broken pipe" in str(e):
                print("Connection from %s was forcibly closed by the client." % (addr[0]))
            break

def init_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, PORT))
    s.listen(100)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return s

def run():
    global player, connections
    player = mpv.MPV(ytdl=True)

    s = init_server()
    t = threading.Thread(target=cycle_queue)
    t.start()
    print("PiPlay server v%s initialized." % (VERSION))

    while True:
        try:
            (conn, addr) = s.accept()
            connections.append(conn)
            t = threading.Thread(target=handle_server, args=(conn, addr))
            t.start()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(e)  

run()
