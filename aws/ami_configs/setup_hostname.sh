#! /bin/bash

if [ -e "/etc/setup_hostname.done" ]; then
    logger --stderr -t setup_hostname "Skipping $0"
    exit 0
fi

ATTEMPTS=10
FAILED=0
while [ ! -f /root/userdata ]; do
    curl -f http://169.254.169.254/latest/user-data > /root/userdata.tmp 2>/dev/null
    if [ $? -eq 0 ]; then
        mv -f /root/userdata.tmp /root/userdata
        logger --stderr -t setup_hostname "Successfully retrieved user data"
    else
        FAILED=$(($FAILED + 1))
        if [ $FAILED -ge $ATTEMPTS ]; then
            logger --stderr -t setup_hostname "Failed to retrieve user data after $FAILED attempts, quitting"
            break
        fi
        logger --stderr -t setup_hostname "Could not retrieve user data (attempt #$FAILED/$ATTEMPTS), retrying in 5 seconds..."
        sleep 5
    fi
done

source /root/userdata
shred -u -n 7 -z /root/userdata || :

if [ -z "$FQDN" ]; then
    logger --stderr -t setup_hostname "Cannot set hostname, rebooting"
    sleep 60
    reboot
fi

echo "$FQDN" > /etc/hostname
hostname "$FQDN"
sed -i -e "s/127.0.0.1.*/127.0.0.1 $FQDN localhost/g" /etc/hosts
rm -f /builds/slave/buildbot.tac

touch /etc/setup_hostname.done

ATTEMPTS=10
FAILED=0
while ! puppet agent --test 2>&1 >> /root/puppetize.log; do
    FAILED=$(($FAILED + 1))
    if [ $FAILED -ge $ATTEMPTS ]; then
        logger --stderr -t setup_hostname "Failed to puppetize after $FAILED attempts, quitting"
        poweroff
    fi
    logger --stderr -t setup_hostname "Failed to puppetize (attempt #$FAILED/$ATTEMPTS), retrying in 5 seconds..."
    sleep 60
done
