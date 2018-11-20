
set -x

CHROOT="/mnt/cloud_root"
ROOT_DEV="/dev/xvdf"
SRC="/tmp/src"

yum -d 1 install -y MAKEDEV
yum -d 1 install -y patch

#parted -s $ROOT_DEV mktable gpt mkpart primary ext4 2048s 100%
parted -s $ROOT_DEV mklabel gpt
#parted -s -a optimal $ROOT_DEV -- mkpart bbp 1MB 2MB
#parted -s $ROOT_DEV -- set 1 bios_grub on
parted -s -a optimal $ROOT_DEV -- mkpart root ext4 1MB 100%
mkfs.ext4 "${ROOT_DEV}1"
/sbin/e2label "${ROOT_DEV}1" root
mkdir -p $CHROOT
mount "${ROOT_DEV}1" $CHROOT
mkdir $CHROOT/dev $CHROOT/proc $CHROOT/etc $CHROOT/boot $CHROOT/sys
mount -t sysfs sys $CHROOT/sys
mount -t proc proc $CHROOT/proc
for i in console null zero random urandom; do /sbin/MAKEDEV -d $CHROOT/dev -x $i; done

echo "search srv.releng.use1.mozilla.com" >> /etc/resolv.conf

cp $SRC/etc/yum-local.cfg $CHROOT/etc/yum-local.cfg
yum -d 1 -c $CHROOT/etc/yum-local.cfg -y --installroot=$CHROOT groupinstall Core Base
yum -d 1 -c $CHROOT/etc/yum-local.cfg -y --installroot=$CHROOT clean packages

chroot $CHROOT rpmdb --rebuilddb
rsync $SRC/boot $SRC/etc $CHROOT -av

ln -s grub.conf $CHROOT/boot/grub/menu.lst
ln -s ../boot/grub/grub.conf $CHROOT/boot/grub.conf

sed -i s/@VERSION@/`chroot $CHROOT rpm -q --queryformat "%{version}-%{release}.%{arch}" kernel |tail -n1`/g $CHROOT/boot/grub/grub.conf

patch -p0 -i $SRC/grub-install.diff /sbin/grub-install
/sbin/grub-install --root-directory=$CHROOT --no-floppy $ROOT_DEV

sed -i -e '/PermitRootLogin/d' -e '/UseDNS/d' -e '$ a PermitRootLogin without-password' -e '$ a UseDNS no' $CHROOT/etc/ssh/sshd_config

umount $CHROOT/boot || :
umount $CHROOT/sys || :
umount $CHROOT/proc || :
umount $CHROOT


exit 0
