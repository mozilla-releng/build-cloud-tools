PREFIX=$1

for ROOT in /proc/*/root; do
    LINK=$(readlink $ROOT)
    if [ "x$LINK" != "x" ]; then
        if [ "x${LINK:0:${#PREFIX}}" = "x$PREFIX" ]; then
            # this process is in the chroot...
            PID=$(basename $(dirname "$ROOT"))
            kill "$PID"
            kill -9 "$PID"
        fi
    fi
done
