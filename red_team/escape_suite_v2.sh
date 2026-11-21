#!/bin/bash
HOST_KERNEL="${1:-unknown}"
BLOCKED=0
TOTAL=15

record() {
    local name="$1"
    local status="$2"
    local detail="$3"
    echo "${name},${status},${detail}"
    if [ "$status" = "BLOCKED" ]; then
        BLOCKED=$((BLOCKED + 1))
    fi
}

CUR_KERNEL=$(uname -r)
if [ "$CUR_KERNEL" = "$HOST_KERNEL" ]; then
    record "P01_KERNEL_MASK" "EXPOSED" "$CUR_KERNEL"
else
    record "P01_KERNEL_MASK" "BLOCKED" "$CUR_KERNEL"
fi

if [ -r /proc/modules ] && [ -s /proc/modules ]; then
    record "P02_PROC_MODULES" "EXPOSED" "$(wc -l < /proc/modules)_modules"
else
    record "P02_PROC_MODULES" "BLOCKED" "hidden_or_empty"
fi

DMESG_OUT=$(dmesg 2>/dev/null)
if [ $? -eq 0 ] && ! echo "$DMESG_OUT" | grep -qi "gVisor"; then
    record "P03_DMESG_LOG" "EXPOSED" "readable"
else
    record "P03_DMESG_LOG" "BLOCKED" "denied_or_synthetic"
fi

UID_MAP=$(tr -s ' ' < /proc/self/uid_map 2>/dev/null | head -n 1 | xargs)
if echo "$CUR_KERNEL" | grep -qi "gvisor"; then
    record "P04_USERNS_ISOLATION" "BLOCKED" "gvisor_sentry"
elif [ "$UID_MAP" = "0 0 4294967295" ]; then
    record "P04_USERNS_ISOLATION" "EXPOSED" "direct_host_uid0"
else
    record "P04_USERNS_ISOLATION" "BLOCKED" "remapped_${UID_MAP// /_}"
fi

CAP_HEX=$(awk '/^CapEff:/ {print $2}' /proc/self/status 2>/dev/null)
CAP_DEC=$((16#${CAP_HEX:-0}))
CAP_COUNT=0
TMP=$CAP_DEC
while (( TMP > 0 )); do
    (( CAP_COUNT += TMP & 1 ))
    (( TMP >>= 1 ))
done

IFS=, read -r st dt <<< "$(/red_team/escape_helper sock_raw)"
record "P05_SOCK_RAW_ICMP" "$st" "${dt}_caps_${CAP_COUNT}"

mkdir -p /tmp/probe_mnt
if mount -t tmpfs tmpfs /tmp/probe_mnt 2>/dev/null; then
    umount /tmp/probe_mnt 2>/dev/null
    record "P06_SYSCALL_MOUNT" "EXPOSED" "mount_succeeded"
else
    record "P06_SYSCALL_MOUNT" "BLOCKED" "mount_denied"
fi
rmdir /tmp/probe_mnt 2>/dev/null

if unshare -m true 2>/dev/null; then
    record "P07_SYSCALL_UNSHARE" "EXPOSED" "unshare_succeeded"
else
    record "P07_SYSCALL_UNSHARE" "BLOCKED" "unshare_denied"
fi

rm -f /tmp/probe_dev
if mknod /tmp/probe_dev c 1 3 2>/dev/null; then
    rm -f /tmp/probe_dev
    record "P08_SYSCALL_MKNOD" "EXPOSED" "mknod_succeeded"
else
    record "P08_SYSCALL_MKNOD" "BLOCKED" "mknod_denied"
fi

IFS=, read -r st dt <<< "$(/red_team/escape_helper ptrace)"
record "P09_SYSCALL_PTRACE" "$st" "$dt"

IFS=, read -r st dt <<< "$(/red_team/escape_helper bpf)"
record "P10_SYSCALL_BPF" "$st" "$dt"

IFS=, read -r st dt <<< "$(/red_team/escape_helper setns)"
record "P11_SYSCALL_SETNS" "$st" "$dt"

IFS=, read -r st dt <<< "$(/red_team/escape_helper chroot)"
record "P12_SYSCALL_CHROOT" "$st" "$dt"

IFS=, read -r st dt <<< "$(/red_team/escape_helper keyctl)"
record "P13_SYSCALL_KEYCTL" "$st" "$dt"

if [ -w /proc/sysrq-trigger ] 2>/dev/null || touch /sys/probe_write_test 2>/dev/null; then
    rm -f /sys/probe_write_test 2>/dev/null
    record "P14_PROC_SYS_WRITABLE" "EXPOSED" "writable_proc_or_sys"
else
    record "P14_PROC_SYS_WRITABLE" "BLOCKED" "read_only_masked"
fi

if [ -e /host_canary/host_secret.txt ]; then
    if grep -q "HOST_CANARY_SECRET" /host_canary/host_secret.txt 2>/dev/null; then
        record "P15_BIND_CANARY_ROOT" "EXPOSED" "read_host_root_0600_file"
    else
        record "P15_BIND_CANARY_ROOT" "BLOCKED" "permission_denied_uid_isolated"
    fi
else
    record "P15_BIND_CANARY_ROOT" "SKIPPED" "canary_not_mounted"
fi

echo "SUMMARY,SCORE=${BLOCKED}/${TOTAL},CAP_COUNT=${CAP_COUNT}"