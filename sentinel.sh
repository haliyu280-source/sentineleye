#!/bin/bash

# Output format: text or json
OUTPUT_FORMAT=${OUTPUT_FORMAT:-text}
if [ "$OUTPUT_FORMAT" = "json" ]; then
    exec 3>&1 1>/dev/null
fi

# SentinelEye - A sharper eye on your infrastructure.
# Collects basic system health information.

# Overall health status
overall_status=0

# Monitoring data variables

disk_usage="null"
cpu_usage="null"
memory_total_mb="null"

echo "================================="
echo "    SENTINELEYE HEALTH CHECK"
echo "================================="
echo ""

echo "Date and time:"
date
echo ""

echo "Operating system:"
uname -s
echo ""

echo "System uptime:"
uptime
echo ""

# -------------------------------
# DISK HEALTH CHECK
# -------------------------------

echo "Disk health check:"

if ! disk_output=$(df -P /); then
    echo "ERROR: Unable to retrieve disk usage."
    disk_status=1
else
    disk_usage=$(printf '%s\n' "$disk_output" | awk 'NR==2 {gsub("%","",$5); print $5}')   
 disk_threshold=${DISK_THRESHOLD:-80}

    if ! [[ "$disk_usage" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Could not read a valid disk-usage percentage."
        disk_status=1
    elif ! [[ "$disk_threshold" =~ ^[0-9]+$ ]]; then
        echo "ERROR: DISK_THRESHOLD must be a whole number."
        disk_status=1
    elif [ "$disk_threshold" -gt 100 ]; then
        echo "ERROR: DISK_THRESHOLD cannot exceed 100."
        disk_status=1
    elif [ "$disk_usage" -ge "$disk_threshold" ]; then
        echo "WARNING: Disk usage is ${disk_usage}%"
        disk_status=1
    else
        echo "OK: Disk usage is ${disk_usage}%"
        disk_status=0
    fi
fi

echo ""
echo "Disk usage for root filesystem:"
df -h /
echo ""

# -------------------------------
# MEMORY INFORMATION
# -------------------------------

echo "Memory information:"

if [ "$(uname -s)" = "Darwin" ]; then
    memory_bytes=$(sysctl -n hw.memsize)
    echo "Total physical memory: $((memory_bytes / 1024 / 1024)) MB"
memory_total_mb=$((memory_bytes / 1024 / 1024))

else
    free -h
fi

echo ""


# -------------------------------
# CPU HEALTH CHECK
# -------------------------------

echo "CPU health check:"

cpu_status=0
cpu_threshold=${CPU_THRESHOLD:-80}

# Validate CPU threshold
if ! [[ "$cpu_threshold" =~ ^[0-9]+$ ]]; then
    echo "ERROR: CPU_THRESHOLD must be a whole number."
    cpu_status=1
elif [ "$cpu_threshold" -gt 100 ]; then
    echo "ERROR: CPU_THRESHOLD cannot exceed 100."
    cpu_status=1

# macOS CPU monitoring
elif [ "$(uname -s)" = "Darwin" ]; then

    cpu_output=$(top -l 2 -n 0 | grep "CPU usage" | tail -n 1)
    cpu_idle=$(printf '%s\n' "$cpu_output" | awk '{gsub("%","",$7); print $7}')

    if ! [[ "$cpu_idle" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        echo "ERROR: Could not read a valid CPU idle percentage."
        cpu_status=1
    else
        cpu_usage=$(awk -v idle="$cpu_idle" 'BEGIN {printf "%.2f", 100-idle}')

        if awk -v usage="$cpu_usage" -v threshold="$cpu_threshold" 'BEGIN {exit !(usage >= threshold)}'; then
            echo "WARNING: CPU usage is ${cpu_usage}%"
            cpu_status=1
        else
            echo "OK: CPU usage is ${cpu_usage}%"
        fi
    fi

# Linux CPU monitoring
elif [ "$(uname -s)" = "Linux" ]; then

    if [ ! -r /proc/stat ]; then
        echo "ERROR: Cannot read Linux CPU statistics."
        cpu_status=1
    else
        # First CPU reading
        cpu_stats_before=$(awk '/^cpu / {
            idle = $5 + $6
            total = 0
            for (i = 2; i <= NF; i++) total += $i
            printf "%.0f %.0f", idle, total
            exit
        }' /proc/stat)

        sleep 1

        # Second CPU reading
        cpu_stats_after=$(awk '/^cpu / {
            idle = $5 + $6
            total = 0
            for (i = 2; i <= NF; i++) total += $i
            printf "%.0f %.0f", idle, total
            exit
        }' /proc/stat)

        cpu_idle_before=$(printf '%s\n' "$cpu_stats_before" | awk '{print $1}')
        cpu_total_before=$(printf '%s\n' "$cpu_stats_before" | awk '{print $2}')

        cpu_idle_after=$(printf '%s\n' "$cpu_stats_after" | awk '{print $1}')
        cpu_total_after=$(printf '%s\n' "$cpu_stats_after" | awk '{print $2}')

        if ! [[ "$cpu_idle_before" =~ ^[0-9]+$ ]] || \
           ! [[ "$cpu_total_before" =~ ^[0-9]+$ ]] || \
           ! [[ "$cpu_idle_after" =~ ^[0-9]+$ ]] || \
           ! [[ "$cpu_total_after" =~ ^[0-9]+$ ]]; then

            echo "ERROR: Could not read valid Linux CPU statistics."
            cpu_status=1

        else
            idle_difference=$((cpu_idle_after - cpu_idle_before))
            total_difference=$((cpu_total_after - cpu_total_before))

            if [ "$total_difference" -le 0 ] || [ "$idle_difference" -lt 0 ]; then
                echo "ERROR: Invalid Linux CPU measurement."
                cpu_status=1
            else
                cpu_usage=$(awk -v idle="$idle_difference" -v total="$total_difference" \
                    'BEGIN {printf "%.2f", (1-idle/total)*100}')

                if awk -v usage="$cpu_usage" -v threshold="$cpu_threshold" \
                    'BEGIN {exit !(usage >= threshold)}'; then
                    echo "WARNING: CPU usage is ${cpu_usage}%"
                    cpu_status=1
                else
                    echo "OK: CPU usage is ${cpu_usage}%"
                fi
            fi
        fi
    fi

else
    echo "ERROR: CPU monitoring is not supported on this operating system."
    cpu_status=1
fi

echo ""

# -------------------------------
# TOP PROCESSES
# -------------------------------

echo "Top processes by CPU usage:"
ps aux | head -n 6

echo ""
echo "================================="
echo "         CHECK COMPLETE"
echo "================================="

# -------------------------------
# FINAL HEALTH STATUS
# -------------------------------

if [ "$disk_status" -ne 0 ] || [ "$cpu_status" -ne 0 ]; then
    overall_status=1
fi

if [ "$OUTPUT_FORMAT" = "json" ]; then
    exec 1>&3 3>&-
    if [ "$overall_status" -eq 0 ]; then
        health_status="healthy"
    else
        health_status="warning"
    fi

    printf '{\n'
    printf '  "operating_system": "%s",\n' "$(uname -s)"
    printf '  "disk_usage": %s,\n' "$disk_usage"
    printf '  "cpu_usage": %s,\n' "$cpu_usage"
    printf '  "memory_total_mb": %s,\n' "$memory_total_mb"
    printf '  "status": "%s"\n' "$health_status"
    printf '}\n'
fi

exit "$overall_status"

