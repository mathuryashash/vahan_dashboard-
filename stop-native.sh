#!/bin/bash
cd "$(dirname "$0")"

# Kills by port, not by the pid setup-native.sh recorded from `$!` -- on
# Windows, `nohup <cmd> & ; echo $!` through an activated venv captures an
# intermediate wrapper's pid, not the real long-running server process
# (confirmed by hand: the recorded pid didn't match what `netstat` showed
# actually bound to the port, and killing it left the real server running).
# Whatever is actually listening on the port is authoritative regardless of
# how it got spawned. Caveat: this kills WHATEVER is on 8020/3000, not
# specifically this app's processes -- if something unrelated happens to be
# using the same port on your machine, this stops that too (hit exactly
# this while testing, against an unrelated background service someone else
# had running on port 3000).
kill_port() {
  port="$1"
  if command -v taskkill >/dev/null 2>&1; then
    pid=$(netstat -ano 2>/dev/null | grep -E "[:.]$port[[:space:]]" | grep LISTENING | awk '{print $NF}' | sort -u | head -1)
    [ -n "$pid" ] && taskkill //F //T //PID "$pid" >/dev/null 2>&1 && echo "Stopped process on port $port (pid $pid)" || echo "Nothing listening on port $port"
  else
    pid=$(lsof -ti tcp:"$port" 2>/dev/null | head -1)
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null && echo "Stopped process on port $port (pid $pid)" || echo "Nothing listening on port $port"
  fi
}

kill_port 8020
kill_port 3000
rm -f backend.pid frontend.pid
