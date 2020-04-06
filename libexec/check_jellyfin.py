#!/usr/bin/env python2

import json
import optparse
import os
import sys
import time
import urllib2
import ssl
from datetime import date
import datetime

VERSION = "0.1"

OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3

GREEN = '#2A9A3D'
RED = '#FF0000'
ORANGE = '#f57700'
GRAY = '#f57700'

parser = optparse.OptionParser("%prog [options]", version="%prog " + VERSION)
parser.add_option('-H', '--hostname', dest="hostname", help='Hostname to connect to')
parser.add_option('-p', '--port', dest="port", type="int", default=80, help='Jellyfin port (default: 80)')
parser.add_option('-S', '--use-ssl', dest="https", type="int", default=0,  help='Use SSL')
parser.add_option('-k', '--api-key', dest="api_key", default="",  help='Jellyfin API key')

perfdata = []
output = ""

def add_perfdata(name, value, min="", max="", warning="", critical=""):
    global perfdata
    perfdata.append("\"%s\"=%s;%s;%s;%s;%s" % (name.replace(" ", "_"), value, min, max, warning, critical))

def exit(status, exit_label=""):
    global perfdata
    global output

    label = exit_label
    color = GRAY

    if status == OK:
        if not label:
            label = "OK"
        color = GREEN
    elif status == WARNING:
        if not label:
            label = "WARNING"
        color = ORANGE
    elif status == CRITICAL:
        if not label:
            label = "CRITICAL"
        color = RED
    else:
        if not label:
            label = "UNKNOWN"
        color = GRAY

    print "<span style=\"color:%s;font-weight: bold;\">[%s]</span> %s | %s" % (color, label, output, " ".join(perfdata))
    sys.exit(status)


def api_call(hostname, port, https, token, path):
    global output

    if https == 1:
        host = "https://%s:%d" % (hostname, port)
    else:
        host = "http://%s:%d" % (hostname, port)

    url = "%s/emby%s" % (host, "%s" % (path))
    # print url
    # print token

    try:
        start = time.time()
        req = urllib2.urlopen(urllib2.Request(url=url, headers = {
            'Accept': 'application/json',
            'X-Emby-Token': token,
            }), context=ssl._create_unverified_context())
        end = time.time()

        data = req.read()
        return end - start, data
    except urllib2.URLError as e:
        output += "Could not contact jellyfin: %s" % e
        exit(CRITICAL)

def get_section(hostname, port, https, token, section_id):
    resp_time, data = api_call(hostname, port, https, token, "/library/sections/%s/all" % section_id)
    # resp_time, data = api_call(hostname, port, https, token, "" % section_id)
    return json.loads(data)

def get_item_counts(hostname, port, https, token):
    resp_time, data = api_call(hostname, port, https, token, "/Items/Counts")
    sections = json.loads(data)
    counts = {
            "movies": sections.get("MovieCount", 0),
            "shows": sections.get("SeriesCount", 0),
            "episodes": sections.get("EpisodeCount", 0),
            "collections": sections.get("BoxSetCount", 0),
            }

    return counts

def get_sessions(hostname, port, https, token):
    resp_time, data = api_call(hostname, port, https, token, "/Sessions")
    sessions = json.loads(data)

    formatted_session_info = [{
        "play_method": session.get("PlayState").get("PlayMethod"),
        "client": session.get("Client"),
        "device_name": session.get("DeviceName"),
        "active": session.get("NowPlayingItem") is not None,
        "item_name": session.get("NowPlayingItem", {}).get("OriginalTitle")
        } for session in sessions]

    return formatted_session_info

def get_duration_by_user(hostname, port, https, token, days):
    resp_time, data = api_call(hostname, port, https, token, "/user_usage_stats/UserId/BreakDownReport?days=%d&filter=Movie,Episode" % days)
    stats = json.loads(data)
    
    if not stats:
        return None

    durations = []
    for item in stats:
        durations.append({
            "user": item.get("label"),
            "duration": item.get("time"),
            })

    return durations

def get_duration_by_device(hostname, port, https, token, days):
    resp_time, data = api_call(hostname, port, https, token, "/user_usage_stats/DeviceName/BreakDownReport?days=%d&filter=Movie,Episode" % days)
    stats = json.loads(data)

    if not stats:
        return None

    durations = []
    for item in stats:
        durations.append({
            "device": item.get("label"),
            "duration": item.get("time"),
            })

    return durations

def get_duration_by_platform(hostname, port, https, token, days):
    resp_time, data = api_call(hostname, port, https, token, "/user_usage_stats/ClientName/BreakDownReport?days=%d&filter=Movie,Episode" % days)
    stats = json.loads(data)

    if not stats:
        return None

    durations = []
    for item in stats:
        durations.append({
            "client": item.get("label"),
            "duration": item.get("time"),
            })

    return durations

def get_users(hostname, port, https, token):
    resp_time, data = api_call(hostname, port, https, token, "/Users")
    users = json.loads(data)

    return users

def get_play_stats(hostname, port, https, token, days):
    resp_time, data = api_call(hostname, port, https, token, "/user_usage_stats/UserId/BreakDownReport?days=7&filter=Movie,Episode")
    stats = json.loads(data)

    play_durations_by_users = get_duration_by_user(hostname, port, https, token, days)
    play_durations_by_device = get_duration_by_device(hostname, port, https, token, days)
    play_durations_by_platform = get_duration_by_platform(hostname, port, https, token, days)

    return play_durations_by_users, play_durations_by_device, play_durations_by_platform

def add_stats_perfdata(hostname, port, https, token, label, days):
    by_user, by_device, by_platform = get_play_stats(hostname, port, https, token, days)
    if by_user:
        for s in by_user:
            user = s.get("user").split("@")[0]
            add_perfdata("play_by_user_%s_%s" % (label, user), s.get("duration"))

    if by_device:
        for d in by_device:
            device = d.get("device")
            add_perfdata("play_by_device_%s_%s" % (label, device), d.get("duration"))

    if by_platform:
        for p in by_platform:
            client_name = p.get("client")
            add_perfdata("play_by_platform_%s_%s" % (label, client_name), p.get("duration"))


def get_hourly_play_time(hostname, port, https, token):
    resp_time, data = api_call(hostname, port, https, token, "/user_usage_stats/HourlyReport?days=1&filter=Movie,Episode")
    stats = json.loads(data)

    current_date = date.today()
    day_number = current_date.isoweekday()
    hours = datetime.datetime.now().hour
    selector = "%d-%02d" % (day_number, hours)

    return stats.get(selector)


def get_stats(hostname, port, https, token):
    global output

    resp_time, system_info = api_call(hostname, port, https, token, "/System/Info")
    counts = get_item_counts(hostname, port, https, token)
    add_perfdata("movie_count", counts["movies"])
    add_perfdata("shows_count", counts["shows"])
    add_perfdata("episodes_count", counts["episodes"])

    sessions = get_sessions(hostname, port, https, token)
    inactive_sessions_counter = len([ s for s in sessions if not s.get("active") ])
    active_sessions_counter = len([ s for s in sessions if s.get("active") ])
    transcode_sessions = len([ s for s in sessions if s.get("play_method") == "Transcode" ])
    directplay_sessions = len([ s for s in sessions if s.get("play_method") == "DirectPlay" ])
    directstream_sessions = len([ s for s in sessions if s.get("play_method") == "DirectStream" ])

    add_perfdata("session_total", active_sessions_counter + inactive_sessions_counter)
    add_perfdata("session_active", active_sessions_counter)
    add_perfdata("session_inactive", inactive_sessions_counter)
    add_perfdata("transcode_sessions", transcode_sessions)
    add_perfdata("directplay_sessions", directplay_sessions)
    add_perfdata("directstream_sessions", directstream_sessions)

    add_perfdata("response_time", resp_time)


    users = get_users(hostname, port, https, token)
    add_perfdata("user_count", len(users))

    # Play stats for last hour
    # add_stats_perfdata(hostname, port, https, token, "hour", int(time.time()) - 60*60)
    hour_play_time = get_hourly_play_time(hostname, port, https, token)
    if hour_play_time is not None:
        add_perfdata("current_hour_playtime", hour_play_time)

    # Play stats for today
    add_stats_perfdata(hostname, port, https, token, "today", 1)
    # Play stats for the last week
    add_stats_perfdata(hostname, port, https, token, "week", 7)
    # Play stats for the all time
    add_stats_perfdata(hostname, port, https, token, "year", 365)

    output = "Jellyfin stats collected"
    exit(OK)

if __name__ == '__main__':
    # Ok first job : parse args
    opts, args = parser.parse_args()
    if args:
        parser.error("Does not accept any argument.")

    port = opts.port
    hostname = opts.hostname
    token = opts.api_key
    if not hostname:
        # print "<span style=\"color:#A9A9A9;font-weight: bold;\">[ERROR]</span> Hostname parameter (-H) is mandatory"
        output = "Hostname parameter (-H) is mandatory"
        exit(CRITICAL, "ERROR")

    if not token:
        # print "<span style=\"color:#A9A9A9;font-weight: bold;\">[ERROR]</span> Hostname parameter (-H) is mandatory"
        output = "Token parameter (-t) is mandatory"
        exit(CRITICAL, "ERROR")

    get_stats(hostname, port, opts.https, token)
