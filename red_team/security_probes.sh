#!/bin/bash
# Safe Container Isolation & Attack-Surface Probe Suite
HOST_KERNEL="${1:-unknown}"
BLOCKED=0
TOTAL=8

record() {
    local name="$1"
    local status="$2"
    local detail="$3"
    echo "${name},${status},${detail}"
    if [ "$status" = "BLOCKED" ]; then
        BLOCKED=$((BLOCKED + 1))
    fi
}

# 1. Host Kernel Version Masking
CUR_KERNEL=$(uname -r)
if [ "$CUR_KERNEL" = "$HOST_KERNEL" ]; then
    record "P1_KERNEL_MASK" "EXPOSED" "$CUR_KERNEL"
else
    record "P1_KERNEL_MASK" "BLOCKED" "$CUR_KERNEL"
fi

# 2. Host Kernel Modules Leak (/proc/modules)
if [ -r /proc/modules ] && [ -s /proc/modules ]; then
    MOD_COUNT=$(wc -l < /proc/modules)
    record "P2_PROC_MODULES" "EXPOSED" "${MOD_COUNT}_modules_visible"
else
    record "P2_PROC_MODULES" "BLOCKED" "hidden_or_empty"
fi

# 3. Kernel Ring Buffer Access (dmesg)
DMESG_OUT=$(dmesg 2>/dev/null)
if [ $? -eq 0 ] && ! echo "$DMESG_OUT" | grep -qi "gVisor"; then
    record "P3_DMESG_LOG" "EXPOSED" "readable"
else
    record "P3_DMESG_LOG" "BLOCKED" "permission_denied"
fi

# 4. Root User-Namespace Isolation (/proc/self/uid_map)
UID_MAP=$(tr -s ' ' < /proc/self/uid_map 2>/dev/null | head -n 1 | xargs)
if echo "$CUR_KERNEL" | grep -qi "gvisor"; then
    record "P4_USERNS_ISOLATION" "BLOCKED" "gvisor_sentry_kernel"
elif [ "$UID_MAP" = "0 0 4294967295" ]; then
    record "P4_USERNS_ISOLATION" "EXPOSED" "direct_host_uid0"
else
    record "P4_USERNS_ISOLATION" "BLOCKED" "remapped_${UID_MAP// /_}"
fi

# 5. CAP_NET_RAW Capability Check + Total Effective Capabilities
CAP_HEX=$(awk '/^CapEff:/ {print $2}' /proc/self/status 2>/dev/null)
CAP_DEC=$((16#${CAP_HEX:-0}))
CAP_COUNT=0
TMP=$CAP_DEC
while (( TMP > 0 )); do
    (( CAP_COUNT += TMP & 1 ))
    (( TMP >>= 1 ))
done
if (( (CAP_DEC & 0x2000) != 0 )); then
    record "P5_CAP_NET_RAW" "EXPOSED" "enabled_total_caps_${CAP_COUNT}"
else
    record "P5_CAP_NET_RAW" "BLOCKED" "dropped_total_caps_${CAP_COUNT}"
fi

# 6. Syscall: mount (filesystem mount attempt)
mkdir -p /tmp/probe_mnt
if mount -t tmpfs tmpfs /tmp/probe_mnt 2>/dev/null; then
    umount /tmp/probe_mnt 2>/dev/null
    record "P6_SYSCALL_MOUNT" "EXPOSED" "mount_succeeded"
else
    record "P6_SYSCALL_MOUNT" "BLOCKED" "mount_denied"
fi
rmdir /tmp/probe_mnt 2>/dev/null

# 7. Syscall: unshare (nested mount namespace escape attempt)
if unshare -m true 2>/dev/null; then
    record "P7_SYSCALL_UNSHARE" "EXPOSED" "unshare_succeeded"
else
    record "P7_SYSCALL_UNSHARE" "BLOCKED" "unshare_denied"
fi

# 8. Syscall: mknod (character device creation attempt)
rm -f /tmp/probe_dev
if mknod /tmp/probe_dev c 1 3 2>/dev/null; then
    rm -f /tmp/probe_dev
    record "P8_SYSCALL_MKNOD" "EXPOSED" "mknod_succeeded"
else
    record "P8_SYSCALL_MKNOD" "BLOCKED" "mknod_denied"
fi

echo "SUMMARY,SCORE=${BLOCKED}/${TOTAL},CAP_COUNT=${CAP_COUNT}"
