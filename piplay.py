#!/usr/bin/env python
import alsaaudio
import pafy
import requests
import socket
import threading
import time
import vlc

# TODO
# volume improvements
# skip should be able to skip to autoplay if nothing in queue
# add a stop command to stop whatever is currently playing
# autoplay needs to be worked on so it doesn't repeat, currently repeats after a few songs
# running the skip command breaks the queue for some reason, look into this

HOST = "0.0.0.0"
PORT = 2727

CMDLET = "---> "

vlc_instance = ""
player = ""
queue = []
autoplay = ""
connections = []
active_timer = ""

def send(conn, msg="", cmdlet=True):
    if not cmdlet:
        conn.sendall("%s\n" % (msg))
        if "Welcome" not in msg:
            send(conn)
    else:
        conn.sendall("\n%s" % (CMDLET))

def send_help(conn):
    HELPMSG = """The following commands exist:
    \tplay <YouTube URL>\t- Adds a song to the queue.
    \tplaynow <YouTube URL>\t- Stops the current song and plays the requested URL.
    \tskip\t\t\t- Skips the current song and moves to the next one.
    \tqueue\t\t\t- Shows the current song queue.
    \tvol <0-100>\t\t- Sets the volume level.
    \thelp\t\t\t- Shows this help message.
    \texit\t\t\t- Exits this PiPlay connection.\n"""
    conn.sendall(HELPMSG)

def grab_autoplay(conn, url):
    global autoplay
    html = requests.get(url).text

    # pull the URL from youtube's autoplay "up next" feature
    html = html[html.index("Up next"):]
    html = html[html.index("href"):html.index("href")+100]
    url = "https://www.youtube.com%s" % (html.split('"')[1])

    vid = pafy.new(url)
    autoplay = vid

def play(conn, vid):
    global vlc_instance, player, connections, active_timer
    try:
        # load url to stream in VLC
        stream = vid.getbest(preftype="webm")
        media = ""
        if stream is None:
            media = vlc_instance.media_new(vid.getbest().url)
        else:
            media = vlc_instance.media_new(stream.url)
        media.get_mrl()
        player.set_media(media)
        player.play()
        player.set_fullscreen(True)

        # keep track of when songs were started so that a playlist will only run for 6 minutes before moving on in the queue
        active_timer = time.time()

        # if there's nothing in the queue to play after this song, grab the autoplay up next from youtube
        if len(queue) == 0:
            grab_autoplay(conn, vid.watchv_url)
        for c in connections:
            send(c, "\nNow playing %s\nLength: %s" % (vid.title, vid.duration), False)
    except ValueError:
        if conn is not None:
            send(conn, "Invalid URL entered.", False)

def cycle_queue():
    global player, queue, autoplay, active_timer

    # loop every 7 seconds checking queue
    while True:
        time.sleep(7)
        # if no song is playing and there is something in the queue, play it
        if player.is_playing() == 0 or (time.time() - active_timer > 360):
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

    global queue, player
    m = alsaaudio.Mixer()
    
    while True:
        try:
            cmd = conn.recv(1024).strip()

            if "play " in cmd:
                # play music
                args = cmd.split(" ")
                if len(args) != 2:
                    send(conn, "Invalid syntax.", False)
                    continue

                # obtain url
                url = args[1]
                try:
                    vid = pafy.new(url)
                    # if queue is empty and player is off, play
                    if len(queue) == 0 and player.is_playing() == 0:
                        play(conn, vid)
                    else:
                        # songs are queued or currently playing, add to queue
                        queue.append(vid)
                        send(conn, "Video added to queue.", False)
                except ValueError as e:
                    send(conn, "Invalid URL entered: %s" % (url), False)

            elif "playnow " in cmd:
                # stop and play
                if player.is_playing() == 0:
                    send(conn, "Player isn't currently playing anything. Try 'play <url>'.", False)
                else:
                    args = cmd.split(" ")
                    if len(args) != 2:
                        send(conn, "Invalid syntax.", False)
                        continue
                    
                    # obtain url
                    url = args[1]
                    vid = pafy.new(url)

                    play(conn, vid)

            elif cmd == "skip":
                # skips current song
                if player.is_playing() == 0:
                    send(conn, "Player isn't currently playing anything.")
                elif len(queue) > 0:
                    play(conn, queue.pop(0))
                else:
                    send(conn, "Queue is empty, nothing to skip to.")

            elif cmd == "queue":
                # list songs in queue
                if len(queue) == 0:
                    send(conn, "Queue is empty.", False)
                else:
                    i = 1
                    for vid in queue:
                        conn.sendall("%d. %s (%s)\n" % (i, vid.title, vid.duration))
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

        except socket.error, e:
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
    global vlc_instance, player, connections
    vlc_instance = vlc.Instance()
    player = vlc_instance.media_player_new()

    s = init_server()
    t = threading.Thread(target=cycle_queue)
    t.start()
    print("PiPlay server initialized.")

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