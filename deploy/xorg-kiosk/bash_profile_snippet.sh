
# Chatterbox kiosk: auto-start the GUI on a real console login at tty1 (plain-Xorg fallback --
# see deploy/xorg-kiosk/README.md for why cage/wlroots isn't used here).
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -keeptty
fi
